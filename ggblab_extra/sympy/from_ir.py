"""SymPy objects from the construction XML's numbers (stage 2 "algebra", 2026-09-10; data-in, ruling (ii)).

v1's `*_from_value` parsers read `getValueString` display strings ("p: -1.71x - 2.47z = 0", rounded to 2 decimals).
Under ruling (ii) those strings are gone; the XML carries the exact numbers (see geometry_ir.py for the conventions).
This module builds the same kinds of objects v1's `Object3D.from_value_command` produced — `kind` in {point, line,
segment, ray, circle, plane, sphere, conic, quadric, vector, polygon, numeric, text, list} — from `ElementIR` records,
so `enumerate_plane_members` style analysis (eg12) runs on the XML alone.  v1 modules are untouched; only new code here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import polars as pl
from sympy import Eq, Float, Matrix, S, sqrt, symbols, sympify
from sympy.geometry import Circle as SympyCircle
from sympy.geometry import Line2D, Line3D, Plane as SympyPlane, Point2D, Point3D, Polygon as SympyPolygon, Ray2D, Ray3D, Segment2D, Segment3D

from ggblab_extra.geometry_ir import ElementIR, element_irs
from .circle import Circle3D
from .object3d import Object3D
from .plane import _check_circle_on_plane, _check_line_on_plane, _check_point_on_plane, _check_segment_on_plane, point_on_plane

X, Y, Z = symbols("x y z")


def P2(*a):
    return Point2D(*a, evaluate=False)


def P3(*a):
    return Point3D(*a, evaluate=False)
_AXES: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {   # name → (a point, direction)
    "xAxis": ((0, 0, 0), (1, 0, 0)), "yAxis": ((0, 0, 0), (0, 1, 0)), "zAxis": ((0, 0, 0), (0, 0, 1)),
}
_PLANES: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {   # name → (a point, normal)
    "xOyPlane": ((0, 0, 0), (0, 0, 1)),
}
_2D_LINE_TYPES = ("line", "segment", "ray")


@dataclass(frozen=True)
class Sphere:
    """SymPy has no sphere; the quadric's own numbers give centre and radius (kind "sphere")."""
    center: Point3D
    radius: Any

    def distance(self, p) -> Any:                      # |d(center, p) − r| — 0 on the surface
        return abs(self.center.distance(p) - self.radius)


@dataclass(frozen=True)
class Vector:
    start: Any                                           # Point2D / Point3D (None when the tail is unknown)
    direction: Matrix

    @property
    def end(self):
        if self.start is None:
            return None
        return self.start + type(self.start)(*self.direction)


def _num(s: Optional[str]):
    """The XML's text → a SymPy number: integers stay exact, decimals become Float (sympy's Point would otherwise
    rationalise them into 50-digit fractions)."""
    if s is None:
        return S.Zero
    t = str(s).strip()
    try:
        return S(int(t))
    except ValueError:
        return Float(t)


def _is_zero(v, tol: float = 1e-12) -> bool:
    try:
        return abs(float(v)) <= tol
    except (TypeError, ValueError):
        return v == 0


def point_from_ir(ir: ElementIR, as_3d: bool = False):
    """point / point3d → Point2D / Point3D (homogeneous weight divided out); None for a point at infinity or no coords."""
    if not ir.coords:
        return None
    if ir.type == "point3d" or ir.coord("w") is not None:
        x, y, z, w = (_num(ir.coord(k)) for k in ("x", "y", "z", "w"))
        if _is_zero(w):
            return None
        return P3(x / w, y / w, z / w)
    x, y, z = (_num(ir.coord(k)) for k in ("x", "y", "z"))
    if _is_zero(z):
        return None
    p = (x / z, y / z)
    return P3(*p, 0) if as_3d else P2(*p)


def _resolve_point(label: str, irs: Mapping[str, ElementIR], as_3d: bool):
    ir = irs.get(label)
    if ir is None:
        return None
    if ir.type in ("point", "point3d"):
        return point_from_ir(ir, as_3d=as_3d)
    return None


def _line2d_from_coefficients(a, b, c):
    """a X + b Y + c = 0 → Line2D through two of its points."""
    if not _is_zero(b):
        p1, p2 = P2(0, -c / b), P2(1, (-c - a) / b)
    elif not _is_zero(a):
        p1, p2 = P2(-c / a, 0), P2(-c / a, 1)
    else:
        return None
    return Line2D(p1, p2)


