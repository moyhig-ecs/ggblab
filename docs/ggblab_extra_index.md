# Advanced Tools (ggblab_extra)

The advanced analysis and educational tools live in the optional package `ggblab_extra` rather than in the core `ggblab` package. These tools include extended parsing, scene development guides, symbolic integration helpers, and larger I/O utilities.

## How to view the extras documentation

- If you have the `ggblab_extra` sources available locally, you can copy its documentation files into this `docs/ggblab_extra/` folder so Sphinx/ReadTheDocs will build them together with the core docs.
- Alternatively, install `ggblab_extra` in editable mode and open the package README and source files directly:
  - Install editable: `pip install -e .[dev]` from the project root (or install the published `ggblab_extra` package if available).
  - Read the package README and guides in the `ggblab_extra` source tree.

## Including extras in ReadTheDocs builds

To include the detailed `ggblab_extra` guides in the hosted documentation, add those Markdown files under `docs/ggblab_extra/` and reference them from `docs/root.rst`. This keeps the core docs lightweight while making the extras available on ReadTheDocs.

If you'd like, I can either:

- (A) Copy the existing `ggblab_extra` guide files into `docs/ggblab_extra/` and update the toctree to include them, or
- (B) Leave this index as the canonical pointer and add a short external link or README excerpt describing where to find the full guides. The README excerpt and install instructions below are provided as a quick pointer for ReadTheDocs users and local readers.

## README excerpt (short)

`ggblab_extra` contains advanced analysis and educational tooling that is optional to the core package. It includes:

- Extended construction parsing and DataFrame-based I/O
- Scene development guides and educational workflows
- Symbolic integration helpers (SymPy) and scene verification tools

## Installation & quick access

- From the project root (sources present):

```bash
pip install -e .[dev]
```

- From PyPI (if published):

```bash
pip install ggblab-extra
```

After installing, open the `ggblab_extra` package README or the `ggblab_extra/docs/` folder in the source tree for the full guides. If you prefer the extras to appear in this ReadTheDocs build, I can copy their Markdown files into `docs/ggblab_extra/` and add them to the toctree.

Which option do you prefer?
