"""py_comm_bridge

A small TCP -> frontend Comm bridge intended to run inside a Python kernel
that is connected to the Jupyter frontend (for example, the Python "kernel2"
process used to host front-end comms). The bridge accepts one-line JSON
requests on localhost and forwards them to the frontend using an
``ipykernel.comm.Comm`` with the target name ``jupyter.ggblab``. It waits for
the first reply on that Comm and returns the reply as a single-line JSON
response over the same TCP connection.

Usage (package import, recommended -- run inside the Python kernel):

        from ggblab_core import start_bridge, stop_bridge
        start_bridge(port=8765, timeout=10.0)

Use ``stop_bridge()`` to stop the background server.

Quick test (from another process):

        # echo a JSON payload and receive a JSON response
        printf '{"op":"ping"}\n' | nc 127.0.0.1 8765

Notes
-----
- The function is intentionally minimal: it creates a short-lived Comm per
    incoming TCP connection and closes it after the first reply (or timeout).
- The frontend must have a comm target registered such as ``jupyter.ggblab``
    that will handle incoming requests and send replies.
"""

import threading
import asyncio
import json
import traceback
from typing import Optional
import uuid
import time

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


def register_comm_target(target_name: str = 'jupyter.ggblab'):
    """Register an IPython Comm target so frontends can open comms to kernel.

    The callback stores the opened comm in `_bridge_state['target_comm']`
    and installs an `on_msg` handler that places incoming messages into
    `_bridge_state['incoming_msgs']` for diagnostics or further routing.
    """
    if get_ipython is None:
        return False
    try:
        ip = get_ipython()
        if ip is None:
            return False
        km = getattr(ip, 'kernel', None)
        if km is None:
            return False
        cm = getattr(km, 'comm_manager', None)
        if cm is None:
            return False

        def _target_cb(comm, open_msg):
            try:
                with _bridge_state_lock:
                    _bridge_state['target_comm'] = comm
                    _bridge_state.setdefault('incoming_msgs', [])

                def _on_msg(msg):
                    try:
                        data = msg.get('content', {}).get('data', msg)
                    except Exception:
                        data = msg

                    # If message contains an 'id', route it to the waiting TCP client
                    msg_id = None
                    try:
                        if isinstance(data, dict):
                            msg_id = data.get('id')
                    except Exception:
                        msg_id = None

                    if msg_id:
                        # fulfill any pending future associated with this id
                        with _bridge_state_lock:
                            pending = _bridge_state.get('pending_replies', {})
                            entry = pending.pop(msg_id, None) if pending else None
                        if entry:
                            fut, fut_loop = entry
                            try:
                                if fut_loop is not None and getattr(fut_loop, 'is_running', lambda: False)():
                                    fut_loop.call_soon_threadsafe(fut.set_result, data.get('payload', data))
                                else:
                                    fut.set_result(data.get('payload', data))
                            except Exception:
                                try:
                                    fut.set_result(data)
                                except Exception:
                                    pass
                        return

                    # otherwise, queue as an incoming event
                    with _bridge_state_lock:
                        _bridge_state.setdefault('incoming_msgs', []).append(data)

                try:
                    comm.on_msg(_on_msg)
                except Exception:
                    pass

                def _on_close():
                    try:
                        with _bridge_state_lock:
                            _bridge_state.pop('target_comm', None)
                    except Exception:
                        pass

                try:
                    comm.on_close(_on_close)
                except Exception:
                    pass
            except Exception:
                return

        # register target (best-effort)
        try:
            cm.register_target(target_name, _target_cb)
            _bridge_state['target_name'] = target_name
            return True
        except Exception:
            return False
    except Exception:
        return False


def unregister_comm_target():
    """Unregister the previously-registered comm target if possible."""
    try:
        ip = get_ipython()
        if ip is None:
            return False
        km = getattr(ip, 'kernel', None)
        if km is None:
            return False
        cm = getattr(km, 'comm_manager', None)
        if cm is None:
            return False
        tname = _bridge_state.get('target_name')
        if not tname:
            return False
        # Some CommManager implementations expose `unregister_target`
        unregister = getattr(cm, 'unregister_target', None)
        if callable(unregister):
            try:
                unregister(tname)
            except Exception:
                pass
        # clear stored state
        _bridge_state.pop('target_name', None)
        _bridge_state.pop('target_comm', None)
        _bridge_state.pop('incoming_msgs', None)
        return True
    except Exception:
        return False

