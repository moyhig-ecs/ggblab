"""Bridge client used by non-Python kernels via PythonCall.

Provides a tiny synchronous TCP client that speaks the one-line-JSON
protocol used by `py_comm_bridge`. Intended to be called from Julia via
`PythonCall` (or directly from Python).

Functions:
  - send(payload, host='127.0.0.1', port=8765, timeout=10.0) -> dict
      Send `payload` (dict or JSON-serializable) and return parsed reply.

  - send_async(payload, callback, host='127.0.0.1', port=8765, timeout=10.0)
      Perform `send` in a background thread and invoke `callback(reply, error)`
      when the operation completes. `error` is None on success.
"""
from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Dict, Optional, Tuple


def _parse_reply(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def send(payload: Any, host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> Any:
    """Send a JSON payload to the bridge and return the parsed reply.

    The bridge protocol is one-line JSON per request/response. This
    function blocks until a response is received or a timeout occurs.
    """
    data = payload
    # If payload is bytes/str, forward as-is; otherwise JSON-serialize
    if not isinstance(payload, (str, bytes)):
        try:
            data = json.dumps(payload)
        except Exception:
            # fallback: convert to string
            data = str(payload)

    s: Optional[socket.socket] = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        # Use a file-like wrapper for convenient readline
        s_file = s.makefile('rwb')
        line = (data.rstrip('\n') + '\n').encode('utf-8')
        s_file.write(line)
        s_file.flush()
        # Read a single line response
        resp_bytes = s_file.readline()
        if not resp_bytes:
            raise RuntimeError('no response from bridge')
        text = resp_bytes.decode('utf-8', errors='replace').strip()
        return _parse_reply(text)
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def send_async(payload: Any, callback: Callable[[Any, Optional[Exception]], None], host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> threading.Thread:
    """Perform `send` in a background thread and call `callback(reply, error)`.

    Returns the `threading.Thread` instance. The callback is invoked in the
    background thread.
    """

    def _worker():
        try:
            reply = send(payload, host=host, port=port, timeout=timeout)
            try:
                callback(reply, None)
            except Exception:
                # callback exceptions are swallowed to avoid crashing the thread
                pass
        except Exception as e:
            try:
                callback(None, e)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


__all__ = ['send', 'send_async']
