# ggblab Documentation

Welcome to the ggblab documentation. This site contains comprehensive guides, design documents, and technical references for the ggblab JupyterLab extension.

## Quick Start

- [README](../README.md) - Installation and basic usage
- [TODO](../TODO.md) - Development roadmap and priorities

## Design & Architecture

### [Philosophy](philosophy.md)
Core design principles, scope boundaries, and educational vision for ggblab. Covers communication architecture, GeoGebra + Python complementarity, and the geometric scene evolution paradigm.

### [Scoping](scoping.md)
Foundational educational mission: using geometric scene construction to teach variable scoping and computational thinking. Includes pedagogical framework, classroom integration, and implementation details.

### [Architecture](architecture.md)
Technical deep-dive into ggblab's dual-channel communication design (IPython Comm + out-of-band sockets), error handling, resource lifecycle, and dependency parser architecture.

### [SymPy Integration](sympy_integration.md)
Design specification for symbolic computation integration. Covers GeoGebra ↔ SymPy conversion, symbolic verification, code generation, and advanced solvers (locus, envelope, constraints).

---

## Key Features

### Communication Architecture
- Dual-channel design: IPython Comm (primary) + Unix socket/TCP (secondary)
- Works with Jupyter, JupyterHub, Google Colab
- Handles both idle and long-running cell execution

### Educational Focus
- **Scoping Pedagogy**: Map geometric dependencies to programming scopes
- **Dependency Visualization**: Interactive dependency graphs
- **Symbolic Verification**: Prove geometric properties with SymPy
- **Code Generation**: Export constructions as reproducible Python

### Future Roadmap
- **v0.8**: Scene Timeline (snapshots and playback)
- **v1.0**: Numerical integration (scipy ODE solving)
- **v1.0 - v1.5**: Manim export (publication-quality animations)
- **v1.1+**: SymPy integration, advanced lesson modules

---

## For Developers

- Review the [Architecture](architecture.md) document for communication design details
- Check [TODO.md](../TODO.md) for open issues and priorities
- See each design document for implementation roadmaps and testing strategies

---

## For Educators

- Start with [Scoping](scoping.md) to understand the pedagogical framework
- Review classroom integration strategies in [Scoping § 6](scoping.md#6-classroom-integration)
- Design documents contain lesson progression examples and assessment rubrics

---

## For Users

- See [README](../README.md) for installation and first steps
- Each design document includes example code and usage patterns
- Check [TODO.md](../TODO.md) for feature status and version roadmap

---

## Document Index

| Document | Focus | Audience |
|----------|-------|----------|
| [Philosophy](philosophy.md) | Design principles & vision | Architects, educators |
| [Scoping](scoping.md) | Educational framework | Educators, designers |
| [Architecture](architecture.md) | Technical implementation | Developers |
| [SymPy Integration](sympy_integration.md) | Symbolic computation | Developers, mathematicians |

---

**Last Updated**: January 2026

For questions or contributions, see the main [README](../README.md).
