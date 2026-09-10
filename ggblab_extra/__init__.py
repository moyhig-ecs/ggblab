"""ggblab_extra (v2): analysis on top of Construction / construction XML — data-in only, no communication.
Stage 2 "algebra" (2026-09-10): `geometry_ir` (the XML's own numbers per element + the command DAG) and `sympy`
(v1's SymPy helpers, host coupling removed, plus `from_ir` builders)."""
from .construction_io import ConstructionIO, DataFrameIO, read_ggb
from .geometry_ir import ElementIR, CommandIR, element_irs, command_edges, attach_ir
__all__ = ["ConstructionIO", "DataFrameIO", "read_ggb", "ElementIR", "CommandIR", "element_irs", "command_edges", "attach_ir"]
