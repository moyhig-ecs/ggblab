"""Compatibility shim for ggblab_core2 utils.

This module re-exports `called_from_julia` from the single canonical
implementation in `ggblab.utils_julia` to avoid duplication and import
cycles across the package boundary.
"""

from typing import Any

try:
    from ggblab.utils_julia import called_from_julia  # type: ignore
except Exception:  # pragma: no cover - fall back safe stub

    def called_from_julia(*args: Any, **kwargs: Any) -> bool:  # type: ignore
        return False


__all__ = ["called_from_julia"]
