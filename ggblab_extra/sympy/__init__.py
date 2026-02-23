"""SymPy helpers subpackage for ggblab_extra.

This subpackage groups the optional SymPy-based helper modules so callers
can import them as `from ggblab_extra import sympy` or
`from ggblab_extra.sympy import point_from_value` without pulling heavy deps
at the top-level package import.
"""

# Import the focused helper functions from the sibling modules so users can
# access a compact, well-scoped API via `ggblab_extra.sympy`.
from .point import (
    point_from_value,
)
from .utils import set_applet_3d, get_applet_3d
from .line import line_from_value, segment_from_command, ray_from_command
from .circle import circle_from_value, Circle3D
from .plane import (
    plane_from_value,
    enumerate_plane_members,
    point_on_plane,
    segment_on_plane,
    line_on_plane,
    circle_on_plane,
    valueobject_on_plane,
)
from .object3d import Object3D, Segment as Segment3D, to_sympy_line, SimpleLine3D, attach_object3d
from .object2d import Object2D, attach_object2d

__all__ = [
    "point_from_value",
    "set_applet_3d",
    "get_applet_3d",
    "line_from_value",
    "segment_from_command",
    "ray_from_command",
    "circle_from_value",
    "Circle3D",
    "plane_from_value",
    "enumerate_plane_members",
    "point_on_plane",
    "segment_on_plane",
    "line_on_plane",
    "circle_on_plane",
    "valueobject_on_plane",
    "Object3D",
    "Segment3D",
    "to_sympy_line",
    "SimpleLine3D",
    "Object2D",
    "attach_object2d",
    "attach_object3d",
]
