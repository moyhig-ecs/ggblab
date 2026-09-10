"""Stage 2 (C6 data-in): the SymPy helpers are v1 verbatim minus every host coupling — checked as predicates on the
source (no import of the retired glue, no coroutine, no implicit applet lookup), not by reading the docstrings."""
import ast
from pathlib import Path
import pytest

PKG = Path(__file__).resolve().parents[1] / "ggblab_extra/sympy"


def _sources():
    for p in sorted(PKG.glob("*.py")):
        yield p, ast.parse(p.read_text(encoding="utf-8"))


def test_no_host_glue_imports_and_no_coroutines():
    for p, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                assert not any("utils_julia" in n or "ipymagic" in n or n == "IPython" for n in names), (p.name, names)
            assert not isinstance(node, ast.AsyncFunctionDef), (p.name, getattr(node, "name", ""))


def test_no_implicit_applet_lookup_in_code():
    for p, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("_instance", "user_ns"), (p.name, node.attr)
            if isinstance(node, ast.Name):
                assert node.id not in ("get_ipython", "maybe_await", "called_from_julia", "patch_ggb_for_julia"), (p.name, node.id)


def test_v1_string_parsers_still_work():
    from ggblab_extra.sympy import expr_from_value, point_from_value, plane_from_value, line_from_value
    assert point_from_value("A = (1, 2)").obj.x == 1
    p = plane_from_value("p: x + 2y - z = 4"); assert tuple(p.normal_vector) == (1, 2, -1)
    l = line_from_value("a: X = (0, 0, 0) + λ (2, 0, -1)"); assert list(l.obj.direction) == [2, 0, -1]
    assert expr_from_value("l1 = {?}") is not None


def test_3d_flag_is_set_from_xml_only():
    from ggblab_extra.sympy import get_applet_3d, set_applet_3d, set_applet_3d_from_xml
    from ggblab_extra import read_ggb
    set_applet_3d(None); assert get_applet_3d(force=True) is None                 # no detector behind `force`
    assert set_applet_3d_from_xml(read_ggb(PKG.parents[1] / "examples/2025_02_03.ggb")) is True
    assert get_applet_3d() is True
    set_applet_3d(None)
