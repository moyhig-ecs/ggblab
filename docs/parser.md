# Constructions as text

The cell magic `%%ggb` (Python) and the string macro `ggb"…"` (Julia) take a construction as text. Both send the text
to the same parser.

```python
%load_ext ggblab.ipymagic
```

```python
%%ggb g
A = (2, 1)
B = (-1, 2)
C = (0, -1)
Polygon(:A, :B, :C)
Circle(:A, 1)
```

The applet is named on the magic line (`g`). There is no implicit applet.

## A closed world

The parser knows 28 GeoGebra commands. An unknown command is an error (`UnknownHead`), not a guess.

| | | | |
|---|---|---|---|
| `Angle` | `AngleBisector` | `ApplyMatrix` | `Circle` |
| `ClosestPoint` | `Cone` | `Determinant` | `Distance` |
| `Ellipse` | `Intersect` | `IntersectConic` | `Length` |
| `Line` | `Locus` | `Midpoint` | `PerpendicularBisector` |
| `PerpendicularLine` | `PerpendicularPlane` | `Plane` | `Point` |
| `Polar` | `Polygon` | `Reflect` | `Segment` |
| `Slider` | `Sphere` | `TriangleCenter` | `Vector` |

Commands outside this list are sent with `g.command(...)`.

## Rules

| Rule | Example |
|---|---|
| An object is referenced by its label with a colon | `Circle(:A, 1)` |
| A statement may name its result | `c = Circle(:A, 1)` |
| Relative references (`_`, `__`, `_N`) are rejected (`RelativeReference`) | — |
| No `$` interpolation | — |
| An upper-case label followed by `(` is read as a command | name a list `l1`, not `L1` |
