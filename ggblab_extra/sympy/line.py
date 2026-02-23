"""Line helpers (moved into sympy subpackage).
"""
from dataclasses import dataclass
from typing import Protocol, Any, TypeVar, Generic, Union
from sympy import Matrix

try:
    from sympy.geometry.line3d import Line3D as SympyLine3D
except Exception:
    try:
        from sympy.geometry import Line3D as SympyLine3D
    except Exception:
        SympyLine3D = None

try:
    from sympy.geometry.line import Line as SympyLine2D
except Exception:
    try:
        from sympy.geometry import Line as SympyLine2D
    except Exception:
        SympyLine2D = None

try:
    from sympy.geometry.point import Point2D as SympyPoint2D
except Exception:
    try:
        from sympy.geometry import Point2D as SympyPoint2D
    except Exception:
        SympyPoint2D = None


class LineLike(Protocol):
    point: Any
    direction: Any
    p1: Any
    p2: Any


AnyLine = TypeVar("AnyLine", bound=LineLike)


@dataclass
class Line(Generic[AnyLine]):
    obj: AnyLine

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"Line({self.obj!r})"

    def __getattr__(self, name: str):
        return getattr(self.obj, name)


@dataclass
class SimpleLine3D:
    pass


def to_sympy_line(simple) -> object:
    if SympyLine3D is None:
        return simple
    try:
        if isinstance(simple, (tuple, list)):
            p, d = simple[0], simple[1]
        else:
            p, d = getattr(simple, "point"), getattr(simple, "direction")
        try:
            p2 = type(p)(*(p[i] + d[i] for i in range(3)))
        except Exception:
            p2 = type(p)(p.x + d[0], p.y + d[1], p.z + d[2])
        return SympyLine3D(p, p2)
    except Exception:
        return simple


import re
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy import symbols, Matrix, sin, cos
from .point import sympy_point_from_coords, point_from_value
from typing import Optional

try:
    from sympy.geometry.segment import Segment as SympySegment
except Exception:
    try:
        from sympy.geometry import Segment as SympySegment
    except Exception:
        SympySegment = None

try:
    from sympy.geometry.ray import Ray as SympyRay
except Exception:
    try:
        from sympy.geometry import Ray as SympyRay
    except Exception:
        SympyRay = None

_t = symbols("t")
_transformations = standard_transformations + (implicit_multiplication_application,)


def line_from_value(value_str: str) -> object:
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    m = re.search(r"=\s*\(([^)]+)\)\s*\+\s*(?:λ\s*)?\(([^)]+)\)", s)
    if not m:
        if "=" in s:
            try:
                x, y, z = symbols("x y z")
                if ":" in s:
                    _, s2 = s.split(":", 1)
                else:
                    s2 = s
                lhs_str, rhs_str = s2.split("=", 1)
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
                    raise ValueError()
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
                    except Exception:
                        p2 = sympy_point_from_coords(P.x + D[0], P.y + D[1], P.z + D[2])
                    return Line(SympyLine3D(P, p2))
            except Exception:
                pass
        raise ValueError(f"not a line value: {value_str!r}")
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
    if SympyLine3D is None:
        return Line((P, D))
    return Line(SympyLine3D(P, P2))


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


def _is_pointlike(obj: object) -> bool:
    try:
        return hasattr(obj, "x") and hasattr(obj, "y")
    except Exception:
        return False


def _resolve_label_to_point(label: str, df, name_col: str, value_col: str, obj_col: str):
    if _is_pointlike(label):
        return label
    if not isinstance(label, str):
        return None
    if df is None:
        return None
    try:
        matches = df.filter(df[name_col] == label)
        if len(matches) == 0:
            return None
        try:
            obj = matches[obj_col][0]
            resolved = getattr(obj, "obj", obj) if obj is not None else None
            if _is_pointlike(resolved):
                return resolved
        except Exception:
            pass
        try:
            return sympy_point_from_coords(*[parse_expr(v, transformations=_transformations) for v in matches[value_col][0].strip().lstrip(label).strip().lstrip("=").strip().strip("()").split(",")])
        except Exception:
            return None
    except Exception:
        try:
            sel = df[df[name_col] == label]
            if len(sel) == 0:
                return None
            row = sel.iloc[0]
            try:
                obj = row[obj_col]
                resolved = getattr(obj, "obj", obj) if obj is not None else None
                if _is_pointlike(resolved):
                    return resolved
            except Exception:
                pass
            try:
                return point_from_value(row[value_col])
            except Exception:
                return None
        except Exception:
            return None


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
    ra = a if _is_pointlike(a) else _resolve_label_to_point(a, df, name_col, value_col, obj_col)
    rb = b if _is_pointlike(b) else _resolve_label_to_point(b, df, name_col, value_col, obj_col)
    if _is_pointlike(ra) and _is_pointlike(rb):
        if SympySegment is not None:
            try:
                return SympySegment(ra, rb)
            except Exception:
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
    ra = a if _is_pointlike(a) else _resolve_label_to_point(a, df, name_col, value_col, obj_col)
    rb = b if _is_pointlike(b) else _resolve_label_to_point(b, df, name_col, value_col, obj_col)
    if _is_pointlike(ra) and _is_pointlike(rb):
        try:
            z0 = getattr(ra, "z", 0)
            z1 = getattr(rb, "z", 0)
            if (z0 == 0 or z0 is None) and (z1 == 0 or z1 is None) and SympyRay is not None:
                try:
                    return SympyRay(ra, rb)
                except Exception:
                    pass
            D = Matrix([rb[i] - ra[i] for i in range(3)])
            if SympyLine2D is not None and SympyPoint2D is not None:
                try:
                    P2d = SympyPoint2D(float(ra.x), float(ra.y))
                    P2d2 = SympyPoint2D(float(rb.x), float(rb.y))
                    return Line(SympyLine2D(P2d, P2d2))
                except Exception:
                    pass
            return Line((ra, D))
        except Exception:
            pass
    return Line((a, Matrix([0, 0, 0])))


__all__ = ["line_from_value", "segment_from_command", "ray_from_command"]
