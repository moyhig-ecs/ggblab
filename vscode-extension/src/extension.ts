import * as path from 'path';
import * as vscode from 'vscode';

export function activate(context: vscode.ExtensionContext) {
  const disposable = vscode.commands.registerCommand('ggblab.openWebview', () => {
    const panel = vscode.window.createWebviewPanel(
      'ggblabView',
      'GGBlab GeoGebra',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.file(path.join(context.extensionPath, 'media'))]
      }
    );

    const scriptPathOnDisk = vscode.Uri.file(path.join(context.extensionPath, 'media', 'bundle.js'));
    const scriptUri = panel.webview.asWebviewUri(scriptPathOnDisk);

    panel.webview.html = getWebviewContent(scriptUri.toString());

    // Handle messages from the webview
    panel.webview.onDidReceiveMessage(msg => {
      switch (msg.command) {
        case 'info':
          vscode.window.showInformationMessage(msg.text);
          break;
      }
    });
  });

  context.subscriptions.push(disposable);
}

function getWebviewContent(scriptUri: string) {
  return `<!doctype html>
  <html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>html,body,#root{height:100%;margin:0;padding:0;}</style>
  </head>
  <body>
    <div id="root"></div>
    <script>window.acquireVsCodeApi = window.acquireVsCodeApi || function(){return {postMessage:()=>{}}}</script>
    <script src="${scriptUri}"></script>
  </body>
  </html>`;
}

export function deactivate() {}
