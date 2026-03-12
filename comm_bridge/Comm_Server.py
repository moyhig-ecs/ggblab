"""Wrapper exposing the original bridge API and a thin `Comm_Server` class.

`Comm_Server` is a small adapter that delegates to `comm_bridge.server`'s
module-level functions. This allows other modules (like the OOB server)
to reuse an interface without modifying the original `server.py`.
"""

from . import server as _server
from typing import Any


class Comm_Server:
    """Adapter around the original `comm_bridge.server` module.

    Methods mirror the module-level functions in `comm_bridge.server`.
    Subclasses may override any of these methods to provide alternative
    transport behaviour.
    """

    def __init__(self) -> None:
        pass

    def start(self, *args, **kwargs) -> Any:
        return _server.start_server(*args, **kwargs)

    def stop(self) -> Any:
        return _server.stop_server()

    def get_state(self) -> Any:
        return _server.get_state()

    def dump_bridge_state(self) -> Any:
        return _server.dump_bridge_state()

    def local_send(self, payload: Any) -> Any:
        return _server.local_send(payload)

    def register_comm_target(self, target_name: str) -> Any:
        return _server.register_comm_target(target_name)

    def unregister_comm_target(self, target_name: str) -> Any:
        return _server.unregister_comm_target(target_name)


# Backwards-compatible function aliases
start_server = _server.start_server
stop_server = _server.stop_server
get_state = _server.get_state
dump_bridge_state = _server.dump_bridge_state
local_send = _server.local_send
register_comm_target = _server.register_comm_target
unregister_comm_target = _server.unregister_comm_target

__all__ = [
    "Comm_Server",
    "start_server",
    "stop_server",
    "get_state",
    "dump_bridge_state",
    "local_send",
    "register_comm_target",
    "unregister_comm_target",
]
