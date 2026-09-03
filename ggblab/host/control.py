"""C0-A — control-channel comm: replies from the applet reach the kernel while a cell is running.

Kernel side: open a Comm (target 'ggblab-control'). The frontend never needs to handle this comm; it only
needs its comm_id. The relay (jupyter_server extension, see relay.py) sends `comm_msg` on the kernel's
CONTROL socket; ipykernel >= 6 dispatches comm messages on the control thread
(ipykernel 7.2.0 kernelbase.py: "control channel accepts all shell messages and some of its own").
The handler resolves the pending reply by req_id and sets a threading.Event; the shell thread, blocked
in `wait`, wakes up.
"""
from __future__ import annotations
import os, threading, uuid, time
from typing import Any, Callable


def kernel_id() -> str | None:
    """jupyter_server names connection files kernel-<kernel_id>.json."""
    try:
        from ipykernel import get_connection_file
        base = os.path.basename(get_connection_file())
    except Exception:
        return None
    if base.startswith("kernel-") and base.endswith(".json"):
        return base[len("kernel-"):-len(".json")]
    return None


class ControlComm:
    TARGET = "ggblab-control"

    def __init__(self) -> None:
        from comm import create_comm  # ipykernel 7 uses the `comm` package
        self._pending: dict[str, dict] = {}
        self._events: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self.comm = create_comm(target_name=self.TARGET, data={"role": "reply-channel"})
        self.comm.on_msg(self._on_msg)
        self.thread_seen: set[str] = set()

    @property
    def comm_id(self) -> str:
        return self.comm.comm_id

    # --- pending replies (req_id -> {event, data}) ---
    def new_request(self) -> str:
        rid = uuid.uuid4().hex[:12]
        with self._lock:
            self._pending[rid] = {"event": threading.Event(), "data": None, "t0": time.time()}
        return rid

    def wait(self, req_id: str, timeout: float = 10.0) -> Any:
        ent = self._pending.get(req_id)
        if ent is None:
            raise KeyError(req_id)
        if not ent["event"].wait(timeout):
            raise TimeoutError(f"no reply for {req_id} within {timeout}s")
        with self._lock:
            self._pending.pop(req_id, None)
        return ent["data"]

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._events.append(cb)

    # --- handler: runs on ipykernel's control thread when the relay sends comm_msg on CONTROL ---
    def _on_msg(self, msg: dict) -> None:
        self.thread_seen.add(threading.current_thread().name)
        data = msg.get("content", {}).get("data", {}) or {}
        rid = data.get("req_id")
        if rid and rid in self._pending:
            ent = self._pending[rid]
            ent["data"] = data.get("data")
            ent["event"].set()
        elif data.get("kind") == "event":
            for cb in self._events:
                try: cb(data)
                except Exception: pass
