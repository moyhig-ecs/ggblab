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
import tempfile
import time
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
        except Exception:
            pass

        try:
            # Allow the server coroutine to exit its context and the thread to join
            if self.server_thread is not None:
                self.server_thread.join(timeout=1.0)
        except Exception:
            pass

        try:
            if self.server_handle is not None:
                # best-effort close; actual closure happens when server coroutine exits
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
                       try:
                           self.logs.append(f"WebSocket server started at ws://localhost:{self.wsPort}")
                       except Exception:
                           pass
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
              # _data = ast.literal_eval(msg)
                _data = json.loads(msg)
                _id = _data.get('id')
              # self.logs.append(f"Received message from client: {_id}")
                
                # Route event-type messages to recv_events queue
                # Messages with 'id' are command responses; messages without 'id' are events.
                # This enables:
                # - Real-time error capture during cell execution
                # - Dynamic scope learning from Applet error events
                # - Cross-domain error pattern analysis
                
                if _id:
                    # Response message: fulfill any waiting Future for this id
                    with self.thread_lock:
                        fut = self.pending_futures.pop(_id, None)
                    if fut:
                        try:
                            # Safely set the result on the waiting Future.
                            # Handle both asyncio.Future (must be set on its loop)
                            # and concurrent.futures.Future (thread-safe set_result).
                            import asyncio as _asyncio
                            try:
                                is_asyncio = isinstance(fut, _asyncio.Future)
                            except Exception:
                                is_asyncio = False

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
                                    loop.call_soon_threadsafe(fut.set_result, _data['payload'])
                                else:
                                    # Fallback: set directly (may raise if not allowed).
                                    fut.set_result(_data['payload'])
                            else:
                                # concurrent.futures.Future is safe to set from other threads
                                fut.set_result(_data['payload'])
                        except Exception:
                            # ignore set_result errors but record for diagnostics when debug
                            try:
                                if getattr(self, 'debug', False):
                                    with self.thread_lock:
                                        self.logs.append(f"Error setting result for id {_id}")
                            except Exception:
                                pass
                    else:
                        # No future waiting; quietly ignore unless debugging
                        try:
                            if getattr(self, 'debug', False):
                                with self.thread_lock:
                                    self.logs.append(f"Unexpected response for id {_id}")
                        except Exception:
                            pass
                else:
                    # Event message: queue for event processing
                    # Error handling is deferred to send_recv() for proper exception propagation
                    self.recv_events.put(_data)

                # yield to the event loop so other coroutines can make progress
                await asyncio.sleep(0)
        except Exception as e:
            # record connection errors for diagnostics instead of silently passing
            try:
                with self.thread_lock:
                    # record connection errors but avoid spamming; use same rate-limit
                    now = time.time()
                    if now - self._last_client_log_time > 5.0:
                        # Connection errors are notable; always record
                        self.logs.append(f"Connection error: {e}")
                        self._last_client_log_time = now
            except Exception:
                pass
            # self.logs.append(f"Connection closed: {e}")
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
    def register_target(self):
        """Register the IPython Comm target for frontend messages.

        Note: IPython Comm registration is disabled by default (see
        `self.use_ipython_comm`). Callers may enable it by setting that
        attribute to True before calling this method.
        """
        if not getattr(self, 'use_ipython_comm', False):
            # If widget-bridge creation is disabled, return early.
            if not getattr(self, 'enable_widget_bridge', False):
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('IPython Comm registration skipped (use_ipython_comm=False)')
                except Exception:
                    pass
                return

            # Otherwise attempt to create a minimal ipywidgets bridge (best-effort).
            if not _WIDGETS_AVAILABLE:
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('ipywidgets not available; IPython Comm registration skipped')
                except Exception:
                    pass
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
                            try:
                                with self.thread_lock:
                                    self.logs.append('Error handling widget bridge message')
                            except Exception:
                                pass

                    try:
                        self.widget_bridge.on_msg(_on_msg)
                    except Exception:
                        # Older ipywidgets may use different signature; ignore if not supported
                        pass

                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('Using ipywidgets bridge for comms')
                except Exception:
                    pass
            except Exception:
                try:
                    if getattr(self, 'debug', False):
                        with self.thread_lock:
                            self.logs.append('Failed to create ipywidgets bridge')
                except Exception:
                    pass
            return

        # If explicitly requested, perform IPython Comm registration (best-effort)
        try:
            get_ipython().kernel.comm_manager.register_target(
                self.target_name,
                self.register_target_cb)
        except Exception:
            try:
                with self.thread_lock:
                    self.logs.append('Failed to register IPython Comm target')
            except Exception:
                pass
        # Ensure we have a post-execute hook to flush any queued events
        try:
            self.register_post_execute()
        except Exception:
            pass

    def register_target_cb(self, comm, msg):
        """Register the IPython Comm connection callback and install message handlers."""
        # IPython Comm is not thread-aware; protect assignment anyway
        with self.thread_lock:
            self.target_comm = comm
            try:
                if getattr(self, 'debug', False):
                    self.logs.append(f"register_target_cb: {self.target_comm}")
            except Exception:
                pass

        @comm.on_msg
        def _recv(msg):
            self.handle_recv(msg)

        @comm.on_close
        def _close():
            self.target_comm = None

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
                        # fall through to direct send
                        pass
            except Exception:
                pass
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
                has_clients = bool(self.clients)
                has_target = self.target_comm is not None
            if not has_clients and not has_target:
                try:
                    with self.thread_lock:
                        self.logs.append(f"No clients; waiting for client before sending {_id}")
                except Exception:
                    pass
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
                except Exception:
                    result['targets'][tname] = str(cb)
        except Exception:
            pass

        try:
            comms = getattr(cm, 'comms', {}) or {}
            for cid, comm in comms.items():
                try:
                    result['comms'][cid] = {
                        'target_name': getattr(comm, 'target_name', None),
                        'target_module': getattr(comm, 'target_module', None),
                        'metadata': getattr(comm, 'metadata', None)
                    }
                except Exception:
                    result['comms'][cid] = str(comm)
        except Exception:
            pass

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