async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float):
    peer = writer.get_extra_info('peername')
    try:
        data = await reader.readline()
        if not data:
            writer.close()
            await writer.wait_closed()
            return
        text = data.decode('utf-8', errors='replace').strip()
        try:
            payload = json.loads(text)
        except Exception:
            # If not JSON, forward raw string
            payload = text

        # Use the registered comm target for sending/receiving messages.
        if Comm is None:
            resp = {"error": "ipykernel.comm.Comm not available in this kernel"}
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        loop = asyncio.get_event_loop()

        # Ensure a target_comm is available (wait briefly)
        waited = 0.0
        tc = None
        while waited < 2.0:
            with _bridge_state_lock:
                tc = _bridge_state.get('target_comm')
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

        # Determine message id
        try:
            if isinstance(payload, dict) and 'id' in payload:
                msg_id = payload['id']
            else:
                msg_id = str(uuid.uuid4())
                if isinstance(payload, dict):
                    payload['id'] = msg_id
        except Exception:
            msg_id = str(uuid.uuid4())

        fut = loop.create_future()

        # store pending future with its loop so comm callback can fulfill it
        with _bridge_state_lock:
            _bridge_state.setdefault('pending_replies', {})[msg_id] = (fut, loop)

        # Send message via the stored comm. Use kernel io_loop if available.
        sent = False
        try:
            try:
                ip = get_ipython()
                kernel = getattr(ip, 'kernel', None)
                io_loop = getattr(kernel, 'io_loop', None)
                if io_loop is not None and hasattr(io_loop, 'add_callback'):
                    try:
                        io_loop.add_callback(lambda: tc.send(payload))
                        sent = True
                    except Exception:
                        sent = False
                else:
                    tc.send(payload)
                    sent = True
            except Exception:
                # last resort: attempt direct send
                try:
                    tc.send(payload)
                    sent = True
                except Exception as e:
                    sent = False
                    with _bridge_state_lock:
                        _bridge_state.get('pending_replies', {}).pop(msg_id, None)
                    out = {"error": f"Failed to send on registered Comm: {e}"}
                    writer.write((json.dumps(out) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
        except Exception as e:
            with _bridge_state_lock:
                _bridge_state.get('pending_replies', {}).pop(msg_id, None)
            out = {"error": f"Failed to send message: {e}", "trace": traceback.format_exc()}
            writer.write((json.dumps(out, default=str) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Await reply via the pending future
        try:
            reply_payload = await asyncio.wait_for(fut, timeout=timeout)
            out = {"reply": reply_payload}
        except asyncio.TimeoutError:
            with _bridge_state_lock:
                _bridge_state.get('pending_replies', {}).pop(msg_id, None)
            out = {"error": "timeout waiting for reply"}
        except Exception as e:
            with _bridge_state_lock:
                _bridge_state.get('pending_replies', {}).pop(msg_id, None)
            out = {"error": str(e), "trace": traceback.format_exc()}

        writer.write((json.dumps(out, default=str) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    except Exception as e:
        try:
            writer.write((json.dumps({"error": str(e), "trace": traceback.format_exc()}) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def start_bridge(port: int = 8765, timeout: float = 10.0):
    """Start the bridge server in a background thread.

    Returns a dict with `thread` and `port`. To stop the bridge, call
    `stop_bridge()` which will cancel the asyncio loop and thread.
    """
    if _bridge_state.get('running'):
        print('py_comm_bridge: already running on port', _bridge_state.get('port'))
        return _bridge_state

    # Best-effort: register an IPython Comm target so frontends can open
    # comms to this kernel under the expected name.
    try:
        registered = register_comm_target('jupyter.ggblab')
        _bridge_state['registered_target'] = bool(registered)
        if registered:
            print('py_comm_bridge: registered comm target jupyter.ggblab')
    except Exception:
        _bridge_state['registered_target'] = False

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server_coro = asyncio.start_server(lambda r, w: _handle_client(r, w, timeout), '127.0.0.1', port)
        server = loop.run_until_complete(server_coro)
        _bridge_state['loop'] = loop
        _bridge_state['server'] = server
        _bridge_state['running'] = True
        _bridge_state['port'] = port
        print(f'py_comm_bridge: listening on 127.0.0.1:{port}')
        try:
            loop.run_forever()
        finally:
            server.close()
            loop.run_until_complete(server.wait_closed())
            loop.close()
            _bridge_state['running'] = False

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    _bridge_state['thread'] = t
    return _bridge_state


def stop_bridge():
    """Stop the running bridge if any."""
    try:
        loop = _bridge_state.get('loop')
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        t = _bridge_state.get('thread')
        if t:
            t.join(timeout=1.0)
    except Exception:
        pass
    # Try to unregister the comm target if we registered it
    try:
        if _bridge_state.get('registered_target'):
            unregister_comm_target()
    except Exception:
        pass
    _bridge_state.clear()


if __name__ == '__main__':
    print('py_comm_bridge: run start_bridge(port=8765) to launch server')


def get_bridge_state():
    """Return a shallow copy of the bridge internal state for debugging."""
    try:
        with _bridge_state_lock:
            return dict(_bridge_state)
    except Exception:
        return dict(_bridge_state)
