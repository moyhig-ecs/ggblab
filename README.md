# ggblab

GeoGebra applets in Jupyter notebooks, driven from Python and Julia kernels.

This is **version 2** (`2.0.0rc1`, a release candidate). It is a rewrite, not an upgrade of 1.x: see
[Relation to version 1](#relation-to-version-1).

## What it is

- The applet is mounted by a trusted HTML output of a notebook cell. There is no JupyterLab extension to build or install.
- The kernel talks to the applet through a mailbox on its own Jupyter server (`ggblab.host.relay`, a server extension).
  The kernel is an HTTP client of that server. No comm, no comm target, no ipywidgets.
- The same mailbox and the same JavaScript serve every kernel language. Python and Julia hosts are included.
- The interface is a closed set of eight verbs over the GeoGebra Apps API: four writes (`eval`, `new`, `delete`, `xml_in`),
  three reads (`xml_out`, `value`, `kind`) and one subscription (`listen`).
- Constructions written as text are parsed by a closed-world parser: 28 GeoGebra commands, labels referenced as `:label`.
  An unknown command is an error, not a guess.

## Install

Python 3.11 or later.

```bash
pip install ggblab==2.0.0rc1            # the core: applet host, server extension, parser
pip install "ggblab[extra]==2.0.0rc1"   # plus ggblab_extra: construction I/O, geometry IR, SymPy objects
pip install "ggblab[examples]==2.0.0rc1" # plus what the notebooks in examples/ import (matplotlib, networkx, numpy)
```

Without a version, `pip install ggblab` installs 1.8.1 while 2.0.0 is a release candidate.

The server extension is enabled by the installation. Check it, then restart the Jupyter server:

```bash
jupyter server extension list        # expect: ggblab.host.relay enabled, OK
```

## Quick start

### Python

```python
from ggblab import GeoGebra

g = GeoGebra(appName="suite", showAlgebraInput=True)
g                                   # displaying g mounts the applet in this cell's output
```

```python
g.command("O = (0, 0)", "c1 = Circle(O, 1)", "A = (1, 0)", "c2 = Circle(A, 1)",
          "l1 = {Intersect(c1, c2)}", "a = Length(l1)")     # one reply entry per command
g.value("a")                        # 2
g.xml()                             # the construction as GeoGebra XML
g.events()                          # what happened in the applet since the last call
```

A cell magic takes the construction as text:

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

### Julia

The Julia host is two files inside the installed Python package. It needs the Julia packages `JSON` and `IJulia`; the
string macro also needs `PythonCall`.

```julia
host = strip(read(`python -c "import ggblab, pathlib; print(pathlib.Path(ggblab.__file__).parent / 'julia' / 'host')"`, String))
include(joinpath(host, "html_host.jl")); using .GGBLabHost

g = GeoGebra(appName="suite", showAlgebraInput=true)
g
```

```julia
command(g, "O = (0, 0)", "c1 = Circle(O, 1)", "A = (1, 0)", "c2 = Circle(A, 1)", "l1 = {Intersect(c1, c2)}", "a = Length(l1)")
value(g, "a")
```

```julia
include(joinpath(host, "ggb_macro.jl")); using .GGBLabMacro
ggb"""
A = (0, 0)
c = Circle(:A, 1)
"""g
```

The notebooks in `examples/` show more. eg1 and eg2 need no server and no applet.

| notebook | what it shows |
|---|---|
| eg1, eg2 | reading a `.ggb` file; the construction XML as a Python dict |
| eg3 | the verbs, one by one |
| eg4 | errors |
| eg5 | the construction as a data frame |
| eg6 | the parser |
| eg7 | plotting |
| eg8, eg10 | sliders: the kernel reacts to changes made in the applet |
| eg9 | listeners and events |
| eg11 | a longer construction |
| julia_host, julia_macro | the Julia host and the string macro |

## Where it runs

| | Python kernel | Julia kernel |
|---|---|---|
| JupyterLab | yes | yes |
| JupyterHub on Kubernetes | yes (checked 2026-09-15) | yes (checked 2026-09-15) |
| VS Code notebooks | not yet | not yet |

Version 1 has an experimental VS Code extension. Version 2 does not support VS Code notebooks yet.

## Known limitations

- **Trusted output.** The applet is mounted by a script in the cell output. The notebook has to be trusted.
- **One machine.** The kernel and the Jupyter server are assumed to run on the same machine or in the same container.
- **Reply of `command`.** Each entry is one of three things: the labels GeoGebra returned, `None` when GeoGebra refused
  the command (see `g.errors()`), or `{"error": …}` when the Apps API threw for that command.
- **Commands outside the 28.** The parser rejects them. Examples met in course material and not yet supported:
  `IntersectPath`, `Element`, `SetCoords`. Send such commands with `g.command(...)`.
- **An upper-case label followed by `(`** is read as a command, for example `L1(1)`. Name the list in lower case.
- **No `$` interpolation** in the `%%ggb` cell and in the `ggb"…"` string.
- **Not among the eight verbs.** Showing or hiding a layer (`setLayerVisible`) and reading the applet state as a file
  (`getBase64`). Visibility of one object can be changed by editing the XML (see `examples/eg3`).
- **The layout of a file is not applied.** A GeoGebra document carries, in its `<gui>` element, the layout it was saved
  with (which views are open, the input bar). `g.set_xml(xml)` leaves that element out, so the applet keeps its own layout;
  `g.set_xml(xml, gui=True)` sends the document as it is. A file saved with the algebra view closed then closes the side
  panel, and sending XML again does not reopen it.
- **`.ggb` files are read, not written.** A `.ggb` file depends on the order of its XML elements and carries the state
  of the user interface besides the construction. Version 2 works on the construction only.
- **Julia module names** (`GGBLabHost`, `GGBLabMacro`) may change before 2.0.0.

## Tests

The tests read fixtures by paths relative to the repository, so they run in a source tree, not against an installed wheel.

```bash
pip install -e ".[extra,test]"
pytest -q tests          # 66 tests; five of them start Julia and are skipped where Julia is absent
```

## Relation to version 1

Version 1 (1.8.1) used a comm and a JupyterLab extension. Version 2 replaces both and has no compatibility layer:
`await GeoGebra().init()`, `ggb.function(...)` and the implicit applet of the `%%ggb` magic are gone.
Version 1 stays available as it is: `pip install "ggblab<2"`.

## License

BSD 3-Clause, see [LICENSE](LICENSE).

GeoGebra itself is not part of this package. The applet is loaded from GeoGebra's servers under
[GeoGebra's own license](https://www.geogebra.org/license), which is free for non-commercial use.

## How this version was written

<!-- draft wording; the author's text replaces it before the release -->

Version 2 was written with AI assistance. The author decided the design, the order of the stages and the acceptance
criteria, and ruled on every open question. The code, the tests and the documentation were drafted by an AI coding agent
(Anthropic Claude, through Claude Code) and accepted only after the example notebooks and the test suite reproduced the
recorded results. Version 1 was written by the author, from January 2026 with the help of GitHub Copilot.
