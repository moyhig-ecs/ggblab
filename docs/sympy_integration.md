````markdown
# SymPy Integration (overview)

This document provides an overview of the planned SymPy integration for ggblab.

NOTE: Advanced, implementation-specific guides and examples live in the
optional `ggblab_extra` package. See `docs/ggblab_extra_index.md` for how to
access those files or install `ggblab_extra` locally.

## Goals

- Provide a bridge between GeoGebra constructions and symbolic mathematics
  (SymPy) for verification and code generation.
- Support symbolic proofs of geometric relations (collinearity, concurrency,
  equal distances/angles, tangency, etc.).
- Enable export of symbolic results to Manim or other animation tooling.

## Scope (core)

- Lightweight converters from GeoGebra expression tokens → SymPy expressions.
- A small set of verification utilities for common geometric predicates.
- APIs for requesting symbolic computations from the notebook and returning
  human-readable proofs and verification reports.

## Advanced features (ggblab_extra)

The following capabilities are planned as advanced features and are provided
by the optional `ggblab_extra` package rather than the core `ggblab`:

- Full construction-to-SymPy translation covering complex dependent objects.
- Automated proof generation pipelines and step-by-step symbolic reasoning.
- Code generation helpers (SymPy → Python/Manim snippets) for reproducible
  visualizations.

## How to use (developer notes)

1. Consider enabling SymPy in your environment: `pip install sympy`.
2. Use the high-level API (planned):

```
from ggblab import GeoGebra
ggb = await GeoGebra().init()
# hypothetical API
res = await ggb.sympy.verify("Circle(A,B) is tangent to Line(C,D)")
```

For full implementation details and examples, consult the `ggblab_extra`
package documentation or install the extras locally and copy their docs into
`docs/ggblab_extra/`.

````
