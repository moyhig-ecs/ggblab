# Changelog

## 2.0.0rc1 (not yet released)

Version 2 is a rewrite. It does not read or extend version 1's code, and there is no compatibility layer.

### Changed, compared with 1.8.1

| | 1.8.1 | 2.0.0rc1 |
|---|---|---|
| Kernel to applet | a comm and a control socket | HTTP to a mailbox on the kernel's own Jupyter server (`ggblab.host.relay`) |
| Front end | a JupyterLab extension, built with Node.js | a trusted HTML output; nothing to build |
| Widgets | ipywidgets | none (an anywidget adapter is kept for marimo; import it explicitly) |
| Calls | `await ggb.command(...)`, `await ggb.function(name, args)` | synchronous; eight verbs: `command`, `new_construction`, `delete`, `set_xml`, `xml`, `value`, `kind`, `listen` |
| Start | `ggb = await GeoGebra().init()` opens a side panel | `g = GeoGebra(...)`; displaying `g` mounts the applet in the cell output |
| Applet address | the object | the document: one live applet per notebook |
| `%%ggb` magic | finds an implicit applet | the host is named on the magic line: `%%ggb g` |
| Construction text | tokenizer; unknown input passed through | closed-world parser: 28 commands, `:label` references, unknown command is an error |
| Relative references `_`, `__`, `_N` | accepted | rejected (`RelativeReference`) |
| Julia | `@ggb` expression macro | `ggb"…"` string macro; the text goes to the same Python parser |
| Packaging | version from `package.json` | version in `pyproject.toml`; pure Python wheel |
| Python | 3.10 or later | 3.11 or later |

### Added

- `ggblab.host.relay`: the server extension. It is enabled by installing the package.
- The Julia host and the string macro, shipped inside the Python package (`ggblab/julia/host/`).
- `ggblab_extra`: construction I/O, the geometry IR and SymPy objects. Install with `ggblab[extra]`.
- JupyterHub on Kubernetes: the kernel finds its server from `JUPYTERHUB_SERVICE_URL` and `JUPYTERHUB_API_TOKEN`.

### Fixed before the release

- `set_xml` leaves out the `<gui>` element of the document. Sent as it is, a file saved with the algebra view closed closed
  the side panel of the applet. `set_xml(xml, gui=True)` sends the document unchanged. Python and Julia hosts.
- A request could be served by an applet that was no longer on the page: when the cell that mounts the applet was run
  again, the poller of the replaced output, parked in its long poll, took the next request. It now hands the request to
  the applet that replaced it.

### Examples

- eg1, eg2 and eg3 are rewritten for version 2. eg4 to eg11 and the two Julia notebooks no longer contain paths of the
  development machine. The notebooks that served as acceptance checks of the stages moved to `probes/notebooks/`,
  the version 1 originals to `probes/v1_examples/`.
- Extra `examples`: everything the notebooks import.

### Removed

- The JupyterLab extension and the Node.js build.
- The comm target and the control socket.
- `GeoGebra().init()`, `ggb.function(...)`, `ggb.file`, `ggb.parser.tokenize`.

### Not in this release

- VS Code notebooks.
- Commands outside the 28 in the parser (for example `IntersectPath`, `Element`, `SetCoords`).
- Writing a `.ggb` file, `setLayerVisible`, `getBase64`.
