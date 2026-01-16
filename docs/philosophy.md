# ggblab Design Philosophy

This document articulates the design principles, scope boundaries, and educational vision for ggblab.

**Core Educational Mission**: ggblab uses geometric scene construction to teach **variable scoping** and **computational thinking**—concepts often poorly understood in Python education. Geometric dependencies (points → lines → circles) are isomorphic to programming scopes (global → function → nested). See [scoping.md](scoping.md) for the complete pedagogical framework.

**Side-by-side layout principle**: ggblab intentionally keeps the GeoGebra applet in a fixed JupyterLab main-area panel while the notebook remains scrollable on the side. Embedding the applet inside the notebook causes it to scroll out of view when editing code; the side-by-side layout preserves continuous visual feedback as code evolves the Geometric Scene.

## 1. Communication Architecture: Achieved & Plateaued

### Current State

ggblab implements a **dual-channel communication pattern** that balances:
- **Jupyter/JupyterHub compatibility**: Works locally and in cloud deployments (JupyterHub, Google Colab)
- **Cell execution responsiveness**: Out-of-band socket (Unix domain / TCP) bridges the IPython Comm blocking limitation
- **Platform portability**: POSIX sockets on Linux/macOS; TCP fallback on Windows

This design is **mature for its scope**. Further incremental improvements (connection pooling, compression, binary protocols) yield diminishing returns relative to complexity.

### Accepted Limitations

