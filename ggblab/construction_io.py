"""Compatibility shim for `ggblab_extra.construction_io`.

This module intentionally avoids importing `ggblab_extra` at import time
so that projects that only build `ggblab` do not fail when
`ggblab_extra` isn't installed. The real implementations are imported
on-demand when the wrapper classes are instantiated.

Note:
    Full DataFrame-based construction I/O and heavy parsing utilities live in
    `ggblab_extra.construction_io`. Install `ggblab_extra` to access the
    complete implementations (recommended for workflows that use Polars or
    require the `save_dataframe` helper). This shim emits DeprecationWarning
    when used and will be removed in a future major release.
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
        """Import and instantiate the real `ConstructionIO` implementation."""
        Impl, _ = _import_impl()
        self._impl = Impl(*args, **kwargs)

    def __getattr__(self, name):
        """Delegate attribute access to the underlying implementation."""
        return getattr(self._impl, name)


class DataFrameIO:
    """Lazy wrapper for the real `DataFrameIO` implementation."""

    def __init__(self, *args, **kwargs):
        """Import and instantiate the real `DataFrameIO` implementation."""
        _, Impl = _import_impl()
        self._impl = Impl(*args, **kwargs)

    def __getattr__(self, name):
        """Delegate attribute access to the underlying implementation."""
        return getattr(self._impl, name)


__all__ = ["ConstructionIO", "DataFrameIO"]
