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

try:
    from ipykernel.comm import Comm
except Exception:
    Comm = None

_bridge_state = {}

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

        if Comm is None:
            resp = {"error": "ipykernel.comm.Comm not available in this kernel"}
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Create a comm for this request. The frontend should have a target
        # 'jupyter.ggblab' or similar registered for this kernel session.
        comm = None
        try:
            comm = Comm(target_name='jupyter.ggblab')
        except Exception as e:
            # Try alternative constructor shapes
            try:
                comm = Comm(target_name='jupyter.ggblab', data={})
            except Exception as ee:
                resp = {"error": "Failed to open Comm: %s" % (str(ee),)}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

        loop = asyncio.get_event_loop()
        fut = loop.create_future()

        def _on_msg(msg):
            try:
                # msg is a dict-like with content.data
                d = msg.get('content', {}).get('data', msg)
            except Exception:
                d = msg
            if not fut.done():
                fut.set_result(d)

        try:
            comm.on_msg(_on_msg)
        except Exception:
            # some Comm objects expose `on_msg` as attribute or method
            try:
                comm.on_msg(_on_msg)
            except Exception:
                pass

        # send payload (ipykernel Comm supports dicts)
        try:
            comm.send(payload)
        except Exception as e:
            # try sending JSON string
            try:
                comm.send(json.dumps(payload))
            except Exception as ee:
                resp = {"error": "Failed to send on Comm: %s" % (str(ee),)}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                try:
                    comm.close()
                except Exception:
                    pass
                return

        # wait for reply with timeout
        try:
            reply = await asyncio.wait_for(fut, timeout=timeout)
            out = {"reply": reply}
        except asyncio.TimeoutError:
            out = {"error": "timeout waiting for reply"}
        except Exception as e:
            out = {"error": str(e), "trace": traceback.format_exc()}

        try:
            comm.close()
        except Exception:
            pass

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
    _bridge_state.clear()


if __name__ == '__main__':
    print('py_comm_bridge: run start_bridge(port=8765) to launch server')
