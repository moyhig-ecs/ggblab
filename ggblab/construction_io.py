"""Backward-compat shim for `ggblab.construction_io`.

The real implementation lives in `ggblab_extra.construction_io`. This shim
re-exports the implementation to avoid breaking imports that still refer to
`ggblab.construction_io` while emitting a deprecation warning.
"""

import warnings

try:
    from ggblab_extra.construction_io import ConstructionIO, DataFrameIO  # type: ignore
    warnings.warn(
        "Importing from 'ggblab.construction_io' is deprecated; use 'ggblab_extra.construction_io' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
except Exception:
    # If ggblab_extra is not available, surface the underlying error
    raise

__all__ = ["ConstructionIO", "DataFrameIO"]
