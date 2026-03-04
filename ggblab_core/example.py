"""Example: kernel-side target registration and client usage.

Kernel-side registration (run inside the kernel/process that will
handle comms):

    from ipykernel.comm import Comm
    def handle_comm(comm, open_msg):
        @comm.on_msg
        def _recv(msg):
            data = msg['content']['data']
            # echo back a simple response
            comm.send({"echo": data})

    # register the target name used by the client
    get_ipython().kernel.comm_manager.register_target('ggblab_target', handle_comm)

Client-side usage (from an external process that can create a
BlockingKernelClient and connect to the same kernel):

    from jupyter_client import BlockingKernelClient
    from ggblab_core import CommSync

    kc = BlockingKernelClient()
    kc.load_connection_file('/path/to/connection-file.json')
    kc.start_channels()

    comm = CommSync(kc, 'ggblab_target', timeout=5.0)
    comm.open({'init': True})
    reply = comm.send({'cmd': 'ping'})
    print('reply', reply)
    comm.close()

"""

__all__ = ["example"]
