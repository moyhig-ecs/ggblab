"""ggblab_core: Minimal core providing synchronous Comm via BlockingKernelClient.

This package provides a small synchronous Comm wrapper suitable for
use from external clients (for example IJulia.jl via PyCall) when a
`jupyter_client.BlockingKernelClient` is available.

See `ggblab_core/comm.py` for the main API.
"""

from .comm import CommSync
from .utils import load_blocking_client
from .kernel_comm import KernelComm, get_kernel_comm
from .applet import AppletInjector

__all__ = ["CommSync", "load_blocking_client", "KernelComm", "get_kernel_comm", "AppletInjector"]
