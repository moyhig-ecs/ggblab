"""SymPy-related utilities for parsing GeoGebra Value strings.

This module lives under the optional `ggblab_extra` package and contains
SymPy-dependent helpers for converting GeoGebra "Value" strings into
SymPy geometry objects (Point3D, Plane, parametric circles, lines,
segments) and some small DataFrame convenience functions.

Keep this module optional to avoid forcing SymPy onto minimal users.

Notes and limitations:
- This module is pragmatic and aims to interoperate with GeoGebra's
    exported `Value`/`Command` strings; it is not a complete formal
    geometry library. Some predicates and conversions are best-effort.
- SymPy APIs vary across versions; the code attempts graceful fallbacks
    (e.g. Line3D import/representation) but behavior may differ by
    SymPy release. Tests should be run in the target environment.
- `line_from_value`, `circle_from_value`, `segment_from_command`,
    `attach_object3d`, and `enumerate_plane_members` are pragmatic helpers
    and may return lightweight placeholders when full symbolic objects
    cannot be constructed (e.g. unresolved segment endpoints).
- For educational extracts: annotate examples and explain fallbacks and
    limitations before reuse in teaching materials.
"""

import math
import re
from dataclasses import dataclass
from typing import Optional, Union

from sympy import Matrix, cos, sin, sqrt, symbols
from sympy.geometry import Plane as SympyPlane, Point3D as SympyPoint3D
try:
    from sympy.geometry.line3d import Line3D as SympyLine3D
except Exception:
    try:
        from sympy.geometry import Line3D as SympyLine3D
    except Exception:
        SympyLine3D = None
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

# Parser transformations and time symbol
_t = symbols("t")
_transformations = standard_transformations + (implicit_multiplication_application,)


def _parse_vec_str(vec_str: str):
    parts = [p.strip() for p in vec_str.split(",")]
    if len(parts) != 3:
        raise ValueError("expected three components in vector part")
    exprs = []
    for p in parts:
        if p == "" or p == "0":
            exprs.append(
                parse_expr(
                    "0",
                    transformations=_transformations,
                    local_dict={"sin": sin, "cos": cos, "t": _t},
                )
            )
        else:
            exprs.append(
                parse_expr(
                    p,
                    transformations=_transformations,
                    local_dict={"sin": sin, "cos": cos, "t": _t},
                )
            )
    return exprs


_LINE_RE = re.compile(r"^\s*([^:]+)\s*:\s*X\s*=\s*\((.*?)\)\s*\+\s*\((.*?)\)\s*$", re.I)


def parse_line(line: str):
    m = _LINE_RE.match(line)
    if not m:
        raise ValueError(f"line does not match expected pattern: {line!r}")
    label = m.group(1).strip()
    center_str = m.group(2).strip()
    vec_str = m.group(3).strip()
    center_parts = [c.strip() for c in center_str.split(",")]
    if len(center_parts) != 3:
        raise ValueError("expected three center components")
    center_exprs = [
        parse_expr(
            p if p else "0",
            transformations=_transformations,
            local_dict={"sin": sin, "cos": cos, "t": _t},
        )
        for p in center_parts
    ]
    vec_exprs = _parse_vec_str(vec_str)
    return label, center_exprs, vec_exprs


def compute_axis(vec_exprs):
    cos_coeffs = [expr.expand().coeff(cos(_t), 1) for expr in vec_exprs]
    sin_coeffs = [expr.expand().coeff(sin(_t), 1) for expr in vec_exprs]
    A = Matrix(cos_coeffs)
    B = Matrix(sin_coeffs)
    n = A.cross(B)
    n_simpl = Matrix([ni.simplify() for ni in n])
    norm_val = (
        float(sqrt(sum([float((ni**2).evalf()) for ni in n_simpl])))
        if any([ni != 0 for ni in n_simpl])
        else 0.0
    )
    unit = (
        (n_simpl / norm_val).applyfunc(lambda x: x.evalf())
        if norm_val != 0
        else n_simpl
    )
    return n_simpl, unit


