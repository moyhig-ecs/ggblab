"""Pytest configuration and shared fixtures.

This file is automatically loaded by pytest and provides:
- Shared fixtures across all test files
- Pytest configuration
- Test utilities
"""

import pytest
import sys
from pathlib import Path

# Add project root to sys.path to enable importing ggblab
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# Shared fixtures can be added here
# Example:
# @pytest.fixture(scope="session")
# def sample_data():
#     return {"key": "value"}
