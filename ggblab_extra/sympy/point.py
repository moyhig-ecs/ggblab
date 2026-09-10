"""Point helpers: factory and wrapper for SymPy Point2D/Point3D.

This module centralizes the logic for constructing SymPy points and
provides a `Point` wrapper exposing a uniform API across 2D/3D points.
"""

import re
from dataclasses import dataclass
from typing import Any, Generic, Optional, Protocol, TypeVar

_HAS_SYMPY = True
try:
    from sympy import cos, sin, symbols
    from sympy.geometry import Point as SympyPoint
    from sympy.geometry import Point2D as SympyPoint2D
    from sympy.geometry import Point3D as SympyPoint3D
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application, parse_expr,
        standard_transformations)
except Exception:
    SympyPoint = SympyPoint3D = SympyPoint2D = None
    implicit_multiplication_application = None
    parse_expr = None
    standard_transformations = ()
    sin = None
    cos = None
    symbols = None
    _HAS_SYMPY = False

# Parser transformations and time symbol for parametric expressions
_t = symbols("t") if _HAS_SYMPY and symbols is not None else None
_transformations = (
    standard_transformations + (implicit_multiplication_application,)
    if _HAS_SYMPY and implicit_multiplication_application is not None
    else ()
)


class PointLike(Protocol):
    x: Any
    y: Any

    """Protocol representing a point-like object (has `x`, `y`)."""

    def distance(self, other: Any) -> Any:  # pragma: no cover - typing helper
        """Return distance to another point-like object."""
        ...


AnyPoint = TypeVar("AnyPoint", bound=PointLike)


def sympy_point_from_coords(*coords, is_3d: Optional[bool] = None):
    """Construct a SymPy Point from numeric/expression coordinates.

    The `is_3d` hint forces 2D/3D construction when provided.
    """
    if not _HAS_SYMPY:
        raise ImportError("SymPy is required for constructing sympy points")

    if is_3d is True:
        if len(coords) == 2:
            return SympyPoint3D(coords[0], coords[1], 0)
        return SympyPoint3D(*coords)

    if is_3d is False:
        if len(coords) >= 2:
            return SympyPoint2D(coords[0], coords[1])
        return SympyPoint2D(*coords)

    if len(coords) >= 3:
        return SympyPoint3D(*coords[:3])
    if len(coords) == 2:
        return SympyPoint2D(coords[0], coords[1])
    return SympyPoint(*coords)


@dataclass
class Point(Generic[AnyPoint]):
    """Wrapper around a SymPy `Point` exposing uniform `x`,`y`,`z` access."""

    obj: AnyPoint

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"Point({self.obj!r})"

    @property
    def x(self):
        return getattr(self.obj, "x")

    @property
    def y(self):
        return getattr(self.obj, "y")

    @property
    def z(self):
        return getattr(self.obj, "z", 0)

    def is_3d(self) -> bool:
        return hasattr(self.obj, "z")

    @property
    def is_zero(self) -> bool:
        v = getattr(self.obj, "is_zero", None)
        if isinstance(v, bool):
            return v
        try:
            zx = float(self.x.evalf()) if hasattr(self.x, "evalf") else float(self.x)
            zy = float(self.y.evalf()) if hasattr(self.y, "evalf") else float(self.y)
            zz = (
                float(getattr(self.obj, "z", 0))
                if getattr(self.obj, "z", None) is not None
                else 0.0
            )
            return zx == 0.0 and zy == 0.0 and zz == 0.0
        except (TypeError, ValueError, AttributeError):
            return False

    def __getattr__(self, name: str):
        return getattr(self.obj, name)


# Applet dimensionality flag moved to `ggblab_extra.sympy.utils`.


def point_from_value(value_str: str) -> "Point":
    """Parse a GeoGebra-style `Value` string into a `Point` wrapper.

    Accepts forms like "A = (1,2)" or "(x,y)". Raises `ValueError` if
    parsing fails.
    """
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    m = re.search(r"=\s*\(([^,]+),([^,]+),([^\)]+)\)", s)
    if not m:
        m2 = re.search(r"\(([^,]+),([^,]+)\)", s)
        if not m2:
            m3 = re.search(r"\(([^,]+),([^,]+),([^\)]+)\)", s)
            if not m3:
                raise ValueError(f"not a point value: {value_str!r}")
            m = m3
        else:
            a = m2.group(1).strip()
            b = m2.group(2).strip()
            m = (a, b, "0")
    if isinstance(m, tuple):
        comps = [m[0].strip(), m[1].strip(), m[2].strip()]
    else:
        comps = [c.strip() for c in m.groups()]
    # GeoGebra represents NaN values as '?'. If any component is '?',
    # stop processing here to avoid passing invalid code to sympy's parser.
    if any((c == "?" or (isinstance(c, str) and "?" in c)) for c in comps):
        raise ValueError(f"point value contains NaN placeholder '?': {value_str!r}")
    # Use centralized parser to keep GeoGebra-specific handling consistent
    # (handles placeholders like '?', brace-lists, assignments, equations, etc.)
    try:
        from .utils import expr_from_value

        exprs = [
            expr_from_value(
                c,
                transformations=_transformations,
                local_dict={"sin": sin, "cos": cos, "t": _t},
            )
            for c in comps
        ]
    except Exception:
        # Fallback to local parse_expr if utils is unavailable
        exprs = [
            parse_expr(
                c,
                transformations=_transformations,
                local_dict={"sin": sin, "cos": cos, "t": _t},
            )
            for c in comps
        ]
    try:
        from .utils import get_applet_3d

        is3d = get_applet_3d()
    except (ImportError, AttributeError):
        is3d = None
    if is3d:
        p = sympy_point_from_coords(*exprs, is_3d=True)
    else:
        try:
            p = SympyPoint2D(exprs[0], exprs[1])
        except (TypeError, ValueError, AttributeError):
            p = sympy_point_from_coords(*exprs)
    return Point(p)


__all__ = ["point_from_value"]
