# ggblab_core (minimal)

This small package provides a synchronous Comm wrapper (`CommSync`)
that works with `jupyter_client.BlockingKernelClient`.

Key points:
- Synchronous: uses blocking channel receive calls, no OOB event loop.
- Comm-based: expects a kernel-side comm target to be registered.
- Minimal: only open/send/close are provided.

Kernel snippet and client usage are in `example.py`.
