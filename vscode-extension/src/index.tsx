import React from 'react';
import { createRoot } from 'react-dom/client';
import GeoGebraWidget from './widget';
import { setupKernelResources } from '../../src/components/jupyterlab';

// Mount the widget into a given container id. This is the entry point
// that should be bundled and referenced from the webview HTML.
export function mountGeoGebra(containerId = 'root') {
  const container = document.getElementById(containerId);
  if (!container) {
    throw new Error('Container not found: ' + containerId);
  }
  const root = createRoot(container);
  root.render(<GeoGebraWidget elementId="ggb-element-debug" />);
}

// For convenience, auto-mount if `#root` is present (useful during dev)
if (typeof document !== 'undefined' && document.getElementById('root')) {
  try {
    // Enable verbose debug messages for development builds / webview.
    // Consumers may set this globally as well; only set if not already true.
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    if (!(window as any).ggblabDebugMessages) {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      (window as any).ggblabDebugMessages = true;
    }
  } catch (e) {
    // ignore
  }
  try {
    mountGeoGebra('root');
    // If running inside a VS Code webview, request serverSettings via postMessage
    try {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      if (typeof (window as any).acquireVsCodeApi === 'function') {
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment
        // @ts-ignore
        const vscode = (window as any).acquireVsCodeApi();
        try {
          vscode.postMessage({ type: 'ready' });
          console.debug('Sent ready message to extension host');
        } catch (e) {
          console.error('Failed to post ready message to extension host', e);
        }

        // Listen for messages from the extension host
        window.addEventListener('message', (ev) => {
          try {
            const msg = (ev && (ev as any).data) || null;
            if (!msg) return;
            if (msg.type === 'serverSettings') {
              // eslint-disable-next-line @typescript-eslint/ban-ts-comment
              // @ts-ignore
              (window as any).__GGBlab_ServerSettings = msg.serverSettings || null;
              // eslint-disable-next-line @typescript-eslint/ban-ts-comment
              // @ts-ignore
              (window as any).__GGBlab_AutoInit = !!msg.autoInit;
              console.debug('Received serverSettings from extension host', msg.serverSettings, 'autoInit=', msg.autoInit);
              if (msg.serverSettings && msg.autoInit) {
                try {
                  const ss = msg.serverSettings;
                  const resources: any = {
                    kernelId: ss.kernelId || '',
                    commTarget: ss.commTarget || '',
                    socketPath: ss.socketPath || null,
                    wsPort: ss.wsPort || 8888
                  };
                  setupKernelResources(resources, { serverSettings: ss }, console.debug).then((helpers) => {
                    (window as any).__GGBlab_kernelHelpers = helpers;
                    console.debug('setupKernelResources initialized from webview via postMessage', helpers);
                    try {
                      // Try opening a comm to the notebook-side target to verify connectivity
                      const target = ss.commTarget || 'jupyter.widget';
                      const kc = (helpers as any).kernelConn;
                      if (kc && typeof kc.createComm === 'function') {
                        const comm = kc.createComm(target, {});
                        try {
                          const maybeId = (comm as any)?.comm_id || (comm as any)?.commId || (comm as any)?.id || null;
                          console.debug('Created comm object', { target, comm, commId: maybeId });
                        } catch (_) {}
                        // Attach handlers before opening to reduce race between kernel messages
                        try {
                          comm.onMsg = (m: any) => console.debug('comm message from kernel:', m);
                        } catch (e) {
                          console.warn('Failed to attach onMsg to comm', e);
                        }
                        try {
                          (comm as any).onClose = (m: any) => {
                            try {
                              const closedId = (m && m.content && m.content.comm_id) || (comm as any)?.comm_id || (comm as any)?.commId || null;
                              console.debug('Comm closed (webview side)', { target, closedId, message: m });
                            } catch (ee) {
                              console.debug('Comm closed (webview side, no id available)', target, m);
                            }
                          };
                        } catch (e) {
                          console.warn('Failed to attach onClose to comm', e);
                        }

                        try {
                          // Open the comm after a short tick so handlers/registering can settle.
                          setTimeout(() => {
                            try {
                              comm.open();
                              console.debug('Opened comm to target', target);
                              try {
                                // If running in VS Code webview, notify extension
                                // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                                // @ts-ignore
                                if (typeof (window as any).acquireVsCodeApi === 'function') {
                                  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                                  // @ts-ignore
                                  (window as any).acquireVsCodeApi().postMessage({ type: 'commStatus', status: 'opened', target });
                                }
                              } catch (e) { /* ignore */ }
                            } catch (e) {
                              console.error('Failed to open comm', e);
                              try {
                                (window as any).acquireVsCodeApi().postMessage({ type: 'commStatus', status: 'open_failed', error: String(e) });
                              } catch (ee) {}
                            }
                          }, 30);
                        } catch (e) {
                          console.error('Error while attempting to schedule comm open', e);
                        }
                      } else {
                        console.debug('No kernelConn.createComm available to open comm');
                      }
                    } catch (e) {
                      console.error('Error while attempting to open comm', e);
                    }
                  }).catch((e) => console.error('setupKernelResources failed', e));
                } catch (e) {
                  console.error('Auto-init after receiving serverSettings failed', e);
                }
              }
            }
          } catch (e) {
            /* ignore */
          }
        });
      }
    } catch (e) {
      /* ignore */
    }
    // If serverSettings are provided by the host (e.g., VS Code extension),
    // initialize kernel resources using the shared helper.
    try {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      const ss = (window as any).__GGBlab_ServerSettings || null;
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      const autoInit = (window as any).__GGBlab_AutoInit === true;
      if (ss && autoInit) {
        const resources: any = {
          kernelId: ss.kernelId || '',
          commTarget: ss.commTarget || '',
          socketPath: ss.socketPath || null,
          wsPort: ss.wsPort || 8888
        };
        setupKernelResources(resources, { serverSettings: ss }, console.debug).then((helpers) => {
          // expose for debugging
          (window as any).__GGBlab_kernelHelpers = helpers;
          console.debug('setupKernelResources initialized from webview', helpers);
        }).catch((e) => console.error('setupKernelResources failed', e));
      }
    } catch (e) {
      console.error('Auto init of kernel resources failed', e);
    }
  } catch (e) {
    // swallow in dev
    // eslint-disable-next-line no-console
    console.error('Auto-mount failed', e);
  }
}

export default mountGeoGebra;
