"""Plane-related helpers (moved into sympy subpackage).
"""
import math
from typing import Any

from sympy import Matrix, sqrt, symbols
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from .point import sympy_point_from_coords, point_from_value
try:
    from .utils import is_pointlike, resolve_label_to_point, expr_from_value
except Exception:
    from .utils import is_pointlike, resolve_label_to_point
    expr_from_value = None

try:
    from sympy.geometry import Plane as SympyPlane
    from sympy.geometry import Point3D as SympyPoint3D
except ImportError:
    SympyPlane = None
    SympyPoint3D = None

_t = symbols("t")
_transformations = standard_transformations + (implicit_multiplication_application,)


def _parse_expr(s: str, local: dict = None):
    if expr_from_value is not None:
        return expr_from_value(s, transformations=_transformations, local_dict=local)
    return parse_expr(s, transformations=_transformations, local_dict=local)


def plane_from_value(value_str: str) -> Any:
    """Parse a plane equation string into a plane representation.

    Returns a SymPy Plane when available, otherwise a `(point, normal)` tuple.
    """
    if value_str is None:
        raise ValueError("empty value")
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    if "=" in s:
        lhs_str, rhs_str = s.split("=", 1)
    else:
        lhs_str, rhs_str = s, "0"
    x, y, z = symbols("x y z")
    local = {"x": x, "y": y, "z": z}
    lhs = _parse_expr(lhs_str.strip(), local=local)
    rhs = _parse_expr(rhs_str.strip(), local=local)
    if isinstance(rhs, tuple) or getattr(rhs, "is_Tuple", False):
        raise ValueError(f"RHS parses as tuple, not a plane equation: {value_str!r}")
    if isinstance(lhs, tuple) or getattr(lhs, "is_Tuple", False):
        raise ValueError(f"LHS parses as tuple, not a plane equation: {value_str!r}")
    expr = lhs - rhs
    a = expr.coeff(x, 1)
    b = expr.coeff(y, 1)
    c = expr.coeff(z, 1)
    const = expr.subs({x: 0, y: 0, z: 0})
    d = -const
    if a == 0 and b == 0 and c == 0:
        raise ValueError(f"no linear plane terms: {value_str!r}")
    normal = (a, b, c)
    if a != 0:
        pt = sympy_point_from_coords(d / a, 0, 0)
    elif b != 0:
        pt = sympy_point_from_coords(0, d / b, 0)
    else:
        pt = sympy_point_from_coords(0, 0, d / c)
    if SympyPlane is None:
        return (pt, normal)
    return SympyPlane(pt, normal)


def attach_planes(df, value_col="Value", out_col="sym_plane"):
    raise RuntimeError("attach_planes was removed; use parsing helpers directly if needed")


def _to_numeric_vector(v):
    if v is None:
        return None
    if isinstance(v, (tuple, list)):
        mat = Matrix(v)
    elif isinstance(v, Matrix):
        mat = v
    else:
        mat = Matrix(v)
    vals = [float(vi.evalf()) for vi in mat]
    return vals


# Delegate point-like resolution to shared helpers in `utils.py`.


def point_distance_to_plane(point, plane) -> float:
    """Return the numeric distance from `point` to `plane`.

    Tries SymPy's `distance` API first and falls back to numeric math.
    """
    try:
        d = plane.distance(point)
        return float(d.evalf())
    except (AttributeError, TypeError, ValueError) as exc:
        try:
            plane_pt = getattr(plane, "p1", None)
            normal = getattr(plane, "normal_vector", None)
            if plane_pt is None or normal is None:
                raise RuntimeError("cannot get plane point/normal") from exc
            P = Matrix(point)
            P0 = Matrix(plane_pt)
            N = Matrix(normal)
            num = (P - P0).dot(N)
            den = float(sqrt(sum(float((ni**2).evalf()) for ni in N)))
            return abs(float(num.evalf())) / den
        except (AttributeError, TypeError, ValueError, IndexError) as exc2:
            raise RuntimeError("failed to compute point-plane distance") from exc2


