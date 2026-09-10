"""Stage 2 "algebra" (C5/R6): the XML's own numbers → SymPy, calibrated against objects of the SAME construction
(positive controls) and a corrupted matrix / label (negative controls).  No host, no value strings."""
from pathlib import Path
import math
import polars as pl
import pytest
import sympy
from sympy.geometry import Circle, Line2D, Line3D, Plane, Point2D, Point3D, Segment2D, Segment3D

from ggblab_extra import ConstructionIO, read_ggb, element_irs, command_edges, attach_ir
from ggblab_extra.sympy import is_applet_3d_from_xml
from ggblab_extra.sympy.from_ir import Sphere, attach_object3d_ir, enumerate_plane_members_ir, objects_from_xml

ROOT = Path(__file__).resolve().parents[1]
GGB2D = ROOT / "examples/2025_13_01.ggb"       # Thales (2D, 170 elements)
GGB3D = ROOT / "examples/2025_02_03.ggb"       # cylinder / Dandelin (3D, 87 elements)


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def test_every_element_has_an_ir_and_the_types_are_the_dataframe_types():
    xml = read_ggb(GGB2D); irs = element_irs(xml); df = ConstructionIO.from_xml(xml)
    assert set(irs) == set(df["Name"].to_list())
    assert all(irs[n].type == t for n, t in zip(df["Name"].to_list(), df["Type"].to_list()))


def test_2d_point_and_segment_and_line_conventions():
    xml = read_ggb(GGB2D); o = objects_from_xml(xml)
    C, A = o["C"].obj, o["A"].obj
    assert C == Point2D(0, 0) and isinstance(A, Point2D)
    f = o["f"].obj                                   # f = Segment(C, A, poly1): endpoints from the command
    assert isinstance(f, Segment2D) and f.p1 == C and f.p2 == A
    l = o["l"].obj                                   # l = PerpendicularLine(E, k): the line coefficients pass through E
    assert isinstance(l, Line2D) and near(l.distance(o["E"].obj), 0)
    # the line coefficients of the segment itself are the line through its endpoints
    ir = element_irs(xml)["f"]; a, b, c = (float(ir.coord(k)) for k in ("x", "y", "z"))
    for p in (C, A):
        assert near(a * float(p.x) + b * float(p.y) + c, 0)


def test_conic_matrix_convention_thales_circle():
    o = objects_from_xml(read_ggb(GGB2D))
    c1 = o["c_1"].obj                                # c_1 = Circle(O, C)
    assert isinstance(c1, Circle)
    assert near(c1.center.distance(o["O"].obj), 0)                       # centre = O
    assert near(abs(c1.center.distance(o["C"].obj) - c1.radius), 0)      # passes through C
    assert near(c1.center.distance(o["A"].obj) - c1.radius, 0)           # Thales: A is on the circle as well


def test_3d_point_plane_line_sphere_conventions():
    xml = read_ggb(GGB3D); o = objects_from_xml(xml)
    assert o["C_{t}"].obj == Point3D(0, 0, 3) and o["C_{b}"].obj == Point3D(0, 0, -3)
    assert o["O"].obj == Point3D(0, 0, 0)            # a 2D-class `point` in a 3D document is lifted to z = 0
    p = o["p"].obj                                   # p = Plane(Q, yAxis)
    assert isinstance(p, Plane) and near(p.distance(o["Q"].obj), 0)
    assert near(sympy.Matrix(p.normal_vector).dot(sympy.Matrix([0, 1, 0])), 0)          # contains the y axis
    f2 = o["f_2"].obj                                # f_2 = PerpendicularLine(O'', p): direction ∥ normal of p
    assert isinstance(f2, Line3D)
    d = sympy.Matrix([float(v) for v in f2.direction_ratio]); n = sympy.Matrix([float(v) for v in p.normal_vector])
    assert near(d.cross(n).norm(), 0, 1e-9) and near(f2.distance(o["O''"].obj), 0)
    s = o["o"].obj                                   # o = Sphere(O'', F_2)
    assert isinstance(s, Sphere) and near(s.center.distance(o["O''"].obj), 0) and near(s.distance(o["F_2"].obj), 0)
    g = o["g"].obj                                   # g = Segment(O, A)
    assert isinstance(g, Segment3D) and g.p1 == o["O"].obj and near(g.p2.distance(o["A"].obj), 0)
    c = o["c"].obj                                   # rim circle of Cylinder(C_t, C_b, 1): centre C_t, radius 1, axis z
    assert near(c.center.distance(o["C_{t}"].obj), 0) and near(c.radius, 1)
    assert near(sympy.Matrix(c.normal).cross(sympy.Matrix([0, 0, 1])).norm(), 0)
    e = o["e"].obj                                   # e = Circle(yAxis, C_t): centre = foot on the y axis, radius 3
    assert near(e.center.distance(Point3D(0, 0, 0)), 0) and near(e.radius, 3)