def compute_axis_from_line(line: str):
    label, center, vec = parse_line(line)
    return label, compute_axis(vec)


@dataclass
class Circle3D:
    center: SympyPoint3D
    normal: Matrix
    radius: object
    axis_cos: Matrix
    axis_sin: Matrix

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"Circle3D(center={self.center}, radius={self.radius}, normal={tuple(self.normal)})"


def circle_from_value(value_str: str):
    label, center_exprs, vec_exprs = parse_line(value_str)
    if not any(expr.has(sin(_t)) or expr.has(cos(_t)) for expr in vec_exprs):
        raise ValueError("not a parametric trig circle")
    cos_coeffs = [expr.expand().coeff(cos(_t), 1) for expr in vec_exprs]
    sin_coeffs = [expr.expand().coeff(sin(_t), 1) for expr in vec_exprs]
    A = Matrix(cos_coeffs)
    B = Matrix(sin_coeffs)
    normal = A.cross(B)
    normal_simpl = Matrix([ni.simplify() for ni in normal])
    rA = sqrt(sum([ci**2 for ci in A]))
    rB = sqrt(sum([ci**2 for ci in B]))
    radius = (rA + rB) / 2
    center = SympyPoint3D(*center_exprs)
    return Circle3D(
        center=center, normal=normal_simpl, radius=radius, axis_cos=A, axis_sin=B
    )


def point_from_value(value_str: str) -> SympyPoint3D:
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    m = re.search(r"=\s*\(([^,]+),([^,]+),([^\)]+)\)", s)
    if not m:
        m2 = re.search(r"\(([^,]+),([^,]+),([^\)]+)\)", s)
        if not m2:
            raise ValueError(f"not a point value: {value_str!r}")
        m = m2
    comps = [c.strip() for c in m.groups()]
    exprs = [
        parse_expr(
            c,
            transformations=_transformations,
            local_dict={"sin": sin, "cos": cos, "t": _t},
        )
        for c in comps
    ]
    return SympyPoint3D(*exprs)


def plane_from_value(value_str: str) -> SympyPlane:
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
        pt = SympyPoint3D(d / a, 0, 0)
    elif b != 0:
        pt = SympyPoint3D(0, d / b, 0)
    else:
        pt = SympyPoint3D(0, 0, d / c)
    return SympyPlane(pt, normal)


def attach_planes(df, value_col="Value", out_col="sym_plane"):
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_planes requires a polars DataFrame")

    vals = df[value_col].to_list()
    planes = [plane_from_value(v) for v in vals]
    normals = [p.normal_vector for p in planes]
    return df.with_columns([pl.Series(out_col, planes), pl.Series(out_col + "_normal", normals)])


def value_to_sympy(value_str: str):
    try:
        return point_from_value(value_str)
    except Exception:
        pass
    try:
        return circle_from_value(value_str)
    except Exception:
        pass
    try:
        return plane_from_value(value_str)
    except Exception:
        pass
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    x, y, z = symbols("x y z")
    if "=" in s:
        lhs_str, rhs_str = s.split("=", 1)
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
        return lhs - rhs
    return parse_expr(
        s, transformations=_transformations, local_dict={"x": x, "y": y, "z": z}
    )


def attach_sympy(df, value_col="Value", sym_col="sympy"):
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_sympy requires a polars DataFrame")

    vals = df[value_col].to_list()
    syms = [value_to_sympy(v) for v in vals]
    return df.with_columns([pl.Series(sym_col, syms)])


@dataclass
class ValueObject:
    kind: str
    obj: object
    raw: str

    def is_point(self) -> bool:
        return self.kind == "point"

    def is_circle(self) -> bool:
        return self.kind == "circle"

    def is_plane(self) -> bool:
        return self.kind == "plane"

    def is_line(self) -> bool:
        return self.kind == "line"

    def is_segment(self) -> bool:
        return self.kind == "segment"


