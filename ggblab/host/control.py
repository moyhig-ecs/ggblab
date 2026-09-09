"""Reply table for reactive hosts + `kernel_id()`.

C0-A — the phantom comm on the control socket (2026-09-03 → 09-09) — is retired (teacher's ruling (i), 09-09): the
Jupyter host (html_host.py) is now an HTTP client of its own server (relay.py, RPC), so nothing in this package opens a
comm, registers a comm target, or touches ipykernel's `control_handlers` any more. What remains here is the pending-reply
table that anywidget_host.py (mirror-read adapter for reactive runtimes: marimo / VS Code) feeds through model sync.
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


class ControlBridge:
    """Pending-reply table for hosts whose runtime delivers replies itself (reactive model sync). `dispatch()` resolves a
    pending request or fans an event out to listeners; `wait()` blocks the caller on an Event."""

    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}
        self._events: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self.thread_seen: set[str] = set()

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
        """content = {req_id?, kind?, data?} as delivered by the reactive host."""
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
