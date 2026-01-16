#!/usr/bin/env python3
"""Quick test runner to verify test_parser.py changes."""
import subprocess
import sys

# Run parser tests
result = subprocess.run(
    ["python", "-m", "pytest", "tests/test_parser.py", "-v", "--tb=short"],
    cwd="/Users/manabu/work/wasm/ggblab"
)

sys.exit(result.returncode)
