"""OOB_Server: Out-of-band message server for GeoGebra frontend.

This module provides `OOB_Server`, a TCP-based local out-of-band
message server using asyncio. It accepts newline-delimited JSON messages
from local clients and supports `send`, `send_recv`, and `recv_queue`.
"""

import asyncio
import inspect
import functools
import json
import os
import queue
import socket as _socket
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, Optional
from collections import deque
import queue
from websockets.asyncio.server import serve, unix_serve


class OOB_Server:
    """Out-of-band message server.

    - Use `start()` / `stop()` to manage the background server thread.
    - `recv_queue` is an `asyncio.Queue` of incoming messages.
    - `send` / `send_recv` allow sending JSON-serializable messages.
    """

    # raw incoming message buffer for diagnostics (stores dicts: {ts, dir, raw})
    _raw_buffer = queue.Queue()

    def __init__(self, oob_timeout: float = 30.0, socket_path: Optional[str] = None):
        # server transport state
        # If caller provided a socket_path, use it. Otherwise proactively
        # reserve a transport depending on the platform so callers can
        # inspect `socket_path` or `ws_port` immediately after `start()`.
        # let IngestLoop perform socket reservation/setup
        self.socket_path: Optional[str] = socket_path
        # prebind port placeholder - IngestLoop may set this during its init
        # self._prebind_port = None
        self.ws_port: Optional[int] = None
        self.server_handle = None
        self.ingest_server = None
        self.serve_server = None
        self.server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # running asyncio loop for the background server thread
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # runtime state
        self.recv_queue: asyncio.Queue = asyncio.Queue()
        self.clients = set()
        self._client_lock = threading.Lock()
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self._pending_lock = threading.Lock()
        self.shared_objects: Dict[str, Any] = {}
        self.shared_listeners = []

        # sequence number and bounded change log for shared_objects updates
        self._seq = 0
        self._change_log = deque(maxlen=1000)
        self.oob_timeout = oob_timeout
        self.debug = False
        # prebind a separate serve port for client-facing API to reduce races
        self.serve_port: Optional[int] = None

        # create handler loop wrappers (defined below)
        self.ingest_loop = IngestLoop(self)
        self.observer_loop = ObserverLoop(self)

    def start(self):
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = threading.Event()

        self.server_thread = threading.Thread(
            target=lambda: asyncio.run(self._server()), daemon=True
        )
        self.server_thread.start()

    def stop(self):
        self._stop_event.set()
        # join server thread (allow background loop to observe _stop_event)
        if self.server_thread is not None:
            self.server_thread.join(timeout=1.0)

        # Close and await server handles on the background loop if possible
        for srv in (getattr(self, "ingest_server", None), getattr(self, "serve_server", None)):
            if srv is None:
                continue
            # synchronous close() if available
            close_fn = getattr(srv, "close", None)
            if callable(close_fn):
                close_fn()

            # schedule wait_closed() on background loop if available
            wait_closed = getattr(srv, "wait_closed", None)
            if callable(wait_closed) and getattr(self, "_loop", None) is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(wait_closed(), self._loop)
            elif callable(wait_closed):
                asyncio.run(wait_closed())

        # remove unix socket file if we used one
        sp = getattr(self, "socket_path", None)
        if sp and os.path.exists(sp):
            os.remove(sp)

    async def _server(self):
        loop = asyncio.get_running_loop()
        try:
            self._loop = loop
        except Exception:
            self._loop = None
        # Start two servers: ingest (receives OOB msgs from frontend) and
        # serve (client-facing API for snapshots/diffs and broadcasts).

        # Prepare ingest server (use unix socket on POSIX if socket_path present)
        ingest_server = None
        serve_server = None

        # Start ingest server using an async context (required by websockets)
        ingest_server = None
        serve_server = None
        try:
            async with self.ingest_loop.serve_context() as ingest_server:
                self._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": f"Starting ingest server"})

                # Start observer (client-facing) server inside the same context
                try:
                    serve_server = await self.observer_loop.start()
                except Exception:
                    serve_server = None
                if serve_server is not None:
                    self.serve_port = serve_server.sockets[0].getsockname()[1]
                    self.ws_port = self.serve_port
                else:
                    self.serve_port = None

                # store handles and run until stop
                self.ingest_server = ingest_server
                self.serve_server = serve_server
                await loop.run_in_executor(None, self._stop_event.wait)
        except Exception:
            # if context fails, ensure attributes remain set to None
            self.ingest_server = ingest_server
            self.serve_server = serve_server

    async def _handle_object_update(self, payload: Any):
        changes = {}
        if isinstance(payload, list) and payload and isinstance(payload[0], list):
            for pair in payload:
                if isinstance(pair, list) and len(pair) >= 2:
                    name, value = pair[0], pair[1]
                    self.shared_objects[name] = value
                    changes[name] = value
        elif isinstance(payload, list) and len(payload) >= 2 and not any(isinstance(i, list) for i in payload):
            name, value = payload[0], payload[1]
            self.shared_objects[name] = value
            changes[name] = value
        elif isinstance(payload, dict):
            if "name" in payload and "value" in payload:
                self.shared_objects[payload["name"]] = payload["value"]
                changes[payload["name"]] = payload["value"]
            else:
                for k, v in payload.items():
                    self.shared_objects[k] = v
                    changes[k] = v

        if changes:
            # increment sequence and record change
            try:
                self._seq += 1
            except Exception:
                self._seq = getattr(self, "_seq", 0) + 1
            self._change_log.append((self._seq, dict(changes)))
            await self.recv_queue.put({"type": "shared_objects_update", "seq": self._seq, "payload": changes})

            loop = asyncio.get_running_loop()
            for cb in list(self.shared_listeners):
                if inspect.iscoroutinefunction(cb):
                    asyncio.create_task(cb(changes, self._seq))
                else:
                    await loop.run_in_executor(None, functools.partial(cb, changes, self._seq))

            # broadcast update to connected clients (inline to avoid removed send_all)
            if self.clients:
                text = (json.dumps({"type": "shared_objects_update", "seq": self._seq, "payload": changes}) + "\n").encode("utf-8")
                coros = []
                for w in list(self.clients):
                    w.write(text)
                    coros.append(w.drain())
                if coros:
                    await asyncio.gather(*coros, return_exceptions=True)
            
    async def _ingest_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming OOB messages from the frontend or other producers.

        This handler focuses on ingesting messages (object_update, bulk_actions)
        and updating `shared_objects` / `_change_log`. It does not add the
        writer to the broadcast client set.
        """
        # stream-based ingest removed; use websockets via IngestLoop
        raise RuntimeError("_ingest_handler is removed; use websockets via IngestLoop")

    # websocket-based ingest moved to IngestLoop.handler

    # observer serve handler moved to ObserverLoop.handler

    # Convenience server-side APIs
    def get_shared_objects(self) -> Dict[str, Any]:
        try:
            return dict(self.shared_objects)
        except Exception:
            return {}

    def get_change_log(self):
        """Return a snapshot copy of the internal change log.

        Returns a list of (seq, changes) tuples in chronological order.
        """
        try:
            return list(self._change_log)
        except Exception:
            return []

    def get_raw_buffer(self):
        """Return a copy of the raw incoming message buffer.

        Each entry is a dict: {"ts": <timestamp>, "dir": "ingest|serve|tcp", "raw": <str>}
        """
        try:
            return list(self._raw_buffer)
        except Exception:
            return []

    def get_frontend_params(self) -> Dict[str, Optional[Any]]:
        """Return connection parameters intended for the frontend.

        - On POSIX systems, `socket_path` will be a filesystem path the
          frontend can connect to via a local unix-socket bridge.
        - On other platforms, `ws_port` will contain the TCP port reserved
          for the ingest websocket endpoint.

        These parameters are set by `IngestLoop` during `OOB_Server`
        initialization and are safe for callers (e.g., the applet) to
        serialize and send to the frontend so it knows how to reach the
        bridge.
        """
        try:
            return {"socket_path": getattr(self, "socket_path", None), "ws_port": getattr(self, "ws_port", None), "serve_port": getattr(self, "serve_port", None)}
        except Exception:
            return {"socket_path": None, "ws_port": None, "serve_port": None}

    def clear_raw_buffer(self):
        """Clear the raw message buffer."""
        try:
            self._raw_buffer.clear()
            return True
        except Exception:
            return False

    def add_shared_listener(self, fn):
        raise AttributeError("add_shared_listener removed; use shared_listeners directly")

    def remove_shared_listener(self, fn):
        raise AttributeError("remove_shared_listener removed; use shared_listeners directly")


    async def send_all(self, msg: dict):
        raise AttributeError("send_all removed; use a custom broadcaster via clients set")

    def send(self, msg: dict):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            asyncio.create_task(self.send_all(msg))
        else:
            asyncio.run(self.send_all(msg))


class IngestLoop:
    """Ingest-side WebSocket handler implementation.

    This class contains the actual ingestion loop formerly implemented on
    `OOB_Server._ingest_ws_handler`. It operates on `self.server` to update
    `shared_objects` and enqueue messages onto `recv_queue`.
    """

    def __init__(self, server: OOB_Server):
        self.server = server

        # Move socket reservation and prebind port logic here (ingest-specific)
        if getattr(self.server, "socket_path", None):
            # caller provided path; nothing to reserve
            pass
        else:
            if os.name == "posix":
                _fd, _path = tempfile.mkstemp(prefix="/tmp/ggb_")
                os.close(_fd)
                os.remove(_path)
                self.server.socket_path = _path
                self.server._raw_buffer.put({"ts": time.time(), "dir": "ingest", "raw": f"Reserved ingest socket_path {self.server.socket_path}"})
            else:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", 0))
                _, p = s.getsockname()
                self.server.ws_port = p
                s.close()
                self.server._raw_buffer.put({"ts": time.time(), "dir": "ingest", "raw": f"Reserved ingest ws_port {self.server.ws_port}"})

        # (observer prebind moved to ObserverLoop)

    def serve_context(self):
        """Return an async context manager for starting the ingest websocket server.

        Usage:
            async with ingest_loop.serve_context() as ingest_server:
                ...
        """
        # Prepare path/port and return the appropriate websockets context manager
        if getattr(self.server, "socket_path", None):
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            return unix_serve(self.handler, path=path)
        else:
            port = getattr(self.server, "ws_port", None)
            if port is None:
                port = 0
            return serve(self.handler, "127.0.0.1", port)



    async def start(self):
        """Start the ingest WebSocket server and attach handle to the parent server.

        Returns the server handle (or None on failure).
        """
        if getattr(self.server, "socket_path", None):
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            ingest_server = await unix_serve(self.handler, path=path)
            self.server._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": f"Starting unix socket server at {path}"})
        else:
            port = getattr(self.server, "ws_port", None)
            if port is None:
                port = 0
            ingest_server = await serve(self.handler, "127.0.0.1", port)
            self.server._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": f"Starting TCP socket server at 127.0.0.1:{port}"})

        self.server.ingest_server = ingest_server
        return ingest_server

    async def handler(self, websocket):
        async for msg in websocket:
            self.server._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": msg})

            try:
                data = json.loads(msg) if isinstance(msg, str) else msg
            except Exception:
                await self.server.recv_queue.put(msg)
                continue

            if isinstance(data, dict) and data.get("type") == "bulk_actions":
                payload = data.get("payload")
                if isinstance(payload, list):
                    for entry in payload:
                        if not isinstance(entry, dict):
                            continue
                        etype = entry.get("type")
                        epayload = entry.get("payload")
                        if etype == "object_update":
                            await self.server._handle_object_update(epayload)
                        else:
                            if isinstance(epayload, (dict, list)):
                                await self.server._handle_object_update(epayload)
                            else:
                                await self.server.recv_queue.put(entry)
                continue

            if isinstance(data, dict) and data.get("type") == "object_update":
                await self.server._handle_object_update(data.get("payload"))
                continue

            await self.server.recv_queue.put(data)


class ObserverLoop:
    """Client-facing TCP handler implementation.

    Contains the snapshot/diff/get/send handling formerly in
    `OOB_Server._serve_handler`.
    """

    def __init__(self, server: OOB_Server):
        self.server = server

    async def start(self):
        """Start the observer (client-facing) TCP server and return the handle.

        Uses an ephemeral port (0). Attaches the server to `self.server.serve_server`.
        """
        try:
            port =  0
            serve_server = await asyncio.start_server(self.handler, "127.0.0.1", port)
            self.server._raw_buffer.put({"ts": time.time(), "dir": "serve", "raw": f"Starting serve TCP server at 127.0.0.1:{port}"})
            self.server.serve_server = serve_server
            return serve_server
        except Exception:
            return None

    async def handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        with self.server._client_lock:
            self.server.clients.add(writer)
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                self.server._raw_buffer.put({"ts": time.time(), "dir": "serve", "raw": text})
                try:
                    data = json.loads(text) if isinstance(text, str) else text
                except Exception:
                    continue

                if isinstance(data, dict) and data.get("op") is not None:
                    op = data.get("op")
                    if op == "get_shared_snapshot":
                        out = {"type": "shared_objects_snapshot", "seq": self.server._seq, "payload": self.server.shared_objects}
                        writer.write((json.dumps(out) + "\n").encode("utf-8"))
                        await writer.drain()
                        continue
                    if op == "get_shared_diffs":
                        since = data.get("since", 0)
                        diffs = []
                        for s, ch in list(self.server._change_log):
                            if s > since:
                                diffs.append({"seq": s, "payload": ch})
                        out = {"type": "shared_objects_diffs", "since": since, "seq": self.server._seq, "payload": diffs}
                        writer.write((json.dumps(out) + "\n").encode("utf-8"))
                        await writer.drain()
                        continue

                _id = data.get("id") if isinstance(data, dict) else None
                if _id:
                    fut = None
                    with self.server._pending_lock:
                        fut = self.server.pending_futures.pop(_id, None)
                    if fut:
                        if not fut.done():
                            fut.set_result(data.get("payload"))
                    else:
                        if self.server.debug:
                            await self.server.recv_queue.put({"type": "unexpected_response", "id": _id, "payload": data.get("payload")})
                else:
                    await self.server.recv_queue.put(data)

                await asyncio.sleep(0)
        finally:
            with self.server._client_lock:
                self.server.clients.remove(writer)


__all__ = ["OOB_Server"]
