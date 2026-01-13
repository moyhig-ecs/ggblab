# ggblab Development TODO

## Next-Step Priorities (v0.8 - v1.0)

### 1. Parser Correctness & Performance (v0.7.3 - v1.0)

**File**: [ggblab/parser.py](ggblab/parser.py) — `parse_subgraph()` method

**Issues**:
- Exponential time complexity O(2^n) — intractable for 20+ root objects
- Infinite loop risk under certain topologies
- Limited to 1-2 parent dependencies (ignores 3+)
- Debug print statements in production code
- Redundant neighbor computation in loops

**Actions**:
- [ ] v0.7.3: Remove debug `print()` statements; add optional `logging` module with debug flag
- [ ] v0.7.3: Add early termination check (max 100 iterations) to detect infinite loops
- [ ] v0.7.3: Cache neighbor computation to avoid O(n) redundant work per iteration
- [ ] v0.7.3: Extend match statement to handle 3+ parent dependencies (not just 1-2)
- [ ] v1.0: Replace entire algorithm with topological sort + reachability pruning (O(n(n+m)))
- [ ] v1.0: Add comprehensive unit tests: simple chains, diamonds, N-ary deps, large graphs (50+ nodes)

**Reference**: [ARCHITECTURE.md § Dependency Parser Architecture](ARCHITECTURE.md#dependency-parser-architecture)

---

### 2. API Validation & Type Safety (v0.8.x - v1.0)

**Files**: [src/widget.tsx](src/widget.tsx), [src/index.ts](src/index.ts), [ggblab/ggbapplet.py](ggblab/ggbapplet.py)

**Issues**:
- TypeScript strict mode disabled; uses `any` type in places
- No input validation on commands/functions before sending to GeoGebra
- Widget props lack full interface documentation

**Actions**:
- [ ] v0.8: Enable TypeScript strict mode; eliminate `any` casts in widget
- [ ] v0.8: Add lightweight argument validation in `GeoGebra.command()` and `GeoGebra.function()` 
- [ ] v0.8: Add JSDoc for all public TypeScript/Python APIs
- [ ] v1.0: Full type safety audit; 100% of public interfaces documented

---

### 3. Error Handling & User Feedback (v0.8.x)

**Files**: [src/widget.tsx](src/widget.tsx), [ggblab/comm.py](ggblab/comm.py)

**Issues**:
- Communication errors logged to console but not shown to users
- 3-second timeout on out-of-band socket gives no context
- No retry/backoff logic for transient failures
- Dialog-based errors from GeoGebra not reliably surfaced

**Actions**:
- [ ] v0.8: Add user-facing toast/notification for Comm/WebSocket failures in widget
- [ ] v0.8: Wrap out-of-band timeout in Python exception with context (command, timestamp, 3-sec limit)
- [ ] v0.8: Support custom timeout via `GeoGebra(timeout=5.0)` constructor parameter
- [ ] v0.8: Hook GeoGebra dialog events and extract error messages; forward via Comm
- [ ] v0.8: Add basic retry logic (1 retry, 100ms backoff) for transient socket failures

---

### 4. CI/CD & Testing (v0.8.x - v1.0)

**Files**: 
- New: `.github/workflows/ci.yml` (GitHub Actions)
- New: `tests/test_parser.py`, `tests/test_parser_large.py` (unit/perf tests)
- New: `tests/test_comm.py` (mock Comm tests)
- Update: `ui-tests/` (Playwright integration tests)

**Issues**:
- No automated tests on PR/release
- Unit test coverage <10% (parser, comm untested)
- No linting on commit
- Manual release process

**Actions**:
- [ ] v0.8: Create `.github/workflows/ci.yml` to run:
  - `jlpm lint` (frontend TypeScript/CSS)
  - `jlpm test` (frontend unit tests)
  - `python -m pytest tests/` (backend unit tests)
  - Playwright tests (optional, slow)
- [ ] v0.8: Create `tests/test_parser.py`:
  - Simple dependency chain (A → B → C)
  - Diamond deps (A,B → C → D)
  - Binary tree of deps
  - 3+ parent dependencies (N-ary)
  - Large graph performance (50+ nodes, <5sec)
- [ ] v0.8: Create `tests/test_comm.py`:
  - Mock IPython Comm
  - Test message ID correlation
  - Test timeout handling
- [ ] v1.0: Achieve >80% test coverage for backend, >60% for frontend
- [ ] v1.0: Update [RELEASE.md](RELEASE.md) with automated release checklist

---

### 5. Developer Documentation (v0.8.x)

**Files**: [ARCHITECTURE.md](ARCHITECTURE.md) or new [CONTRIBUTING.md](CONTRIBUTING.md)

**Issues**:
- No step-by-step guide for first-time contributors
- Build/test/release process not fully documented
- Coding standards scattered across [AGENTS.md](AGENTS.md)

**Actions**:
- [ ] v0.8: Create or expand [CONTRIBUTING.md](CONTRIBUTING.md) with:
  - Prerequisites (Node.js, Python 3.10+, jlpm)
  - Clone → activate env → install deps workflow
  - Local build & test commands (`jlpm build`, `jupyter lab`)
  - Running tests and CI checks locally
  - Code style (2-space indent, TypeScript strict, docstrings)
  - Pull request process
- [ ] v0.8: Add "Architecture for Contributors" section to [ARCHITECTURE.md](ARCHITECTURE.md):
  - Dual-channel communication overview (1-2 pages)
  - Component responsibilities
  - Message flow diagrams
- [ ] v0.8: Document hardcoded constants (Comm target `'test3'`, socket timeout 3s) and why they exist

---

### 6. Configuration & Customization (v0.8.x)

**Files**: [src/widget.tsx](src/widget.tsx), [ggblab/ggbapplet.py](ggblab/ggbapplet.py), [schema/plugin.json](schema/plugin.json)

**Issues**:
- Comm target hardcoded as `'test3'` — no customization
- Socket timeout hardcoded to 3 seconds
- No settings UI in JupyterLab

**Actions**:
- [ ] v0.8: Allow `GeoGebra(comm_target='custom', timeout=5.0)` via constructor
- [ ] v0.8: Populate [schema/plugin.json](schema/plugin.json) with user-configurable options
- [ ] v0.9: Add JupyterLab settings UI for Comm target and socket timeout

---

### 7. Monitoring & Observability (v1.0+)

**Files**: [ggblab/ggbapplet.py](ggblab/ggbapplet.py), [src/widget.tsx](src/widget.tsx)

**Issues**:
- No logging of operation latency
- No metrics on Comm/socket success rates
- No way to diagnose user-reported issues

**Actions**:
- [ ] v1.0: Add structured logging (JSON format) for all major operations
- [ ] v1.0: Emit latency metrics (command exec time, function call time, socket round-trip)
- [ ] v1.0: Add configurable telemetry endpoint (optional, privacy-respecting)

---

## Checklist Summary

- [ ] Parser: v0.7.3 quick fixes (logging, loop guard, caching, N-ary)
- [ ] Parser: v1.0 algorithm replacement + tests
- [ ] Type safety: strict mode, JSDoc, validation
- [ ] Error UX: notifications, timeout context, retry logic
- [ ] CI: GitHub Actions workflow, unit tests, coverage >80%
- [ ] Docs: CONTRIBUTING.md, architecture overview for developers
- [ ] Config: allow customization of Comm target and timeout
- [ ] Monitor: logging, metrics, optional telemetry

---

## Known Blocking Issues

1. **Parser `parse_subgraph()` on large graphs**: Can hang or timeout. Blocks analytical workflows on complex constructions. **Workaround**: Use graphs with <15 independent roots.
2. **No CI**: Cannot merge PRs with confidence. Risk of regressions. **Action**: Set up GitHub Actions immediately.
3. **TypeScript not strict**: Type safety gaps. **Action**: Enable strict mode and fix failures.
4. **Hardcoded Comm target**: Users cannot override. **Action**: Make configurable in v0.8.
