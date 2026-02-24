"""Parametric curve helpers for 2D Cartesian curves.

Provides a lightweight parser that recognizes GeoGebra `Curve(...)`
command strings and simple `name:(x(u), y(u))` value forms. When SymPy
is available the parser will attempt to construct a SymPy curve object;
otherwise a simple `ParametricCurve` wrapper is returned.
"""
from dataclasses import dataclass
from typing import Any, Optional, Tuple
import re

from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy import symbols, sin, cos, pi, E, tan, sqrt
from sympy.core.sympify import SympifyError

_transformations = standard_transformations + (implicit_multiplication_application,)


@dataclass
class ParametricCurve:
    x: Any
    y: Any
    var: Any
    start: Optional[Any] = None
    end: Optional[Any] = None
    sympy: Optional[Any] = None

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        return f"ParametricCurve(x={self.x!r}, y={self.y!r}, var={self.var!r}, start={self.start!r}, end={self.end!r})"


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


def curve_from_value(val: str) -> ParametricCurve:
    """Parse a GeoGebra `Curve(...)` or value like `a:(x(u), y(u))`.

    Returns a `ParametricCurve`. Attempts to construct a SymPy curve when
    possible; otherwise returns a lightweight wrapper with parsed
    expressions.
    """
    if val is None:
        raise ValueError("empty value")
    s = val
    if ':' in s and not s.strip().lower().startswith('curve'):
        # value form: "name:(expr, expr)"
        try:
            _, rest = s.split(':', 1)
            rest = rest.strip()
            if rest.startswith('(') and rest.endswith(')'):
                inner = rest[1:-1]
                parts = _split_top_level_commas(inner)
                if len(parts) >= 2:
                    x_s, y_s = parts[0], parts[1]
                    # no range provided
                    var_sym = symbols('t')
                    x_expr = parse_expr(x_s, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': var_sym})
                    y_expr = parse_expr(y_s, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': var_sym})
                    return ParametricCurve(x=x_expr, y=y_expr, var=var_sym)
        except (ValueError, SympifyError, IndexError):
            pass

    # command-like form: Curve(xexpr, yexpr, var, start, end)
    m = re.search(r"Curve\s*\((.*)\)", s, re.I)
    if m:
        inner = m.group(1)
        parts = _split_top_level_commas(inner)
        if len(parts) >= 2:
            x_s = parts[0]
            y_s = parts[1]
            var_name = 't'
            start_expr = None
            end_expr = None
            if len(parts) >= 3:
                var_name = parts[2]
            if len(parts) >= 4:
                start_expr = parts[3]
            if len(parts) >= 5:
                end_expr = parts[4]
            try:
                var_sym = symbols(str(var_name).strip())
                local = {'sin': sin, 'cos': cos, str(var_sym): var_sym}
                # also provide 't' alias
                local['t'] = var_sym
                x_expr = parse_expr(x_s, transformations=_transformations, local_dict=local)
                y_expr = parse_expr(y_s, transformations=_transformations, local_dict=local)
                start = parse_expr(start_expr, transformations=_transformations, local_dict=local) if start_expr is not None else None
                end = parse_expr(end_expr, transformations=_transformations, local_dict=local) if end_expr is not None else None
            except (SympifyError, TypeError, ValueError):
                raise ValueError(f"could not parse curve expression: {val!r}")

            # Try to construct a SymPy Curve if available (best-effort)
            try:
                try:
                    from sympy.geometry.curve import Curve as SympyCurve
                except Exception:
                    try:
                        from sympy.geometry import Curve as SympyCurve
                    except Exception:
                        SympyCurve = None
                if SympyCurve is not None:
                    # Build a rich local_dict for parsing/evaluation
                    local = {"sin": sin, "cos": cos, "tan": tan, "sqrt": sqrt, "pi": pi, "E": E}
                    local[str(var_sym)] = var_sym
                    local["t"] = var_sym
                    # Ensure start/end are SymPy expressions when present
                    s_expr = start
                    e_expr = end
                    try:
                        if start is not None:
                            s_expr = parse_expr(str(start), transformations=_transformations, local_dict=local)
                        if end is not None:
                            e_expr = parse_expr(str(end), transformations=_transformations, local_dict=local)
                    except Exception:
                        s_expr = start
                        e_expr = end

                    try:
                        if s_expr is not None and e_expr is not None:
                            sym = SympyCurve((x_expr, y_expr), (var_sym, s_expr, e_expr))
                        else:
                            # Some SymPy versions accept (exprs, param) signature
                            try:
                                sym = SympyCurve((x_expr, y_expr), var_sym)
                            except Exception:
                                sym = SympyCurve((x_expr, y_expr))
                        return ParametricCurve(x=x_expr, y=y_expr, var=var_sym, start=start, end=end, sympy=sym)
                    except Exception:
                        # Fall through to wrapper if construction fails
                        pass
            except Exception:
                pass

            return ParametricCurve(x=x_expr, y=y_expr, var=var_sym, start=start, end=end)

    raise ValueError(f"not a recognized curve value: {val!r}")


__all__ = ["ParametricCurve", "curve_from_value"]
