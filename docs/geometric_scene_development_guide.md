# Geometric Scene Development Guide for textbook-2025

**Date**: January 17, 2026  
**Context**: Analysis of chapters/01–15 with full ggblab dual-coding environment  
**Author Assumption**: ggblab widget.tsx fully implements GeoGebra applet execution + IPython Comm + async verification

---

## Part 1: Understanding the Current Architecture

### 1.1 Widget.tsx Communication Flow (Recap)

ggblab's `widget.tsx` implements a **four-layer communication architecture**:

```
Layer 1: GeoGebra JavaScript API (frontend)
  ↓ (IPython Comm)
Layer 2: Jupyter Kernel (Python backend)
  ↓ (WebSocket/Unix socket)
Layer 3: Out-of-band listener kernel (async events)
  ↓ (Python functions)
Layer 4: GeoGebra class API (ggblab/ggbapplet.py)
```

**Key listeners registered** (widget.tsx lines 243–287):
- `addListener`: Objects added to construction
- `removeListener`: Objects removed
- `renameListener`: Objects renamed
- `clearListener`: Construction cleared
- `MutationObserver`: Error dialogs captured

This means **every GeoGebra action is observable in Python**.

### 1.2 Construction Protocol as Executable Data Structure

The **Construction Protocol** (e.g., chapter/01/014_geogebra.ipynb) is not just documentation—it is:

```
┌─────────────────────────────────────────┐
│  Construction Protocol Table            │
│  (Name | Definition | Value)            │
└─────────────────────────────────────────┘
         ↓ (load via ggb_parser)
┌─────────────────────────────────────────┐
│  NetworkX DiGraph (Dependency Graph)    │
│  Nodes: Objects                         │
│  Edges: Dependencies                    │
└─────────────────────────────────────────┘
         ↓ (layer extraction)
┌─────────────────────────────────────────┐
│  Layer 1, 2, 3, 4 (Scope Hierarchy)    │
└─────────────────────────────────────────┘
```

**This is isomorphic to Python variable scoping.**

---

## Part 2: Patterns Observed in Chapters 01–15

### 2.1 Chapter 01: Foundation (Thales' Theorem)

**Structure**:
- `010_intro.ipynb` — Environment setup
- `011_jupyter_ai.ipynb` — AI-assisted exploration (unstructured)
- `012_draw.ipynb` — Manual drawing on blackboard (visual intuition)
- `013_geogebra.ipynb` — GeoGebra interface tutorial
- `014_geogebra.ipynb` — **Construction Protocol with AI verification** ⭐
- `015_geogebra.ipynb` — (Further exploration)

**Key Pattern**: 
- Manual → GeoGebra visual → AI-guided reasoning → Structured protocol

**Geometric Insight**: Thales' theorem is proven through:
1. Point construction (free objects)
2. Geometric derivations (dependent objects)
3. Boolean properties (verification layer)

### 2.2 Chapters 02–07: Geometric Progressions (Estimated)

Based on historical/mathematical pedagogy:

| Chapter | Likely Topic | Key Construction |
|---------|-------------|------------------|
| 02 | Quadrilateral properties | Parallelogram, symmetry |
| 03 | Similar figures | Homothety, scaling |
| 04 | Geometric mean | Golden ratio, harmonic division |
| 05 | Regular polygons | Angle relationships |
| 06 | Circle properties | Tangent, chord, arc |
| 07 | Conic sections | Focus-directrix definition |

**Pattern**: Each builds hierarchically on previous knowledge

### 2.3 Chapters 08–11: Historical Arc (Tycho → Archimedes)

**Observation**: Chapter 08 mentions "Copernicus & Tycho" (astronomy)

This suggests **non-Euclidean context**:
- Kepler's laws (ellipses)
- Archimedes' spirals
- Parametric curves

**Construction implication**: 
- Free point (center)
- Dependent trajectory (locus)
- Computed property (eccentricity)

