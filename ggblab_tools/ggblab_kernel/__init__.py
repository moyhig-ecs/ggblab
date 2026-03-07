"""ggblab_tools.ggblab_kernel

Lightweight in-process Python Jupyter kernel that executes code via
IPython InteractiveShell and exposes ggblab helpers when enabled.
"""

import contextlib
import io
import logging
import os
import sys

from ipykernel.kernelbase import Kernel
from IPython.core.interactiveshell import InteractiveShell

try:
    from ipykernel.comm import CommManager
except Exception:
    CommManager = None

LOG = logging.getLogger(__name__)


class LocalKernel(Kernel):
    implementation = "ggblab-local"
    implementation_version = "0.1"
    language = "python"
    language_version = sys.version.split()[0]
    language_info = {
        "name": "python",
        "mimetype": "text/x-python",
        "file_extension": ".py",
    }
    protocol_version = "5.3"
    banner = "ggblab local kernel (executes in-process)"

    def __init__(self, ggblab_enabled=False, **kwargs):
        super().__init__(**kwargs)
        # Allow enabling ggblab either via kernel kwargs or environment variable
        env_flag = os.environ.get("GGBLAB_ENABLE", "").lower() in ("1", "true", "yes")
        self.ggblab_enabled = bool(ggblab_enabled) or env_flag

        try:
            self._local_shell = InteractiveShell.instance()
        except Exception:
            self._local_shell = InteractiveShell()

        # Ensure CommManager available for frontends that use comms
        if CommManager is not None:
            try:
                try:
                    self.comm_manager = CommManager(parent=self)
                except TypeError:
                    try:
                        self.comm_manager = CommManager(kernel=self)
                    except TypeError:
                        self.comm_manager = CommManager()
            except Exception:
                self.comm_manager = None
        else:
            self.comm_manager = None

        # Make InteractiveShell aware of this kernel
        try:
            self._local_shell.kernel = self
        except Exception:
            LOG.exception("Failed to set InteractiveShell.kernel")

        # # Optionally initialize ggblab_core and export helpers into user namespace
        # if self.ggblab_enabled:
        #     # Defer initialization until the kernel appears to be fully started.
        #     # Start a daemon thread that waits for the kernel iopub socket to
        #     # be available and then performs ggblab initialization. This aims
        #     # to run after InteractiveShellApp.exec_lines have been processed
        #     # and avoids race conditions with comm targets from the frontend.
        #     def _deferred_init():
        #         try:
        #             # wait for iopub_socket to appear (kernel app has finished setup)
        #             for _ in range(200):
        #                 if getattr(self, 'iopub_socket', None) is not None:
        #                     break
        #                 time.sleep(0.05)

        #             # small grace period to let exec_lines run
        #             time.sleep(0.2)

        #             try:
        #                 from ggblab_core.applet import AppletInjector, function_sync, command_sync
        #             except Exception:
        #                 LOG.exception("ggblab_core not available or failed to import")
        #                 return

        #             try:
        #                 ggb = AppletInjector()
        #                 try:
        #                     ggb.open()
        #                 except Exception:
        #                     LOG.exception("AppletInjector.open() failed")
        #                 # Export to shell user namespace for cell access
        #                 try:
        #                     ns = getattr(self._local_shell, 'user_ns', None)
        #                     if ns is not None:
        #                         ns.setdefault("ggb", ggb)
        #                         ns.setdefault("function_sync", function_sync)
        #                         ns.setdefault("command_sync", command_sync)
        #                 except Exception:
        #                     LOG.exception("Failed to inject ggblab helpers into user_ns")
        #             except Exception:
        #                 LOG.exception("Error during ggblab initialization")
        #         except Exception:
        #             LOG.exception("Deferred ggblab init thread error")

        #     t = threading.Thread(target=_deferred_init, name="ggblab-init", daemon=True)
        #     t.start()

        # Provide a simple display_pub bridge for InteractiveShell
        try:

            class _DirectDisplayPub:
                def __init__(self, kernel):
                    self.kernel = kernel
                    self.is_publishing = False

                def publish(self, data, metadata=None, source=None):
                    try:
                        content = {"data": data, "metadata": metadata or {}}
                        self.kernel.send_response(
                            self.kernel.iopub_socket, "display_data", content
                        )
                    except Exception:
                        LOG.exception("Failed to publish display data")

            if getattr(self, "display_pub", None) is None:
                self.display_pub = _DirectDisplayPub(self)
            self._local_shell.display_pub = self.display_pub
        except Exception:
            LOG.exception("Failed to attach display_pub")

    def do_execute(
        self, code, silent, store_history=True, user_expressions=None, allow_stdin=False
    ):
        if not code.strip():
            return {"status": "ok", "execution_count": self.execution_count}

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(stderr_buf),
            ):
                res = self._local_shell.run_cell(code)

            out_text = stdout_buf.getvalue()
            err_text = stderr_buf.getvalue()

            if out_text:
                self.send_response(
                    self.iopub_socket, "stream", {"name": "stdout", "text": out_text}
                )
            if err_text:
                self.send_response(
                    self.iopub_socket, "stream", {"name": "stderr", "text": err_text}
                )

            if res.error_in_exec:
                tb = []
                if getattr(res, "error_before_exec", None):
                    tb = [str(res.error_before_exec)]
                elif getattr(res, "error_in_exec", None):
                    tb = [str(res.error_in_exec)]
                err = {
                    "ename": (
                        type(res.error_in_exec).__name__ if res.error_in_exec else ""
                    ),
                    "evalue": str(res.error_in_exec) if res.error_in_exec else "",
                    "traceback": tb,
                }
                self.send_response(self.iopub_socket, "error", err)
                return {"status": "error", "execution_count": self.execution_count}

            # send execute_result if there is a result
            if hasattr(res, "result") and res.result is not None:
                data = {
                    "execution_count": self.execution_count,
                    "data": {"text/plain": repr(res.result)},
                    "metadata": {},
                }
                self.send_response(self.iopub_socket, "execute_result", data)

            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }
        except Exception as e:
            tb = [str(e)]
            err = {"ename": type(e).__name__, "evalue": str(e), "traceback": tb}
            self.send_response(self.iopub_socket, "error", err)
            return {"status": "error", "execution_count": self.execution_count}

    def do_shutdown(self, restart):
        return {"status": "ok", "restart": restart}
