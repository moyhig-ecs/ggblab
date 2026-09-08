"""Stage 1 acceptance (C5/R6): ConstructionIO is data-in — XML string in, DataFrame out; no host, no comm."""
from pathlib import Path
import polars as pl
import pytest
from ggblab_extra import ConstructionIO, read_ggb
from ggblab.xml_errata import construction_xml

ROOT = Path(__file__).resolve().parents[1]
GGB = ROOT / "examples/2025_13_01.ggb"
G3 = ROOT / "probes/stage2/gate2/v2_g3.xml"          # a getXML() document captured from the v2 host (stage 2 gate #2)


def test_from_ggb_file_shape_and_types():
    df = ConstructionIO.from_ggb_file(GGB)
    assert df.shape == (170, 10)
    assert df.columns == ["Sequence", "Name", "Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
    assert df["Sequence"].to_list() == list(range(1, 171))
    assert df["Layer"].dtype == pl.UInt32 and df["ShowObject"].dtype == pl.Boolean


def test_polygon_errata_is_the_positive_control():
    df = ConstructionIO.from_ggb_file(GGB)
    poly = df.filter(pl.col("Type") == "polygon")
    assert poly["Command"].to_list()[:2] == ["Polygon(C, A, 4)", "Polygon(A, C, 4)"]
    seg = df.filter(pl.col("Name") == "f")["Command"].item()
    assert seg == "Segment(C, A, poly1)"                 # the edge of a Polygon(…, 4) gets its Segment(…) command back


def test_from_xml_accepts_document_element_and_fragment():
    xml = G3.read_text(encoding="utf-8")
    df_doc = ConstructionIO.from_xml(xml)
    df_el = ConstructionIO.from_xml(construction_xml(xml))
    assert df_doc.equals(df_el) and df_doc.height > 0
    frag = construction_xml(xml)
    inner = frag[len("<construction>"):-len("</construction>")] if frag.startswith("<construction>") else None
    if inner:
        assert ConstructionIO.from_xml(inner).equals(df_doc)


def test_ggb_and_applet_xml_agree_modulo_sequence():
    """The same construction read from the .ggb and from a getXML() document (after setXML) must give the same rows."""
    xml = read_ggb(GGB)
    a = ConstructionIO.from_xml(xml).drop("Sequence").sort("Name")
    b = ConstructionIO.from_ggb_file(GGB).drop("Sequence").sort("Name")
    assert a.equals(b)


def test_negative_control_detects_a_changed_label():
    xml = read_ggb(GGB).replace('label="poly1"', 'label="polyX"', 1)
    assert not ConstructionIO.from_xml(xml).equals(ConstructionIO.from_ggb_file(GGB))


def test_type_is_the_xml_class_and_closed_under_eltype():
    """Teacher 2026-09-08: Type = XML class (GeoClass.xmlName); the runtime kind is a separate, host-read column."""
    df = ConstructionIO.from_ggb_file(GGB)
    assert ConstructionIO.unknown_types(df) == []
    assert set(df["Type"].to_list()) >= {"conic", "polygon", "point"}        # never "circle" / "triangle" here
    assert "circle" not in df["Type"].to_list() and "triangle" not in df["Type"].to_list()
    kinds = {"c_1": "circle", "t1": "triangle"}                                 # what getObjectType would answer (captured 2026-09-08)
    dk = ConstructionIO.with_kind(df, kinds)
    assert dk.filter(pl.col("Name") == "c_1")["Kind"].item() == "circle" and dk.filter(pl.col("Name") == "t1")["Type"].item() == "polygon"
    assert dk["Kind"].null_count() == df.height - 2
    assert ConstructionIO.unknown_types(pl.DataFrame({"Type": ["conic", "circle"]})) == ["circle"]   # negative control: an API kind is not an XML class