@dataclass
class CommandObject:
    """Parsed representation of a GeoGebra command string.

    Minimal container for symmetry with `ValueObject`. Currently supports
    `segment` commands parsed via `segment_from_command` (returns the
    Segment container defined elsewhere in this module).
    """

    kind: Optional[str]
    obj: object | None
    raw: str


def parse_command(command_str: str) -> CommandObject:
    """Parse a GeoGebra `Command` string into a CommandObject.

    Currently recognizes `Segment(...)` commands and returns a
    `CommandObject(kind='segment', obj=Segment(...), raw=command_str)`.
    Unknown or unparsed commands return `CommandObject(None, None, raw)`.
    """
    if not command_str:
        return CommandObject(None, None, command_str)
    try:
        # Try known command parsers; start with Segment
        seg = segment_from_command(command_str)
        return CommandObject("segment", seg, command_str)
    except Exception:
        # Unknown/unsupported command
        return CommandObject(None, None, command_str)


@dataclass
class Object3D:
    """Unified container for 3D construction objects.

    Holds an optional `value` string (GeoGebra Value), an optional
    `command` string (GeoGebra command), and the resolved object when
    possible. The resolver will attempt to create a SymPy-based object
    from `value` and/or `command`. Some objects cannot be fully
    resolved from the value alone (e.g. a `Segment` specified only by
    endpoint labels), so `obj` may be a lightweight container with
    unresolved labels.
    """

    kind: str | None = None
    obj: object | None = None
    value: str | None = None
    command: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - formatting
        return f"Object3D(kind={self.kind!r}, obj={self.obj!r}, value={self.value!r}, command={self.command!r})"

    @classmethod
    def from_value_command(cls, value: str | None = None, command: str | None = None):
        """Build an Object3D from optional `value` and `command` strings.

        Resolution rules (simple heuristic):
        - If `command` looks like a `Segment(...)` command, parse it and
            return an 'segment' Object3D with endpoint labels stored in the
            `Segment` container (labels unresolved).
        - Otherwise, if `value` is present, call `parse_value(value)` and
            use its result.
        - If both are present, prefer `command` for labeled constructions
            (endpoints) and use `value` as fallback for numeric definitions.
        """
        # Prefer command when it explicitly names endpoints (Segment(A,B))
        if command:
            try:
                cmd = parse_command(command)
                if cmd.kind == "segment":
                    return cls(kind="segment", obj=cmd.obj, value=value, command=command)
                # other command kinds may be handled here in future
            except Exception:
                # not a recognized command; fall through to value-based parsing
                pass

        if value:
            vo = parse_value(value)
            return cls(kind=vo.kind, obj=vo.obj, value=value, command=command)

        # nothing to resolve
        return cls(kind=None, obj=None, value=value, command=command)


