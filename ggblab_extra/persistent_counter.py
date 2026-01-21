"""Compatibility shim exposing `PersistentCounter` in ``ggblab_extra``.

Re-exports the implementation from the core ``ggblab`` package so code
that imports ``ggblab_extra.persistent_counter`` keeps working.
"""
import warnings

try:
    from ggblab.persistent_counter import PersistentCounter as _PC
except Exception as e:
    raise ImportError("Failed to import PersistentCounter from ggblab.persistent_counter") from e

warnings.warn(
    "Importing 'PersistentCounter' from 'ggblab_extra' is deprecated; use 'ggblab.persistent_counter' instead.",
    DeprecationWarning,
    stacklevel=2,
)

class PersistentCounter(_PC):
    """Deprecated wrapper for the core PersistentCounter implementation."""

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "PersistentCounter from 'ggblab_extra' is deprecated; import from 'ggblab.persistent_counter'",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


__all__ = ["PersistentCounter"]
