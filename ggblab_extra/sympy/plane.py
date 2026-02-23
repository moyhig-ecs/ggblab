"""Plane-related helpers (moved into sympy subpackage).
"""
import math
import re
from typing import Any

from sympy import Matrix, sqrt, symbols
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from .point import sympy_point_from_coords, point_from_value

try:
    from sympy.geometry import Plane as SympyPlane
    from sympy.geometry import Point3D as SympyPoint3D
except Exception:
    SympyPlane = None
    SympyPoint3D = None

_t = symbols("t")
_transformations = standard_transformations + (implicit_multiplication_application,)


def plane_from_value(value_str: str) -> Any:
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
    lhs = parse_expr(lhs_str.strip(), transformations=_transformations, local_dict={"x": x, "y": y, "z": z})
    rhs = parse_expr(rhs_str.strip(), transformations=_transformations, local_dict={"x": x, "y": y, "z": z})
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


def point_distance_to_plane(point, plane) -> float:
    try:
        d = plane.distance(point)
        return float(d.evalf())
    except Exception:
        try:
            plane_pt = getattr(plane, "p1", None)
            normal = getattr(plane, "normal_vector", None)
            if plane_pt is None or normal is None:
                raise RuntimeError("cannot get plane point/normal")
            P = Matrix(point)
            P0 = Matrix(plane_pt)
            N = Matrix(normal)
            num = (P - P0).dot(N)
            den = float(sqrt(sum([float((ni**2).evalf()) for ni in N])))
            return abs(float(num.evalf())) / den
        except Exception:
            raise


def point_on_plane(point, plane, tol=1e-2) -> bool:
    d = point_distance_to_plane(point, plane)
    return d <= tol


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
        return math.sqrt(sum([x * x for x in vec]))

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
    if vo is None or plane is None:
        return False
    try:
        from typing import Any

        if hasattr(vo, "is_point") and vo.is_point():
            return point_on_plane(vo.obj, plane, tol=tol)
        if hasattr(vo, "is_circle") and vo.is_circle():
            return circle_on_plane(vo.obj, plane, dist_tol=tol, angle_tol=angle_tol)
        if hasattr(vo, "is_line") and vo.is_line():
            l = vo.obj
            D = _to_numeric_vector(getattr(l, "direction", None))
            N = _to_numeric_vector(getattr(plane, "normal_vector", None))
            P = getattr(l, "point", None)
            if D is None or N is None or P is None:
                return False
            d1 = math.sqrt(sum([x * x for x in D]))
            d2 = math.sqrt(sum([x * x for x in N]))
            if d1 == 0 or d2 == 0:
                return False
            dot = sum([a * b for a, b in zip(D, N)])
            cosang = abs(dot) / (d1 * d2)
            cosang = max(min(cosang, 1.0), -1.0)
            ang = math.acos(cosang)
            if abs(ang - math.pi / 2) > angle_tol:
                return False
            return point_on_plane(P, plane, tol=tol)
        if hasattr(vo, "is_segment") and vo.is_segment():
            seg = vo.obj
            p1 = getattr(seg, "p1", None)
            p2 = getattr(seg, "p2", None)
            if p1 is None or p2 is None:
                return False
            return point_on_plane(p1, plane, tol=tol) and point_on_plane(p2, plane, tol=tol)
        if hasattr(vo, "is_plane") and vo.is_plane():
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
        return False
    except Exception:
        return False


def segment_on_plane(seg, plane, df=None, name_col: str = "Name", value_col: str = "Value", obj_col: str = "object3d", tol: float = 1e-2) -> bool:
    if seg is None or plane is None:
        return False
    p1 = getattr(seg, "p1", None)
    p2 = getattr(seg, "p2", None)
    if p1 is None or p2 is None:
        return False
    if (isinstance(p1, str) or isinstance(p2, str)) and df is None:
        raise ValueError("df is required to resolve labeled segment endpoints")

    def _is_pointlike(obj: object) -> bool:
        try:
            return hasattr(obj, "x") and hasattr(obj, "y")
        except Exception:
            return False

    def _resolve_label(label):
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
                return point_from_value(matches[value_col][0])
            except Exception:
                return None
        except Exception:
            return None

    rp1 = p1 if _is_pointlike(p1) else _resolve_label(p1)
    rp2 = p2 if _is_pointlike(p2) else _resolve_label(p2)
    if not _is_pointlike(rp1) or not _is_pointlike(rp2):
        return False
    return point_on_plane(rp1, plane, tol=tol) and point_on_plane(rp2, plane, tol=tol)


def line_on_plane(line_obj, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    if line_obj is None or plane is None:
        return False
    try:
        if hasattr(line_obj, "point") and hasattr(line_obj, "direction"):
            P = getattr(line_obj, "point")
            D = getattr(line_obj, "direction")
        else:
            return False
        N = _to_numeric_vector(getattr(plane, "normal_vector", None))
        Dn = _to_numeric_vector(D)
        if N is None or Dn is None:
            return False
        d1 = math.sqrt(sum([x * x for x in Dn]))
        d2 = math.sqrt(sum([x * x for x in N]))
        if d1 == 0 or d2 == 0:
            return False
        dot = sum([a * b for a, b in zip(Dn, N)])
        cosang = abs(dot) / (d1 * d2)
        cosang = max(min(cosang, 1.0), -1.0)
        ang = math.acos(cosang)
        if abs(ang - math.pi / 2) > angle_tol:
            return False
        return point_on_plane(P, plane, tol=tol)
    except Exception:
        return False


__all__ = [
    "plane_from_value",
    "attach_planes",
    "point_distance_to_plane",
    "point_on_plane",
    "circle_on_plane",
    "valueobject_on_plane",
    "segment_on_plane",
    "line_on_plane",
    "enumerate_plane_members",
]


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

    from .three_d import Object3D, Segment as SegmentType

    members_list = []

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    names = df[name_col].to_list()

    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            o = Object3D.from_value_command(value=(v if v is not None else None), command=(c if c is not None else None))
        except Exception:
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append((t, o))

    def _is_pointlike(obj: object) -> bool:
        try:
            return hasattr(obj, "x") and hasattr(obj, "y")
        except Exception:
            return False

    for idx, (t, o) in enumerate(objs):
        if (isinstance(t, str) and t.lower() == "plane") or (t == "plane"):
            try:
                plane = plane_from_value(vals[idx])
            except Exception:
                members_list.append([])
                continue
            members = []
            for j, (tt, oj) in enumerate(objs):
                if j == idx:
                    continue
                name_j = names[j]
                if oj.kind == "point" and _is_pointlike(getattr(oj, "obj", None)):
                    try:
                        if point_on_plane(getattr(oj, "obj", None), plane):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
                if oj.kind == "segment" and isinstance(oj.obj, SegmentType):
                    try:
                        if segment_on_plane(
                            oj.obj,
                            plane,
                            df=df,
                            name_col=name_col,
                            value_col=value_col,
                            obj_col="object3d",
                            tol=1e-2,
                        ):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
                if oj.kind == "circle":
                    try:
                        if circle_on_plane(oj.obj, plane):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
                if oj.kind == "line":
                    try:
                        if line_on_plane(oj.obj, plane):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
            members_list.append(members)
        else:
            members_list.append([])

    try:
        list_type = getattr(pl, "List")(getattr(pl, "Utf8"))
        s = pl.Series(out_col, members_list, dtype=list_type)
    except Exception:
        try:
            s = pl.Series(out_col, members_list)
        except Exception:
            s = pl.Series(out_col, [[str(x) for x in m] for m in members_list])
    return df.with_columns([s])
