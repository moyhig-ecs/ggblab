"""ggblab_vscode Python package used by the VS Code extension for kernel websocket client helpers.

Expose `GGBlabWSClient` for easy import inside kernels:

	from ggblab_vscode import GGBlabWSClient
"""

from .ggblab_ws_client import GGBlabWSClient

__all__ = ["GGBlabWSClient"]
