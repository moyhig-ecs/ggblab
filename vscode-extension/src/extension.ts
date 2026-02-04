import * as path from 'path';
import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';
import { ServerConnection, KernelManager, SessionManager } from '@jupyterlab/services';
// Use require for 'ws' to avoid needing type declarations during build
const _ws: any = require('ws');
type WS = any;
const WebSocketServer: any = _ws.WebSocketServer || _ws.Server;
const WebSocket: any = _ws.WebSocket || _ws;

export function activate(context: vscode.ExtensionContext) {
  console.log('ggblab: activate called');
  const channel = vscode.window.createOutputChannel('GGBlab');
  channel.appendLine('ggblab: activate called');
  context.subscriptions.push(channel);
    try {
        // Start a local WebSocket broker for bridging webview <-> kernel clients.
        // Bind to loopback and let OS pick a free port (port=0).
        const wsToken = Math.random().toString(36).slice(2);
        let wsPort: number | null = null;
        const clientMetaBySocket = new Map<any, any>();
        const kernelClients = new Map<string, Set<any>>(); // kernelId -> Set<ws>
        const webviewClients = new Set<any>();
        // persistent pending queues (in-memory) to hold messages when no webview is present
        const pendingQueues: Map<string, string[]> = new Map(); // kernelId -> [jsonStr]
        const pendingBroadcasts: string[] = [];
        const PENDING_LIMIT = 2000;

        const wss = new WebSocketServer({ host: '127.0.0.1', port: 0 });
        try { channel.appendLine('ws-broker: WebSocketServer created'); } catch (e) {}
        try { wss.on('error', (err: any) => { channel.appendLine(`ws-broker: server error: ${((err as any) && (err as any).stack) ? (err as any).stack : String(err)}`); }); } catch (e) {}
        // improved heartbeat + app-level keep-alive
        const heartbeatInterval = 20000; // ms
        const maxMissed = 3;
        const heartbeat = setInterval(() => {
          try {
            (wss as any).clients.forEach((c: any) => {
              try {
                const meta: any = clientMetaBySocket.get(c) || {};
                const now = Date.now();
                const last = meta.lastSeen || (c.isAlive ? now : 0);
                const missed = Math.floor((now - last) / heartbeatInterval);
                if (missed >= maxMissed) {
                  try { channel.appendLine(`ws-broker: heartbeat terminate client missed=${missed}`); } catch (e) {}
                  try { c.terminate(); } catch (e) {}
                  return;
                }
                // application-level ping
                try {
                  if (c.readyState === c.OPEN) {
                    try { c.send(JSON.stringify({ type: 'ping' })); } catch (e) {}
                  }
                } catch (e) {}
              } catch (e) {}
            });
          } catch (e) {}
        }, heartbeatInterval);
        wss.on('listening', () => {
          try {
            //@ts-ignore
            const addr: any = wss.address();
            wsPort = addr && addr.port ? addr.port : null;
            channel.appendLine(`ws-broker listening port=${wsPort}`);
            // Debug: also print the broker token so webview/token delivery issues
            // can be diagnosed quickly during development.
            channel.appendLine(`ws-broker token=${wsToken}`);
          } catch (e) {
            channel.appendLine(`ws-broker listening (addr error): ${e}`);
          }
        });

        wss.on('connection', (ws: WebSocket, req: any) => {
          channel.appendLine('ws-broker: connection established');
          try {
            const remote = (req && (req.socket && (req.socket.remoteAddress || req.socket.remoteFamily))) || req && (req.connection && req.connection.remoteAddress) || (req && req.headers && req.headers['x-forwarded-for']) || 'unknown';
            channel.appendLine(`ws-broker: connection from=${remote}`);
          } catch (e) {}
          // mark alive and setup pong handler; enable TCP keepalive if possible
          try { (ws as any).isAlive = true; } catch (e) {}
          try { (ws as any).on('pong', () => { try { (ws as any).isAlive = true; const m = clientMetaBySocket.get(ws) || {}; m.lastSeen = Date.now(); clientMetaBySocket.set(ws, m); } catch (e) {} }); } catch (e) {}
          try {
            const sock = (ws as any)._socket || (ws as any).socket || null;
            if (sock && typeof sock.setKeepAlive === 'function') {
              try { sock.setKeepAlive(true, 10000); } catch (e) {}
            }
            if (sock && typeof sock.setNoDelay === 'function') {
              try { sock.setNoDelay(true); } catch (e) {}
            }
          } catch (e) {}
          // initialize per-socket meta for lastSeen and outgoing queue
          try { clientMetaBySocket.set(ws, { lastSeen: Date.now(), outQueue: [] }); } catch (e) {}
          // log transport errors
          try { (ws as any).on('error', (err: any) => { channel.appendLine(`ws-broker: ws error: ${((err as any) && (err as any).stack) ? (err as any).stack : String(err)}`); }); } catch (e) {}
          let authenticated = false;
          let meta: any = { kind: 'unknown', kernelId: null };

          (ws as any).on('message', (data: any) => {
            try {
              // Log raw incoming message for debugging
              try { channel.appendLine(`ws-broker: raw-msg type=${typeof data} len=${data && (data.length || JSON.stringify(data).length)}`); } catch (e) {}
              try { const sm = clientMetaBySocket.get(ws) || {}; sm.lastSeen = Date.now(); clientMetaBySocket.set(ws, sm); } catch (e) {}
              let obj: any = null;
              // Some clients (Python websocket-client, etc.) may deliver
              // message payloads as binary Buffers. Normalize to string
              // and then JSON.parse so both text and binary frames work.
              let text: any = null;
              try {
                text = typeof data === 'string' ? data : (data && typeof data.toString === 'function' ? data.toString() : String(data));
              } catch (e) {
                text = data;
              }
              try { obj = typeof text === 'string' ? JSON.parse(text) : data; } catch (e) { obj = data; }
              // If possible, log a short JSON preview for diagnosis (after obj exists)
              try { const preview = (typeof text === 'string' ? text : JSON.stringify(obj)).slice(0,200); channel.appendLine(`ws-broker: raw-json-preview ${preview}`); } catch (e) {}
              // Expect initial hello: {type:'hello', token:'...', kind:'kernel'|'webview', kernelId: '...'}
                if (!authenticated) {
                  if (obj && obj.type === 'hello' && obj.token === wsToken) {
                  authenticated = true;
                  meta.kind = obj.kind || 'unknown';
                  meta.kernelId = obj.kernelId || null;
                    // merge auth meta into socket meta
                    try { const sm = clientMetaBySocket.get(ws) || {}; sm.kind = meta.kind; sm.kernelId = meta.kernelId; sm.lastSeen = Date.now(); clientMetaBySocket.set(ws, sm); } catch (e) {}
                  if (meta.kind === 'kernel' && meta.kernelId) {
                    let s = kernelClients.get(meta.kernelId);
                    if (!s) { s = new Set(); kernelClients.set(meta.kernelId, s); }
                    s.add(ws);
                  }
                  if (meta.kind === 'webview') webviewClients.add(ws);
                    channel.appendLine(`ws-broker: authenticated kind=${meta.kind} kernel=${meta.kernelId}`);
                    // flush queued messages for this socket
                    try { const sm = clientMetaBySocket.get(ws) || {}; if (Array.isArray(sm.outQueue) && sm.outQueue.length) { for (const m of sm.outQueue) { try { if ((ws as any).readyState === (ws as any).OPEN) (ws as any).send(m); } catch (e) { channel.appendLine(`ws-broker: flush-send failed ${String(e)}`); } } sm.outQueue = []; clientMetaBySocket.set(ws, sm); } } catch (e) {}
                    // If this is a webview, flush persistent pending queues to all webviews
                    try {
                      if (meta.kind === 'webview') {
                        // send pending broadcasts first
                        if (pendingBroadcasts.length > 0) {
                          for (const msg of pendingBroadcasts) {
                            for (const vw of webviewClients) {
                              try { if ((vw as any).readyState === (vw as any).OPEN) (vw as any).send(msg); } catch (e) { channel.appendLine(`ws-broker: flush-pending-broadcast failed ${String(e)}`); }
                            }
                          }
                          pendingBroadcasts.length = 0;
                        }
                        // send kernel-specific pending messages
                        for (const [kid, arr] of Array.from(pendingQueues.entries())) {
                          if (!arr || !arr.length) continue;
                          for (const msg of arr) {
                            for (const vw of webviewClients) {
                              try { if ((vw as any).readyState === (vw as any).OPEN) (vw as any).send(msg); } catch (e) { channel.appendLine(`ws-broker: flush-pending-kid failed ${String(e)}`); }
                            }
                          }
                          pendingQueues.delete(kid);
                        }
                      }
                    } catch (e) { channel.appendLine(`ws-broker: pending flush error ${String(e)}`); }
                  return;
                } else {
                  channel.appendLine('ws-broker: unauthenticated or invalid hello, closing');
                  try { ws.close(4001, 'unauthenticated'); } catch (e) {}
                  return;
                }
              }

                // Application-level ping/pong handling
                if (obj && obj.type === 'ping') {
                  try { if ((ws as any).readyState === (ws as any).OPEN) (ws as any).send(JSON.stringify({ type: 'pong' })); } catch (e) {}
                  return;
                }
                if (obj && obj.type === 'pong') {
                  try { const sm = clientMetaBySocket.get(ws) || {}; sm.lastSeen = Date.now(); clientMetaBySocket.set(ws, sm); } catch (e) {}
                  return;
                }

                // Allow a connected kernel to set or update its kernelId after auth
                if (authenticated && obj && obj.type === 'set-kernel-id' && obj.kernelId) {
                  try {
                    const kid = String(obj.kernelId);
                    const sm = clientMetaBySocket.get(ws) || {};
                    sm.kernelId = kid;
                    sm.lastSeen = Date.now();
                    clientMetaBySocket.set(ws, sm);
                    let s = kernelClients.get(kid);
                    if (!s) { s = new Set(); kernelClients.set(kid, s); }
                    s.add(ws);
                    channel.appendLine(`ws-broker: kernel id set post-auth kernel=${kid}`);
                  } catch (e) { channel.appendLine(`ws-broker: set-kernel-id failed: ${String(e)}`); }
                  return;
                }

              // Routing: messages expected as {type:'broker', to:'kernel'|'webview', kernelId:'...', payload: {...}}
              if (obj && obj.type === 'broker') {
                const to = obj.to;
                const kid = obj.kernelId || meta.kernelId;
                const payload = obj.payload || {};
                const asStr = JSON.stringify(payload);
                if (to === 'kernel' && kid) {
                  const set = kernelClients.get(kid);
                  if (set) {
                    for (const c of set) {
                      try {
                        if ((c as any).readyState === (c as any).OPEN) {
                          (c as any).send(asStr);
                        } else {
                          try { const cm = clientMetaBySocket.get(c) || {}; cm.outQueue = cm.outQueue || []; cm.outQueue.push(asStr); clientMetaBySocket.set(c, cm); } catch (e) {}
                        }
                      } catch (e) { channel.appendLine(`ws-broker: send->kernel failed ${((e as any) && (e as any).stack) ? (e as any).stack : String(e)}`); }
                    }
                  }
                } else if (to === 'webview') {
                  // If no webview clients are connected, persist the message
                  if (webviewClients.size === 0) {
                    try {
                      if (kid) {
                        const q = pendingQueues.get(kid) || [];
                        if (q.length < PENDING_LIMIT) q.push(asStr);
                        pendingQueues.set(kid, q);
                        channel.appendLine(`ws-broker: queued message for kernel=${kid} pending=${q.length}`);
                      } else {
                        if (pendingBroadcasts.length < PENDING_LIMIT) pendingBroadcasts.push(asStr);
                        channel.appendLine(`ws-broker: queued broadcast pending=${pendingBroadcasts.length}`);
                      }
                    } catch (e) { channel.appendLine(`ws-broker: queue store failed ${String(e)}`); }
                  } else {
                    for (const c of webviewClients) {
                      try {
                        if ((c as any).readyState === (c as any).OPEN) {
                          (c as any).send(asStr);
                        } else {
                          try { const cm = clientMetaBySocket.get(c) || {}; cm.outQueue = cm.outQueue || []; cm.outQueue.push(asStr); clientMetaBySocket.set(c, cm); } catch (e) {}
                        }
                      } catch (e) { channel.appendLine(`ws-broker: send->webview failed ${((e as any) && (e as any).stack) ? (e as any).stack : String(e)}`); }
                    }
                  }
                } else if (to === 'broadcast') {
                  // broadcast to all kernel clients
                  for (const [k, set] of kernelClients.entries()) {
                    for (const c of set) {
                      try {
                        if ((c as any).readyState === (c as any).OPEN) {
                          (c as any).send(asStr);
                        } else {
                          try { const cm = clientMetaBySocket.get(c) || {}; cm.outQueue = cm.outQueue || []; cm.outQueue.push(asStr); clientMetaBySocket.set(c, cm); } catch (e) {}
                        }
                      } catch (e) {}
                    }
                  }
                }
                return;
              }

              // Fallback: if message carries kernelId, forward to webview or kernel clients
              if (obj && obj.kernelId) {
                const set = kernelClients.get(obj.kernelId);
                if (set) for (const c of set) try {
                  const sstr = JSON.stringify(obj);
                  if ((c as any).readyState === (c as any).OPEN) (c as any).send(sstr);
                  else { try { const cm = clientMetaBySocket.get(c) || {}; cm.outQueue = cm.outQueue || []; cm.outQueue.push(sstr); clientMetaBySocket.set(c, cm); } catch (e) {} }
                } catch (e) { channel.appendLine(`ws-broker: fallback-send failed ${((e as any) && (e as any).stack) ? (e as any).stack : String(e)}`); }
              }
            } catch (e) {
              channel.appendLine(`ws-broker: message handler error: ${e}`);
            }
          });

          (ws as any).on('close', (code: any, reason: any) => {
            try {
              const m = clientMetaBySocket.get(ws) || meta;
              if (m && m.kind === 'kernel' && m.kernelId) {
                const s = kernelClients.get(m.kernelId);
                if (s) { s.delete(ws); if (s.size === 0) kernelClients.delete(m.kernelId); }
              }
              if (m && m.kind === 'webview') webviewClients.delete(ws);
              clientMetaBySocket.delete(ws);
              try { channel.appendLine(`ws-broker: connection closed code=${code} reason=${String(reason)}`); } catch (e) {}
            } catch (e) {
              try { channel.appendLine(`ws-broker: connection closed handler error: ${e}`); } catch (er) {}
            }
          });
        });
        // clear heartbeat on server close
        try { (wss as any).on('close', () => { try { clearInterval(heartbeat); } catch (e) {} }); } catch (e) {}

      // remembered Jupyter settings so extension can act as a server-side
      // controller for kernels/comm without requiring the webview to do CORS
      // requests itself.
      let savedBaseUrl: string | undefined = undefined;
      let savedToken: string | undefined = undefined;
      const kernelConnections: Map<string, any> = new Map();
    
    async function ensureKernelTarget(kernelObj: any, targetName: string): Promise<boolean> {
      try {
        if (!kernelObj || typeof kernelObj.requestExecute !== 'function') return false;
        const code = `try:\n    def _ggblab_handler(comm, open_msg):\n        def _on_msg(msg):\n            try:\n                pass\n            except Exception:\n                pass\n        try:\n            comm.on_msg(_on_msg)\n        except Exception:\n            pass\n    get_ipython().kernel.comm_manager.register_target("${targetName}", _ggblab_handler)\n    print(\"ggblab:registered:${targetName}\")\nexcept Exception as e:\n    print(\"ggblab:register-failed:\" + str(e))`;
        try {
          const fut: any = kernelObj.requestExecute({ code });
          if (fut && typeof fut.onIOPub === 'function') {
            try { fut.onIOPub((m: any) => channel.appendLine(`ensureKernelTarget iopub: ${JSON.stringify(m)}`)); } catch (e) {}
          }
          // wait for completion if available
          if (fut && fut.done) await fut.done;
          channel.appendLine(`ensureKernelTarget: requested registration for target=${targetName}`);
          return true;
        } catch (err) {
          channel.appendLine(`ensureKernelTarget: requestExecute failed: ${err}`);
          return false;
        }
      } catch (err) {
        channel.appendLine(`ensureKernelTarget: unexpected error: ${err}`);
        return false;
      }
    }
    let currentPanel: vscode.WebviewPanel | undefined;

    const disposable = vscode.commands.registerCommand('ggblab.openWebview', () => {
      console.log('ggblab: openWebview command invoked');
      try {
        if (currentPanel) {
          // If panel already exists, reveal it and return — this ensures
          // message handlers stay attached to the visible panel.
          currentPanel.reveal(vscode.ViewColumn.One);
          return;
        }

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
        const nonce = getNonce();

        panel.webview.html = getWebviewContent(scriptUri.toString(), nonce, panel.webview.cspSource, wsPort, wsToken);

        // If ws broker is listening, inform the webview of broker URL and token
        try {
          // best-effort: if wsPort is available, send ws-broker info
          if (typeof wsPort === 'number' && wsPort > 0) {
            panel.webview.postMessage({ type: 'ws-broker', url: `ws://127.0.0.1:${wsPort}`, token: wsToken });
            channel.appendLine(`posted ws-broker to webview ws://127.0.0.1:${wsPort}`);
          } else {
            // If not yet known, wait briefly and try again
            setTimeout(() => {
              try {
                if (typeof wsPort === 'number' && wsPort > 0) panel.webview.postMessage({ type: 'ws-broker', url: `ws://127.0.0.1:${wsPort}`, token: wsToken });
              } catch (e) {}
            }, 250);
          }
        } catch (e) {
          channel.appendLine(`failed posting ws-broker: ${e}`);
        }

        // send an immediate ping to the webview to verify messaging
        try {
          panel.webview.postMessage({ type: 'extension-ping' });
        } catch (e) {
          console.error('ggblab: failed to post ping to webview', e);
        }

        // Prompt user for Jupyter connection info and forward to webview
        (async () => {
          try {
            const hostInput = await vscode.window.showInputBox({ prompt: 'Jupyter host (e.g. localhost or http://localhost)', value: 'http://localhost' });
            if (!hostInput) return; // cancelled
            const portInput = await vscode.window.showInputBox({ prompt: 'Jupyter port (e.g. 8888)', value: '8888' });
            if (!portInput) return;
            const tokenInput = await vscode.window.showInputBox({ prompt: 'Jupyter token (leave blank if none)', password: true });

            const baseUrl = hostInput.match(/^https?:\/\//) ? `${hostInput}:${portInput}` : `http://${hostInput}:${portInput}`;

            // store token securely if provided
            if (tokenInput) {
              await context.secrets.store('jupyter.token', tokenInput);
            }

            // remember settings and send to webview (token included only if provided)
            savedBaseUrl = baseUrl;
            savedToken = tokenInput || '';
            panel.webview.postMessage({
              type: 'jupyter-settings',
              baseUrl,
              token: tokenInput || ''
            });

            // Also perform a quick proxy fetch from the extension host and
            // forward the result to the webview so the UI can update even if
            // webview->extension postMessage fails for some message types.
            (async () => {
              const probeId = 'initial-' + String(Date.now());
              try {
                const api = `${baseUrl.replace(/\/$/, '')}/api`;
                const u = new URL(api);
                const client = u.protocol === 'https:' ? https : http;
                const opts: any = { method: 'GET', headers: {} };
                if (tokenInput) opts.headers['Authorization'] = `Token ${tokenInput}`;
                const req = client.request(u, opts, (res: any) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', (chunk: any) => (body += chunk));
                  res.on('end', () => {
                    try {
                      panel.webview.postMessage({ type: 'proxy-response', id: probeId, status: res.statusCode, body });
                      // Also send an explicit connection-status so the webview
                      // can update UI reliably even if message matching differs.
                      panel.webview.postMessage({ type: 'connection-status', connected: !!(res.statusCode && res.statusCode >= 200 && res.statusCode < 300), status: res.statusCode });
                      channel.appendLine(`proxy-initial: status=${res.statusCode} len=${(body||'').length}`);
                    } catch (e) {
                      channel.appendLine(`proxy-initial-post-failed: ${e}`);
                    }
                  });
                });
                req.on('error', (err: any) => channel.appendLine(`proxy-initial-error: ${err}`));
                req.end();
              } catch (err) {
                channel.appendLine(`proxy-initial-exception: ${err}`);
              }
            })();
          } catch (err) {
            console.error('ggblab: error sending jupyter settings to webview', err);
          }
        })();

        // Handle messages from the webview
        panel.webview.onDidReceiveMessage(async msg => {
          try {
            if (!msg) return;
            channel.appendLine(`webview message: ${JSON.stringify(msg)}`);
            // webview ready: resend ws-broker info (help webview that started
            // before extension posted broker info)
            if (msg.type === 'webview-ready') {
              try {
                if (typeof wsPort === 'number' && wsPort > 0) {
                  panel.webview.postMessage({ type: 'ws-broker', url: `ws://127.0.0.1:${wsPort}`, token: wsToken });
                  channel.appendLine(`re-posted ws-broker to webview ws://127.0.0.1:${wsPort}`);
                }
              } catch (e) {
                channel.appendLine(`failed re-posting ws-broker: ${e}`);
              }
            }
            // Top-level: websocket open to kernel (start or connect)
            if (msg.type === 'kernel-ws-open') {
              const id = msg.id || String(Date.now());
              if (!savedBaseUrl) {
                try { panel.webview.postMessage({ type: 'kernel-ws-opened', id, error: 'no-jupyter-settings' }); } catch (e) {}
                channel.appendLine('kernel-ws-open: no jupyter settings');
                return;
              }
              try {
                const serverSettings = ServerConnection.makeSettings({ baseUrl: savedBaseUrl, wsUrl: savedBaseUrl.replace(/^http/, 'ws'), token: savedToken });
                const km = new KernelManager({ serverSettings });
                let promise: Promise<any>;
                if (msg.kernelId) {
                  try {
                    // try to connect to an existing kernel via manager
                    const kc = km.connectTo({ model: { id: msg.kernelId, name: msg.kernelName || 'python3' } });
                    promise = Promise.resolve(kc);
                  } catch (e) {
                    // fallback: startNew via manager
                    promise = km.startNew({ name: msg.kernelName || 'python3' });
                  }
                } else {
                  // start a fresh kernel via manager
                  promise = km.startNew({ name: msg.kernelName || 'python3' });
                }
                promise.then(async (kernelConn: any) => {
                  try {
                    const kid = kernelConn.id || msg.kernelId || String(Date.now());
                    kernelConnections.set(kid, kernelConn);
                    panel.webview.postMessage({ type: 'kernel-ws-opened', id, status: 'ok', kernelId: kid });
                    channel.appendLine(`kernel-ws-opened: id=${id} kernelId=${kid}`);
                  } catch (e) {
                    channel.appendLine(`kernel-ws-opened-post-failed: ${e}`);
                  }
                  // Best-effort: register comm target on the kernel and open an init comm
                  try {
                    await ensureKernelTarget(kernelConn, 'ggblab');
                    try {
                      const kc: any = kernelConn;
                      if (kc.createComm) {
                        const initId = `ggblab-init-${Date.now().toString(36)}`;
                        try {
                          const comm = kc.createComm('ggblab', initId);
                          if (comm && typeof comm.open === 'function') {
                            comm.open({ init: true });
                            channel.appendLine(`kernel-ws-open: opened init comm ${initId} on kernel ${kc.id}`);
                          }
                        } catch (e) {
                          channel.appendLine(`kernel-ws-open: init-comm failed: ${e}`);
                        }
                      }
                    } catch (e) {
                      channel.appendLine(`kernel-ws-open: createComm check failed: ${e}`);
                    }
                  } catch (e) {
                    channel.appendLine(`kernel-ws-open: ensureKernelTarget failed: ${e}`);
                  }
                  // Attach IOPub forwarding and comm listeners
                  try {
                    const k: any = kernelConn;
                    if (k.iopubMessage && typeof k.iopubMessage.connect === 'function') {
                      k.iopubMessage.connect((sender: any, msg: any) => {
                        try {
                          const mt = msg && msg.header && msg.header.msg_type;
                          if (mt === 'comm_open' || mt === 'comm_msg' || mt === 'comm_close') {
                            const payload = msg.content || {};
                            panel.webview.postMessage({ type: mt === 'comm_open' ? 'comm-open' : mt === 'comm_msg' ? 'comm-msg' : 'comm-close', kernelId: k.id, commId: payload.comm_id, target: payload.target_name || payload.target, data: payload.data });
                          } else {
                            // Forward other iopub messages optionally for debugging
                            panel.webview.postMessage({ type: 'iopub', kernelId: k.id, msgType: mt, content: msg.content });
                          }
                        } catch (err) {
                          channel.appendLine(`kernel iopub forward error: ${err}`);
                        }
                      });
                    }
                  } catch (err) {
                    channel.appendLine(`attach-comm-listener-failed: ${err}`);
                  }
                }).catch((err: any) => {
                  try { panel.webview.postMessage({ type: 'kernel-ws-opened', id, error: String(err) }); } catch (e) {}
                  channel.appendLine(`kernel-ws-open-error: ${err}`);
                });
              } catch (err) {
                try { panel.webview.postMessage({ type: 'kernel-ws-opened', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`kernel-ws-open-exception: ${err}`);
              }
              return;
            }
            // handle kernel-related requests from the webview
            if (msg.type === 'kernel-probe') {
              const id = msg.id || String(Date.now());
              if (!savedBaseUrl) {
                try { panel.webview.postMessage({ type: 'kernel-probe-response', id, error: 'no-jupyter-settings' }); } catch (e) {}
                channel.appendLine('kernel-probe: no jupyter settings');
                return;
              }
              try {
                const api = `${savedBaseUrl.replace(/\/$/, '')}/api/kernels`;
                const u = new URL(api);
                const client = u.protocol === 'https:' ? https : http;
                const opts: any = { method: 'GET', headers: {} };
                if (savedToken) opts.headers['Authorization'] = `Token ${savedToken}`;
                const req = client.request(u, opts, (res: any) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', (chunk: any) => (body += chunk));
                  res.on('end', () => {
                    try { panel.webview.postMessage({ type: 'kernel-probe-response', id, status: res.statusCode, body }); } catch (e) {}
                    channel.appendLine(`kernel-probe: status=${res.statusCode} len=${(body||'').length}`);
                  });
                });
                req.on('error', (err: any) => { try { panel.webview.postMessage({ type: 'kernel-probe-response', id, error: String(err) }); } catch (e) {}; channel.appendLine(`kernel-probe-error: ${err}`); });
                req.end();
              } catch (err) {
                try { panel.webview.postMessage({ type: 'kernel-probe-response', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`kernel-probe-exception: ${err}`);
              }
              return;
            }
            if (msg.type === 'kernel-start') {
              const id = msg.id || String(Date.now());
              if (!savedBaseUrl) {
                try { panel.webview.postMessage({ type: 'kernel-start-response', id, error: 'no-jupyter-settings' }); } catch (e) {}
                channel.appendLine('kernel-start: no jupyter settings');
                return;
              }
              try {
                const api = `${savedBaseUrl.replace(/\/$/, '')}/api/kernels`;
                const u = new URL(api);
                const client = u.protocol === 'https:' ? https : http;
                const bodyPayload = JSON.stringify({ name: msg.kernelName || 'python3' });
                const opts: any = { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyPayload) } };
                if (savedToken) opts.headers['Authorization'] = `Token ${savedToken}`;
                const req = client.request(u, opts, (res: any) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', (chunk: any) => (body += chunk));
                  res.on('end', async () => {
                    try { panel.webview.postMessage({ type: 'kernel-start-response', id, status: res.statusCode, body }); } catch (e) {}
                    channel.appendLine(`kernel-start: status=${res.statusCode} len=${(body||'').length}`);

                    // If the kernel was created successfully (201), try to
                    // automatically open a websocket connection to it so the
                    // webview can use comms without manual WS open.
                    if (res.statusCode && res.statusCode === 201) {
                      try {
                        let parsed: any = null;
                        try { parsed = JSON.parse(body || '{}'); } catch (e) { parsed = null; }
                        const restKernelId = parsed && parsed.id ? parsed.id : undefined;
                        if (restKernelId && savedBaseUrl) {
                          const serverSettings = ServerConnection.makeSettings({ baseUrl: savedBaseUrl, wsUrl: savedBaseUrl.replace(/^http/, 'ws'), token: savedToken });
                          try {
                            const km = new KernelManager({ serverSettings });
                            let kernelConn: any;
                            try {
                              // Try to connect to the existing kernel via manager
                              kernelConn = km.connectTo({ model: { id: restKernelId, name: parsed.name || 'python3' } });
                            } catch (e) {
                              // If connectTo fails, start a new connection via manager
                              kernelConn = await km.startNew({ name: parsed.name || 'python3' });
                            }

                            const kid = kernelConn.id || restKernelId;
                            // map both the REST id and the connected id to the
                            // same kernel connection object for lookup.
                            if (restKernelId) kernelConnections.set(restKernelId, kernelConn);
                            kernelConnections.set(kid, kernelConn);

                            // Notify webview and attach iopub comm forwarding
                            try { panel.webview.postMessage({ type: 'kernel-ws-opened', id: id + '-auto', status: 'ok', kernelId: kid }); } catch (e) {}
                            channel.appendLine(`kernel-start-auto-ws: connected kernelId=${kid} restId=${restKernelId}`);

                            try {
                              const k: any = kernelConn;
                              if (k.iopubMessage && typeof k.iopubMessage.connect === 'function') {
                                k.iopubMessage.connect((sender: any, msg: any) => {
                                  try {
                                    const mt = msg && msg.header && msg.header.msg_type;
                                    if (mt === 'comm_open' || mt === 'comm_msg' || mt === 'comm_close') {
                                      const payload = msg.content || {};
                                      panel.webview.postMessage({ type: mt === 'comm_open' ? 'comm-open' : mt === 'comm_msg' ? 'comm-msg' : 'comm-close', kernelId: k.id, commId: payload.comm_id, target: payload.target_name || payload.target, data: payload.data });
                                    } else {
                                      panel.webview.postMessage({ type: 'iopub', kernelId: k.id, msgType: mt, content: msg.content });
                                    }
                                  } catch (err) {
                                    channel.appendLine(`kernel iopub forward error: ${err}`);
                                  }
                                });
                              }
                            } catch (err) {
                              channel.appendLine(`attach-comm-listener-failed (auto): ${err}`);
                            }
                              // Best-effort: register comm target and open init comm
                              try {
                                await ensureKernelTarget(kernelConn, 'ggblab');
                                try {
                                  const kc: any = kernelConn;
                                  if (kc.createComm) {
                                    const initId = `ggblab-init-${Date.now().toString(36)}`;
                                    try {
                                      const comm = kc.createComm('ggblab', initId);
                                      if (comm && typeof comm.open === 'function') {
                                        comm.open({ init: true });
                                        channel.appendLine(`kernel-start-auto-ws: opened init comm ${initId} on kernel ${kc.id}`);
                                      }
                                    } catch (e) {
                                      channel.appendLine(`kernel-start-auto-ws: init-comm failed: ${e}`);
                                    }
                                  }
                                } catch (e) {
                                  channel.appendLine(`kernel-start-auto-ws: createComm check failed: ${e}`);
                                }
                              } catch (e) {
                                channel.appendLine(`kernel-start-auto-ws: ensureKernelTarget failed: ${e}`);
                              }
                          } catch (err) {
                            channel.appendLine(`kernel-start-auto-ws-failed: ${err}`);
                          }
                        }
                      } catch (err) {
                        channel.appendLine(`kernel-start-post-connect-exception: ${err}`);
                      }
                    }
                  });
                });
                req.on('error', (err: any) => { try { panel.webview.postMessage({ type: 'kernel-start-response', id, error: String(err) }); } catch (e) {}; channel.appendLine(`kernel-start-error: ${err}`); });
                req.write(bodyPayload);
                req.end();
              } catch (err) {
                try { panel.webview.postMessage({ type: 'kernel-start-response', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`kernel-start-exception: ${err}`);
              }
              return;
            }
            // COMM BRIDGE: webview requests to open/send/close comm messages to kernel
            if (msg.type === 'comm-open') {
              const id = msg.id || String(Date.now());
              const kid = msg.kernelId;
              const target = msg.target;
              const commId = msg.commId;
              const data = msg.data || {};
              let k = kernelConnections.get(kid);
              const ensureAndSend = async (kernelObj: any) => {
                try {
                  const kv: any = kernelObj;
                      if (kv.createComm) {
                        try {
                          const comm = kv.createComm(target, commId);
                          if (comm && typeof comm.open === 'function') {
                            comm.open(data);
                            try { panel.webview.postMessage({ type: 'comm-open-response', id, status: 'ok' }); } catch (e) {}
                            return true;
                          }
                        } catch (e) {
                          // If comm already exists, consider this a success for idempotency
                          const msg = String(e || '');
                          if (msg.includes('already') || msg.includes('already created')) {
                            try { panel.webview.postMessage({ type: 'comm-open-response', id, status: 'ok', note: 'already-created' }); } catch (ee) {}
                            return true;
                          }
                          try { panel.webview.postMessage({ type: 'comm-open-response', id, error: String(e) }); } catch (ee) {}
                        }
                      }
                      // No safe low-level fallback available; rely on createComm/_comms only
                      try { panel.webview.postMessage({ type: 'comm-open-response', id, error: 'no-comm-api' }); } catch (e) {}
                      return false;
                } catch (err) {
                  try { panel.webview.postMessage({ type: 'comm-open-response', id, error: String(err) }); } catch (e) {}
                  channel.appendLine(`comm-open-exception: ${err}`);
                  return false;
                }
              };
              if (!k && kid && savedBaseUrl) {
                try {
                  const serverSettings = ServerConnection.makeSettings({ baseUrl: savedBaseUrl, wsUrl: savedBaseUrl.replace(/^http/, 'ws'), token: savedToken });
                    try {
                      const km = new KernelManager({ serverSettings });
                      const kernelObj = km.connectTo({ model: { id: kid, name: msg.kernelName || 'python3' } });
                      k = kernelObj;
                      kernelConnections.set(k.id || kid, kernelObj);
                      channel.appendLine(`comm-open: connected to kernel ${k.id} via KernelManager`);
                    } catch (e) {
                      // Fallback: create a Session connected to the existing kernel id
                      const km2 = new KernelManager({ serverSettings });
                      const sm = new SessionManager({ serverSettings, kernelManager: km2 });
                      const session = await sm.startNew({ path: `ggblab-${kid}`, name: '', type: 'terminal', kernel: { id: kid, name: msg.kernelName || 'python3' } } as any);
                      const kernelObj = session.kernel;
                      k = kernelObj;
                      kernelConnections.set(k.id || kid, kernelObj);
                      channel.appendLine(`comm-open: connected to kernel ${k.id} via SessionManager`);
                    }
                } catch (err) {
                  channel.appendLine(`comm-open: failed to connect to kernel ${kid}: ${err}`);
                }
              }
              if (!k) {
                try { panel.webview.postMessage({ type: 'comm-open-response', id, error: 'no-kernel' }); } catch (e) {}
                channel.appendLine(`comm-open: no kernel ${kid}`);
                return;
              }
              // Ensure kernel has the comm target registered (best-effort)
              try {
                await ensureKernelTarget(k, target);
              } catch (e) {
                channel.appendLine(`comm-open: ensureKernelTarget failed: ${e}`);
              }
              await ensureAndSend(k);
              return;
            }
            if (msg.type === 'comm-msg') {
              const id = msg.id || String(Date.now());
              const kid = msg.kernelId;
              const commId = msg.commId;
              const data = msg.data || {};
              let k = kernelConnections.get(kid);
              const trySend = async (kernelObj: any) => {
                try {
                  const kv: any = kernelObj;
                  let sent = false;
                  try {
                    if (kv._comms && kv._comms[commId] && typeof kv._comms[commId].send === 'function') {
                      kv._comms[commId].send(data);
                      sent = true;
                    }
                  } catch (innerErr) {
                    channel.appendLine(`comm-msg send inner error: ${innerErr && (innerErr as any).stack ? (innerErr as any).stack : String(innerErr)}`);
                    // Try to recover: attempt to ensure target/register and recreate comm
                    try {
                      await ensureKernelTarget(kv, msg.target || '');
                      if (kv.createComm) {
                        const recreated = kv.createComm(msg.target || '', commId);
                        if (recreated && typeof recreated.send === 'function') {
                          recreated.send(data);
                          sent = true;
                        }
                      }
                    } catch (recreateErr) {
                      channel.appendLine(`comm-msg recovery failed: ${recreateErr && (recreateErr as any).stack ? (recreateErr as any).stack : String(recreateErr)}`);
                    }
                  }
                  if (sent) { try { panel.webview.postMessage({ type: 'comm-msg-response', id, status: 'sent' }); } catch (e) {} }
                  else { try { panel.webview.postMessage({ type: 'comm-msg-response', id, error: 'no-comm-object' }); } catch (e) {} }
                } catch (err) {
                  try { panel.webview.postMessage({ type: 'comm-msg-response', id, error: String(err), stack: err && (err as any).stack ? (err as any).stack : '' }); } catch (e) {}
                  channel.appendLine(`comm-msg-exception: ${err && (err as any).stack ? (err as any).stack : String(err)}`);
                }
              };
              if (!k && kid && savedBaseUrl) {
                try {
                  const serverSettings = ServerConnection.makeSettings({ baseUrl: savedBaseUrl, wsUrl: savedBaseUrl.replace(/^http/, 'ws'), token: savedToken });
                  try {
                    const km = new KernelManager({ serverSettings });
                    const kernelObj = km.connectTo({ model: { id: kid, name: msg.kernelName || 'python3' } });
                    k = kernelObj;
                    kernelConnections.set(k.id || kid, kernelObj);
                    channel.appendLine(`comm-msg: connected to kernel ${k.id} via KernelManager`);
                  } catch (e) {
                    const km2 = new KernelManager({ serverSettings });
                    const sm = new SessionManager({ serverSettings, kernelManager: km2 });
                    const session = await sm.startNew({ path: `ggblab-${kid}`, name: '', type: 'terminal', kernel: { id: kid, name: msg.kernelName || 'python3' } } as any);
                    const kernelObj = session.kernel;
                    k = kernelObj;
                    kernelConnections.set(k.id || kid, kernelObj);
                    channel.appendLine(`comm-msg: connected to kernel ${k.id} via SessionManager`);
                  }
                } catch (err) {
                  channel.appendLine(`comm-msg: failed to connect to kernel ${kid}: ${err}`);
                }
              }
              if (!k) {
                try { panel.webview.postMessage({ type: 'comm-msg-response', id, error: 'no-kernel' }); } catch (e) {}
                channel.appendLine(`comm-msg: no kernel ${kid}`);
                return;
              }
              await trySend(k);
              return;
            }
            if (msg.type === 'comm-close') {
              const id = msg.id || String(Date.now());
              const kid = msg.kernelId;
              const commId = msg.commId;
              let k = kernelConnections.get(kid);
              if (!k && kid && savedBaseUrl) {
                try {
                  const serverSettings = ServerConnection.makeSettings({ baseUrl: savedBaseUrl, wsUrl: savedBaseUrl.replace(/^http/, 'ws'), token: savedToken });
                  try {
                    const km = new KernelManager({ serverSettings });
                    const kernelObj = km.connectTo({ model: { id: kid, name: msg.kernelName || 'python3' } });
                    k = kernelObj;
                    kernelConnections.set(k.id || kid, kernelObj);
                  } catch (e) {
                    const km2 = new KernelManager({ serverSettings });
                    const sm = new SessionManager({ serverSettings, kernelManager: km2 });
                    const session = await sm.startNew({ path: `ggblab-${kid}`, name: '', type: 'terminal', kernel: { id: kid, name: msg.kernelName || 'python3' } } as any);
                    const kernelObj = session.kernel;
                    k = kernelObj;
                    kernelConnections.set(k.id || kid, kernelObj);
                  }
                } catch (err) {
                  channel.appendLine(`comm-close: failed to connect to kernel ${kid}: ${err}`);
                }
              }
              if (!k) {
                try { panel.webview.postMessage({ type: 'comm-close-response', id, error: 'no-kernel' }); } catch (e) {}
                channel.appendLine(`comm-close: no kernel ${kid}`);
                return;
              }
              try {
                const kv: any = k;
                if (kv._comms && kv._comms[commId] && typeof kv._comms[commId].close === 'function') {
                  kv._comms[commId].close();
                  try { panel.webview.postMessage({ type: 'comm-close-response', id, status: 'closed' }); } catch (e) {}
                } else {
                  try { panel.webview.postMessage({ type: 'comm-close-response', id, error: 'no-comm-object' }); } catch (e) {}
                }
              } catch (err) {
                try { panel.webview.postMessage({ type: 'comm-close-response', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`comm-close-exception: ${err}`);
              }
              return;
            }
            // handle simple proxy-fetch requests from the webview to bypass CORS
            if (msg.type === 'connect-request' && msg.url) {
              // webview asked the extension to connect to Jupyter (carry out the HTTP GET)
              const id = msg.id || String(Date.now());
              try {
                const u = new URL(msg.url);
                const client = u.protocol === 'https:' ? https : http;
                const options: any = {
                  method: 'GET',
                  headers: msg.headers || {}
                };
                const req = client.request(u, options, (res: any) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', (chunk: any) => (body += chunk));
                  res.on('end', () => {
                    try {
                      panel.webview.postMessage({ type: 'proxy-response', id, status: res.statusCode, body: body });
                      channel.appendLine(`proxy-response (connect-request): id=${id} status=${res.statusCode} len=${(body||'').length}`);
                    } catch (e) {
                      console.error('ggblab: failed posting proxy-response', e);
                    }
                  });
                });
                req.on('error', (err: any) => {
                  try { panel.webview.postMessage({ type: 'proxy-response', id, error: String(err) }); } catch (e) {}
                  channel.appendLine(`proxy-response-error (connect-request): id=${id} error=${String(err)}`);
                });
                req.end();
              } catch (err) {
                try { panel.webview.postMessage({ type: 'proxy-response', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`proxy-request-exception (connect-request): id=${id} error=${String(err)}`);
              }
              return;
            }
            if (msg.type === 'proxy-fetch' && msg.url) {
              const id = msg.id || String(Date.now());
              try {
                const u = new URL(msg.url);
                const client = u.protocol === 'https:' ? https : http;
                const options: any = {
                  method: msg.method || 'GET',
                  headers: msg.headers || {}
                };
                const req = client.request(u, options, (res: any) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', (chunk: any) => (body += chunk));
                  res.on('end', () => {
                    try {
                      panel.webview.postMessage({ type: 'proxy-response', id, status: res.statusCode, body: body });
                      panel.webview.postMessage({ type: 'connection-status', connected: !!(res.statusCode && res.statusCode >= 200 && res.statusCode < 300), status: res.statusCode });
                      channel.appendLine(`proxy-response: id=${id} status=${res.statusCode} len=${(body||'').length}`);
                    } catch (e) {
                      console.error('ggblab: failed posting proxy-response', e);
                    }
                  });
                });
                req.on('error', (err: any) => {
                  try { panel.webview.postMessage({ type: 'proxy-response', id, error: String(err) }); } catch (e) {}
                  channel.appendLine(`proxy-response-error: id=${id} error=${String(err)}`);
                });
                req.end();
              } catch (err) {
                try { panel.webview.postMessage({ type: 'proxy-response', id, error: String(err) }); } catch (e) {}
                channel.appendLine(`proxy-request-exception: id=${id} error=${String(err)}`);
              }
              return;
            }
            // webview-forwarded logs
            if (msg.type === 'webview-log') {
              const text = (msg.args || []).map((a: any) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
              if (msg.level === 'error') {
                console.error('webview:', text);
                channel.appendLine(`webview: ERROR: ${text}`);
              } else {
                console.log('webview:', text);
                channel.appendLine(`webview: ${text}`);
              }
              return;
            }

            if (msg.type === 'webview-ready') {
              console.log('ggblab: webview ready');
              channel.appendLine('ggblab: webview ready');
              return;
            }

            // legacy/info messages
            switch (msg.command) {
              case 'info':
                vscode.window.showInformationMessage(msg.text);
                break;
            }
          } catch (e) {
            console.error('ggblab: error handling webview message', e);
            channel.appendLine(`ggblab: error handling webview message: ${e}`);
          }
        });

        // Track current panel and clean up when closed
        currentPanel = panel;
        panel.onDidDispose(() => {
          currentPanel = undefined;
          channel.appendLine('ggblab: webview panel disposed');
        });
      } catch (err) {
        console.error('ggblab: error creating webview', err);
        vscode.window.showErrorMessage('GGBlab: failed to open webview — see developer console for details');
      }
    });

    context.subscriptions.push(disposable);
    // Debug command: dump kernelConnections and _comms for each kernel
    const dumpCmd = vscode.commands.registerCommand('ggblab.dumpKernelComms', () => {
      try {
        channel.appendLine('=== ggblab.dumpKernelComms ===');
        for (const [kId, kObj] of Array.from(kernelConnections.entries())) {
          try {
            const ko: any = kObj;
            const id = ko && ko.id ? ko.id : 'n/a';
            const status = ko && ko.connectionStatus ? ko.connectionStatus : (ko && ko.status ? ko.status : 'n/a');
            channel.appendLine(`kernel ${String(kId)} id=${id} status=${status}`);

            try {
              const kc: any = ko;
              channel.appendLine(`  createCommExists=${typeof kc.createComm === 'function'}`);
              if (kc._comms === undefined) {
                channel.appendLine('  _comms: undefined');
              } else {
                const typeRepr = Object.prototype.toString.call(kc._comms);
                channel.appendLine(`  _comms type: ${typeRepr}`);
                let commCount = 0;
                if (kc._comms instanceof Map) {
                  channel.appendLine(`  _comms is Map size=${kc._comms.size}`);
                  for (const [ck, cv] of kc._comms.entries()) {
                    channel.appendLine(`    comm key: ${ck} typeof:${typeof cv}`);
                    commCount++;
                  }
                } else if (typeof kc._comms === 'object' && kc._comms !== null) {
                  const own = Object.getOwnPropertyNames(kc._comms || {});
                  channel.appendLine(`  _comms object ownKeys=${own.length}`);
                  for (const nk of own) {
                    try { channel.appendLine(`    comm key: ${nk} typeof:${typeof (kc._comms as any)[nk]}`); } catch (e) {}
                    commCount++;
                  }
                  // fallback: for..in
                  let forInCount = 0;
                  try { for (const k in kc._comms) { forInCount++; } } catch (e) {}
                  channel.appendLine(`  _comms for..in count=${forInCount}`);
                } else {
                  channel.appendLine(`  _comms other repr: ${String(kc._comms)}`);
                }
                channel.appendLine(`  reported commCount=${commCount}`);
              }
            } catch (e) {
              channel.appendLine(`  inspect _comms failed: ${e}`);
            }
          } catch (e) {
            channel.appendLine(`  kernel ${String(kId)} dump failed: ${e}`);
          }
        }
        channel.appendLine('=== end dump ===');
      } catch (err) {
        channel.appendLine(`dumpKernelComms failed: ${err}`);
      }
    });
    context.subscriptions.push(dumpCmd);
    // Open the webview immediately on activate to ensure EDH creates the panel
    // (helps debug when commands are accidentally run in the wrong window)
    vscode.commands.executeCommand('ggblab.openWebview').then(() => {}, () => {});
  } catch (err) {
    console.error('ggblab: activation failed', err);
    vscode.window.showErrorMessage('GGBlab: activation failed — see developer console for details');
    throw err;
  }
}



function getWebviewContent(scriptUri: string, nonce: string, cspSource: string, wsPort?: number | null, wsToken?: string | null) {
  const brokerSnippet = (typeof wsPort === 'number' && wsPort > 0) ?
    `<script nonce="${nonce}">window.ggblabWsBrokerUrl = 'ws://127.0.0.1:${wsPort}'; window.ggblabWsBrokerToken = '${wsToken || ''}';</script>` : '';

  // Inline proxy script: overrides element creation for <script> and <link rel="stylesheet"> to
  // fetch external resources via the extension host (postMessage -> proxy-fetch) and then
  // inject them as blob URLs or style tags. This avoids CORS blocks when webview attempts
  // to load CDNs like https://unpkg.com/ directly.
  const proxySnippet = `
  <script nonce="${nonce}">
  (function(){
    try {
      const vscode = acquireVsCodeApi();
      window.__ggblab_pending = {};
      function proxyFetch(url, method, headers){
        const id = 'pf-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
        return new Promise((resolve) => {
          window.__ggblab_pending[id] = resolve;
          try { vscode.postMessage({ type: 'proxy-fetch', id: id, url: url, method: method || 'GET', headers: headers || {} }); } catch(e) { resolve({ error: String(e) }); }
        });
      }
      window.addEventListener('message', (ev) => {
        try {
          const msg = ev && ev.data;
          if (!msg) return;
          if (msg.type === 'proxy-response' && msg.id && window.__ggblab_pending[msg.id]) {
            try { window.__ggblab_pending[msg.id](msg); } catch(e){}
            try { delete window.__ggblab_pending[msg.id]; } catch(e){}
          }
        } catch(e) {}
      });

      const origCreate = Document.prototype.createElement;
      Document.prototype.createElement = function(tagName){
        const el = origCreate.call(this, tagName);
        try {
          const t = (tagName || '').toLowerCase();
          if (t === 'script') {
            const desc = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'src');
            Object.defineProperty(el, 'src', {
              configurable: true,
              set: function(url){
                try {
                  if (typeof url === 'string' && (url.startsWith('http://') || url.startsWith('https://')) ) {
                    proxyFetch(url).then(function(resp){
                      try {
                        if (resp && resp.body) {
                          const blob = new Blob([resp.body], { type: 'text/javascript' });
                          const blobUrl = URL.createObjectURL(blob);
                          if (desc && desc.set) desc.set.call(this, blobUrl);
                        } else {
                          if (desc && desc.set) desc.set.call(this, url);
                        }
                      } catch(e){ if (desc && desc.set) desc.set.call(this, url); }
                    }.bind(this)).catch(function(){ if (desc && desc.set) desc.set.call(this, url); }.bind(this));
                  } else {
                    if (desc && desc.set) desc.set.call(this, url);
                  }
                } catch(e) { if (desc && desc.set) desc.set.call(this, url); }
              },
              get: function(){ try { return desc && desc.get ? desc.get.call(this) : ''; } catch(e){ return ''; } }
            });
          }
          if (t === 'link') {
            const hrefDesc = Object.getOwnPropertyDescriptor(HTMLLinkElement.prototype, 'href');
            Object.defineProperty(el, 'href', {
              configurable: true,
              set: function(url){
                try {
                  const rel = (this.rel || '').toLowerCase();
                  if (rel === 'stylesheet' && typeof url === 'string' && (url.startsWith('http://') || url.startsWith('https://'))) {
                    proxyFetch(url).then(function(resp){
                      try {
                        if (resp && resp.body) {
                          const style = document.createElement('style');
                          style.textContent = resp.body;
                          document.head.appendChild(style);
                        } else {
                          if (hrefDesc && hrefDesc.set) hrefDesc.set.call(this, url);
                        }
                      } catch(e) { if (hrefDesc && hrefDesc.set) hrefDesc.set.call(this, url); }
                    }.bind(this)).catch(function(){ if (hrefDesc && hrefDesc.set) hrefDesc.set.call(this, url); }.bind(this));
                  } else {
                    if (hrefDesc && hrefDesc.set) hrefDesc.set.call(this, url);
                  }
                } catch(e) { if (hrefDesc && hrefDesc.set) hrefDesc.set.call(this, url); }
              },
              get: function(){ try { return hrefDesc && hrefDesc.get ? hrefDesc.get.call(this) : ''; } catch(e){ return ''; } }
            });
          }
        } catch(e) {}
        return el;
      };
    } catch (e) {
      // don't break the page if proxy injection fails
      console.error('ggblab proxy injection failed', e);
    }
  })();
  </script>`;
  return `<!doctype html>
  <html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource} https: data:; script-src 'nonce-${nonce}' ${cspSource}; style-src ${cspSource} 'unsafe-inline'; connect-src ${cspSource} http: https: ws: wss;">
    <style>html,body,#root{height:100%;margin:0;padding:0;}</style>
  </head>
  <body>
    <div id="root"></div>
    ${brokerSnippet}
    ${proxySnippet}
    <script nonce="${nonce}" src="${scriptUri}"></script>
  </body>
  </html>`;
}

function getNonce() {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

export function deactivate() {}
