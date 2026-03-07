import importlib.util
import sys
# Load construction_parser directly to avoid importing ggblab_extra package
from pathlib import Path

import polars as pl

mod_path = (
    Path(__file__).resolve().parents[1] / "ggblab_extra" / "construction_parser.py"
)
spec = importlib.util.spec_from_file_location(
    "repro_construction_parser", str(mod_path)
)
cp = importlib.util.module_from_spec(spec)
sys.modules["repro_construction_parser"] = cp
spec.loader.exec_module(cp)
ConstructionTreeParser = cp.ConstructionTreeParser

rows = [
    ("A", "point", "(0,0)", []),
    ("c", "circle", "Circle(A,1)", ["A"]),
    ("B", "point", "Point(c)", ["A", "c"]),
    ("f", "line", "Line(A,B)", ["A", "B", "c"]),
    ("C", "point", "Point(f)", ["A", "B", "f"]),
    ("g", "line", "PerpendicularLine(C,f)", ["A", "B", "f", "C"]),
    ("l1", "list", "{Intersect(c,g)}", []),
    ("D", "point", "l1(1)", ["l1"]),
    ("E", "point", "l1(2)", ["l1"]),
    ("t1", "triangle", "Polygon(A,D,E)", ["A", "D", "E", "l1"]),
    ("e", "segment", "Segment(A,D,t1)", ["A", "D", "t1"]),
    ("a", "segment", "Segment(D,E,t1)", ["D", "E", "t1"]),
    ("d", "segment", "Segment(E,A,t1)", ["E", "A", "t1"]),
    ("F", "point", "Midpoint(A,C)", ["A", "C", "f"]),
    ("h", "circle", "Circle(F,A)", ["F", "A"]),
    ("l2", "list", "{Intersect(c,h)}", []),
    ("G", "point", "l2(1)", ["l2"]),
    ("H", "point", "l2(2)", ["l2"]),
    ("t2", "triangle", "Polygon(A,C,G)", ["A", "C", "G", "l2"]),
    ("g_1", "segment", "Segment(A,C,t2)", ["A", "C", "t2"]),
    ("a_1", "segment", "Segment(C,G,t2)", ["C", "G", "t2"]),
    ("c_1", "segment", "Segment(G,A,t2)", ["G", "A", "t2"]),
    ("l3", "list", "{Tangent(C,c)}", []),
    ("i", "line", "l3(1)", ["l3"]),
    ("j", "line", "l3(2)", ["l3"]),
]

df = pl.DataFrame(rows, schema=["Name", "Type", "Command", "DependsOn"])

parser = ConstructionTreeParser(df=df, auto_assign_layers=True)
G = parser.parse()

sel = parser.df.select(
    [pl.col("Name"), pl.col("Type"), pl.col("Command"), pl.col("Layer")]
)
print("Name\tType\tCommand\tLayer")
for r in sel.rows():
    print(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}")

print("\nDependsOn (after parse):")
for n, dep in parser.df.select([pl.col("Name"), pl.col("DependsOn")]).rows():
    print(f"{n}: {dep}")