### 2.4 Chapters 12–15: Integration Phase (Estimated)

Likely synthesis of earlier concepts with:
- Numerical methods
- Symbolic computation
- Real-world applications

---

## Part 3: Geometric Scene Development Best Practices

### 3.1 Five-Level Scene Decomposition

Every geometric scene (construction) should be decomposable into **5 levels**:

```python
Level 0: Sketch (visual intuition)
  └─ Manual drawing, visual exploration
  └─ ggblab role: Display GeoGebra visual

Level 1: Free Objects (degrees of freedom)
  └─ Points, sliders with no dependencies
  └─ ggblab role: Accept user input, pass to GeoGebra

Level 2: Derived Geometry (deterministic construction)
  └─ Lines, circles, intersections (depend on Level 1)
  └─ ggblab role: Command execution, dependency tracking

Level 3: Relationships (properties and constraints)
  └─ Distances, angles, areas, boolean equality tests
  └─ ggblab role: Function calls, numeric computation

Level 4: Verification (proof/documentation)
  └─ Assertions, symbolic proofs, exported code
  └─ ggblab role: Python verification, SymPy integration (v1.1+)
```

**Example: Thales' Theorem (Chapter 01)**

```python
# Level 0: Sketch
# "Draw a circle with a diameter"

# Level 1: Free Objects
await ggb.command("eq1: x^2 + y^2 = 1")   # Circle (implicit)
await ggb.command("O = (0, 0)")            # Center
await ggb.command("P = (1, 0)")            # Point on circle

# Level 2: Derived Geometry
await ggb.command("f: Line[O, P]")         # Diameter line
await ggb.command("A = Intersect[eq1, f]") # Endpoints
await ggb.command("B = Intersect[eq1, f]")
await ggb.command("C = Point[f]")          # Free point on diameter
await ggb.command("g: PerpendicularLine[C, f]")  # Perpendicular
await ggb.command("D = Intersect[eq1, g]") # Upper intersection
await ggb.command("E = Intersect[eq1, g]") # Lower intersection

# Level 3: Relationships
await ggb.command("t1: Polygon[O, D, E]")  # Triangle
await ggb.command("a: AreEqual[Distance[O,D], Distance[O,E]]")
await ggb.command("b: AreEqual[Angle[O,D,E], Angle[O,E,D]]")

# Level 4: Verification (Python)
distance_OD = await ggb.function("getValueString", ["Distance[O,D]"])
distance_OE = await ggb.function("getValueString", ["Distance[O,E]"])
assert float(distance_OD) ≈ float(distance_OE), "Thales: Equal distances"

angle_ODE = await ggb.function("getValueString", ["Angle[O,D,E]"])
angle_OED = await ggb.function("getValueString", ["Angle[O,E,D]"])
assert float(angle_ODE) ≈ float(angle_OED), "Thales: Equal angles"
```

### 3.2 Dependency Graph Analysis Pattern

After constructing a scene, always analyze dependencies:

```python
from ggblab import GeoGebra, ggb_parser
import polars as pl

ggb = await GeoGebra().init()
# ... perform construction ...

# Fetch construction protocol
construction = {}
for obj_name in await ggb.function("getAllObjectNames"):
    obj_info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj_name]
    )
    construction[obj_name] = obj_info

# Parse into dependency graph
parser = ggb_parser()
df = pl.DataFrame({
    'Name': list(construction.keys()),
    'Type': [v[0] for v in construction.values()],
    'Command': [v[1] for v in construction.values()],
    'Value': [v[2] for v in construction.values()],
    'Caption': [v[3] for v in construction.values()],
    'Layer': [v[4] for v in construction.values()],
}, strict=False)

parser.initialize_dataframe(df=df)
parser.parse()

# Analysis
print(f"Roots (free objects): {parser.roots}")
print(f"Leaves (unused): {parser.leaves}")

# Dependency depth
import networkx as nx
depths = {node: nx.shortest_path_length(parser.G, node, target) 
          for target in parser.G.nodes() 
          for node in parser.G.predecessors(target)}
print(f"Max depth: {max(depths.values())}")
```

