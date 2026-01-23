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

ggblab embeds a GeoGebra applet into JupyterLab and provides a compact, async Python API to send commands and call GeoGebra functions. Open a panel from the Command Palette or from Python (`GeoGebra().init()`), interact with the applet visually, and drive it programmatically from notebook code.



### Features

- **Dual Coding System**: Geometric visualization + Python code in a unified workspace—students learn through both visual and symbolic representations
 - Programmatic launch via `GeoGebra().init()` (recommended), which uses ipylab to pass communication settings before widget initialization (Command ID: `ggblab:create`, label: "React Widget"). Use the Command Palette to open a panel; the Launcher tile has been removed.
- Call GeoGebra commands (`command`) and API functions (`function`) from Python through the `GeoGebra` helper
- **Domain Bridge**: Construction dependencies in GeoGebra map isomorphically to variable scoping in Python—teach computational thinking through geometric structure
- **Transfer of Learning**: Knowledge learned in geometric context transfers to computational thinking and vice versa. Dual representations strengthen understanding across both domains.
- **ML-ready parser outputs**: The parser enriches the construction DataFrame with production-ready features (e.g. `Sequence`, `DependsOn`, `DependsOn_minimal`) that are stored as native Polars types and are directly usable for feature engineering, graph models, and inference pipelines — see [Parser outputs for ML / Inference](#parser-outputs-for-ml--inference).
 - **Communication and events**: ggblab uses a dual-channel design — an IPython Comm (`ggblab-comm`) per notebook kernel plus an out-of-band socket (Unix domain socket or WebSocket) for larger messages and event transport. The frontend watches applet events (add/remove/rename/clear and dialog messages) and forwards them to the kernel over these channels.

    By design, a notebook kernel drives one side-by-side GeoGebra applet via a single Comm; other notebooks can open and drive their own applets. Controlling multiple applets from the same kernel is possible in principle but is not enabled by default—implementations will be considered if a clear use case is proposed.

    (Design note: this avoids message correlation issues because IPython Comm cannot receive during cell execution and asyncio send/receive logic relies on a single shared buffer. See [ggblab/utils.py section 8](ggblab/utils.py) and [architecture.md](docs/architecture.md#asyncio-design-challenges-in-jupyter) for details.)

### Requirements

- JupyterLab >= 4.0
- Python >= 3.10
- Browser access to https://cdn.geogebra.org/apps/deployggb.js
 - For development: Node.js may be useful; `jlpm` is not required for classroom installs. Follow the Development Workflow for optional build steps.

## 📦 Package Ecosystem

ggblab consists of two packages:

### **ggblab** (Core) — JupyterLab Extension
Interactive GeoGebra widgets with bidirectional Python ↔ GeoGebra communication.

**Core features (this repo):**
- Embedded GeoGebra applet in JupyterLab
- Dual-channel communication: a per-kernel IPython Comm (`ggblab-comm`) plus an out-of-band socket (Unix domain socket or WebSocket)
- Async Python API to send commands and call GeoGebra functions; frontend watches applet events and forwards them to the kernel
- .ggb file I/O (`ggb_file`, alias `ggb_construction`)
- Design note: one Comm per notebook kernel drives one side-by-side applet by default; other notebooks can open their own applets. Multi-applet-from-one-kernel is not enabled by default.

### **ggblab_extra** — Analysis & Educational Tools

> **Note**: The optional `ggblab_extra` package (import name `ggblab_extra`) is
> currently undergoing restructuring and will be republished soon as a standalone
> package or distribution. The core `ggblab` package remains lightweight; import
# ggblab

[![PyPI](https://img.shields.io/pypi/v/ggblab.svg)](https://pypi.org/project/ggblab/)
[![Python](https://img.shields.io/pypi/pyversions/ggblab.svg)](https://pypi.org/project/ggblab/)
[![Tests](https://github.com/moyhig-ecs/ggblab/actions/workflows/tests.yml/badge.svg)](https://github.com/moyhig-ecs/ggblab/actions/workflows/tests.yml)
[![Documentation Status](https://readthedocs.org/projects/ggblab/badge/?version=latest)](https://ggblab.readthedocs.io/en/latest/?badge=latest)

Compact overview and quick guide for contributors and users.

ggblab embeds a GeoGebra applet into JupyterLab and provides an asynchronous Python API to
drive the applet programmatically from notebooks. It is intended for teaching geometry
side-by-side with Python and for producing reproducible construction datasets useful for
analysis and ML workflows.

--

## Quick Links

- Documentation: https://ggblab.readthedocs.io/
- Examples & notebooks: [examples/](examples/)
- Demo (Binder): see [binder/README.md](binder/README.md)
- Blog / News: [blog/README.md](blog/README.md)

## Key Features

- Side-by-side GeoGebra applet embedded in JupyterLab.
- Async Python API: send algebraic commands and call GeoGebra functions from notebooks.
 - Async Python API: send algebraic commands and call GeoGebra functions from notebooks.
- Dual-channel communication: IPython Comm for normal messages and an optional
   out-of-band socket for responsiveness during cell execution.
- Construction I/O: load/save `.ggb` (base64 zip), XML, JSON, and normalized DataFrame
   outputs (Polars) for analysis and ML.
- Rich error-handling and pre-flight validation to catch many issues before execution.

## Installation

Recommended (end users / JupyterHub):

```bash
pip install ggblab
```

Development (edit & test locally):

```bash
pip install -e ".[dev]"
jupyter labextension develop . --overwrite
jlpm build   # optional: only needed for frontend changes
jupyter lab
```

Notes:
- For managed JupyterHub deployments, `pip install ggblab` is usually sufficient —
   no manual `jlpm` steps are required.

## Quick Start (Python)

In a notebook cell:

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()    # initialize comm/socket and open the applet panel

await ggb.command("A = (0,0)")
val = await ggb.function("getValue", ["A"])
print(val)
```

Tips:
- Run `await ggb.init()` in its own cell and wait for completion before sending commands.
- Each GeoGebra panel shows the kernel id (first 8 chars) to help match notebooks↔applets.

## Examples

- See [examples/example.ipynb](examples/example.ipynb) for a basic demo.
- `ggblab_extra` contains advanced parsing and scene-development tools: see
   [ggblab_extra/README.md](./ggblab_extra/README.md).

### Plotting: Matplotlib vs GeoGebra

If you use SymPy to generate numeric samples, you can render them either with
classic Python plotting libraries (e.g. Matplotlib) or with an interactive
GeoGebra panel. See [examples/eg7_plotting.ipynb](examples/eg7_plotting.ipynb)
for a short English example that:

- Shows how to sample a SymPy expression with `lambdify` and `numpy.linspace`.
- Renders the same samples with Matplotlib (static) and with GeoGebra (interactive
   `LineGraph` or list-based import).
- Demonstrates capturing a GeoGebra PNG via `getPNGBase64` and displaying it
   inside the notebook.

This comparison is useful for deciding whether to prioritize static publication
quality (Matplotlib) or interactive student exploration (GeoGebra).

## Development & Testing

Run Python tests:

```bash
pip install -e ".[dev]" pytest pytest-cov
pytest tests/ -v
```

Frontend tests and tasks (only for frontend development):

```bash
jlpm install
jlpm test
jlpm build
```

CI: GitHub Actions runs tests and coverage on PRs — see `.github/workflows/tests.yml`.

## Documentation

Full docs are in `docs/` and published at https://ggblab.readthedocs.io/.
Start at [docs/index.md](docs/index.md) or the high-level [philosophy](docs/philosophy.md).

## Contributing

1. Fork and create a feature branch.
2. Run tests and linters locally.
3. Open a PR with a clear description and tests where applicable.

For large changes, please open an issue first to discuss design.

## License

BSD-3-Clause

--

If you want, I can now:

- run a quick markdown preview or lint
- update `README.md` further with more examples or screenshots
- create a commit and open a PR draft

Which should I do next?
  - Implementation roadmap and quick reference

### Quick Reference

| Document | Primary Audience | Key Insight |
|----------|-----------------|-------------|
| **[ggblab_extra: SCENE_DEVELOPMENT_QUICK_START.md](./ggblab_extra/docs/SCENE_DEVELOPMENT_QUICK_START.md)** | **Educators, textbook authors** | **How to use ggblab with textbook-2025** |
| **[ggblab_extra: geometric_scene_development_guide.md](./ggblab_extra/docs/geometric_scene_development_guide.md)** | **Educators, textbook authors** | **Complete framework for 15-chapter curriculum** |
| **[docs/scoping.md](docs/scoping.md)** | Educators, Students | Geometric construction teaches programming scoping |
| **[docs/philosophy.md](docs/philosophy.md)** | Contributors, Researchers | ggblab = GeoGebra → Timeline → Manim → Video pipeline |
| **[ggblab_extra/docs/sympy_integration.md](./ggblab_extra/docs/sympy_integration.md)** | Math/CS Instructors | Symbolic proof + code generation + manim export |
| **[docs/architecture.md](docs/architecture.md)** | Developers | Dual-channel communication (core) |
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

### Construction I/O (example)

Use `ConstructionIO` (preferred) to build a normalized Polars DataFrame from a `.ggb`
file or directly from a running applet. `DataFrameIO` is kept as a compatibility alias.

```python
from ggblab.construction_io import ConstructionIO

# From a .ggb file (requires a GeoGebra runner instance)
df_from_file = await ConstructionIO.initialize_dataframe(
   ggb, file='path/to/example.ggb',
   _columns=ConstructionIO.COLUMNS + ["ShowObject", "ShowLabel", "Auxiliary"]
)

# Or build from the running applet state
df_from_applet = await ConstructionIO.initialize_dataframe(ggb, use_applet=True)

print(df_from_file.head())
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

### Object Dependency Analysis (ggblab_extra)

Advanced parsing, dependency graphs, and subgraph extraction now live in
**ggblab_extra**. See [ggblab_extra/README.md](./ggblab_extra/README.md) and the

scene development docs in `ggblab_extra/docs/` for full usage and examples.

### Architecture

- **Frontend** ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx)): Registers the plugin `ggblab:plugin` and command `ggblab:create`. Creates a `GeoGebraWidget` ReactWidget that loads GeoGebra from the CDN, opens an IPython Comm target (default `test3`), executes commands/functions, and mirrors add/remove/rename/clear events plus dialog notices back to the kernel. Results can also be forwarded over the external socket when provided.
- **Backend** ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/file.py](ggblab/file.py)): Initializes a singleton `GeoGebra`, spins up a Unix-socket/TCP WebSocket server, registers the IPython Comm target, and drives the frontend command via ipylab. `ggb_comm.send_recv` waits for responses; `ggb_file` (alias `ggb_construction`) loads multiple file formats (`.ggb`, zip, JSON, XML) and provides `geogebra_xml` + `ggb_schema` for converting construction XML to schema objects. Advanced parsing and verification live in `ggblab_extra`.
- **Styles** ([style/index.css](style/index.css), [style/base.css](style/base.css)): Ensure the embedded applet fills the available area.

**Browser reload & state restoration**

- What happens: A full browser reload or JupyterLab restart destroys the front-end JavaScript context (DOM and in-memory applet instances).

- Why: The browser resets the JS runtime; Lumino's `ILayoutRestorer` recreates widgets by invoking the saved command, but it does not preserve prior in-memory objects.

- Consequence: Kernel connections (`kernelId`) persist on the server, but GeoGebra applets are re-created in the client. A dispose→create cycle on reload is unavoidable.

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

## Note about legacy `parse_subgraph`

The `ggblab_extra.construction_parser` module preserves the original
``parse_subgraph`` heuristic under the name ``parse_subgraph_legacy()`` for
reproducibility and compatibility. The legacy function retains the
human-oriented search strategy and original control flow; it is kept
because some users prefer its behavior.

Prefer the refactored ``parse_subgraph()`` for new development — it uses
clearer variable names, removes debug output, and is easier to maintain.
Call ``parse_subgraph_legacy()`` only when you specifically need the legacy
behavior.

## Parser outputs for ML / Inference

ggblab does more than visualize geometry — it converts constructions into
first-class, production-ready datasets for machine learning and inference.

- Rich, ML-friendly features: the parser annotates the construction
   DataFrame with engineered columns such as ``Sequence``, ``DependsOn``,
   and ``DependsOn_minimal`` that encode ordering, full ancestor lists,
   and compact parent sets respectively.
- Native Polars types: all metadata are stored as proper Polars types
   (including list/Utf8 columns) so they integrate directly with
   feature pipelines, graph neural networks, and downstream model
   orchestration tools without ad-hoc conversion.
- Persisted for reproducibility: use ``ConstructionIO.save_dataframe`` to
   persist datasets (Parquet primary, JSON fallback). Parquet is the
   recommended format for ML workflows for its schema fidelity and
   efficient I/O.

Use ggblab to transform geometric constructions into predictable,
repeatable feature sets — ready for feature engineering, GNN inputs,
or any inference pipeline you build on top of geometric structure.

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
