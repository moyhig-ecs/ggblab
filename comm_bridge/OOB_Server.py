"""OOB_Server: Out-of-band message server for GeoGebra frontend.

This module provides `OOB_Server`, a TCP-based local out-of-band
message server using asyncio. It accepts newline-delimited JSON messages
from local clients and supports `send`, `send_recv`, and `recv_queue`.
"""

import asyncio
import errno
import functools
import inspect
import json
import os
import queue
import socket as _socket
import tempfile
import threading
import time
import traceback
from collections import deque
from typing import Any, Dict, Optional

from websockets.asyncio.server import serve, unix_serve


class OOB_Server:
    """Out-of-band message server.

    - Use `start()` / `stop()` to manage the background server thread.
    - `recv_queue` is an `asyncio.Queue` of incoming messages.
    - `send` / `send_recv` allow sending JSON-serializable messages.
    """

    def __init__(self, oob_timeout: float = 30.0, port: Optional[int] = None):
        # server transport state
        # If caller provided a socket_path, use it. Otherwise proactively
        # reserve a transport depending on the platform so callers can
        # inspect `socket_path` or `ws_port` immediately after `start()`.
        # let IngestLoop perform socket reservation/setup
        # Do not process or reserve `socket_path` here; IngestLoop handles socket reservation.
        # Keep attribute if present for later use, but do not perform setup in constructor.
        self.socket_path: Optional[str] = None
        # prebind port placeholder - IngestLoop may set this during its init
        # self._prebind_port = None
        self.ws_port: Optional[int] = None
        self.server_handle = None
        self.ingest_server = None
        self.observe_server = None
        self.server_thread: Optional[threading.Thread] = None
        # ingest server runs in its own thread + loop to avoid blocking
        self._ingest_thread: Optional[threading.Thread] = None
        self._ingest_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        # running asyncio loop for the background server thread
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # raw incoming message buffer for diagnostics (stores dicts: {ts, dir, raw})
        self._raw_buffer = queue.Queue(maxsize=100)

        # runtime state
        self.recv_queue: asyncio.Queue = asyncio.Queue()
        self.clients = set()
        self._client_lock = threading.Lock()
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self._pending_lock = threading.Lock()
        self.shared_objects: Dict[str, Any] = {}
        self.shared_listeners = []
        # lock protecting shared_objects and _change_log
        self._shared_lock = threading.Lock()

        # fallback raw buffer (thread-safe via _shared_lock) used when
        # the configured `_raw_buffer` does not support thread-safe put
        # or is an asyncio.Queue whose put() is a coroutine.
        self._raw_buffer_fallback = deque(maxlen=100)

        # sequence number and bounded change log for shared_objects updates
        self._seq = 0
        self._change_log = deque(maxlen=1000)
        self.oob_timeout = oob_timeout
        self.debug = False
        # prebind a separate observe port for client-facing API to reduce races
        # optional requested observe port (if caller wants to reserve a specific port)
        self.observe_port: Optional[int] = port

        # create handler loop wrappers (defined below)
        self.ingest_loop = IngestLoop(self)
        self.observer_loop = ObserverLoop(self)
        # runtime toggle to disable broadcasting (useful for debugging stalls)
        self.broadcast_enabled = True
        # broadcast queue (created on observer loop when needed)
        self._broadcast_queue: Optional[asyncio.Queue] = None

    def set_broadcast_enabled(self, enabled: bool):
        try:
            self.broadcast_enabled = bool(enabled)
            return True
        except Exception:
            return False

    def _push_raw_buffer(self, entry: Dict[str, Any]):
        """Helper to push entries into the raw buffer under the shared lock.

        Some callers may run on different threads/loops; use the shared lock
        to serialize access when requested by the caller.
        """
        rb = getattr(self, "_raw_buffer", None)
        # 1) Try non-blocking put for standard queue.Queue-like APIs (never block)
        try:
            if rb is not None and hasattr(rb, "put_nowait"):
                try:
                    rb.put_nowait(entry)
                    return
                except Exception:
                    # Full or other error -> fallback
                    pass
        except Exception:
            pass

        # 3) Fallback: append into local deque under lock
        try:
            with self._shared_lock:
                try:
                    self._raw_buffer_fallback.append(entry)
                except Exception:
                    pass
        except Exception:
            try:
                self._raw_buffer_fallback.append(entry)
            except Exception:
                pass

    def start(self):
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = threading.Event()

        # Start ingest server in its own thread to keep it alive while
        # processing OOB messages in the main server thread.
        if self._ingest_thread is None or not self._ingest_thread.is_alive():
            self._ingest_thread = threading.Thread(
                target=self._ingest_thread_main, daemon=True
            )
            self._ingest_thread.start()

        # Start observer/server loop in a separate background thread
        self.server_thread = threading.Thread(
            target=self._server_thread_main, daemon=True
        )
        self.server_thread.start()

    def _server_thread_main(self):
        try:
            asyncio.run(self._server())
        except Exception:
            # record traceback and avoid silent thread death
            try:
                self._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "server_thread",
                        "raw": traceback.format_exc(),
                    }
                )
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()
        # join server thread (allow background loop to observe _stop_event)
        if self.server_thread is not None:
            self.server_thread.join(timeout=1.0)

        # Close and await server handles on the background loop if possible
        for srv_name, srv in ("ingest", getattr(self, "ingest_server", None)), (
            "observe",
            getattr(self, "observe_server", None),
        ):
            # srv_name is unused in behavior but kept for clarity
            if srv is None:
                continue
            close_fn = getattr(srv, "close", None)
            wait_closed = getattr(srv, "wait_closed", None)

            # If this is the ingest server, it may live on its own event loop
            if srv is self.ingest_server and self._ingest_loop is not None:
                if callable(close_fn):
                    # schedule close on ingest loop
                    try:
                        asyncio.run_coroutine_threadsafe(close_fn(), self._ingest_loop)
                    except Exception:
                        try:
                            self._ingest_loop.call_soon_threadsafe(close_fn)
                        except Exception:
                            pass
                if callable(wait_closed):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            wait_closed(), self._ingest_loop
                        )
                    except Exception:
                        pass
                # stop the ingest loop
                try:
                    self._ingest_loop.call_soon_threadsafe(self._ingest_loop.stop)
                except Exception:
                    pass
            else:
                # observer server lives on self._loop
                if callable(close_fn):
                    close_fn()
                if (
                    callable(wait_closed)
                    and getattr(self, "_loop", None) is not None
                    and self._loop.is_running()
                ):
                    asyncio.run_coroutine_threadsafe(wait_closed(), self._loop)
                elif callable(wait_closed):
                    try:
                        asyncio.run(wait_closed())
                    except Exception:
                        pass

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
        # Only start the observer/server in this loop. The ingest server
        # is started in a dedicated thread (see `start()`).
        observe_server = None
        try:
            try:
                observe_server = await self.observer_loop.start()
            except Exception:
                observe_server = None
            if observe_server is not None:
                try:
                    self.observe_port = observe_server.sockets[0].getsockname()[1]
                except Exception:
                    self.observe_port = None
            else:
                self.observe_port = None

            self.observe_server = observe_server
            # Wait until stop event is set
            await loop.run_in_executor(None, self._stop_event.wait)
        finally:
            # ensure observer handle remains set (or None) for cleanup
            self.observe_server = observe_server

    def _ingest_thread_main(self):
        """Run the ingest websocket server on its own asyncio loop in a background thread.

        This creates a dedicated event loop, starts the ingest server via
        `IngestLoop.start()` and then runs the loop forever until stopped.
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._ingest_loop = loop
            # start the ingest server and keep loop running
            try:
                ingest_srv = loop.run_until_complete(self.ingest_loop.start())
                self.ingest_server = ingest_srv
                self._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "ingest_ws",
                        "raw": "Ingest thread started",
                    }
                )
            except Exception:
                # startup failed; record traceback and exit
                self._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "ingest_ws",
                        "raw": f"Ingest thread failed to start: {traceback.format_exc()}",
                    }
                )
                self._ingest_loop = None
                return

            try:
                loop.run_forever()
            finally:
                # Attempt to close server cleanly
                try:
                    if self.ingest_server is not None:
                        close_fn = getattr(self.ingest_server, "close", None)
                        wait_closed = getattr(self.ingest_server, "wait_closed", None)
                        if callable(close_fn):
                            loop.run_until_complete(close_fn())
                        if callable(wait_closed):
                            loop.run_until_complete(wait_closed())
                except Exception:
                    pass
        finally:
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
            self._ingest_loop = None
            self._push_raw_buffer(
                {"ts": time.time(), "dir": "ingest_ws", "raw": "Ingest thread exiting"}
            )

    async def _handle_object_update(self, payload: Any):
        self._push_raw_buffer(
            {
                "ts": time.time(),
                "dir": "ingest",
                "raw": f"Object update payload: {payload}",
            }
        )
        changes = {}
        # parse payload into a plain changes dict first
        if isinstance(payload, list) and payload and isinstance(payload[0], list):
            for pair in payload:
                if isinstance(pair, list) and len(pair) >= 2:
                    name, value = pair[0], pair[1]
                    changes[name] = value
        elif (
            isinstance(payload, list)
            and len(payload) >= 2
            and not any(isinstance(i, list) for i in payload)
        ):
            name, value = payload[0], payload[1]
            changes[name] = value
        elif isinstance(payload, dict):
            if "name" in payload and "value" in payload:
                changes[payload["name"]] = payload["value"]
            else:
                for k, v in payload.items():
                    changes[k] = v

        if changes:
            # increment sequence and record change under lock
            try:
                with self._shared_lock:
                    try:
                        self._seq += 1
                    except Exception:
                        self._seq = getattr(self, "_seq", 0) + 1
                    # apply changes to shared_objects
                    for k, v in changes.items():
                        self.shared_objects[k] = v
                    # record the change
                    self._change_log.append((self._seq, dict(changes)))
                    seq = self._seq
            except Exception:
                # fallback behavior if locking fails
                try:
                    self._seq += 1
                except Exception:
                    self._seq = getattr(self, "_seq", 0) + 1
                self._change_log.append((self._seq, dict(changes)))
                seq = self._seq
            await self.recv_queue.put(
                {"type": "shared_objects_update", "seq": seq, "payload": changes}
            )

            loop = asyncio.get_running_loop()
            for cb in list(self.shared_listeners):
                if inspect.iscoroutinefunction(cb):
                    asyncio.create_task(cb(changes, seq))
                else:
                    await loop.run_in_executor(
                        None, functools.partial(cb, changes, seq)
                    )

            # broadcast update to connected clients if enabled. Writers belong to the
            # observer loop; enqueue broadcast on that loop to avoid cross-loop
            # await/drain issues. A dedicated broadcaster task on the observer
            # loop will consume the queue and perform actual writes.
            if getattr(self, "broadcast_enabled", True) and self.clients:
                try:
                    if (
                        getattr(self, "_loop", None) is not None
                        and asyncio.get_running_loop() is not self._loop
                    ):
                        # schedule enqueue on observer loop (non-blocking from ingest)
                        try:
                            self._push_raw_buffer(
                                {
                                    "ts": time.time(),
                                    "dir": "serve",
                                    "raw": f"Enqueuing broadcast on observer loop seq={seq}",
                                }
                            )
                            # ensure broadcast queue exists on observer loop
                            if getattr(self, "_broadcast_queue", None) is None:
                                try:
                                    asyncio.run_coroutine_threadsafe(
                                        self._create_broadcast_queue(), self._loop
                                    ).result(timeout=1.0)
                                except Exception:
                                    pass

                            if getattr(self, "_broadcast_queue", None) is not None:
                                try:
                                    asyncio.run_coroutine_threadsafe(
                                        self._broadcast_queue.put((changes, seq)),
                                        self._loop,
                                    )
                                except Exception:
                                    # enqueue failed; fallback to direct broadcast
                                    await self._broadcast_update(changes, seq)
                            else:
                                # no queue available; fallback
                                await self._broadcast_update(changes, seq)
                        except Exception:
                            # fallback: attempt to run in current loop
                            await self._broadcast_update(changes, seq)
                    else:
                        await self._broadcast_update(changes, seq)
                except RuntimeError:
                    # No running loop information; attempt direct broadcast
                    try:
                        await self._broadcast_update(changes, seq)
                    except Exception:
                        pass

    async def _ingest_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle incoming OOB messages from the frontend or other producers.

        This handler focuses on ingesting messages (object_update, bulk_actions)
        and updating `shared_objects` / `_change_log`. It does not add the
        writer to the broadcast client set.
        """
        # stream-based ingest removed; use websockets via IngestLoop
        raise RuntimeError("_ingest_handler is removed; use websockets via IngestLoop")

    async def _broadcast_update(self, changes: Dict[str, Any], seq: int):
        """Broadcast a shared_objects_update to all connected clients.

        This method must be executed on the observer loop where the
        StreamWriter objects were created.
        """
        try:
            text = (
                json.dumps(
                    {"type": "shared_objects_update", "seq": seq, "payload": changes}
                )
                + "\n"
            ).encode("utf-8")
            TIMEOUT = 1.0
            with self._client_lock:
                clients = list(self.clients)

            to_remove = []
            for w in clients:
                try:
                    w.write(text)
                except Exception:
                    to_remove.append(w)
                    continue

                try:
                    await asyncio.wait_for(w.drain(), timeout=TIMEOUT)
                except asyncio.TimeoutError:
                    # slow client -> drop
                    to_remove.append(w)
                    self._push_raw_buffer(
                        {
                            "ts": time.time(),
                            "dir": "serve",
                            "raw": f"Dropping slow client on seq={seq}",
                        }
                    )
                except Exception:
                    to_remove.append(w)

            if to_remove:
                with self._client_lock:
                    for w in to_remove:
                        try:
                            if w in self.clients:
                                self.clients.remove(w)
                        except Exception:
                            pass
                        try:
                            close_fn = getattr(w, "close", None)
                            if callable(close_fn):
                                close_fn()
                        except Exception:
                            pass
        except Exception:
            try:
                self._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "serve",
                        "raw": f"_broadcast_update failed: {traceback.format_exc()}",
                    }
                )
            except Exception:
                pass
            return

    async def _create_broadcast_queue(self):
        """Create the broadcast queue and start the broadcaster task on the
        observer loop. This must be executed on the observer loop."""
        if getattr(self, "_broadcast_queue", None) is None:
            self._broadcast_queue = asyncio.Queue()
            try:
                asyncio.create_task(self._broadcaster())
            except Exception:
                try:
                    self._push_raw_buffer(
                        {
                            "ts": time.time(),
                            "dir": "serve",
                            "raw": "Failed to start broadcaster task",
                        }
                    )
                except Exception:
                    pass

    async def _broadcaster(self):
        """Consume broadcast queue and forward updates to clients.

        Runs on the observer loop and serializes writes so slow clients don't
        block the ingest path.
        """
        while True:
            try:
                item = await self._broadcast_queue.get()
                if item is None:
                    return
                changes, seq = item
                try:
                    await self._broadcast_update(changes, seq)
                except Exception:
                    try:
                        self._push_raw_buffer(
                            {
                                "ts": time.time(),
                                "dir": "serve",
                                "raw": f"Broadcaster failed for seq={seq}: {traceback.format_exc()}",
                            }
                        )
                    except Exception:
                        pass
            except Exception:
                try:
                    self._push_raw_buffer(
                        {
                            "ts": time.time(),
                            "dir": "serve",
                            "raw": f"Broadcaster loop exception: {traceback.format_exc()}",
                        }
                    )
                except Exception:
                    pass

    # websocket-based ingest moved to IngestLoop.handler

    # observer serve handler moved to ObserverLoop.handler

    # Convenience server-side APIs
    def get_shared_objects(self) -> Dict[str, Any]:
        try:
            with self._shared_lock:
                return dict(self.shared_objects)
        except Exception:
            return {}

    def get_change_log(self):
        """Return a snapshot copy of the internal change log.

        Returns a list of (seq, changes) tuples in chronological order.
        """
        try:
            with self._shared_lock:
                return list(self._change_log)
        except Exception:
            return []

    def get_raw_buffer(self):
        """Return a copy of the raw incoming message buffer.

        Each entry is a dict: {"ts": <timestamp>, "dir": "ingest|serve|tcp", "raw": <str>}
        """
        try:
            with self._shared_lock:
                rb = getattr(self, "_raw_buffer", None)
                entries = []
                if rb is None:
                    entries = []
                elif hasattr(rb, "queue"):
                    try:
                        entries = list(rb.queue)
                    except Exception:
                        entries = []
                elif hasattr(rb, "_queue"):
                    try:
                        entries = list(rb._queue)
                    except Exception:
                        entries = []
                else:
                    try:
                        entries = list(rb)
                    except Exception:
                        entries = []

                # append any fallback entries
                try:
                    entries.extend(list(self._raw_buffer_fallback))
                except Exception:
                    pass
                return entries
        except Exception:
            try:
                return list(self._raw_buffer_fallback)
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
            return {
                "socket_path": getattr(self, "socket_path", None),
                "ws_port": getattr(self, "ws_port", None),
                "observe_port": getattr(self, "observe_port", None),
            }
        except Exception:
            return {"socket_path": None, "ws_port": None, "observe_port": None}

    def clear_raw_buffer(self):
        """Clear the raw message buffer."""
        try:
            self._raw_buffer.clear()
            return True
        except Exception:
            return False

    def add_shared_listener(self, fn):
        raise AttributeError(
            "add_shared_listener removed; use shared_listeners directly"
        )

    def remove_shared_listener(self, fn):
        raise AttributeError(
            "remove_shared_listener removed; use shared_listeners directly"
        )

    async def send_all(self, msg: dict):
        raise AttributeError(
            "send_all removed; use a custom broadcaster via clients set"
        )

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

        if os.name in ["posix"]:
            _fd, _path = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(_path)
            self.server.socket_path = _path
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest",
                    "raw": f"Reserved ingest socket_path {self.server.socket_path}",
                }
            )
        else:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            _, p = s.getsockname()
            self.server.ws_port = p
            s.close()
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest",
                    "raw": f"Reserved ingest ws_port {self.server.ws_port}",
                }
            )

    def serve_context(self):
        """Return an async context manager for starting the ingest websocket server.

        Usage:
            async with ingest_loop.serve_context() as ingest_server:
                ...
        """
        # Prepare path/port and return the appropriate websockets context manager
        if self.server.socket_path:
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            return unix_serve(self.handler, path=path)
        else:
            port = self.server.ws_port
            if port is None:
                port = 0
            return serve(self.handler, "127.0.0.1", port)

    async def start(self):
        """Start the ingest WebSocket server and attach handle to the parent server.

        Returns the server handle (or None on failure).
        """
        if self.server.socket_path:
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            ingest_server = await unix_serve(self.handler, path=path)
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest_ws",
                    "raw": f"Starting unix socket server at {path}",
                }
            )
        else:
            port = self.server.ws_port
            if port is None:
                port = 0
            ingest_server = await serve(self.handler, "127.0.0.1", port)
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest_ws",
                    "raw": f"Starting TCP socket server at 127.0.0.1:{port}",
                }
            )

        self.server.ingest_server = ingest_server
        return ingest_server

    async def handler(self, websocket):
        async for msg in websocket:
            self.server._push_raw_buffer(
                {"ts": time.time(), "dir": "ingest_ws", "raw": msg}
            )

            try:
                data = json.loads(msg) if isinstance(msg, str) else msg
                self.server._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "ingest",
                        "raw": f"Parsed ingest message: {data}",
                    }
                )
            except Exception:
                self.server._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "ingest",
                        "raw": f"Failed to parse ingest message: {msg}",
                    }
                )
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
                self.server._push_raw_buffer(
                    {
                        "ts": time.time(),
                        "dir": "ingest",
                        "raw": f"Object update payload: {data.get('payload')}",
                    }
                )
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

        Uses an ephemeral port (0). Attaches the server to `self.server.observe_server`.
        """
        try:
            # use optional prebound/requested port if provided, otherwise ephemeral
            req_port = (
                getattr(self.server, "observe_port", None)
                if hasattr(self, "server")
                else None
            )
            port = req_port if req_port is not None else 0
            try:
                observe_server = await asyncio.start_server(
                    self.handler, "127.0.0.1", port
                )
            except OSError as e:
                # If the requested port is in use or permission denied, fall back to ephemeral
                if req_port is not None and getattr(e, "errno", None) in (
                    errno.EADDRINUSE,
                    errno.EACCES,
                ):
                    observe_server = await asyncio.start_server(
                        self.handler, "127.0.0.1", 0
                    )
                    bound_port = observe_server.sockets[0].getsockname()[1]
                    self.server._push_raw_buffer(
                        {
                            "ts": time.time(),
                            "dir": "serve",
                            "raw": f"Requested serve port {req_port} unavailable; bound to ephemeral {bound_port}",
                        }
                    )
                else:
                    raise

            # Determine actual bound port for logging
            try:
                bound = observe_server.sockets[0].getsockname()
                bound_port = bound[1] if bound else None
            except Exception:
                bound_port = None

            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "serve",
                    "raw": f"Starting serve TCP server at 127.0.0.1:{bound_port}",
                }
            )
            self.server.observe_server = observe_server
            # Ensure broadcaster queue/task exists on the observer loop
            try:
                await self.server._create_broadcast_queue()
            except Exception:
                try:
                    self.server._push_raw_buffer(
                        {
                            "ts": time.time(),
                            "dir": "serve",
                            "raw": f"Failed to create broadcast queue: {traceback.format_exc()}",
                        }
                    )
                except Exception:
                    pass
            return observe_server
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
                text = (
                    raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                )
                try:
                    # text may be large; push under lock for consistency
                    self.server._push_raw_buffer(
                        {"ts": time.time(), "dir": "serve", "raw": text}
                    )
                except Exception:
                    pass
                try:
                    data = json.loads(text) if isinstance(text, str) else text
                except Exception:
                    continue

                if isinstance(data, dict) and data.get("op") is not None:
                    op = data.get("op")
                    if op == "get_shared_snapshot":
                        # snapshot shared_objects and seq under lock
                        try:
                            with self.server._shared_lock:
                                snap_seq = self.server._seq
                                snap_payload = dict(self.server.shared_objects)
                        except Exception:
                            snap_seq = self.server._seq
                            snap_payload = dict(self.server.shared_objects)
                        out = {
                            "type": "shared_objects_snapshot",
                            "seq": snap_seq,
                            "payload": snap_payload,
                        }
                        writer.write((json.dumps(out) + "\n").encode("utf-8"))
                        await writer.drain()
                        continue
                    if op == "get_shared_diffs":
                        since = data.get("since", 0)
                        diffs = []
                        try:
                            with self.server._shared_lock:
                                change_log_copy = list(self.server._change_log)
                                snap_seq = self.server._seq
                        except Exception:
                            change_log_copy = list(self.server._change_log)
                            snap_seq = self.server._seq
                        for s, ch in change_log_copy:
                            if s > since:
                                diffs.append({"seq": s, "payload": ch})
                        out = {
                            "type": "shared_objects_diffs",
                            "since": since,
                            "seq": snap_seq,
                            "payload": diffs,
                        }
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
                            await self.server.recv_queue.put(
                                {
                                    "type": "unexpected_response",
                                    "id": _id,
                                    "payload": data.get("payload"),
                                }
                            )
                else:
                    await self.server.recv_queue.put(data)

                await asyncio.sleep(0)
        finally:
            with self.server._client_lock:
                self.server.clients.remove(writer)


__all__ = ["OOB_Server"]
