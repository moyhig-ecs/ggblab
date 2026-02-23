"""Line helpers (moved into sympy subpackage).
"""
from dataclasses import dataclass
from typing import Protocol, Any, TypeVar, Generic, Union, Optional
import re

_HAS_SYMPY = True
try:
    from sympy import Matrix
    from sympy import symbols
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
except Exception:
    Matrix = None
    symbols = None
    implicit_multiplication_application = None
    parse_expr = None
    standard_transformations = ()
    _HAS_SYMPY = False

from .utils import is_pointlike, resolve_label_to_point

try:
    from sympy.geometry.line3d import Line3D as SympyLine3D
except ImportError:
    try:
        from sympy.geometry import Line3D as SympyLine3D
    except ImportError:
        SympyLine3D = None

try:
    from sympy.geometry.line import Line as SympyLine2D
except ImportError:
    try:
        from sympy.geometry import Line as SympyLine2D
    except ImportError:
        SympyLine2D = None

try:
    from sympy.geometry.point import Point2D as SympyPoint2D
except ImportError:
    try:
        from sympy.geometry import Point2D as SympyPoint2D
    except ImportError:
        SympyPoint2D = None


class LineLike(Protocol):
    point: Any
    direction: Any
    p1: Any
    p2: Any

    """Protocol describing a line-like object with point/direction or p1/p2."""


AnyLine = TypeVar("AnyLine", bound=LineLike)


@dataclass
class Line(Generic[AnyLine]):
    obj: AnyLine

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"Line({self.obj!r})"

    """Lightweight wrapper for line-like objects exposing `.obj`."""

    def __getattr__(self, name: str):
        return getattr(self.obj, name)


@dataclass
class SimpleLine3D:
    """Simple container for a 3D line with `point` and `direction` attrs."""
    pass


def to_sympy_line(simple) -> object:
    if SympyLine3D is None:
        return simple
    try:
        # Extract point and direction from tuple/list or attributes
        if isinstance(simple, (tuple, list)):
            p, d = simple[0], simple[1]
        else:
            p = getattr(simple, "point")
            d = getattr(simple, "direction")

        # Helper to get coordinate from a point-like object
        def _coord(pt, i):
            try:
                return pt[i]
            except (IndexError, TypeError):
                try:
                    return getattr(pt, ("x", "y", "z")[i])
                except (AttributeError, TypeError):
                    return None

        # Helper to get direction component
        def _dcomp(vec, i):
            try:
                return vec[i]
            except (IndexError, TypeError):
                try:
                    # Matrix or sympy Matrix
                    return vec[i]
                except (IndexError, TypeError, AttributeError):
                    return None

        coords_p = [_coord(p, i) for i in range(3)]
        comps_d = [_dcomp(d, i) for i in range(3)]

        # If any coordinate missing, fall back to simple behavior
        if any(c is None for c in coords_p) or any(di is None for di in comps_d):
            return simple

        # Build new point p2 = p + d
        p2_coords = [coords_p[i] + comps_d[i] for i in range(3)]

        # Construct Sympy Point3D if available, else try using type(p)
        try:
            from sympy.geometry.point import Point3D as SympyPoint3D
        except ImportError:
            try:
                from sympy.geometry import Point3D as SympyPoint3D
            except ImportError:
                SympyPoint3D = None

        if SympyPoint3D is not None:
            P = SympyPoint3D(*coords_p)
            P2 = SympyPoint3D(*p2_coords)
            return SympyLine3D(P, P2)

        try:
            p2 = type(p)(*(p2_coords[i] for i in range(3)))
            return SympyLine3D(p, p2)
        except (TypeError, AttributeError, ValueError):
            return simple
    except (AttributeError, TypeError, IndexError):
        return simple

        
from .point import sympy_point_from_coords

try:
    from sympy.geometry.segment import Segment as SympySegment
except ImportError:
    try:
        from sympy.geometry import Segment as SympySegment
    except ImportError:
        SympySegment = None

try:
    from sympy.geometry.ray import Ray as SympyRay
