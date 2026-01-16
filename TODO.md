# ggblab Development TODO

## Roadmap Overview (docs alignment)

This TODO consolidates Roadmap and Future Works from:
- [docs/philosophy.md](docs/philosophy.md) — Tiers 1–5 (education-first)
- [docs/scoping.md](docs/scoping.md) — Pedagogical roadmap (v0.8–v1.2)
- [docs/architecture.md](docs/architecture.md) — Communication design, launch strategy, testing, parser
- [docs/sympy_integration.md](docs/sympy_integration.md) — SymPy bridge roadmap (v1.1+)

Version focus:
- ✅ **v0.7.3**: Unit test coverage, parser fix, error handling, CI/CD pipeline
- v0.8–v1.0: Scene Timeline, launch strategy, error UX, strict types
- v1.0–v1.5: Manim export, numerical integration wrappers
- v1.1–v1.2: SymPy geometry bridge + verification

---

## Completed Milestones (v0.7.3)

### ✅ Testing & CI/CD Infrastructure

- ✅ **Unit tests**: Comprehensive pytest suite
  - `tests/test_parser.py`: 18 test classes, 70+ methods covering dependency analysis
  - `tests/test_ggbapplet.py`: 6 test classes, 16 methods for GeoGebra interface
  - `tests/test_construction.py`: 5 test classes testing file loading/saving
  - All tests validate error handling, edge cases, and large constructions

- ✅ **GitHub Actions CI/CD**: Automated testing pipeline
  - Workflow: [.github/workflows/tests.yml](.github/workflows/tests.yml)
  - Runs on `main`/`dev` branches for push and pull requests
  - Tests across Python 3.10, 3.11, 3.12 on Ubuntu, macOS, Windows
  - Coverage reports uploaded to Codecov
  - `pytest --cov=ggblab` with full coverage metrics

- ✅ **Error Handling Refactor**:
  - Syntax validation (tokenization-based) for pre-execution checking
  - Semantic validation (object existence) with cache integration
  - Custom exceptions: `GeoGebraSyntaxError`, `GeoGebraSemanticsError`
  - Timeout handling (3-second default) with exception context
  - Event queue routing (client_handle distinguishes responses vs. events)

- ✅ **Parser Coverage Expansion**:
  - New test classes: BinaryTree, Nary, LargeConstruction, Diamond, Reachability, CyclicDetection
  - Edge case coverage: empty construction, single objects, N-ary dependencies
  - Performance tests: 30+ objects, linear chains, large graphs
  - All tests follow `ggb_parser(cache_enabled=False)` for isolation

### ✅ Documentation Updates

- ✅ **README.md**: 
  - Added CI/CD badge
  - Updated testing section with GitHub Actions reference
  - Marked as ✅ completed: Unit tests, CI/CD pipeline
  - Linked [.github/workflows/tests.yml](.github/workflows/tests.yml)

- ✅ **docs/architecture.md**:
  - Command Validation section (syntax/semantic checks)
  - Error Handling strategy (3-layer approach)
  - Event routing refactor documentation
  - Parser performance analysis and future improvements

- ✅ **Created supporting docs**:
  - TEST_FIX_SUMMARY.md - Parser test fixture restructuring
  - FIX_COMPLETION_REPORT.md - Complete test API alignment
  - COMPLETION_CHECKLIST.md - Verification of all fixes
  - AGENTS.md - Extension development standards (maintained)

---

## Next-Step Priorities (v0.8 – v1.0)

### 1. Scene Timeline & Launch Strategy (v0.8 – v1.0)

**Refs**: [docs/philosophy.md § Tier 2](docs/philosophy.md), [docs/architecture.md § Widget Launch Strategy](docs/architecture.md)

**Actions**:
- [ ] v0.8: Implement `SceneTimeline` class (snapshot capture, store metadata)
- [ ] v0.9: Add timeline navigation and playback in Jupyter
- [ ] v0.8: Programmatic launch via ipylab `GeoGebra().init()` passing Comm target + socket settings
- [ ] v0.8: Document Launcher/Command Palette fixed-args limitation; steer users to programmatic launch

---

### 2. Numerical Integration & Wrappers (v0.9 – v1.0)

**Refs**: [docs/philosophy.md § Tier 3](docs/philosophy.md), [docs/scoping.md § Parameter Sweeps](docs/scoping.md)

**Actions**:
- [ ] v0.9: Python wrappers for scipy ODEs → GeoGebra point lists
- [ ] v0.9: Numpy ↔ GeoGebra conversions (point lists, curves)
- [ ] v1.0: Parameter sweep utilities; record to `SceneTimeline`
- [ ] v1.0: Tutorial notebooks (projectile motion, damped pendulum)

---

### 3. SymPy Geometry Bridge (v1.1 – v1.2)

**Refs**: [docs/sympy_integration.md](docs/sympy_integration.md)

**Actions**:
- [ ] v1.1: Conversion layer `geogrebra_to_sympy()` and `sympy_to_geogrebra()`
- [ ] v1.1: Verification APIs (`verify_collinearity`, `verify_concyclicity`, `verify_perpendicular`, `verify_property`)
- [ ] v1.2: Code generation (`to_python_code`, `to_construction_string`)
- [ ] v1.2: Export symbolic results → GeoGebra visualization (numeric approximation pipeline)

---

### 4. Manim Export (v1.0 – v1.5)

