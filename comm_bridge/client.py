"""Bridge client used by non-Python kernels via PythonCall.

Relocated from `ggblab_core.bridge_client`.
Provides synchronous `send`/`get_reply` helpers and `retry_send`.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from typing import Any, Callable, Optional


def _parse_reply(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def request(payload: Any, host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> Any:
    data = payload
    if not isinstance(payload, (str, bytes)):
        try:
            data = json.dumps(payload)
        except Exception:
            data = str(payload)

    s: Optional[socket.socket] = None
    try:
        # If the server is present in the same process, try to use local_send
        try:
            import importlib
            pb = importlib.import_module('comm_bridge.server')
            state = getattr(pb, 'get_state', lambda: {})()
            if state.get('running') and hasattr(pb, 'local_send'):
                try:
                    return pb.local_send(payload, timeout=timeout)
                except Exception:
                    pass
        except Exception:
            pass

        s = socket.create_connection((host, port), timeout=timeout)
        s_file = s.makefile('rwb')
        line = (data.rstrip('\n') + '\n').encode('utf-8')
        s_file.write(line)
        s_file.flush()
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


def request_async(payload: Any, callback: Callable[[Any, Optional[Exception]], None], host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> threading.Thread:
    def _worker():
        try:
            reply = request(payload, host=host, port=port, timeout=timeout)
            try:
                callback(reply, None)
            except Exception:
                pass
        except Exception as e:
            try:
                callback(None, e)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def poll_reply(reply_id: str, host: str = '127.0.0.1', port: int = 8765, timeout: float = 5.0) -> Any:
    payload = {'op': 'get_reply', 'id': reply_id}
    return request(payload, host=host, port=port, timeout=timeout)


def request_with_retry(
    payload: Any,
    host: str = '127.0.0.1',
    port: int = 8765,
    timeout: float = 10.0,
    retries: int = 3,
    backoff: float = 0.5,
    allow_get_reply: bool = True,
    poll_interval: float = 0.5,
    poll_timeout: float = 5.0,
) -> Any:
    last_exc = None
    msg_id = None
    if isinstance(payload, dict):
        msg_id = payload.get('id')
        if not msg_id:
            try:
                msg_id = str(uuid.uuid4())
                payload = dict(payload)
                payload['id'] = msg_id
            except Exception:
                msg_id = None

    for attempt in range(max(1, int(retries))):
        try:
            return request(payload, host=host, port=port, timeout=timeout)
        except Exception as e:
            last_exc = e
            if attempt < (retries - 1):
                sleep_for = backoff * (2 ** attempt)
                try:
                    time.sleep(sleep_for)
                except Exception:
                    pass
                continue

    if allow_get_reply and msg_id:
        end = time.time() + float(poll_timeout)
        while time.time() < end:
            try:
                r = poll_reply(msg_id, host=host, port=port, timeout=poll_interval)
                if isinstance(r, dict) and r.get('error'):
                    pass
                else:
                    return r
            except Exception:
                pass
            try:
                time.sleep(poll_interval)
            except Exception:
                pass
        if last_exc is not None:
            raise last_exc
    return {'error': 'retry_send failed without exception'}


__all__ = ['request', 'request_async', 'poll_reply', 'request_with_retry']
