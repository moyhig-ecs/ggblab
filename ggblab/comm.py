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

class ggb_comm:
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
        self.server_thread = threading.Thread(target=lambda: asyncio.run(self.server()), daemon=True)
        self.server_thread.start()

    def stop(self):
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
                self.recv_logs[_id] = _data['payload']
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
        if isinstance(msg['content']['data'], str):
            _data = json.loads(msg['content']['data'])
        else:
            _data = msg['content']['data']
        # _id = _data.get('id')
        if 'id' not in _data:
            self.recv_events.put(_data)
        # if self.mid and self.mid == _id:
        #     self.recv_msgs[_id] = [_data]
        #     self.mid = None
        # else:
        #     if _id in self.recv_msgs:
        #         # self.recv_msgs[_id].append(_data)
        #     else:
        #         self.recv_msgs[_id] = [_data]

    def send(self, msg):
        return self.target_comm.send(msg)

    async def send_recv(self, msg):
        try:
            async with asyncio.timeout(3.0):
                if isinstance(msg, str):
                    _data = json.loads(msg)
                else:
                    _data = msg

                _id = str(uuid.uuid4())
                self.mid = _id
                msg['id'] = _id
                self.send(json.dumps(_data))
                
                while not (_id in self.recv_logs):
                    await asyncio.sleep(0.01)

                #       self.recv_msgs.pop(_id, None)
                value = self.recv_logs.pop(_id, None)
                return value
        except TimeoutError:
            print(f"TimeoutError in send_recv {msg}")
            return { 'type': 'error', 'message': 'TimeoutError in send_recv' }
