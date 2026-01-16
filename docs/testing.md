# Testing Guide for ggblab

This document describes the structure of ggblab's unit and integration tests, how to run them locally and on CI, coverage goals, and how to extend them.

## Test Structure

- Directory structure (excerpt)
  - `tests/` (unit tests)
    - `test_construction.py`: Loading/saving by format (.ggb Base64, ZIP, JSON, XML), round-trip, edge cases
    - `test_parser.py`: Dependency graph construction, root/leaf identification, topological sort, generation analysis
    - `__init__.py`, `conftest.py`: Pytest configuration and shared fixtures
  - Root
    - `pytest.ini`: Coverage/marker/output configuration
    - `.github/workflows/tests.yml`: Automated testing on GitHub Actions

## Local Execution

Prerequisite: Activate virtual environment (Conda/venv)

```bash
pip install -e ".[dev]"
pip install pytest pytest-cov

# Run all tests
pytest

# Verbose output + coverage
pytest -v --cov=ggblab --cov-report=term-missing

# Specific file only
pytest tests/test_construction.py -v
pytest tests/test_parser.py -v

# Re-run failed tests only
pytest --lf
```

Generated artifacts:
- `htmlcov/` (HTML coverage report)
- `coverage.xml` (coverage report for CI)

## CI (GitHub Actions)

- Workflow: `.github/workflows/tests.yml`
- Targets: `ubuntu-latest`, `macos-latest`, `windows-latest` / Python `3.10`–`3.12`
- Execution steps:
  - Install dependencies (`pip install -e ".[dev]"`)
  - Run tests with pytest + generate coverage
  - Upload to Codecov (optional)

## Coverage Goals

- v0.8.0: ≥50% (achieved primarily through `construction`, `parser`)
- v0.9.0: ≥70% (add tests for `comm`, `ggbapplet`)
- v1.0.0: ≥80% (integration tests/remaining edge cases)

## Test Writing Guidelines

- Single responsibility per test function (one test = one behavior)
- Use fixtures (`conftest.py`) for test data generation and reuse
- Prioritize edge cases (empty files, corrupted data, non-existent paths)
- Provide meaningful error messages on failure (exception type/message)
- Use round-trip testing when possible (load→save→load) for consistency validation

## Representative Test Content (Overview)

- `test_construction.py`
  - Loading Base64 .ggb / ZIP .ggb / JSON / XML
  - XML stripping to `<construction>` and normalization of scientific notation (`e-1 → E-1`)
  - Save behavior with/without Base64 (ZIP/plain XML)
  - Automatic filename generation (`name_1.ggb`, `name_2.ggb`)
  - Round-trip consistency validation
- `test_parser.py`
  - Node/edge generation (dependencies)
  - Root/leaf identification
  - Topological sort/generation analysis (scope levels)
  - Transitive dependencies (A→AB→L→C→triangle, etc.)

## Extension Plan (Proposed)

- `tests/test_comm.py`: Mock tests for communication layer (IPython Comm + OOB socket)
- `tests/test_ggbapplet.py`: Integration tests for `GeoGebra` API (init→function calls)
- Playwright/Galata UI tests (separate repo/directory)

## Troubleshooting

- `ImportError: ggblab.* not found`
  - Verify that `conftest.py` adds project root to `sys.path`
  - Run `pip install -e ".[dev]"`
- ZIP file-related failures on Windows
  - Be aware of path/line ending differences, pre-check with `zipfile.is_zipfile()`
- Low coverage
  - Add more edge cases, write tests that exercise all branches

## References

- `pytest.ini`: Coverage and marker configuration
- `.github/workflows/tests.yml`: CI execution conditions/environment
- `docs/ai_assessment.md`: Technical assessment and test prioritization background
