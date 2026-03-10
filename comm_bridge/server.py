"""TCP -> frontend Comm bridge (server)

This module is a direct relocation of the previous `ggblab_core.py_comm_bridge`.
It provides the same API: `start_server`, `stop_server`, `get_state`,
`dump_bridge_state`, and `local_send` for same-process optimization.
"""

import asyncio
import json
import threading
import time
import traceback
import uuid
from typing import Optional

try:
    from ipykernel.comm import Comm
except Exception:
    Comm = None

try:
    from IPython import get_ipython
except Exception:
    get_ipython = None

_bridge_state = {}
_bridge_state_lock = threading.Lock()

# stored_replies: map of message id -> reply payload for replies that arrived
# after the original pending future timed out. This allows clients to poll
# for late replies via an explicit get_reply op.
_bridge_state.setdefault("stored_replies", {})


def _log_diag(msg: str) -> None:
    try:
        ts = time.time()
        entry = (ts, str(msg))
        with _bridge_state_lock:
            lst = _bridge_state.setdefault("diag", [])
            lst.append(entry)
            if len(lst) > 200:
                del lst[:-200]
    except Exception:
        try:
            import sys

            sys.stderr.write(f"comm_bridge(diag): {msg}\n")
            sys.stderr.flush()
        except Exception:
            pass


def register_comm_target(target_name: str = "jupyter.ggblab"):
    if get_ipython is None:
        return False
    try:
        ip = get_ipython()
        if ip is None:
            return False
        km = getattr(ip, "kernel", None)
        if km is None:
            return False
        cm = getattr(km, "comm_manager", None)
        if cm is None:
            return False

        def _target_cb(comm, open_msg):
            try:
                with _bridge_state_lock:
                    _bridge_state["target_comm"] = comm
                    _bridge_state.setdefault("incoming_msgs", [])

                def _on_msg(msg):
                    try:
                        data = msg.get("content", {}).get("data", msg)
                    except Exception:
                        data = msg

                    try:
                        if isinstance(data, (bytes, bytearray)):
                            try:
                                s = data.decode("utf-8")
                                data = json.loads(s)
                            except Exception:
                                try:
                                    data = s
                                except Exception:
                                    pass
                        elif isinstance(data, str):
                            try:
                                parsed = json.loads(data)
                                data = parsed
                            except Exception:
                                pass
                    except Exception:
                        pass

                    msg_id = None
                    try:
                        if isinstance(data, dict):
                            msg_id = (
                                data.get("id")
                                or (
                                    data.get("payload")
                                    and isinstance(data.get("payload"), dict)
                                    and data["payload"].get("id")
                                )
                                or (
                                    data.get("reply")
                                    and isinstance(data.get("reply"), dict)
                                    and data["reply"].get("id")
                                )
                                or data.get("requestId")
                                or data.get("request_id")
                                or data.get("correlation_id")
                            )
                            if (
                                not msg_id
                                and "data" in data
                                and isinstance(data["data"], dict)
                            ):
                                msg_id = data["data"].get("id")
                    except Exception:
                        msg_id = None

                    try:
                        with _bridge_state_lock:
                            pending_keys = list(
                                _bridge_state.get("pending_replies", {}).keys()
                            )
                        _log_diag(
                            f"received comm msg, id={msg_id}, pending={pending_keys}, data={data}"
                        )
                    except Exception:
                        pass

                    if msg_id:
                        result_payload = None
                        if isinstance(data, dict):
                            result_payload = data.get(
                                "payload", data.get("reply", data)
                            )

                        try:
                            with _bridge_state_lock:
                                stored = _bridge_state.setdefault("stored_replies", {})
                                if len(stored) > 1000:
                                    try:
                                        oldest = next(iter(stored))
                                        stored.pop(oldest, None)
                                    except Exception:
                                        pass
                                stored[msg_id] = (
                                    result_payload
                                    if result_payload is not None
                                    else data
                                )
                        except Exception:
                            pass

                        with _bridge_state_lock:
                            pending = _bridge_state.get("pending_replies", {})
                            entry = pending.pop(msg_id, None) if pending else None
                        if entry:
                            fut, fut_loop = entry
                            try:
                                if (
                                    fut_loop is not None
                                    and getattr(fut_loop, "is_running", lambda: False)()
                                ):
                                    fut_loop.call_soon_threadsafe(
                                        fut.set_result, result_payload
                                    )
                                else:
                                    fut.set_result(result_payload)
                            except Exception:
                                try:
                                    fut.set_result(data)
                                except Exception:
                                    pass
                            return

                    try:
                        with _bridge_state_lock:
                            if msg_id:
                                stored = _bridge_state.setdefault("stored_replies", {})
                                try:
                                    stored[msg_id] = (
                                        data.get("payload", data)
                                        if isinstance(data, dict)
                                        else data
                                    )
                                except Exception:
                                    stored[msg_id] = data
                            else:
                                _bridge_state.setdefault("incoming_msgs", []).append(
                                    data
                                )
                    except Exception:
                        try:
                            _bridge_state.setdefault("incoming_msgs", []).append(data)
                        except Exception:
                            pass

                try:
                    comm.on_msg(_on_msg)
                except Exception:
                    pass

                def _on_close():
                    try:
                        with _bridge_state_lock:
                            _bridge_state.pop("target_comm", None)
                    except Exception:
                        pass

                try:
                    comm.on_close(_on_close)
                except Exception:
                    pass
            except Exception:
                return

        try:
            cm.register_target(target_name, _target_cb)
            _bridge_state["target_name"] = target_name
            return True
        except Exception:
            return False
    except Exception:
        return False


