const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
// Create an OutputChannel for ggblab logs
let ggblabOutput = null;

function getWebviewContent(bundleScriptUrl, serverSettingsJson, autoInit) {
  // If a bundleScriptUrl is provided, load the bundle which should mount
  // the React widget into `#root`. Otherwise fall back to the inline
  // minimal HTML that injects deployggb.js directly.
  if (bundleScriptUrl) {
    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>GGBlab Applet</title>
    <script>window.ggblabDebugMessages = true;</script>
    <style>
      html,body,#root{height:100%;margin:0;padding:0}
      /* Stretch the applet vertically to fill the webview area and center horizontally */
      #ggb-container{width:100%;height:100%;display:flex;align-items:stretch;justify-content:center}
      /* Make applet container responsive so the applet can grow with the panel */
      .applet-wrapper{width:100%;height:100%;max-width:100%;align-self:stretch}
    </style>
  </head>
  <body>
    <div id="root">
      <div id="ggb-container">
        <div id="ggb-element-debug" class="applet-wrapper"></div>
      </div>
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
  try {
    ggblabOutput = vscode.window.createOutputChannel('ggblab');
    ggblabOutput.appendLine('ggblab extension activated');
  } catch (e) {
    console.error('Failed to create ggblab output channel', e);
  }
  // Probe for MS Jupyter extension or workspace jupyter settings to infer
  // remote kernel connection info (best-effort). This allows us to prefill
  // baseUrl/token or a serverUrl so users don't need to re-enter them.
  const probeMsJupyter = async () => {
    try {
      const candidates = ['ms-toolsai.jupyter', 'ms-toolsai.vscode-jupyter'];
      for (const id of candidates) {
        try {
          const ext = vscode.extensions.getExtension(id);
          if (!ext) continue;
          const api = await ext.activate();
          if (!api) continue;
          // Try common shapes — many extension APIs vary. Prefer full
          // server URI if exposed, else attempt to read base/token fields.
          if (api.serverUri) return { serverUrl: api.serverUri };
          if (typeof api.getServerUri === 'function') {
            try {
              const uri = await api.getServerUri();
              if (uri) return { serverUrl: uri.toString ? uri.toString() : uri };
            } catch (e) {}
          }
          // Some APIs expose connection objects
          if (api.connections) {
            try {
              const conn = api.connections.active || api.connections[0];
              if (conn) {
                const out = {};
                if (conn.serverUrl) out.serverUrl = conn.serverUrl;
                if (conn.baseUrl) out.baseUrl = conn.baseUrl;
                if (conn.token) out.token = conn.token;
                if (Object.keys(out).length) return out;
              }
            } catch (e) {}
          }
        } catch (e) {
          // activation may fail for some extension versions; ignore
        }
      }

      // Best-effort: execute well-known commands the Jupyter extension or
      // related powertoys might register. If any return connection info,
      // use that.
      try {
        const commandCandidates = [
          'jupyter.getServerUri',
          'jupyter.getServerUriForNotebook',
          'jupyter.getConnectionInfo',
          'jupyter.getActiveConnections',
          'jupyter.requestServer',
          'jupyter.server.getUri',
          'jupyter.pw.getRemoteConnection',
          'jupyter.powertoys.getConnectionInfo',
          'jupyter.getRemoteKernelInfo'
        ];
        for (const cmd of commandCandidates) {
          try {
            const res = await vscode.commands.executeCommand(cmd);
            if (!res) continue;
            try { ggblabOutput?.appendLine('commandProbe ' + cmd + ': ' + JSON.stringify(res)); } catch (e) { ggblabOutput?.appendLine('commandProbe ' + cmd + ': [unserializable]'); }
            const out = {};
            if (typeof res === 'string') out.serverUrl = res;
            else {
              if (res.serverUri) out.serverUrl = res.serverUri;
              if (res.serverUrl) out.serverUrl = res.serverUrl;
              if (res.baseUrl) out.baseUrl = res.baseUrl;
              if (res.token) out.token = res.token;
              if (res.authToken) out.token = res.authToken;
            }
            if (Object.keys(out).length) return out;
          } catch (e) {
            // command may not be registered; ignore
          }
        }
      } catch (e) {}

      // Fallback: check workspace settings under `jupyter` for common keys
      const jc = vscode.workspace.getConfiguration('jupyter');
      const jsrv = jc.get('serverUri') || jc.get('serverUrl') || jc.get('jupyterServerUrl') || null;
      const jbase = jc.get('baseUrl') || null;
      const jtoken = jc.get('token') || jc.get('authToken') || null;
      const res = {};
      if (jsrv) res.serverUrl = jsrv;
      if (jbase) res.baseUrl = jbase;
      if (jtoken) res.token = jtoken;
      return Object.keys(res).length ? res : null;
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
  let disposable = vscode.commands.registerCommand('ggblab.openApplet', async function () {
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
        if (fs.existsSync(bundlePath)) {
          const bundleUri = panel.webview.asWebviewUri(vscode.Uri.file(bundlePath));
          ggblabOutput?.appendLine(`Loading bundle: ${bundleUri.toString()}`);
          const config = vscode.workspace.getConfiguration('ggblab');
          // Start with configured serverSettings, but allow probe results to
          // fill missing defaults so input boxes are prefilled when possible.
          const cfgServerSettings = config.get('serverSettings') || {};
          let discovered = null;
          try { discovered = await probeMsJupyter(); } catch (e) { discovered = null; }
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

          // Merge sources: prefer discovered -> workspace file -> extension config
          const serverSettings = Object.assign({}, discovered || {}, (wsGg && wsGg.data) || {}, cfgServerSettings);
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
              panel.webview.html = getWebviewContent(bundleUri.toString(), serverSettingsJson, autoInit);
              ggblabOutput?.appendLine(`Using workspace/server settings; connecting without prompts`);
            } else {
              const defaultKernel = serverSettings.kernelId || '';
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
              const serverSettingsJson = Object.keys(_sendSettings).length ? JSON.stringify(_sendSettings) : null;
              panel.webview.html = getWebviewContent(bundleUri.toString(), serverSettingsJson, autoInit);
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
}

function deactivate() {}

module.exports = { activate, deactivate };

