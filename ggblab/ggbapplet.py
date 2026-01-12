import asyncio
import re
import ipykernel.connect

from IPython.core.getipython import get_ipython
from ipylab import JupyterFrontEnd

from .comm import ggb_comm
from .construction import ggb_construction

class GeoGebra:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.initialized = False
        self.construction = ggb_construction()
  
    async def init(self):
        if not self.initialized:
            self.comm = ggb_comm()
            self.comm.start()
            while self.comm.socketPath is None:
                await asyncio.sleep(.01)
            self.comm.register_target()

            _connection_file = ipykernel.connect.get_connection_file()
            self.kernel_id = re.search(r'kernel-(.*)\.json', _connection_file).group(1)
            
            self.app = JupyterFrontEnd()
            self.app.commands.execute('ggblab:create', {
                'kernelId': self.kernel_id,
                'commTarget': 'test3',
                'insertMode': 'split-right',
                'socketPath': self.comm.socketPath,
              # 'wsPort': self.comm.wsPort,
            })
            
            self._initialized = True
        return self
    
    async def function(self, f, args=None):
        r = await self.comm.send_recv({
            "type": "function",
            "payload": {
                "name": f,
                "args": args
            }
        })
        return r['value']

    async def command(self, c):
        return await self.comm.send_recv({
            "type": "command",
            "payload": c
        })