#!/usr/bin/env python3
"""
Simplified kernel launcher for ggblab development.

This launcher ensures the repository root is on PYTHONPATH so the
developer checkout can be imported without pip-installing, then starts
an IPython kernel bound to the connection file provided by Jupyter.

It is intentionally small and predictable. Use the accompanying
generate_kernelspec.py to write a kernelspec `kernel.json` that points
to this launcher.
"""
from __future__ import annotations

import argparse
import os
import sys

# Make repository root importable (assumes this file is in tools/ggblab_kernel/)
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    import ggblab  # noqa: F401
except Exception as e:  # pragma: no cover - best-effort import for dev
    print("Warning: failed to import ggblab at startup:", e, file=sys.stderr)

try:
    # Prefer launching in-process when available
    from ipykernel.kernelapp import IPKernelApp
except Exception:
    IPKernelApp = None


def main():
    # Sanitize argv to strip Jupyter application-scoped options that some
    # frontends pass (e.g. --_App.connection_file). This prevents
    # argparse in this launcher from treating them as unrecognized.
    try:
        _orig_argv = list(sys.argv)
        _parser = argparse.ArgumentParser(add_help=False)
        _parser.add_argument("-f", "--connection-file", dest="connection_file")
        # _parser.add_argument('--_App.connection_file', dest='connection_file')
        _known, _unknown = _parser.parse_known_args(_orig_argv[1:])
        _sanitized = [sys.argv[0]]
        if getattr(_known, "connection_file", None):
            _sanitized.extend(["-f", getattr(_known, "connection_file")])
        # If no connection file found but a bare json arg exists, use that
        if len(_sanitized) == 1:
            for a in _orig_argv[1:]:
                if a.endswith(".json") and not a.startswith("--"):
                    _sanitized.extend(["-f", a])
                    break
        if _sanitized != _orig_argv:
            sys.argv = _sanitized
    except Exception:
        # If anything goes wrong, leave sys.argv alone and continue
        pass

    parser = argparse.ArgumentParser(description="Simple ggblab kernel launcher")
    parser.add_argument(
        "-f",
        "--connection-file",
        dest="connection_file",
        help="Connection file path passed by Jupyter",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    if not args.connection_file:
        print("Expected -f <connection_file> argument from Jupyter", file=sys.stderr)
        sys.exit(2)

    if args.debug:
        print("[DEBUG] Repo root:", repo_root, file=sys.stderr)

    # Make sure child kernel process will import the repo when spawned
    os.environ["PYTHONPATH"] = repo_root + (
        os.pathsep + os.environ.get("PYTHONPATH", "")
        if os.environ.get("PYTHONPATH")
        else ""
    )

    argv = ["-f", args.connection_file]
    # If ipykernel is available, start in-process which matches Jupyter's expectation
    if IPKernelApp is not None:
        ggblab_flag = os.environ.get("GGBLAB_ENABLE", "").lower() in ("1", "true")

        if ggblab_flag:
            print(f"GGBLAB_ENABLE={ggblab_flag} (from environment variable)")

            # Subclass IPKernelApp to inject InteractiveShellApp.exec_lines
            class GGBlabApp(IPKernelApp):
                def initialize(self, argv=None):
                    # super().initialize(argv)
                    print("Injecting ggblab init into kernel config")
                    try:

                        from traitlets.config import Config

                        snippet = (
                            "from ggblab_core.applet import AppletInjector\n"
                            "from ggblab_core.applet import function_sync, command_sync\n"
                            "ggb = AppletInjector()\n"
                            "ggb.open(wait_for_open=False)"
                        )
                        c = Config()
                        existing = []
                        try:
                            existing = list(
                                getattr(
                                    self.config.InteractiveShellApp, "exec_lines", []
                                )
                                or []
                            )
                        except Exception:
                            existing = []
                        existing.append(snippet)
                        print(
                            "Injecting ggblab init into InteractiveShellApp.exec_lines:",
                            existing,
                        )
                        c.InteractiveShellApp.exec_lines = existing
                        self.update_config(c)
                    except Exception:
                        # Fail silently; kernel can still start without ggblab init
                        print(
                            "Failed to inject ggblab init into kernel config:",
                            file=sys.stderr,
                        )
                        pass
                    super().initialize(argv)

            try:
                GGBlabApp.launch_instance(argv=argv)
            except SystemExit:
                return
            except Exception as e:
                print(
                    "Failed to launch in-process ipykernel (with ggblab init):",
                    e,
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            try:
                IPKernelApp.launch_instance(argv=argv)
            except SystemExit:
                return
            except Exception as e:
                print("Failed to launch in-process ipykernel:", e, file=sys.stderr)
                sys.exit(1)

    # Fallback: spawn a subprocess using the same python interpreter
    kernel_cmd = [sys.executable, "-m", "ipykernel_launcher"] + argv
    os.execvpe(kernel_cmd[0], kernel_cmd, os.environ)


if __name__ == "__main__":
    main()
