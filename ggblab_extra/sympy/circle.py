"""Circle helpers (moved into sympy subpackage).

This module contains lightweight parsers that try to produce SymPy circle
objects when SymPy is available, otherwise they return simple tuples or
lightweight wrappers.
"""

from dataclasses import dataclass
from typing import Any, Optional
import re
import math

from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy import symbols, sin, cos, Matrix, sqrt
from sympy.core.sympify import SympifyError
from sympy.geometry import Point3D as SympyPoint3D

from .point import sympy_point_from_coords, point_from_value

try:
    from sympy.geometry.circle import Circle as SympyCircle
except ImportError:
    try:
        from sympy.geometry import Circle as SympyCircle
    except ImportError:
        SympyCircle = None

_t = symbols("t")
_transformations = standard_transformations + (implicit_multiplication_application,)

try:
    from .utils import expr_from_value
except Exception:
    expr_from_value = None


def _parse_expr(s: str, local: dict = None):
    if expr_from_value is not None:
        return expr_from_value(s, transformations=_transformations, local_dict=local)
    return parse_expr(s, transformations=_transformations, local_dict=local)


@dataclass
class CircleLike:
    obj: Any

    """Wrapper for circle-like objects exposing `.obj` and simple attrs."""

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"Circle({self.obj!r})"

    @property
    def center(self):
        return getattr(self.obj, "center", None)

    @property
    def radius(self):
        return getattr(self.obj, "radius", None)


def sympy_circle_from_center_radius(center, radius, is_3d: Optional[bool] = None):
    if not hasattr(center, "x"):
        center = sympy_point_from_coords(*center, is_3d=False)
    if SympyCircle is None:
        return (center, radius)
    try:
        return SympyCircle(center, radius)
    except (TypeError, ValueError, AttributeError):
        return (center, radius)


@dataclass
class Circle3D:
    center: SympyPoint3D
    normal: Matrix
    radius: object
    axis_cos: Matrix
    axis_sin: Matrix

    """Representation for a 3D circle (parametric axes + normal)."""

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return (
            f"Circle3D(center={self.center}, radius={self.radius}, "
            f"normal={tuple(self.normal)})"
        )


_CIRCLE_CENTER_RAD_RE = re.compile(r"Circle\s*\(\s*([^,\)]+)\s*,\s*([^\)]+)\)", re.I)
_EQUATION_RE = re.compile(r"\(x[-+].*\)\s*=\s*.*")


