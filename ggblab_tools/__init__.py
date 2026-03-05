"""ggblab_tools package: proxy Jupyter kernel that forwards to real kernels."""

from . import proxy_kernel

# Provide the ggblab_kernel subpackage for explicit imports. Avoid importing
# launcher/installer modules here to prevent side-effects when running as
# `python -m ggblab_tools.ggblab_kernel.proxy_launcher`.
from . import ggblab_kernel

__all__ = [
	"proxy_kernel",
	"ggblab_kernel",
]