def unregister_comm_target():
    try:
        ip = get_ipython()
        if ip is None:
            return False
        km = getattr(ip, "kernel", None)
        if km is None:
            return False
        cm = getattr(km, "comm_manager", None)
        if cm is None:
            return False
        tname = _bridge_state.get("target_name")
        if not tname:
            return False
        unregister = getattr(cm, "unregister_target", None)
        if callable(unregister):
            try:
                unregister(tname)
            except Exception:
                pass
        _bridge_state.pop("target_name", None)
        _bridge_state.pop("target_comm", None)
        _bridge_state.pop("incoming_msgs", None)
        return True
    except Exception:
        return False


async def _handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float
):
    writer.get_extra_info("peername")
    try:
        data = await reader.readline()
        if not data:
            writer.close()
            await writer.wait_closed()
            return
        text = data.decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(text)
        except Exception:
            payload = text

        try:
            if isinstance(payload, dict) and payload.get("op") == "get_reply":
                req_id = payload.get("id")
                if not req_id:
                    out = {"error": "missing id in get_reply request"}
                else:
                    with _bridge_state_lock:
                        stored = _bridge_state.setdefault("stored_replies", {})
                        val = stored.pop(req_id, None)
                    if val is None:
                        out = {"error": "no reply available"}
                    else:
                        out = {"reply": val}
                writer.write((json.dumps(out, default=str) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
        except Exception:
            pass

        try:
            if isinstance(payload, dict) and payload.get("op") == "ping":
                try:
                    _log_diag("received local ping; replying pong")
                except Exception:
                    pass
                writer.write(
                    (json.dumps({"op": "pong", "echo": payload}) + "\n").encode()
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
        except Exception:
            pass

        if Comm is None:
            resp = {"error": "ipykernel.comm.Comm not available in this kernel"}
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        loop = asyncio.get_event_loop()

        waited = 0.0
        tc = None
        while waited < 2.0:
            with _bridge_state_lock:
                tc = _bridge_state.get("target_comm")
            if tc:
                break
            await asyncio.sleep(0.05)
            waited += 0.05

        if tc is None:
            out = {"error": "no frontend comm client connected"}
            writer.write((json.dumps(out) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        try:
            if isinstance(payload, dict) and "id" in payload:
                msg_id = payload["id"]
            else:
                msg_id = str(uuid.uuid4())
                if isinstance(payload, dict):
                    payload["id"] = msg_id
        except Exception:
            msg_id = str(uuid.uuid4())

        fut = loop.create_future()

        with _bridge_state_lock:
            _bridge_state.setdefault("pending_replies", {})[msg_id] = (fut, loop)
        try:
            with _bridge_state_lock:
                pending_keys = list(_bridge_state.get("pending_replies", {}).keys())
            _log_diag(f"stored pending reply id={msg_id}, pending={pending_keys}")
        except Exception:
            pass

        try:
            try:
                ip = get_ipython()
                kernel = getattr(ip, "kernel", None)
                io_loop = getattr(kernel, "io_loop", None)
                send_payload = payload
                try:
                    if not isinstance(payload, (str, bytes)):
                        send_payload = json.dumps(payload)
                except Exception:
                    try:
                        send_payload = str(payload)
                    except Exception:
                        send_payload = payload

                if io_loop is not None and hasattr(io_loop, "add_callback"):
                    try:
                        io_loop.add_callback(lambda: tc.send(send_payload))
                    except Exception:
                        pass
                else:
                    tc.send(send_payload)
            except Exception:
                try:
                    send_payload = payload
                    try:
                        if not isinstance(payload, (str, bytes)):
                            send_payload = json.dumps(payload)
                    except Exception:
                        try:
                            send_payload = str(payload)
                        except Exception:
                            send_payload = payload

                    tc.send(send_payload)
                except Exception as e:
                    with _bridge_state_lock:
                        _bridge_state.get("pending_replies", {}).pop(msg_id, None)
                    out = {"error": f"Failed to send on registered Comm: {e}"}
                    writer.write((json.dumps(out) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
        except Exception as e:
            with _bridge_state_lock:
                _bridge_state.get("pending_replies", {}).pop(msg_id, None)
            out = {
                "error": f"Failed to send message: {e}",
                "trace": traceback.format_exc(),
            }
            writer.write((json.dumps(out, default=str) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        try:
            reply_payload = await asyncio.wait_for(fut, timeout=timeout)
            out = {"reply": reply_payload}
        except asyncio.TimeoutError:
            with _bridge_state_lock:
                _bridge_state.get("pending_replies", {}).pop(msg_id, None)
            out = {"error": "timeout waiting for reply"}
            try:
                _log_diag(f"timeout waiting for reply id={msg_id}")
            except Exception:
                pass
        except Exception as e:
            with _bridge_state_lock:
                _bridge_state.get("pending_replies", {}).pop(msg_id, None)
            out = {"error": str(e), "trace": traceback.format_exc()}

        writer.write((json.dumps(out, default=str) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    except Exception as e:
        try:
            writer.write(
                (
                    json.dumps({"error": str(e), "trace": traceback.format_exc()})
                    + "\n"
                ).encode()
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def start_server(port: int = 8765, timeout: float = 10.0):
    if _bridge_state.get("running"):
        print("comm_bridge: already running on port", _bridge_state.get("port"))
        return _bridge_state

    try:
        registered = register_comm_target("jupyter.ggblab")
        _bridge_state["registered_target"] = bool(registered)
        if registered:
            print("comm_bridge: registered comm target jupyter.ggblab")
    except Exception:
        _bridge_state["registered_target"] = False

    def _runner(started_event: Optional[threading.Event] = None):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Prefer to bind to port 8765 if available; otherwise fall back to the
        # requested `port`. If both fail, propagate the last exception.
        ports_to_try = [8765]
        if port not in ports_to_try:
            ports_to_try.append(port)

        server = None
        last_exc = None
        for p in ports_to_try:
            try:
                server_coro = asyncio.start_server(
                    lambda r, w: _handle_client(r, w, timeout), "127.0.0.1", p
                )
                server = loop.run_until_complete(server_coro)
                bound_port = p
                break
            except Exception as e:
                last_exc = e
                # try next candidate port
                continue

        if server is None:
            # nothing succeeded; re-raise the last exception so caller sees error
            if last_exc is not None:
                raise last_exc
            else:
                raise RuntimeError("failed to bind server to any candidate port")
        _bridge_state["loop"] = loop
        _bridge_state["server"] = server
        _bridge_state["running"] = True
        # Determine actual bound port (important when port==0 / ephemeral)
        bound_port = None
        try:
            sv_socks = getattr(server, "sockets", None) or []
            if sv_socks:
                # pick first socket's bound port
                try:
                    bound_port = sv_socks[0].getsockname()[1]
                except Exception:
                    try:
                        bound_port = sv_socks[0].getsockname()
                    except Exception:
                        bound_port = port
        except Exception:
            bound_port = port

        _bridge_state["port"] = bound_port or port
        print(f'comm_bridge: listening on 127.0.0.1:{_bridge_state.get("port")}')
        # signal caller that server is ready and port is known
        try:
            if started_event is not None:
                started_event.set()
        except Exception:
            pass

        try:
            loop.run_forever()
        finally:
            server.close()
            loop.run_until_complete(server.wait_closed())
            loop.close()
            _bridge_state["running"] = False

    # start thread and wait briefly for server to become ready so we can return
    started = threading.Event()
    t = threading.Thread(target=lambda: _runner(started), daemon=True)
    t.start()
    _bridge_state["thread"] = t
    # wait up to a short timeout for the server to bind and report port
    try:
        started.wait(timeout=2.0)
    except Exception:
        pass
    return _bridge_state


def stop_server():
    try:
        loop = _bridge_state.get("loop")
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        t = _bridge_state.get("thread")
        if t:
            t.join(timeout=1.0)
    except Exception:
        pass
    try:
        if _bridge_state.get("registered_target"):
            unregister_comm_target()
    except Exception:
        pass
    _bridge_state.clear()


if __name__ == "__main__":
    print("comm_bridge: run start_server(port=8765) to launch server")


def get_state():
    try:
        with _bridge_state_lock:
            return dict(_bridge_state)
    except Exception:
        return dict(_bridge_state)


def dump_bridge_state():
    try:
        with _bridge_state_lock:
            s = dict(_bridge_state)
    except Exception:
        s = dict(_bridge_state)

    out = {
        "running": bool(s.get("running", False)),
        "port": s.get("port"),
        "registered_target": bool(s.get("registered_target", False)),
        "diag": s.get("diag", [])[-200:],
    }

    try:
        pending = s.get("pending_replies") or {}
        out["pending_count"] = len(pending)
        out["pending_ids"] = list(pending.keys())[:50]
    except Exception:
        out["pending_count"] = None

    try:
        stored = s.get("stored_replies") or {}
        out["stored_count"] = len(stored)
        out["stored_ids"] = list(stored.keys())[:50]
    except Exception:
        out["stored_count"] = None

    try:
        t = s.get("thread")
        out["thread_alive"] = (
            bool(t.is_alive()) if (t is not None and hasattr(t, "is_alive")) else False
        )
    except Exception:
        out["thread_alive"] = None

    try:
        server = s.get("server")
        sockets = []
        if server is not None:
            sv_socks = getattr(server, "sockets", None) or []
            for sock in sv_socks:
                try:
                    sockets.append(
                        {"fileno": sock.fileno(), "sockname": sock.getsockname()}
                    )
                except Exception as e:
                    sockets.append({"error": str(e)})
        out["server_sockets"] = sockets
    except Exception:
        out["server_sockets"] = None

    try:
        tc = s.get("target_comm")
        if tc is not None:
            cid = (
                getattr(tc, "comm_id", None) or getattr(tc, "target_name", None) or None
            )
            out["target_comm_id"] = cid
        else:
            out["target_comm_id"] = None
    except Exception:
        out["target_comm_id"] = None

    return out


def local_send(payload, timeout: float = 10.0):
    try:
        with _bridge_state_lock:
            tc = _bridge_state.get("target_comm")
        if tc is None:
            raise RuntimeError("no target_comm registered")

        msg_id = None
        if isinstance(payload, dict):
            msg_id = payload.get("id")
            if not msg_id:
                msg_id = str(uuid.uuid4())
                payload = dict(payload)
                payload["id"] = msg_id
        else:
            msg_id = str(uuid.uuid4())

        send_payload = payload
        try:
            if not isinstance(payload, (str, bytes)):
                send_payload = json.dumps(payload)
        except Exception:
            try:
                send_payload = str(payload)
            except Exception:
                send_payload = payload

        tc.send(send_payload)

        end = time.time() + float(timeout)
        while time.time() < end:
            with _bridge_state_lock:
                stored = _bridge_state.get("stored_replies", {})
                val = stored.pop(msg_id, None)
            if val is not None:
                return val
            time.sleep(0.01)

        raise TimeoutError("timeout waiting for reply")
    except Exception:
        raise