1. **Singleton instance per kernel session**: This is not a limitation but a **fundamental requirement** imposed by Python's asyncio concurrency model. In ggblab, multiple concurrent `send_recv()` async tasks must share a single buffer (`recv_logs` dict) to correlate message IDs with responses. This buffer **must be a class variable, not an instance variable**, because asyncio task scheduling doesn't preserve instance variable semantics across concurrent contexts (see [ggblab/utils.py § 8. Asyncio Scope Separation](../ggblab/utils.py) and [architecture.md § Global Scope Buffer Requirement](architecture.md#global-scope-buffer-requirement) for the detailed problem). The singleton pattern is therefore **an architectural necessity, not a design trade-off**. Multi-instance workflows can be supported at the notebook level (separate kernel sessions) rather than at the GeoGebra object level.
2. **3-second timeout on out-of-band channel**: Sufficient for interactive use; longer operations should be decomposed into steps.
3. **No persistent connection pooling**: Per-transaction connections are simple, predictable, and naturally clean up resources.

### Design Stability

The communication architecture has reached **stable maturity**. Investment in further optimization (v0.8+) should be **minimal**. Focus shifts to application-layer features built atop this foundation.

---

## 1.5. Error Handling: Transcending GeoGebra's Limitations

### The GeoGebra Problem

GeoGebra **provides no formal Error API**:
- No machine-readable error schema
- No documented error event format
- No structured error classification system
- Error information comes only as asynchronous, unstructured messages from the applet

This is a significant limitation that would paralyze most integrations.

### The ggblab Innovation: Schema-Free Error Capture

ggblab's solution is conceptually elegant:

**Rather than depending on missing GeoGebra APIs, we observe GeoGebra's actual behavior and build around it.**

This yields a system **more robust than GeoGebra's native capabilities**:

1. **Pre-flight validation** (before GeoGebra sees the command):
   - Syntax checking: Can the command be tokenized?
   - Semantic checking: Do referenced objects exist in the applet?
   - Zero GeoGebra API dependency; pure local analysis

2. **Runtime error capture** (after GeoGebra processes the command):
   - Asynchronous event monitoring via out-of-band socket
   - Works even when IPython Comm is blocked during cell execution
   - Consolidates multiple error events into semantic units
   - Properly handles timeouts, empty responses, delayed errors

3. **Hierarchical exception system**:
   ```
   GeoGebraError (all GeoGebra-related)
   ├── GeoGebraCommandError (pre-flight validation)
   │   ├── GeoGebraSyntaxError (tokenization failure)
   │   └── GeoGebraSemanticsError (missing objects)
   └── GeoGebraAppletError (runtime from GeoGebra)
   ```

### Why This Is Remarkable

**Design Principle**: When an external system (GeoGebra) provides inadequate APIs, transcend the limitation through **observational independence**.

- ✅ Zero API dependency: Works regardless of GeoGebra's error infrastructure
- ✅ Future-proof: Updates to GeoGebra don't break error handling
- ✅ Flexible: Captures errors GeoGebra doesn't officially expose
- ✅ Layered: Pre-flight + runtime provide complementary coverage
- ✅ asyncio-aware: Respects Python's concurrency semantics

**Result**: ggblab provides error handling that **exceeds GeoGebra's own capabilities**, turning a limitation into an architectural advantage.

See [docs/architecture.md — Runtime Error Handling](architecture.md#runtime-error-handling-geogebraappletererror) for technical details.

---

### The Problem with GeoGebra Alone

GeoGebra's native capabilities for numerical work are **asymmetric**:
- ✅ **Geometry + visualization**: Unmatched; native 2D/3D rendering
- ✅ **Symbolic algebra**: Usable for medium-complexity expressions
- ✅ **Lists & iteration**: Functional `Map()`, `Sequence()` exist but are cumbersome
- ✅ **Matrix operations**: Available but interface is awkward for iterative workflows
- ✅ **Solving (ODE)**: Native ODE solver available (`SolveODE` command); usable for medium complexity
- ✅ **Constraint solving**: Limited; no built-in constraint solver APIs
- ❌ **Numerical iteration**: No native iteration control; scripting is fragile
- ❌ **Data wrangling**: No structured data types (no DataFrame equivalent)
- ❌ **Statistical analysis**: Minimal support

### The ggblab Approach: Complementary Specialization

**Philosophy**: Leverage each platform's strength; bridge where needed.

| Task | Belongs To | Why |
|------|-----------|-----|
| **Geometric definition** | GeoGebra | Native primitives (point, line, circle, polygon); effortless rendering |
| **Transformation (affine, projection)** | GeoGebra native + Python wrapper | GeoGebra has matrix ops; Python cleans up interface (numpy arrays ↔ GeoGebra points) |
| **ODE solving** | Python (scipy) | GeoGebra has no solver; scipy has mature algorithms |
| **Visualization** | GeoGebra (primary), Matplotlib/Plotly (secondary) | GeoGebra excels; others useful for comparative plots |
| **Scene timeline** | ggblab + GeoGebra | Python records snapshots; GeoGebra re-renders |
| **List processing** | Python + GeoGebra function binding | Python iterates; GeoGebra evaluates user-defined functions |
| **Educational narrative** | Jupyter notebook cells | Markdown + code + visualization in unified document |

### Concrete Example: Projectile Motion with Air Resistance

**Goal**: Visualize trajectory of projectile under gravity + drag; vary parameters interactively.

```
Python side (scipy, numpy):
  - Define ODE: dy/dt = v, dv/dt = -g - (k * v²) [drag model]
  - Solve for trajectory points over time
  - Return points as list

GeoGebra side:
  - Receive point list via ggblab
  - Define path object: Curve(points)
  - Render natively with slider for t, parameter sliders for g/k
  
Jupyter narrative:
  - Cell 1: Explain physics, show ODE
  - Cell 2: Import scipy, define ODE
  - Cell 3: Open GeoGebra, solve & visualize
  - Cell 4: Vary k, observe trajectory change
  - Cell 5: Compare analytical (no drag) vs numerical (drag)
```

### Wrapper Interface Design

GeoGebra ↔ Python should be **asymmetric wrappers** tuned to each platform:

#### 1. Python → GeoGebra: List of Operations

```python
# Python computes; GeoGebra visualizes
points = solve_ode(...)  # List of [x, y] coords
await ggb.function("setBase64", [visualize_trajectory(points)])
```

#### 2. GeoGebra → Python: Parameter Export

```python
# GeoGebra exposes interactive parameters; Python reads
params = await ggb.function("getCommandString", ["k", "g"])  # Slider values
```

#### 3. Bidirectional: Scene State

```python
# Snapshot scene at each parameter step
scenes = []
for k in [0.1, 0.5, 1.0]:
    await ggb.command(f"k = {k}")
    state = await ggb.function("getBase64")
    scenes.append(state)
# Later: replay scenes as timeline
```

### Out-of-Scope: What NOT to Wrap

**Anti-pattern**: Wrapping GeoGebra's entire command syntax in Python.

❌ Don't: `ggb.create_point(x, y)` → `await ggb.command(f"A = ({x},{y})")`
- Redundant; users can write GeoGebra syntax directly
- Obscures what's actually happening
- Maintenance burden for every API change

✅ Do: Wrap **composite operations** that Python does better:
- Multi-step ODE solving → single function call
- Batch parameter sweeps → loop + `await ggb.command()`
- Scene timeline recording/playback → higher-level abstraction

---

## 3. Geometric Scene Evolution (Timeline/Animation)

### Vision: Wolfram's GeometricScene Paradigm

Mathematica's `GeometricScene` is a powerful, underexplored concept in the broader programming community. It represents a **unified data structure** for geometric configurations that can be:
- **Defined**: Specify objects, relationships, and constraints symbolically
- **Parameterized**: Vary the scene as parameters change
- **Visualized**: Render in 2D/3D at arbitrary resolution
- **Queried**: Ask questions about properties, relationships, symmetries
- **Animated**: Replay evolution as an educational narrative

While GitHub documentation on `GeometricScene` is sparse (Wolfram keeps this as intellectual property), the paradigm is revolutionary for mathematics education.

### ggblab's Reinterpretation: Scenes → Manim Videos

ggblab adapts this vision for the open-source ecosystem:

**Goal**: Transform interactive GeoGebra scenes into polished **manim-rendered educational videos**.

```
GeoGebra Construction
    ↓ (Interactive exploration, parameter adjustment)
Scene Timeline (snapshots at each parameter step)
    ↓ (Extract geometry + annotations)
Manim Script (Python code describing animations)
    ↓ (manim render engine)
MP4 Video (HD mathematical animation for teaching)
```

### Why Manim?

**manim** (Mathematical Animation Engine by Grant Sanderson / 3Blue1Brown) is:
- **Open-source**, Python-based
- **Designed for math**: Elegantly animates equations, transformations, curves
- **Publication-quality**: Produces broadcast-ready mathematical visualizations
- **Community-driven**: Large ecosystem of custom animations and examples

**Synergy**: GeoGebra provides **interactive geometric design**; manim provides **professional animation pipeline**. ggblab bridges them.

### Three-Phase Implementation

#### Phase 1: State Capture (v0.8 - v0.9)

Interactive exploration and scene snapshot recording in Jupyter.

#### Phase 2: Interactive Navigation (v0.9 - v1.0)

Timeline navigation in Jupyter; optional GeoGebra-based playback.

#### Phase 3: Educational Narrative (v1.0+)

Embed timelines in Jupyter cells with markdown annotations.

#### Phase 4: Manim Export (v1.0 - v1.5)

**The final and defining feature**: Convert scene timelines to manim-rendered videos.

```python
class SceneTimeline:
    # ... previous methods ...
    
    def to_manim_script(self, 
                        output_file='scene.py',
                        title='Geometric Transformation',
                        fps=30) -> str:
        """
        Generate a manim Scene class that reproduces the timeline.
        
        Returns:
            Python source code as string
            
        Example output:
        ```python
        from manim import *
        class GeometricEvolution(Scene):
            def construct(self):
                # Frame 0: Initial configuration
                A = Dot(point=np.array([0, 0, 0]))
                B = Dot(point=np.array([3, 0, 0]))
                # ... animate to frame 1, 2, ... N
        ```
        """
        
    async def render_video(self,
                          output_format='mp4',
                          quality='high') -> bytes:
        """
        Orchestrate:
        1. Extract geometry from snapshots
        2. Generate manim script
        3. Invoke 'manim render'
        4. Return video file bytes
        """
```

**Pedagogical power**: Students can:
1. Interactively build scenes in GeoGebra
2. Record parameter evolution in Jupyter
3. Export as professional-quality video
4. Share on platforms (YouTube, course sites)
5. Understand the code that generated it (transparency)

### Why Not Multiple Simultaneous Applets?

**Initial goal**: Compare two constructions side-by-side for pedagogical clarity (e.g., "with drag" vs "without drag").

**Reality check from implementation**: GeoGebra Applet's rendering pipeline misinterprets device DPI / responsive scaling. Placing two applets in smaller containers compounds the bug — content progressively shrinks, defeating pedagogical clarity.

**Pragmatic redesign**: Single applet + timeline-driven navigation. Actually *better* UX:
- Users focus on one scene at a time, reducing cognitive load
- Parameter transitions reveal cause-and-effect relationships more viscerally
- Smooth playback (frame-by-frame or animated) makes understanding memorable
- Works on all devices without DPI/scaling workarounds

This aligns with the Mathematica precedent: *replay* conveys understanding better than *side-by-side comparison*.

---

## 4. Parser: Rationale & Sunset

### Original Intent

`parse_subgraph()` attempted to extract "minimal construction sequences" — which objects are strictly necessary to derive a target object, removing redundancies.

### Why It Failed: Lessons from Implementation

Through extensive experimentation, we discovered that `parse_subgraph()`, despite solid algorithmic intent, did not serve ggblab's educational mission:

1. **Ambiguous definition**: "Minimal" can mean different things (fewest objects? simplest construction? fastest evaluation?) No single definition emerges as pedagogically useful.

2. **Intractable computation**: $O(2^n)$ for $n$ roots makes it impractical at scale. Even moderate constructions (15+ independent objects) hang or timeout.

3. **Limited pedagogical value**: For teaching, **explicit construction steps** (what the student actually did) matter more than **mathematical minimality**. Students don't ask "what's the minimal way to build this?" — they ask "how did I build this, and what changes when I adjust parameters?"

### Reconsidering the True Goal

Parser experiments revealed our actual objective: **Geometric Scene evolution**, not dependency minimization. This aligns with Stephen Wolfram's Scene concept in Mathematica — capturing and replaying the *trajectory* of a construction as parameters vary, rather than decomposing it.

### Revised Approach

- **Dependency graph `G`**: Still valuable. Users can inspect what depends on what.
- **Subgraph extraction `G2`**: Deprecated. If needed in future, use topological pruning (v1.0 design in [architecture.md](architecture.md)).
- **Scene timeline**: Better serves the goal of showing "how the construction evolves."

**Action**: Keep `parse()` for graph building. Deprecate `parse_subgraph()` with a warning; remove in v1.1 unless strong use case emerges.

---

## 5. Educational Context: Design for Classroom Use

ggblab's primary audience is **geometry/math education**, not production applications.

### Assumptions

- **Interactive, exploratory workflow**: User is learning, experimenting, adjusting parameters
- **Narrative integration**: Jupyter notebook provides context (problem statement, hints, reflection questions)
- **Reproducibility**: Instructor can run the same notebook repeatedly; students see consistent visualizations
- **Low barrier to entry**: Python + GeoGebra + Jupyter should "just work" without deep infrastructure knowledge

### Design Implications

1. **Simplicity over completeness**: Omit rarely-used features (multi-instance, persistent connection pools, etc.)
2. **Clear error messages**: When something fails, explain why and suggest remediation
3. **Example-driven**: Include worked examples (affine transformation, ODE solving, scene timelines) in tutorial notebooks
4. **Iterative refinement**: Expect feedback from instructors; prioritize classroom-observed pain points

### Scope Exclusion

**Out of scope**:
- Production deployment (high-availability, monitoring, SLA)
- Real-time collaboration (multiple users editing same notebook simultaneously)
- Offline-first workflows (assume network access)
- Non-educational use (general GeoGebra remote control)

---

## 6. Technical Roadmap: Prioritized by Learning Value

### Tier 1: Foundational (Already Done)

- Dual-channel communication ✅
- File format support ✅
- Basic GeoGebra API binding ✅

### Tier 2: Scene & Animation (v0.8 - v1.0)

**High learning value**:
- Scene snapshot capture
- Timeline navigation
- Smooth playback in Jupyter

**Why**: Bridges interactive exploration and narrative understanding.

### Tier 2.5: Manim Export (v1.0 - v1.5)

**Extremely high impact; defining feature**:
- Extract geometry from scene snapshots
- Generate manim Python code automatically
- Render to MP4/GIF for publication

**Why**: Enables educators to author professional mathematical videos without manim expertise. Closes the loop from education design to broadcast-quality content.

### Tier 3: Numerical Integration & Symbolic Verification (v0.9 - v1.0)

**High learning value**:
- Wrapper for scipy ODE solvers
- Point list ↔ GeoGebra object conversion
- Parameter sweep utilities
- **SymPy Geometry bridge** for symbolic computation and verification

**Why**: Teaches numerical analysis, complementary use of tools, scientific computing. SymPy integration enables symbolic proof verification, exact calculations, and bidirectional code generation between geometric representations.

**SymPy Integration Highlights**:
- Convert GeoGebra constructions ↔ SymPy geometric objects
- Verify geometric properties symbolically (collinearity, concyclicity, perpendicularity)
- Generate manim animation code from SymPy geometry
- Export construction steps as reproducible Python code
- See [sympy_integration.md](sympy_integration.md) for detailed design.

### Tier 4: Data Structures & Iteration (v1.0+)

**Medium learning value**:
- Polars/Pandas DataFrames for construction metadata
- Batch list operations
- Functional programming patterns

**Why**: Reinforces data wrangling skills; prepares for advanced analysis.

### Tier 5: Optimization & Deployment (v1.0+)

**Low priority for education**:
- Connection pooling, compression, binary protocols
- High-availability setup
- Cloud scaling

**Rationale**: Not directly relevant to teaching. Do only if real bottleneck appears.

---

## 7. Success Criteria

### For v0.8 (Scene Timeline)

- [ ] SceneTimeline class captures and replays GeoGebra snapshots
- [ ] Example notebook: projectile motion with interactive timeline
- [ ] Instructor feedback: "students understand parameter effects better"

### For v1.0 (Numerical Integration)

- [ ] scipy ODE integration example: damped pendulum with GeoGebra visualization
- [ ] Point list conversion utilities (numpy ↔ GeoGebra objects)
- [ ] Example notebook: compare analytical vs numerical solutions
- [ ] Student outcomes: improved intuition for differential equations

### For v1.5 (Manim Export)

- [ ] `SceneTimeline.to_manim_script()` generates publication-quality animation code
- [ ] `SceneTimeline.render_video()` orchestrates manim render pipeline
- [ ] Example: projectile motion with air resistance → animated video
- [ ] Educator feedback: "can now publish professional educational content"
- [ ] Impact: Open-source alternative to expensive animation software

### Long-term (v1.5+)

- [ ] 5+ complete lesson modules (affine transforms, ODEs, constrained geometry, etc.)
- [ ] Adoption by 3+ institutions
- [ ] Open-source community contributions

---

## 8. Boundary Conditions

### What ggblab Is NOT

- A replacement for GeoGebra (GeoGebra is the engine)
- A replacement for Python (Python is the compute substrate)
- A production geometry server (scope is education)
- A competitor to Mathematica (inspiration only)

### What ggblab IS

- A **bridge** between GeoGebra and Python in Jupyter
- A **framework** for capturing and replaying geometric scenes
- A **teaching tool** to deepen understanding through interactive exploration and numerical integration

---

## Summary: Design Maturity by Dimension

| Dimension | Status | Next Action |
|-----------|--------|------------|
| **Communication** | Mature, plateaued | Maintain; focus elsewhere |
| **Geometry visualization** | Mature (GeoGebra native) | Enhance via Scene Timeline |
| **Scene evolution** | Proof-of-concept needed | Implement v0.8-v1.0 |
| **Manim export** | Greenfield; **defining feature** | Architect extraction + codegen (v1.0-v1.5) |
| **Numerical analysis** | Greenfield | Design wrapper layer; v0.9-v1.0 |
| **SymPy integration** | Greenfield | Bridge symbolic ↔ geometric representations; v1.1-v1.2 |
| **Parser (subgraph)** | Failed experiment | Deprecate; shift focus to timeline |
| **Educational integration** | In progress | Develop lesson modules; gather instructor feedback |

**Thesis**: ggblab's value lies not in technical infrastructure (communication is solved) but in creating a **unified authoring and publishing pipeline** for interactive mathematical education:

$$\text{GeoGebra (design)} \to \text{Timeline (explore)} \to \text{Manim (publish)} \to \text{Video (teach)}$$

This reinterprets Wolfram's `GeometricScene` vision for the open-source community, enabling educators to author mathematical animations without deep manim programming expertise.
