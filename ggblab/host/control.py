"""C0-A — control-channel delivery of applet replies (Jupyter hosts).

Design (2026-09-03, after the browser diagnosis): no kernel-created comm target. The reply rides the *widget's own* comm
(ipywidgets/anywidget: open on both sides, so JupyterLab never rejects it). The relay (relay.py) sends an ipywidgets
`custom` message for that comm_id on the kernel's CONTROL socket; ipykernel dispatches it on the control thread once
comm_* handlers are wired into `control_handlers` (ipykernel wires them only into shell_handlers). The widget's
`on_msg` callback resolves the pending reply -> the shell thread, blocked in `wait`, wakes up.
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
        """content = {req_id?, kind?, data?} as posted by the browser (via relay) or sent by the widget model."""
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


# backwards-compatible name used by probe #1 (mechanism test with a bare comm)
class ControlComm(ControlBridge):
    TARGET = "ggblab-control"
    def __init__(self) -> None:
        super().__init__()
        from comm import create_comm
        self.comm = create_comm(target_name=self.TARGET, data={"role": "reply-channel"})
        self.comm.on_msg(lambda msg: self.dispatch(msg.get("content", {}).get("data", {}) or {}))
    @property
    def comm_id(self) -> str:
        return self.comm.comm_id
