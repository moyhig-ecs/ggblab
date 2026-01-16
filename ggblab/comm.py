import uuid
import json
# import ast
import queue

# import time
import asyncio
import threading

import tempfile
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
        recv_logs (dict): Response storage keyed by message ID
        recv_events (queue.Queue): Event queue for frontend notifications
    
    See:
        docs/architecture.md for detailed communication architecture.
    """
    # [Frontent to kernel callback - JupyterLab - Jupyter Community Forum]
    # (https://discourse.jupyter.org/t/frontent-to-kernel-callback/1666)
    recv_msgs = {}
    recv_logs = {}
    recv_events = queue.Queue()
    logs = []
    thread = None
    mid = None

    def __init__(self):
        self.target_comm = None
        self.target_name = 'ggblab-comm'
        self.server_handle = None
        self.server_thread = None
        self.clients = set()
        self.socketPath = None
        self.wsPort = 0

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
        if os.name in [ 'posix' ]:
            _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(self.socketPath)
            async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
                await asyncio.Future()
        else:
           async with serve(self.client_handle, "localhost", 0) as self.server_handle:
               self.wsPort = self.server_handle.sockets[0].getsockname()[1]
               self.logs.append(f"WebSocket server started at ws://localhost:{self.wsPort}")
               await asyncio.Future() 

    async def client_handle(self, client_id):
        self.clients.add(client_id)
        self.logs.append(f"Client {client_id} registered.")

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
                    # Response message: store in recv_logs for send_recv() to retrieve
                    self.recv_logs[_id] = _data['payload']
                else:
                    # Event message: queue for event processing
                    # Error handling is deferred to send_recv() for proper exception propagation
                    self.recv_events.put(_data)
        except Exception as e:
            pass
          # self.logs.append(f"Connection closed: {e}")
        finally:
            self.clients.remove(client_id)
          # self.logs.append(f"Client disconnected: {client_id}")

    # comm
    def register_target(self):
        get_ipython().kernel.comm_manager.register_target(
            self.target_name,
            self.register_target_cb)

    def register_target_cb(self, comm, msg):
        self.target_comm = comm

        @comm.on_msg
        def _recv(msg):
            self.handle_recv(msg)

        @comm.on_close
        def _close():
            self.target_comm = None

    def unregister_target_cb(self, comm, msg):
        self.target_comm.close()
        self.target_comm = None

    def handle_recv(self, msg):
        # Note: All event-type messages are now routed to recv_events via the
        # out-of-band socket (client_handle). This method is reserved for command
        # responses (messages with id) sent via IPython Comm.
        # 
        # IPython Comm cannot receive messages during cell execution, so real-time
        # error event processing happens on the out-of-band socket instead.
        if isinstance(msg['content']['data'], str):
            _data = json.loads(msg['content']['data'])
        else:
            _data = msg['content']['data']
        
        # All messages here are assumed to be responses with 'id'
        # (event messages are handled via client_handle in the out-of-band socket)

    def send(self, msg):
        return self.target_comm.send(msg)

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

            _id = str(uuid.uuid4())
            self.mid = _id
            msg['id'] = _id
            self.send(json.dumps(_data))
            
            # Wait for response with 3-second timeout
            async def wait_for_response():
                while not (_id in self.recv_logs):
                    await asyncio.sleep(0.01)
            
            await asyncio.wait_for(wait_for_response(), timeout=3.0)
            
            value = self.recv_logs.pop(_id, None)
            
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
