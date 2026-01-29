"""Communication primitives for GeoGebra frontend↔kernel messaging.

This module implements a dual-channel communication layer combining
IPython Comm with an out-of-band socket (Unix domain socket or WebSocket)
to ensure reliable message delivery while notebook cells execute.
"""
import uuid
import json
import queue
import concurrent.futures
import asyncio
import threading
import time
import tempfile
from websockets.asyncio.server import unix_serve, serve
import os

from IPython import get_ipython

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
    
    Comm target defaults to 'ggblab-comm'. Historically 'jupyter.widget'
    was used to integrate with ipywidgets, but the default was changed
    back to 'ggblab-comm' to preserve the original ggblab channel and
    avoid surprising behavior for callers that expect the ggblab comm
    target name.
    
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
    thread = None
    thread_lock = threading.Lock()
    mid = None
    # target_comm = None

    def __init__(self):
        """Initialize communication state and defaults."""
        self.target_comm = None
        # Default to the ggblab-specific comm target so callers that
        # expect the legacy channel ('ggblab-comm') continue to work.
        # Callers may still override by passing a different name to
        # `register_target(name)` if needed.
        self.target_name = 'ggblab-comm'
        # Out-of-band socket/server state (used for response delivery)
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

        # Whether a comm target registration has been performed.
        # This is False until `register_target` installs a handler and
        # `register_target_cb` is invoked by the IPython kernel on comm_open.
        self._registered = False
        # Flag set when a frontend OOB client explicitly notifies readiness
        # via a small event message (e.g. {'type':'oob_ready'}). This allows
        # send_recv() to detect readiness even if `clients` or `target_comm`
        # are not yet populated due to ordering races.
        self._oob_ready = False

        # Outbound message queue: messages queued when a Comm isn't yet
        # available but the target was registered. Messages are flushed
        # when `target_comm` becomes available or an OOB client signals
        # readiness.
        self._outbound_queue = []

        # Feature flag: when True, treat an incoming 'oob_ready' event as
        # equivalent to an applet 'start' event. This causes the kernel to
        # consider the applet started and also inject a synthetic 'start'
        # event into `recv_events` so existing consumers relying on the
        # previous 'start' message continue to work.
        # Default to True to integrate the frontend's explicit 'oob_ready'
        # into the legacy 'start' semantics.
        self.treat_oob_ready_as_start = True

        # NOTE: Do NOT automatically register the IPython Comm target here.
        # Registration must be requested explicitly by callers via
        # `ggb_comm.register_target()` (or by the frontend executing a
        # kernel-side registration snippet) so that target installation and
        # comm_open ordering can be coordinated by the frontend. Eager
        # registration caused transient targets and race conditions during
        # same-cell initialization.

    # oob websocket (unix_domain socket in posix)
    # Out-of-band socket server: run a helper server in a background thread
    # so the frontend can deliver responses during blocking cell execution.
    def start(self):
        """Start the out-of-band socket server in a background thread.

        Creates a Unix domain socket (POSIX) or TCP WebSocket server (Windows)
        and runs it in a daemon thread. The server listens for GeoGebra responses.
        """
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = threading.Event()

        self.server_thread = threading.Thread(target=lambda: asyncio.run(self.server()), daemon=True)
        self.server_thread.start()

    def stop(self):
        """Stop the out-of-band socket server."""
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
            if self.server_handle is not None:
                close = getattr(self.server_handle, 'close', None)
                if callable(close):
                    close()
        except Exception:
            pass

    async def server(self):
        """Run the out-of-band socket server.

        Uses a Unix domain socket on POSIX systems and a TCP WebSocket otherwise.
        """
        loop = asyncio.get_running_loop()
        if os.name in ['posix']:
            _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(self.socketPath)
            async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
                await loop.run_in_executor(None, self._stop_event.wait)
        else:
            async with serve(self.client_handle, "localhost", 0) as self.server_handle:
                with self.thread_lock:
                    self.wsPort = self.server_handle.sockets[0].getsockname()[1]
                    try:
                        self.logs.append(f"WebSocket server started at ws://localhost:{self.wsPort}")
                    except Exception:
                        pass
                await loop.run_in_executor(None, self._stop_event.wait)

    async def client_handle(self, client_id):
        """Handle messages from a connected websocket client.

        Routes command responses into `pending_futures` and event messages into `recv_events`.
        """
        with self.thread_lock:
            self.clients.add(client_id)
            self._client_connect_count += 1
            try:
                now = time.time()
                if now - self._last_client_log_time > 5.0:
                    self.logs.append(
                        f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                    )
                    self._client_connect_count = 0
                    self._client_disconnect_count = 0
                    self._last_client_log_time = now
            except Exception:
                pass

        try:
            async for msg in client_id:
                _data = json.loads(msg)
                _id = _data.get('id')
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
                                    loop.call_soon_threadsafe(fut.set_result, _data['payload'])
                                else:
                                    fut.set_result(_data['payload'])
                            else:
                                fut.set_result(_data['payload'])
                        except Exception:
                            try:
                                if getattr(self, 'debug', False):
                                    with self.thread_lock:
                                        self.logs.append(f"Error setting result for id {_id}")
                            except Exception:
                                pass
                    else:
                        try:
                            if getattr(self, 'debug', False):
                                with self.thread_lock:
                                    self.logs.append(f"Unexpected response for id {_id}")
                        except Exception:
                            pass
                else:
                    self.recv_events.put(_data)

                await asyncio.sleep(0)
        except Exception as e:
            try:
                with self.thread_lock:
                    now = time.time()
                    if now - self._last_client_log_time > 5.0:
                        self.logs.append(f"Connection error: {e}")
                        self._last_client_log_time = now
            except Exception:
                pass
        finally:
            with self.thread_lock:
                try:
                    self.clients.remove(client_id)
                except Exception:
                    pass
                self._client_disconnect_count += 1
                try:
                    now = time.time()
                    if now - self._last_client_log_time > 5.0:
                        self.logs.append(
                            f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                        )
                        self._client_connect_count = 0
                        self._client_disconnect_count = 0
                        self._last_client_log_time = now
                except Exception:
                    pass

    # comm
    def register_target(self, name: str = None):
        """Register the IPython Comm target for frontend messages.

        If `name` is provided, update `self.target_name` to the requested
        target before registering. Registration is a best-effort operation
        and respects `self.use_ipython_comm` and `self.enable_widget_bridge`.
        """
        if name:
            try:
                self.target_name = name
            except Exception:
                pass
        if not getattr(self, 'use_ipython_comm', False):
            # If IPython Comm registration is disabled, bail out.
            try:
                if getattr(self, 'debug', False):
                    with self.thread_lock:
                        self.logs.append('IPython Comm registration skipped (use_ipython_comm=False)')
            except Exception:
                pass
            return

        # If explicitly requested, perform IPython Comm registration (best-effort)
        try:
            # Ensure the out-of-band socket server is running so clients can
            # connect and responses can be delivered. Start it lazily here
            # if it hasn't been started already.
            try:
                if getattr(self, 'server_thread', None) is None:
                    try:
                        self.start()
                    except Exception:
                        # Best-effort: don't fail registration if OOB server can't start
                        pass
            except Exception:
                pass
            get_ipython().kernel.comm_manager.register_target(
                self.target_name,
                self.register_target_cb)
            # indicate registration attempt succeeded (handler installed)
            try:
                with self.thread_lock:
                    self._registered = True
            except Exception:
                pass
        except Exception:
            try:
                with self.thread_lock:
                    self.logs.append('Failed to register IPython Comm target')
            except Exception:
                pass
            return False

        # Ensure we have a post-execute hook to flush any queued events
        try:
            self.register_post_execute()
        except Exception:
            pass
        return True

    def register_target_cb(self, comm, msg):
        """Register the IPython Comm connection callback and install message handlers.

        Uses a shared handler attachment helper so the same logic can adopt
        Comm objects created elsewhere in the kernel (e.g. when user code
        calls `create_comm`/`Comm(...)`). This makes the instance robust to
        different Comm implementations and the ipykernel deprecation path.
        """
        # Attach handlers and adopt the comm object
        try:
            self._attach_comm_handlers(comm)
            with self.thread_lock:
                try:
                    self._registered = True
                except Exception:
                    pass
                if getattr(self, 'debug', False):
                    try:
                        self.logs.append(f"register_target_cb: {self.target_comm}")
                    except Exception:
                        pass
        except Exception:
            try:
                with self.thread_lock:
                    self.logs.append('Failed to attach handlers to incoming comm')
            except Exception:
                pass

    def adopt_comm(self, comm):
        """Public helper to adopt an externally-created Comm object.

        Call this from kernel-side code if you create a Comm manually and
        want `ggb_comm_instance` to use it for send/recv. Example:

            from ggblab.comm import ggb_comm_instance
            c = create_comm('ggblab-comm')  # or Comm(...)
            ggb_comm_instance.adopt_comm(c)

        The method is tolerant to different Comm implementations and will
        attach handlers as needed.
        """
        try:
            self._attach_comm_handlers(comm)
        except Exception:
            try:
                with self.thread_lock:
                    self.logs.append('adopt_comm: failed to adopt provided comm')
            except Exception:
                pass

    def _attach_comm_handlers(self, comm):
        """Internal helper to attach handlers to a Comm-like object.

        Supports objects exposing either decorator-based hooks (e.g.
        `@comm.on_msg`) or callback registration methods (e.g.
        `comm.on_msg(callback)`), and similarly for close events.
        The function stores the comm as `self.target_comm` under lock.
        """
        # Store reference under lock
        with self.thread_lock:
            self.target_comm = comm
            try:
                self._registered = True
            except Exception:
                pass

        # Attach message handler: support decorator or direct registration
        try:
            # decorator style: comm.on_msg(function) via decorator
            if hasattr(comm, 'on_msg') and callable(getattr(comm, 'on_msg')):
                try:
                    # Some implementations expect call: comm.on_msg(callback)
                    comm.on_msg(lambda msg: self.handle_recv(msg))
                except TypeError:
                    # Others use decorator (@comm.on_msg)
                    try:
                        @comm.on_msg
                        def _recv(msg):
                            self.handle_recv(msg)
                    except Exception:
                        pass
        except Exception:
            pass

        # Attach close handler: try multiple common patterns
        try:
            if hasattr(comm, 'on_close') and callable(getattr(comm, 'on_close')):
                try:
                    comm.on_close(lambda: self._on_comm_close())
                except TypeError:
                    try:
                        @comm.on_close
                        def _close():
                            self._on_comm_close()
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_comm_close(self):
        """Internal callback when the adopted comm is closed."""
        try:
            with self.thread_lock:
                self.target_comm = None
                try:
                    self._registered = False
                except Exception:
                    pass
        except Exception:
            pass

    def unregister_target_cb(self):
        """Unregister and close the IPython Comm connection."""
        with self.thread_lock:
            try:
                if self.target_comm:
                    self.target_comm.close()
            except Exception:
                pass
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
                try:
                    with self.thread_lock:
                        # Keep a compact diagnostic of the event
                        self.logs.append(f"post_execute: event {ev.get('type', 'unknown')}")
                except Exception:
                    pass
            if drained:
                try:
                    with self.thread_lock:
                        self.logs.append(f"post_execute: flushed {drained} recv_events")
                except Exception:
                    pass
        except Exception as e:
            try:
                with self.thread_lock:
                    self.logs.append(f"post_execute handler error: {e}")
            except Exception:
                pass

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
                except Exception:
                    pass
                return True
            except Exception:
                try:
                    with self.thread_lock:
                        self.logs.append('Failed to register post_execute handler')
                except Exception:
                    pass
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
            try:
                with self.thread_lock:
                    self.logs.append('Malformed comm message received')
            except Exception:
                pass
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
                    try:
                        with self.thread_lock:
                            self.logs.append(f"Error setting result for id {_id}")
                    except Exception:
                        pass
            else:
                try:
                    with self.thread_lock:
                        self.logs.append(f"Unexpected response for id {_id}")
                except Exception:
                    pass
            return

        # Otherwise it's an event message: enqueue for consumers
        try:
            # Detect explicit OOB-ready notification from frontend and set
            # internal readiness flag so send_recv() can proceed earlier.
            if isinstance(_data, dict) and _data.get('type') == 'oob_ready':
                try:
                    with self.thread_lock:
                        self._oob_ready = True
                        if getattr(self, 'debug', False):
                            self.logs.append('Received oob_ready from frontend')
                except Exception:
                    pass

                # Optionally treat oob_ready as an applet 'start' event
                try:
                    if getattr(self, 'treat_oob_ready_as_start', False):
                        start_event = {'type': 'start', 'payload': _data.get('payload')}
                        self.recv_events.put(start_event)
                        if getattr(self, 'debug', False):
                            with self.thread_lock:
                                self.logs.append('Translated oob_ready -> start event')
                except Exception:
                    pass

                # When oob_ready is received, flush any queued outbound messages
                try:
                    self._flush_outbound_queue()
                except Exception:
                    pass

            # Enqueue event messages for consumers
            self.recv_events.put(_data)
        except Exception:
            try:
                with self.thread_lock:
                    self.logs.append('Failed to enqueue recv event')
            except Exception:
                pass
        return

    def send(self, msg):
        """Send a message via the IPython Comm channel."""
        # Check current comm and registered state under lock
        with self.thread_lock:
            tc = self.target_comm
            registered = getattr(self, '_registered', False)

        # If no active comm but the target registration was performed,
        # queue the message for later delivery and return. This avoids
        # failing sends when the frontend's comm_open is racing the kernel.
        if not tc and registered:
            try:
                with self.thread_lock:
                    self._outbound_queue.append(msg)
                    if getattr(self, 'debug', False):
                        self.logs.append('Queued outbound message; will flush when comm available')
            except Exception:
                pass
            return

        # If still no comm and target not registered, raise a clearer error
        if not tc:
            raise RuntimeError(
                "No active Comm: Comm target not registered. "
                "Call ggb_comm_instance.register_target(<name>) in the kernel or ensure the frontend requests registration before sending."
            )

        # Prefer scheduling the send on the kernel I/O loop if available
        try:
            kernel = get_ipython().kernel
            io_loop = getattr(kernel, 'io_loop', None)
            if io_loop is not None and hasattr(io_loop, 'add_callback'):
                try:
                    def _do_send(tc_local=tc, mm=msg):
                        try:
                            tc_local.send(mm)
                        except Exception:
                            try:
                                if getattr(self, 'debug', False):
                                    with self.thread_lock:
                                        self.logs.append('Scheduled send failed; attempting direct send')
                            except Exception:
                                pass
                            try:
                                tc_local.send(mm)
                            except Exception:
                                try:
                                    if getattr(self, 'debug', False):
                                        with self.thread_lock:
                                            self.logs.append('Direct resend failed in scheduled _do_send')
                                except Exception:
                                    pass

                    io_loop.add_callback(_do_send)
                    return
                except Exception:
                    # fall through to direct send
                    pass
        except Exception:
            pass
        return tc.send(msg)

    def _flush_outbound_queue(self):
        """Flush queued outbound messages via the active Comm or OOB channel.

        This method attempts to send any messages queued while the Comm
        target was registered but not yet open. It's safe to call from
        different threads; it acquires `thread_lock` for coordination.
        """
        with self.thread_lock:
            if not self._outbound_queue:
                return
            queued = list(self._outbound_queue)
            self._outbound_queue.clear()

        # Attempt to send each queued message using existing send scheduling.
        for m in queued:
            try:
                # Use existing send path which will schedule on I/O loop
                # if available; this also handles serialization.
                try:
                    kernel = get_ipython().kernel
                    io_loop = getattr(kernel, 'io_loop', None)
                    if io_loop is not None and hasattr(io_loop, 'add_callback') and getattr(self, 'target_comm', None) is not None:
                        try:
                            io_loop.add_callback(lambda mm=m: self.target_comm.send(mm))
                            continue
                        except Exception:
                            pass
                except Exception:
                    pass

                if getattr(self, 'target_comm', None) is not None:
                    self.target_comm.send(m)
            except Exception:
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('Failed to flush queued outbound message')
                except Exception:
                    pass

    # Widget-bridge fallback removed: rely on IPython Comm target only.

    async def send_recv(self, msg):
        """Send a message via IPython Comm and wait for response via out-of-band socket.
        
        This method:
        1. Generates a unique message ID (UUID)
        2. Sends the message via IPython Comm to the frontend
        3. Waits for the response to arrive via the out-of-band socket
        4. Raises GeoGebraAppletError if error events are received
        5. Returns the response payload
        
        The 3-second timeout is sufficient for interactive operations.
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
                has_clients = bool(getattr(self, 'clients', None))
                has_target = self.target_comm is not None
                oob_ready = bool(getattr(self, '_oob_ready', False))
            if not has_clients and not has_target and not oob_ready:
                try:
                    with self.thread_lock:
                        self.logs.append(f"No clients; waiting for client before sending {_id}")
                except Exception:
                    pass
                waited = 0.0
                while waited < 2.0:
                    with self.thread_lock:
                        if getattr(self, 'clients', None) or self.target_comm or getattr(self, '_oob_ready', False):
                            break
                    await asyncio.sleep(0.05)
                    waited += 0.05

            # Send after registering the future to avoid races.
            try:
                self.send(json.dumps(_data))
            except RuntimeError as re:
                # If the kernel attempted to send before the frontend's
                # comm_open arrived, wait briefly (mitigate race) and retry.
                try:
                    msgtxt = str(re)
                except Exception:
                    msgtxt = ''
                if 'No active Comm' in msgtxt:
                    waited = 0.0
                    waited_ok = False
                    try:
                        with self.thread_lock:
                            self.logs.append(f"send_recv: send blocked, waiting for comm {_id}")
                    except Exception:
                        pass
                    while waited < 2.0:
                        with self.thread_lock:
                            if getattr(self, 'target_comm', None) or getattr(self, 'clients', None) or getattr(self, '_oob_ready', False):
                                waited_ok = True
                                break
                        await asyncio.sleep(0.05)
                        waited += 0.05
                    if waited_ok:
                        # retry send once
                        try:
                            self.send(json.dumps(_data))
                        except Exception:
                            # bubble up original RuntimeError if retry fails
                            raise
                    else:
                        # re-raise original RuntimeError with clearer context
                        raise RuntimeError(
                            "No active Comm after waiting for frontend; ensure the frontend opened the Comm target and retry."
                        )
                else:
                    raise
            # Yield briefly so comm handlers can process incoming messages
            await asyncio.sleep(0)

            # Schedule a watchdog to ensure the future doesn't hang indefinitely.
            loop = asyncio.get_running_loop()
            def _watchdog():
                if not fut.done():
                    try:
                        fut.set_exception(asyncio.TimeoutError("oob future timed out"))
                    except Exception:
                        pass

            handle = loop.call_later(3.0, _watchdog)

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

    def status(self):
        """Return a dict describing current comm registration/state.

        Useful for debugging from the kernel to inspect which comm target
        and comm object (if any) the instance is currently using.
        """
        try:
            with self.thread_lock:
                tc = self.target_comm
                try:
                    comm_id = getattr(tc, 'comm_id', None) or getattr(tc, 'commId', None) or getattr(tc, 'id', None)
                except Exception:
                    comm_id = None
                return {
                    'target_name': getattr(self, 'target_name', None),
                    'registered': bool(getattr(self, '_registered', False)),
                    'target_comm_id': comm_id,
                    'has_oob_clients': bool(getattr(self, 'clients', None)),
                    'socketPath': getattr(self, 'socketPath', None),
                    'wsPort': getattr(self, 'wsPort', None),
                }
        except Exception:
            return {
                'target_name': getattr(self, 'target_name', None),
                'registered': bool(getattr(self, '_registered', False)),
            }


    def report_comm_status():
        """Helper to find the module-level `ggb_comm_instance` (if present)
        and return its status. Returns None if no instance is found.
        """
        try:
            ip = get_ipython()
            user_ns = getattr(ip, 'user_ns', {}) if ip is not None else {}
            inst = user_ns.get('ggb_comm_instance') or globals().get('ggb_comm_instance')
            if inst is None:
                return None
            try:
                return inst.status()
            except Exception:
                return None
        except Exception:
            return None


# Module-level singleton for convenience and backwards compatibility.
# Older code and notebooks expect `ggb_comm_instance` to be available
# after `from ggblab.comm import ggb_comm_instance`.
try:
    ggb_comm_instance
except NameError:
    try:
        ggb_comm_instance = ggb_comm()
    except Exception:
        ggb_comm_instance = None