def parse_value(value_str: str) -> ValueObject:
    s = value_str if value_str is not None else ""
    try:
        c = circle_from_value(s)
        return ValueObject("circle", c, s)
    except Exception:
        pass
    try:
        l = line_from_value(s)
        return ValueObject("line", l, s)
    except Exception:
        pass
    try:
        p = point_from_value(s)
        return ValueObject("point", p, s)
    except Exception:
        pass
    try:
        if ":" not in s:
            mnum = re.search(r"=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", s)
            if mnum and re.match(r"^\w+\s*=\s*[-+]?\d", s):
                try:
                    val = float(mnum.group(1))
                    return ValueObject("segment", Segment(length=val), s)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        pl = plane_from_value(s)
        return ValueObject("plane", pl, s)
    except Exception:
        pass
    try:
        x, y, z = symbols("x y z")
        if ":" in s:
            _, s2 = s.split(":", 1)
        else:
            s2 = s
        s2 = s2.strip()
        if "=" in s2:
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
            if (
                isinstance(lhs, tuple)
                or getattr(lhs, "is_Tuple", False)
                or isinstance(rhs, tuple)
                or getattr(rhs, "is_Tuple", False)
            ):
                    try:
                        p = point_from_value(value_str)
                        return ValueObject("point", p, value_str)
                    except Exception:
                        raise
            expr = lhs - rhs
            try:
                aa = expr.coeff(x, 1)
                bb = expr.coeff(y, 1)
                cc = expr.coeff(z, 1)
                const = expr.subs({x: 0, y: 0, z: 0})
                if not (aa == 0 and bb == 0 and cc == 0):
                    dd = -const
                    normal = (aa, bb, cc)
                    if aa != 0:
                        pt = SympyPoint3D(dd / aa, 0, 0)
                    elif bb != 0:
                        pt = SympyPoint3D(0, dd / bb, 0)
                    else:
                        pt = SympyPoint3D(0, 0, dd / cc)
                    return ValueObject("plane", SympyPlane(pt, normal), value_str)
            except Exception:
                pass
        else:
            expr = parse_expr(
                s2,
                transformations=_transformations,
                local_dict={"x": x, "y": y, "z": z},
            )
        return ValueObject("expr", expr, value_str)
    except Exception:
        return ValueObject("raw", value_str, value_str)



def attach_object3d(
    df, type_col="Type", command_col="Command", value_col="Value", out_col="object3d"
):
    """Attach an `Object3D` for each row using `Type`, `Command`, and `Value`.

    - For polars DataFrame: uses column lists and returns a new DataFrame with
      a `out_col` column of `Object3D` instances.
    - For pandas-like DataFrame: applies row-wise using `apply(axis=1)`.
    """
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_object3d requires a polars DataFrame")

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            o = Object3D.from_value_command(
                value=v if v is not None else None, command=c if c is not None else None
            )
        except Exception:
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append(o)
    try:
        s = pl.Series(out_col, objs, dtype=getattr(pl, "Object"))
    except Exception:
        s = pl.Series(out_col, objs)
    return df.with_columns([s])


def enumerate_plane_members(
    df,
    type_col="Type",
    name_col="Name",
    command_col="Command",
    value_col="Value",
    out_col="plane_members",
):
    """For rows where `Type` == 'plane', list names of objects that lie on that plane.

    - `segment` endpoints referenced by label are resolved using the `Name` column.
    - Returns the original DataFrame with a new column `out_col` containing a
      semicolon-separated string of member names for each plane row (empty string otherwise).
    """
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("enumerate_plane_members requires a polars DataFrame")

    # Use module-level predicates (`point_on_plane`, `segment_on_plane`,
    # `line_on_plane`, `circle_on_plane`) to determine membership. The
    # global `segment_on_plane` will resolve labeled endpoints using the
    # provided `df` when necessary.

    members_list = []

    # precompute Object3D for each row to simplify checks
    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    names = df[name_col].to_list()

    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            o = Object3D.from_value_command(value=v if v is not None else None, command=c if c is not None else None)
        except Exception:
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append((t, o))

    # For each plane row, collect member names
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
                # points
                if oj.kind == "point" and isinstance(oj.obj, SympyPoint3D):
                    if point_on_plane(oj.obj, plane):
                        members.append(name_j)
                        continue
                # segments: delegate resolution + test to global helper
                if oj.kind == "segment" and isinstance(oj.obj, Segment):
                    try:
                        if segment_on_plane(oj.obj, plane, df=df, name_col=name_col, value_col=value_col, obj_col="object3d", tol=1e-2):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
                # circles
                if oj.kind == "circle":
                    try:
                        if circle_on_plane(oj.obj, plane):
                            members.append(name_j)
                            continue
                    except Exception:
                        pass
                # lines
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

    # attach results as a List column
    try:
        list_type = getattr(pl, "List")(getattr(pl, "Utf8"))
        s = pl.Series(out_col, members_list, dtype=list_type)
    except Exception:
        try:
            s = pl.Series(out_col, members_list)
        except Exception:
            s = pl.Series(out_col, [[str(x) for x in m] for m in members_list])
    return df.with_columns([s])


