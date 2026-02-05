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
      #ggb-container{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
      .applet-wrapper{width:800px;height:600px}
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
  let disposable = vscode.commands.registerCommand('ggblab.openApplet', function () {
    try { ggblabOutput?.show(true); } catch (e) {}
    const panel = vscode.window.createWebviewPanel(
      'ggblabApplet',
      'GGBlab Applet (Debug)',
      vscode.ViewColumn.One,
      {
        enableScripts: true
      }
    );

    // If a bundled React script exists in the extension's dist directory,
    // convert it to a webview URI and load it. Otherwise fall back to the
    // inline HTML that directly injects the applet.
    try {
      const bundlePath = path.join(context.extensionPath, 'dist', 'bundle.js');
      ggblabOutput?.appendLine(`Checking for bundle at ${bundlePath}`);
      if (fs.existsSync(bundlePath)) {
        const bundleUri = panel.webview.asWebviewUri(vscode.Uri.file(bundlePath));
        ggblabOutput?.appendLine(`Loading bundle: ${bundleUri.toString()}`);
        const config = vscode.workspace.getConfiguration('ggblab');
        const serverSettings = config.get('serverSettings') || {};
        const autoInit = config.get('autoInit') === true;

        // Prompt the user for a notebook kernel id to connect the webview to.
        // This allows the webview to target a specific notebook kernel for
        // requestExecute/comm usage. The prompt is optional; empty -> no kernel.
        let _sendSettings = null;
        (async () => {
          try {
            const defaultKernel = serverSettings.kernelId || '';
            const kernelId = await vscode.window.showInputBox({
              prompt: 'Enter notebook kernel id to connect (optional)',
              value: defaultKernel,
              placeHolder: 'e.g. 1234abcd-... or leave empty'
            });
            _sendSettings = Object.assign({}, serverSettings, { kernelId: kernelId || '' });
            const serverSettingsJson = Object.keys(_sendSettings).length ? JSON.stringify(_sendSettings) : null;
            panel.webview.html = getWebviewContent(bundleUri.toString(), serverSettingsJson, autoInit);
            ggblabOutput?.appendLine(`Using kernel id: ${kernelId || '<none>'}`);
          } catch (e) {
            ggblabOutput?.appendLine(`Error prompting for kernel id: ${String(e)}`);
            _sendSettings = serverSettings || null;
            panel.webview.html = getWebviewContent(bundleUri.toString(), null, autoInit);
          }
        })();

        // Setup a message handler: webview will post {type: 'ready'} when
        // it has mounted; reply with serverSettings via postMessage so the
        // handshake is explicit and secure.
        panel.webview.onDidReceiveMessage((message) => {
          try {
            ggblabOutput?.appendLine(`webview -> extension message: ${JSON.stringify(message)}`);
          } catch (e) {}
          if (message && message.type === 'ready') {
            ggblabOutput?.appendLine('Webview ready; sending serverSettings to webview');
            // Prefer the settings we assembled when creating the HTML (_sendSettings)
            // which includes the user-entered kernelId. Fall back to workspace
            // config when not present.
            const cfg = vscode.workspace.getConfiguration('ggblab');
            const baseSettings = cfg.get('serverSettings') || {};
            const payloadSettings = _sendSettings || baseSettings || null;
            panel.webview.postMessage({ type: 'serverSettings', serverSettings: payloadSettings, autoInit: !!autoInit });
          }
          // Log comm status messages from the webview
          if (message && message.type === 'commStatus') {
            try {
              ggblabOutput?.appendLine(`commStatus: ${JSON.stringify(message)}`);
            } catch (e) {}
          }
        });

        return;
      }
    } catch (e) {
      ggblabOutput?.appendLine(`Error checking for bundle.js: ${String(e)}`);
      console.error('Error checking for bundle.js', e);
    }

    // No bundle found: still allow passing serverSettings to the fallback page
    ggblabOutput?.appendLine('dist/bundle.js not found; showing build instructions in webview');
    const config = vscode.workspace.getConfiguration('ggblab');
    const serverSettings = config.get('serverSettings') || null;
    const autoInit = config.get('autoInit') === true;
    const serverSettingsJson = serverSettings ? JSON.stringify(serverSettings) : null;
    panel.webview.html = getWebviewContent(null, serverSettingsJson, autoInit);
  });

  context.subscriptions.push(disposable);
}

function deactivate() {}

module.exports = { activate, deactivate };