def line_from_ir(ir: ElementIR, irs: Mapping[str, ElementIR] = None, as_3d: bool = False):
    """line / segment / ray (2D coefficients; endpoints from the command) and line3d / segment3d (origin + direction /
    endpoints from the command) → the SymPy line-like object; None when the numbers are not there."""
    irs = irs or {}
    cmd = ir.command
    if ir.type == "line3d":
        ow = _num(ir.coord("ow"))
        if _is_zero(ow) or ir.coord("vx") is None:
            return None
        o = P3(_num(ir.coord("ox")) / ow, _num(ir.coord("oy")) / ow, _num(ir.coord("oz")) / ow)
        d = [_num(ir.coord(k)) for k in ("vx", "vy", "vz")]
        if all(_is_zero(v) for v in d):
            return None
        return Line3D(o, direction_ratio=d)
    if ir.type in ("segment3d", "ray3d") or (ir.type in ("segment", "ray") and as_3d):
        if cmd is None or len(cmd.inputs) < 2:
            return None
        p, q = (_resolve_point(l, irs, True) for l in cmd.inputs[:2])
        if p is None or q is None or p == q:
            return None
        return Segment3D(p, q) if ir.type.startswith("segment") else Ray3D(p, q)
    if ir.type in _2D_LINE_TYPES:
        if ir.type in ("segment", "ray") and cmd is not None and len(cmd.inputs) >= 2:
            p, q = (_resolve_point(l, irs, False) for l in cmd.inputs[:2])
            if p is not None and q is not None and p != q:
                return Segment2D(p, q) if ir.type == "segment" else Ray2D(p, q)
        if not ir.coords:
            return None
        return _line2d_from_coefficients(*(_num(ir.coord(k)) for k in ("x", "y", "z")))
    return None


def plane_from_ir(ir: ElementIR):
    """plane3d coords (a, b, c, d): a X + b Y + c Z + d = 0 → sympy Plane (a point of it + its normal)."""
    if ir.type != "plane3d" or not ir.coords:
        return None
    a, b, c, d = (_num(ir.coord(k)) for k in ("x", "y", "z", "w"))
    if not _is_zero(a):
        pt = P3(-d / a, 0, 0)
    elif not _is_zero(b):
        pt = P3(0, -d / b, 0)
    elif not _is_zero(c):
        pt = P3(0, 0, -d / c)
    else:
        return None
    return SympyPlane(pt, normal_vector=(a, b, c))


def conic_from_ir(ir: ElementIR):
    """conic matrix A0..A5: A0 X² + A1 Y² + A2 + 2 A3 XY + 2 A4 X + 2 A5 Y = 0 → sympy Circle when it is one, else the
    equation Eq(expr, 0) in x, y."""
    if not ir.matrix or len(ir.matrix) < 6:
        return None
    A0, A1, A2, A3, A4, A5 = (_num(v) for v in ir.matrix[:6])
    if not _is_zero(A0) and _is_zero(A0 - A1, 1e-9) and _is_zero(A3, 1e-9):
        cx, cy = -A4 / A0, -A5 / A0
        r2 = cx**2 + cy**2 - A2 / A0
        if float(r2) > 0:
            return SympyCircle(P2(cx, cy), sqrt(r2), evaluate=False)
    return Eq(A0 * X**2 + A1 * Y**2 + A2 + 2 * A3 * X * Y + 2 * A4 * X + 2 * A5 * Y, 0)


def quadric_from_ir(ir: ElementIR):
    """quadric matrix A0..A9 → Sphere(center, radius) when it is one, else Eq(expr, 0) in x, y, z."""
    if not ir.matrix or len(ir.matrix) < 10:
        return None
    A = [_num(v) for v in ir.matrix[:10]]
    A0, A1, A2, A3, A4, A5, A6, A7, A8, A9 = A
    if not _is_zero(A0) and all(_is_zero(A0 - v, 1e-9) for v in (A1, A2)) and all(_is_zero(v, 1e-9) for v in (A4, A5, A6)):
        c = P3(-A7 / A0, -A8 / A0, -A9 / A0)
        r2 = c.x**2 + c.y**2 + c.z**2 - A3 / A0
        if float(r2) > 0:
            return Sphere(c, sqrt(r2))
    return Eq(A0 * X**2 + A1 * Y**2 + A2 * Z**2 + A3 + 2 * (A4 * X * Y + A5 * X * Z + A6 * Y * Z + A7 * X + A8 * Y + A9 * Z), 0)


