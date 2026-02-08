# GeoGebra Injector (vscode-extension)

This folder contains the VS Code extension that opens a webview and injects a GeoGebra applet for debugging.

Extension ID: `moyhig.geogebra-injector` (publisher: `moyhig`, name: `geogebra-injector`)

Quick build & package

1. Build the web bundle (produces `dist/bundle.js`):

```bash
cd vscode-extension
npm install   # if needed the first time
npm run build
```

2. Prepare and package (automated: sync version from top-level and build):

```bash
cd vscode-extension
npm run package:vsce
```

This runs `scripts/sync-version.js` to copy the top-level `package.json` `version` into this package, runs the build, then runs `vsce package`.

Install the generated VSIX locally:

```bash
code --install-extension geogebra-injector-<version>.vsix
```

Notes
- Ensure `vsce` is available on PATH for `npm run package:vsce` to succeed.
- Adjust `.vscodeignore` if the produced VSIX still contains unnecessary files.
- To publish to the Marketplace you need a publisher account; the extension ID will be `ggblab.geogebra-injector` when publishing.
# GGBlab Applet Injector (VS Code Extension)

This is a minimal VS Code extension that opens a Webview and injects a GeoGebra applet for quick debugging.

Usage

- Open the command palette (Cmd+Shift+P) and run `GGBlab: Open Applet Webview`.

Notes

- This extension is intentionally minimal and loads the GeoGebra CDN script `https://cdn.geogebra.org/apps/deployggb.js` inside the webview.

Building a React bundle (optional)

1. Install a bundler, for example `esbuild`:

```bash
cd vscode-extension
npm init -y
npm install --save-dev esbuild react react-dom
```

2. Add a build script to produce `dist/bundle.js` from `src/index.tsx`, for example:

```bash
npx esbuild src/index.tsx --bundle --outfile=dist/bundle.js --loader:.tsx=tsx --platform=browser
```

3. Modify `extension.js` webview HTML to load `dist/bundle.js` from the extension's files (use `webview.asWebviewUri` when producing the webview HTML in a real extension).

The `src/` folder contains `index.tsx` and `widget.tsx` as the React entry and component to be bundled.

Notebook quick-start
--------------------

You can open the Applet Webview directly from a Jupyter notebook cell using a `vscode:` command URI. Click the link below (or generate it programmatically) to call the extension command `ggblab.openApplet` and open the webview.

Python (IPython) example:

```python
from IPython.display import HTML, display
import json, urllib.parse

args = {
	"kernelId": "",            # optional
	"commTarget": "jupyter.ggblab",
	"socketPath": "",         # optional
	"serverUrl": ""           # optional
}
payload = urllib.parse.quote(json.dumps(args))
url = "vscode:command/ggblab.openApplet?" + payload
display(HTML(f'<a href="{url}">Open GGBlab Applet (Webview)</a>'))
```

Notes:
- Keep the payload minimal and avoid embedding secrets (tokens) directly in the URI.
- The extension will prompt for missing connection details when needed and will post `serverSettings` to the webview once it is ready.

Important notes about VS Code / Notebook integration
--------------------------------------------------

Due to platform constraints, the VS Code extension cannot always obtain per-notebook kernel connection details automatically. There are two supported ways to pass connection settings to the extension:

- Clipboard: copy a JSON blob containing the connection info (e.g. `{"kernelId":"...","socketPath":"...","serverUrl":"..."}`) into the clipboard, then click the extension's **GGBlab Open** status item in VS Code. The extension prefers clipboard JSON when present.
- Workspace file: write a `.vscode/ggblab.json` in your workspace containing the same JSON. The extension will search workspace folders for this file and use it as a fallback.

Why this is required
--------------------
VS Code's built-in Notebook link handling does not always pass complex JSON payloads through `command:` URIs in all environments. Where available, the Microsoft `vscode-jupyter` extension exposes APIs such as `getServerUriForNotebook` that can supply notebook-scoped server information. If Microsoft provides an API key or your environment supports `vscode-jupyter`’s notebook-scoped API, the extension can be integrated to obtain settings automatically — contact Microsoft or watch the repo for updates.

How to use clipboard flow from a notebook
----------------------------------------
In a notebook cell, run the small helper that prints and copies the connection JSON (the `GeoGebra().init(use_vscode=True)` helper attempts to write `.vscode/ggblab.json` and copy settings to the clipboard when available). Alternatively, generate and copy the JSON manually and then click **GGBlab Open** in VS Code.

Security note
-------------
Do not place long-lived tokens in clipboard or checked-in workspace files. Prefer ephemeral CLI tokens or secrets stored in VS Code `SecretStorage` when possible. The extension moves tokens from `.vscode/ggblab.json` into SecretStorage when available.
