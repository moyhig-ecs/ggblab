# TODO — Next session (short list)

Planned tasks to work on next:

1. Harden Thales detection in `ir_transform.py` — make detection robust to input ordering and fallback to numeric checks.
2. Add Pythagoras detection (angle + distance checks) and emit inferences.
3. Add Cosine-law detection (detect `cos` expressions and verify via distances/angles).
4. Detect Projection / Γ expressions and map results to element `metadata`.
5. Expand `computed` fields (distances, dot products, on_circle checks, unit vectors).
6. Emit `inferences` for all detected patterns and generate CSV reports per layer.
7. Run the full pipeline on `examples/2025_13_01.xml` and review/verify results.
8. Document usage: add README snippets for transform & detection workflow.

Notes:

- Use `scripts/ir_transform.py` as the integration point. Add unit-checking tolerances and confidence scoring.
- Prefer writing `inferences` declaratively into the extended IR so downstream UIs can consume without code.
