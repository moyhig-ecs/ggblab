# ggblab-extra

Extended functionality for [ggblab](https://github.com/moyhig-ecs/ggblab): construction parsing, scene verification, and educational tools.

## Overview

`ggblab-extra` provides advanced analysis and educational tools for GeoGebra constructions:

- **Construction Parser**: Dependency graph analysis using NetworkX
- **Scene Verification**: Automated testing infrastructure for geometric constructions
- **Educational Tools**: Layer-based playback and verification for curricula

**Migration note (from ggblab core):** `ggb_parser` and `scene_verification`
previously shipped inside `ggblab`. They now live here. Core still provides
`.ggb` I/O via `ggb_file` (alias `ggb_construction`), while advanced parsing and
verification live in `ggblab-extra`. Update imports accordingly:

```python
# Core .ggb I/O
from ggblab import ggb_file  # or ggb_construction alias

# Advanced parsing / verification
from ggblab_extra import ggb_parser, SceneVerifier, ScenePlayback
```

## Installation

```bash
pip install ggblab-extra
```

Or for development:

```bash
cd ggblab-extra
pip install -e ".[dev]"
```

## Quick Start

### Parse a GeoGebra Construction

```python
from ggblab import ggb_file  # or ggb_construction for backward compatibility
from ggblab_extra import ggb_parser

# Load a .ggb file
file = ggb_file()
file.load('myfile.ggb')

# Parse dependencies
parser = ggb_parser()
parser.df = file.to_dataframe()  # Convert to DataFrame
parser.parse()

# Analyze dependency graph
print(f"Root objects: {parser.roots}")
print(f"Leaf objects: {parser.leaves}")
```

### Verify a Scene

```python
from ggblab import GeoGebra
from ggblab_extra import SceneVerifier

ggb = await GeoGebra().init()
verifier = SceneVerifier(ggb)

# Verify all objects
results = await verifier.verify_all()
report = verifier.summary(results)
print(report)
```

### Scene Playback (Layer-by-layer)

```python
from ggblab_extra import ScenePlayback

playback = ScenePlayback(ggb, construction_df)

# Play construction layer by layer
await playback.play_layer(0)  # Free points
await playback.play_layer(1)  # Dependent objects
await playback.play_all_layers()  # Complete construction
```

## Modules

| Module | Description |
|--------|-------------|
| `parser` | Dependency graph analysis with NetworkX |
| `scene_verification` | Verification and playback infrastructure |

## Dependencies

- **ggblab** (>=0.9.0): Core GeoGebra interaction and .ggb file I/O
- **polars** (>=0.20.0): High-performance DataFrames
- **networkx** (>=3.0): Graph analysis

## Use Cases

### Educational Curricula
- **textbook-2025**: 15-chapter geometry curriculum
- **textbook-2026**: Student-led rediscovery projects
- Layer-based construction playback
- Automated verification of student work

### Research & Analysis
- Dependency graph visualization
- Construction protocol analysis
- Command extraction and learning
- Minimal subgraph computation

## License

BSD 3-Clause License (same as ggblab)

## Documentation

- **[Scene Development Guide](./docs/geometric_scene_development_guide.md)**: Comprehensive pedagogical framework for GeoGebra scene design
- **[Scene Development Quick Start](./docs/SCENE_DEVELOPMENT_QUICK_START.md)**: Quick reference for implementing scenes
- **[Session Summary](./SCENE_DEVELOPMENT_SESSION_SUMMARY.md)**: Development session notes and best practices
- **[ggblab API Reference](https://ggblab.readthedocs.io)**: Complete API documentation

## Related Projects

- [ggblab](https://github.com/moyhig-ecs/ggblab): Core JupyterLab extension
- [textbook-2025](https://github.com/Cloudedu-Osaka/textbook-2025): Geometry curriculum
