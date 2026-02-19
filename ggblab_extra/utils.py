"""Utility helpers for parsing GeoGebra-style parametric circle lines
and computing axis normals (cos/sin coefficient cross product).

Functions:
- parse_line(line): returns (label, center_exprs, vec_exprs)
- compute_axis(vec_exprs): returns (unnormalized_axis, unit_axis)
- compute_axis_from_line(line): convenience wrapper

Uses SymPy's parse_expr with implicit multiplication to accept inputs like
"3 sin(t)" or "0.88 sin(t)".
"""
from sympy import symbols, sin, cos, Matrix, sqrt
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application
import re

# Single global symbol 't'
_t = symbols('t')
_transformations = standard_transformations + (implicit_multiplication_application,)

# regex to match lines like "label: X = (c0,c1,c2) + (u0,u1,u2)"
_LINE_RE = re.compile(r'^\s*([^:]+)\s*:\s*X\s*=\s*\((.*?)\)\s*\+\s*\((.*?)\)\s*$', re.I)

def _parse_vec_str(vec_str):
    """Parse a comma-separated vector component string into SymPy Exprs.

    Accepts GeoGebra-like implicit multiplication (e.g. "3 sin(t)").
    Returns a list of 3 SymPy expressions.
    """
    parts = [p.strip() for p in vec_str.split(',')]
    if len(parts) != 3:
        raise ValueError("expected three components in vector part")
    exprs = []
    for p in parts:
        if p == '' or p == '0':
            exprs.append(parse_expr('0', transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': _t}))
        else:
            exprs.append(parse_expr(p, transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': _t}))
    return exprs


def parse_line(line):
    """Parse a single GeoGebra line into (label, center_exprs, vec_exprs).

    center_exprs is a list of three SymPy expressions (constants typically).
    vec_exprs is a list of three SymPy expressions depending on `t`.
    """
    m = _LINE_RE.match(line)
    if not m:
        raise ValueError(f"line does not match expected pattern: {line!r}")
    label = m.group(1).strip()
    center_str = m.group(2).strip()
    vec_str = m.group(3).strip()
    # parse center components (allow numeric or simple literals)
    center_parts = [c.strip() for c in center_str.split(',')]
    if len(center_parts) != 3:
        raise ValueError("expected three center components")
    center_exprs = [parse_expr(p if p else '0', transformations=_transformations, local_dict={'sin': sin, 'cos': cos, 't': _t}) for p in center_parts]
    vec_exprs = _parse_vec_str(vec_str)
    return label, center_exprs, vec_exprs


def compute_axis(vec_exprs):
    """Compute axis normal (cross product of cos and sin coefficient vectors).

    vec_exprs: list of three SymPy expressions (functions of t)

    Returns: (n, unit_n) where n is unnormalized SymPy Matrix, unit_n is numeric-evaluated unit vector
    """
    # extract cos and sin coefficients for each component
    cos_coeffs = [expr.expand().coeff(cos(_t), 1) for expr in vec_exprs]
    sin_coeffs = [expr.expand().coeff(sin(_t), 1) for expr in vec_exprs]
    A = Matrix(cos_coeffs)
    B = Matrix(sin_coeffs)
    n = A.cross(B)
    n_simpl = Matrix([ni.simplify() for ni in n])
    # numeric unit vector (evalf) to avoid symbolic sqrt complications
    norm_val = float(sqrt(sum([float((ni**2).evalf()) for ni in n_simpl]))) if any([ni != 0 for ni in n_simpl]) else 0.0
    unit = (n_simpl / norm_val).applyfunc(lambda x: x.evalf()) if norm_val != 0 else n_simpl
    return n_simpl, unit


def compute_axis_from_line(line):
    """Convenience: parse a single line and compute its axis normal."""
    label, center, vec = parse_line(line)
    return label, compute_axis(vec)


__all__ = ['parse_line', 'compute_axis', 'compute_axis_from_line']
