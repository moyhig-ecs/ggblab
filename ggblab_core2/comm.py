"""Communication primitives for GeoGebra frontend↔kernel messaging.

This module was moved from `ggblab.comm` and adapted to live inside the
`ggblab_core2` package so kernel-facing bridge logic is grouped together.
"""

import asyncio
import concurrent.futures
import functools
import json
import os
import queue
import tempfile
import threading
import time
import uuid

from IPython import get_ipython
from websockets.asyncio.server import serve, unix_serve

from ggblab.errors import GeoGebraAppletError

# Optional ipywidgets import for DOMWidget-based comm bridge
try:
    import ipywidgets as _ipywidgets

    _WIDGETS_AVAILABLE = True
except Exception:
    _ipywidgets = None
    _WIDGETS_AVAILABLE = False


class ggb_comm:
    """Dual-channel communication layer for kernel↔widget messaging.
    (content moved unchanged from original ggblab.comm with minimal import fixes)
    """

    recv_msgs = {}
    pending_futures = {}
    recv_events = queue.Queue()
    logs = []
    shared_objects = {}
    _shared_listeners = []
    thread = None
    thread_lock = threading.Lock()
    mid = None

    def __init__(self):
        self.target_comm = None
        self.target_name = "jupyter.ggblab"
        self.server_handle = None
        self.server_thread = None
        self.clients = set()
        self.socketPath = None
        self.wsPort = 0
        self._stop_event = threading.Event()
        self._client_connect_count = 0
        self._client_disconnect_count = 0
        self._last_client_log_time = 0.0
        self.pending_futures = {}
        self.widget_bridge = None
        self.use_ipython_comm = True
        self.enable_widget_bridge = False
        self.debug = False
        try:
            self.oob_timeout = float(os.environ.get("GGB_OOB_TIMEOUT", "30"))
        except Exception:
            self.oob_timeout = 30.0

    def start(self):
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = threading.Event()

        self.server_thread = threading.Thread(
            target=lambda: asyncio.run(self.server()), daemon=True
        )
        self.server_thread.start()

    def stop(self):
        try:
            self._stop_event.set()
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error signaling stop_event: {e}")

        try:
            if self.server_thread is not None:
                self.server_thread.join(timeout=1.0)
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error joining server_thread: {e}")

        try:
            if self.server_handle is not None:
                close = getattr(self.server_handle, "close", None)
                if callable(close):
                    close()
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"stop(): error closing server_handle: {e}")

    async def server(self):
        loop = asyncio.get_running_loop()
        if os.name in ["posix"]:
            _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(self.socketPath)
            async with unix_serve(
                self.client_handle, path=self.socketPath
            ) as self.server_handle:
                await loop.run_in_executor(None, self._stop_event.wait)
        else:
            async with serve(self.client_handle, "localhost", 0) as self.server_handle:
                with self.thread_lock:
                    self.wsPort = self.server_handle.sockets[0].getsockname()[1]
                    self.logs.append(
                        f"WebSocket server started at ws://localhost:{self.wsPort}"
                    )
                await loop.run_in_executor(None, self._stop_event.wait)

    async def client_handle(self, client_id):
        with self.thread_lock:
            self.clients.add(client_id)
            self._client_connect_count += 1
            now = time.time()
            if now - self._last_client_log_time > 5.0:
                self.logs.append(
                    f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                )
                self._client_connect_count = 0
                self._client_disconnect_count = 0
                self._last_client_log_time = now

        try:
            async for msg in client_id:
                _data = json.loads(msg)
                try:
                    t = _data.get("type") if isinstance(_data, dict) else None
                    with self.thread_lock:
                        self.logs.append(f"recv:type={t}")
                except Exception as _e:
                    with self.thread_lock:
                        self.logs.append(f"recv:type:logging_failed {_e}")

                async def _handle_object_update(payload):
                    try:
                        changes = {}
                        with self.thread_lock:
                            cls = self.__class__
                            if (
                                isinstance(payload, list)
                                and payload
                                and isinstance(payload[0], list)
                            ):
                                for pair in payload:
                                    if isinstance(pair, list) and len(pair) >= 2:
                                        name = pair[0]
                                        value = pair[1]
                                        cls.shared_objects[name] = value
                                        changes[name] = value
                            elif (
                                isinstance(payload, list)
                                and len(payload) >= 2
                                and not any(isinstance(i, list) for i in payload)
                            ):
                                name = payload[0]
                                value = payload[1]
                                cls.shared_objects[name] = value
                                changes[name] = value
                            elif isinstance(payload, dict):
                                if "name" in payload and "value" in payload:
                                    cls.shared_objects[payload["name"]] = payload[
                                        "value"
                                    ]
                                    changes[payload["name"]] = payload["value"]
                                else:
                                    for k, v in payload.items():
                                        cls.shared_objects[k] = v
                                        changes[k] = v

                        if changes:
                            try:
                                self.recv_events.put(
                                    {
                                        "type": "shared_objects_update",
                                        "payload": changes,
                                    }
                                )
                            except Exception:
                                with self.thread_lock:
                                    self.logs.append(
                                        "Failed to enqueue shared_objects_update event"
                                    )

                        if changes and getattr(cls, "_shared_listeners", None):
                            loop = asyncio.get_running_loop()
                            for cb in list(cls._shared_listeners):
                                try:
                                    import inspect

                                    if inspect.iscoroutinefunction(cb):
                                        try:
                                            await cb(changes)
                                        except Exception as e:
                                            with self.thread_lock:
                                                self.logs.append(
                                                    f"Error in async shared_objects listener: {e}"
                                                )
                                    else:
                                        try:
                                            await loop.run_in_executor(
                                                None, functools.partial(cb, changes)
                                            )
                                        except Exception as e:
                                            with self.thread_lock:
                                                self.logs.append(
                                                    f"Error in sync shared_objects listener: {e}"
                                                )
                                except Exception:
                                    with self.thread_lock:
                                        self.logs.append(
                                            "Error invoking shared_objects listener"
                                        )
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(
                                f"Failed to process object_update payload: {e}"
                            )

                if isinstance(_data, dict) and _data.get("type") == "bulk_actions":
                    payload = _data.get("payload")
                    try:
                        if isinstance(payload, list):
                            try:
                                with self.thread_lock:
                                    self.logs.append(
                                        f"bulk_actions: packaged_count={len(payload)}"
                                    )
                            except Exception:
                                pass
                            for entry in payload:
                                try:
                                    if not isinstance(entry, dict):
                                        continue
                                    etype = entry.get("type")
                                    epayload = entry.get("payload")
                                    if etype == "object_update":
                                        try:
                                            await _handle_object_update(epayload)
                                        except Exception:
                                            with self.thread_lock:
                                                self.logs.append(
                                                    "Error handling object_update entry in bulk_actions"
                                                )
                                    else:
                                        try:
                                            self.recv_events.put(entry)
                                        except Exception:
                                            with self.thread_lock:
                                                self.logs.append(
                                                    "Failed to enqueue bulk action entry"
                                                )
                                except Exception:
                                    with self.thread_lock:
                                        self.logs.append(
                                            "Error processing entry in bulk_actions"
                                        )
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(
                                f"Failed to process bulk_actions payload: {e}"
                            )
                    continue

                if isinstance(_data, dict) and _data.get("type") == "object_update":
                    payload = _data.get("payload")
                    try:
                        await _handle_object_update(payload)
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(
                                f"Failed to process object_update payload: {e}"
                            )
                    continue

            _id = _data.get("id") if isinstance(_data, dict) else None

            if _id:
                with self.thread_lock:
                    fut = self.pending_futures.pop(_id, None)
                if fut:
                    try:
                        import asyncio as _asyncio

                        is_asyncio = (
                            isinstance(fut, _asyncio.Future)
                            if hasattr(_asyncio, "Future")
                            else False
                        )
                        if is_asyncio:
                            loop = None
                            try:
                                get_loop = getattr(fut, "get_loop", None)
                                if callable(get_loop):
                                    loop = get_loop()
                            except Exception:
                                loop = getattr(fut, "_loop", None)

                            if (
                                loop is not None
                                and getattr(loop, "is_running", lambda: False)()
                            ):
                                loop.call_soon_threadsafe(
                                    fut.set_result, _data.get("payload")
                                )
                            else:
                                fut.set_result(_data.get("payload"))
                        else:
                            fut.set_result(_data.get("payload"))
                    except Exception as e:
                        if getattr(self, "debug", False):
                            with self.thread_lock:
                                self.logs.append(
                                    f"Error setting result for id {_id}: {e}"
                                )
                else:
                    if getattr(self, "debug", False):
                        with self.thread_lock:
                            self.logs.append(f"Unexpected response for id {_id}")
            else:
                self.recv_events.put(_data)

            await asyncio.sleep(0)
        except Exception as e:
            with self.thread_lock:
                now = time.time()
                if now - self._last_client_log_time > 5.0:
                    self.logs.append(f"Connection error: {e}")
                    self._last_client_log_time = now
        finally:
            with self.thread_lock:
                if client_id in self.clients:
                    try:
                        self.clients.remove(client_id)
                    except Exception as e:
                        self.logs.append(f"Error removing client: {e}")
                self._client_disconnect_count += 1
                now = time.time()
                if now - self._last_client_log_time > 5.0:
                    self.logs.append(
                        f"Clients connected: {len(self.clients)} (connects+={self._client_connect_count}, disconnects+={self._client_disconnect_count})"
                    )
                    self._client_connect_count = 0
                    self._client_disconnect_count = 0
                    self._last_client_log_time = now

    def register_target(self):
        if not getattr(self, "use_ipython_comm", False):
            if not getattr(self, "enable_widget_bridge", False):
                if getattr(self, "debug", False):
                    with self.thread_lock:
                        self.logs.append(
                            "IPython Comm registration skipped (use_ipython_comm=False)"
                        )
                return

            if not _WIDGETS_AVAILABLE:
                if getattr(self, "debug", False):
                    with self.thread_lock:
                        self.logs.append(
                            "ipywidgets not available; IPython Comm registration skipped"
                        )
                return

            try:
                if self.widget_bridge is None:
                    wb = _ipywidgets.Widget()
                    self.widget_bridge = wb

                    def _on_msg(widget, content, buffers):
                        try:
                            msg = {"content": {"data": content}}
                            self.handle_recv(msg)
                        except Exception:
                            with self.thread_lock:
                                self.logs.append("Error handling widget bridge message")

                    self.widget_bridge.on_msg(_on_msg)

                if getattr(self, "debug", False):
                    with self.thread_lock:
                        self.logs.append("Using ipywidgets bridge for comms")
            except Exception:
                if getattr(self, "debug", False):
                    with self.thread_lock:
                        self.logs.append("Failed to create ipywidgets bridge")
            return

        try:
            get_ipython().kernel.comm_manager.register_target(
                self.target_name, self.register_target_cb
            )
        except Exception:
            with self.thread_lock:
                self.logs.append("Failed to register IPython Comm target")
        self.register_post_execute()

    @classmethod
    def add_shared_listener(cls, fn):
        try:
            if not callable(fn):
                return False
            with cls.thread_lock:
                if fn not in cls._shared_listeners:
                    cls._shared_listeners.append(fn)
            return True
        except Exception:
            return False

    @classmethod
    def remove_shared_listener(cls, fn):
        try:
            with cls.thread_lock:
                if fn in cls._shared_listeners:
                    cls._shared_listeners.remove(fn)
            return True
        except Exception:
            return False

    @classmethod
    def clear_shared_listeners(cls):
        try:
            with cls.thread_lock:
                n = len(cls._shared_listeners)
                cls._shared_listeners.clear()
            return n
        except Exception:
            return 0

    @classmethod
    def clear_shared_listner(cls):
        return cls.clear_shared_listeners()

    def register_target_cb(self, comm, msg):
        with self.thread_lock:
            self.target_comm = comm
            if getattr(self, "debug", False):
                self.logs.append(f"register_target_cb: {self.target_comm}")

        @comm.on_msg
        def _recv(msg):
            self.handle_recv(msg)

        @comm.on_close
        def _close():
            self.target_comm = None

    def unregister_target_cb(self):
        with self.thread_lock:
            if self.target_comm:
                self.target_comm.close()
            self.target_comm = None

    def _post_execute_handler(self, *args, **kwargs):
        try:
            drained = 0
            while True:
                try:
                    ev = self.recv_events.get_nowait()
                except queue.Empty:
                    break
                drained += 1
                with self.thread_lock:
                    self.logs.append(f"post_execute: event {ev.get('type', 'unknown')}")
            if drained:
                with self.thread_lock:
                    self.logs.append(f"post_execute: flushed {drained} recv_events")
        except Exception as e:
            with self.thread_lock:
                self.logs.append(f"post_execute handler error: {e}")

    def register_post_execute(self):
        try:
            ip = get_ipython()
            if ip is None:
                return False
            try:
                ip.events.register("post_execute", self._post_execute_handler)
                try:
                    if getattr(self, "debug", False):
                        with self.thread_lock:
                            self.logs.append(
                                "Registered post_execute handler for recv_events"
                            )
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(
                            f"register_post_execute: logging registration message failed: {e}"
                        )
                return True
            except Exception:
                try:
                    with self.thread_lock:
                        self.logs.append("Failed to register post_execute handler")
                except Exception as e:
                    with self.thread_lock:
                        self.logs.append(
                            f"register_post_execute: failed logging error: {e}"
                        )
                return False
        except Exception:
            return False

    def handle_recv(self, msg):
        try:
            if isinstance(msg["content"]["data"], str):
                _data = json.loads(msg["content"]["data"])
            else:
                _data = msg["content"]["data"]
        except Exception:
            with self.thread_lock:
                self.logs.append("Malformed comm message received")
            return

        _id = _data.get("id") if isinstance(_data, dict) else None
        if _id:
            with self.thread_lock:
                fut = self.pending_futures.pop(_id, None)
            if fut:
                try:
                    import asyncio as _asyncio

                    try:
                        is_asyncio = isinstance(fut, _asyncio.Future)
                    except Exception:
                        is_asyncio = False

                    if is_asyncio:
                        loop = None
                        try:
                            get_loop = getattr(fut, "get_loop", None)
                            if callable(get_loop):
                                loop = get_loop()
                        except Exception:
                            loop = getattr(fut, "_loop", None)

                        if (
                            loop is not None
                            and getattr(loop, "is_running", lambda: False)()
                        ):
                            loop.call_soon_threadsafe(
                                fut.set_result, _data.get("payload")
                            )
                        else:
                            fut.set_result(_data.get("payload"))
                    else:
                        fut.set_result(_data.get("payload"))
                except Exception:
                    with self.thread_lock:
                        self.logs.append(f"Error setting result for id {_id}")
                else:
                    with self.thread_lock:
                        self.logs.append(f"Unexpected response for id {_id}")
            return

        try:
            self.recv_events.put(_data)
        except Exception:
            with self.thread_lock:
                self.logs.append("Failed to enqueue recv event")
        return

    def send(self, msg):
        with self.thread_lock:
            tc = self.target_comm
        if tc:
            try:
                kernel = get_ipython().kernel
                io_loop = getattr(kernel, "io_loop", None)
                if io_loop is not None and hasattr(io_loop, "add_callback"):
                    try:
                        io_loop.add_callback(lambda: tc.send(msg))
                        return
                    except Exception:
                        with self.thread_lock:
                            self.logs.append(
                                "send(): io_loop.add_callback failed; falling back to direct send"
                            )
            except Exception:
                with self.thread_lock:
                    self.logs.append("send(): error obtaining kernel io_loop")
            return tc.send(msg)

        raise RuntimeError(
            "No active Comm: GeoGebra().init() must be called in a notebook cell before sending commands."
        )

    async def send_recv(self, msg):
        try:
            if isinstance(msg, str):
                _data = json.loads(msg)
            else:
                _data = msg

            _id = str(uuid.uuid4())
            self.mid = _id
            msg["id"] = _id

            fut = concurrent.futures.Future()
            with self.thread_lock:
                self.pending_futures[_id] = fut

            with self.thread_lock:
                has_clients = bool(self.clients)
                has_target = self.target_comm is not None
            if not has_clients and not has_target:
                with self.thread_lock:
                    self.logs.append(
                        f"No clients; waiting for client before sending {_id}"
                    )
                waited = 0.0
                while waited < 2.0:
                    with self.thread_lock:
                        if self.clients or self.target_comm:
                            break
                    await asyncio.sleep(0.05)
                    waited += 0.05

            self.send(json.dumps(_data))
            await asyncio.sleep(0)

            loop = asyncio.get_running_loop()

            def _watchdog():
                if not fut.done():
                    try:
                        fut.set_exception(asyncio.TimeoutError("oob future timed out"))
                    except Exception as e:
                        with self.thread_lock:
                            self.logs.append(
                                f"_watchdog: failed to set exception on future: {e}"
                            )

            handle = loop.call_later(getattr(self, "oob_timeout", 30.0), _watchdog)

            try:
                value = await asyncio.wrap_future(fut)
            finally:
                handle.cancel()
                with self.thread_lock:
                    self.pending_futures.pop(_id, None)

            if value is None:
                await asyncio.sleep(0.5)
                error_messages = []
                while True:
                    try:
                        event = self.recv_events.get_nowait()
                        if event.get("type") == "Error":
                            error_messages.append(event.get("payload", "Unknown error"))
                    except queue.Empty:
                        break

                if error_messages:
                    combined_message = "\n".join(error_messages)
                    raise GeoGebraAppletError(
                        error_message=combined_message, error_type="AppletError"
                    )

            return value
        except (asyncio.TimeoutError, TimeoutError):
            print(f"TimeoutError in send_recv {msg}")
            raise

    @classmethod
    def kernel_comm_summary(cls):
        ip = get_ipython()
        kernel = getattr(ip, "kernel", None)
        cm = getattr(kernel, "comm_manager", None)
        result = {"targets": {}, "comms": {}}
        if cm is None:
            return result

        try:
            targets = getattr(cm, "targets", {}) or {}
            for tname, cb in targets.items():
                try:
                    result["targets"][tname] = getattr(
                        cb, "__name__", type(cb).__name__
                    )
                except Exception:
                    result["targets"][tname] = str(cb)
        except Exception as e:
            result["targets_error"] = str(e)

        try:
            comms = getattr(cm, "comms", {}) or {}
            for cid, comm in comms.items():
                try:
                    result["comms"][cid] = {
                        "target_name": getattr(comm, "target_name", None),
                        "target_module": getattr(comm, "target_module", None),
                        "metadata": getattr(comm, "metadata", None),
                    }
                except Exception:
                    result["comms"][cid] = str(comm)
        except Exception as e:
            result["comms_error"] = str(e)

        return result


try:
    ggb_comm_instance
except NameError:
    ggb_comm_instance = ggb_comm()


def kernel_comm_summary():
    try:
        return ggb_comm.kernel_comm_summary()
    except Exception:
        return {"targets": {}, "comms": {}}
