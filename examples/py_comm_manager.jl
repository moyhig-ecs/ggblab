# examples/py_comm_manager.jl
# Create a Python-side PyCommManager class and return an instance.

try
    using PyCall
catch e
    @warn "PyCall required for create_pycommmanager: $e"
end

function create_pycommmanager()
    # Define a simple Python class at runtime that holds target handlers
    py"""
class PyCommManager:
    def __init__(self):
        # mapping from target_name (str) to callable
        self.targets = {}
        self._send_callback = None

    def register_target(self, name, handler):
        self.targets[str(name)] = handler

    def unregister_target(self, name):
        self.targets.pop(str(name), None)

    def register_comm(self, name, handler):
        self.targets[str(name)] = handler

    def unregister_comm(self, name):
        self.targets.pop(str(name), None)

    def get_comm(self, name):
        return self.targets.get(str(name))

    def set_send_callback(self, cb):
        # cb should be a Python callable that accepts (comm_id, msg_json)
        self._send_callback = cb

    def send_to_julia(self, comm_id, msg_json):
        # Ask Julia to send this message for comm_id
        if self._send_callback is not None:
            try:
                self._send_callback(comm_id, msg_json)
            except Exception as e:
                print('PyCommManager.send_to_julia handler error:', e)
        else:
            print('No send callback set')

    def comm_open(self, target_name, comm, msg):
        # invoke the registered handler if present
        h = self.targets.get(str(target_name))
        if h is not None:
            try:
                h(comm, msg)
            except Exception as e:
                print('PyCommManager.comm_open handler error:', e)

    def comm_msg(self, comm, msg):
        # If msg contains a target_name, dispatch; otherwise try comm.target
        target = None
        if isinstance(msg, dict) and 'target_name' in msg:
            target = msg['target_name']
        elif hasattr(comm, 'target_name'):
            target = getattr(comm, 'target_name')
        if target is not None:
            h = self.targets.get(str(target))
            if h is not None:
                try:
                    h(comm, msg)
                except Exception as e:
                    print('PyCommManager.comm_msg handler error:', e)

    def comm_close(self, comm, msg):
        # noop by default
        pass
"""

    # Return an instance of the Python class
    return py"PyCommManager()"
end

export create_pycommmanager
