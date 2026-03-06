"""ggblab_core2

Kernel-focused core package extracted from `ggblab`.

This package contains the modules that directly depend on the communication
bridge (comm, ggbapplet, utils). Code was moved from `ggblab.*` to create a
clean separation for kernel-specific functionality used by `kernel2`.
"""

__all__ = [
    'comm',
    'ggbapplet',
    'utils',
]
