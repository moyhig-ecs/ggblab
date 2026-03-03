"""Kernel-side synchronous Comm bridge.

Register a Comm target in the running IPython kernel and provide
`send_recv` which sends a message to the frontend and waits
synchronously for the reply.

This is minimal and suitable for testing with `ipylab`-injected
frontend panels that open a comm to the kernel.
"""
from typing import Any, Dict, Optional
import queue
import threading
import uuid
import logging
import json

from IPython.core.getipython import get_ipython

_log = logging.getLogger(__name__)


class KernelComm:
    """Register a kernel Comm target and allow synchronous request/response."""

    def __init__(self, target_name: str = 'jupyter.ggblab', timeout: float = 30.0):
        self.target_name = target_name
        self.timeout = float(timeout)
        self.comm = None
        self.pending: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()
        self._open_event = threading.Event()

    def register_target(self) -> None:
        """Register the comm target on the current IPython kernel."""
        ip = get_ipython()
        kernel = getattr(ip, 'kernel', None)
        if kernel is None:
            raise RuntimeError('No kernel available to register comm target')

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
                _log.exception('Error in _on_open')

        kernel.comm_manager.register_target(self.target_name, _on_open)

    def wait_for_open(self, timeout: Optional[float] = None) -> None:
        """Block until a frontend opens a comm to the registered target.

        Raises `TimeoutError` if no open arrives within `timeout` seconds.
        """
        if timeout is None:
            timeout = self.timeout
        ok = self._open_event.wait(timeout=timeout)
        if not ok:
            raise TimeoutError(f"No frontend opened a comm to target {self.target_name} within {timeout}s")

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
            content = msg.get('content', {})
            data = content.get('data')
            # frontend sends a JSON string (see ggblab frontend), so parse if needed
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    _log.debug('Received non-JSON data on comm: %r', content.get('data'))
                    return
            if not isinstance(data, dict):
                return
            _id = data.get('id')
            if not _id:
                return
            with self.lock:
                q = self.pending.get(_id)
            if q is not None:
                try:
                    q.put_nowait(data)
                except Exception:
                    _log.exception('Failed to enqueue reply for id %s', _id)
        except Exception:
            _log.exception('Error handling incoming comm message')

    def send_recv(self, msg: Dict[str, Any], timeout: Optional[float] = None) -> Any:
        """Send `msg` to the frontend comm and wait synchronously for reply.

        The message will be augmented with an `id` UUID. The frontend must
        reply with a message containing the same `id` inside the payload
        (in `content.data.id`).
        """
        if self.comm is None:
            raise RuntimeError('No comm open; ensure the frontend opened a comm or call register_target() before injection')

        if timeout is None:
            timeout = self.timeout

        _id = str(uuid.uuid4())
        payload = dict(msg)
        payload['id'] = _id

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
                _log.exception('Comm.send failed')
                raise

            try:
                data = q.get(timeout=timeout)
                return data
            except queue.Empty:
                raise TimeoutError(f'No reply for id {_id} after {timeout}s')
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
