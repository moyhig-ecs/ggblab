"""Utilities for ggblab_core.

Provides helpers to create a `BlockingKernelClient` from a Jupyter
connection file. The function intentionally performs minimal validation
and raises clear errors for missing files or missing dependencies.
"""
from pathlib import Path
from typing import Any

try:
    from jupyter_client import BlockingKernelClient
except Exception:  # pragma: no cover - runtime import fallback
    BlockingKernelClient = None  # type: ignore


def load_blocking_client(connection_file: str) -> Any:
    """Create and return a `BlockingKernelClient` loaded from JSON file.

    Raises `FileNotFoundError` if `connection_file` does not exist.
    Raises `RuntimeError` if `jupyter_client` is not available.
    """
    p = Path(connection_file)
    if not p.exists():
        raise FileNotFoundError(f"Connection file not found: {connection_file}")
    if BlockingKernelClient is None:
        raise RuntimeError("jupyter_client.BlockingKernelClient is required")
    kc = BlockingKernelClient()
    kc.load_connection_file(str(p))
    return kc
