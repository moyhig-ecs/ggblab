"""Applet injector for JupyterFrontEnd (ipylab) moved to ggblab_core2.

Provides `AppletInjector2` which encapsulates logic to open the GeoGebra
panel in JupyterLab via the `ipylab.JupyterFrontEnd` API. This isolates
frontend-specific code in the kernel-focused package.
"""

import asyncio
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit

import ipykernel.connect


class AppletInjector2:
    """Helper to open the GeoGebra frontend panel using ipylab's JFE.

    Methods return True on success, False on failure (no exception raised
    for normal failures so callers can fall back to alternate behavior).
    """

    def open_panel(
        self,
        kernelId: str,
        socketPath: str,
        appName: str = "suite",
        commTarget: str = "jupyter.ggblab",
        insertMode: str = "split-right",
    ) -> bool:
        """Attempt to open the GeoGebra panel in JupyterLab.

        Returns True if the panel was opened via `ipylab.JupyterFrontEnd`,
        False otherwise.
        """
        try:
            import ipylab  # type: ignore

            JupyterFrontEnd = getattr(ipylab, "JupyterFrontEnd", None)
            if JupyterFrontEnd is None:
                return False

            app = JupyterFrontEnd()
            # Best-effort execute the extension command; don't raise on errors
            try:
                app.commands.execute(
                    "ggblab:create",
                    {
                        "kernelId": kernelId,
                        "commTarget": commTarget,
                        "insertMode": insertMode,
                        "socketPath": socketPath,
                        "appName": appName,
                    },
                )
            except Exception:
                # Execution may fail silently depending on frontend state
                return False

            return True
        except Exception:
            return False

    def open(
        self,
        appName: str = "suite",
        insertMode: str = "split-right",
        socketPath: Optional[str] = None,
        register_kernel_comm: bool = True,
    ):
        """Open the frontend panel and initialize a GeoGebra instance.

        Returns an initialized `ggblab_core2.ggbapplet.GeoGebra` instance on
        success. Raises RuntimeError on failure to inject or initialize.
        """
        # Create GeoGebra instance early so setup_comm_and_kernel can attach
        # a comm instance and set kernel_id before frontend injection.
        GeoGebra = None
        try:
            from ggblab_core2.ggbapplet import GeoGebra as _Geo

            GeoGebra = _Geo
        except Exception:
            GeoGebra = None

        if GeoGebra is None or not hasattr(GeoGebra, "init"):
            try:
                from ggblab.ggbapplet import GeoGebra as _Geo2

                GeoGebra = _Geo2
            except Exception as e:
                raise RuntimeError(
                    f"Could not import GeoGebra controller from ggblab or ggblab_core2: {e}"
                )

        ggb = GeoGebra()

        # Attach comm and register target before injecting frontend so the
        # frontend can immediately connect to the already-registered handler.
        try:
            _setup = globals().get("setup_comm_and_kernel")
            if _setup is None:
                from ggblab_core2.applet import setup_comm_and_kernel as _setup

            if hasattr(ggb, "_run_sync"):
                ggb._run_sync(_setup(ggb))
            else:
                res = {}
                exc = {}

                def _t():
                    try:
                        res["v"] = asyncio.run(_setup(ggb))
                    except Exception as e:
                        exc["e"] = e

                th = threading.Thread(target=_t, daemon=True)
                th.start()
                th.join()
                if "e" in exc:
                    raise exc["e"]

            info = {
                "kernel_id": getattr(ggb, "kernel_id", None),
                "socketPath": getattr(getattr(ggb, "comm", None), "socketPath", None),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to setup comm before injection: {e}")

        # Validate appName early
        try:
            appName = validate_app_name(appName)
        except Exception:
            raise

        # Now inject the frontend; the frontend will connect to the registered
        # comm target and use the provided socketPath/kernel_id.
        opened = self.open_panel(
            kernelId=info.get("kernel_id"),
            socketPath=info.get("socketPath"),
            appName=appName,
            commTarget="jupyter.ggblab",
            insertMode=insertMode,
        )
        if not opened:
            raise RuntimeError("Failed to open GeoGebra panel in JupyterLab via ipylab")

        # Finally run the GeoGebra init sequence which may perform further
        # RPCs against the frontend now that the frontend is injected.
        try:
            if hasattr(ggb, "_run_sync"):
                ggb._run_sync(ggb.init(appName=appName, use_vscode=False))
            else:
                res2 = {}
                exc2 = {}

                def _t2():
                    try:
                        res2["v"] = asyncio.run(
                            ggb.init(appName=appName, use_vscode=False)
                        )
                    except Exception as e:
                        exc2["e"] = e

                th2 = threading.Thread(target=_t2, daemon=True)
                th2.start()
                th2.join()
                if "e" in exc2:
                    raise exc2["e"]
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize GeoGebra instance after injection: {e}"
            )

        return ggb