except ImportError:
    try:
        from sympy.geometry import Ray as SympyRay
    except ImportError:
        SympyRay = None

_t = symbols("t") if _HAS_SYMPY and symbols is not None else None
_transformations = (
    standard_transformations + (implicit_multiplication_application,)
    if _HAS_SYMPY and implicit_multiplication_application is not None
    else ()
)


def _try_parse_line_equation(s: str):
    """Try to parse an implicit cartesian plane equation into a Line.

    Returns a `Line(...)` or `None` on failure.
    """
    try:
        if "=" not in s:
            return None
        x, y, z = symbols("x y z")
        lhs_str, rhs_str = s.split("=", 1)
        # Sanitize common notation issues from GeoGebra/LaTeX-like strings
        def _sanitize(sym_str: str) -> str:
            # remove LaTeX-style braces which confuse the parser: v_{1} -> v_1
            t = sym_str.replace("{", "").replace("}", "")
            # normalize subscript forms like _('1') or _ ( 1 ) -> _1
            t = re.sub(r"_\s*\((\d+)\)", r"_\1", t)
            # collapse repeated whitespace
            t = re.sub(r"\s+", " ", t)
            return t
        lhs_str = _sanitize(lhs_str)
        rhs_str = _sanitize(rhs_str)
        lhs = parse_expr(
            lhs_str.strip(),
            transformations=_transformations,
            local_dict={"x": x, "y": y, "z": z},
        )
        rhs = parse_expr(
            rhs_str.strip(),
            transformations=_transformations,
            local_dict={"x": x, "y": y, "z": z},
        )
        if isinstance(lhs, tuple) or getattr(lhs, "is_Tuple", False):
            return None
        expr = lhs - rhs
        a = expr.coeff(x, 1)
        b = expr.coeff(y, 1)
        c = expr.coeff(z, 1)
        const = expr.subs({x: 0, y: 0, z: 0})
        d = -const
        if c == 0 and (a != 0 or b != 0):
            if b != 0:
                px = 0
                py = d / b
            else:
                px = d / a
                py = 0
            dx, dy = -b, a
            if SympyLine2D is not None and SympyPoint2D is not None:
                P2d = SympyPoint2D(px, py)
                P2d2 = SympyPoint2D(px + dx, py + dy)
                return Line(SympyLine2D(P2d, P2d2))
            P = sympy_point_from_coords(px, py, 0)
            D = Matrix([dx, dy, 0])
            if SympyLine3D is None:
                return Line((P, D))
            try:
                p2 = sympy_point_from_coords(*(P[i] + D[i] for i in range(3)))
            except (TypeError, AttributeError):
                p2 = sympy_point_from_coords(P.x + D[0], P.y + D[1], P.z + D[2])
            return Line(SympyLine3D(P, p2))
    except (AttributeError, TypeError, ValueError, ImportError):
        return None
    return None


def line_from_value(value_str: str) -> object:
    # Normalize input and try a couple of parsing strategies.
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()

    # First, try the parametric form: (c) + λ (d)
    m = re.search(r"=\s*\(([^)]+)\)\s*\+\s*(?:λ\s*)?\(([^)]+)\)", s)
    if m:
        c_str = m.group(1)
        d_str = m.group(2)
        c_parts = [p.strip() for p in c_str.split(",")]
        d_parts = [p.strip() for p in d_str.split(",")]
        if len(c_parts) != 3 or len(d_parts) != 3:
            raise ValueError(f"expected three components in line value: {value_str!r}")
        exprs_c = [
            parse_expr(
                p,
                transformations=_transformations,
                local_dict={"x": symbols("x"), "y": symbols("y"), "z": symbols("z")},
            )
            for p in c_parts
        ]
        exprs_d = [
            parse_expr(
                p,
                transformations=_transformations,
                local_dict={"x": symbols("x"), "y": symbols("y"), "z": symbols("z")},
            )
            for p in d_parts
        ]
        P = sympy_point_from_coords(*exprs_c)
        D = Matrix(exprs_d)
        P2 = sympy_point_from_coords(*(exprs_c[i] + exprs_d[i] for i in range(3)))
        # Always return a lightweight object exposing `.point` and `.direction`.
        sline = SimpleLine3D()
        setattr(sline, "point", P)
        setattr(sline, "direction", D)
        if SympyLine3D is not None:
            try:
                setattr(sline, "sympy", to_sympy_line((P, D)))
            except (AttributeError, TypeError, ValueError):
                pass
        return Line(sline)

    # Next, try parsing as an implicit cartesian equation lhs = rhs
    eq_result = _try_parse_line_equation(s)
    if eq_result is not None:
        return eq_result

    raise ValueError(f"not a line value: {value_str!r}")


