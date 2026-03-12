"""OOB_Server: Out-of-band message server for GeoGebra frontend.

This module provides `OOB_Server`, a TCP-based local out-of-band
message server using asyncio. It accepts newline-delimited JSON messages
from local clients and supports `send`, `send_recv`, and `recv_queue`.
"""

import asyncio
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
        self.socket_path: Optional[str] = None
        if socket_path:
            self.socket_path = socket_path
        else:
            try:
                if os.name in ["posix"]:
                    # create a temporary pathname in /tmp for a unix socket
                    _fd, _path = tempfile.mkstemp(prefix="/tmp/ggb_")
                    os.close(_fd)
                    try:
                        os.remove(_path)
                    except Exception:
                        pass
                    self.socket_path = _path
                else:
                    # Reserve a free TCP port and publish it as ws_port so
                    # downstream code can use it. This reduces race when
                    # binding the asyncio server later.
                    try:
                        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                        s.bind(("127.0.0.1", 0))
                        _, p = s.getsockname()
                        self.ws_port = p
                        # remember to close the temporary socket; the real
                        # asyncio server will bind the same port shortly.
                        s.close()
                        # store prebind port for later use
                        self._prebind_port = p
                    except Exception:
                        self._prebind_port = None
            except Exception:
                # best-effort; leave attributes as None on failure
                pass
        self.ws_port: Optional[int] = None
        self.server_handle = None
        self.ingest_server = None
        self.serve_server = None
        self.server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

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
        self._serve_prebind_port = None
        try:
            s2 = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s2.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            s2.bind(("127.0.0.1", 0))
            _, p2 = s2.getsockname()
            self._serve_prebind_port = p2
            s2.close()
        except Exception:
            self._serve_prebind_port = None

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
        try:
            self._stop_event.set()
        except Exception:
            pass

        try:
            if self.server_thread is not None:
                self.server_thread.join(timeout=1.0)
        except Exception:
            pass

        try:
            # close ingest and serve servers if present
            for srv in (getattr(self, "ingest_server", None), getattr(self, "serve_server", None)):
                if srv is not None:
                    close = getattr(srv, "close", None)
                    if callable(close):
                        close()
        except Exception:
            pass

    async def _server(self):
        loop = asyncio.get_running_loop()
        # Start two servers: ingest (receives OOB msgs from frontend) and
        # serve (client-facing API for snapshots/diffs and broadcasts).

        # Prepare ingest server (use unix socket on POSIX if socket_path present)
        ingest_server = None
        serve_server = None

        # Ensure ingest socket path parent exists when using unix socket
        if getattr(self, "socket_path", None):
            path = self.socket_path
            try:
                parent = os.path.dirname(path)
                if parent and not os.path.exists(parent):
                    os.makedirs(parent, exist_ok=True)
            except Exception:
                pass
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            # Use websockets unix_serve to accept WebSocket connections.
            async with unix_serve(self._ingest_ws_handler, path=path) as ingest_server:
                self._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": f"Starting unix socket server at {path}"})
                # Prepare serve server (client-facing API) on TCP port
                await loop.run_in_executor(None, self._stop_event.wait)
        else:
            port = getattr(self, "_prebind_port", None)
            if port is None:
                try:
                    port = int(os.environ.get("GGB_WS_PORT", "0"))
                except Exception:
                    port = 0
            # Use websockets serve for TCP WebSocket ingestion.
            ingest_server = await serve(self._ingest_ws_handler, "127.0.0.1", port)
            self._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": f"Starting TCP socket server at 127.0.0.1:{port}"})

        # Prepare serve server (client-facing API) - prefer prebound serve port
        serve_port = getattr(self, "_serve_prebind_port", None)
        if serve_port is None:
            try:
                serve_port = int(os.environ.get("GGB_OOB_SERVE_PORT", "0"))
            except Exception:
                serve_port = 0
        serve_server = await asyncio.start_server(self._serve_handler, "127.0.0.1", serve_port)
        try:
            self.serve_port = serve_server.sockets[0].getsockname()[1]
            self.ws_port = self.serve_port
        except Exception:
            self.serve_port = None

        # store handles and run both until stop
        self.ingest_server = ingest_server
        self.serve_server = serve_server
        # async with ingest_server, serve_server:
        #     await loop.run_in_executor(None, self._stop_event.wait)

    async def _handle_object_update(self, payload: Any):
        changes = {}
        try:
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
        except Exception:
            return

        if changes:
            try:
                # increment sequence and record change
                try:
                    self._seq += 1
                except Exception:
                    self._seq = getattr(self, "_seq", 0) + 1
                try:
                    self._change_log.append((self._seq, dict(changes)))
                except Exception:
                    pass
                await self.recv_queue.put({"type": "shared_objects_update", "seq": self._seq, "payload": changes})
            except Exception:
                pass

            loop = asyncio.get_running_loop()
            for cb in list(self.shared_listeners):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(changes, self._seq))
                    else:
                        await loop.run_in_executor(None, functools.partial(cb, changes, self._seq))
                except Exception:
                    pass

            # broadcast update to connected clients
            try:
                await self.send_all({"type": "shared_objects_update", "seq": self._seq, "payload": changes})
            except Exception:
                pass
    async def _ingest_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming OOB messages from the frontend or other producers.

        This handler focuses on ingesting messages (object_update, bulk_actions)
        and updating `shared_objects` / `_change_log`. It does not add the
        writer to the broadcast client set.
        """
        # `_ingest_handler` was removed in favor of websocket-based ingestion
        # using `_ingest_ws_handler`. This placeholder is intentionally left
        # to provide a clear location for the old stream-based handler.
        raise RuntimeError("_ingest_handler is removed; use websocket ingestion")

    async def _ingest_ws_handler(self, websocket):
        """Handle incoming WebSocket connections on the ingest socket.

        This accepts text frames and processes JSON payloads similarly to
        `_ingest_handler` (supports `bulk_actions` and `object_update`).
        """
        # record raw text for diagnostics
        # self._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": websocket})
        try:
            async for msg in websocket:
                self._raw_buffer.put({"ts": time.time(), "dir": "ingest_ws", "raw": msg})
                try:
                    data = json.loads(msg) if isinstance(msg, str) else msg
                except Exception:
                    # non-json -> enqueue raw
                    try:
                        await self.recv_queue.put(msg)
                    except Exception:
                        pass
                    continue

                if isinstance(data, dict) and data.get("type") == "bulk_actions":
                    payload = data.get("payload")
                    if isinstance(payload, list):
                        for entry in payload:
                            try:
                                if not isinstance(entry, dict):
                                    continue
                                etype = entry.get("type")
                                epayload = entry.get("payload")
                                if etype == "object_update":
                                    try:
                                        await self._handle_object_update(epayload)
                                    except Exception:
                                        pass
                                else:
                                    try:
                                        if isinstance(epayload, (dict, list)):
                                            try:
                                                await self._handle_object_update(epayload)
                                            except Exception:
                                                pass
                                        else:
                                            await self.recv_queue.put(entry)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    continue

                if isinstance(data, dict) and data.get("type") == "object_update":
                    try:
                        await self._handle_object_update(data.get("payload"))
                    except Exception:
                        pass
                    continue
                # otherwise enqueue
                try:
                    await self.recv_queue.put(data)
                except Exception:
                    pass
        except Exception:
            pass

    async def _serve_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle client-facing connections: snapshot/diffs and subscription for broadcasts."""
        with self._client_lock:
            self.clients.add(writer)
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                    # store raw line for diagnostics
                    try:
                        self._raw_buffer.put({"ts": time.time(), "dir": "serve", "raw": text})
                    except Exception:
                        pass
                    data = json.loads(text) if isinstance(text, str) else text
                except Exception:
                    continue

                # Control ops: snapshot / diffs
                if isinstance(data, dict) and data.get("op") is not None:
                    op = data.get("op")
                    try:
                        if op == "get_shared_snapshot":
                            out = {"type": "shared_objects_snapshot", "seq": self._seq, "payload": self.shared_objects}
                            writer.write((json.dumps(out) + "\n").encode("utf-8"))
                            await writer.drain()
                            continue
                        if op == "get_shared_diffs":
                            since = data.get("since", 0)
                            diffs = []
                            try:
                                for s, ch in list(self._change_log):
                                    if s > since:
                                        diffs.append({"seq": s, "payload": ch})
                            except Exception:
                                pass
                            out = {"type": "shared_objects_diffs", "since": since, "seq": self._seq, "payload": diffs}
                            writer.write((json.dumps(out) + "\n").encode("utf-8"))
                            await writer.drain()
                            continue
                    except Exception:
                        pass

                _id = data.get("id") if isinstance(data, dict) else None
                if _id:
                    fut = None
                    with self._pending_lock:
                        fut = self.pending_futures.pop(_id, None)
                    if fut:
                        try:
                            if not fut.done():
                                fut.set_result(data.get("payload"))
                        except Exception:
                            pass
                    else:
                        if self.debug:
                            try:
                                await self.recv_queue.put({"type": "unexpected_response", "id": _id, "payload": data.get("payload")})
                            except Exception:
                                pass
                else:
                    try:
                        await self.recv_queue.put(data)
                    except Exception:
                        pass

                await asyncio.sleep(0)
        finally:
            with self._client_lock:
                try:
                    self.clients.remove(writer)
                except Exception:
                    pass

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

    def clear_raw_buffer(self):
        """Clear the raw message buffer."""
        try:
            self._raw_buffer.clear()
            return True
        except Exception:
            return False

    def add_shared_listener(self, fn):
        try:
            if not callable(fn):
                return False
            with self._pending_lock:
                if fn not in self.shared_listeners:
                    self.shared_listeners.append(fn)
            return True
        except Exception:
            return False

    def remove_shared_listener(self, fn):
        try:
            with self._pending_lock:
                if fn in self.shared_listeners:
                    self.shared_listeners.remove(fn)
            return True
        except Exception:
            return False


    async def send_all(self, msg: dict):
        if not self.clients:
            return
        text = (json.dumps(msg) + "\n").encode("utf-8")
        coros = []
        for w in list(self.clients):
            try:
                w.write(text)
                coros.append(w.drain())
            except Exception:
                pass
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    def send(self, msg: dict):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            asyncio.create_task(self.send_all(msg))
        else:
            asyncio.run(self.send_all(msg))

    async def send_recv(self, msg: dict):
        if isinstance(msg, str):
            try:
                _data = json.loads(msg)
            except Exception:
                _data = {"payload": msg}
        else:
            _data = dict(msg)

        _id = str(uuid.uuid4())
        _data["id"] = _id

        fut = asyncio.get_running_loop().create_future()
        with self._pending_lock:
            self.pending_futures[_id] = fut

        waited = 0.0
        while not self.clients and waited < 2.0:
            await asyncio.sleep(0.05)
            waited += 0.05

        await self.send_all(_data)

        try:
            value = await asyncio.wait_for(fut, timeout=self.oob_timeout)
        finally:
            with self._pending_lock:
                self.pending_futures.pop(_id, None)

        return value


__all__ = ["OOB_Server"]
