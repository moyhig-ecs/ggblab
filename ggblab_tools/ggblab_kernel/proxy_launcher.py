"""Launcher for the ggblab local kernel.

This launcher respects the environment variable `GGBLAB_ENABLE` (set to
"1"/"true") to enable ggblab initialization. It avoids custom CLI
arguments to prevent conflicts with IPKernelApp's argument parsing.
"""

import logging
import os
import sys

# Early sanitize sys.argv to remove Jupyter's `--_App.connection_file` style
# arguments that some Jupyter frontends pass. Doing this before importing
# IPKernelApp prevents argparse in IPKernelApp from seeing unrecognized
# application-scoped flags.
_orig_argv = list(sys.argv)
# Use argparse.parse_known_args to robustly strip Jupyter's application-scoped
# flags (like --_App.connection_file) while preserving other legitimate args.
try:
    import argparse as _argparse

    _parser = _argparse.ArgumentParser(add_help=False)
    _parser.add_argument("-f", "--connection-file", dest="connection_file")
    # Accept the Jupyter application-style option too
    _parser.add_argument("--_App.connection_file", dest="connection_file")
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
        logging.getLogger(__name__).debug(
            "proxy_launcher: sanitized argv from %r to %r", _orig_argv, _sanitized
        )
        sys.argv = _sanitized
except Exception:
    # Fallback: leave sys.argv unchanged
    pass

# Ensure repository root is importable (similar to tools/ggblab_kernel_launch.py)
try:
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
except Exception:
    _repo_root = None

from ipykernel.kernelapp import IPKernelApp

# Configure basic logging to stderr if no handlers are present so DEBUG
# messages in this module (e.g. the GGBLAB_ENABLE debug line) are visible
# when the process is started by Jupyter (which may not set up logging).
root_logger = logging.getLogger()
if not root_logger.handlers:
    logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")

# Ensure this module's logger always emits DEBUG to stderr regardless of
# external logging configuration (some Jupyter launch paths set handlers
# and levels before our module runs, which can hide DEBUG messages).
_logger = logging.getLogger(__name__)
if not any(isinstance(h, logging.StreamHandler) for h in _logger.handlers):
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _logger.addHandler(_h)
_logger.setLevel(logging.DEBUG)


def main():
    from . import LocalKernel

    ggblab_flag = os.environ.get("GGBLAB_ENABLE", "").lower() in ("1", "true")
    print(f"GGBLAB_ENABLE={ggblab_flag} (from environment variable)")
    logging.getLogger("tornado").debug(
        "proxy_launcher: GGBLAB_ENABLE=%r", os.environ.get("GGBLAB_ENABLE")
    )

    class _App(IPKernelApp):
        def initialize(self, argv=None):
            super().initialize(argv)
            self.kernel_class_kwargs = getattr(self, "kernel_class_kwargs", {})
            if ggblab_flag:
                self.kernel_class_kwargs["ggblab_enabled"] = True
                # Also register exec_lines so IPython runs ggblab init in the
                # InteractiveShellApp startup sequence (makes symbols visible
                # in the interpreter immediately).
                try:
                    from traitlets.config import Config

                    snippet = (
                        "try:\n"
                        "    from ggblab_core.applet import AppletInjector, function_sync, command_sync\n"
                        "    ggb = AppletInjector()\n"
                        "    try:\n"
                        "        ggb.open(wait_for_open=False)\n"
                        "    except Exception:\n"
                        "        import logging; logging.exception('AppletInjector.open() failed')\n"
                        "    globals().setdefault('ggb', ggb)\n"
                        "    globals().setdefault('function_sync', function_sync)\n"
                        "    globals().setdefault('command_sync', command_sync)\n"
                        "except Exception:\n"
                        "    import logging; logging.exception('ggblab_core import/init failed')"
                    )
                    c = Config()
                    # preserve existing exec_lines if present
                    existing = []
                    try:
                        existing = list(
                            getattr(self.config.InteractiveShellApp, "exec_lines", [])
                            or []
                        )
                    except Exception:
                        existing = []
                    existing.append(snippet)
                    c.InteractiveShellApp.exec_lines = existing
                    self.update_config(c)
                except Exception:
                    # Fail silently; deferred init in kernel will still run.
                    pass

    # Sanitize sys.argv: keep just the program and the '-f <connection_file>' pair
    argv = [sys.argv[0]]
    connection = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        # -f <file>
        if a == "-f" and i + 1 < len(args):
            connection = args[i + 1]
            break
        # --_App.connection_file=<file> or --_App.connection_file <file>
        if a.startswith("--_App.connection_file="):
            connection = a.split("=", 1)[1]
            break
        if a == "--_App.connection_file" and i + 1 < len(args):
            connection = args[i + 1]
            break
        # any json filename passed as bare arg
        if a.endswith(".json"):
            connection = a
            break
        i += 1

    if connection:
        argv.extend(["-f", connection])
    # Pass sanitized argv directly to launch_instance to avoid IPKernelApp
    # trying to parse unrelated arguments that Jupyter may pass (e.g.
    # --_App.connection_file). This ensures only the -f <connection> pair
    # is considered by the kernel app.
    _App.launch_instance(argv=argv, kernel_class=LocalKernel)


if __name__ == "__main__":
    main()