def circle_from_value(value_str: str):
    """Parse a string `value_str` into a circle-like object.

    Attempts center+radius, cartesian-equation, and parametric forms.
    """
    if value_str is None:
        raise ValueError("empty value")
    s = value_str
    if ":" in s:
        _, s = s.split(":", 1)
    s = s.strip()

    m = _CIRCLE_CENTER_RAD_RE.search(s)
    if m:
        center_part = m.group(1).strip()
        radius_part = m.group(2).strip()
        center = None
        try:
            if center_part.startswith("("):
                comps = [c.strip() for c in center_part.strip("() ").split(",")]
                exprs = [
                    _parse_expr(c, local={"sin": sin, "cos": cos, "t": _t})
                    for c in comps
                ]
                center = sympy_point_from_coords(*exprs, is_3d=False)
            else:
                try:
                    center = point_from_value(center_part)
                except (ValueError, TypeError):
                    comps = [c.strip() for c in center_part.strip("() ").split(",")]
                    center = sympy_point_from_coords(
                        *[_parse_expr(c) for c in comps],
                        is_3d=False,
                    )
        except (ValueError, TypeError, AttributeError, IndexError, SympifyError):
            center = None

        try:
            r_expr = _parse_expr(radius_part, local={"sin": sin, "cos": cos, "t": _t})
        except (ValueError, TypeError, SympifyError, SyntaxError):
            r_expr = None

        if center is not None and r_expr is not None:
            return sympy_circle_from_center_radius(center, r_expr)

    try:
        # Normalize common superscript and caret forms
        eq = s.replace("²", "**2").replace("^2", "**2")

        # Simple canonical form: x**2 + y**2 = R
        simple_match = re.match(
            r"^\s*x\s*\*\*\s*2\s*\+\s*y\s*\*\*\s*2\s*=\s*([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)\s*$",
            eq,
        )
        if simple_match:
            r2 = float(simple_match.group(1))
            if r2 < 0:
                raise ValueError("negative radius squared")
            r = math.sqrt(r2)
            center = sympy_point_from_coords(0, 0, 0)
            return sympy_circle_from_center_radius(center, r)

        # More general expanded form: (x + a)**2 + (y + b)**2 = R
        mx = re.search(r"\(\s*x\s*([+-]\s*[0-9.+eE-]+)\s*\)\s*\*\*2", eq)
        my = re.search(r"\(\s*y\s*([+-]\s*[0-9.+eE-]+)\s*\)\s*\*\*2", eq)
        mr = re.search(r"=\s*([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)", eq)
        if mx and my and mr:
            nx = mx.group(1).replace(" ", "")
            ny = my.group(1).replace(" ", "")
            h = -float(nx)
            k = -float(ny)
            r2 = float(mr.group(1))
            if r2 < 0:
                raise ValueError("negative radius squared")
            r = math.sqrt(r2)
            center = sympy_point_from_coords(h, k, 0)
            return sympy_circle_from_center_radius(center, r)
    except (ValueError, TypeError):
        pass

    try:
        s_low = s
        eq_pos = s_low.find("=")
        if eq_pos != -1:
            def find_matching_paren(text, start_idx):
                depth = 0
                for i in range(start_idx, len(text)):
                    ch = text[i]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                return -1

            first_paren = s_low.find("(", eq_pos)
            if first_paren != -1:
                center_end = find_matching_paren(s_low, first_paren)
                if center_end != -1:
                    center_str = s_low[first_paren + 1 : center_end]
                    plus_pos = s_low.find("+", center_end)
                    if plus_pos != -1:
                        second_paren = s_low.find("(", plus_pos)
                        if second_paren != -1:
                            vec_end = find_matching_paren(s_low, second_paren)
                            if vec_end != -1:
                                vec_str = s_low[second_paren + 1 : vec_end]
                                center_parts = [c.strip() for c in center_str.split(",")]
                                if len(center_parts) not in (2, 3):
                                    raise ValueError("expected 2 or 3 components in center")
                                center_exprs = [
                                    _parse_expr(p, local={"sin": sin, "cos": cos, "t": _t})
                                    for p in center_parts
                                ]
                                vec_parts = [v.strip() for v in vec_str.split(",")]
                                if len(vec_parts) != 3:
                                    raise ValueError("expected three components in parametric part")
                                vec_exprs = [
                                    _parse_expr(v, local={"sin": sin, "cos": cos, "t": _t})
                                    for v in vec_parts
                                ]
                                cos_coeffs = [expr.expand().coeff(cos(_t), 1) for expr in vec_exprs]
                                sin_coeffs = [expr.expand().coeff(sin(_t), 1) for expr in vec_exprs]
                                A = Matrix(cos_coeffs)
                                B = Matrix(sin_coeffs)
                                normal = A.cross(B)
                                normal_simpl = Matrix([ni.simplify() for ni in normal])
                                rA = sqrt(sum(ci**2 for ci in A))
                                rB = sqrt(sum(ci**2 for ci in B))
                                radius = (rA + rB) / 2
                                center = sympy_point_from_coords(*center_exprs, is_3d=True)
                                return Circle3D(
                                    center=center,
                                    normal=normal_simpl,
                                    radius=radius,
                                    axis_cos=A,
                                    axis_sin=B,
                                )
    except (ValueError, TypeError, IndexError, AttributeError, SympifyError):
        pass

    raise ValueError(f"not a recognized circle value: {value_str!r}")


__all__ = ["circle_from_value"]
