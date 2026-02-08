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