**Refs**: [docs/philosophy.md § Tier 2.5](docs/philosophy.md)

**Actions**:
- [ ] v1.0: `SceneTimeline.to_manim_script()` generates Scene class
- [ ] v1.0: Geometry extraction from snapshots → manim primitives
- [ ] v1.5: `SceneTimeline.render_video()` orchestrates `manim render` (MP4/GIF)
- [ ] v1.5: Example notebooks; educator feedback loop

---

### 5. Parser: Sunset & Replacement (v1.0 – v1.1)

**Refs**: [docs/architecture.md § Dependency Parser Architecture](docs/architecture.md#dependency-parser-architecture), [docs/philosophy.md § Parser: Rationale & Sunset](docs/philosophy.md)

**Actions**:
- [ ] v1.0: Replace `parse_subgraph()` with topological pruning approach (O(n(n+m)))
- [ ] v1.0: Unit tests: chains, diamonds, N-ary, large graphs (50+ nodes)
- [ ] v1.1: Deprecate/remove `parse_subgraph()` unless strong use case emerges

---

### 6. Error Handling & User Feedback (v0.8.x – v0.9)

**Refs**: [docs/architecture.md § Future Error Handling Improvements](docs/architecture.md)

**Completed (v0.7.3)**:
- ✅ Convert timeout to Python exception with context (command, timestamp)
- ✅ Support custom timeout via `GeoGebra(timeout=5.0)` and per-call overrides
- ✅ Hook GeoGebra dialog events; forward structured error via Comm
- ✅ Basic retry logic (1 retry, 100ms backoff) for transient socket failures

**Remaining (v0.8+)**:
- [ ] v0.8: Enhanced error recovery strategies
- [ ] v0.9: User-facing error dialogs in widget (not console-only)

---

### 7. API Validation & Type Safety (v0.8.x – v1.0)

**Files**: [src/widget.tsx](src/widget.tsx), [src/index.ts](src/index.ts), [ggblab/ggbapplet.py](ggblab/ggbapplet.py)
**Refs**: [AGENTS.md § Type Safety](AGENTS.md)

**Actions**:
- [ ] v0.8: Enable TypeScript strict mode; remove `any`
- [ ] v0.8: Lightweight arg validation in `GeoGebra.command()` and `GeoGebra.function()`
- [ ] v0.8: JSDoc/docstrings for all public TS/Python APIs
- [ ] v1.0: Full type safety audit; public interfaces documented

---

### 8. CI/CD & Testing (v0.8.x – v1.0)

**Refs**: [docs/architecture.md § Testing Strategies](docs/architecture.md)

**Actions**:
- [ ] v0.8: Add GitHub Actions `.github/workflows/ci.yml` (lint, unit, integration)
- [ ] v0.8: Backend tests (`tests/test_comm.py`, parser tests incl. performance)
- [ ] v0.8: Frontend unit tests; optional Playwright/Galata integration
- [ ] v1.0: Coverage targets: backend >80%, frontend >60%
- [ ] v1.0: Update [RELEASE.md](RELEASE.md) for automated release checklist

---

### 9. Configuration & Settings (v0.8 – v0.9)

**Files**: [src/widget.tsx](src/widget.tsx), [ggblab/ggbapplet.py](ggblab/ggbapplet.py), [schema/plugin.json](schema/plugin.json)

**Actions**:
- [ ] v0.8: Constructor options `GeoGebra(comm_target='custom', timeout=5.0)`
- [ ] v0.8: Populate [schema/plugin.json](schema/plugin.json) with user-configurable options
- [ ] v0.9: JupyterLab settings UI (Comm target, socket timeout)

---

### 10. Monitoring & Observability (v1.0+)

**Files**: [ggblab/ggbapplet.py](ggblab/ggbapplet.py), [src/widget.tsx](src/widget.tsx)

**Actions**:
- [ ] v1.0: Structured logging (JSON) for major operations
- [ ] v1.0: Latency metrics (command/func exec time, socket round-trip)
- [ ] v1.0: Optional telemetry endpoint (privacy-respecting)

---

## Checklist Summary

- [ ] Timeline: capture, navigate, playback; ipylab launch wired
- [ ] Numerical: scipy wrappers, conversions, sweeps, notebooks
- [ ] SymPy: conversion, verification APIs, codegen, visualization
- [ ] Manim: script generation, render orchestration, examples
- [ ] Parser: replace subgraph algo; tests; deprecate legacy
- [ ] Error UX: exceptions with context, custom timeout, dialogs, retry
- [ ] Type safety: TS strict, validation, JSDoc/docstrings, audit
- [ ] CI: GitHub Actions, unit/integration, coverage targets, release
- [ ] Config: constructor options, settings schema, settings UI
- [ ] Monitor: logging, metrics, optional telemetry

---

## Known Blocking Issues

1. **Launcher fixed arguments**: Cannot inject per-session comm settings. **Action**: Use programmatic launch via ipylab (see [docs/architecture.md](docs/architecture.md)).
2. **Parser combinatorial explosion**: `parse_subgraph()` is intractable on large graphs. **Action**: Replace with topological pruning; deprecate legacy.
3. **No CI**: Risk of regressions without automated checks. **Action**: Add GitHub Actions and tests.
4. **TypeScript not strict**: Type safety gaps. **Action**: Enable strict mode and fix failures.
