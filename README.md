# ggblab — A JupyterLab extension for learning geometry and Python programming side-by-side with GeoGebra

🚀 Quick links:

- **Binder (Demo)**: Hosted demo and instructions to launch the examples in JupyterLab — see [binder/README.md](binder/README.md).
- **Blog**: Project news and writeups — published site: https://moyhig-ecs.github.io/ggblab/ (source / local preview: [blog/README.md](blog/README.md)).


[![PyPI](https://img.shields.io/pypi/v/ggblab.svg)](https://pypi.org/project/ggblab/)
[![Python](https://img.shields.io/pypi/pyversions/ggblab.svg)](https://pypi.org/project/ggblab/)
[![Tests](https://github.com/moyhig-ecs/ggblab/actions/workflows/tests.yml/badge.svg)](https://github.com/moyhig-ecs/ggblab/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/moyhig-ecs/ggblab/branch/main/graph/badge.svg)](https://codecov.io/gh/moyhig-ecs/ggblab)
[![License](https://img.shields.io/pypi/l/ggblab.svg)](LICENSE)
[![Documentation Status](https://readthedocs.org/projects/ggblab/badge/?version=latest)](https://ggblab.readthedocs.io/en/latest/?badge=latest)
[![JupyterHub](https://img.shields.io/badge/JupyterHub-Supported-brightgreen)](#cloud-deployment)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/moyhig-ecs/ggblab/main?urlpath=lab/tree/examples/example.ipynb)

A JupyterLab extension that displays a GeoGebra applet in a side-by-side panel while your notebook code remains editable on the side—enabling **interactive dual coding** where you manipulate geometry visually and control it from Python. Geometric visualization and computational thinking reinforce each other. Learn programming through geometric construction; reason about geometry through Python code. Grounded in cognitive science (Dual Coding Theory, Transfer of Learning), ggblab bridges visual and symbolic domains so knowledge transfers across disciplines.

The GeoGebra applet displays in a fixed JupyterLab panel while your notebook remains scrollable on the side—preserving continuous visual feedback as you edit code. You can manipulate geometry directly in GeoGebra (dragging points, creating objects) and simultaneously control it from Python code. This side-by-side layout enables true bidirectional interaction: change the applet, see Python respond; run Python code, watch the geometry update.

### Features

- **Dual Coding System**: Geometric visualization + Python code in a unified workspace—students learn through both visual and symbolic representations
- Programmatic launch via `GeoGebra().init()` (recommended), which uses ipylab to pass communication settings before widget initialization (Command ID: `ggblab:create`, label: "React Widget"). Command Palette/Launcher work only with fixed arguments and are suitable for default settings.
- Call GeoGebra commands (`command`) and API functions (`function`) from Python through the `GeoGebra` helper
- **Domain Bridge**: Construction dependencies in GeoGebra map isomorphically to variable scoping in Python—teach computational thinking through geometric structure
- **Transfer of Learning**: Knowledge learned in geometric context transfers to computational thinking and vice versa. Dual representations strengthen understanding across both domains.
- Combined IPython Comm + Unix domain socket (POSIX) / TCP WebSocket channel for fast data exchange
- Frontend watches add/remove/rename/clear events and dialog messages and forwards them to the kernel
- Settings schema is wired up (no user options yet) for future configuration
- **Single Comm target name `ggblab-comm`** and **singleton instance per kernel session**: Multiplexing via multiple targets is avoided because (1) IPython Comm cannot receive during cell execution, and (2) more fundamentally, **asyncio's concurrency model requires all concurrent `send_recv()` tasks to share a single message buffer at class scope** to safely correlate responses by message ID. See [ggblab/utils.py section 8 — Unexpected Scope Subdivision in asyncio](ggblab/utils.py) for why instance variables fail in asyncio contexts, and [architecture.md § Asyncio Design Challenges](docs/architecture.md#asyncio-design-challenges-in-jupyter) for the full technical rationale.

### Requirements

- JupyterLab >= 4.0
- Python >= 3.10
- Browser access to https://cdn.geogebra.org/apps/deployggb.js
- For development: Node.js and `jlpm`

### Installation

```bash
pip install ggblab
jupyter labextension list | grep ggblab
```

#### Cloud/JupyterHub Support

This JupyterLab extension supports both local installs and managed cloud deployments:

- Managed JupyterHub on Kubernetes: install via `pip install ggblab` only — no manual labextension build steps required.
- All communication concerns are addressed and validated in cloud environments (IPython Comm + out-of-band sockets).
- End users on JupyterHub can use the extension immediately after `pip install`; developers can follow the Development Workflow for local builds.

For deployment guidance and troubleshooting, see the [Cloud Deployment](#cloud-deployment) section.

#### ⚠️ Known Browser Compatibility Issue: JupyterLab on Safari and iPadOS

**Classroom Deployment Notice**: JupyterLab's UI framework (Lumino) has known compatibility issues with Safari browser and all browsers on iPadOS. This is a **JupyterLab/Lumino limitation related to WebKit browser engine restrictions, not specific to ggblab**. Affected functionality includes:
- **Affected platforms**: 
  - iPad running iPadOS 26 (2025) — **all browsers on iPadOS are forced to use WebKit engine, making this unsolvable at the browser level**
  - macOS with Safari browser
- **Issue**: JupyterLab's Lumino UI framework relies on browser APIs that WebKit (Safari) restricts or handles differently, affecting layout rendering, widget lifecycle, and frontend-to-kernel communication reliability
- **Not affected**: JupyterLab on Chromium-based browsers (Chrome, Edge) and Firefox on macOS, Windows, and Linux remain fully supported
- **Impact on ggblab**: ggblab's frontend widget relies on JupyterLab's Lumino framework; when Lumino itself is compromised by WebKit limitations, ggblab functionality may degrade
- **Workaround for classrooms**: 
  - **iPadOS**: No browser-level workaround available (all browsers use WebKit). Consider alternatives to iPad, or use iPad only for static Jupyter notebooks
  - **macOS**: Use Chromium-based browsers (Chrome, Edge) or Firefox instead of Safari for interactive JupyterLab sessions
  - **Recommended**: Deploy JupyterLab on macOS, Windows, or Linux systems for classroom use; these platforms have no browser restrictions and full JupyterLab/ggblab support
  - If JupyterHub is deployed, document these limitations and restrict interactive JupyterLab access from iPad or Safari

This is an upstream JupyterLab/Lumino + WebKit browser engine limitation, not a ggblab-specific problem. See [JupyterLab documentation](https://jupyterlab.readthedocs.io/) and [GitHub Issues](https://github.com/moyhig-ecs/ggblab/issues) for current status.

#### ⚠️ Known Display Issue: GeoGebra Applet Size Scaling on Window Resize

**Technical Notice**: ggblab applies Applet dimensions via CSS and widget configuration. However, when the JupyterLab window is resized after the Applet is initialized, device resolution scaling can become confused, causing the displayed GeoGebra applet to appear smaller than expected.

- **Issue**: Window resize triggers recalculation of CSS dimensions, but internal DPI/device pixel ratio tracking in GeoGebra may not sync properly with the updated layout
- **Symptom**: GeoGebra applet appears compressed or smaller after resizing the browser window
- **Affected configurations**: More common on high-DPI displays (2x+ device pixel ratio), including Retina displays on macOS and high-resolution external monitors
- **Note**: This scaling issue **cannot be reset via GeoGebra API commands** (e.g., `SetCoords()`) once triggered; it is purely a rendering/layout issue
- **Workaround**: 
  - Refresh the browser page after resizing the JupyterLab window to reinitialize display scaling
  - Avoid frequent window resizing during interactive sessions when possible

This is a display/rendering interaction between JupyterLab's layout manager and GeoGebra's canvas scaling, not a communication or functionality issue. The Applet operates correctly; only the visual presentation is affected.

Uninstall:

```bash
pip uninstall ggblab
```

### Quick Start (UI)

1. Open JupyterLab
2. Run "React Widget" from the Command Palette (category "Tutorial") or click the Launcher tile under "example"
3. A GeoGebra panel opens in the main area; layout restoration and launcher integration are enabled

Design note: ggblab is optimized for a side-by-side workflow—GeoGebra stays pinned in the main area while the notebook scrolls independently. Embedding the applet inside a notebook cell is possible but not recommended because it scrolls out of view during code edits.

### Quick Start (Notebook/Python)

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # init IPython Comm/socket and open the GeoGebra panel

await ggb.command("A=(0,0)")    # create a point
value = await ggb.function("getValue", ["A"])  # call GeoGebra API
print(value)
```

`init()` fetches the current kernel ID, starts the IPython Comm/WebSocket server, and triggers the frontend command `ggblab:create` to open the panel. `command` sends GeoGebra commands; `function` calls GeoGebra API names (single name or list) and returns the result asynchronously.

### Error Handling — Comprehensive Exception Hierarchy

ggblab implements a **sophisticated, multi-layer error handling system** that stands out as a remarkable achievement in transcending GeoGebra's limitations:

**The Challenge**: GeoGebra provides no formal Error API or machine-readable error schema. Error information comes purely as asynchronous event messages from the applet.

**The Breakthrough**: Rather than depending on missing GeoGebra APIs, ggblab implements a **schema-free, observation-driven error capture system** that:
1. **Validates pre-flight** (syntax, semantics) before GeoGebra ever sees the command
2. **Captures runtime errors asynchronously** via the dual-channel architecture (out-of-band socket)
3. **Consolidates multiple error events** automatically
4. **Distinguishes error sources** (pre-flight vs. runtime) through a rich exception hierarchy

**Result**: ggblab's error handling is **more robust and flexible than GeoGebra's native capabilities**.

```python
from ggblab.errors import GeoGebraError, GeoGebraAppletError

# Pre-flight validation errors (caught before execution)
try:
    ggb.check_syntax = True
    ggb.check_semantics = True
    await ggb.command("Circle(A, B)")
except GeoGebraSyntaxError as e:
    print(f"Syntax error: {e.command}")
except GeoGebraSemanticsError as e:
    print(f"Missing objects: {e.missing_objects}")

# Runtime errors from GeoGebra applet (caught after execution)
try:
    await ggb.command("Unbalanced(")
except GeoGebraAppletError as e:
    print(f"Applet error: {e.error_message}")

# Catch all GeoGebra errors
try:
    await ggb.command("...")
except GeoGebraError:
    # Handles all GeoGebra-related exceptions
    pass
```

**Error Types:**
- **GeoGebraSyntaxError**: Command cannot be tokenized (pre-flight)
- **GeoGebraSemanticsError**: Referenced objects don't exist in applet (pre-flight)
- **GeoGebraAppletError**: GeoGebra applet produces error events during execution (runtime)

**Architecture Achievements:**
- Pre-flight validation prevents invalid commands from reaching GeoGebra
- Runtime errors captured asynchronously via dual-channel communication (IPython Comm + WebSocket)
- Consecutive error events automatically consolidated into semantic units
- Full asyncio compliance with timeout handling and queue polling
- Zero dependency on external error schemas or APIs

See [ggblab/errors.py](ggblab/errors.py) for the complete exception hierarchy and [docs/architecture.md](docs/architecture.md#runtime-error-handling-geogebraappletererror) for implementation details.

## Documentation


ggblab's design philosophy and implementation details are documented across several focused documents:

**Full documentation available at**: https://ggblab.readthedocs.io/

Note: Documentation has moved under docs/. Start at [docs/index.md](docs/index.md) or [philosophy.md](docs/philosophy.md). Legacy copies are retained in docs_archive/ (git-ignored) for reference.

### Core Documentation

- **[philosophy.md](docs/philosophy.md)** - Design principles, scope boundaries, and educational vision
  - Communication architecture maturity and stability assessment
  - GeoGebra + Python complementarity framework
  - Geometric Scene evolution inspired by Wolfram's GeometricScene paradigm
  - Manim video export as the ultimate pedagogical goal
  - Prioritized technical roadmap (Tiers 1-5) focused on learning value
  - Success criteria for each version milestone (v0.8 - v1.5+)

- **[scoping.md](docs/scoping.md)** - **Core Educational Mission**: Variable scoping via geometric construction
  - **The foundational insight**: Geometric dependencies (points → lines → circles) are isomorphic to programming scopes (global → function → nested)
  - How GeoGebra's construction protocol naturally forms a scope tree
  - Computational thinking pedagogy through geometric decomposition, pattern recognition, abstraction, and algorithm design
  - Concrete lesson plans for teaching Python scoping using geometric constructions
  - Classroom integration roadmap with assessment rubrics
  - Cognitive science rationale: Dual Coding Theory, Transfer of Learning, Constructivism

- **[architecture.md](docs/architecture.md)** - Technical implementation details
  - Dual-channel communication design (IPython Comm + Unix socket/TCP WebSocket)
  - Message flow patterns and error handling strategies
  - Dependency parser architecture with performance analysis
  - Critical limitations of `parse_subgraph()` and recommended v1.0 algorithm replacement
  - Resource cleanup and security considerations
  - Testing strategies and development workflow

- **[TODO.md](TODO.md)** - Actionable development roadmap
  - 7 priority areas: Parser, Type Safety, Error Handling, CI/CD, Documentation, Configuration, Monitoring
  - Version targets (v0.7.3 - v1.0+) with concrete implementation tasks
  - Blocking issues and dependency tracking
  - Quick-fix vs. long-term architectural improvements

- **[ai_assessment.md](docs/ai_assessment.md)** - Independent AI evaluation of project quality and direction
  - Comprehensive strengths and weaknesses analysis
  - Technical, educational, and practical usability assessment
  - Recommended actions and prioritization guidance
  - Critical questions for project sustainability

### Advanced Integration

- **[sympy_integration.md](docs/sympy_integration.md)** - Symbolic computation and code generation
  - Bidirectional conversion: GeoGebra constructions ↔ SymPy Geometry objects
  - Symbolic verification of geometric properties (collinearity, concyclicity, perpendicularity)
  - Automatic Python code generation from constructions (reproducibility + version control)
  - Advanced solvers: locus equations, envelope curves, constraint satisfaction
  - Manim export pipeline: SymPy geometry → manim animation code
  - Implementation roadmap (v1.1 - v1.5) with educational success criteria

### API Reference

- **[API Documentation](https://ggblab.readthedocs.io/en/latest/api.html)** - Python API reference auto-generated from docstrings
  - `GeoGebra` class: Main interface for controlling applets
  - `ggb_comm`: Dual-channel communication layer
  - `ggb_construction`: File loader and saver
  - `ggb_parser`: Dependency graph analysis
  - `ggb_schema`: XML schema loader

### Quick Reference

| Document | Primary Audience | Key Insight |
|----------|-----------------|-------------|
| **[docs/scoping.md](docs/scoping.md)** | Educators, Students | Geometric construction teaches programming scoping |
| **[docs/philosophy.md](docs/philosophy.md)** | Contributors, Researchers | ggblab = GeoGebra → Timeline → Manim → Video pipeline |
| **[docs/sympy_integration.md](docs/sympy_integration.md)** | Math/CS Instructors | Symbolic proof + code generation + manim export |
| **[docs/architecture.md](docs/architecture.md)** | Developers | Dual-channel communication; parser needs v1.0 redesign |
| **[TODO.md](TODO.md)** | Contributors | Concrete next steps prioritized by learning value |
| **[API Reference](https://ggblab.readthedocs.io/en/latest/api.html)** | Developers | Complete Python API documentation |

### Examples

- Sample notebook: [examples/example.ipynb](examples/example.ipynb)
- Demo video:

![Demo video](https://github.com/user-attachments/assets/b02122bb-7fdd-42ac-bb53-9d58ab288973)

Run steps:

```python
%load_ext autoreload
%autoreload 2

from ggblab import GeoGebra
import io

ggb = await GeoGebra().init()  # open GeoGebra widget on the left

c = ggb.construction.load('/path/to/your.ggb')  # supports .ggb, zip, JSON, XML
o = c.ggb_schema.decode(io.StringIO(c.geogebra_xml))  # geogebra_xml is auto-stripped to construction
o
```

Note: Supports `.ggb` (base64-encoded zip), plain zip, JSON, and XML formats. The `geogebra_xml` is automatically narrowed to the `construction` element and scientific notation is normalized. Schema/decoding APIs may evolve.

### Saving construction

Save the current construction (archive when Base64 is set, otherwise plain XML):

```python
from ggblab import GeoGebra

ggb = await GeoGebra().init()
c = ggb.construction.load('/path/to/your.ggb')

# Save to XML (when no Base64 is set)
c.save('/tmp/construction.xml')

# Save to a .ggb file name; content depends on state:
# - if Base64 is set -> decoded archive (.ggb zip)
# - else -> plain XML bytes (extension does not enforce format)
c.save('/tmp/construction.ggb')
```

#### Saving behavior and defaults

- `c.save()` with no arguments writes to the next available filename derived from the originally loaded `source_file` (e.g., `name_1.ggb`, `name_2.ggb`, ...). Use `c.save(overwrite=True)` to overwrite the original `source_file`.
- If `construction.base64_buffer` is set (e.g., from `getBase64()` or `load()`), `save()` writes the decoded archive; otherwise it writes the in-memory `geogebra_xml` as plain XML.
- Target file extension does not enforce format: if Base64 is absent, saving to a `.ggb` path will still write plain XML bytes.
- Note: `getBase64()` from the applet may not include non-XML artifacts present in the original `.ggb` archive (e.g., thumbnails or other resources). Saving after API-driven changes can therefore produce a leaner archive.

### Use Cases (from examples/eg3_applet.ipynb)

#### 1) Algebraic commands and API functions

```python
# Algebraic command
r = await ggb.command("O = (0, 0)")

# API functions
r = await ggb.function("getAllObjectNames")
r = await ggb.function("newConstruction")
```

#### 2) Load .ggb and draw via Base64

```python
# Load a .ggb (base64-encoded zip)
c = ggb.construction.load('path/to/file.ggb')

# Render in applet
await ggb.function("setBase64", [ggb.construction.base64_buffer.decode('utf-8')])
```

#### 3) Layer visibility control

```python
from itertools import zip_longest

layers = range(10)
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=False)))
layers = [9, 0]
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=True)))
```

#### 4) XML attribute edit roundtrip

```python
# Pull XML for object 'A'
r = await ggb.function("getXML", ['A'])

# Decode to schema dict, modify, and encode back
o2 = c.ggb_schema.decode(r)
o2['show'][0]['@object'] = False
x = xmlschema.etree_tostring(c.ggb_schema.encode(o2, 'element'))

# Apply to applet
await ggb.function("evalXML", [x])
```

#### 5) Roundtrip save from applet state

```python
# Fetch current applet state as base64 and save
r = await ggb.function("getBase64")
ggb.construction.base64_buffer = r.encode('ascii')
c.save()              # next available filename based on source_file
# c.save(overwrite=True)  # to overwrite the original
```

### Object Dependency Analysis (Parser)

ggblab includes a **dependency parser** (`ggblab.parser.ggb_parser`) that analyzes object relationships in GeoGebra constructions using **NetworkX graphs**. This enables:

- **Dependency tracking**: Build a directed graph of which objects depend on which others
- **Root/leaf identification**: Find independent starting objects and final dependent objects
- **Subgraph analysis**: Identify minimal construction sequences needed to derive specific objects

#### Basic Usage

```python
from ggblab import GeoGebra
from ggblab.parser import ggb_parser
import networkx as nx

ggb = GeoGebra()
await ggb.init()

# Fetch construction protocol from applet
construction = {}
for obj_name in await ggb.function("getAllObjectNames"):
    obj_info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj_name]
    )
    construction[obj_name] = obj_info

# Parse into Polars DataFrame
parser = ggb_parser()
parser.initialize_dataframe(df=pl.DataFrame(construction, strict=False))
parser.parse()  # Build dependency graph

# Access the NetworkX DiGraph
G = parser.G
print(f"Root objects: {parser.roots}")      # Objects with no dependencies
print(f"Leaf objects: {parser.leaves}")      # Objects that nothing depends on

# Traverse dependencies
for obj in parser.roots:
    descendants = nx.descendants(G, obj)  # All objects that depend on this one
    print(f"{obj} -> {descendants}")
```

#### Advanced: Subgraph Extraction

Extract minimal construction sequences needed for specific output objects:

```python
# Analyze subgraph for focused construction steps
parser.parse_subgraph()  # Builds G2 with simplified dependencies
G2 = parser.G2

# Reconstruct only necessary steps
nx.write_network_text(G2)  # View simplified dependency tree
```

#### Parser Components

- **`df`**: Polars DataFrame with columns `Type`, `Command`, `Value`, `Caption`, `Layer` (transposed from construction protocol)
- **`G` (NetworkX DiGraph)**: Full dependency graph; edges point from dependencies to dependents
- **`G2` (NetworkX DiGraph)**: Simplified subgraph with redundant dependencies removed
- **`ft` (dict)**: Tokenized command strings; maps object name → list of tokens (parsed by `tokenize_with_commas()`)
- **`roots` (list)**: Objects with `in_degree == 0` (no incoming dependencies)
- **`leaves` (list)**: Objects with `out_degree == 0` (nothing depends on them)

#### Example Notebook

See [examples/eg4_parse.ipynb](examples/eg4_parse.ipynb) for a complete example of loading a `.ggb`, building dependency graphs, and analyzing construction structure.

### Architecture

- **Frontend** ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx)): Registers the plugin `ggblab:plugin` and command `ggblab:create`. Creates a `GeoGebraWidget` ReactWidget that loads GeoGebra from the CDN, opens an IPython Comm target (default `test3`), executes commands/functions, and mirrors add/remove/rename/clear events plus dialog notices back to the kernel. Results can also be forwarded over the external socket when provided.
- **Backend** ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/construction.py](ggblab/construction.py), [ggblab/parser.py](ggblab/parser.py)): Initializes a singleton `GeoGebra`, spins up a Unix-socket/TCP WebSocket server, registers the IPython Comm target, and drives the frontend command via ipylab. `ggb_comm.send_recv` waits for responses; `ggb_construction` loads multiple file formats (`.ggb`, zip, JSON, XML) and provides `geogebra_xml` + `ggb_schema` for converting construction XML to schema objects. `ggb_parser` analyzes object dependencies using NetworkX directed graphs.
- **Styles** ([style/index.css](style/index.css), [style/base.css](style/base.css)): Ensure the embedded applet fills the available area.

#### Communication Architecture

**Dual-channel design**: ggblab uses two communication channels between the frontend and backend:

1. **Primary channel (IPython Comm over WebSocket)**:
   - Handles command/function calls and event notifications
   - Managed by Jupyter/JupyterHub infrastructure with reverse proxy support
   - Connection health guaranteed by Jupyter/JupyterHub
   - **Limitation**: IPython Comm cannot receive messages while a notebook cell is executing

2. **Out-of-band channel (Unix Domain Socket on POSIX / TCP WebSocket on Windows)**:
   - Addresses the Comm limitation by enabling message reception during cell execution
   - Allows GeoGebra applet responses to be received even when Python is busy executing code
   - Connection is opened/closed per transaction (no persistent connection)
   - No auto-reconnection needed due to transient nature

This dual-channel approach ensures that interactive operations (e.g., retrieving object values, updating constructions) remain responsive even during long-running cell execution.

See [architecture.md](docs/architecture.md) for detailed design rationale and implementation notes.

##### Architecture Diagram

```mermaid
flowchart TB
   subgraph Browser
      FE[JupyterLab Frontend + GeoGebra Applet]
   end
   subgraph Server
      K[Python Kernel]
      S["Socket Bridge (Unix or TCP WebSocket)"]
   end
   FE -- "IPython Comm (WebSocket)\nvia JupyterHub proxy" --> K
   FE -- "Out-of-band socket (transient)" --> S
   S --- K
   FE -. "GeoGebra asset" .-> CDN[cdn.geogebra.org/apps/deployggb.js]
```

#### Security & Compatibility

- Reverse proxy-friendly: Operates over JupyterLab's IPython Comm/WebSocket within the platform's auth/CSRF boundaries.
- CORS-aware CDN: GeoGebra is loaded from `https://cdn.geogebra.org/apps/deployggb.js` as a static asset; no cross-origin API calls from the browser beyond this script.
- Same-origin messaging: Kernel↔widget interactions remain within Jupyter's origin; no custom headers or cookies required.
- Optional socket bridge: Transient Unix/TCP bridge opens per transaction and closes immediately to avoid long-lived external listeners; improves responsiveness during cell execution.
- JupyterHub readiness: Validated in managed JupyterHub (Kubernetes) behind reverse proxies.

#### Error Handling and Limitations

**Primary channel (IPython Comm)**: Error handling is managed automatically by Jupyter/JupyterHub infrastructure. Connection failures are detected and handled transparently; kernel status is visible in the JupyterLab UI.

**Out-of-band channel**: The secondary channel has a **3-second timeout** for receiving responses. If no response arrives within this window, a `TimeoutError` is raised in Python:

```python
try:
    result = await ggb.function("getValue", ["a"])
except TimeoutError:
    print("GeoGebra did not respond within 3 seconds")
```

**GeoGebra API constraint**: The GeoGebra API does **not** provide explicit error response codes. Instead, errors are communicated through **dialog popups** displayed in the browser. The frontend monitors these dialog events and forwards error information via the primary Comm channel. For errors that do not trigger dialogs (e.g., malformed responses), the timeout is the primary error signal.

See [architecture.md § Error Handling](docs/architecture.md#error-handling) for details on error detection and recovery strategies.

### Settings

The current settings schema ([schema/plugin.json](schema/plugin.json)) exposes no user options yet but is ready for future configuration.

### Development Workflow

```bash
pip install -e ".[dev]"
jupyter labextension develop . --overwrite
jlpm build           # or `jlpm watch` during development
jupyter lab          # run in another terminal
```

To remove the dev link, uninstall and delete the `ggblab` symlink listed by `jupyter labextension list`.

### Testing

**Automated Testing (GitHub Actions)**:
- Continuous integration configured via [.github/workflows/tests.yml](.github/workflows/tests.yml)
- Runs on `main` and `dev` branches on every push and pull request
- Tests across Python 3.10, 3.11, 3.12 on Ubuntu, macOS, and Windows
- Coverage reports uploaded to Codecov

**Running Tests Locally**:

```bash
# Install test dependencies
pip install -e ".[dev]"
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_parser.py -v

# Run with coverage report
pytest tests/ --cov=ggblab --cov-report=html
```

**Frontend Tests**:
- `jlpm install && jlpm test`

**Integration Tests (Playwright/Galata)**:
- See [ui-tests/README.md](ui-tests/README.md)
- Build with `jlpm build:prod`, then `cd ui-tests && jlpm install && jlpm playwright test`

### Release

See [RELEASE.md](RELEASE.md) for publishing to PyPI/NPM or using Jupyter Releaser; bump versions with `hatch version`.

### Known Issues and Gaps

#### Frontend Limitations

- **No explicit error handling UI**: Communication failures between frontend and backend are logged to console but not displayed to users. Currently relies on browser console for debugging.
- **Limited event notification**: Only monitors basic GeoGebra events (add/remove/rename/clear objects, dialogs). Advanced events like slider changes, conditional visibility toggles, or script execution results are not automatically propagated.
- **Hardcoded Comm target**: The Comm target name is hardcoded as `'test3'` with no option for customization without code changes.
- **TypeScript strict checks disabled**: Some type assertions use `any` type, reducing type safety. Widget props lack full interface documentation.
- **No input validation**: Commands and function arguments are not validated before sending to GeoGebra; invalid requests may cause silent failures.

#### Backend Limitations

- **Singleton pattern constraint**: Only one active GeoGebra instance per kernel session. Attempting to create multiple instances will reuse the same connection.
- **Out-of-band communication timeout**: The out-of-band socket channel has a 3-second timeout. If the frontend does not respond within this window, the backend raises a timeout exception.
- **Limited error handling on out-of-band channel**: GeoGebra API does not provide explicit error responses, so errors are communicated indirectly:
  - GeoGebra displays error dialogs (native popups) when operations fail (e.g., invalid syntax in algebraic commands)
  - The frontend monitors dialog events and forwards error messages via the primary Comm channel
  - Errors without a dialog (e.g., malformed JSON responses) result in timeout exceptions or silent failures
- **Parser subgraph extraction (`parse_subgraph()`) performance issues**:
  - **Combinatorial explosion**: Generates $2^n$ path combinations where $n$ = number of root objects. Performance degrades rapidly with 15+ independent roots.
  - **Infinite loop risk**: May hang indefinitely under certain graph topologies.
  - **Limited N-ary dependency support**: Only handles 1-ary and 2-ary dependencies; 3+ objects jointly creating an output are ignored.
  - **Redundant computation**: Neighbor lookups are recalculated unnecessarily in loops.
   - See [architecture.md § Dependency Parser Architecture](docs/architecture.md#dependency-parser-architecture) for detailed analysis and planned improvements.

#### General Limitations

- ✅ **Unit tests**: Comprehensive Python test suite with pytest (parser, GeoGebra applet, construction handling)
- ✅ **CI/CD pipeline**: Automated testing on all pull requests via GitHub Actions (Python 3.10+, multi-OS)
- 🔄 **Incomplete integration tests**: No Playwright tests yet for critical workflows (command execution, file loading, event handling)
- **Minimal documentation**: No dedicated developer guide beyond code comments; architecture rationale is not documented.

### Project Assessment (Objective)

- **Maturity**: Early-stage (0.x). Core functionality works for driving GeoGebra via dual channels, but lacks automated verification and release safeguards.
- **Strengths**: Clear architecture docs; dual-channel communication to mitigate Comm blocking; supports multiple file formats; dependency parser groundwork.
- **Key Risks**: No CI, low test coverage (unit/integration absent); parser `parse_subgraph()` has performance/loop risks on large graphs; hardcoded Comm target; minimal UX for error surfacing.
- **Maintainability**: TypeScript not strict; some `any` and limited input validation; parser algorithm needs replacement for scale.
- **Operational Gaps**: No monitoring/telemetry; no retry/backoff around sockets; release process manual.

### Future Enhancements and Roadmap

#### Short Term (v0.8.x)

1. **Error Handling & User Feedback**
   - Add user-facing error notifications for Comm/WebSocket failures
   - Improve out-of-band error reporting: detect timeout conditions and propagate as Python exceptions with context
   - Support for custom timeout configuration in `GeoGebra()` initialization
   - Enhanced error message recovery from GeoGebra dialog content
   - Provide more descriptive error messages in the UI when operations fail

2. **Parser Optimization** (`v0.7.3`)
   - Remove debug output; add optional logging via `logging` module
   - Add early termination check to detect infinite loops in `parse_subgraph()`
   - Cache neighbor computation to reduce redundant graph traversals
   - Extend N-ary dependency support (currently limited to 1-2 parents; should support 3+)

3. **Event System Expansion**
   - Subscribe to additional GeoGebra events (slider value changes, object property changes, script execution)
   - Expose event system to Python API via `ggb.on_event()` pattern
   - Log all events with timestamps for debugging

4. **Configuration & Customization**
   - Add settings UI to choose Comm target name and socket configuration
   - Allow custom GeoGebra CDN URL (for offline or private CDN scenarios)
   - Implement widget position/size preferences (split-right, split-left, tab, etc.)

#### Medium Term (v1.0)

1. **Type Safety & Code Quality**
   - Enable TypeScript strict mode and eliminate `any` types
   - Add JSDoc for all public TypeScript/Python APIs
   - Increase test coverage to >80% for both frontend and backend
   - Add comprehensive unit tests for parser, especially for edge cases and large graphs

2. **Parser Algorithm Replacement**
   - Replace `parse_subgraph()` with topological sort + reachability pruning approach
   - Reduce time complexity from $O(2^n)$ to $O(n(n+m))$
   - Support arbitrary N-ary dependencies (not limited to 2 parents)
   - Eliminate infinite loop risk through deterministic algorithm
   - See [architecture.md § Dependency Parser Architecture](docs/architecture.md#dependency-parser-architecture) for detailed design

3. **Advanced Features**
   - **Multi-panel support**: Allow multiple GeoGebra instances in different notebook cells
   - **State persistence**: Save/restore GeoGebra construction state to notebook or file
   - **Real-time collaboration**: Support multiple users viewing/editing the same construction
   - **Animation API**: Programmatic animation of objects with timeline control
   - **Custom tool definitions**: Allow users to define and persist custom GeoGebra tools

4. **Integration Improvements**
   - **Jupyter Widgets (ipywidgets) support**: Make GeoGebra embeddable in `ipywidgets` environments
   - **Matplotlib/Plotly integration**: Export construction data to visualization libraries
   - **NumPy/Pandas integration**: Bidirectional data sync with DataFrames

#### Long Term (v1.5+)

1. **Performance & Scalability**
   - WebSocket batching for high-frequency updates (e.g., animations)
   - Caching layer for repeated function calls
   - Support for serverless/container environments without persistent sockets
   - Memoization of subgraph extraction results

2. **ML/Data Science Features**
   - Built-in geometry solvers with numerical optimization (scipy integration)
   - Constraint solving interface
   - Interactive visualization of mathematical models

3. **Parser Enhancements**
   - Weighted edges representing construction order preference
   - Interactive subgraph selection UI
   - Integration with constraint solving for optimal construction paths
   - Interactive visualization of mathematical models

3. **Ecosystem & Standards**
   - JupyterHub compatibility testing and official support
   - Jupyter Notebook (classic) extension variant
   - Conda-forge packaging
   - Official plugin for popular JupyterLab distributions (JupyterHub, Google Colab, etc.)

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/xyz`)
3. Commit with clear messages
4. Run tests and linting: `jlpm lint && jlpm test`
5. Submit a pull request

For major changes, please open an issue first to discuss.

### License

BSD-3-Clause

## Cloud Deployment

This section outlines how to deploy and operate ggblab in common cloud setups. ggblab is a prebuilt JupyterLab 4 federated extension packaged in Python, so cloud installs typically require only `pip install ggblab`.

### JupyterHub (Kubernetes)

- Image bake (recommended): Add ggblab to your single-user image.

   ```dockerfile
   FROM quay.io/jupyter/base-notebook:latest
   RUN pip install --no-cache-dir ggblab
   ```

- Runtime install (quick test): From a user session terminal, install and restart the server.

   ```bash
   pip install -U ggblab
   jupyter labextension list | grep ggblab
   # Stop the server from the menu or via Control Panel, then start again
   ```

- Notes:
   - No Node.js or `jlpm build` is required in cloud environments; the extension is prebuilt and registered via Python packaging.
   - Verify installation with `jupyter labextension list` — ggblab should appear as enabled and OK.
   - If users share a base image, prefer baking ggblab into the image to avoid per-user installs.

#### Admin Tips (JupyterHub)

- Prefer image bake: reduce per-user variance and avoid cold-start installs.
- Restart single-user servers after runtime install: use Control Panel or admin culling to ensure extension loads.
- Ensure same environment: `pip` must target the environment used by `jupyter lab` (check `which jupyter` and `python -m site`).
- Allow egress to GeoGebra CDN: whitelist `cdn.geogebra.org` in cluster/network policies.
- Monitor logs: check Hub and single-user server logs for proxy/WebSocket errors during Comm operations.
- Version pinning: bake a specific ggblab version in images; use `pip install -U ggblab` only when you intentionally roll forward.
- Dev vs prod: reserve `pip install -e ".[dev]"` for development images; production should use pinned releases.
- No inbound ports: the out-of-band socket bridge is transient and initiated from the kernel; no extra public ports need exposure.



### Generic Cloud VM

- Install in your environment and start JupyterLab:

   ```bash
   pip install ggblab
   jupyter lab
   ```

### Troubleshooting

- Extension not visible:
   - Confirm JupyterLab >= 4 and that you are installing into the same environment used by JupyterLab.
   - Run `jupyter labextension list` to verify ggblab is enabled.
   - Fully restart JupyterLab; a simple browser refresh may not load new extensions.
- Network/CDN restrictions:
   - ggblab loads GeoGebra from `https://cdn.geogebra.org/apps/deployggb.js`. Ensure your cluster egress policy allows this domain.
- Communication checks:
   - ggblab uses IPython Comm and an optional socket bridge. These work in managed JupyterHub environments; if you see timeouts, check proxy/network policies and consider increasing operation timeouts.

For detailed deployment guidance, environment checks, common pitfalls, and verification steps, see [docs/cloud-deployment-guide.md](docs/cloud-deployment-guide.md).