def test_plane_membership_from_ir_matches_the_construction():
    xml = read_ggb(GGB3D); df = ConstructionIO.from_xml(xml)
    out = enumerate_plane_members_ir(df, xml)
    members = dict(zip(out["Name"].to_list(), out["plane_members"].to_list()))
    assert {"Q", "O", "A", "C", "g"} <= set(members["p"])          # Plane(Q, yAxis) holds Q, O and Segment(O, A)
    assert {"C_{t}", "C_{b}", "O", "e"} <= set(members["q"])       # Plane(xAxis, zAxis) holds the axis points and Circle(yAxis, C_t)
    assert "C_{t}" not in members["p_{xy}"]                        # (0, 0, 3) is not on z = 0
    assert all(members[n] == [] for n in out.filter(pl.col("Type") != "plane3d")["Name"].to_list())


def test_attach_object3d_ir_and_attach_ir_columns():
    xml = read_ggb(GGB3D); df = ConstructionIO.from_xml(xml)
    d1 = attach_object3d_ir(df, xml); d2 = attach_ir(df, xml)
    assert "object3d" in d1.columns and "IR" in d2.columns and d1.height == d2.height == df.height
    kinds = {r["Name"]: r["object3d"].kind for r in d1.iter_rows(named=True)}
    assert kinds["p"] == "plane" and kinds["o"] == "sphere" and kinds["g"] == "segment" and kinds["v_1"] == "numeric"


def test_command_edges_are_the_construction_dag():
    xml = read_ggb(GGB2D); edges = command_edges(xml); irs = element_irs(xml)
    assert ("C", "f") in edges and ("A", "f") in edges and ("O", "c_1") in edges and ("C", "c_1") in edges
    assert all(a in irs and b in irs for a, b in edges)
    import networkx as nx
    G = nx.DiGraph(edges); assert nx.is_directed_acyclic_graph(G)


def test_is_applet_3d_from_xml():
    assert is_applet_3d_from_xml(read_ggb(GGB3D)) is True
    assert is_applet_3d_from_xml(read_ggb(GGB2D)) is False
    assert is_applet_3d_from_xml("<construction></construction>") is None   # a fragment cannot tell — never a guess
    assert is_applet_3d_from_xml("not xml") is None


def test_negative_controls():
    xml = read_ggb(GGB2D); o = objects_from_xml(xml)
    i = xml.index('label="c_1"'); j = xml.index('A2="', i); k = xml.index('"', j + 4)
    bad = xml[:j] + 'A2="0.5"' + xml[k + 1:]                                          # the constant term: the conic no longer passes through the origin
    assert bad != xml
    c1 = objects_from_xml(bad)["c_1"].obj
    assert isinstance(c1, Circle) and not near(abs(c1.center.distance(o["C"].obj) - c1.radius), 0)
    bad2 = xml.replace('label="C"', 'label="Cx"', 1)                                  # a renamed endpoint breaks the segment
    assert objects_from_xml(bad2)["f"].obj is None or objects_from_xml(bad2)["f"].obj != o["f"].obj
