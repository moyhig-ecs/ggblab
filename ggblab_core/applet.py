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
from typing import Optional, Dict, Any
from .kernel_comm import get_kernel_comm


class AppletInjector:
    """Programmatically open the GeoGebra applet panel via `ipylab`.

    Parameters
    - kernel_id: optional kernel identifier string. If omitted, the injector
      will attempt to discover it via `ipykernel.connect.get_connection_file()`.
    - comm_target: the comm target name the frontend will use to communicate
      with the kernel (default: 'jupyter.ggblab').
    """

    def __init__(self, kernel_id: Optional[str] = None, comm_target: str = 'jupyter.ggblab'):
        self.kernel_id = kernel_id
        self.comm_target = comm_target

    def open(self, appName: str = 'suite', insertMode: str = 'split-right', socketPath: Optional[str] = None,
             register_kernel_comm: bool = True, wait_for_open: bool = True, wait_timeout: Optional[float] = None) -> Dict[str, Any]:
        """Open the applet using `ipylab` and return the payload sent.

        Raises `RuntimeError` if `ipylab` is not available in the environment.
        """
        try:
            import ipylab  # type: ignore
        except Exception:
            raise RuntimeError("ipylab is required to inject the applet from Python/JupyterLab")

        JupyterFrontEnd = getattr(ipylab, 'JupyterFrontEnd', None)
        if JupyterFrontEnd is None:
            raise RuntimeError("ipylab does not expose JupyterFrontEnd in this environment")

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
                m = re.search(r'kernel-(.*)\.json', cf)
                if m:
                    self.kernel_id = m.group(1)
            except Exception:
                self.kernel_id = None

        app = JupyterFrontEnd()
        payload = {
            'kernelId': self.kernel_id,
            'commTarget': self.comm_target,
            'insertMode': insertMode,
            'socketPath': socketPath,
            'appName': appName,
        }
        # Execute the frontend command used by the main ggblab extension
        try:
            app.commands.execute('ggblab:create', payload)
        except Exception as e:
            raise RuntimeError(f"Failed to execute frontend command: {e}")

        # Optionally wait for the frontend to open the comm we registered
        if register_kernel_comm and wait_for_open:
            try:
                kc = get_kernel_comm()
                kc.wait_for_open(timeout=wait_timeout)
            except Exception:
                # propagate timeout/other errors to caller
                raise

        return payload


def function_sync(name: str, args: Optional[list] = None, timeout: Optional[float] = None):
    """Call a GeoGebra API function synchronously via the kernel-side Comm.

    Returns the function result (frontend should return {'id': ..., 'value': ...}).
    """
    kc = get_kernel_comm()
    if not kc.is_open:
        # If the comm isn't open, try to wait a short while
        kc.wait_for_open(timeout=timeout or kc.timeout)
    resp = kc.send_recv({
        'type': 'function',
        'payload': {
            'name': name,
            'args': args
        }
    }, timeout=timeout)
    # ggblab frontend replies use { type: 'value', id, payload: { value: ... } }
    if isinstance(resp, dict):
        pl = resp.get('payload') or {}
        if 'value' in pl:
            return pl['value']
        # older format support: direct 'value' key
        if 'value' in resp:
            return resp['value']
    return resp


def command_sync(command: str, timeout: Optional[float] = None):
    """Execute a GeoGebra command synchronously via the kernel-side Comm.

    Returns the frontend response (may include 'label' or other metadata).
    """
    kc = get_kernel_comm()
    if not kc.is_open:
        kc.wait_for_open(timeout=timeout or kc.timeout)
    resp = kc.send_recv({
        'type': 'command',
        'payload': command
    }, timeout=timeout)
    # For commands the frontend returns { type: 'created'|'error', id, payload: ... }
    if isinstance(resp, dict):
        return resp.get('payload', resp)
    return resp
