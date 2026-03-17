"""Compatibility shim exposing a `connect()` helper under the `ggblab`
package namespace.

This module provides a canonical `connect(host, port)` function that
returns a `BridgeProxy` object with async methods `function`, `command`,
and `listen`. It delegates to the top-level `comm_bridge.client` request
implementation.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional


class BridgeProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port

    async def _request(self, payload: Any, timeout: Optional[float] = None):
        import importlib

        client = importlib.import_module("comm_bridge.client")
        return await asyncio.to_thread(client.request, payload, self.host, self.port, timeout or 10.0)

    async def function(self, name: str, args: Optional[list] = None, timeout: Optional[float] = None):
        resp = await self._request({"type": "function", "payload": {"name": name, "args": args}}, timeout)
        if isinstance(resp, dict):
            if "reply" in resp:
                resp = resp["reply"]
            if isinstance(resp, dict) and "payload" in resp:
                p = resp["payload"]
                if isinstance(p, dict) and "value" in p:
                    return p["value"]
            if "value" in resp:
                return resp["value"]
        return resp

    async def command(self, command: Any, timeout: Optional[float] = None):
        resp = await self._request({"type": "command", "payload": command}, timeout)
        if isinstance(resp, dict):
            return resp.get("reply", resp) or resp
        return resp

    async def listen(self, name: str, enabled: bool = True, timeout: Optional[float] = None):
        resp = await self._request({"type": "listen", "payload": [name, bool(enabled)]}, timeout)
        if isinstance(resp, dict):
            return resp.get("reply", resp) or resp
        return resp


def connect(host: str = "127.0.0.1", port: int = 8765, *, export_globals: bool = False) -> BridgeProxy:
    """Return a `BridgeProxy` for the given host/port.

    If `export_globals` is True, the proxy's methods will be installed on
    the `ggblab` module when this function is called (keeps older usage
    patterns working).
    """
    proxy = BridgeProxy(host=host, port=port)

    if export_globals:
        try:
            import sys

            mod = sys.modules.get("ggblab")
            if mod is not None:
                try:
                    setattr(mod, "function", proxy.function)
                    setattr(mod, "command", proxy.command)
                    setattr(mod, "listen", proxy.listen)
                except Exception:
                    pass
        except Exception:
            pass

    return proxy


__all__ = ["connect", "BridgeProxy"]
