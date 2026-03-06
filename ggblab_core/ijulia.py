"""Minimal Python interface for Julia (IJulia/PyCall) to interact with
the ggblab comm-bridge.

This module exports a tiny set of functions with simple signatures and
JSON-friendly inputs/outputs so they can be easily called from Julia via
`PyCall`/`PythonCall` or similar bridges.

Functions return plain Python types (dict/list/str) and raise `RuntimeError`
when required bridge modules are unavailable.

Quick snippet (Python)
-----------------------
>>> from ggblab_core.ijulia import start_bridge, request, request_json, stop_bridge
>>> # start bridge on ephemeral port
>>> state = start_bridge(port=0)
>>> host = '127.0.0.1'
>>> port = state.get('port')
>>> # send a simple function request
>>> resp = request({'type': 'function', 'payload': {'name': 'getVersion', 'args': []}}, host=host, port=port)
>>> print(resp)
>>> stop_bridge()

"""
from typing import Any, Optional
import json


def _import_server_client():
    try:
        import comm_bridge.server as _server  # type: ignore
        import comm_bridge.client as _client  # type: ignore
        return _server, _client
    except Exception:
        return None, None


def start_bridge(port: int = 0, timeout: float = 10.0) -> dict:
    """Start the local comm bridge server.

    Parameters
    - port: int = 0
        TCP port to bind the bridge to. Use ``0`` to request an ephemeral port.
    - timeout: float
        Server request timeout (passed to the bridge server startup).

    Returns
    - dict
        The bridge state dictionary as returned by ``comm_bridge.server.start_server``.

    Raises
    - RuntimeError if the bridge server module is not available.
    """
    server, _ = _import_server_client()
    if server is None:
        raise RuntimeError('comm_bridge.server not available')
    return server.start_server(port=port, timeout=timeout)


def stop_bridge() -> None:
    """Stop the locally started comm bridge.

    This will attempt to stop the bridge previously started by
    :pyfunc:`start_bridge`. If no bridge is running this function is a no-op.

    Raises
    - RuntimeError if the bridge server module is not available.
    """
    server, _ = _import_server_client()
    if server is None:
        raise RuntimeError('comm_bridge.server not available')
    return server.stop_server()


def request(payload: Any, host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> Any:
    """Send a request payload to the bridge and return the parsed reply.

    Parameters
    - payload: Any
        The object to send to the bridge. If not a string it will be JSON-encoded.
    - host: str
        Bridge host (default: ``127.0.0.1``).
    - port: int
        Bridge port (default: ``8765``).
    - timeout: float
        Socket/request timeout in seconds.

    Returns
    - Any
        The parsed bridge reply (typically a dict or primitive type).

    Raises
    - RuntimeError if the bridge client module is not available.
    """
    _, client = _import_server_client()
    if client is None:
        raise RuntimeError('comm_bridge.client not available')
    return client.request(payload, host=host, port=port, timeout=timeout)


def request_with_retry(payload: Any, host: str = '127.0.0.1', port: int = 8765,
                       timeout: float = 10.0, retries: int = 3, backoff: float = 0.5,
                       allow_get_reply: bool = True, poll_interval: float = 0.5,
                       poll_timeout: float = 5.0) -> Any:
    """Send a request with retry/backoff and optional stored-reply polling.

    This helper attempts to send the payload to the bridge and will retry
    failed attempts using exponential backoff. If all retries fail and
    ``allow_get_reply`` is true, the function will poll the bridge for a
    previously stored reply using the message id (if present in ``payload``).

    Parameters
    - payload: Any
    - host, port, timeout: connection params
    - retries: int
        Number of attempts to make (default 3).
    - backoff: float
        Base backoff in seconds used to compute exponential backoff.
    - allow_get_reply: bool
        When true and the payload contains an ``id``, poll the bridge via
        the ``get_reply`` op to attempt to retrieve a late reply.
    - poll_interval, poll_timeout: float
        Polling parameters for the stored-reply retrieval phase.

    Returns
    - Any: the bridge response if successful, or a dict with ``error``.
    """
    _, client = _import_server_client()
    if client is None:
        raise RuntimeError('comm_bridge.client not available')
    return client.request_with_retry(
        payload,
        host=host,
        port=port,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        allow_get_reply=allow_get_reply,
        poll_interval=poll_interval,
        poll_timeout=poll_timeout,
    )


def poll_reply(reply_id: str, host: str = '127.0.0.1', port: int = 8765, timeout: float = 5.0) -> Any:
    """Poll the bridge for a previously stored reply by ``reply_id``.

    Parameters
    - reply_id: str
        The message id originally sent to the bridge.
    - host, port, timeout: connection params

    Returns
    - Any: the stored reply, or a dict containing an ``error`` key if not found.
    """
    _, client = _import_server_client()
    if client is None:
        raise RuntimeError('comm_bridge.client not available')
    return client.poll_reply(reply_id, host=host, port=port, timeout=timeout)


def request_json(json_text: str, host: str = '127.0.0.1', port: int = 8765, timeout: float = 10.0) -> str:
    """Variant that accepts a JSON string and returns a JSON string.

    Useful for language-bridging (e.g., calling from Julia) where passing
    and receiving native Python objects is inconvenient. The input is
    parsed as JSON if possible; otherwise treated as a raw string. The
    returned value is a JSON string representing the bridge reply.
    """
    try:
        payload = json.loads(json_text)
    except Exception:
        # treat as raw string
        payload = json_text
    res = request(payload, host=host, port=port, timeout=timeout)
    try:
        return json.dumps(res)
    except Exception:
        return json.dumps({'reply': str(res)})


__all__ = [
    'start_bridge', 'stop_bridge', 'request', 'request_with_retry', 'poll_reply', 'request_json'
]
