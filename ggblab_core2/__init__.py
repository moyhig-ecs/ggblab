"""ggblab_core2

Kernel-focused core package extracted from `ggblab`.

This package contains the modules that directly depend on the communication
bridge (comm, ggbapplet, utils). Code was moved from `ggblab.*` to create a
clean separation for kernel-specific functionality used by `kernel2`.
"""

__all__ = [
    "comm",
    "ggbapplet",
    "utils",
]

import asyncio

from . import utils


def connect_to_bridge(host: str = "127.0.0.1", port: int = 0):
    """Configure ggblab_core2 to forward applet function/command calls to
    a bridge previously started by `ggblab_core.AppletInjector.start_proxy_mode`.

    After calling this, `ggblab_core2.ggbapplet.GeoGebra.function` and
    `...command` will be patched to call into
    `ggblab_core.applet.AppletInjector.function_sync/command_sync` with
    the provided host/port.
    """
    try:
        from . import ggbapplet as _ggbapplet
    except Exception as e:
        raise RuntimeError("ggblab_core2.ggbapplet not importable") from e

    try:
        pass
    except Exception as e:
        raise RuntimeError(
            "ggblab_core.applet not importable; ensure ggblab_core is installed"
        ) from e

    async def _bridge_function(self, name, args=None, timeout=None):
        # Use comm_bridge.client.request to send to the bridge directly.
        payload = {"type": "function", "payload": {"name": name, "args": args}}
        try:
            import importlib

            client = None
            for modname in (
                "comm_bridge.client",
                "ggblab.comm_bridge.client",
                "ggblab_core.comm_bridge.client",
            ):
                try:
                    client = importlib.import_module(modname)
                    break
                except Exception:
                    continue
            if client is None:
                raise RuntimeError("comm_bridge.client not available")
            # call request in thread to avoid blocking event loop
            resp = await asyncio.to_thread(
                client.request, payload, host, port, timeout or 10.0
            )
            # unwrap common shapes
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
        except Exception:
            raise

    async def _bridge_command(self, command, timeout=None):
        payload = {"type": "command", "payload": command}
        try:
            import importlib

            client = None
            for modname in (
                "comm_bridge.client",
                "ggblab.comm_bridge.client",
                "ggblab_core.comm_bridge.client",
            ):
                try:
                    client = importlib.import_module(modname)
                    break
                except Exception:
                    continue
            if client is None:
                raise RuntimeError("comm_bridge.client not available")
            resp = await asyncio.to_thread(
                client.request, payload, host, port, timeout or 10.0
            )
            if isinstance(resp, dict):
                return resp.get("reply", resp) or resp
            return resp
        except Exception:
            raise

    # Patch the GeoGebra class methods
    if hasattr(_ggbapplet, "GeoGebra"):
        setattr(_ggbapplet.GeoGebra, "function", _bridge_function)
        setattr(_ggbapplet.GeoGebra, "command", _bridge_command)
    else:
        raise RuntimeError("ggblab_core2.ggbapplet.GeoGebra not found")

    return True
