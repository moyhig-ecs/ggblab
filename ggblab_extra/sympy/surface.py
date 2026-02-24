"""Parametric surface helpers for 3D parametric surfaces.

Provides a lightweight parser that recognizes GeoGebra `Surface(...)`
command strings and simple `name:(x(u,v), y(u,v), z(u,v))` value forms.
When SymPy is available the parser will attempt to construct a SymPy
surface object; otherwise a simple `ParametricSurface` wrapper is
returned.
"""
from dataclasses import dataclass
from typing import Any, Optional
import re

from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy import symbols, sin, cos, tan, sqrt, pi, E
from sympy.core.sympify import SympifyError

_transformations = standard_transformations + (implicit_multiplication_application,)


@dataclass
class ParametricSurface:
    x: Any
    y: Any
    z: Any
    u: Any
    v: Any
    u_start: Optional[Any] = None
    u_end: Optional[Any] = None
    v_start: Optional[Any] = None
    v_end: Optional[Any] = None
    sympy: Optional[Any] = None

    def __repr__(self) -> str:  # pragma: no cover - formatting
        return (
            f"ParametricSurface(x={self.x!r}, y={self.y!r}, z={self.z!r}, u={self.u!r}, v={self.v!r},"
            f" u_range=({self.u_start!r},{self.u_end!r}), v_range=({self.v_start!r},{self.v_end!r}))"
        )


def _split_top_level_commas(s: str):
    parts = []
    depth = 0
    cur = []
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur).strip())
    return parts


def surface_from_value(val: str) -> ParametricSurface:
    """Parse a GeoGebra `Surface(...)` or value like `s:(x(u,v), y(u,v), z(u,v))`.

    Returns a `ParametricSurface`. Attempts to construct a SymPy surface when
    possible; otherwise returns a lightweight wrapper with parsed expressions.
    """
    if val is None:
        raise ValueError("empty value")
    s = val
    # value-like: name:(x(u,v), y(u,v), z(u,v))
    if ':' in s and not s.strip().lower().startswith('surface'):
        try:
            _, rest = s.split(':', 1)
            rest = rest.strip()
            if rest.startswith('(') and rest.endswith(')'):
                inner = rest[1:-1]
                parts = _split_top_level_commas(inner)
                if len(parts) >= 3:
                    x_s, y_s, z_s = parts[0], parts[1], parts[2]
                    u_sym, v_sym = symbols('u v')
                    x_expr = parse_expr(x_s, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': u_sym, 'u': u_sym, 'v': v_sym})
                    y_expr = parse_expr(y_s, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': u_sym, 'u': u_sym, 'v': v_sym})
                    z_expr = parse_expr(z_s, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': u_sym, 'u': u_sym, 'v': v_sym})
                    return ParametricSurface(x=x_expr, y=y_expr, z=z_expr, u=u_sym, v=v_sym)
        except (ValueError, SympifyError, IndexError):
            pass

    m = re.search(r"Surface\s*\((.*)\)", s, re.I)
    if m:
        inner = m.group(1)
        parts = _split_top_level_commas(inner)
        # Expected forms:
        # Surface(x(u,v), y(u,v), z(u,v), u, u0, u1, v, v0, v1)
        if len(parts) >= 3:
            x_s, y_s, z_s = parts[0], parts[1], parts[2]
            # default param names
            u_name = 'u'
            v_name = 'v'
            u0 = u1 = v0 = v1 = None
            try:
                if len(parts) >= 4:
                    u_name = parts[3]
                if len(parts) >= 6:
                    u0 = parts[4]
                    u1 = parts[5]
                if len(parts) >= 9:
                    v_name = parts[6]
                    v0 = parts[7]
                    v1 = parts[8]
            except Exception:
                pass
            try:
                u_sym = symbols(str(u_name).strip())
                v_sym = symbols(str(v_name).strip())
                local = {'sin': sin, 'cos': cos, 'tan': tan, 'sqrt': sqrt, 'pi': pi, 'E': E}
                local[str(u_sym)] = u_sym
                local[str(v_sym)] = v_sym
                local['u'] = u_sym
                local['v'] = v_sym
                x_expr = parse_expr(x_s, transformations=_transformations, local_dict=local)
                y_expr = parse_expr(y_s, transformations=_transformations, local_dict=local)
                z_expr = parse_expr(z_s, transformations=_transformations, local_dict=local)
                u0_expr = parse_expr(u0, transformations=_transformations, local_dict=local) if u0 is not None else None
                u1_expr = parse_expr(u1, transformations=_transformations, local_dict=local) if u1 is not None else None
                v0_expr = parse_expr(v0, transformations=_transformations, local_dict=local) if v0 is not None else None
                v1_expr = parse_expr(v1, transformations=_transformations, local_dict=local) if v1 is not None else None
            except (SympifyError, TypeError, ValueError):
                raise ValueError(f"could not parse surface expression: {val!r}")

            # Try to build a SymPy surface if available
            try:
                try:
                    from sympy.geometry.surface import Surface as SympySurface
                except Exception:
                    try:
                        from sympy.geometry import Surface as SympySurface
                    except Exception:
                        SympySurface = None
                if SympySurface is not None:
                    try:
                        # SymPy surface constructors vary; try a reasonable signature
                        sym = SympySurface((x_expr, y_expr, z_expr), (u_sym, v_sym))
                        return ParametricSurface(x=x_expr, y=y_expr, z=z_expr, u=u_sym, v=v_sym, u_start=u0_expr, u_end=u1_expr, v_start=v0_expr, v_end=v1_expr, sympy=sym)
                    except Exception:
                        pass
            except Exception:
                pass

            return ParametricSurface(x=x_expr, y=y_expr, z=z_expr, u=u_sym, v=v_sym, u_start=u0_expr, u_end=u1_expr, v_start=v0_expr, v_end=v1_expr)

    raise ValueError(f"not a recognized surface value: {val!r}")


__all__ = ["ParametricSurface", "surface_from_value"]
