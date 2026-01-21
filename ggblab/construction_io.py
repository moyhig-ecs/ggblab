"""Compatibility shim for `ggblab_extra.construction_io`.

This module intentionally avoids importing `ggblab_extra` at import time
so that projects that only build `ggblab` do not fail when
`ggblab_extra` isn't installed. The real implementations are imported
on-demand when the wrapper classes are instantiated.
"""
import warnings


def _import_impl():
    try:
        from ggblab_extra.construction_io import ConstructionIO as _C, DataFrameIO as _D
    except Exception as e:
        raise ImportError(
            "ggblab_extra is not available. Install the project in editable mode (pip install -e .) or install ggblab_extra so ConstructionIO is available."
        ) from e
    warnings.warn(
        "ggblab.construction_io is deprecated; import from ggblab_extra.construction_io instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _C, _D


class ConstructionIO:
    """Lazy wrapper for the real `ConstructionIO` implementation.

    Instantiating this class imports the real implementation from
    `ggblab_extra.construction_io`. Import errors are raised only when
    the class is actually used.
    """

    def __init__(self, *args, **kwargs):
        Impl, _ = _import_impl()
        self._impl = Impl(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._impl, name)


class DataFrameIO:
    """Lazy wrapper for the real `DataFrameIO` implementation."""

    def __init__(self, *args, **kwargs):
        _, Impl = _import_impl()
        self._impl = Impl(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._impl, name)


__all__ = ["ConstructionIO", "DataFrameIO"]