def point_on_plane(point, plane, tol=1e-2) -> bool:
    d = point_distance_to_plane(point, plane)
    return d <= tol


def _both_points_on_plane(p1, p2, plane, tol=1e-2) -> bool:
    try:
        return point_on_plane(p1, plane, tol=tol) and point_on_plane(p2, plane, tol=tol)
    except (TypeError, AttributeError):
        return False


def circle_on_plane(circle, plane, dist_tol=1e-2, angle_tol=1e-1) -> bool:
    center_ok = point_on_plane(circle.center, plane, tol=dist_tol)
    plane_n = getattr(plane, "normal_vector", None)
    circ_n = getattr(circle, "normal", None)
    if plane_n is None or circ_n is None:
        return False
    n1 = _to_numeric_vector(plane_n)
    n2 = _to_numeric_vector(circ_n)
    if n1 is None or n2 is None:
        return False

    def norm(vec):
        return math.sqrt(sum(x * x for x in vec))

    d1 = norm(n1)
    d2 = norm(n2)
    if d1 == 0 or d2 == 0:
        return False
    dot = sum([a * b for a, b in zip(n1, n2)])
    cosang = abs(dot) / (d1 * d2)
    cosang = max(min(cosang, 1.0), -1.0)
    ang = math.acos(cosang)
    angle_ok = ang <= angle_tol
    return center_ok and angle_ok