async def setup_comm_and_kernel(ggb) -> dict:
    """Start kernel-side comm bridge on `ggb` and discover kernel id.

    This function mirrors the initialization snippet previously located
    in `ggblab.ggbapplet` — it starts `ggb.comm`, waits for the
    out-of-band socket to be available, registers the comm target, and
    extracts the kernel id from the IPython connection file.

    Returns a dict with keys `kernel_id` and `socketPath`.
    """
    # Prefer the kernel-focused comm implementation in ggblab_core2, but
    # fall back to the original ggblab.comm if the former is unavailable.
    try:
        from ggblab_core2.comm import ggb_comm
    except Exception:
        try:
            from ggblab.comm import ggb_comm
        except Exception as e:
            raise RuntimeError("No ggb_comm implementation available") from e

    # Ensure we have a comm instance attached to the GeoGebra controller
    ggb.comm = ggb_comm()
    ggb.comm.start()
    while getattr(ggb.comm, "socketPath", None) is None:
        await asyncio.sleep(0.01)
    try:
        ggb.comm.register_target()
    except Exception:
        # best-effort; ignore registration failures
        pass

    try:
        _connection_file = ipykernel.connect.get_connection_file()
        m = re.search(r"kernel-(.*)\.json", _connection_file)
        ggb.kernel_id = m.group(1) if m else None
    except Exception:
        ggb.kernel_id = None

    return {
        "kernel_id": ggb.kernel_id,
        "socketPath": getattr(ggb.comm, "socketPath", None),
    }


async def publish_connection_for_vscode(ggb) -> bool:
    """Publish kernel/socket connection info for VS Code to consume.

    Writes `.vscode/ggblab.json` in the current workspace and attempts
    to copy the payload to the clipboard. Returns True on success.
    """
    try:
        payload = {
            "kernelId": getattr(ggb, "kernel_id", None),
            "socketPath": getattr(getattr(ggb, "comm", None), "socketPath", None),
        }

        # connection file path
        try:
            conn_file = ipykernel.connect.get_connection_file()
            payload["connection_file"] = conn_file
        except Exception:
            conn_file = None

        # Try to discover a running Jupyter server and token (best-effort)
        try:
            from jupyter_server.serverapp import list_running_servers

            servers = list(list_running_servers())
            if servers:
                srv = None
                try:
                    if conn_file and Path(conn_file).exists():
                        try:
                            with open(conn_file, "r", encoding="utf8") as cf:
                                conn_json = json.load(cf)
                        except Exception:
                            conn_json = {}
                        conn_ip = conn_json.get("ip") or conn_json.get("ip")
                        for s in servers:
                            raw_url = s.get("url") or s.get("server_url") or ""
                            if not raw_url:
                                continue
                            parts = urlsplit(raw_url)
                            host = parts.hostname
                            if (
                                conn_ip
                                and host
                                and (
                                    conn_ip == host
                                    or (
                                        conn_ip in ("127.0.0.1", "::1")
                                        and host in ("localhost", "127.0.0.1")
                                    )
                                )
                            ):
                                srv = s
                                break
                except Exception:
                    srv = None

                if srv is None:
                    srv = servers[0]

                base_url = srv.get("base_url") or srv.get("baseUrl") or None
                raw_url = srv.get("url") or srv.get("server_url") or None
                token = srv.get("token") or srv.get("password") or None
                if raw_url:
                    parts = urlsplit(raw_url)
                    qs = parse_qs(parts.query)
                    for k in ("token", "access_token"):
                        if k in qs and qs[k]:
                            token = token or qs[k][0]
                    base_no_q = urlunsplit(
                        (parts.scheme, parts.netloc, parts.path or "/", "", "")
                    )
                    if (not base_url) or (str(base_url).strip() == "/"):
                        base_url = base_no_q
                if base_url:
                    payload["baseUrl"] = base_url
                payload["token"] = token or ""
        except Exception:
            # ignore if jupyter_server is not available
            pass

        # Write to .vscode/ggblab.json in cwd (best-effort workspace)
        try:
            ws_file = Path.cwd() / ".vscode" / "ggblab.json"
            ws_file.parent.mkdir(parents=True, exist_ok=True)
            with open(ws_file, "w", encoding="utf8") as fh:
                json.dump(payload, fh, indent=2)
        except Exception:
            pass

        # Try to copy to clipboard via GeoGebra instance helper if present
        try:
            copy_fn = getattr(ggb, "copy_connection_to_clipboard", None)
            if copy_fn is not None:
                try:
                    await copy_fn()
                except Exception:
                    pass
            else:
                # Fallback: try pyperclip or pbcopy
                txt = json.dumps(payload)
                try:
                    import pyperclip

                    try:
                        pyperclip.copy(txt)
                    except Exception:
                        pass
                except Exception:
                    try:
                        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                        p.communicate(txt.encode("utf8"))
                    except Exception:
                        pass
        except Exception:
            pass

        return True
    except Exception:
        return False


def validate_app_name(appName: str) -> str:
    """Validate and normalize `appName` (raises ValueError on invalid names).

    Returns the normalized lowercase app name when valid.
    """
    valid_app_names = {
        "graphing",
        "geometry",
        "3d",
        "classic",
        "suite",
        "evaluator",
        "scientific",
        "notes",
    }
    try:
        appName_str = str(appName)
    except Exception:
        raise ValueError(f"Invalid appName: {appName!r}")
    appName_norm = appName_str.lower()
    if appName_norm not in valid_app_names:
        raise ValueError(
            f"Invalid appName '{appName}'; allowed values: {', '.join(sorted(valid_app_names))}"
        )
    return appName_norm
