# Geometric Scene Development — Quick Implementation Guide

## Overview

ggblab is a **fully functional dual-coding environment** with:
- ✅ GeoGebra applet execution (widget.tsx)
- ✅ Bidirectional Python ↔ GeoGebra communication (IPython Comm + WebSocket)
- ✅ Real-time event monitoring (addListener, removeListener, etc.)
- ✅ Dependency graph analysis (ggb_parser)
- ✅ Construction file I/O (ggb_construction)

**New in this session** (v0.10):
- ✅ `scene_verification.py` — Type-aware verification framework
- ✅ `geometric_scene_development_guide.md` — Pedagogical roadmap
- ✅ Standardized chapter notebook templates

---

## What You Can Do NOW

### 1. Load & Verify Any Geometric Construction

```python
from ggblab import GeoGebra, ggb_file
from ggblab_extra import ggb_parser
from ggblab_extra.scene_verification import SceneVerifier

ggb = await GeoGebra().init()

# Load Thales' theorem construction (chapter 01)
f = ggb_file()
f.load("chapters/01/scenes/thales.ggb")
await ggb.function("evalXML", [f.geogebra_xml])

# Analyze dependencies
parser = ggb_parser()
# (populate parser with construction protocol)
parser.parse()

# Verify all objects
verifier = SceneVerifier(ggb, parser)
results = await verifier.verify_all()
print(verifier.summary(results))
```

### 2. Interactive Layer-by-Layer Playback

```python
from ggblab_extra.scene_verification import ScenePlayback

playback = ScenePlayback(ggb, construction_df)

# Play layer 0 (free objects)
await playback.play_layer(0)

# Play layer 1 (derived geometry)
await playback.play_layer(1)

# Play all layers sequentially
await playback.play_all_layers()
```

### 3. Analyze Dependency Structure

```python
# After parser.parse():
print(f"Root objects: {parser.roots}")     # Entry points
print(f"Leaf objects: {parser.leaves}")    # Unused
print(f"Layers: {sorted(set(df['Layer']))}")  # Construction depth

# Visualize (requires matplotlib, networkx)
import networkx as nx
import matplotlib.pyplot as plt

pos = nx.spring_layout(parser.G)
nx.draw(parser.G, pos, with_labels=True)
plt.title("Construction Dependency Graph")
plt.show()
```

---

## What You Should Do NEXT

### Phase 1: Inventory (Weeks 1–2)

For each chapter 01–15:
1. Locate the construction file (`.ggb` file or protocol table)
2. Extract Construction Protocol (if not already available)
3. Document layer structure:
   - Layer 0: Free objects (points, sliders)
   - Layer 1–N: Derived objects (lines, circles, etc.)
4. Add to `docs/scene_catalog.md`

**Example**:
```markdown
## Chapter 01: Thales' Theorem

- **Free objects (Layer 0)**: Circle eq1, Point O, Point P
- **Derived objects (Layer 1)**: Line f, Points A, B
- **Relationships (Layer 2)**: Points C, D, E; Triangle t1
- **Verification (Layer 3)**: Boolean checks a, b, c
- **File**: chapters/01/scenes/thales.ggb
- **Nodes**: 18 | Max depth: 3
```

### Phase 2: Standardization (Weeks 2–4)

For each chapter NN, create:

```
chapters/NN/
├─ NN_01_intro.ipynb           (motivation, visual)
├─ NN_02_geogebra.ipynb        (GeoGebra tutorial)
├─ NN_03_protocol.ipynb        (construction protocol table)
├─ NN_04_verify.ipynb          (NEW: verification + analysis)
├─ NN_05_explore.ipynb         (interactive exploration)
├─ scenes/
│  └─ [chapter_scene].ggb
└─ scenes_json/
   └─ [chapter_scene].json     (for version control)
```

**`NN_04_verify.ipynb` template** (copy to each chapter):

```python
# Cell 1: Import
from ggblab import GeoGebra, ggb_file
from ggblab_extra import ggb_parser
from ggblab_extra.scene_verification import SceneVerifier, ScenePlayback
import polars as pl

# Cell 2: Initialize
ggb = await GeoGebra().init()

# Cell 3: Load construction
c = ggb_construction()
c.load("scenes/[chapter_scene].ggb")
await ggb.function("evalXML", [c.geogebra_xml])

# Cell 4: Build dataframe
construction = {}
for obj in await ggb.function("getAllObjectNames"):
    info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj]
    )
    construction[obj] = info

df = pl.DataFrame({
    'Name': list(construction.keys()),
    'Type': [v[0] for v in construction.values()],
    'Command': [v[1] for v in construction.values()],
    'Value': [v[2] for v in construction.values()],
    'Caption': [v[3] for v in construction.values()],
    'Layer': [v[4] for v in construction.values()],
}, strict=False)

# Cell 5: Parse and analyze
parser = ggb_parser()
parser.initialize_dataframe(df=df)
parser.parse()

print(f"**Construction Analysis**")
print(f"- Objects: {len(df)}")
print(f"- Roots: {parser.roots}")
print(f"- Max dependency depth: {max(nx.shortest_path_length(parser.G, root) for root in parser.roots)}")

# Cell 6: Verify
verifier = SceneVerifier(ggb, parser)
results = await verifier.verify_all()
print(verifier.summary(results))

# Cell 7: Visualize dependencies (optional)
import networkx as nx
import matplotlib.pyplot as plt
pos = nx.spring_layout(parser.G, seed=42)
nx.draw(parser.G, pos, with_labels=True, node_color='lightblue', arrows=True)
plt.title(f"Chapter {chapter_num}: Dependency Graph")
plt.show()

# Cell 8: Interactive playback
playback = ScenePlayback(ggb, df)
await playback.play_all_layers()

# Cell 9: Chapter-specific verification (custom)
# Example for Chapter 01 (Thales):
# OD = float(await ggb.function("getValueString", ["Distance[O,D]"]))
# OE = float(await ggb.function("getValueString", ["Distance[O,E]"]))
# assert abs(OD - OE) < 1e-6, "Thales: |OD - OE| should be ~0"
```

