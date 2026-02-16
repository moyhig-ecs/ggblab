"""Compatibility wrapper exposing graph similarity helpers from
`ggblab_extra.graph_similarity` under the `ggblab` package.

This keeps the old import path `ggblab.graph_similarity` working while
the implementation lives in `ggblab_extra`.
"""
from ggblab_extra.graph_similarity import (
    cost_between,
    collapse_scc,
    hungarian_similarity,
)

__all__ = [
    'cost_between',
    'collapse_scc',
    'hungarian_similarity',
]