@dataclass
class SimpleLine3D:
    point: SympyPoint3D
    direction: Matrix

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"SimpleLine3D(point={self.point}, direction={tuple(self.direction)})"


def to_sympy_line(simple: SimpleLine3D) -> object:
    """Convert a `SimpleLine3D` (point + direction) to SymPy's Line3D.

    Constructs a second point as P + d and returns SympyLine3D(P, P+d).
    """
    p = simple.point
    d = simple.direction
    # If SympyLine3D is not available in this SymPy build, return the simple object
    if SympyLine3D is None:
        return simple
    try:
        p2 = SympyPoint3D(*(p[i] + d[i] for i in range(3)))
    except Exception:
        # Fallback using named attributes
        p2 = SympyPoint3D(p.x + d[0], p.y + d[1], p.z + d[2])
    return SympyLine3D(p, p2)


@dataclass
class Segment:
    p1: Union[SympyPoint3D, str, None] = None
    p2: Union[SympyPoint3D, str, None] = None
    length: Optional[float] = None
    parent: Optional[str] = None

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        if self.p1 is not None and self.p2 is not None:
            return f"Segment(p1={self.p1}, p2={self.p2})"
        return f"Segment(length={self.length})"


def line_from_value(value_str: str) -> object:
    if ":" in value_str:
        _, s = value_str.split(":", 1)
    else:
        s = value_str
    s = s.strip()
    m = re.search(r"=\s*\(([^\)]+)\)\s*\+\s*(?:λ\s*)?\(([^\)]+)\)", s)
    if not m:
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
    # Build point and direction
    P = SympyPoint3D(*exprs_c)
    D = Matrix(exprs_d)
    P2 = SympyPoint3D(*(exprs_c[i] + exprs_d[i] for i in range(3)))
    if SympyLine3D is None:
        # Fall back to a simple local representation when SymPy's Line3D isn't available
        return SimpleLine3D(point=P, direction=D)
    return SympyLine3D(P, P2)


def segment_from_command(command_str: str) -> Segment:
    if command_str is None:
        raise ValueError("empty command")
    s = command_str.strip()
    # Accept Segment(A,B) or Segment(A,B,Polygon) where the third arg is optional
    m = re.search(r"Segment\s*\(\s*([^,]+?)\s*,\s*([^,\)]+?)(?:\s*,\s*([^\)]+))?\s*\)", s)
    if not m:
        raise ValueError(f"not a Segment command: {command_str!r}")
    a = m.group(1).strip()
    b = m.group(2).strip()
    c = m.group(3).strip() if m.group(3) is not None else None
    return Segment(p1=a, p2=b, parent=c)


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
    # print(f"Debug: distance from point {point} to plane {plane} is {d}")
    return d <= tol


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


