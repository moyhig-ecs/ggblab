#!/usr/bin/env python3
"""
Simple Jupyter kernel adapter that runs Julia for each execution request.

Limitations:
- Stateless: each `execute_request` spawns a fresh `julia -e` process.
- No persistent Julia session or state shared between calls.

This is a minimal prototype intended for interactive testing from a
Jupyter terminal or as a kernelspec-launched kernel. For production use
you may want a persistent Julia subprocess or a full Jupyter kernel
implementation in Julia.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict

try:
    from ipykernel.kernelapp import IPKernelApp
    from ipykernel.kernelbase import Kernel
except Exception:
    # Allow syntax checks even when ipykernel isn't installed in this env
    Kernel = object  # type: ignore
    IPKernelApp = None  # type: ignore


class JuliaKernel(Kernel):
    implementation = "julia-adapter"
    implementation_version = "0.1"
    language = "julia"
    language_version = ""
    language_info = {
        "name": "julia",
        "mimetype": "text/x-julia",
        "file_extension": ".jl",
    }
    banner = "Julia adapter kernel (stateless; spawns julia -e per execute)"

    def do_execute(
        self,
        code: str,
        silent: bool,
        store_history: bool = True,
        user_expressions: Dict[str, Any] | None = None,
        allow_stdin: bool = False,
    ) -> Dict[str, Any]:
        code = code or ""
        if not code.strip():
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Run a fresh Julia process for each execute request. This keeps the
        # adapter extremely simple at the cost of losing session state.
        try:
            proc = subprocess.run(["julia", "-e", code], capture_output=True, text=True)
        except FileNotFoundError:
            err = "julia executable not found in PATH"
            if not silent:
                stream_content = {"name": "stderr", "text": err + "\n"}
                try:
                    # type: ignore[attr-defined]
                    self.send_response(self.iopub_socket, "stream", stream_content)
                except Exception:
                    pass
            return {
                "status": "error",
                "ename": "FileNotFoundError",
                "evalue": err,
                "traceback": [],
            }

        out = proc.stdout or ""
        err_out = proc.stderr or ""

        if not silent:
            if out:
                stream_content = {"name": "stdout", "text": out}
                try:
                    # type: ignore[attr-defined]
                    self.send_response(self.iopub_socket, "stream", stream_content)
                except Exception:
                    pass
            if err_out:
                stream_content = {"name": "stderr", "text": err_out}
                try:
                    # type: ignore[attr-defined]
                    self.send_response(self.iopub_socket, "stream", stream_content)
                except Exception:
                    pass

        if proc.returncode != 0:
            return {
                "status": "error",
                "ename": "JuliaError",
                "evalue": (err_out.strip() or "Julia process failed"),
                "traceback": [],
            }

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }


def main() -> int:
    if IPKernelApp is None:
        print(
            "ipykernel not available in this environment. This script is a kernel adapter and must be run where ipykernel is installed."
        )
        return 2

    # Configure IPKernelApp to use our JuliaKernel class and start the kernel
    try:
        app = IPKernelApp.instance()
        app.kernel_class = JuliaKernel
        app.initialize()
        app.start()
    except Exception as e:
        print("Failed to start Julia adapter kernel:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
