# Changelog

## Unreleased (toward 2.0.0rc2)

- The relay serves a holder page: `GET ggblab/holder?mount=<box>` returns a same-origin page with the same `div` and the
  same `mount.js` a notebook output gets, with no CSP sandbox, so a headless browser, an app's webview or a phone can
  hold the applet of a box without a notebook. Opened with `?token=`, the page carries the token; opened by a logged-in
  user, it uses the cookie.
- The relay keeps each box's state: the latest XML (asked of the holder after every state-changing request) and the log
  of those requests. A new holder's first poll carries a `restore`, applied before any request is served: taking over a
  box now carries the construction (a page reload, or a page opened after a headless holder, shows what was drawn).
  `GET ggblab/state?mount=<box>` returns the box's copy.
- Two projection verbs: `png` (`getPNGBase64`) and `svg` (`exportSVG`) — `g.png()` returns PNG bytes, `g.svg()` SVG text;
  the same in Julia. Ten verbs now (the code-graph probe's allow-list records the fourth state).
- The Julia host can be installed as a Julia package: `julia/Project.toml` (`GGBLab`, provisional name) wraps the same
  two files the wheel ships; `Pkg.test` runs offline tests; the mount JavaScript is looked up at the first mount (also
  through the installed Python package `ggblab`, or `GGBLAB_MOUNT_JS`), no longer read when the file is loaded.

## 2.0.0rc1 (2026-09-29)

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

### Documentation

- `docs/` for Read the Docs (Sphinx, MyST). The copyright line of `LICENSE` names the author; the license is unchanged.

### Removed

- The JupyterLab extension and the Node.js build.
- The comm target and the control socket.
- `GeoGebra().init()`, `ggb.function(...)`, `ggb.file`, `ggb.parser.tokenize`.

### Not in this release

- VS Code notebooks.
- Commands outside the 28 in the parser (for example `IntersectPath`, `Element`, `SetCoords`).
- Writing a `.ggb` file, `setLayerVisible`, `getBase64`.