def valueobject_on_plane(vo: ValueObject, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    if vo is None or plane is None:
        return False
    try:
        if vo.is_point():
            return point_on_plane(vo.obj, plane, tol=tol)
        if vo.is_circle():
            return circle_on_plane(vo.obj, plane, dist_tol=tol, angle_tol=angle_tol)
        if vo.is_line():
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
        if vo.is_segment():
            seg = vo.obj
            p1 = getattr(seg, "p1", None)
            p2 = getattr(seg, "p2", None)
            if p1 is None or p2 is None:
                return False
            return point_on_plane(p1, plane, tol=tol) and point_on_plane(
                p2, plane, tol=tol
            )
        if vo.is_plane():
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


def segment_on_plane(
    seg: Segment,
    plane,
    df=None,
    name_col: str = "Name",
    value_col: str = "Value",
    obj_col: str = "object3d",
    tol: float = 1e-2,
) -> bool:
    """Return True when both segment endpoints lie on the plane.

    Resolution rules:
    - If `seg.p1`/`seg.p2` are SymPy Point3D, test directly.
    - If they are labels (strings), `df` is used to locate the row with
      `Name == label`. The function first attempts to read `obj_col` from
      that row (expected to be an `Object3D` or SymPy Point). If missing
      it falls back to parsing `value_col` with `point_from_value`.
    - Supports both pandas-like DataFrames and polars DataFrames.
    """
    if seg is None or plane is None:
        return False

    p1 = getattr(seg, "p1", None)
    p2 = getattr(seg, "p2", None)
    if p1 is None or p2 is None:
        return False

    # If endpoints are labels (strings) we require a valid DataFrame to
    # resolve them; raise an error if none provided or if the DataFrame
    # does not contain the expected name column.
    if (isinstance(p1, str) or isinstance(p2, str)):
        if df is None:
            raise ValueError("df is required to resolve labeled segment endpoints")
        try:
            cols = getattr(df, "columns")
            if name_col not in cols:
                raise ValueError(f"df must contain '{name_col}' column to resolve labels")
        except Exception:
            # If df doesn't expose columns in a standard way, still proceed
            # and let resolution attempts raise a clearer error later.
            pass

    def _resolve_label(label):
        # already a sympy point
        if isinstance(label, SympyPoint3D):
            return label
        if not isinstance(label, str):
            return None
        if df is None:
            return None

        # Assume polars-like DataFrame; prefer `obj_col` then `value_col`.
        try:
            matches = df.filter(df[name_col] == label)
            if len(matches) == 0:
                return None
            # try object column first
            try:
                obj = matches[obj_col][0]
                resolved = getattr(obj, "obj", obj) if obj is not None else None
                if isinstance(resolved, SympyPoint3D):
                    return resolved
            except Exception:
                pass
            # fall back to parsing the Value column
            try:
                return point_from_value(matches[value_col][0])
            except Exception:
                return None
        except Exception:
            return None

    rp1 = p1 if isinstance(p1, SympyPoint3D) else _resolve_label(p1)
    rp2 = p2 if isinstance(p2, SympyPoint3D) else _resolve_label(p2)
    if not isinstance(rp1, SympyPoint3D) or not isinstance(rp2, SympyPoint3D):
        return False
    return point_on_plane(rp1, plane, tol=tol) and point_on_plane(rp2, plane, tol=tol)


def line_on_plane(line_obj, plane, tol=1e-2, angle_tol=1e-1) -> bool:
    """Return True when a line lies on `plane`.

    Criteria:
    - line direction is orthogonal to plane normal (angle ~ 90 degrees)
    - at least one point on the line lies on the plane (within `tol`)

    Accepts either SymPy Line3D, `SimpleLine3D` (point+direction), or
    objects with `point` and `direction` attributes.
    """
    if line_obj is None or plane is None:
        return False
    try:
        # obtain a point P and direction D for the line
        if hasattr(line_obj, "point") and hasattr(line_obj, "direction"):
            P = getattr(line_obj, "point")
            D = getattr(line_obj, "direction")
        elif SympyLine3D is not None and isinstance(line_obj, SympyLine3D):
            p1 = line_obj.p1
            p2 = line_obj.p2
            P = p1
            D = Matrix([p2[i] - p1[i] for i in range(3)])
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
        # direction should be perpendicular to plane normal
        if abs(ang - math.pi / 2) > angle_tol:
            return False
        # check a point on the line lies on the plane
        return point_on_plane(P, plane, tol=tol)
    except Exception:
        return False

__all__ = [
    "parse_line",
    "compute_axis",
    "compute_axis_from_line",
    "Circle3D",
    "circle_from_value",
    "point_from_value",
    "plane_from_value",
    "attach_planes",
    "value_to_sympy",
    "attach_sympy",
    "ValueObject",
    "parse_value",
    "Segment",
    "line_from_value",
    "segment_from_command",
    "point_on_plane",
    "segment_on_plane",
    "line_on_plane",
    "circle_on_plane",
    "valueobject_on_plane",
    "Object3D",
]