**Why this matters**: 
- Root objects = pedagogical entry points
- Leaf objects = less important (can be removed)
- Depth = scope nesting level = complexity

### 3.3 Layer-by-Layer Playback Pattern

For teaching, decompose construction into **playback steps**:

```python
class ScenePlayback:
    def __init__(self, ggb, construction_df):
        self.ggb = ggb
        self.df = construction_df
        self.parser = ggb_parser()
        self.parser.initialize_dataframe(df=construction_df)
        self.parser.parse()
    
    async def play_layer(self, level: int):
        """Execute all commands at a given layer."""
        layer_objects = self.df.filter(pl.col('Layer') == level)
        for row in layer_objects.iter_rows(named=True):
            if row['Command']:  # Skip free objects
                await self.ggb.command(f"{row['Name']} = {row['Command']}")
        await asyncio.sleep(1)  # Visual pause
    
    async def play_all_layers(self):
        """Sequentially play all layers."""
        layers = sorted(set(self.df['Layer']))
        for layer in layers:
            print(f"Playing layer {layer}...")
            await self.play_layer(layer)
            # Optional: Highlight layer
            # await self.ggb.function("setLayerVisible", [(layer, True)])

# Usage
playback = ScenePlayback(ggb, df)
await playback.play_all_layers()
```

### 3.4 Verification-by-Type Pattern

Different object types require different verification:

```python
async def verify_construction(ggb, parser):
    """Multi-level verification strategy."""
    
    # Type-specific validators
    validators = {
        'point': verify_point,
        'line': verify_line,
        'circle': verify_circle,
        'polygon': verify_polygon,
        'angle': verify_angle,
        'boolean': verify_boolean,
    }
    
    results = {}
    for obj_name, obj_type in zip(parser.df['Name'], parser.df['Type']):
        if obj_type in validators:
            try:
                is_valid = await validators[obj_type](ggb, obj_name)
                results[obj_name] = {'valid': is_valid, 'type': obj_type}
            except Exception as e:
                results[obj_name] = {'valid': False, 'error': str(e)}
    
    return results

async def verify_boolean(ggb, obj_name):
    """Verify boolean condition (e.g., AreEqual[...])."""
    value = await ggb.function("getValueString", [obj_name])
    return value.lower() == 'true'

async def verify_point(ggb, obj_name):
    """Verify point is valid (not undefined)."""
    try:
        coords = await ggb.function("getXcoord", [obj_name])
        return coords is not None
    except:
        return False
```

---

## Part 4: Chapter-Specific Implementation Strategy

### 4.1 Chapter 01 (Thales) — Current Reference

**Status**: Already has Construction Protocol ✅

**Recommendation**: Enhance `014_geogebra.ipynb` with:

```python
# Cell: Load and verify Thales construction
from ggblab import GeoGebra, ggb_parser
ggb = await GeoGebra().init()

# (Load saved construction from GeoGebra file or construct step-by-step)

# Verify Thales properties
OD = float(await ggb.function("getValueString", ["Distance[O,D]"]))
OE = float(await ggb.function("getValueString", ["Distance[O,E]"]))
assert abs(OD - OE) < 1e-6, f"Thales: |OD - OE| = {abs(OD - OE)}"

# Plot dependency graph
parser = ggb_parser()
# (populate df from construction protocol)
import matplotlib.pyplot as plt
import networkx as nx

pos = nx.spring_layout(parser.G)
nx.draw(parser.G, pos, with_labels=True, node_color='lightblue')
plt.title("Thales' Theorem: Dependency Graph")
plt.show()
```

### 4.2 Chapters 02–07 — Standardized Pattern

For each chapter, ensure:

