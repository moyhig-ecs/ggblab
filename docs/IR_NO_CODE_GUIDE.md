IR extension for no-code inference
================================

This document describes the minimal IR extensions and conventions used to enable
no-code pattern detection (Thales, Pythagoras, Cosine-law, Projection, Geometric mean)
without writing custom Python logic.

Key additions
- `commands[].id` and `elements[].command_id`: explicit linking by id
- `commands[].normalized`: structured form for commands where ordering/semantics matter
- `elements[].computed`: numeric precomputations (angles, dot-products, distances)
- `inferences[]`: declarative inference records (pattern name, subjects, evidence, confidence)

Workflow
- Produce base IR using existing pipeline (XML -> IR). Use `scripts/ir_transform.py` to
  convert and enrich the IR with the fields above. The transform will optionally validate
  the result against `docs/ir_extended_schema.json`.

Search & Queries (no-code)
- Use `by_layer` or `elements[*].type` to filter candidate elements.
- Find `inferences[*].pattern=='thales'` to list detected Thales instances.
- Query `elements[*].computed.degree_at_vertex` to find right angles.

See `docs/ir_extended_schema.json` for the formal schema and `scripts/ir_transform.py`
for implementation details used to generate the extended IR.
