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

# Bridge utility (TCP -> frontend Comm)
try:
	from comm_bridge.server import start_server, stop_server, get_state
except Exception:
	def _bridge_unavailable(*args, **kwargs):
		raise RuntimeError('comm_bridge.server not available in this environment')

	start_server = stop_server = get_state = _bridge_unavailable

__all__ = [
	"CommSync",
	"load_blocking_client",
	"KernelComm",
	"get_kernel_comm",
	"AppletInjector",
	"start_server",
	"stop_server",
	"get_state",
]