def _axis_or_line(label: str, irs: Mapping[str, ElementIR]):
    """A 3D line by label: xAxis/yAxis/zAxis, or an element line3d / segment3d (two of its points)."""
    if label in _AXES:
        p, d = _AXES[label]
        return Line3D(P3(*p), direction_ratio=list(d))
    ir = irs.get(label)
    if ir is None:
        return None
    l = line_from_ir(ir, irs, as_3d=True)
    if isinstance(l, (Segment3D, Ray3D)):
        return Line3D(l.p1, l.p2)
    return l if isinstance(l, Line3D) else None


def _circle3d(center: Point3D, normal: Sequence[Any], radius) -> Circle3D:
    n = Matrix(list(normal))
    # any two unit vectors spanning the plane (the parametric axes v1 stored from "X = c + (cos t) A + (sin t) B")
    trial = Matrix([1, 0, 0]) if not _is_zero(n[1]) or not _is_zero(n[2]) else Matrix([0, 1, 0])
    a = trial - n * (trial.dot(n) / n.dot(n)); a = a / sqrt(a.dot(a))
    b = n.cross(a); b = b / sqrt(b.dot(b))
    return Circle3D(center=center, normal=n, radius=radius, axis_cos=a * radius, axis_sin=b * radius)


def _numeric_arg(label: str, irs: Mapping[str, ElementIR]):
    ir = irs.get(label)
    if ir is not None and ir.value is not None:
        return _num(ir.value)
    try:
        return sympify(label)
    except Exception:
        return None


def circle3d_from_command(ir: ElementIR, irs: Mapping[str, ElementIR]):
    """conic3d has no coordinate system in the XML; the command gives it: Circle(<axis line>, <point>) and the two rim
    circles of Cylinder(P1, P2, r) (output 1 is centred at P1, output 2 at P2 — measured against v1's value string)."""
    cmd = ir.command
    if cmd is None:
        return None
    if cmd.name == "Circle" and len(cmd.inputs) >= 2:
        axis = _axis_or_line(cmd.inputs[0], irs); p = _resolve_point(cmd.inputs[1], irs, True)
        if axis is not None and p is not None:
            foot = axis.projection(p)
            r = foot.distance(p)
            if _is_zero(r):
                return None
            return _circle3d(foot, axis.direction_ratio, r)
    if cmd.name in ("Cylinder", "Cone") and len(cmd.inputs) >= 3 and cmd.index in (1, 2):
        p1, p2 = (_resolve_point(l, irs, True) for l in cmd.inputs[:2]); r = _numeric_arg(cmd.inputs[2], irs)
        if p1 is None or p2 is None or r is None or p1 == p2:
            return None
        center = p1 if cmd.index == 1 else p2
        if cmd.name == "Cone" and cmd.index == 1:
            return None
        return _circle3d(center, [p1.x - p2.x, p1.y - p2.y, p1.z - p2.z], r)
    return None


def polygon_from_ir(ir: ElementIR, irs: Mapping[str, ElementIR], as_3d: bool):
    cmd = ir.command
    if cmd is None or cmd.name != "Polygon":
        return None
    pts = [_resolve_point(l, irs, as_3d) for l in cmd.inputs]
    if len(cmd.inputs) == 3 and pts[2] is None and irs.get(cmd.inputs[2]) is None:
        return None                                  # Polygon(A, B, n): the regular polygon — vertices are outputs, not inputs
    if any(p is None for p in pts) or len(pts) < 3:
        return None
    try:
        return SympyPolygon(*pts)
    except Exception:
        return None


def vector_from_ir(ir: ElementIR, irs: Mapping[str, ElementIR], as_3d: bool):
    if not ir.coords:
        return None
    if ir.type == "vector3d" or ir.coord("w") is not None:
        d = Matrix([_num(ir.coord(k)) for k in ("x", "y", "z")]); three = True
    else:
        d = Matrix([_num(ir.coord(k)) for k in ("x", "y")]); three = False
        if as_3d:
            d = Matrix([d[0], d[1], 0]); three = True
    start = _resolve_point(ir.start_point, irs, three) if ir.start_point else None
    return Vector(start, d)


