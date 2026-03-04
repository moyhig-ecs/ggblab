import os
import sys
import logging
from ipykernel.kernelbase import Kernel
from jupyter_client import KernelManager
import io
import contextlib
from IPython.core.interactiveshell import InteractiveShell
try:
    from ipykernel.comm import CommManager
except Exception:
    CommManager = None
import threading
import time
import json

LOG = logging.getLogger(__name__)


class ProxyKernel(Kernel):
    implementation = "ggblab-proxy"
    implementation_version = "0.1"
    language = "python"
    language_version = sys.version.split()[0]
    language_info = {"name": "python", "mimetype": "text/x-python", "file_extension": ".py"}
    protocol_version = "5.3"
    banner = "ggblab proxy kernel (forwards to real child kernel)"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Child kernel name can be set with env var GGBLAB_PROXY_CHILD_KERNEL
        child_kernel = os.environ.get("GGBLAB_PROXY_CHILD_KERNEL", "python3")
        LOG.info("Starting child kernel: %s", child_kernel)

        # Mode: 'proxy' (forward to external kernel) or 'direct' (run locally using InteractiveShell)
        self.mode = os.environ.get("GGBLAB_PROXY_MODE", "proxy")
        LOG.info("ggblab proxy mode: %s", self.mode)

        # If direct mode, prepare a local InteractiveShell instance
        if self.mode == "direct":
            try:
                self._local_shell = InteractiveShell.instance()
            except Exception:
                self._local_shell = InteractiveShell()
            # do not start a child kernel in direct mode
            self.km = None
            self.kc = None
            self._child_session = None
            # ensure we have a comm manager for direct mode
            if CommManager is not None:
                try:
                    # CommManager may accept different keyword names depending on ipykernel version
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
            # make the InteractiveShell aware of this kernel instance so
            # code that does `ip = get_ipython(); ip.kernel` finds us
            try:
                self._local_shell.kernel = self
            except Exception:
                LOG.exception("Failed to set InteractiveShell.kernel")
            # provide display publisher if available
            try:
                # Ensure a minimal display_pub exists so InteractiveShell
                # can call display_pub.is_publishing and publish display data.
                class _DirectDisplayPub:
                    def __init__(self, kernel):
                        self.kernel = kernel
                        self.is_publishing = False

                    def publish(self, data, metadata=None, source=None):
                        try:
                            content = {"data": data, "metadata": metadata or {}}
                            # Use kernel iopub to send display_data
                            self.kernel.send_response(self.kernel.iopub_socket, "display_data", content)
                        except Exception:
                            LOG.exception("Failed to publish display data")

                # attach to kernel and InteractiveShell
                if getattr(self, "display_pub", None) is None:
                    self.display_pub = _DirectDisplayPub(self)
                self._local_shell.display_pub = self.display_pub
            except Exception:
                LOG.exception("Failed to attach display_pub to InteractiveShell")
            # start a watcher thread that publishes new comms to iopub
            try:
                self._comm_watcher_stop = threading.Event()
                self._comm_watcher_seen = set()

                def _comm_watcher():
                    cm = getattr(self, "comm_manager", None)
                    while not self._comm_watcher_stop.is_set():
                        try:
                            if cm is None:
                                time.sleep(0.5)
                                continue
                            comms = {}
                            for name in ("comms", "_comms", "_comms_by_msgid"):
                                try:
                                    val = getattr(cm, name, None)
                                    if isinstance(val, dict):
                                        for k, v in val.items():
                                            comms.setdefault(k, []).append((name, v))
                                except Exception:
                                    continue

                            for cid, entries in comms.items():
                                if cid in self._comm_watcher_seen:
                                    continue
                                self._comm_watcher_seen.add(cid)
                                try:
                                    info = {"comm_id": cid, "entries": [n for n, _ in entries]}
                                    text = json.dumps(info)
                                    self.send_response(self.iopub_socket, "stream", {"name": "stdout", "text": f"[ggblab-proxy] NEW_COMM: {text}\n"})
                                except Exception:
                                    LOG.exception("Failed to publish new comm info for %s", cid)
                            time.sleep(0.5)
                        except Exception:
                            LOG.exception("comm_watcher loop error")
                            time.sleep(1.0)

                t = threading.Thread(target=_comm_watcher, daemon=True)
                t.start()
            except Exception:
                LOG.exception("Failed to start comm watcher thread")
            return

        self.km = KernelManager(kernel_name=child_kernel)
        # start the child kernel process
        self.km.start_kernel()

        # create a blocking client to communicate with child kernel
        self.kc = self.km.blocking_client()
        self.kc.start_channels()
        try:
            self.kc.wait_for_ready(timeout=60)
        except Exception as e:
            LOG.exception("Child kernel did not become ready: %s", e)

        # expose a small helper to send shell messages directly to child kernel
        # (BlockingKernelClient exposes `session` and channel sockets)
        self._child_session = getattr(self.kc, "session", None)

    # --------------------
    # Forward comm messages coming from frontend to child kernel
    # --------------------
    def comm_open(self, msg):
        """Forward comm_open from frontend to child kernel."""
        try:
            LOG.info("comm_open received: header=%s", msg.get("header", {}))
        except Exception:
            pass
        try:
            # also write to stderr so the server log definitely shows it
            import sys as _sys
            _sys.stderr.write(f"[ggblab-proxy] comm_open header={msg.get('header', {})}\n")
            _sys.stderr.flush()
        except Exception:
            pass
        # direct mode: hand off to local CommManager
        if getattr(self, "mode", "proxy") == "direct":
            try:
                if getattr(self, "comm_manager", None) is not None:
                    # CommManager expects the full message dict
                    self.comm_manager.comm_open(msg)
                    return
            except Exception:
                LOG.exception("Local comm_manager failed to handle comm_open")

        # proxy mode: forward to child kernel
        try:
            content = msg.get("content", {})
            if self._child_session is not None:
                # send raw comm_open on child's shell channel
                self._child_session.send(self.kc.shell_channel, "comm_open", content, parent=msg.get("header", {}))
        except Exception:
            LOG.exception("Failed to forward comm_open to child")

    def comm_msg(self, msg):
        """Forward comm_msg from frontend to child kernel."""
        try:
            LOG.info("comm_msg received: header=%s", msg.get("header", {}))
        except Exception:
            pass
        try:
            import sys as _sys
            _sys.stderr.write(f"[ggblab-proxy] comm_msg header={msg.get('header', {})}\n")
            _sys.stderr.flush()
        except Exception:
            pass
        # direct mode: hand off to local CommManager
        if getattr(self, "mode", "proxy") == "direct":
            try:
                if getattr(self, "comm_manager", None) is not None:
                    self.comm_manager.comm_msg(msg)
                    return
            except Exception:
                LOG.exception("Local comm_manager failed to handle comm_msg")

        try:
            content = msg.get("content", {})
            if self._child_session is not None:
                self._child_session.send(self.kc.shell_channel, "comm_msg", content, parent=msg.get("header", {}))
        except Exception:
            LOG.exception("Failed to forward comm_msg to child")

    def comm_close(self, msg):
        """Forward comm_close from frontend to child kernel."""
        try:
            LOG.info("comm_close received: header=%s", msg.get("header", {}))
        except Exception:
            pass
        try:
            import sys as _sys
            _sys.stderr.write(f"[ggblab-proxy] comm_close header={msg.get('header', {})}\n")
            _sys.stderr.flush()
        except Exception:
            pass
        # direct mode: hand off to local CommManager
        if getattr(self, "mode", "proxy") == "direct":
            try:
                if getattr(self, "comm_manager", None) is not None:
                    self.comm_manager.comm_close(msg)
                    return
            except Exception:
                LOG.exception("Local comm_manager failed to handle comm_close")

        try:
            content = msg.get("content", {})
            if self._child_session is not None:
                self._child_session.send(self.kc.shell_channel, "comm_close", content, parent=msg.get("header", {}))
        except Exception:
            LOG.exception("Failed to forward comm_close to child")

    async def dispatch_shell(self, msg, *args, **kwargs):
        """Intercept comm_* shell messages and forward to our handlers.

        Fall back to the base implementation for other message types.
        """
        try:
            # msg may sometimes be a list of raw frames; only handle prefilter when it's a dict
            if not isinstance(msg, dict):
                LOG.debug("dispatch_shell received non-dict message, skipping prefilter: %s", type(msg))
            else:
                mtype = msg.get("header", {}).get("msg_type")
                LOG.debug("dispatch_shell received msg_type=%s", mtype)
                try:
                    import sys as _sys
                    _sys.stderr.write(f"[ggblab-proxy] dispatch_shell msg_type={mtype}\n")
                    _sys.stderr.flush()
                except Exception:
                    pass
                if mtype in ("comm_open", "comm_msg", "comm_close"):
                    LOG.info("dispatch_shell intercepting %s", mtype)
                    try:
                        if mtype == "comm_open":
                            self.comm_open(msg)
                        elif mtype == "comm_msg":
                            self.comm_msg(msg)
                        elif mtype == "comm_close":
                            self.comm_close(msg)
                        return
                    except Exception:
                        LOG.exception("Error handling %s", mtype)
        except Exception:
            LOG.exception("Error in dispatch_shell prefilter")

        # delegate to base class for other messages
        try:
            return await super().dispatch_shell(msg, *args, **kwargs)
        except AttributeError:
            # Some Kernel base classes may not expose an awaitable dispatch_shell
            try:
                return super().dispatch_shell(msg, *args, **kwargs)
            except Exception:
                return None


    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        if not code.strip():
            return {"status": "ok", "execution_count": self.execution_count}

        if self.mode == "direct":
            # Execute locally using InteractiveShell and forward outputs
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    res = self._local_shell.run_cell(code)

                out_text = stdout_buf.getvalue()
                err_text = stderr_buf.getvalue()

                if out_text:
                    self.send_response(self.iopub_socket, "stream", {"name": "stdout", "text": out_text})
                if err_text:
                    self.send_response(self.iopub_socket, "stream", {"name": "stderr", "text": err_text})

                if res.error_in_exec:
                    # send error
                    tb = []
                    if res.error_before_exec:
                        tb = [str(res.error_before_exec)]
                    elif res.error_in_exec:
                        tb = [str(res.error_in_exec)]
                    err = {"ename": type(res.error_in_exec).__name__ if res.error_in_exec else "", "evalue": str(res.error_in_exec) if res.error_in_exec else "", "traceback": tb}
                    self.send_response(self.iopub_socket, "error", err)
                    return {"status": "error", "execution_count": self.execution_count}

                # send execute_result if there is a result
                if hasattr(res, "result") and res.result is not None:
                    text = repr(res.result)
                    data = {"execution_count": self.execution_count, "data": {"text/plain": text}, "metadata": {}}
                    self.send_response(self.iopub_socket, "execute_result", data)

                return {"status": "ok", "execution_count": self.execution_count, "payload": [], "user_expressions": {}}
            except Exception as e:
                tb = [str(e)]
                err = {"ename": type(e).__name__, "evalue": str(e), "traceback": tb}
                self.send_response(self.iopub_socket, "error", err)
                return {"status": "error", "execution_count": self.execution_count}

        # send code to child kernel
        msg_id = self.kc.execute(code, store_history=store_history)

        # collect iopub messages from child and forward them
        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=5)
            except Exception:
                break

            parent = msg.get("parent_header") or {}
            if parent.get("msg_id") != msg_id:
                # not related to our execution
                continue

            mtype = msg["header"]["msg_type"]
            content = msg.get("content", {})

            if mtype == "status":
                if content.get("execution_state") == "idle":
                    break
                continue

            if mtype == "stream":
                stream_content = {"name": content.get("name"), "text": content.get("text")}
                # Forward stream to frontend
                self.send_response(self.iopub_socket, "stream", stream_content)

                # Detect special proxy requests emitted by child kernels.
                # Child kernels can emit a stream line starting with the
                # prefix 'GGB_REQ:' followed by a JSON object:
                #   {"id": "<reqid>", "type": "function_sync"|"command_sync", "name": "...", "args": [...]}.
                # When seen, call the corresponding local function and send
                # a reply back to the child kernel by executing a small
                # print statement that emits a 'GGB_REPLY:' JSON payload on
                # the child's stdout. This allows language kernels (Julia,
                # Python) to request synchronous applet operations via the
                # proxy.
                try:
                    text = content.get("text", "") or ""
                    if isinstance(text, str) and text.startswith("GGB_REQ:"):
                        payload_json = text.split("GGB_REQ:", 1)[1].strip()
                        try:
                            req = json.loads(payload_json)
                        except Exception:
                            req = None
                        if req and isinstance(req, dict):
                            # handle request asynchronously but within this loop
                            try:
                                # Lazy import to avoid cycles
                                from ggblab_core.applet import function_sync, command_sync

                                r = None
                                if req.get("type") == "function_sync":
                                    try:
                                        r = function_sync(req.get("name"), args=req.get("args", None), timeout=req.get("timeout", None))
                                    except Exception as e:
                                        r = {"error": str(e)}
                                elif req.get("type") == "command_sync":
                                    try:
                                        r = command_sync(req.get("command", ""), timeout=req.get("timeout", None))
                                    except Exception as e:
                                        r = {"error": str(e)}
                                else:
                                    r = {"error": "unknown request type"}

                                # Prepare a JSON-safe reply
                                try:
                                    reply = json.dumps({"id": req.get("id"), "result": r})
                                except Exception:
                                    # Fallback to stringification
                                    reply = json.dumps({"id": req.get("id"), "result": str(r)})

                                # Send reply to child kernel by executing a print
                                # in the child kernel so it appears on its iopub.
                                try:
                                    code = f"print('GGB_REPLY:' + {json.dumps(reply)})"
                                    # Use non-blocking execute to avoid deadlocks.
                                    try:
                                        self.kc.execute(code, store_history=False)
                                    except Exception:
                                        # best-effort: ignore failures to send reply
                                        LOG.exception("Failed to send reply execute to child kernel")
                                except Exception:
                                    LOG.exception("Failed to schedule reply to child kernel")
                            except Exception:
                                LOG.exception("Error handling GGB_REQ payload")
                except Exception:
                    LOG.exception("Error while inspecting stream content for proxy requests")

            elif mtype == "execute_result":
                data = {"execution_count": content.get("execution_count"), "data": content.get("data", {}), "metadata": content.get("metadata", {})}
                self.send_response(self.iopub_socket, "execute_result", data)

            elif mtype == "display_data":
                data = {"data": content.get("data", {}), "metadata": content.get("metadata", {})}
                self.send_response(self.iopub_socket, "display_data", data)

            elif mtype == "error":
                err = {"ename": content.get("ename"), "evalue": content.get("evalue"), "traceback": content.get("traceback", [])}
                self.send_response(self.iopub_socket, "error", err)
            elif mtype in ("comm_open", "comm_msg", "comm_close"):
                # forward comm events from child kernel to frontend
                try:
                    self.send_response(self.iopub_socket, mtype, content)
                except Exception:
                    LOG.exception("Failed to forward child comm message: %s", mtype)

        return {"status": "ok", "execution_count": self.execution_count, "payload": [], "user_expressions": {}}

    def do_shutdown(self, restart):
        try:
            if getattr(self, 'kc', None) is not None:
                self.kc.stop_channels()
        except Exception:
            pass
        try:
            if getattr(self, 'km', None) is not None:
                self.km.shutdown_kernel(restart=restart)
        except Exception:
            pass
        return {"status": "ok", "restart": restart}
