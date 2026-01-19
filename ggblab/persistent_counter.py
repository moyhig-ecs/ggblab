"""Deprecated shim: PersistentCounter moved to ggblab_extra."""
import warnings

try:
    from ggblab_extra.persistent_counter import PersistentCounter  # type: ignore
except ImportError as exc:
    raise ImportError(
        "PersistentCounter has moved to ggblab_extra. "
        "Install ggblab-extra and import from ggblab_extra instead."
    ) from exc

warnings.warn(
    "Importing 'PersistentCounter' from 'ggblab' is deprecated. "
    "Use 'from ggblab_extra import PersistentCounter' instead. "
    "This shim will be removed in ggblab 1.0.0.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ["PersistentCounter"]
