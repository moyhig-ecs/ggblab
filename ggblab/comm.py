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
    
    Comm target is fixed at 'ggblab-comm' because multiplexing via multiple
    targets would not solve the IPython Comm receive limitation.
    
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
    
    See:
        docs/architecture.md for detailed communication architecture.
        
    Note:
        This module focuses on communication primitives. Higher-level
        construction I/O and analysis helpers are provided in the optional
        ``ggblab_extra`` package; the core keeps communication and minimal
        shims only.
    
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
        self.target_name = 'ggblab-comm'
        self.server_handle = None
        self.server_thread = None
        self.clients = set()
        self.socketPath = None
        self.wsPort = 0
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

    # oob websocket (unix_domain socket in posix)
    def start(self):
        """Start the out-of-band socket server in a background thread.
        
        Creates a Unix domain socket (POSIX) or TCP WebSocket server (Windows)
        and runs it in a daemon thread. The server listens for GeoGebra responses.
        """
        self.server_thread = threading.Thread(target=lambda: asyncio.run(self.server()), daemon=True)
        self.server_thread.start()

    def stop(self):
        """Stop the out-of-band socket server."""
        self.server_handle.close()

    async def server(self):
        """Run the out-of-band socket server.

        Uses a Unix domain socket on POSIX systems and a TCP WebSocket otherwise.
        """
        if os.name in [ 'posix' ]:
            _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(self.socketPath)
            async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
                await asyncio.Future()
        else:
               async with serve(self.client_handle, "localhost", 0) as self.server_handle:
                   with self.thread_lock:
                       self.wsPort = self.server_handle.sockets[0].getsockname()[1]
                       try:
                           self.logs.append(f"WebSocket server started at ws://localhost:{self.wsPort}")
                       except Exception:
                           pass
                   await asyncio.Future()

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
                            fut.set_result(_data['payload'])
                            # try:
                            #     with self.thread_lock:
                            #         self.logs.append(f"Fulfilled future for id {_id}")
                            # except Exception:
                            #     pass
                        except Exception:
                            # ignore set_result errors but record
                            try:
                                with self.thread_lock:
                                    self.logs.append(f"Error setting result for id {_id}")
                            except Exception:
                                pass
                    else:
                        # No future waiting; log unexpected response
                        try:
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
        """Register the IPython Comm target for frontend messages."""
        get_ipython().kernel.comm_manager.register_target(
            self.target_name,
            self.register_target_cb)

    def register_target_cb(self, comm, msg):
        """Register the IPython Comm connection callback and install message handlers."""
        # IPython Comm is not thread-aware; protect assignment anyway
        with self.thread_lock:
            self.target_comm = comm
            try:
                self.logs.append(f"register_target_cb: {self.target_comm}")
            except Exception:
                pass

        @comm.on_msg
        def _recv(msg):
            self.handle_recv(msg)

        @comm.on_close
        def _close():
            self.target_comm = None

    def unregister_target_cb(self, comm, msg):
        """Unregister and close the IPython Comm connection."""
        with self.thread_lock:
            try:
                if self.target_comm:
                    self.target_comm.close()
            except Exception:
                pass
            self.target_comm = None

    def handle_recv(self, msg):
        """Handle a message received via IPython Comm (command response).

        Event-type messages are routed via the out-of-band socket; this method
        processes response messages delivered over IPython Comm.
        """
        if isinstance(msg['content']['data'], str):
            _data = json.loads(msg['content']['data'])
        else:
            _data = msg['content']['data']
        
        # All messages here are assumed to be responses with 'id'
        # (event messages are handled via client_handle in the out-of-band socket)

    def send(self, msg):
        """Send a message via the IPython Comm channel."""
        with self.thread_lock:
            tc = self.target_comm
        if tc:
            return tc.send(msg)
        else:
            raise RuntimeError("GeoGebra().init() must be called in a notebook cell before sending commands.")

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

            handle = loop.call_later(5.0, _watchdog)

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
