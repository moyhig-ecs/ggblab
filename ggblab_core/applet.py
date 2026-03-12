"""Applet injector using `ipylab` to programmatically open the GeoGebra panel.

This module provides `AppletInjector` which asks `ipylab.JupyterFrontEnd`
to create the GeoGebra applet panel in the frontend and returns the
parameters that the frontend will use to connect (e.g., `commTarget`,
`kernelId`, `socketPath`). The injector does not try to manage the
frontend comm target from Python; the kernel-side comm target must be
registered separately (e.g., by the usual `ggblab` kernel registration).

Usage (in a JupyterLab session where `ipylab` is available):

    injector = AppletInjector(kernel_id, comm_target='jupyter.ggblab')
    info = injector.open(appName='suite', insertMode='split-right')

`info` will contain the payload sent to the frontend command and can be
used for diagnostics.
"""

from typing import Any, Dict, Optional

from .kernel_comm import get_kernel_comm

# Optional bridge helpers (used for proxy-response mode)
_py_comm_bridge = None
_bridge_client = None


def _import_comm_bridge():
    """Attempt to import comm_bridge.server/client via multiple strategies.

    Returns (server_mod, client_mod) or (None, None) if unavailable.
    """
    import importlib
    import importlib.util
    import os
    import sys

    names_to_try = [
        ("comm_bridge.server", "comm_bridge.client"),
        ("ggblab.comm_bridge.server", "ggblab.comm_bridge.client"),
        ("ggblab_core.comm_bridge.server", "ggblab_core.comm_bridge.client"),
    ]

    for sname, cname in names_to_try:
        try:
            server = importlib.import_module(sname)
            client = importlib.import_module(cname)
            return server, client
        except Exception:
            continue

    # As a last resort, try to load from a sibling "comm_bridge" directory
    # located at the repository root (two levels up from this file may vary).
    try_paths = [
        os.path.join(os.path.dirname(__file__), "..", "comm_bridge", "server.py"),
        os.path.join(os.getcwd(), "comm_bridge", "server.py"),
    ]

    for server_path in try_paths:
        try:
            server_path = os.path.abspath(server_path)
            client_path = (
                os.path.splitext(server_path)[0].replace("server", "client") + ".py"
            )
            if os.path.exists(server_path) and os.path.exists(client_path):
                spec_s = importlib.util.spec_from_file_location(
                    "comm_bridge.server", server_path
                )
                spec_c = importlib.util.spec_from_file_location(
                    "comm_bridge.client", client_path
                )
                if spec_s and spec_c:
                    server = importlib.util.module_from_spec(spec_s)
                    client = importlib.util.module_from_spec(spec_c)
                    sys.modules["comm_bridge.server"] = server
                    sys.modules["comm_bridge.client"] = client
                    spec_s.loader.exec_module(server)  # type: ignore
                    spec_c.loader.exec_module(client)  # type: ignore
                    return server, client
        except Exception:
            continue

    return None, None


_py_comm_bridge, _bridge_client = _import_comm_bridge()


