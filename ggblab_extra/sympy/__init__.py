"""SymPy helpers subpackage for ggblab_extra.

This subpackage groups the optional SymPy-based helper modules so callers
can import them as `from ggblab_extra import sympy` or
`from ggblab_extra.sympy import point_from_value` without pulling heavy deps
at the top-level package import.
"""

# Lightweight, lazy-loading API surface for optional SymPy helpers.
#
# Importing SymPy is expensive and may not be available at package import
# time. Provide `set_applet_3d` / `get_applet_3d` immediately while lazily
# importing other helpers on demand via `__getattr__` (PEP 562).
from importlib import import_module
from typing import Any

from .utils import get_applet_3d, set_applet_3d

# Build `__all__` dynamically so the module can expose names without
# importing heavy SymPy-dependent modules at import time. Static analyzers
# may not be able to prove the lazy imports; silence that specific check
# for this expression. The assignment is placed after `_LAZY_MAP` below.

# Map attribute names to (module_path, attribute_name) for lazy import.
_LAZY_MAP = {
    # point
    "point_from_value": (".point", "point_from_value"),
    # utils
    "expr_from_value": (".utils", "expr_from_value"),
    # line
    "line_from_value": (".line", "line_from_value"),
    "segment_from_command": (".line", "segment_from_command"),
    "ray_from_command": (".line", "ray_from_command"),
    # circle
    "circle_from_value": (".circle", "circle_from_value"),
    "surface_from_value": (".surface", "surface_from_value"),
    "ParametricSurface": (".surface", "ParametricSurface"),
    "curve_from_value": (".curve", "curve_from_value"),
    "Circle3D": (".circle", "Circle3D"),
    # plane
    "plane_from_value": (".plane", "plane_from_value"),
    "enumerate_plane_members": (".plane", "enumerate_plane_members"),
    "point_on_plane": (".plane", "point_on_plane"),
    "segment_on_plane": (".plane", "segment_on_plane"),
    "line_on_plane": (".plane", "line_on_plane"),
    "circle_on_plane": (".plane", "circle_on_plane"),
    "valueobject_on_plane": (".plane", "valueobject_on_plane"),
    # 3D/2D helpers
    "Object3D": (".object3d", "Object3D"),
    "Segment3D": (".object3d", "Segment"),
    "to_sympy_line": (".object3d", "to_sympy_line"),
    "SimpleLine3D": (".object3d", "SimpleLine3D"),
    "Object2D": (".object2d", "Object2D"),
    "attach_object2d": (".object2d", "attach_object2d"),
    "attach_object3d": (".object3d", "attach_object3d"),
}


def __getattr__(name: str) -> Any:
    """Lazily import attributes when first accessed.

    Allows `from ggblab_extra import sympy` and calling `set_applet_3d()`
    without requiring SymPy to be installed. Other helpers import SymPy
    on demand when used.
    """
    if name in _LAZY_MAP:
        mod_path, attr = _LAZY_MAP[name]
        mod = import_module(__name__ + mod_path)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY_MAP.keys()))


# Build `__all__` dynamically so the module can expose names without
# importing heavy SymPy-dependent modules at import time. Static analyzers
# may not be able to prove the lazy imports; silence that specific check
# for this expression.
__all__ = ["set_applet_3d", "get_applet_3d"] + list(
    _LAZY_MAP.keys()
)  # pylint: disable=undefined-all-variable
