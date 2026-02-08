"""Communication primitives for GeoGebra frontend↔kernel messaging.

This module implements a dual-channel communication layer combining
IPython Comm with an out-of-band socket (Unix domain socket or WebSocket)
to ensure reliable message delivery while notebook cells execute.
"""
import asyncio
import concurrent.futures
import functools
import json
import os
import queue
import tempfile
import threading
import time
import uuid

from IPython import get_ipython
from websockets.asyncio.server import serve, unix_serve

from .errors import GeoGebraAppletError

# Optional ipywidgets import for DOMWidget-based comm bridge
try:
    import ipywidgets as _ipywidgets
    _WIDGETS_AVAILABLE = True
except Exception:
    _ipywidgets = None
    _WIDGETS_AVAILABLE = False


class ggb_comm:
    """Dual-channel communication layer for kernel↔widget messaging.
    
    Implements a combination of IPython Comm (primary) and out-of-band socket
    (Unix domain socket on POSIX, TCP WebSocket on Windows) to enable message
    delivery during cell execution when IPython Comm is blocked.
    
    IPython Comm cannot receive messages while a notebook cell is executing,
    which breaks interactive workflows. The out-of-band socket solves this by
    providing a secondary channel for GeoGebra responses.
    
    Architecture:
        - IPython Comm: Command dispatch, event notifications, heartbeat
        - Out-of-band socket: Response delivery during cell execution
    
    Comm target is fixed at 'jupyter.ggblab' because multiplexing via multiple
    targets would not solve the IPython Comm receive limitation. The
    dotted name follows the ipywidgets-style naming convention and is also
    used by `load_ipython_extension` to register the handler at runtime.
    
    Attributes:
        target_comm: IPython Comm object
        target_name (str): Comm target name ('ggblab-comm')
        server_handle: WebSocket server handle
        server_thread: Background thread running the socket server
        clients (set): Currently connected WebSocket clients
        socketPath (str): Unix domain socket path (POSIX)
        wsPort (int): TCP port number (Windows)
        pending_futures (dict): Mapping of message-id to Future for awaiting responses
        recv_events (queue.Queue): Event queue for frontend notifications
    
        Future improvement:
            Consider integrating the out-of-band server with Jupyter's
            Tornado/ioloop to avoid cross-thread asyncio interactions. This
            would simplify event-loop boundaries but has non-trivial
            implementation cost, so it's deferred for future work.
    """

    # [Frontent to kernel callback - JupyterLab - Jupyter Community Forum]
    # (https://discourse.jupyter.org/t/frontent-to-kernel-callback/1666)
    recv_msgs = {}
    # pending_futures maps message-id -> concurrent.futures.Future
    pending_futures = {}
    recv_events = queue.Queue()
    logs = []
    # Shared object state published by incoming `object_update` events.
    # This is a class-level dict intended for cross-instance/global access.
    shared_objects = {}
    # Listeners (callables) invoked when shared_objects are updated.
    # Listener signature: fn(changes: dict) -> None
    _shared_listeners = []
    # (removed) optional asyncio loop field no longer used
    thread = None
    thread_lock = threading.Lock()
    mid = None
    # target_comm = None

    def __init__(self):
        """Initialize communication state and defaults."""
        self.target_comm = None
        self.target_name = 'jupyter.ggblab'
        self.server_handle = None
        self.server_thread = None
        self.clients = set()
        self.socketPath = None
        self.wsPort = 0
        # Event to signal the background server thread to stop
        self._stop_event = threading.Event()
        # counters for noisy connect/disconnect events; used to aggregate logs
        self._client_connect_count = 0
        self._client_disconnect_count = 0
        self._last_client_log_time = 0.0
        # applet_started removed; rely on out-of-band responses (pending_futures)
        # NOTE: Originally we planned to use an explicit 'start' handshake so that
        # `ggbapplet.init()` could be executed in the same notebook cell that
        # starts the frontend. In practice, IPython Comm target registration and
        # handler installation are not reliably completed until the cell's
        # execution finishes, so messages emitted within the same cell may not
        # be received. Because of this timing constraint the 'applet_start'
        # handshake was left pending and removed here to avoid brittle behavior.
        # Per-instance mapping from message id to Future
        self.pending_futures = {}
        # Optional ipywidgets bridge widget whose comm can be reused
        self.widget_bridge = None
        # Prefer to register the IPython Comm target by default so the
        # frontend can open a kernel-level Comm for command/response.
        # Older behaviour allowed opting out; keep the flag for backwards
        # compatibility but default to True which is the expected path now.
        self.use_ipython_comm = True
        # Feature flag: enable creation of an ipywidgets-based bridge
        # when `use_ipython_comm` is False. Keep disabled by default to
        # avoid creating transient kernel-side Comms during init.
        self.enable_widget_bridge = False
        # Debug flag: when False, suppress non-actionable diagnostic log entries
        self.debug = False
        # Out-of-band response watchdog timeout (seconds). Can be overridden
        # via the environment variable GGB_OOB_TIMEOUT or by setting the
        # instance attribute `oob_timeout` at runtime. Default is 30 seconds.
        try:
            self.oob_timeout = float(os.environ.get('GGB_OOB_TIMEOUT', '30'))
        except Exception:
            self.oob_timeout = 30.0

    # oob websocket (unix_domain socket in posix)
    def start(self):
        """Start the out-of-band socket server in a background thread.
        
        Creates a Unix domain socket (POSIX) or TCP WebSocket server (Windows)
        and runs it in a daemon thread. The server listens for GeoGebra responses.
        """
        # Ensure any previous stop event is cleared and start server thread
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = threading.Event()

        self.server_thread = threading.Thread(target=lambda: asyncio.run(self.server()), daemon=True)
        self.server_thread.start()

    def stop(self):
        """Stop the out-of-band socket server."""
        try:
            # Signal the server to stop
            self._stop_event.set()
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error signaling stop_event: {e}")

        try:
            # Allow the server coroutine to exit its context and the thread to join
            if self.server_thread is not None:
                self.server_thread.join(timeout=1.0)
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error joining server_thread: {e}")

        try:
            if self.server_handle is not None:
                # best-effort close; actual closure happens when server coroutine exits
                close = getattr(self.server_handle, 'close', None)
                if callable(close):
                    close()
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error closing server_handle: {e}")

    async def server(self):
        """Run the out-of-band socket server.

        Uses a Unix domain socket on POSIX systems and a TCP WebSocket otherwise.
        """
        loop = asyncio.get_running_loop()
        if os.name in [ 'posix' ]:
            _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(self.socketPath)
            async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
                # Wait until stop_event is set in another thread
                await loop.run_in_executor(None, self._stop_event.wait)
        else:
            async with serve(self.client_handle, "localhost", 0) as self.server_handle:
                with self.thread_lock:
                    self.wsPort = self.server_handle.sockets[0].getsockname()[1]
                    self.logs.append(f"WebSocket server started at ws://localhost:{self.wsPort}")
                # Wait until stop_event is set in another thread
                await loop.run_in_executor(None, self._stop_event.wait)

    async def client_handle(self, client_id):
        """Handle messages from a connected websocket client.

        Routes command responses into `pending_futures` and event messages into `recv_events`.
        """
        with self.thread_lock:
            self.clients.add(client_id)
            self._client_connect_count += 1
            # rate-limit detailed connect logs to once every 5 seconds
            now = time.time()
            if now - self._last_client_log_time > 5.0:
                self.logs.append(
                    f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                )
                self._client_connect_count = 0
                self._client_disconnect_count = 0
                self._last_client_log_time = now

        try:
            async for msg in client_id:
                # _data = ast.literal_eval(msg)
                _data = json.loads(msg)
                # Log incoming message type for diagnostics
                try:
                    t = _data.get('type') if isinstance(_data, dict) else None
                    with self.thread_lock:
                        self.logs.append(f"recv:type={t}")
                except Exception as _e:
                    with self.thread_lock:
                        self.logs.append(f"recv:type:logging_failed {_e}")
                # Helper to process object_update payloads (shared_objects update + notify listeners)
                async def _handle_object_update(payload):
                    try:
                        changes = {}
                        with self.thread_lock:
                            cls = self.__class__
                            # list of pairs [[name, value], ...]
                            if isinstance(payload, list) and payload and isinstance(payload[0], list):
                                for pair in payload:
                                    if isinstance(pair, list) and len(pair) >= 2:
                                        name = pair[0]
                                        value = pair[1]
                                        cls.shared_objects[name] = value
                                        changes[name] = value
                            # single pair [name, value]
                            elif isinstance(payload, list) and len(payload) >= 2 and not any(isinstance(i, list) for i in payload):
                                name = payload[0]
                                value = payload[1]
                                cls.shared_objects[name] = value
                                changes[name] = value
                            # payload may be a dict {name: value, ...}
                            # or a single object {'name': name, 'value': value}
                            elif isinstance(payload, dict):
                                # Handle {'name': ..., 'value': ...} shape
                                if 'name' in payload and 'value' in payload:
                                    cls.shared_objects[payload['name']] = payload['value']
                                    changes[payload['name']] = payload['value']
                                else:
                                    for k, v in payload.items():
                                        cls.shared_objects[k] = v
                                        changes[k] = v

                        # If any changes were applied, enqueue an event for consumers
                        if changes:
                            try:
                                # Event shape: type 'shared_objects_update'
                                self.recv_events.put({'type': 'shared_objects_update', 'payload': changes})
                            except Exception:
                                with self.thread_lock:
                                    self.logs.append('Failed to enqueue shared_objects_update event')

                        # Invoke any registered Python callbacks: await coroutine listeners
                        # directly (this is inside an async handler) and run sync listeners
                        # in the event loop's executor.
                        if changes and getattr(cls, '_shared_listeners', None):
                            loop = asyncio.get_running_loop()
                            for cb in list(cls._shared_listeners):
                                try:
                                    import inspect

                                    if inspect.iscoroutinefunction(cb):
                                        try:
                                            await cb(changes)
                                        except Exception as e:
                                            with self.thread_lock:
                                                self.logs.append(f'Error in async shared_objects listener: {e}')
                                    else:
                                        try:
                                            await loop.run_in_executor(None, functools.partial(cb, changes))
                                        except Exception as e:
                                            with self.thread_lock:
                                                self.logs.append(f'Error in sync shared_objects listener: {e}')
                                except Exception:
                                    with self.thread_lock:
                                        self.logs.append('Error invoking shared_objects listener')
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(f'Failed to process object_update payload: {e}')

                # If this is a `bulk_actions` message, unpack and process entries
                if isinstance(_data, dict) and _data.get('type') == 'bulk_actions':
                    payload = _data.get('payload')
                    try:
                        if isinstance(payload, list):
                            try:
                                with self.thread_lock:
                                    self.logs.append(f'bulk_actions: packaged_count={len(payload)}')
                            except Exception:
                                pass
                            for entry in payload:
                                try:
                                    if not isinstance(entry, dict):
                                        # Skip malformed entries
                                        continue
                                    etype = entry.get('type')
                                    epayload = entry.get('payload')
                                    # Handle object_update entries specially
                                    if etype == 'object_update':
                                        try:
                                            await _handle_object_update(epayload)
                                        except Exception:
                                            with self.thread_lock:
                                                self.logs.append('Error handling object_update entry in bulk_actions')
                                    else:
                                        # Queue other action entries as individual events
                                        try:
                                            self.recv_events.put(entry)
                                        except Exception:
                                            with self.thread_lock:
                                                self.logs.append('Failed to enqueue bulk action entry')
                                except Exception:
                                    with self.thread_lock:
                                        self.logs.append('Error processing entry in bulk_actions')
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(f'Failed to process bulk_actions payload: {e}')
                    # After unpacking we continue to next message
                    continue

                # If this is an `object_update` event, update the shared_objects
                # class-level mapping so other consumers can read the latest
                # object values. Payloads may be a single pair [name, value]
                # or a list of pairs.
                if isinstance(_data, dict) and _data.get('type') == 'object_update':
                    payload = _data.get('payload')
                    try:
                        await _handle_object_update(payload)
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(f'Failed to process object_update payload: {e}')

                            # Route event-type messages to recv_events queue
                            # Messages with 'id' are command responses; messages without 'id' are events.
                            # This enables:
                            # - Real-time error capture during cell execution
                            # - Dynamic scope learning from Applet error events
                            # - Cross-domain error pattern analysis

            # ensure we have the message id available for routing
            _id = _data.get('id') if isinstance(_data, dict) else None

            if _id:
                # Response message: fulfill any waiting Future for this id
                with self.thread_lock:
                    fut = self.pending_futures.pop(_id, None)
                if fut:
                    try:
                        import asyncio as _asyncio
                        is_asyncio = isinstance(fut, _asyncio.Future) if hasattr(_asyncio, 'Future') else False
                        if is_asyncio:
                            # Try to obtain the loop associated with the future.
                            loop = None
                            try:
                                get_loop = getattr(fut, 'get_loop', None)
                                if callable(get_loop):
                                    loop = get_loop()
                            except Exception:
                                loop = getattr(fut, '_loop', None)

                            # If the loop is running, schedule thread-safe set_result.
                            if loop is not None and getattr(loop, 'is_running', lambda: False)():
                                loop.call_soon_threadsafe(fut.set_result, _data.get('payload'))
                            else:
                                fut.set_result(_data.get('payload'))
                        else:
                            fut.set_result(_data.get('payload'))
                    except Exception as e:
                        if getattr(self, 'debug', False):
                            with self.thread_lock:
                                self.logs.append(f"Error setting result for id {_id}: {e}")
                else:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append(f"Unexpected response for id {_id}")
            else:
                # Event message: queue for event processing
                # Error handling is deferred to send_recv() for proper exception propagation
                self.recv_events.put(_data)

            # yield to the event loop so other coroutines can make progress
            await asyncio.sleep(0)
        except Exception as e:
            # record connection errors for diagnostics instead of silently passing
            with self.thread_lock:
                # record connection errors but avoid spamming; use same rate-limit
                now = time.time()
                if now - self._last_client_log_time > 5.0:
                    # Connection errors are notable; always record
                    self.logs.append(f"Connection error: {e}")
                    self._last_client_log_time = now
            # self.logs.append(f"Connection closed: {e}")
        finally:
            with self.thread_lock:
                if client_id in self.clients:
                    try:
                        self.clients.remove(client_id)
                    except Exception as e:
                        self.logs.append(f"Error removing client: {e}")
                self._client_disconnect_count += 1
                now = time.time()
                if now - self._last_client_log_time > 5.0:
                    self.logs.append(
                        f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                    )
                    self._client_connect_count = 0
                    self._client_disconnect_count = 0
                    self._last_client_log_time = now

    # comm
    def register_target(self):
        """Register the IPython Comm target for frontend messages.

        Note: IPython Comm registration is disabled by default (see
        `self.use_ipython_comm`). Callers may enable it by setting that
        attribute to True before calling this method.
        """
        if not getattr(self, 'use_ipython_comm', False):
            # If widget-bridge creation is disabled, return early.
            if not getattr(self, 'enable_widget_bridge', False):
                if getattr(self, 'debug', False):
                    with self.thread_lock:
                        self.logs.append('IPython Comm registration skipped (use_ipython_comm=False)')
                return

            # Otherwise attempt to create a minimal ipywidgets bridge (best-effort).
            if not _WIDGETS_AVAILABLE:
                if getattr(self, 'debug', False):
                    with self.thread_lock:
                        self.logs.append('ipywidgets not available; IPython Comm registration skipped')
                return

            try:
                # create or reuse bridge
                if self.widget_bridge is None:
                    wb = _ipywidgets.Widget()
                    self.widget_bridge = wb

                    # route widget messages to handle_recv
                    def _on_msg(widget, content, buffers):
                        try:
                            # normalize into previous message shape
                            msg = {'content': {'data': content}}
                            self.handle_recv(msg)
                        except Exception:
                            with self.thread_lock:
                                self.logs.append('Error handling widget bridge message')

                    self.widget_bridge.on_msg(_on_msg)

                if getattr(self, 'debug', False):
                    with self.thread_lock:
                        self.logs.append('Using ipywidgets bridge for comms')
            except Exception:
                if getattr(self, 'debug', False):
                    with self.thread_lock:
                        self.logs.append('Failed to create ipywidgets bridge')
            return

        # If explicitly requested, perform IPython Comm registration (best-effort)
        try:
            get_ipython().kernel.comm_manager.register_target(
                self.target_name,
                self.register_target_cb)
        except Exception:
            with self.thread_lock:
                self.logs.append('Failed to register IPython Comm target')
        # Ensure we have a post-execute hook to flush any queued events
        self.register_post_execute()

    # Shared-objects listener registration API
    @classmethod
    def add_shared_listener(cls, fn):
        """Register a callable to be invoked on shared_objects updates.

        The callable will be called with a single argument: a dict of changed
        name->value pairs. Callbacks are invoked in a daemon thread so they
        should be thread-safe. Returns True if added.
        """
        try:
            if not callable(fn):
                return False
            with cls.thread_lock:
                if fn not in cls._shared_listeners:
                    cls._shared_listeners.append(fn)
            return True
        except Exception:
            return False

    # set/get_shared_loop removed — listeners are awaited directly in the
    # async handler and synchronous listeners run in the event loop executor.

    @classmethod
    def remove_shared_listener(cls, fn):
        """Remove a previously-registered shared_objects listener."""
        try:
            with cls.thread_lock:
                if fn in cls._shared_listeners:
                    cls._shared_listeners.remove(fn)
            return True
        except Exception:
            return False

    @classmethod
    def clear_shared_listeners(cls):
        """Remove all registered shared_objects listeners and return the count removed."""
        try:
            with cls.thread_lock:
                n = len(cls._shared_listeners)
                cls._shared_listeners.clear()
            return n
        except Exception:
            return 0

    @classmethod
    def clear_shared_listner(cls):
        """Compatibility alias for clear_shared_listeners (typo-friendly)."""
        return cls.clear_shared_listeners()

    def register_target_cb(self, comm, msg):
        """Register the IPython Comm connection callback and install message handlers."""
        # IPython Comm is not thread-aware; protect assignment anyway
        with self.thread_lock:
            self.target_comm = comm
            if getattr(self, 'debug', False):
                self.logs.append(f"register_target_cb: {self.target_comm}")

        @comm.on_msg
        def _recv(msg):
            self.handle_recv(msg)

        @comm.on_close
        def _close():
            self.target_comm = None

    def unregister_target_cb(self):
        """Unregister and close the IPython Comm connection."""
        with self.thread_lock:
            if self.target_comm:
                self.target_comm.close()
            self.target_comm = None

    def _post_execute_handler(self, *args, **kwargs):
        """Post-execute handler to flush queued recv events.

        Some frontends (and ipywidgets-based backends) rely on processing
        queued events after a cell finishes execution. Registering a
        `post_execute` hook helps ensure any events that arrived while a
        cell was executing are drained and surfaced to diagnostics.
        """
        try:
            drained = 0
            while True:
                try:
                    ev = self.recv_events.get_nowait()
                except queue.Empty:
                    break
                drained += 1
                with self.thread_lock:
                    # Keep a compact diagnostic of the event
                    self.logs.append(f"post_execute: event {ev.get('type', 'unknown')}")
            if drained:
                with self.thread_lock:
                    self.logs.append(f"post_execute: flushed {drained} recv_events")
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"post_execute handler error: {e}")

    def register_post_execute(self):
        """Register the `_post_execute_handler` with IPython's post_execute event.

        Returns True if registration succeeded.
        """
        try:
            ip = get_ipython()
            if ip is None:
                return False
            try:
                ip.events.register('post_execute', self._post_execute_handler)
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('Registered post_execute handler for recv_events')
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(f"register_post_execute: logging registration message failed: {e}")
                return True
            except Exception:
                try:
                    with self.thread_lock:
                        self.logs.append('Failed to register post_execute handler')
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(f"register_post_execute: failed logging error: {e}")
                return False
            try:
                ip.events.register('post_execute', self._post_execute_handler)
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('Registered post_execute handler for recv_events')
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(f"register_post_execute: logging registration message failed: {e}")
                return True
            except Exception:
                try:
                    with self.thread_lock:
                        self.logs.append('Failed to register post_execute handler')
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(f"register_post_execute: failed logging error: {e}")
                return False
        except Exception:
            return False

    def handle_recv(self, msg):
        """Handle a message received via IPython Comm (command response).

        Event-type messages are routed via the out-of-band socket; this method
        processes response messages delivered over IPython Comm.
        """
        # Normalize incoming payload
        try:
            if isinstance(msg['content']['data'], str):
                _data = json.loads(msg['content']['data'])
            else:
                _data = msg['content']['data']
        except Exception:
            with self.thread_lock:
                self.logs.append('Malformed comm message received')
            return

        # If the message contains an 'id' field treat it as a response
        _id = _data.get('id') if isinstance(_data, dict) else None
        if _id:
            with self.thread_lock:
                fut = self.pending_futures.pop(_id, None)
            if fut:
                try:
                    import asyncio as _asyncio
                    try:
                        is_asyncio = isinstance(fut, _asyncio.Future)
                    except Exception:
                        is_asyncio = False

                    if is_asyncio:
                        loop = None
                        try:
                            get_loop = getattr(fut, 'get_loop', None)
                            if callable(get_loop):
                                loop = get_loop()
                        except Exception:
                            loop = getattr(fut, '_loop', None)

                        if loop is not None and getattr(loop, 'is_running', lambda: False)():
                            loop.call_soon_threadsafe(fut.set_result, _data.get('payload'))
                        else:
                            fut.set_result(_data.get('payload'))
                    else:
                        fut.set_result(_data.get('payload'))
                except Exception:
                    with self.thread_lock:
                        self.logs.append(f"Error setting result for id {_id}")
                else:
                    with self.thread_lock:
                        self.logs.append(f"Unexpected response for id {_id}")
            return

        # Otherwise it's an event message: enqueue for consumers
        try:
            self.recv_events.put(_data)
        except Exception:
            with self.thread_lock:
                self.logs.append('Failed to enqueue recv event')
        return

    def send(self, msg):
        """Send a message via the IPython Comm channel."""
        with self.thread_lock:
            tc = self.target_comm
        if tc:
            # Prefer scheduling the send on the kernel I/O loop if available
            try:
                kernel = get_ipython().kernel
                io_loop = getattr(kernel, 'io_loop', None)
                if io_loop is not None and hasattr(io_loop, 'add_callback'):
                    try:
                        io_loop.add_callback(lambda: tc.send(msg))
                        return
                    except Exception:
                        # fall through to direct send but record diagnostic
                        with self.thread_lock:
                            self.logs.append('send(): io_loop.add_callback failed; falling back to direct send')
            except Exception:
                with self.thread_lock:
                    self.logs.append('send(): error obtaining kernel io_loop')
            return tc.send(msg)

        # No widget-bridge fallback supported; require active IPython Comm
        raise RuntimeError("No active Comm: GeoGebra().init() must be called in a notebook cell before sending commands.")

    # Widget-bridge fallback removed: rely on IPython Comm target only.

    async def send_recv(self, msg):
        """Send a message via IPython Comm and wait for response via out-of-band socket.
        
        This method:
        1. Generates a unique message ID (UUID)
        2. Sends the message via IPython Comm to the frontend
        3. Waits for the response to arrive via the out-of-band socket
        4. Raises GeoGebraAppletError if error events are received
        5. Returns the response payload
        
        The out-of-band response wait is governed by `self.oob_timeout` (in
        seconds). The default is 30 seconds but this can be overridden via
        the environment variable `GGB_OOB_TIMEOUT` or by setting the
        instance attribute `oob_timeout` before calling `send_recv`.
        For long-running operations, decompose into smaller steps.
        
        Args:
            msg (dict or str): Message to send (will be JSON-serialized).
        
        Returns:
            dict: Response payload from GeoGebra.
            
        Raises:
            asyncio.TimeoutError: If no response arrives within 3 seconds.
            GeoGebraAppletError: If the applet produces error events.
            
        Example:
            >>> response = await comm.send_recv({
            ...     "type": "command",
            ...     "payload": "A=(0,0)"
            ... })
        """
        try:
            if isinstance(msg, str):
                _data = json.loads(msg)
            else:
                _data = msg

            # Note: applet start handshake removed; rely on out-of-band responses.

            _id = str(uuid.uuid4())
            self.mid = _id
            msg['id'] = _id

            # Register a concurrent.futures.Future that client_handle will fulfill.
            fut = concurrent.futures.Future()
            with self.thread_lock:
                self.pending_futures[_id] = fut

            # If no OOB clients are connected, wait a short while for one to appear.
            with self.thread_lock:
                has_clients = bool(self.clients)
                has_target = self.target_comm is not None
            if not has_clients and not has_target:
                with self.thread_lock:
                    self.logs.append(f"No clients; waiting for client before sending {_id}")
                waited = 0.0
                while waited < 2.0:
                    with self.thread_lock:
                        if self.clients or self.target_comm:
                            break
                    await asyncio.sleep(0.05)
                    waited += 0.05

            # Send after registering the future to avoid races.
            self.send(json.dumps(_data))
            # Yield to the event loop to allow the OOB client handler to run
            await asyncio.sleep(0)

            # Schedule a watchdog to ensure the future doesn't hang indefinitely.
            loop = asyncio.get_running_loop()
            def _watchdog():
                if not fut.done():
                    try:
                        fut.set_exception(asyncio.TimeoutError("oob future timed out"))
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(f"_watchdog: failed to set exception on future: {e}")

            # Schedule watchdog using the instance-configurable timeout
            handle = loop.call_later(getattr(self, 'oob_timeout', 30.0), _watchdog)

            # Await the future (it will be set by client_handle or by watchdog)
            try:
                value = await asyncio.wrap_future(fut)
            finally:
                # cancel watchdog and remove mapping
                handle.cancel()
                with self.thread_lock:
                    self.pending_futures.pop(_id, None)
            
            # If response value is empty, check for error events
            if value is None:
                # Wait a bit for error events to arrive
                await asyncio.sleep(0.5)
                
                # Check for error events in recv_events
                error_messages = []
                while True:
                    try:
                        event = self.recv_events.get_nowait()
                        if event.get('type') == 'Error':
                            error_messages.append(event.get('payload', 'Unknown error'))
                    except queue.Empty:
                        break
                
                # If errors were collected, raise GeoGebraAppletError
                if error_messages:
                    combined_message = '\n'.join(error_messages)
                    raise GeoGebraAppletError(
                        error_message=combined_message,
                        error_type='AppletError'
                    )
            
            return value
        except (asyncio.TimeoutError, TimeoutError):
            # On timeout, raise the error
            print(f"TimeoutError in send_recv {msg}")
            raise

    @classmethod
    def kernel_comm_summary(cls):
        """Return a summary of kernel Comm targets and open comms.

        This helper inspects the running IPython kernel's CommManager and
        returns a serializable dict with:
          - targets: mapping of target_name -> callback name/type
          - comms: mapping of comm_id -> basic info (target_name, metadata)

        Useful for debugging from the kernel side to see which comm targets
        are registered and which comms are currently open.
        """
        ip = get_ipython()
        kernel = getattr(ip, 'kernel', None)
        cm = getattr(kernel, 'comm_manager', None)
        result = {'targets': {}, 'comms': {}}
        if cm is None:
            return result

        try:
            targets = getattr(cm, 'targets', {}) or {}
            for tname, cb in targets.items():
                try:
                    result['targets'][tname] = getattr(cb, '__name__', type(cb).__name__)
                except Exception as e:
                    result['targets'][tname] = str(cb)
        except Exception as e:
            result['targets_error'] = str(e)

        try:
            comms = getattr(cm, 'comms', {}) or {}
            for cid, comm in comms.items():
                try:
                    result['comms'][cid] = {
                        'target_name': getattr(comm, 'target_name', None),
                        'target_module': getattr(comm, 'target_module', None),
                        'metadata': getattr(comm, 'metadata', None)
                    }
                except Exception as e:
                    result['comms'][cid] = str(comm)
        except Exception as e:
            result['comms_error'] = str(e)

        return result

# Module-level singleton used by kernel extension loader and examples.
# Creating the instance is cheap; the out-of-band server only starts when
# `start()` is called by consumers.
try:
    ggb_comm_instance
except NameError:
    ggb_comm_instance = ggb_comm()


def kernel_comm_summary():
    """Convenience wrapper returning kernel comm summary.

    Returns the same dict as `ggb_comm.kernel_comm_summary()`.
    """
    try:
        return ggb_comm.kernel_comm_summary()
    except Exception:
        return {'targets': {}, 'comms': {}}
