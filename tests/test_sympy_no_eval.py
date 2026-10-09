"""A3 (2026-10-08): a string read from a construction document (.ggb / XML `<input>` / a value string) is never run as
Python.  Each payload, if evaluated, creates a marker file under pytest's tmp_path; the test is the marker's absence.
Positive control (recorded before the fix, 2026-10-08): every route below created its marker."""
import zipfile
from pathlib import Path
import pytest

from ggblab_extra import read_ggb
from ggblab_extra.sympy import expr_from_value, plane_from_value, point_from_value
from ggblab_extra.sympy.from_ir import objects_from_xml


def payload(marker: Path) -> str:
    return f"__import__('pathlib').Path('{marker}').touch()"


def cylinder_xml(radius: str) -> str:
    return f'''<geogebra format="5.0"><construction title="" author="" date="">
<element type="point3d" label="A"><coords x="0" y="0" z="0" w="1"/></element>
<element type="point3d" label="B"><coords x="0" y="0" z="1" w="1"/></element>
<command name="Cylinder"><input a0="A" a1="B" a2="{radius}"/><output a0="q" a1="c1" a2="c2"/></command>
<element type="quadriclimited" label="q"></element>
<element type="conic3d" label="c1"></element>
<element type="conic3d" label="c2"></element>
</construction></geogebra>'''


def test_xml_input_is_not_evaluated(tmp_path):
    m = tmp_path / "xml_input"
    o = objects_from_xml(cylinder_xml(payload(m)))
    assert not m.exists() and o["c1"].obj is None


def test_ggb_file_input_is_not_evaluated(tmp_path):
    m = tmp_path / "ggb_file"; g = tmp_path / "crafted.ggb"
    with zipfile.ZipFile(g, "w") as z:
        z.writestr("geogebra.xml", cylinder_xml(payload(m)))
    objects_from_xml(read_ggb(g))
    assert not m.exists()


def test_numeric_radius_still_read():
    c1 = objects_from_xml(cylinder_xml("1.5"))["c1"].obj
    assert c1 is not None and float(c1.radius) == 1.5


def test_symbolic_radius_is_a_sympy_value():
    from sympy import sqrt
    c1 = objects_from_xml(cylinder_xml("sqrt(2)"))["c1"].obj
    assert c1 is not None and c1.radius == sqrt(2)


def test_dataframe_value_column_is_not_evaluated(tmp_path):
    from ggblab_extra.construction_io import ConstructionIO
    from ggblab_extra.sympy.object3d import attach_object3d
    m = tmp_path / "value_column"
    x = f'''<geogebra format="5.0"><construction title="" author="" date="">
<expression label="P" exp="({payload(m)}, 1)"/>
<element type="point" label="P"><coords x="1" y="1" z="1"/></element>
</construction></geogebra>'''
    attach_object3d(ConstructionIO.from_xml(x))
    assert not m.exists()


@pytest.mark.parametrize("make", [
    lambda p: p,                       # the whole value
    lambda p: f"x + {p} = 1",          # the equation branch (both sides go through parse_expr)
])
def test_expr_from_value_refuses(tmp_path, make):
    m = tmp_path / "expr"
    with pytest.raises(ValueError):
        expr_from_value(make(payload(m)))
    assert not m.exists()


def test_plane_from_value_is_not_evaluated(tmp_path):
    m = tmp_path / "plane"
    with pytest.raises(Exception):
        plane_from_value(f"p: x + {payload(m)} = 1")
    assert not m.exists()


@pytest.mark.parametrize("s", ["a.b", "1.5.real", "x[0]", "x; y", "'x'", "__class__", "x`y`"])
def test_token_check(s):
    with pytest.raises(ValueError):
        expr_from_value(s)


def test_builtins_are_not_names():
    # with sympy's default globals `eval` / `open` / `exec` were the Python builtins; now they are not names at all, so
    # the parser turns them into SymPy symbols (split letter by letter under implicit multiplication) — a SymPy expression
    from sympy import Basic
    for s in ("eval(x)", "open(x)", "exec(x)"):
        assert isinstance(expr_from_value(s), Basic), s


def test_legitimate_values_unchanged():
    # outputs recorded with the code before A3 (identical before and after)
    assert str(expr_from_value("1.71x - 2.47z = 0")) == "Eq(1.71*x - 2.47*z, 0)"
    assert str(expr_from_value("abs(x - 1)")) == "Abs(x - 1)" and expr_from_value("max(1, 2)") == 2
    assert str(expr_from_value("ln(2)")) == "log(2)" and str(expr_from_value("2π/5")) == "2*π/5"
    assert str(expr_from_value(".5 + 2.")) == "2.50000000000000" and str(expr_from_value("1E-3 x")) == "0.001*x"


def test_point_from_value_is_not_evaluated(tmp_path):
    # point.py caught the refusal with `except Exception` and re-parsed with sympy's default globals (fixed 2026-10-08)
    m = tmp_path / "point"
    try:
        point_from_value(f"A = ({payload(m)}, 1)")
    except Exception:
        pass
    assert not m.exists()


# N2-03 (rc4): the per-module `_parse_expr` of line / circle / curve / surface / plane had a fallback to sympy's bare
# parse_expr when the hardened `expr_from_value` failed to import.  Positive control (stage 2, 2026-10-09, before the fix):
# with `line.expr_from_value = None`, `line._parse_expr("__import__")` returned the builtin.  The input is the bare name
# "__import__" (nothing is imported or called).
_PARSE_MODULES = ["line", "circle", "curve", "surface", "plane"]


@pytest.mark.parametrize("name", _PARSE_MODULES)
def test_parse_expr_refuses_in_the_normal_state(name):
    import importlib
    mod = importlib.import_module(f"ggblab_extra.sympy.{name}")
    assert mod.expr_from_value is not None
    with pytest.raises(ValueError):
        mod._parse_expr("__import__")


@pytest.mark.parametrize("name", _PARSE_MODULES)
def test_parse_expr_has_no_bare_fallback(monkeypatch, name):
    import importlib
    mod = importlib.import_module(f"ggblab_extra.sympy.{name}")
    monkeypatch.setattr(mod, "expr_from_value", None)       # as if `from .utils import expr_from_value` had failed
    with pytest.raises(ImportError):
        mod._parse_expr("__import__")
    assert not hasattr(mod, "parse_expr")                   # the bare parser is no longer imported into the module