class AppletInjector:
    """Programmatically open the GeoGebra applet panel via `ipylab`.

    Parameters
    - kernel_id: optional kernel identifier string. If omitted, the injector
      will attempt to discover it via `ipykernel.connect.get_connection_file()`.
    - comm_target: the comm target name the frontend will use to communicate
      with the kernel (default: 'jupyter.ggblab').
    """

    def __init__(
        self, kernel_id: Optional[str] = None, comm_target: str = "jupyter.ggblab"
    ):
        self.kernel_id = kernel_id
        self.comm_target = comm_target

    # If proxy mode started via `start_proxy_mode`, store bridge info here
    _proxy_bridge: Optional[Dict[str, Any]] = None

    def open(
        self,
        appName: str = "suite",
        insertMode: str = "split-right",
        socketPath: Optional[str] = None,
        register_kernel_comm: bool = True,
    ) -> Dict[str, Any]:
        """Open the applet using `ipylab` and return the payload sent.

        Raises `RuntimeError` if `ipylab` is not available in the environment.
        """
        try:
            import ipylab  # type: ignore
        except Exception:
            raise RuntimeError(
                "ipylab is required to inject the applet from Python/JupyterLab"
            )

        JupyterFrontEnd = getattr(ipylab, "JupyterFrontEnd", None)
        if JupyterFrontEnd is None:
            raise RuntimeError(
                "ipylab does not expose JupyterFrontEnd in this environment"
            )

        # Optionally register the kernel-side comm target before asking the
        # frontend to create the panel. This ensures the kernel is ready to
        # accept comm opens from the injected frontend.
        if register_kernel_comm:
            try:
                kc = get_kernel_comm()
                kc.register_target()
            except Exception:
                # Do not fail injection if registration is not possible;
                # caller can inspect logs. Re-raise only for unexpected errors.
                raise

        # Discover kernel id if not provided
        if self.kernel_id is None:
            try:
                import ipykernel.connect

                cf = ipykernel.connect.get_connection_file()
                import re

                m = re.search(r"kernel-(.*)\.json", cf)
                if m:
                    self.kernel_id = m.group(1)
            except Exception:
                self.kernel_id = None

        app = JupyterFrontEnd()
        payload = {
            "kernelId": self.kernel_id,
            "commTarget": self.comm_target,
            "insertMode": insertMode,
            "socketPath": socketPath,
            "appName": appName,
        }
        # Execute the frontend command used by the main ggblab extension
        try:
            app.commands.execute("ggblab:create", payload)
        except Exception as e:
            raise RuntimeError(f"Failed to execute frontend command: {e}")

        # Note: we do not block waiting for the comm to open here. Callers who
        # need to ensure a comm is open should call `get_kernel_comm().register_target()`
        # prior to injection and check `get_kernel_comm().is_open`.

        return payload

    @classmethod
    def start_proxy_mode(
        cls,
        appName: str = "suite",
        insertMode: str = "split-right",
        socketPath: Optional[str] = None,
        kernel_id: Optional[str] = None,
        comm_target: str = "jupyter.ggblab",
        register_kernel_comm: bool = True,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 0,
        bridge_timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """Inject the applet and start a local py_comm_bridge on an ephemeral port.

        Returns a dict with keys:
          - payload: the frontend payload sent by the injector
          - bridge: the dict returned by `start_bridge()` (includes bound `port`)
        """
        injector = cls(kernel_id=kernel_id, comm_target=comm_target)
        # In proxy-mode we don't register the kernel-side comm target here;
        # the bridge will handle comm registration/attachment.

        # Instantiate and start OOB server first so we can inject socketPath
        import importlib

        try:
            oob_mod = importlib.import_module("comm_bridge.OOB_Server")
            OOBClass = getattr(oob_mod, "OOB_Server")
        except Exception:
            OOBClass = None

        oob_instance = None
        if OOBClass is not None:
            try:
                oob_instance = OOBClass(oob_timeout=bridge_timeout, socket_path=socketPath)
                oob_instance.start()
            except Exception:
                oob_instance = None

        # Now start the main TCP bridge using the Comm_Server wrapper if available
        try:
            comm_mod = importlib.import_module("comm_bridge.Comm_Server")
            CommClass = getattr(comm_mod, "Comm_Server")
        except Exception:
            CommClass = None

        bridge_state = None
        if CommClass is not None:
            try:
                comm_inst = CommClass()
                bridge_state = comm_inst.start(port=bridge_port or 8765, timeout=bridge_timeout)
            except Exception:
                bridge_state = None
        else:
            # fallback to legacy module if present
            if _py_comm_bridge is None:
                raise RuntimeError("comm_bridge.server not available in this environment")
            bridge_state = _py_comm_bridge.start_server(port=bridge_port or 8765, timeout=bridge_timeout)

        # Remember bridge host/port for subsequent convenience calls
        try:
            bound_port = bridge_state.get("port") if isinstance(bridge_state, dict) else None
            if bound_port:
                cls._proxy_bridge = {"host": bridge_host, "port": bound_port}
        except Exception:
            cls._proxy_bridge = None

        # If we started an OOB unix socket, pass its path into the frontend payload
        socket_to_use = None
        if oob_instance is not None and getattr(oob_instance, "socket_path", None):
            socket_to_use = oob_instance.socket_path

        # If OOB server exposes a serve port (client-facing API), capture it
        serve_port = None
        if oob_instance is not None:
            serve_port = getattr(oob_instance, "serve_port", None) or getattr(oob_instance, "ws_port", None)

        # Finally open the frontend injector after the bridge is started so the
        # frontend can connect immediately without an artificial delay.
        try:
            payload = injector.open(
                appName=appName,
                insertMode=insertMode,
                socketPath=socket_to_use or socketPath,
                register_kernel_comm=False,
            )
        except Exception:
            # Best-effort: if injection fails, still return bridge state for
            # diagnostics.
            payload = {"kernelId": kernel_id, "commTarget": comm_target, "socketPath": socket_to_use}

        # Return tuple: (comm_server_instance or None, oob_server_instance or None, info_dict)
        info = {"payload": payload, "bridge": bridge_state, "serve_port": serve_port}
        try:
            comm_obj = comm_inst if 'comm_inst' in locals() else None
        except Exception:
            comm_obj = None
        return (comm_obj, oob_instance, info)

    @classmethod
    def function_sync(
        cls,
        name: str,
        args: Optional[list] = None,
        timeout: Optional[float] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """Call GeoGebra API function synchronously.

        If `port` is provided, the call is forwarded via the TCP bridge; otherwise
        the kernel-side Comm is used as before.
        """
        # If no explicit port, but proxy mode was started, use stored bridge
        use_port = port
        if use_port is None and getattr(cls, "_proxy_bridge", None):
            use_port = cls._proxy_bridge.get("port")

        def _unwrap_value(resp):
            # Try common response shapes and return inner 'value' when present
            try:
                if isinstance(resp, dict):
                    if "reply" in resp:
                        return _unwrap_value(resp.get("reply"))
                    if "payload" in resp:
                        return _unwrap_value(resp.get("payload"))
                    if "value" in resp:
                        return resp.get("value")
                return resp
            except Exception:
                return resp

        if use_port is not None:
            if _bridge_client is None:
                raise RuntimeError("bridge_client not available")
            payload = {"type": "function", "payload": {"name": name, "args": args}}
            resp = _bridge_client.request(
                payload,
                host=(
                    host or cls._proxy_bridge.get("host", "127.0.0.1")
                    if getattr(cls, "_proxy_bridge", None)
                    else (host or "127.0.0.1")
                ),
                port=use_port,
                timeout=timeout or 10.0,
            )
            # Bridge returns {'reply': ...} or {'error': ...}
            return _unwrap_value(resp)

        # Fallback to kernel-side Comm
        kc = get_kernel_comm()
        if not kc.is_open:
            try:
                kc.register_target()
            except Exception:
                pass
            if not kc.is_open:
                raise RuntimeError(
                    "Comm is not open; call register_target() or ensure frontend opened a comm"
                )
        resp = kc.send_recv(
            {"type": "function", "payload": {"name": name, "args": args}},
            timeout=timeout,
        )
        return _unwrap_value(resp)

    @classmethod
    def command_sync(
        cls,
        command: str,
        timeout: Optional[float] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """Execute a GeoGebra command synchronously. Uses bridge if `port` provided."""
        # If no explicit port, but proxy mode was started, use stored bridge
        use_port = port
        if use_port is None and getattr(cls, "_proxy_bridge", None):
            use_port = cls._proxy_bridge.get("port")

        if use_port is not None:
            if _bridge_client is None:
                raise RuntimeError("bridge_client not available")
            payload = {"type": "command", "payload": command}
            resp = _bridge_client.request(
                payload,
                host=(
                    host or cls._proxy_bridge.get("host", "127.0.0.1")
                    if getattr(cls, "_proxy_bridge", None)
                    else (host or "127.0.0.1")
                ),
                port=use_port,
                timeout=timeout or 10.0,
            )
            if isinstance(resp, dict):
                return resp.get("reply", resp) or resp
            return resp

        kc = get_kernel_comm()
        if not kc.is_open:
            try:
                kc.register_target()
            except Exception:
                pass
            if not kc.is_open:
                raise RuntimeError(
                    "Comm is not open; call register_target() or ensure frontend opened a comm"
                )
        resp = kc.send_recv({"type": "command", "payload": command}, timeout=timeout)
        if isinstance(resp, dict):
            return resp.get("payload", resp)
        return resp


def function_sync(
    name: str, args: Optional[list] = None, timeout: Optional[float] = None
):
    """Compatibility wrapper: call `AppletInjector.function_sync` using kernel Comm."""
    return AppletInjector.function_sync(name, args=args, timeout=timeout)


def command_sync(command: str, timeout: Optional[float] = None):
    """Compatibility wrapper: call `AppletInjector.command_sync` using kernel Comm."""
    return AppletInjector.command_sync(command, timeout=timeout)


async def function(
    name: str, args: Optional[list] = None, timeout: Optional[float] = None
):
    """Async wrapper around `function_sync` that runs the sync call in a thread.

    This ensures callers can `await ggblab_core.applet.function(...)` even when
    the underlying implementation is synchronous (bridge-backed).
    """
    import asyncio as _asyncio

    return await _asyncio.to_thread(function_sync, name, args, timeout)


async def command(command: str, timeout: Optional[float] = None):
    """Async wrapper around `command_sync` that runs the sync call in a thread."""
    import asyncio as _asyncio

    return await _asyncio.to_thread(command_sync, command, timeout)
