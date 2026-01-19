"""ggblab-extra: Extended functionality for ggblab.

This package provides advanced analysis and educational tools for GeoGebra
constructions:

- Construction Parser: Dependency graph analysis using NetworkX
- Scene Verification: Automated testing infrastructure
- Educational Tools: Layer-based playback and verification

Main Components:
    - ggb_parser: Dependency graph parser for GeoGebra constructions
    - SceneVerifier: Automated verification for geometric constructions
    - ScenePlayback: Layer-by-layer construction playback

Example:
    >>> from ggblab import ggb_construction
    >>> from ggblab_extra import ggb_parser
    >>> construction = ggb_construction()
    >>> construction.load('myfile.ggb')
    >>> parser = ggb_parser()
    >>> parser.parse()
"""

__version__ = "0.1.0"

from .parser import ggb_parser
from .scene_verification import (
    SceneVerifier,
    ScenePlayback,
    ObjectType,
    VerificationResult,
)
from .persistent_counter import PersistentCounter

__all__ = [
    "ggb_parser",
    "SceneVerifier",
    "ScenePlayback",
    "ObjectType",
    "VerificationResult",
    "PersistentCounter",
]
