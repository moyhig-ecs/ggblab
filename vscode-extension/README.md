VS Code extension for GGBlab

Build and run:

1. From `vscode-extension` install dependencies:

```bash
cd vscode-extension
npm install
```

2. Build the webview bundle and the extension:

```bash
npm run build:webview
tsc -p ./
```

3. Open this folder in VS Code (the repository root), press F5 to run the extension in the Extension Development Host.

Notes:
- The webview bundle entry imports `../../src/components/GGAComponent` from the workspace. Ensure dependencies (React, @jupyterlab/services) are installed in `vscode-extension` before building.
- The webview shows a simple connect form for local Jupyter (base URL and token) and mounts `GGAComponent` once loaded.
