# Webview Debugging — Quick Notes

- Always open the Webview DevTools before reloading the webview. Open DevTools via:
  - Command Palette: `Developer: Open Webview Developer Tools` (with the Webview focused), or
  - Shortcut: `⌘⌥I` (macOS) when the Webview has focus.

- After rebuilding the extension bundle (`vscode-extension`):

```bash
# in workspace root
conda activate py314   # if using conda env
cd vscode-extension
npm run build          # or npm run watch during development
```

- Then reload the Extension Development Host (EDH):
  - In the host window: `Developer: Reload Window`, or restart EDH via F5 in your main VS Code window.
  - If DevTools is open, reload the Webview (⌘R) while DevTools remains focused so source maps resolve.

- If you expect source-mapped files but they don't appear in `Sources`:
  - Make sure DevTools was open before the reload.
  - Confirm `dist/bundle.js` and `dist/bundle.js.map` exist in the extension folder.
  - Check `ggblab` Output channel for `Checking for bundle at` log to confirm the webview URL.

- Notes about `socketPath` and kernel/server settings:
  - Server settings are injected into the webview via `window.__GGBlab_ServerSettings` by the extension host.
  - The widget will read `serverSettings.socketPath` or the `socketPath` passed to the widget; if missing, the widget may not create kernel comms.
  - If `resources.socketPath` appears empty, ensure `serverSettings` contains `socketPath`, rebuild, and re-open the webview.

These steps avoid the common pitfall where DevTools cannot map bundle → source because DevTools was opened after load, or the EDH was not reloaded after building the bundle.
