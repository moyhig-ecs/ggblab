"""Pytest configuration for ggblab-extra tests.

Ensures ggblab_extra package is importable without installation by
adding the repository root to sys.path.
"""

import sys
from pathlib import Path

# Add repository root so `ggblab_extra` can be imported in dev mode
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
