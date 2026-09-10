"""ggblab_extra.geometry_ir — the construction XML's own numbers, per element (data-in; stage 2 "algebra", 2026-09-10).

Teacher's ruling 2026-09-07 (ii): `getValueString` is discarded and the `Value` column is the XML's IR.  For geometric
objects that IR is not a string at all — it is the element's `<coords>` (points: homogeneous x,y,z[,w]; 2D lines /
segments / rays: line coefficients a,b,c; planes: a,b,c,d; 3D lines: origin + direction), its `<matrix>` (conics A0..A5,
quadrics A0..A9) and the `<command>` that produced it (name, inputs, outputs).  `ConstructionIO.from_xml` carries v1's
file path verbatim and therefore leaves `Value` null for those objects; this module reads the same decoded document once
more and exposes the numbers as `ElementIR` records, pure and host-free.  The SymPy builders live in `sympy/from_ir.py`.

Conventions (GeoGebra 5, measured on the fixtures in tests/test_geometry_ir.py — R6: every one of them is checked
against an object of the same construction, e.g. the segment through its own endpoints, the Thales circle through C):
  point      coords x,y,z          finite point = (x/z, y/z)             (z is the homogeneous weight)
  point3d    coords x,y,z,w        finite point = (x/w, y/w, z/w)
  line/segment/ray  coords x,y,z   the line  x*X + y*Y + z = 0           (endpoints come from the command)
  line3d     coords ox..ow, vx..vw origin (ox/ow, oy/ow, oz/ow), direction (vx, vy, vz)
  plane3d    coords x,y,z,w        the plane x*X + y*Y + z*Z + w = 0
  conic      matrix A0..A5         A0 X² + A1 Y² + A2 + 2 A3 XY + 2 A4 X + 2 A5 Y = 0
  quadric    matrix A0..A9         A0 X² + A1 Y² + A2 Z² + A3 + 2 A4 XY + 2 A5 XZ + 2 A6 YZ + 2 A7 X + 2 A8 Y + 2 A9 Z = 0
  vector     coords x,y,z[,w]      the direction (w = 0); `<startPoint exp=label>` is the tail
  conic3d / segment3d / polygon / quadric parts carry no coordinate system in the XML: their geometry comes from the
  command (Circle(axis, point), Cylinder(P1, P2, r) rims, Segment(A, B), Polygon(A, B, C)) — see from_ir.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import polars as pl

from .construction_io import _decode


@dataclass(frozen=True)
class CommandIR:
    name: str
    inputs: Tuple[str, ...]
    outputs: Tuple[str, ...]
    index: int                      # which output this element is (0-based)


@dataclass(frozen=True)
class ElementIR:
    label: str
    type: str                                                   # the XML class (GeoClass.xmlName), same as DataFrame `Type`
    coords: Optional[Tuple[Tuple[str, str], ...]] = None        # ((attr, text), ...) in document order, e.g. (("x","0"),("y","0"),("z","1"))
    matrix: Optional[Tuple[str, ...]] = None                    # (A0, A1, ...) as text
    start_point: Optional[str] = None                           # vector tail label (`<startPoint exp=…>`)
    value: Optional[str] = None                                 # `<value val=…>` (numeric / angle / slider)
    eqn_style: Optional[str] = None
    expression: Optional[str] = None                            # `<expression label=… exp=…>` (numeric / text / list definitions)
    command: Optional[CommandIR] = None

    def coord(self, name: str) -> Optional[str]:
        if not self.coords:
            return None
        for k, v in self.coords:
            if k == name:
                return v
        return None


def _first(x: Any) -> Any:
    """xmlschema decodes repeated children as lists; take the first record."""
    if isinstance(x, list):
        return x[0] if x else None
    return x


def _attrs(rec: Any) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(rec, Mapping):
        return tuple()
    return tuple((k[1:], str(v)) for k, v in rec.items() if isinstance(k, str) and k.startswith("@"))


def _io_labels(rec: Any) -> Tuple[str, ...]:
    """`<input a0=… a1=…>` / `<output a0=…>` in a-index order."""
    if not isinstance(rec, Mapping):
        return tuple()
    items = [(k, v) for k, v in rec.items() if isinstance(k, str) and k.startswith("@a")]
    items.sort(key=lambda kv: int(kv[0][2:]) if kv[0][2:].isdigit() else 0)
    return tuple(str(v) for _, v in items)


def element_irs(xml: str) -> Dict[str, ElementIR]:
    """Every `<element>` of the construction as an ElementIR, keyed by label (document order preserved)."""
    o = _decode(xml)
    expressions: Dict[str, str] = {}
    for e in o.get("expression", []) or []:
        if isinstance(e, Mapping) and "@label" in e:
            expressions[str(e["@label"])] = str(e.get("@exp", ""))
    commands: Dict[str, CommandIR] = {}
    for c in o.get("command", []) or []:
        if not isinstance(c, Mapping):
            continue
        name = str(c.get("@name", ""))
        ins = _io_labels(_first(c.get("input")))
        outs = _io_labels(_first(c.get("output")))
        for i, lab in enumerate(outs):
            commands[lab] = CommandIR(name, ins, outs, i)
    out: Dict[str, ElementIR] = {}
    for e in o.get("element", []) or []:
        if not isinstance(e, Mapping):
            continue
        lab = str(e.get("@label"))
        coords = _attrs(_first(e.get("coords"))) or None
        m = _first(e.get("matrix"))
        matrix = None
        if isinstance(m, Mapping):
            ks = sorted((k for k in m if isinstance(k, str) and k.startswith("@A")), key=lambda k: int(k[2:]))
            matrix = tuple(str(m[k]) for k in ks)
        sp = _first(e.get("startPoint"))
        val = _first(e.get("value"))
        es = _first(e.get("eqnStyle"))
        out[lab] = ElementIR(
            label=lab, type=str(e.get("@type")), coords=coords, matrix=matrix,
            start_point=(str(sp.get("@exp")) if isinstance(sp, Mapping) and "@exp" in sp else None),
            value=(str(val.get("@val")) if isinstance(val, Mapping) and "@val" in val else None),
            eqn_style=(str(es.get("@style")) if isinstance(es, Mapping) and "@style" in es else None),
            expression=expressions.get(lab), command=commands.get(lab),
        )
    return out


def command_edges(xml: str) -> List[Tuple[str, str]]:
    """The construction's own dependency DAG: (input label → output label) for every `<command>`, restricted to labels
    that are elements of this construction (axes, planes such as `xOyPlane`, and literals are not nodes).  This is what
    v1's ConstructionTreeParser re-derived from command strings with regexes; the XML states it directly."""
    irs = element_irs(xml)
    edges: List[Tuple[str, str]] = []
    seen = set()
    for ir in irs.values():
        c = ir.command
        if c is None:
            continue
        for src in c.inputs:
            if src in irs and src != ir.label and (src, ir.label) not in seen:
                seen.add((src, ir.label)); edges.append((src, ir.label))
    return edges


def attach_ir(df: pl.DataFrame, xml: str, out_col: str = "IR") -> pl.DataFrame:
    """Join the ElementIR records into a ConstructionIO DataFrame by `Name` (pure; mirrors `with_kind`)."""
    irs = element_irs(xml)
    objs = [irs.get(n) for n in df["Name"].to_list()]
    return df.with_columns([pl.Series(out_col, objs, dtype=pl.Object)])


__all__ = ["CommandIR", "ElementIR", "element_irs", "command_edges", "attach_ir"]