@dataclass
class SegmentCommand:
    p1: Union[Any, str, None] = None
    p2: Union[Any, str, None] = None
    length: Optional[float] = None
    parent: Optional[str] = None

    def __repr__(self) -> str:
        if self.p1 is not None and self.p2 is not None:
            return f"Segment(p1={self.p1}, p2={self.p2})"
        return f"Segment(length={self.length})"



def segment_from_command(command_str: str, df=None, name_col: str = "Name", value_col: str = "Value", obj_col: str = "object3d"):
    if command_str is None:
        raise ValueError("empty command")
    s = command_str.strip()
    m = re.search(r"Segment\s*\(\s*([^,]+?)\s*,\s*([^,\)]+?)(?:\s*,\s*([^\)]+))?\s*\)", s)
    if not m:
        raise ValueError(f"not a Segment command: {command_str!r}")
    a = m.group(1).strip()
    b = m.group(2).strip()
    c = m.group(3).strip() if m.group(3) is not None else None
    ra = a if is_pointlike(a) else resolve_label_to_point(a, df, name_col, value_col, obj_col)
    rb = b if is_pointlike(b) else resolve_label_to_point(b, df, name_col, value_col, obj_col)
    if is_pointlike(ra) and is_pointlike(rb):
        if SympySegment is not None:
            try:
                return SympySegment(ra, rb)
            except (TypeError, ValueError, AttributeError):
                pass
        return SegmentCommand(p1=ra, p2=rb, parent=c)
    return SegmentCommand(p1=a, p2=b, parent=c)


def ray_from_command(command_str: str, df=None, name_col: str = "Name", value_col: str = "Value", obj_col: str = "object3d"):
    if command_str is None:
        raise ValueError("empty command")
    s = command_str.strip()
    m = re.search(r"Ray\s*\(\s*([^,]+?)\s*,\s*([^,\)]+?)\s*\)", s)
    if not m:
        raise ValueError(f"not a Ray command: {command_str!r}")
    a = m.group(1).strip()
    b = m.group(2).strip()
    ra = a if is_pointlike(a) else resolve_label_to_point(a, df, name_col, value_col, obj_col)
    rb = b if is_pointlike(b) else resolve_label_to_point(b, df, name_col, value_col, obj_col)
    if is_pointlike(ra) and is_pointlike(rb):
        try:
            z0 = getattr(ra, "z", 0)
            z1 = getattr(rb, "z", 0)
            if (z0 == 0 or z0 is None) and (z1 == 0 or z1 is None) and SympyRay is not None:
                try:
                    return SympyRay(ra, rb)
                except (TypeError, ValueError, AttributeError):
                    pass
            D = Matrix([rb[i] - ra[i] for i in range(3)])
            if SympyLine2D is not None and SympyPoint2D is not None:
                try:
                    P2d = SympyPoint2D(float(ra.x), float(ra.y))
                    P2d2 = SympyPoint2D(float(rb.x), float(rb.y))
                    return Line(SympyLine2D(P2d, P2d2))
                except (TypeError, ValueError, AttributeError):
                    pass
            return Line((ra, D))
        except (AttributeError, TypeError, ValueError):
            pass
    return Line((a, Matrix([0, 0, 0])))


__all__ = ["line_from_value", "segment_from_command", "ray_from_command"]