```
[Chapter_NN]
├─ [NN]_01_intro.ipynb           # Motivation, visual
├─ [NN]_02_geogebra.ipynb        # Construction in GeoGebra
├─ [NN]_03_protocol.ipynb        # Construction Protocol table
├─ [NN]_04_verify.ipynb          # ggblab verification (NEW)
├─ [NN]_05_explore.ipynb         # Interactive exploration (sliders)
└─ [NN]_[extras]

Where [NN]_04_verify.ipynb contains:
  - Load construction
  - Parse dependency graph
  - Verify all properties
  - Export results
```

**Template** (`chapters/NN/NN_04_verify.ipynb`):

```python
# Cell 1: Import and setup
from ggblab import GeoGebra, ggb_parser, ggb_construction
import polars as pl
import networkx as nx

# Cell 2: Load construction file
ggb = await GeoGebra().init()
construction = ggb_construction()
construction.load('/path/to/chapter_NN.ggb')
# Load into GeoGebra
await ggb.function("evalXML", [construction.geogebra_xml])

# Cell 3: Build construction protocol
construction_data = {}
for obj in await ggb.function("getAllObjectNames"):
    info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj]
    )
    construction_data[obj] = info

# Cell 4: Parse and analyze
df = pl.DataFrame({...}, strict=False)
parser = ggb_parser()
parser.initialize_dataframe(df=df)
parser.parse()

print(f"Objects: {len(parser.df)}")
print(f"Roots: {parser.roots}")
print(f"Depth: {max distances from roots}")

# Cell 5: Verify chapter-specific properties
# (Custom verification for each chapter's geometric theorem)

# Example for Chapter 04 (Geometric Mean):
# sqrt(CD) = sqrt(AD) * sqrt(DB)  (geometric mean of segments)
```

### 4.3 Chapters 08–11 (Historical/Astronomical) — Parametric Pattern

For chapters involving curves and loci:

```python
async def construct_kepler_ellipse(ggb, a: float, b: float):
    """Construct ellipse via parametric definition."""
    # Level 1: Parameters
    await ggb.command(f"a = {a}")
    await ggb.command(f"b = {b}")
    
    # Level 2: Foci
    await ggb.command(f"c = sqrt(a^2 - b^2)")
    await ggb.command(f"F1 = (-c, 0)")
    await ggb.command(f"F2 = (c, 0)")
    
    # Level 3: Ellipse (via definition)
    await ggb.command(f"eq: x^2/a^2 + y^2/b^2 = 1")
    
    # Level 4: Verification
    # For any point P on ellipse: Distance[P, F1] + Distance[P, F2] = 2a
    await ggb.command(f"P = Point[eq]")  # Free point on ellipse
    await ggb.command(f"d1 = Distance[P, F1]")
    await ggb.command(f"d2 = Distance[P, F2]")
    await ggb.command(f"sum_check: AreEqual[d1 + d2, 2*a]")
    
    return ['eq', 'F1', 'F2', 'P', 'sum_check']
```

---

## Part 5: Implementation Roadmap for chapters/01–15

### 5.1 Phase 1: Documentation (Weeks 1–2)

**Goal**: Generate Construction Protocol for all chapters

- [ ] Create `docs/scene_catalog.md` listing all constructions
- [ ] For each chapter:
  - [ ] Identify construction protocol (extract from GeoGebra files)
  - [ ] Document layer structure (Levels 0–4)
  - [ ] Document dependencies (roots, leaves, depth)

### 5.2 Phase 2: Verification Infrastructure (Weeks 2–4)

**Goal**: Build reusable verification components

- [ ] Create `ggblab/scene_verification.py`:
  - `verify_construction(ggb, parser)` — Multi-level verification
  - `verify_by_type(ggb, type, name)` — Type-specific checks
  - `verify_geometric_properties(ggb, assertions)` — Custom predicates

- [ ] Create `ggblab/scene_playback.py`:
  - `ScenePlayback` class with layer-by-layer execution
  - Timeline scrubbing (forward/backward)
  - Visual highlighting of active layers