def object_from_ir(ir: ElementIR, irs: Mapping[str, ElementIR], as_3d: bool = False) -> Object3D:
    """One element → Object3D(kind, obj, value=None, command=<name(inputs)>).  `as_3d` lifts 2D classes into 3D
    coordinates (z = 0) so that a 3D document's `point` / `segment` elements take part in plane membership."""
    cmd = f"{ir.command.name}({', '.join(ir.command.inputs)})" if ir.command else None
    t = ir.type
    kind, obj = None, None
    try:
        if t in ("point", "point3d"):
            kind, obj = "point", point_from_ir(ir, as_3d=as_3d)
        elif t in ("line", "line3d"):
            kind, obj = "line", line_from_ir(ir, irs, as_3d=as_3d)
        elif t in ("segment", "segment3d"):
            kind, obj = "segment", line_from_ir(ir, irs, as_3d=as_3d)
        elif t in ("ray", "ray3d"):
            kind, obj = "ray", line_from_ir(ir, irs, as_3d=as_3d)
        elif t == "plane3d":
            kind, obj = "plane", plane_from_ir(ir)
        elif t == "conic":
            obj = conic_from_ir(ir); kind = "circle" if isinstance(obj, SympyCircle) else "conic"
        elif t in ("conic3d", "conic3dpart"):
            obj = circle3d_from_command(ir, irs); kind = "circle" if obj is not None else "conic"
        elif t in ("quadric", "quadriclimited", "quadricpart"):
            obj = quadric_from_ir(ir); kind = "sphere" if isinstance(obj, Sphere) else "quadric"
        elif t in ("vector", "vector3d"):
            kind, obj = "vector", vector_from_ir(ir, irs, as_3d)
        elif t in ("polygon", "polygon3d"):
            kind, obj = "polygon", polygon_from_ir(ir, irs, as_3d)
        elif t in ("numeric", "angle"):
            kind, obj = "numeric", (_num(ir.value) if ir.value is not None else None)
        elif t == "text":
            kind, obj = "text", ir.expression
        elif t == "list":
            kind, obj = "list", None
    except Exception:
        obj = None
    return Object3D(kind=kind, obj=obj, value=None, command=cmd)


def objects_from_xml(xml: str, as_3d: Optional[bool] = None) -> Dict[str, Object3D]:
    from .utils import is_applet_3d_from_xml
    irs = element_irs(xml)
    if as_3d is None:
        flag = is_applet_3d_from_xml(xml)
        as_3d = bool(flag) if flag is not None else any(ir.type.endswith("3d") or ir.type.startswith("quadric") for ir in irs.values())
    return {lab: object_from_ir(ir, irs, as_3d=as_3d) for lab, ir in irs.items()}


def attach_object3d_ir(df: pl.DataFrame, xml: str, out_col: str = "object3d", as_3d: Optional[bool] = None) -> pl.DataFrame:
    """v1 `attach_object3d(df)` without value strings: the objects come from the XML the DataFrame was built from."""
    objs = objects_from_xml(xml, as_3d=as_3d)
    col = [objs.get(n) for n in df["Name"].to_list()]
    return df.with_columns([pl.Series(out_col, col, dtype=pl.Object)])


def enumerate_plane_members_ir(df: pl.DataFrame, xml: str, out_col: str = "plane_members", tol: float = 1e-2) -> pl.DataFrame:
    """v1 `enumerate_plane_members(df)` on the XML's numbers: for every plane3d row, the labels of the points, segments,
    circles and lines lying on it (v1's predicates `_check_*_on_plane`, unchanged; spheres are not members)."""
    objs = objects_from_xml(xml, as_3d=True)
    names = df["Name"].to_list()
    members_list = []
    for n in names:
        o = objs.get(n)
        if o is None or o.kind != "plane" or o.obj is None:
            members_list.append([]); continue
        plane = o.obj; members = []
        for m in names:
            if m == n:
                continue
            oj = objs.get(m)
            if oj is None or oj.obj is None:
                continue
            if _check_point_on_plane(oj, plane, tol=tol) or _check_segment_on_plane(oj, plane, tol=tol) \
                    or _check_circle_on_plane(oj, plane) or _check_line_on_plane(oj, plane, tol=tol):
                members.append(m)
        members_list.append(members)
    return df.with_columns([pl.Series(out_col, members_list, dtype=pl.List(pl.Utf8))])


__all__ = ["Sphere", "Vector", "point_from_ir", "line_from_ir", "plane_from_ir", "conic_from_ir", "quadric_from_ir",
           "circle3d_from_command", "polygon_from_ir", "vector_from_ir", "object_from_ir", "objects_from_xml",
           "attach_object3d_ir", "enumerate_plane_members_ir"]
