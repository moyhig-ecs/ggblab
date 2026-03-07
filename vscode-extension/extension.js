const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
// Create an OutputChannel for ggblab logs
let ggblabOutput = null;

function getWebviewContent(bundleScriptUrl, serverSettingsJson, autoInit) {
  // If a bundleScriptUrl is provided, load the bundle which should mount
  // the React widget into `#ggb-mount`. Otherwise fall back to the inline
  // minimal HTML that injects deployggb.js directly.
  if (bundleScriptUrl) {
    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>GGBlab Applet</title>
    <script>window.ggblabDebugMessages = false;</script>
    <style>
      html,body,#ggb-container{height:100%;margin:0;padding:0}
      /* Stretch the applet vertically to fill the webview area and center horizontally */
      #ggb-container{width:100%;height:100%;display:flex;align-items:stretch;justify-content:center}
      /* Make applet container responsive so the applet can grow with the panel */
      .applet-wrapper{width:100%;height:100%;max-width:100%;align-self:stretch}
    </style>
  </head>
  <body>
      <!-- root removed: mounting uses #ggb-mount instead -->
      <div id="ggb-container">
        <div id="ggb-mount" class="ggb-mount"></div>
      </div>

    ${serverSettingsJson ? `<script>window.__GGBlab_ServerSettings = ${serverSettingsJson}; window.__GGBlab_AutoInit = ${autoInit ? 'true' : 'false'};</script>` : ''}
    <script src="${bundleScriptUrl}"></script>
  </body>
</html>`;
  }

  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>GGBlab Applet - Bundle Missing</title>

    <style>
      body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;margin:24px}
      pre{background:#f6f8fa;padding:12px;border-radius:6px}
      .box{max-width:760px}
    </style>
  </head>
  <body>
    <div class="box">
      <h2>GGBlab: bundle.js not found</h2>
      <p>The React bundle <code>dist/bundle.js</code> was not found in the extension folder.</p>
      <p>Build the bundle locally and reload the Extension Development Host:</p>
      <pre>cd vscode-extension
npm install --save-dev esbuild react react-dom
npx esbuild src/index.tsx --bundle --outfile=dist/bundle.js --loader:.tsx=tsx --platform=browser</pre>
      <p>After building, reload the Extension Development Host window (Developer: Reload Window) and re-run the command.</p>
    </div>
  </body>
</html>`;
}

function activate(context) {
  // Create an OutputChannel so debug logs are visible in Output > ggblab.
  // In production this is lightweight; keep enabled to aid debugging.
  try {
    ggblabOutput = vscode.window.createOutputChannel('ggblab');
    ggblabOutput.appendLine('ggblab: activate');
  } catch (e) {
    // Fallback to no-op if OutputChannel creation fails in restricted hosts
    ggblabOutput = { appendLine: () => {} };
  }
  // Probe for MS Jupyter extension or workspace jupyter settings to infer
  // remote kernel connection info (best-effort). This allows us to prefill
  // baseUrl/token or a serverUrl so users don't need to re-enter them.
  // Lightweight probe for MS Jupyter extension. Keep minimal and stable so
  // future work can re-introduce deeper heuristics without noisy output.
  const probeMsJupyter = async () => {
    try {
      const candidates = ['ms-toolsai.jupyter', 'ms-toolsai.vscode-jupyter'];
      ggblabOutput?.appendLine('probeMsJupyter: probing jupyter extensions');
      for (const id of candidates) {
        try {
          const ext = vscode.extensions.getExtension(id);
          if (!ext) continue;
          let api = null;
          try { api = await ext.activate(); } catch (e) { ggblabOutput?.appendLine(`probeMsJupyter: activate ${id} failed: ${String(e)}`); }
          if (!api) continue;

          // Prefer notebook-scoped API if available
          if (typeof api.getServerUriForNotebook === 'function') {
            try {
              const uri = await api.getServerUriForNotebook();
              if (uri) return (typeof uri === 'string') ? { serverUrl: uri } : { serverUrl: uri.serverUrl || uri.serverUri || uri.baseUrl || null, token: uri.token || uri.authToken || null };
            } catch (e) {}
          }

          if (typeof api.getServerUri === 'function') {
            try {
              const uri = await api.getServerUri();
              if (uri) return (typeof uri === 'string') ? { serverUrl: uri } : { serverUrl: uri.serverUrl || uri.serverUri || uri.baseUrl || null, token: uri.token || uri.authToken || null };
            } catch (e) {}
          }
        } catch (e) {
          // ignore and try next candidate
        }
      }

      // Try a small set of well-known command probes
      const commandCandidates = [
        'jupyter.getServerUri',
        'jupyter.getServerUriForNotebook',
        'jupyter.getConnectionInfo',
        'python.datascience.getServerUri',
        'python.getServerUri'
      ];
      for (const cmd of commandCandidates) {
        try {
          const res = await vscode.commands.executeCommand(cmd);
          if (!res) continue;
          if (typeof res === 'string') return { serverUrl: res };
          const out = { serverUrl: res.serverUrl || res.serverUri || res.baseUrl || null, token: res.token || res.authToken || null };
          if (out.serverUrl || out.token) return out;
        } catch (e) {
          // command not available — skip
        }
      }

      // Fallback to workspace configuration
      const jc = vscode.workspace.getConfiguration('jupyter');
      const jsrv = jc.get('serverUri') || jc.get('serverUrl') || jc.get('jupyterServerUrl') || null;
      const jtoken = jc.get('token') || jc.get('authToken') || null;
      const res = {};
      if (jsrv) res.serverUrl = jsrv;
      if (jtoken) res.token = jtoken;
      return Object.keys(res).length ? res : null;
    } catch (err) {
      return null;
    }
  };

  // Attempt to obtain server settings scoped to a notebook URI. This prefers
  // the Jupyter extension's API (`getServerUriForNotebook`) when available
  // and falls back to executing common commands that powertoys or the
  // Jupyter extension may register. Returns a normalized serverSettings
  // object or null.
  const getServerSettingsForNotebook = async (notebookUri) => {
    try {
      let res = null;
      const tryExt = async () => {
        try {
          const candidates = ['ms-toolsai.jupyter', 'ms-toolsai.vscode-jupyter'];
          for (const id of candidates) {
            try {
              const ext = vscode.extensions.getExtension(id);
              if (!ext) continue;
              const api = await ext.activate();
              if (!api) continue;
              if (typeof api.getServerUriForNotebook === 'function' && notebookUri) {
                try { return await api.getServerUriForNotebook(notebookUri); } catch (e) {}
              }
              if (typeof api.getServerUri === 'function') {
                try { return await api.getServerUri(); } catch (e) {}
              }
            } catch (e) {
              // ignore activation errors
            }
          }
        } catch (e) {}
        return null;
      };

      // 1) try extension API
      try { res = await tryExt(); } catch (e) { res = null; }

      // 2) fallback to running known commands (powertoys / jupyter extension)
      if (!res) {
        const cmdCandidates = [
          'jupyter.getServerUriForNotebook',
          'jupyter.getServerUri',
          'jupyter.getConnectionInfo',
          'jupyter.requestServer'
        ];
        for (const cmd of cmdCandidates) {
          try {
            const out = await vscode.commands.executeCommand(cmd, notebookUri);
            if (out) {
              res = out;
              break;
            }
          } catch (e) {
            // command not registered or failed; skip
          }
        }
      }

      if (!res) return null;

      // Normalize result to an object with common fields
      const normalize = (raw) => {
        if (!raw) return null;
        if (typeof raw === 'string') {
          try {
            const u = new URL(raw);
            const token = u.searchParams.get('token') || null;
            return { serverUrl: raw, token };
          } catch (e) {
            return { serverUrl: raw };
          }
        }
        return {
          serverUrl: raw.serverUrl || raw.serverUri || raw.baseUrl || null,
          baseUrl: raw.baseUrl || null,
          token: raw.token || raw.authToken || raw.tokenString || null,
          kernelId: raw.kernelId || raw.kernel || null,
          socketPath: raw.socketPath || raw.socket_path || null
        };
      };

      const normalized = normalize(res);

      // If a token is present, store it in SecretStorage for safer handling
      try {
        if (normalized && normalized.token) {
          await context.secrets.store('ggblab.token', String(normalized.token));
          try { ggblabOutput?.appendLine('Stored token in SecretStorage (ggblab.token)'); } catch (e) {}
          // Remove token from normalized object to avoid accidental exposure
          delete normalized.token;
        }
      } catch (e) {
        try { ggblabOutput?.appendLine('Failed to store token in SecretStorage: ' + String(e)); } catch (ee) {}
      }

      return normalized;
    } catch (err) {
      return null;
    }
  };
  // Read workspace .vscode/ggblab.json (if present) and return {path,data}
  const readWorkspaceGgblab = async () => {
    try {
      const seen = new Set();
      const candidates = [];

      // Add all workspace folders (if any)
      if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length) {
        for (const wf of vscode.workspace.workspaceFolders) {
          try { candidates.push(wf.uri.fsPath); } catch (e) {}
        }
      }

      // Also include extension install path and active editor folder, then
      // probe process.cwd() and a few parent directories (best-effort)
      try { if (context && context.extensionPath) candidates.push(context.extensionPath); } catch (e) {}
      try {
        const ae = vscode.window.activeTextEditor;
        if (ae && ae.document && ae.document.uri && ae.document.uri.fsPath) {
          candidates.push(path.dirname(ae.document.uri.fsPath));
        }
      } catch (e) {}
      try { candidates.push(process.cwd()); } catch (e) {}
      try {
        let p = process.cwd();
        for (let i = 0; i < 6; i++) {
          const parent = path.dirname(p || '');
          if (!parent || parent === p) break;
          candidates.push(parent);
          p = parent;
        }
      } catch (e) {}

      try { ggblabOutput?.appendLine('ggblab.json search paths: ' + JSON.stringify(candidates)); } catch (e) {}

      for (const base of candidates) {
        if (!base) continue;
        const f = path.join(base, '.vscode', 'ggblab.json');
        if (seen.has(f)) continue;
        seen.add(f);
        if (fs.existsSync(f)) {
          try {
            const txt = fs.readFileSync(f, 'utf8');
            const data = JSON.parse(txt || '{}');
            try { ggblabOutput?.appendLine('ggblab.json loaded from: ' + f); } catch (e) {}
            return { path: f, data };
          } catch (e) {
            ggblabOutput?.appendLine('Failed to parse .vscode/ggblab.json (' + f + '): ' + String(e));
          }
        }
      }
      try { ggblabOutput?.appendLine('ggblab.json not found in search paths'); } catch (e) {}
    } catch (e) {
      // ignore
    }
    return null;
  };

  // Read clipboard and parse JSON if present. Returns object or null.
  const readClipboardSettings = async () => {
    try {
      const txt = await vscode.env.clipboard.readText();
      if (!txt || !txt.trim()) return null;
      try {
        const parsed = JSON.parse(txt);
        if (parsed && typeof parsed === 'object' && Object.keys(parsed).length) {
          try { ggblabOutput?.appendLine('ggblab: clipboard settings parsed: ' + JSON.stringify(parsed)); } catch (e) {}
          return parsed;
        }
      } catch (e) {
        // not JSON — ignore
        try { ggblabOutput?.appendLine('ggblab: clipboard does not contain valid JSON'); } catch (ee) {}
      }
    } catch (e) {
      try { ggblabOutput?.appendLine('ggblab: failed to read clipboard: ' + String(e)); } catch (ee) {}
    }
    return null;
  };

  // If a token exists in the workspace file, move it into SecretStorage and
  // rewrite the file without the token for safety. Returns true if moved.
  const storeTokenFromWorkspaceFile = async (fileEntry) => {
    if (!fileEntry || !fileEntry.data) return false;
    const token = fileEntry.data.token || fileEntry.data.authToken || null;
    if (!token) return false;
    try {
      await context.secrets.store('ggblab.token', String(token));
      ggblabOutput?.appendLine('ggblab: moved token to SecretStorage');
      // remove token from file and write back
      delete fileEntry.data.token;
      delete fileEntry.data.authToken;
      try {
        fs.writeFileSync(fileEntry.path, JSON.stringify(fileEntry.data, null, 2), 'utf8');
        ggblabOutput?.appendLine('ggblab: sanitized .vscode/ggblab.json (token removed)');
      } catch (e) {
        ggblabOutput?.appendLine('ggblab: failed to sanitize ggblab.json: ' + String(e));
      }
      return true;
    } catch (e) {
      ggblabOutput?.appendLine('ggblab: failed to store token in SecretStorage: ' + String(e));
      return false;
    }
  };
  // Helper: perform HTTP(S) request from extension host and return results
  const performProxyRequest = async (opts) => {
    try {
      const baseUrl = opts.baseUrl || '';
      const url = new URL(opts.path, baseUrl);
      const isHttps = url.protocol === 'https:';
      const lib = isHttps ? require('https') : require('http');

      const body = opts.body ? JSON.stringify(opts.body) : null;

      const headers = Object.assign({}, opts.headers || {});
      if (body && !headers['content-type']) {
        headers['content-type'] = 'application/json';
      }
      if (opts.token) {
        headers['Authorization'] = `Token ${opts.token}`;
      }

      const requestOptions = {
        method: opts.method || 'GET',
        headers: headers,
      };

      return await new Promise((resolve, reject) => {
        const req = lib.request(url, requestOptions, (res) => {
          const chunks = [];
          res.on('data', (d) => chunks.push(d));
          res.on('end', () => {
            const raw = Buffer.concat(chunks).toString('utf8');
            let json = null;
            try {
              json = raw ? JSON.parse(raw) : null;
            } catch (err) {
              return resolve({ status: res.statusCode, headers: res.headers, body: raw, parseError: err.message });
            }
            resolve({ status: res.statusCode, headers: res.headers, body: json });
          });
        });
        req.on('error', (err) => reject(err));
        if (body) req.write(body);
        req.end();
      });
    } catch (err) {
      return { error: String(err) };
    }
  };
  let disposable = vscode.commands.registerCommand('ggblab.openApplet', function () {
    const commandArgs = Array.prototype.slice.call(arguments || []);
    (async () => {
      // Parse incoming command arguments (e.g. from command: URI). The
      // first argument may be a JSON object or an array containing the
      // object. We prefer values provided by the command over discovered
      // workspace settings so notebook links can open a specific kernel.
      let incomingSettings = null;
      try {
        if (commandArgs && commandArgs.length) {
          let a = commandArgs[0];
          if (typeof a === 'string') {
            try { a = JSON.parse(a); } catch (e) { /* keep as string */ }
          }
          if (Array.isArray(a) && a.length) a = a[0];
          if (a && typeof a === 'object') incomingSettings = a;
        }
        try { ggblabOutput?.appendLine('ggblab.openApplet args: ' + JSON.stringify(incomingSettings)); } catch (e) {}
      } catch (e) {
        try { ggblabOutput?.appendLine('Failed to parse openApplet args: ' + String(e)); } catch (ee) {}
      }
      try {
        // Do not automatically reveal the Output panel; keep it closed unless
        // the user explicitly opens it for debugging.
        const panel = vscode.window.createWebviewPanel(
          'ggblabApplet',
          'GGBlab Applet (Debug)',
          vscode.ViewColumn.One,
          { enableScripts: true, retainContextWhenHidden: true }
        );

        try {
          const bundlePath = path.join(context.extensionPath, 'dist', 'bundle.js');
          ggblabOutput?.appendLine(`Checking for bundle at ${bundlePath}`);
          // Guard: track if panel gets disposed while async prompts are running
          let panelDisposed = false;
          panel.onDidDispose(() => { panelDisposed = true; try { ggblabOutput?.appendLine('ggblab: panel disposed'); } catch (e) {} });
          if (fs.existsSync(bundlePath)) {
            const bundleUri = panel.webview.asWebviewUri(vscode.Uri.file(bundlePath));
            ggblabOutput?.appendLine(`Loading bundle: ${bundleUri.toString()}`);
          const config = vscode.workspace.getConfiguration('ggblab');
          // Start with configured serverSettings, but allow probe results to
          // fill missing defaults so input boxes are prefilled when possible.
          const cfgServerSettings = config.get('serverSettings') || {};
          let discovered = null;

          try {
            discovered = await probeMsJupyter();
          } catch (e) {
            discovered = null;
          }
          // Try to obtain notebook-scoped settings (prefer this when a notebook
          // or editor is active so kernels/tokens can be discovered per-notebook).
          try {
            // Robustly detect an active notebook/document. Prefer Notebook API,
            // then text editor, visible editors, and other fallbacks.
            let activeEditor = null;
            let notebookUri = null;
            if (vscode.window.activeNotebookEditor && vscode.window.activeNotebookEditor.document) {
              activeEditor = vscode.window.activeNotebookEditor;
              notebookUri = vscode.window.activeNotebookEditor.document.uri;
            } else if (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document) {
              activeEditor = vscode.window.activeTextEditor;
              notebookUri = vscode.window.activeTextEditor.document.uri;
            } else if (vscode.window.visibleTextEditors && vscode.window.visibleTextEditors.length) {
              activeEditor = vscode.window.visibleTextEditors[0];
              notebookUri = activeEditor.document && activeEditor.document.uri ? activeEditor.document.uri : null;
            } else if (vscode.window.visibleNotebookEditors && vscode.window.visibleNotebookEditors.length) {
              activeEditor = vscode.window.visibleNotebookEditors[0];
              notebookUri = activeEditor.document && activeEditor.document.uri ? activeEditor.document.uri : null;
            }
            const discoveredNotebook = (notebookUri && !panelDisposed) ? await getServerSettingsForNotebook(notebookUri) : null;
            if (discoveredNotebook) {
              try { ggblabOutput?.appendLine('discovered (notebook): ' + JSON.stringify(discoveredNotebook)); } catch (e) {}
              discovered = Object.assign({}, discoveredNotebook, discovered || {});
            }
          } catch (e) {
            // ignore notebook-scoped discovery failures
          }
          try {
            try { ggblabOutput?.appendLine('discovered: ' + JSON.stringify(discovered)); } catch (e) { ggblabOutput?.appendLine('discovered: [unserializable]'); }
            try {
              // List installed extensions that look related to Jupyter
              const matches = vscode.extensions.all.filter((ext) => /jupyter|ms-toolsai/i.test(ext.id)).map((ext) => ext.id);
              ggblabOutput?.appendLine('matchingExtensions: ' + JSON.stringify(matches));
            } catch (e) {}
            try {
              // Dump workspace jupyter configuration keys we check
              const jc = vscode.workspace.getConfiguration('jupyter');
              const cfgDump = {
                serverUri: jc.get('serverUri'),
                serverUrl: jc.get('serverUrl'),
                jupyterServerUrl: jc.get('jupyterServerUrl'),
                baseUrl: jc.get('baseUrl'),
                token: jc.get('token'),
                authToken: jc.get('authToken')
              };
              ggblabOutput?.appendLine('jupyterConfig: ' + JSON.stringify(cfgDump));
            } catch (e) {}
          } catch (e) {}

          // Also read workspace .vscode/ggblab.json and SecretStorage for token
          let wsGg = null;
          try { wsGg = await readWorkspaceGgblab(); } catch (e) { wsGg = null; }
          if (wsGg) {
            try { ggblabOutput?.appendLine('.vscode/ggblab.json found: ' + JSON.stringify(wsGg.data)); } catch (e) {}
            // NOTE: do not remove token from the workspace file here; read and
            // use it directly. Token management left to workspace policy.
          }

          // Merge sources. Order of precedence (later entries override earlier):
          // discovered -> workspace file -> extension config -> clipboard -> incoming command args
          let serverSettings = Object.assign({}, discovered || {}, (wsGg && wsGg.data) || {}, cfgServerSettings);
          // Prefer clipboard JSON if present (user-requested behaviour)
          try {
            const clipboardSettings = await readClipboardSettings();
            if (clipboardSettings) {
              serverSettings = Object.assign({}, serverSettings, clipboardSettings);
              try { ggblabOutput?.appendLine('Applied clipboard settings: ' + JSON.stringify(clipboardSettings)); } catch (e) {}
            }
          } catch (e) {
            try { ggblabOutput?.appendLine('Failed to read/apply clipboard settings: ' + String(e)); } catch (ee) {}
          }
          // If the command provided explicit settings (from a command: URI),
          // prefer those values (override everything else).
          try {
            if (incomingSettings && typeof incomingSettings === 'object') {
              serverSettings = Object.assign({}, serverSettings, incomingSettings);
              try { ggblabOutput?.appendLine('Applied incoming command settings: ' + JSON.stringify(incomingSettings)); } catch (e) {}
            }
          } catch (e) {}
          // If secret token exists, prefer it
          try {
            const secretToken = await context.secrets.get('ggblab.token');
            if (secretToken) serverSettings.token = serverSettings.token || secretToken;
          } catch (e) {}
          const autoInit = config.get('autoInit') === true;

          let _sendSettings = null;
          try {
            // If serverSettings already contains the necessary connection
            // info (kernelId and socketPath) then skip prompts and use it.
            if (serverSettings && serverSettings.kernelId && serverSettings.socketPath) {
              _sendSettings = Object.assign({}, serverSettings);
              const serverSettingsJson = JSON.stringify(_sendSettings);
              try { ggblabOutput?.appendLine('serverSettings (sent to webview): ' + serverSettingsJson); } catch (e) {}
              // Set webview title to first 8 chars of kernelId when available
              try {
                if (_sendSettings && _sendSettings.kernelId) {
                  const pfx = String(_sendSettings.kernelId).slice(0, 8);
                  panel.title = `GeoGebra (${pfx})`;
                }
              } catch (e) {}
              if (!panelDisposed) panel.webview.html = getWebviewContent(bundleUri.toString(), serverSettingsJson, autoInit);
              ggblabOutput?.appendLine(`Using workspace/server settings; connecting without prompts`);
            } else {
              const defaultKernel = serverSettings.kernelId || '';
              // If panel was disposed while discovering, abort before prompting
              if (panelDisposed) throw new Error('panel-disposed-before-prompts');
              const kernelId = await vscode.window.showInputBox({
                prompt: 'Enter notebook kernel id to connect (optional)',
                value: defaultKernel,
                placeHolder: 'e.g. 1234abcd-... or leave empty',
                ignoreFocusOut: true
              });
              const defaultSocket = serverSettings.socketPath || '';
              const socketPath = await vscode.window.showInputBox({
                prompt: 'Enter socket path for out-of-band responses (optional)',
                value: defaultSocket,
                placeHolder: 'e.g. /tmp/ggb_XXXX or leave empty',
                ignoreFocusOut: true
              });

              // Allow entering a server URL (may include token in query string).
              const defaultServerUrl = serverSettings.serverUrl || '';
              const serverUrl = await vscode.window.showInputBox({
                prompt: 'Enter server URL (optional — may include token in query)',
                value: defaultServerUrl,
                placeHolder: 'e.g. https://example.com/api?token=XXXX or leave empty',
                ignoreFocusOut: true
              });

              // Also allow entering baseUrl and token separately (settings.json may
              // prefer separate records). We prefer a provided `serverUrl`; if not
              // supplied, but baseUrl/token are provided, assemble a serverUrl with
              // the token as a query parameter and also include both fields.
              const defaultBaseUrl = serverSettings.baseUrl || '';
              const baseUrl = await vscode.window.showInputBox({
                prompt: 'Enter base URL (optional — used if no full server URL provided)',
                value: defaultBaseUrl,
                placeHolder: 'e.g. https://example.com/api or leave empty',
                ignoreFocusOut: true
              });
              const defaultToken = serverSettings.token || '';
              const token = await vscode.window.showInputBox({
                prompt: 'Enter token (optional) — will be sent separately',
                value: defaultToken,
                placeHolder: 'e.g. abcdef12345 or leave empty',
                ignoreFocusOut: true
              });

              // Determine final serverUrl: prefer explicit `serverUrl`, else
              // assemble from `baseUrl` + `token` if available.
              let finalServerUrl = serverUrl || null;
              if (!finalServerUrl && baseUrl) {
                finalServerUrl = baseUrl + (token ? (baseUrl.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token) : '');
              }

              _sendSettings = Object.assign({}, serverSettings, {
                kernelId: kernelId || '',
                socketPath: socketPath || null,
                serverUrl: finalServerUrl,
                baseUrl: baseUrl || null,
                token: token || null
              });
              // Update panel title to kernelId prefix when provided by prompts
              try {
                const k = _sendSettings && _sendSettings.kernelId ? String(_sendSettings.kernelId) : null;
                if (k) {
                  const pfx = k.slice(0, 8);
                  panel.title = `GeoGebra (${pfx})`;
                }
              } catch (e) {}
              const serverSettingsJson = Object.keys(_sendSettings).length ? JSON.stringify(_sendSettings) : null;
              try { ggblabOutput?.appendLine('serverSettings (after prompts): ' + serverSettingsJson); } catch (e) {}
              if (!panelDisposed) panel.webview.html = getWebviewContent(bundleUri.toString(), serverSettingsJson, autoInit);
              ggblabOutput?.appendLine(`Using kernel id: ${kernelId || '<none>'} socketPath: ${socketPath || '<none>'}`);
            }
          } catch (e) {
            ggblabOutput?.appendLine(`Error prompting for kernel id: ${String(e)}`);
            _sendSettings = serverSettings || null;
            panel.webview.html = getWebviewContent(bundleUri.toString(), null, autoInit);
          }

          panel.webview.onDidReceiveMessage((message) => {
            try { ggblabOutput?.appendLine(`webview -> extension message: ${JSON.stringify(message)}`); } catch (e) {}
            if (message && message.type === 'ready') {
              ggblabOutput?.appendLine('Webview ready; sending serverSettings to webview');
              const cfg = vscode.workspace.getConfiguration('ggblab');
              const baseSettings = cfg.get('serverSettings') || {};
              const payloadSettings = _sendSettings || baseSettings || null;
              // Inform the webview of serverSettings. Do NOT advertise the
              // extension-host proxy by default here — for debug we avoid
              // enabling the proxy so the webview uses direct fetch paths.
              const enhanced = Object.assign({}, payloadSettings || {});
                try { ggblabOutput?.appendLine('Posting serverSettings payload to webview: ' + JSON.stringify(enhanced)); } catch (e) {}
              panel.webview.postMessage({ type: 'serverSettings', serverSettings: enhanced, autoInit: !!autoInit });
              return;
            }

            // NOTE: proxyRequest handling is disabled for debug runs. If the
            // webview sends a proxyRequest, immediately reply with an error
            // so the webview falls back to direct fetch behavior and we can
            // observe where the JSON parse error originates.
            if (message && message.type === 'proxyRequest') {
              const id = message.id || null;
              try { ggblabOutput?.appendLine(`proxyRequest ignored (debug): ${id} ${message.method} ${message.path}`); } catch (e) {}
              try { panel.webview.postMessage({ type: 'proxyResponse', id: id, response: { error: 'proxy-disabled-for-debug' } }); } catch (e) {}
              return;
            }
            if (message && message.type === 'dbg') {
              try { const lvl = message.level || 'debug'; const txt = message.text || ''; ggblabOutput?.appendLine(`[webview ${lvl}] ${txt}`); } catch (e) {}
              return;
            }
            if (message && message.type === 'commStatus') {
              try { ggblabOutput?.appendLine(`commStatus: ${JSON.stringify(message)}`); } catch (e) {}
            }
          });

        } else {
          ggblabOutput?.appendLine('dist/bundle.js not found; showing build instructions in webview');
          const config = vscode.workspace.getConfiguration('ggblab');
          const serverSettings = config.get('serverSettings') || null;
          const autoInit = config.get('autoInit') === true;
          const serverSettingsJson = serverSettings ? JSON.stringify(serverSettings) : null;
          panel.webview.html = getWebviewContent(null, serverSettingsJson, autoInit);
        }
      } catch (err) {
        ggblabOutput?.appendLine('Error in ggblab.openApplet handler: ' + (err && err.stack ? err.stack : String(err)));
        try { vscode.window.showErrorMessage('GGBlab: failed to open applet webview — see Output: ggblab for details'); } catch (e) {}
      }
    } catch (e) {
      try { ggblabOutput?.appendLine('Unhandled error opening applet: ' + (e && e.stack ? e.stack : String(e))); } catch (ee) {}
    }
    })().catch((err) => {
      try { ggblabOutput?.appendLine('ggblab.openApplet async error: ' + (err && err.stack ? err.stack : String(err))); } catch (e) {}
      try { vscode.window.showErrorMessage('GGBlab: failed to open applet — check Output: ggblab for details'); } catch (e) {}
    });

  });

  // Register a serializer so the webview panel can be restored after
  // a window reload / extension reload. VS Code will call
  // `deserializeWebviewPanel` with the previously saved state (if any).
  try {
    if (vscode.window.registerWebviewPanelSerializer) {
      vscode.window.registerWebviewPanelSerializer('ggblabApplet', {
        async deserializeWebviewPanel(panel, state) {
          try {
            ggblabOutput?.appendLine('Restoring ggblabApplet webview');
            const bundlePath = path.join(context.extensionPath, 'dist', 'bundle.js');
            const bundleUri = fs.existsSync(bundlePath) ? panel.webview.asWebviewUri(vscode.Uri.file(bundlePath)) : null;
            const serverSettingsJson = state && state.serverSettings ? JSON.stringify(state.serverSettings) : null;
            const autoInit = state && state.autoInit;
            try {
              if (state && state.serverSettings && state.serverSettings.kernelId) {
                const pfx = String(state.serverSettings.kernelId).slice(0, 8);
                panel.title = `GeoGebra (${pfx})`;
              }
            } catch (e) {}
            panel.webview.html = getWebviewContent(bundleUri ? bundleUri.toString() : null, serverSettingsJson, autoInit);
            try { panel.webview.postMessage({ type: 'restoreState', state }); } catch (e) {}
          } catch (e) {
            ggblabOutput?.appendLine('Failed to deserialize ggblabApplet: ' + String(e));
          }
        }
      });
    }
  } catch (e) {}

  context.subscriptions.push(disposable);

  // Single 'Open' status item that uses clipboard -> workspace -> probe
  try {
    const openWithArgsItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 98);
    openWithArgsItem.text = '$(rocket) GGBlab Open';
    openWithArgsItem.tooltip = 'Open GGBlab using detected/workspace/clipboard settings';
    openWithArgsItem.command = 'ggblab.openAppletWithArgs';
    openWithArgsItem.show();
    context.subscriptions.push(openWithArgsItem);

    const obtainSettings = async () => {
      try {
        try {
          const clip = await readClipboardSettings();
          if (clip) return clip;
        } catch (e) {}
        let ws = null;
        try { ws = await readWorkspaceGgblab(); } catch (e) { ws = null; }
        if (ws && ws.data) return ws.data;
        try {
          const probed = await probeMsJupyter();
          if (probed) return probed;
        } catch (e) {}
        return {};
      } catch (e) { return {}; }
    };

    const OPEN_WITH_ARGS_CMD = 'ggblab.openAppletWithArgs';
    context.subscriptions.push(vscode.commands.registerCommand(OPEN_WITH_ARGS_CMD, async () => {
      try {
        const settings = await obtainSettings();
        await vscode.commands.executeCommand('ggblab.openApplet', settings);
      } catch (e) {
        // show a simple error without verbose debug
        vscode.window.showErrorMessage('GGBlab: failed to open with args');
      }
    }));
  } catch (e) {
    // ignore status bar creation failures in restricted hosts
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