def valueobject_on_plane(vo, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    """Determine whether a value-object `vo` lies on `plane`.

    This function delegates the specific checks to small helpers to
    keep complexity manageable.
    """
    if vo is None or plane is None:
        return False

    # Point
    try:
        if hasattr(vo, "is_point") and vo.is_point():
            return _vo_point_on_plane(vo, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        pass

    # Circle
    try:
        if hasattr(vo, "is_circle") and vo.is_circle():
            return _vo_circle_on_plane(vo, plane, dist_tol=tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        pass

    # Line
    try:
        if hasattr(vo, "is_line") and vo.is_line():
            return _vo_line_on_plane(vo, plane, tol=tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        pass

    # Segment
    try:
        if hasattr(vo, "is_segment") and vo.is_segment():
            return _vo_segment_on_plane(vo, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        pass

    # Plane
    try:
        if hasattr(vo, "is_plane") and vo.is_plane():
            return _vo_plane_on_plane(vo, plane, tol=tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        pass

    return False


def _vo_point_on_plane(vo, plane, tol=1e-2) -> bool:
    try:
        return point_on_plane(vo.obj, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _vo_circle_on_plane(vo, plane, dist_tol=1e-2, angle_tol=1e-1) -> bool:
    try:
        return circle_on_plane(vo.obj, plane, dist_tol=dist_tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _vo_line_on_plane(vo, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    try:
        return line_on_plane(vo.obj, plane, tol=tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _vo_segment_on_plane(vo, plane, tol=1e-2) -> bool:
    try:
        seg = vo.obj
        p1 = getattr(seg, "p1", None)
        p2 = getattr(seg, "p2", None)
        if p1 is None or p2 is None:
            return False
        return point_on_plane(p1, plane, tol=tol) and point_on_plane(p2, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _vo_plane_on_plane(vo, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    try:
        pl = vo.obj
        N1 = _to_numeric_vector(getattr(pl, "normal_vector", None))
        N2 = _to_numeric_vector(getattr(plane, "normal_vector", None))
        if N1 is None or N2 is None:
            return False
        d1 = math.sqrt(sum([x * x for x in N1]))
        d2 = math.sqrt(sum([x * x for x in N2]))
        if d1 == 0 or d2 == 0:
            return False
        dot = sum([a * b for a, b in zip(N1, N2)])
        cosang = abs(dot) / (d1 * d2)
        cosang = max(min(cosang, 1.0), -1.0)
        ang = math.acos(cosang)
        pt = getattr(pl, "p1", None)
        if pt is None:
            return False
        return (ang <= angle_tol) and point_on_plane(pt, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _check_point_on_plane(oj, plane, tol=1e-2) -> bool:
    """Return True if object `oj` (Object3D-like) is a point on `plane`.

    This helper centralizes the point membership check used by the
    enumerator to keep the loop body small.
    """
    try:
        return oj.kind == "point" and is_pointlike(getattr(oj, "obj", None)) and point_on_plane(getattr(oj, "obj", None), plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        return False


def _check_segment_on_plane(oj, plane, df=None, name_col: str = "Name", value_col: str = "Value", obj_col: str = "object3d", tol: float = 1e-2) -> bool:
    """Return True if object `oj` (Object3D-like) is a segment lying on `plane`.

    Uses the existing `segment_on_plane` helper but keeps the enumerator
    loop concise.
    """
    try:
        if oj.kind == "segment":
            return segment_on_plane(oj.obj, plane, df=df, name_col=name_col, value_col=value_col, obj_col=obj_col, tol=tol)
        return False
    except (AttributeError, TypeError, ValueError):
        return False


def _check_circle_on_plane(oj, plane) -> bool:
    """Return True if object `oj` (Object3D-like) is a circle on `plane`."""
    try:
        return oj.kind == "circle" and circle_on_plane(oj.obj, plane)
    except (AttributeError, TypeError, ValueError):
        return False


def _check_line_on_plane(oj, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    """Return True if object `oj` (Object3D-like) is a line on `plane`."""
    try:
        return oj.kind == "line" and line_on_plane(oj.obj, plane, tol=tol, angle_tol=angle_tol)
    except (AttributeError, TypeError, ValueError):
        return False


def segment_on_plane(seg, plane, df=None, name_col: str = "Name", value_col: str = "Value", obj_col: str = "object3d", tol: float = 1e-2) -> bool:
    # print(f"Checking if segment {seg} is on plane {plane}")
    if seg is None or plane is None:
        return False
    p1 = getattr(seg, "p1", None)
    p2 = getattr(seg, "p2", None)
    if p1 is None or p2 is None:
        return False
    if (isinstance(p1, str) or isinstance(p2, str)) and df is None:
        raise ValueError("df is required to resolve labeled segment endpoints")

    # Resolve labels using shared helper
    def _resolve_label(label):
        return resolve_label_to_point(label, df=df, name_col=name_col, value_col=value_col, obj_col=obj_col)

    # print(f"Segment endpoints before resolution: {p1}, {p2}")
    rp1 = p1 if is_pointlike(p1) else _resolve_label(p1)
    rp2 = p2 if is_pointlike(p2) else _resolve_label(p2)
    if not is_pointlike(rp1) or not is_pointlike(rp2):
        return False
    # print(f"Resolved segment endpoints: {rp1}, {rp2}")
    return point_on_plane(rp1, plane, tol=tol) and point_on_plane(rp2, plane, tol=tol)


def line_on_plane(line_obj, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    if line_obj is None or plane is None:
        return False
    try:
        # Extract point and direction from several possible representations
        P = None
        D_raw = None
        if hasattr(line_obj, "point") and hasattr(line_obj, "direction"):
            P = getattr(line_obj, "point")
            D_raw = getattr(line_obj, "direction")
        elif hasattr(line_obj, "p1") and hasattr(line_obj, "p2"):
            try:
                P = getattr(line_obj, "p1")
                p2 = getattr(line_obj, "p2")
                try:
                    D_raw = Matrix([p2[i] - P[i] for i in range(3)])
                except (TypeError, IndexError, AttributeError):
                    D_raw = Matrix([getattr(p2, ("x", "y", "z")[i]) - getattr(P, ("x", "y", "z")[i]) for i in range(3)])
            except (AttributeError, TypeError, IndexError, ValueError):
                return False
            # If constructed from two explicit points, treat like a segment.
            if hasattr(P, "x") and hasattr(P, "y") and hasattr(p2, "x") and hasattr(p2, "y"):
                return _both_points_on_plane(P, p2, plane, tol=tol)
        elif hasattr(line_obj, "points"):
            try:
                pts = list(line_obj.points)
                if len(pts) >= 2:
                    P = pts[0]
                    p2 = pts[1]
                    try:
                        D_raw = Matrix([p2[i] - P[i] for i in range(3)])
                    except (TypeError, IndexError, AttributeError):
                        D_raw = Matrix([getattr(p2, ("x", "y", "z")[i]) - getattr(P, ("x", "y", "z")[i]) for i in range(3)])
                else:
                    return False
            except (AttributeError, TypeError, IndexError, ValueError):
                return False
            # If points are explicit, treat like segment as well
            if hasattr(P, "x") and hasattr(P, "y") and hasattr(p2, "x") and hasattr(p2, "y"):
                return _both_points_on_plane(P, p2, plane, tol=tol)
        else:
            return False

        N = _to_numeric_vector(getattr(plane, "normal_vector", None))
        Dn = _to_numeric_vector(D_raw)
        if N is None or Dn is None:
            return False
        d1 = math.sqrt(sum(x * x for x in Dn))
        d2 = math.sqrt(sum(x * x for x in N))
        if d1 == 0 or d2 == 0:
            return False
        dot = sum([a * b for a, b in zip(Dn, N)])
        cosang = abs(dot) / (d1 * d2)
        cosang = max(min(cosang, 1.0), -1.0)
        ang = math.acos(cosang)
        if abs(ang - math.pi / 2) > angle_tol:
            return False
        return point_on_plane(P, plane, tol=tol)
    except (AttributeError, TypeError, ValueError):
        return False



def enumerate_plane_members(
    df,
    type_col: str = "Type",
    name_col: str = "Name",
    command_col: str = "Command",
    value_col: str = "Value",
    out_col: str = "plane_members",
):
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("enumerate_plane_members requires a polars DataFrame")

    from .object3d import Object3D, SegmentCommand as SegmentType

    members_list = []

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    names = df[name_col].to_list()

    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            o = Object3D.from_value_command(value=(v if v is not None else None), command=(c if c is not None else None))
        except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError, RuntimeError):
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append((t, o))

    # reuse module-level helper

    for idx, (t, o) in enumerate(objs):
        # print(f"Processing object {names[idx]} of type {t} for plane membership")
        if (isinstance(t, str) and t.lower() == "plane") or (t == "plane"):
            try:
                plane = plane_from_value(vals[idx])
            except (ValueError, TypeError):
                members_list.append([])
                continue
            members = []
            for j, (tt, oj) in enumerate(objs):
                if j == idx:
                    continue
                name_j = names[j]
                if _check_point_on_plane(oj, plane):
                    members.append(name_j)
                    continue
                # print(f"Checking object {name_j} of type {oj.kind} {oj.obj}for plane membership")
                if _check_segment_on_plane(oj, plane, df=df, name_col=name_col, value_col=value_col, obj_col="object3d"):
                    members.append(name_j)
                    continue
                if _check_circle_on_plane(oj, plane):
                    members.append(name_j)
                    continue
                if _check_line_on_plane(oj, plane):
                    members.append(name_j)
                    continue
            members_list.append(members)
        else:
            members_list.append([])

    try:
        list_type = getattr(pl, "List")(getattr(pl, "Utf8"))
        s = pl.Series(out_col, members_list, dtype=list_type)
    except (AttributeError, TypeError):
        try:
            s = pl.Series(out_col, members_list)
        except (TypeError, ValueError):
            s = pl.Series(out_col, [[str(x) for x in m] for m in members_list])
    return df.with_columns([s])

__all__ = [
    "plane_from_value",
    "point_distance_to_plane",
    "point_on_plane",
    "circle_on_plane",
    "valueobject_on_plane",
    "segment_on_plane",
    "line_on_plane",
    "enumerate_plane_members",
]