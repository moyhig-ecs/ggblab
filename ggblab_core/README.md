# ggblab_core (minimal)

This small package provides a synchronous Comm wrapper (`CommSync`)
that works with `jupyter_client.BlockingKernelClient`.

Key points:
- Synchronous: uses blocking channel receive calls, no OOB event loop.
- Comm-based: expects a kernel-side comm target to be registered.
- Minimal: only open/send/close are provided.

Kernel snippet and client usage are in `example.py`.

## py_comm_bridge (TCP -> frontend Comm)

The repository includes a lightweight bridge ``py_comm_bridge`` intended to
run inside a Python kernel that is connected to the frontend. It accepts
single-line JSON requests on localhost and forwards them to the frontend
via an ``ipykernel.comm`` with target ``jupyter.ggblab``. The bridge waits for
the first reply and returns it as a single-line JSON response.

Usage (in a Python kernel):

```python
from ggblab_core import start_server, stop_server
start_server(port=8765, timeout=10.0)
# ... when finished
stop_bridge()
```

Quick test (from another process):

```sh
printf '{"op":"ping"}\n' | nc 127.0.0.1 8765
```

Notes:
- The frontend must register a comm target (e.g. ``jupyter.ggblab``) that will
  receive the forwarded payload and send a reply.
- For higher throughput or persistent sessions, consider evolving the bridge
  to reuse a single Comm instead of opening a new Comm per TCP request.
