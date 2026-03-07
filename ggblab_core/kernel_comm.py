"""Kernel-side synchronous Comm bridge.

Register a Comm target in the running IPython kernel and provide
`send_recv` which sends a message to the frontend and waits
synchronously for the reply.

This is minimal and suitable for testing with `ipylab`-injected
frontend panels that open a comm to the kernel.
"""

import json
import logging
import queue
import threading
import uuid
from typing import Any, Dict, Optional

from IPython.core.getipython import get_ipython

_log = logging.getLogger(__name__)


class KernelComm:
    """Register a kernel Comm target and allow synchronous request/response."""

    def __init__(self, target_name: str = "jupyter.ggblab", timeout: float = 30.0):
        self.target_name = target_name
        self.timeout = float(timeout)
        self.comm = None
        self.pending: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()
        self._open_event = threading.Event()

    def register_target(self) -> None:
        """Register the comm target on the current IPython kernel."""
        ip = get_ipython()
        kernel = getattr(ip, "kernel", None)
        if kernel is None:
            raise RuntimeError("No kernel available to register comm target")

        def _on_open(comm, open_msg):
            try:
                self.comm = comm
                comm.on_msg(self._on_msg)
                # Signal that a comm has been opened
                try:
                    self._open_event.set()
                except Exception:
                    pass
            except Exception:
                _log.exception("Error in _on_open")

        kernel.comm_manager.register_target(self.target_name, _on_open)
        # In some cases the frontend may have opened a comm before the
        # kernel registered the target. Try to find any existing open comm
        # objects in the kernel's comm manager and attach to the first one
        # that matches our target name.
        try:
            cm = getattr(kernel, "comm_manager", None)
            if cm is not None:
                # Try common attribute names for open comm dicts
                comms_dict = None
                if hasattr(cm, "comms"):
                    comms_dict = cm.comms
                elif hasattr(cm, "_comms"):
                    comms_dict = cm._comms

                if comms_dict:
                    for cid, comm in list(comms_dict.items()):
                        try:
                            tname = getattr(comm, "target_name", None) or getattr(
                                comm, "target", None
                            )
                            if tname == self.target_name:
                                # attach to this comm
                                self.comm = comm
                                try:
                                    comm.on_msg(self._on_msg)
                                except Exception:
                                    pass
                                try:
                                    self._open_event.set()
                                except Exception:
                                    pass
                                break
                        except Exception:
                            _log.exception("Error while inspecting existing comm")
        except Exception:
            _log.exception("Failed to scan existing comms on register_target")

    # Removed compatibility helpers: callers should use `register_target()` and
    # check `is_open` for existing comm attachment.

    @property
    def is_open(self) -> bool:
        return self.comm is not None

    def _on_msg(self, msg: Dict[str, Any]) -> None:
        """Handle incoming comm messages from the frontend.

        Expects the frontend to send a message where the payload is in
        `msg['content']['data']` and contains an `id` key to correlate
        responses.
        """
        try:
            content = msg.get("content", {})
            data = content.get("data")
            # frontend sends a JSON string (see ggblab frontend), so parse if needed
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    _log.debug(
                        "Received non-JSON data on comm: %r", content.get("data")
                    )
                    return
            if not isinstance(data, dict):
                return
            _id = data.get("id")
            if not _id:
                return
            with self.lock:
                q = self.pending.get(_id)
            if q is not None:
                try:
                    q.put_nowait(data)
                except Exception:
                    _log.exception("Failed to enqueue reply for id %s", _id)
        except Exception:
            _log.exception("Error handling incoming comm message")

    def send_recv(self, msg: Dict[str, Any], timeout: Optional[float] = None) -> Any:
        """Send `msg` to the frontend comm and wait synchronously for reply.

        The message will be augmented with an `id` UUID. The frontend must
        reply with a message containing the same `id` inside the payload
        (in `content.data.id`).
        """
        if self.comm is None:
            raise RuntimeError(
                "No comm open; ensure the frontend opened a comm or call register_target() before injection"
            )

        if timeout is None:
            timeout = self.timeout

        _id = str(uuid.uuid4())
        payload = dict(msg)
        payload["id"] = _id

        q = queue.Queue(maxsize=1)
        with self.lock:
            self.pending[_id] = q

        try:
            # send via kernel-side Comm
            try:
                # Send JSON string so frontend code that does `JSON.parse(msg.content.data)`
                # receives a string and can parse it. Frontend expects `msg.content.data`
                # to be a JSON string, not a native JS object.
                self.comm.send(json.dumps(payload))
            except Exception:
                _log.exception("Comm.send failed")
                raise

            try:
                data = q.get(timeout=timeout)
                return data
            except queue.Empty:
                raise TimeoutError(f"No reply for id {_id} after {timeout}s")
        finally:
            with self.lock:
                self.pending.pop(_id, None)


# Module-level convenience instance
_kernel_comm_instance: Optional[KernelComm] = None


def get_kernel_comm() -> KernelComm:
    global _kernel_comm_instance
    if _kernel_comm_instance is None:
        _kernel_comm_instance = KernelComm()
    return _kernel_comm_instance


# Compatibility helper removed to reduce maintenance and confusion.


def describe_comm_manager() -> Dict[str, Any]:
    """Return a JSON-serializable summary of the kernel's comm manager.

    Useful for debugging: lists candidate attributes, counts, and
    sample keys/reprs for each candidate dict found.
    """
    out: Dict[str, Any] = {}
    ip = get_ipython()
    kernel = getattr(ip, "kernel", None)
    if kernel is None:
        out["error"] = "no-kernel"
        return out
    cm = getattr(kernel, "comm_manager", None)
    if cm is None:
        out["error"] = "no-comm-manager"
        return out

    candidates = {}
    for name in (
        "comms",
        "_comms",
        "_comms_by_msgid",
        "_targets_by_id",
        "_targets",
        "_target_to_comm",
    ):
        val = None
        try:
            if hasattr(cm, name):
                val = getattr(cm, name)
        except Exception:
            val = "<error>"
        if val is None:
            continue
        if isinstance(val, dict):
            try:
                sample_keys = list(val.keys())[:8]
                samples = []
                for k in sample_keys:
                    try:
                        samples.append({"key": k, "repr": repr(val[k])[:400]})
                    except Exception:
                        samples.append({"key": k, "repr": "<repr-error>"})
                candidates[name] = {
                    "type": "dict",
                    "count": len(val),
                    "sample": samples,
                }
            except Exception:
                candidates[name] = {
                    "type": type(val).__name__,
                    "info": "<error-inspecting>",
                }
        else:
            try:
                candidates[name] = {"type": type(val).__name__, "repr": repr(val)[:400]}
            except Exception:
                candidates[name] = {"type": type(val).__name__, "repr": "<repr-error>"}

    out["candidates"] = candidates
    return out


# (verbose attach helper removed)
