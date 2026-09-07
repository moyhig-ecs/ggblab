import pytest
from ggblab.construction import (HEADS, Command, Construction, Definition, Directive, FreeNumber, FreePoint, Ident, Num, Ref,
                                 Str, Tup, arity_ok, references, render, signature)
from ggblab.parse import UnknownHead, ParseError, parse_cell, parse_statement, split_top, strip_comment

L04 = """@ggb :const :new
@ggb O=(0,0)
@ggb Circle(:O, 1)       # unit circle
@ggb P=(1, 0)
@ggb Q=(-1, 0)
@ggb c2 = Circle(:P, :Q)
@ggb Segment(:P, :Q)
"""

def test_heads_are_28_and_have_signatures():
    assert len(HEADS) == 28
    for h in HEADS:
        s = signature(h); assert s.min_args >= 1 and (s.max_args is None or s.max_args >= s.min_args)

def test_parse_cell_kinds_and_render():
    c = parse_cell(L04)
    kinds = [s.kind for s in c.statements]
    assert kinds == ["directive", "free_point", "command", "free_point", "free_point", "command", "command"]
    assert c.to_ggb() == ("O = (0, 0)", "Circle(O, 1)", "P = (1, 0)", "Q = (-1, 0)", "c2 = Circle(P, Q)", "Segment(P, Q)")
    assert c.heads() == {"Circle": 2, "Segment": 1}
    assert c.labels() == ("O", "P", "Q", "c2")
    assert c.dependencies() == (("P", "c2"), ("Q", "c2"))

def test_arguments():
    s = parse_statement('sph1=Sphere(:C1, 0.6260)')
    assert isinstance(s, Command) and s.label == "sph1" and s.args == (Ref("C1"), Num("0.6260"))
    s = parse_statement('apex=Point("{0, 0, 0}")'); assert s.args == (Str("{0, 0, 0}"),)
    s = parse_statement('nrm=Vector((0.4, 0, 1))'); assert s.args == (Tup((Num("0.4"), Num("0"), Num("1"))),)
    s = parse_statement('M_a = Midpoint(B, C)'); assert s.args == (Ident("B"), Ident("C"))
    assert references(s) == ("B", "C")

def test_nested_command_is_parsed_and_visible():
    s = parse_statement('G = Intersect(Segment(A, M_a), Segment(B, M_b))')
    assert isinstance(s, Command) and all(isinstance(a, Command) for a in s.args)
    assert render(s) == "G = Intersect(Segment(A, M_a), Segment(B, M_b))"

def test_definitions_and_free_number():
    assert parse_statement('G = "(A + B + C) / 3"') == Definition("G", "(A + B + C) / 3", True)
    assert parse_statement('S = {{1, k}, {0, 1}}') == Definition("S", "{{1, k}, {0, 1}}", False)
    assert parse_statement('T_1=l_t(1)') == Definition("T_1", "l_t(1)", False)       # lowercase call = expression, not a head
    assert parse_statement('k = 2') == FreeNumber("k", Num("2"))
    assert render(Definition("G", "(A+B)/2", True)) == "G = (A+B)/2"          # stage 2 gate #1: the current route strips the surface quotes
    assert render(Command("Point", (Str("xOyPlane"),), "P")) == "P = Point(xOyPlane)"   # Str args are rendered bare for the same reason

def test_directive_renders_to_none():
    d = parse_statement(":api getVersion()"); assert d == Directive((":api", "getVersion()")) and render(d) is None

def test_closed_world():
    with pytest.raises(UnknownHead) as e: parse_statement("x = Tangent(:A, :c)")
    assert e.value.head == "Tangent"
    with pytest.raises(UnknownHead): parse_statement("Circle(:O, Tangent(:A, :c))")
    with pytest.raises(ParseError): parse_statement("   ")

def test_arity():
    assert arity_ok(parse_statement("TriangleCenter(:A, :B, :C, 2)"))
    assert not arity_ok(parse_statement("TriangleCenter(:A, :B, :C)"))
    assert arity_ok(parse_statement("Polygon(:A, :B, :C, :D, :E)"))

def test_helpers():
    assert strip_comment('Circle(:O, 1)  # "not a string"') == "Circle(:O, 1)"
    assert strip_comment('s="d1 # d2"') == 's="d1 # d2"'
    assert split_top('(0,0,2.5), :nrm, "a,b"') == ["(0,0,2.5)", ":nrm", '"a,b"']
    assert parse_cell("%%ggb\nA = (1, 2)\nCircle(A, 1)\n", dialect="python").to_ggb() == ("A = (1, 2)", "Circle(A, 1)")
