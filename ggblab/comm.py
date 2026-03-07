"""Compatibility shim: communication primitives moved to `ggblab_core2.comm`.

This module is kept for backward compatibility. Import from
`ggblab_core2.comm` instead.
"""

import warnings

warnings.warn(
    "ggblab.comm has moved to ggblab_core2.comm; import from ggblab_core2",
    DeprecationWarning,
)

from ggblab_core2.comm import *  # noqa: F401,F403

try:
    __all__ = ggblab_core2.comm.__all__
except Exception:
    __all__ = []
