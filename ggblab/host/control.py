"""C0-A — control-channel delivery of applet replies (Jupyter hosts).

Design v2 (2026-09-03 evening, teacher's ruling: no ipywidgets, frontend polls): the kernel opens a *phantom comm* —
a comm registered only in this kernel's comm manager, with `primary=False` so no comm_open is ever published. No
frontend sees it, so nothing can reject it. The relay (relay.py) addresses a comm_msg to its comm_id on the kernel's
CONTROL socket; ipykernel dispatches it on the control thread once comm_* handlers are wired into `control_handlers`
(ipykernel wires them only into shell_handlers; IJulia dispatches both sockets through the same table). The handler
resolves the pending reply and the shell thread, blocked in `wait`, wakes up.
Verified headless 09-03: Python 1.51 s / Julia 1.58 s while the cell blocks; shell-socket negative control times out.
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


def wire_control_handlers() -> bool:
    """Register the comm_* handlers on ipykernel's control table (plain dict). No-op outside ipykernel."""
    try:
        from IPython import get_ipython
        k = getattr(get_ipython(), "kernel", None)
        if k is None or not hasattr(k, "control_handlers") or not hasattr(k, "comm_manager"):
            return False
        for t in ("comm_msg", "comm_close", "comm_open"):
            if t not in k.control_handlers and hasattr(k.comm_manager, t):
                k.control_handlers[t] = getattr(k.comm_manager, t)
        return True
    except Exception:
        return False


class ControlBridge:
    """Pending-reply table. `resolve()` is called from the widget's on_msg (control thread in Jupyter, or the reactive
    runtime elsewhere); `wait()` blocks the caller on an Event."""

    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}
        self._events: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self.thread_seen: set[str] = set()
        self.control_wired = wire_control_handlers()
        self.comm = None
        self.comm_id: str | None = None
        self._open_phantom_comm()

    TARGET = "ggblab_control"

    def _open_phantom_comm(self) -> None:
        """Kernel-private comm: registered here, never announced (primary=False => no comm_open on iopub)."""
        try:
            from comm import get_comm_manager
            from ipykernel.comm import Comm
        except Exception:
            return                                   # not an ipykernel (marimo / plain python): host supplies replies itself
        try:
            c = Comm(target_name=self.TARGET, primary=False)
            get_comm_manager().register_comm(c)
            c.on_msg(lambda msg: self.dispatch((msg.get("content") or {}).get("data") or {}))
            self.comm, self.comm_id = c, c.comm_id
        except Exception:
            self.comm, self.comm_id = None, None

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
            with self._lock:
                self._pending.pop(req_id, None)
            raise TimeoutError(f"no reply for {req_id} within {timeout}s")
        with self._lock:
            self._pending.pop(req_id, None)
        return ent["data"]

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._events.append(cb)

    def dispatch(self, content: dict) -> None:
        """content = {req_id?, kind?, data?} as posted by the browser (via relay -> phantom comm) or by a reactive host."""
        self.thread_seen.add(threading.current_thread().name)
        rid = content.get("req_id")
        if rid and rid in self._pending:
            ent = self._pending[rid]
            ent["data"] = content.get("data")
            ent["event"].set()
        elif content.get("kind") == "event":
            for cb in self._events:
                try: cb(content)
                except Exception: pass


# probe #1 (bare-comm mechanism test) keeps the old name
ControlComm = ControlBridge