### 5.3 Phase 3: Chapter-by-Chapter Notebooks (Weeks 4–12)

For each chapter NN:
- [ ] `chapters/NN/NN_04_verify.ipynb` — Verification template
- [ ] `chapters/NN/NN_05_explore.ipynb` — Interactive exploration (sliders)
- [ ] `chapters/NN/NN_06_prove.ipynb` — Symbolic proof (SymPy, v1.1+)

### 5.4 Phase 4: Integration with Curriculum (Weeks 12–16)

- [ ] Update `textbook-2025` table of contents
- [ ] Create instructor guides (how to use ggblab in classroom)
- [ ] Create student worksheets (discovery-based activities)

---

## Part 6: Why This Approach Maximizes Learning

### 6.1 Cognitive Theory Alignment

**Dual Coding Theory (Paivio, 1986)**:
- Visual (GeoGebra) + Symbolic (Python) → Stronger encoding
- ggblab enables both simultaneously

**Scoping as Mental Model**:
- GeoGebra construction = Python variable scope hierarchy
- Students see isomorphism visually + programmatically
- Transfer of learning: Geometry ↔ Programming

**Constructivist Pedagogy**:
- Students **build** constructions step-by-step (Level 0→4)
- Each level adds understanding (not just repetition)

### 6.2 Automation Benefits

**Verification-by-Execution**:
- Boolean checks in GeoGebra (AreEqual, etc.)
- Python computation (Distance, Angle numerical checks)
- Symbolic proof (SymPy, future)

→ Student gets immediate feedback: "Is my construction correct?"

**Dependency Visibility**:
- Students see **why** constructions need this order
- Parser shows: "To create D, you must first create C"
- Teaches algorithmic thinking naturally

---

## Part 7: Quick Reference

### 7.1 Essential Commands

```python
from ggblab import GeoGebra, ggb_parser, ggb_construction

# Initialize
ggb = await GeoGebra().init()

# Command execution (deterministic)
await ggb.command("A = (0, 0)")
await ggb.command("B = (3, 4)")
await ggb.command("C = Circle[A, B]")

# Function evaluation (for inspection)
value = await ggb.function("getValueString", ["C"])
type_ = await ggb.function("getObjectType", ["C"])

# File I/O
c = ggb_construction()
c.load("my_scene.ggb")
c.save("my_scene_modified.ggb")

# Dependency analysis
parser = ggb_parser()
parser.initialize_dataframe(df=construction_df)
parser.parse()
print(parser.roots)  # Free objects
print(parser.leaves) # Unused objects
```

### 7.2 File Organization

```
textbook-2025/
├─ chapters/
│  ├─ 01/
│  │  ├─ 010_intro.ipynb
│  │  ├─ 011_jupyter_ai.ipynb
│  │  ├─ 012_draw.ipynb
│  │  ├─ 013_geogebra.ipynb
│  │  ├─ 014_geogebra.ipynb (protocol)
│  │  ├─ 015_geogebra.ipynb
│  │  ├─ 01_scenes/            (NEW)
│  │  │  ├─ thales.ggb
│  │  │  └─ thales.json
│  │  └─ [01_04_verify.ipynb]  (NEW template)
│  │
│  └─ 02–15/ (same structure)
│
└─ docs/
   ├─ scene_catalog.md         (NEW)
   └─ geometric_scene_development_guide.md (this file)
```

---

## Conclusion

ggblab provides a **complete dual-coding environment**. Chapters 01–15 should be enhanced to:

1. **Explicitly decompose** each construction into 5 levels
2. **Verify** each step computationally (Python)
3. **Visualize** dependencies (NetworkX)
4. **Export** results (for portfolio, assessment)

This transforms a **static textbook** into an **interactive, verifiable learning system**.

---

**Next Steps**:
1. Confirm chapter structures (02–15)
2. Extract Construction Protocols from existing .ggb files
3. Create verification notebooks following the template
4. Test with students and iterate