### Phase 3: Enrichment (Weeks 4–8)

For each chapter, add to `NN_05_explore.ipynb`:

```python
# Interactive slider → Live verification
# Example: As user moves slider C on diameter, verify Thales property

from ipywidgets import FloatSlider, Output
import asyncio

def on_slider_change(change):
    async def async_callback():
        # Move C to new position
        await ggb.command(f"C = ({change['new']}, 0)")
        
        # Re-verify
        verifier = SceneVerifier(ggb, parser)
        results = await verifier._verify_by_type("a", "boolean")
        print(f"Thales check: {results.value}")
    
    asyncio.run(async_callback())

slider = FloatSlider(min=-1, max=1, value=0.5)
slider.observe(on_slider_change, names='value')
display(slider)
```

---

## File Organization Summary

```
ggblab/
├─ src/
│  ├─ widget.tsx                    ← GeoGebra applet execution
│  └─ ...
├─ ggblab/
│  ├─ ggbapplet.py                  ← Python API (command, function)
│  ├─ parser.py                     ← Dependency graph analysis
│  ├─ construction.py               ← .ggb file I/O
│  ├─ scene_verification.py         ← NEW: Verification framework
│  └─ ...
├─ docs/
│  ├─ geometric_scene_development_guide.md  ← NEW: Complete guide
│  └─ scene_catalog.md              ← NEW: Chapter inventory
└─ textbook-2025/
   └─ chapters/
      ├─ 01/
      │  ├─ 01_04_verify.ipynb      ← NEW: Verification template
      │  ├─ 01_05_explore.ipynb     ← Enhanced with interactivity
      │  └─ scenes/
      │     └─ thales.ggb
      └─ 02–15/ (same pattern)
```

---

## Testing the Setup

### Quick Test: Verify Chapter 01

```python
%load_ext autoreload
%autoreload 2

from ggblab import GeoGebra, ggb_file
from ggblab_extra import ggb_parser
from ggblab_extra.scene_verification import SceneVerifier
import polars as pl

# Initialize
ggb = await GeoGebra().init()

# Load Thales (chapter 01)
c = ggb_construction()
c.load("chapters/01/scenes/thales.ggb")  # Adjust path as needed
await ggb.function("evalXML", [c.geogebra_xml])

# Quick verification
construction = {}
for obj in await ggb.function("getAllObjectNames"):
    info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj]
    )
    construction[obj] = info

df = pl.DataFrame({
    'Name': list(construction.keys()),
    'Type': [v[0] for v in construction.values()],
    'Command': [v[1] for v in construction.values()],
    'Value': [v[2] for v in construction.values()],
    'Caption': [v[3] for v in construction.values()],
    'Layer': [v[4] for v in construction.values()],
}, strict=False)

parser = ggb_parser()
parser.initialize_dataframe(df=df)
parser.parse()

verifier = SceneVerifier(ggb, parser)
results = await verifier.verify_all()
print(verifier.summary(results))
```

Expected output:
```
Verification Summary
==================================================
Total objects: 18
Passed: 18 ✓
Failed: 0 ✗
Pass rate: 100.0%
```

---

## Key Design Principles

1. **5-Level Decomposition**:
   - Level 0: Visual/sketch
   - Level 1: Free objects
   - Level 2: Derived geometry
   - Level 3: Relationships
   - Level 4: Verification

2. **Dual Coding** (Paivio):
   - Visual (GeoGebra) + Symbolic (Python)
   - Reinforces learning through multiple representations

3. **Constructivist Pedagogy**:
   - Students build step-by-step
   - Dependencies visible at each layer
   - Immediate feedback via verification

4. **Scoping as Mental Model**:
   - GeoGebra construction = Python variable scope
   - Transfer of learning: Geometry ↔ Programming

---

## Resources

- **Full Guide**: `docs/geometric_scene_development_guide.md`
- **Verification API**: `ggblab/scene_verification.py` (docstrings)
- **Example Usage**: See `scene_verification.py` end-of-file `EXAMPLE_USAGE`
- **textbook-2025 Analysis**: From `textbook-2025/chapters/`

---

## Next Steps (Recommended Order)

1. ✅ Read `docs/geometric_scene_development_guide.md` (Part 2–3)
2. ⏭️ **Choose Chapter 02–04** for first standardization
3. ⏭️ Extract construction file → create `02_04_verify.ipynb`
4. ⏭️ Test with students → iterate
5. ⏭️ Scale to remaining chapters

---

**Questions or Issues?**

The framework is designed to be extensible. Refer to `scene_verification.py` docstrings or `geometric_scene_development_guide.md` Part 3 for customization examples.

