"""ggblab_extra: optional helpers split out from the core package.

`ggblab_extra` contains non-essential helpers, heavy I/O utilities and
backward-compatible shims that were previously part of `ggblab`.

Install this package when you need Polars-based construction I/O,
convenience utilities (e.g. ``ConstructionIO.save_dataframe``), or the
legacy parser compatibility layers. Consumers that only require the
lightweight runtime should depend on the core ``ggblab`` package; the
core package avoids importing these extras at import time to keep
startup lightweight.
"""

from .construction_io import ConstructionIO, DataFrameIO  # re-export for convenience
from .construction_parser import ConstructionTreeParser, ggb_parser  # re-export parser
from .graph_similarity import hungarian_similarity, collapse_scc, cost_between

__all__ = [
	"ConstructionIO",
	"DataFrameIO",
	"ConstructionTreeParser",
	"ggb_parser",
	"hungarian_similarity",
	"collapse_scc",
	"cost_between",
]

# Optional SymPy helpers are provided as a dedicated subpackage. Import
# `ggblab_extra.sympy` when you need SymPy-based utilities to avoid pulling
# heavy dependencies at top-level package import.
__all__ += ["sympy"]
