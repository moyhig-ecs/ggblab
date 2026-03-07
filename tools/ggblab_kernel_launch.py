#!/usr/bin/env python3
"""
Kernel entrypoint that ensures `ggblab` is importable and launches an IPython kernel.

This script is used by the kernelspec argv so Jupyter will start a kernel
that has `ggblab` available on import. It prepends the repository root to
`sys.path` so the developer checkout can be used without pip-installing.
"""
from __future__ import print_function

import os
import sys

# Make repository root importable (assumes this file is in tools/)
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    import ggblab  # noqa: F401
except Exception as e:
    print("Warning: failed to import ggblab at startup:", e, file=sys.stderr)

# Launch an IPython kernel instance
import argparse
import logging
import os
import time

from jupyter_client import KernelManager

try:
    # prefer launching in-process when available
    from ipykernel.kernelapp import IPKernelApp
except Exception:
    IPKernelApp = None


def monitor_kernel(km):
    # Try to get PID from KernelManager; fall back to attribute access
    pid = None
    if hasattr(km, "kernel") and getattr(km, "kernel") is not None:
        try:
            pid = km.kernel.pid
        except Exception:
            pid = None
    if pid is None and hasattr(km, "kernel_pid"):
        pid = getattr(km, "kernel_pid")

    try:
        while True:
            # If manager reports kernel is dead, break
            if hasattr(km, "is_alive") and not km.is_alive():
                break
            if pid is not None:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Launch a kernel subprocess via jupyter_client, making the repo importable"
    )
    parser.add_argument(
        "-f",
        "--connection-file",
        dest="connection_file",
        help="Connection file path passed by Jupyter",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    if not args.connection_file:
        print("Expected -f <connection_file> argument from Jupyter", file=sys.stderr)
        sys.exit(2)

    # Ensure repository root is importable by kernels we spawn
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # Prepare environment for the kernel subprocess or in-process kernel
    env = os.environ.copy()
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_root + (os.pathsep + old_pp if old_pp else "")

    logging.debug("Repo root: %s", repo_root)
    logging.debug("Effective PYTHONPATH: %s", env["PYTHONPATH"])

    # If ipykernel is available, launch kernel in-process which is the
    # expected behavior when Jupyter starts a kernel process. This avoids
    # confusion with subprocess PIDs and ensures the kernel binds to the
    # provided connection file.
    if IPKernelApp is not None:
        # Set PYTHONPATH in the process environment for the kernel
        os.environ["PYTHONPATH"] = env["PYTHONPATH"]
        argv = ["-f", args.connection_file]
        logging.debug("Launching in-process IPKernelApp with argv: %s", argv)
        try:
            IPKernelApp.launch_instance(argv=argv)
        except SystemExit:
            # IPKernelApp may call sys.exit; exit cleanly
            pass
        except Exception as e:
            print("Failed to launch in-process ipykernel:", e, file=sys.stderr)
            sys.exit(1)
        return

    # Fallback: spawn a subprocess via KernelManager
    kernel_cmd = [
        sys.executable,
        "-m",
        "ipykernel_launcher",
        "-f",
        args.connection_file,
    ]
    logging.debug("Will spawn subprocess kernel using kernel_cmd: %s", kernel_cmd)
    km = KernelManager()
    try:
        km.kernel_cmd = kernel_cmd
        km.start_kernel(env=env)
    except Exception as e:
        print(
            "Failed to start kernel subprocess via jupyter_client:", e, file=sys.stderr
        )
        sys.exit(1)

    print(
        "Kernel subprocess started (pid={})".format(
            getattr(km, "kernel_pid", getattr(km, "kernel", None))
        )
    )
    # Monitor child kernel until it exits
    try:
        monitor_kernel(km)
    finally:
        try:
            km.shutdown_kernel(now=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
