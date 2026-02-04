// comm helper functions inlined from kernel_comm.ts to reduce indirection
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
import { initKernelCommHelpers } from '../kernel_comm';
import { PageConfig } from '@jupyterlab/coreutils';
// Lumino types and wrappers are provided in src/lumino/GeoGebraWidget.tsx
import type { WidgetManagerType } from '../widgetManager';
import { registerWidgetCommTargets } from '../widgetManager';
import type { IAppletApi, IResources } from '../types';

// Global typings are provided in src/declarations.d.ts; avoid duplicate declarations here.

// Debug logging helper controlled from the browser console.
// Enable message logging in the JS console by running:
//   window.ggblabDebugMessages = true
function dbg(...args: any[]) {
  if ((window as any).ggblabDebugMessages) {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
}

export function isArrayOfArrays(value: any): boolean {
  return Array.isArray(value) && value.every((subArray: any) => Array.isArray(subArray));
}

/**
 * React component for a GeoGebra.
 *
 * @returns The React component
 */
export const GGAComponent = (props: IGGAWidgetProps): JSX.Element => {
  // const [kernels, setKernels] = React.useState<any[]>([]);
  const widgetRef = useRef<HTMLDivElement>(null);
  // const [size, setSize] = useState<{width: number; height: number}>({width: 800, height: 600});

  // The following `useState` + resize-listener is intentionally commented out.
  // Lumino's layout and `onResize` handling are the primary resize signals
  // for this widget; the code is kept as a reference for future experiments
  // (ResizeObserver and alternate strategies were unreliable across themes).
  // // Listen to resize events to update size state
  // // but not working as expected in Lumino
  //   useEffect(() => {
  //     window.addEventListener('resize', () => {
  //     if (widgetRef.current) {
  //         setSize({
  //             width: widgetRef.current.offsetWidth,
  //             height: widgetRef.current.offsetHeight,
  //         });
  //         console.log("Resized to:", size.width, size.height);
  //     }
  //     });
  //   }, []);

  dbg('Component props: ', props.kernelId, props.commTarget, props.socketPath, props.wsPort);
  // window.dispatchEvent(new Event('resize'));

  const elementId = 'ggb-element-' + (props?.kernelId || '').substring(0, 8);
  dbg('Element ID:', elementId);

  let applet: any = null;
  // use exported `isArrayOfArrays`

  /**
   * Calls a remote procedure on kernel2 to send a message via remote socket between kernel2 to kernel.
   * Executes Python code on kernel2 that sends the message through either a unix socket or websocket.
   *
   * Note on WebSocket Connection Handling:
   * Previous attempts to maintain persistent websocket connections using ping/pong (keep-alive)
   * were unsuccessful. Websocket connections established via kernel2.requestExecute() execute
   * within isolated contexts that are torn down immediately after the code execution completes.
   * Even with ping/pong mechanisms, connections would be disconnected once the kernel's
   * requestExecute() context ended. Therefore, the implementation creates new socket connections
   * for each message send operation, which is more reliable than attempting to maintain
   * persistent but fragile connections.
   *
   * @param kernel2 - The kernel to execute the remote procedure on
   * @param message - The message to send (as a JSON string)
   * @param socketPath - Optional unix socket path (if provided, uses unix socket; otherwise uses websocket)
   * @param wsUrl - WebSocket URL (used if socketPath is not provided)
   */
  // `sendChain` handled inside kernel_comm helpers when initialized.

  useEffect(() => {
    // Move frequently-used props into the resource bag for consistency

    // Resource bag: consolidate disposable resources into a single
    // object with a `dispose()` helper so teardown is consistent.
    class Resources implements IResources {
      kernelId: string;
      commTarget: string;
      socketPath: string | null;
      wsPort: number;
      kernel2: any = null;
      kernelManager: any = null;
      kernelConn: any = null;
      comm: any = null;
      widgetComm: any = null;
      appletApi: IAppletApi | null = null;
      // unregister function returned by `registerWidgetCommTargets`
      unregisterWidgetCommTargets: (() => void) | null = null;
      observer: MutationObserver | null = null;
      resizeHandler: (() => void) | null = null;
      closeHandler: (() => void) | null = null;
      metaViewport: HTMLMetaElement | null = null;
      scriptTag: HTMLScriptElement | null = null;
      // store last-seen string values for objects to suppress redundant updates
      _lastValues: { [name: string]: string | null } = {};

      constructor(kernelId: string, commTarget: string, socketPath: string | null, wsPort: number) {
        this.kernelId = kernelId;
        this.commTarget = commTarget;
        this.socketPath = socketPath;
        this.wsPort = wsPort;
      }

      async dispose() {
        try {
          if (this.comm) {
            try {
              this.comm.close?.();
            } catch (err) {
              dbg('Error closing comm during cleanup', err);
            }
            this.comm = null;
          }

          if (this.kernel2) {
            try {
              await this.kernel2.shutdown();
            } catch (err) {
              dbg('Error shutting down kernel2 during cleanup', err);
            }
            this.kernel2 = null;
          }

          this.widgetComm = null;
          this.appletApi = null;

          if (this.kernelManager) {
            try {
              await this.kernelManager.shutdown?.();
            } catch (err) {
              dbg('Error shutting down kernelManager', err);
            }
            this.kernelManager = null;
          }

          if (this.observer) {
            try {
              this.observer.disconnect();
            } catch (err) {
              dbg('Error disconnecting observer', err);
            }
            this.observer = null;
          }

          if (this.resizeHandler) {
            try {
              window.removeEventListener('resize', this.resizeHandler);
            } catch (err) {
              dbg('Error removing resize handler', err);
            }
            this.resizeHandler = null;
          }

          if (this.closeHandler) {
            try {
              window.removeEventListener('close', this.closeHandler);
            } catch (err) {
              dbg('Error removing close handler', err);
            }
            this.closeHandler = null;
          }

          if (this.metaViewport && this.metaViewport.parentNode) {
            this.metaViewport.parentNode.removeChild(this.metaViewport);
            this.metaViewport = null;
          }

          if (this.scriptTag && this.scriptTag.parentNode) {
            this.scriptTag.parentNode.removeChild(this.scriptTag);
            this.scriptTag = null;
          }

          try {
            // call the unregister function if present
            this.unregisterWidgetCommTargets?.();
            this.unregisterWidgetCommTargets = null;
          } catch (err) {
            dbg('Error unregistering widget comm targets', err);
          }
        } catch (err) {
          console.error('Error during resources.dispose():', err);
        }
      }
    }

    const res: IResources = new Resources(
      props.kernelId || '',
      props.commTarget || '',
      props.socketPath || null,
      props.wsPort || 8888
    );

    (async () => {
      return await KernelAPI.listRunning();
    })().then(async kernels => {
      // setKernels(kernels);
      dbg('Running kernels:', kernels);

      const baseUrl = PageConfig.getBaseUrl();
      const token = PageConfig.getToken();
      dbg(`Base URL: ${baseUrl}`);
      dbg(`Token: ${token}`);
      const settings = ServerConnection.makeSettings({
        baseUrl: baseUrl, //'http://localhost:8889/',
        token: token, //'7e89be30eb93ee7c149a839d4c7577e08c2c25b3c7f14647',
        appendToken: true
      });

      res.kernelManager = new KernelManager({ serverSettings: settings });
      res.kernel2 = await res.kernelManager.startNew({ name: 'python3' });
      dbg('Started new kernel:', res.kernel2, res.kernelId);
      await res.kernel2.requestExecute({
        code: 'from websockets.sync.client import unix_connect, connect'
      }).done;
      // ws/socket values managed inside kernel_comm helpers
      // Initialize comm helpers from shared module
      const { callRemoteSocketSend, makeIncomingHandler } = initKernelCommHelpers(res, dbg);

      res.kernelConn = new KernelConnection({
        model: { name: 'python3', id: res.kernelId || kernels[0]['id'] },
        serverSettings: settings
      });
      dbg('Connected to kernel:', res.kernelConn);

      // Kernel comm lifecycle is managed inside kernel_comm helpers

      // Process a parsed command and return the reply message string.
      // This function lives in the same `useEffect` scope so it can be
      // called from multiple places (including outside
      // `handleIncomingCommMessage`). It captures `appletApi` and other
      // surrounding variables as needed.
      const processCommandMessage = async (command: any): Promise<string> => {
        let rmsg: any = null;

        // Handler dictionary for command types. Keep each handler focused
        // on producing the reply payload; the common send/mirroring logic
        // is handled by the caller.
        const handlers: { [k: string]: (cmd: any) => Promise<any> } = {
          command: async (cmd: any) => {
            if (res.appletApi && typeof res.appletApi.evalCommandGetLabels === 'function') {
              const label = res.appletApi.evalCommandGetLabels(cmd.payload);
              return JSON.stringify({
                type: 'created',
                id: cmd.id,
                payload: label
              });
            }
            return JSON.stringify({
              type: 'error',
              id: cmd.id,
              payload: { message: 'applet API not available' }
            });
          },
          function: async (cmd: any) => {
            const apiName = cmd.payload.name;
            dbg('apiName:', apiName);
            let value: any[] = [];
            const args = cmd.payload.args;
            value = [];
            (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
              dbg('call', f, args);
              if (isArrayOfArrays(args)) {
                const value2: any[] = [];
                args.forEach((arg2: any[]) => {
                  if (res.appletApi && typeof res.appletApi[f] === 'function') {
                    value2.push(res.appletApi[f](...arg2) || null);
                  } else {
                    value2.push(null);
                  }
                });
                value.push(value2);
              } else {
                if (args) {
                  value.push(
                    res.appletApi && typeof res.appletApi[f] === 'function' ? res.appletApi[f](...args) || null : null
                  );
                } else {
                  value.push(
                    res.appletApi && typeof res.appletApi[f] === 'function' ? res.appletApi[f]() || null : null
                  );
                }
              }
            });
            value = Array.isArray(apiName) ? value : value[0];
            dbg('Function value:', value);
            return JSON.stringify({
              type: 'value',
              id: cmd.id,
              payload: { value: value }
            });
          },
          // Lightweight listen handler: acknowledge subscription. More
          // elaborate listener registration can be added later if needed.
          listen: async (cmd: any) => {
            dbg('Register listen request:', cmd.payload);
            try {
              // Accept multiple payload shapes: [name, enabled],
              // {name, enabled}, or a simple string (enabled=true).
              let name: string | null = null;
              let enabled = true;
              const p = cmd.payload;
              if (Array.isArray(p)) {
                name = p[0];
                enabled = !!p[1];
              } else if (p && typeof p === 'object') {
                if (typeof p.name === 'string') {
                  name = p.name;
                }
                if (p.enabled !== undefined) {
                  enabled = !!p.enabled;
                } else if (p.enable !== undefined) {
                  enabled = !!p.enable;
                }
              } else if (typeof p === 'string') {
                name = p;
                enabled = true;
              }

              if (!name) {
                throw new Error('listen payload must include object name');
              }

              let result: any = null;
              if (enabled) {
                if (res.appletApi && typeof res.appletApi.registerObjectUpdateListener === 'function') {
                  try {
                    // Provide a callback that forwards updates to the
                    // remote socket; keep it lightweight and non-blocking.
                    // Listener callback: no update argument is provided by the
                    // applet runtime. Instead, call `appletApi.getValueString`
                    // to obtain a serializable representation of the object's
                    // current value and forward it as the event payload.
                    const cb = () => {
                      try {
                        let value: any = null;
                        try {
                          if (res.appletApi && typeof res.appletApi.getValueString === 'function') {
                            value = (res.appletApi.getValueString as any)(name);
                          } else {
                            value = null;
                          }
                        } catch (e) {
                          dbg('getValueString failed', e);
                          value = null;
                        }
                        // Suppress sending when the string value hasn't changed since last send.
                        try {
                          const last = res._lastValues[name] ?? null;
                          const cur = value === null || value === undefined ? null : String(value);
                          if (last !== null && last === cur) {
                            // unchanged, skip notification
                            dbg('Suppressing unchanged value for', name, ':', cur);
                            return;
                          }
                          // update last seen value
                          res._lastValues[name] = cur;
                        } catch (e) {
                          dbg('value-comparison in object update failed', e);
                        }

                        const msg = JSON.stringify({
                          type: 'object_update',
                          // id: cmd.id, // intentionally omitted: object_update events are
                          // queued as asynchronous events and should not carry a
                          // request/response id.
                          payload: { name, value }
                        });
                        // fire-and-forget
                        callRemoteSocketSend(msg).catch(e => dbg('object_update send failed', e));
                      } catch (e) {
                        dbg('Error in object update callback', e);
                      }
                    };
                    // Some implementations may return a listener token.
                    result = await Promise.resolve((res.appletApi.registerObjectUpdateListener as any)(name, cb));
                    // Ensure the current value is delivered immediately after registration
                    try {
                      cb();
                    } catch (e) {
                      dbg('initial object_update send failed', e);
                    }
                  } catch (e) {
                    dbg('registerObjectUpdateListener failed', e);
                    result = { ok: false, error: String(e) };
                  }
                } else {
                  result = {
                    ok: false,
                    error: 'registerObjectUpdateListener not available'
                  };
                }
              } else {
                if (res.appletApi && typeof res.appletApi.unregisterObjectUpdateListener === 'function') {
                  try {
                    result = await Promise.resolve((res.appletApi.unregisterObjectUpdateListener as any)(name));
                  } catch (e) {
                    dbg('unregisterObjectUpdateListener failed', e);
                    result = { ok: false, error: String(e) };
                  }
                } else {
                  result = {
                    ok: false,
                    error: 'unregisterObjectUpdateListener not available'
                  };
                }
              }

              return JSON.stringify({
                type: 'listen',
                id: cmd.id,
                payload: { result }
              });
            } catch (e) {
              dbg('Error in listen handler', e);
              return JSON.stringify({
                type: 'error',
                id: cmd.id,
                payload: { message: String(e) }
              });
            }
          }
        };

        try {
          const h = handlers[command.type];
          if (h) {
            rmsg = await h(command);
          } else {
            dbg('No handler for command type', command.type);
            rmsg = JSON.stringify({
              type: 'error',
              id: command.id,
              payload: { message: 'Unsupported command type' }
            });
          }
        } catch (e) {
          dbg('Handler error for command type', command.type, e);
          rmsg = JSON.stringify({
            type: 'error',
            id: command.id,
            payload: { message: 'Handler execution failed' }
          });
        }

        return rmsg;
      };

      // Handler for incoming messages on the kernel-created comm; defined
      // via kernel_comm helper so it can reuse the shared logic.
      const handleIncomingCommMessage = makeIncomingHandler(processCommandMessage);

      // Kernel comm lifecycle is managed by kernel_comm helpers.

      // Register simple passthrough handlers for jupyter.widget when no
      // widgetManager is present. The helper returns a cleanup function.
      try {
        if (props.widgetManager) {
          dbg('widgetManager present; skipping raw jupyter.widget comm registration to avoid stealing widget opens');
        } else {
          // Delegate widget comm passthrough registration to `widgetManager`
          // module which centralizes that behavior. Provide the minimal
          // option bag expected by the manager helper.
          const opts = {
            callRemoteSocketSend,
            kernel2: res.kernel2,
            socketPath: res.socketPath,
            wsUrl: `ws://localhost:${res.wsPort}/`,
            getAppletApi: () => res.appletApi,
            isArrayOfArrays: isArrayOfArrays,
            dbg
          };

          // registerWidgetCommTargets returns an unregister function
          // which we store on the resource bag for cleanup. Use a clear
          // field name so intent is obvious at call sites.
          const unregisterFn = registerWidgetCommTargets(res.kernelConn, opts as any);
          res.unregisterWidgetCommTargets = unregisterFn;
        }
      } catch (e) {
        dbg('Widget comm target registration skipped or failed', e);
      }

      async function ggbOnLoad(api: any) {
        dbg('GeoGebra applet loaded:', api);
        // expose applet API to other handlers (widgetComm etc.)
        res.appletApi = api;
        (async function () {
          const msg = { type: 'start', payload: {} };
          await callRemoteSocketSend(JSON.stringify(msg));
        })();

        res.resizeHandler = function () {
          const wrapperDiv = document.getElementById(elementId);
          const parentDiv = wrapperDiv?.parentElement;
          const width = parseInt(parentDiv?.style.width || '800');
          const height = parseInt(parentDiv?.style.height || '600');
          api.recalculateEnvironments();
          api.setSize(width, height);
        };
        window.addEventListener('resize', res.resizeHandler);
        res.resizeHandler();

        // // Observe size changes of the widget's DOM element
        // // but not working as expected in Lumino
        // const widgetElemnt = window.document.querySelector('div.lm-DockPanel-widget');
        // const widgetElemnt = window.document.querySelector('div.lm-SplitPanel-child');
        // const widgetElemnt = window.document.querySelector('div[class*="Panel"]');
        // if (widgetElemnt) {
        //   if (widgetRef.current) {
        //     const resizeObserver = new ResizeObserver(() => {
        //         console.log("Panel resized.");
        //         resize();
        //     });
        //     resizeObserver.observe(widgetRef.current); //widgetElemnt);
        //   }
        // }

        if (res.commTarget) {
          res.comm = res.kernelConn.createComm(res.commTarget);
          try {
            // Log comm creation details for debugging 'Comm not found' issues
            try {
              const maybeId = (res.comm as any)?.comm_id || (res.comm as any)?.commId || (res.comm as any)?.id || null;
              dbg('Created kernel comm', {
                target: res.commTarget,
                commObject: res.comm,
                commId: maybeId
              });
            } catch {
              dbg('Created kernel comm (unable to read id)', res.commTarget, res.comm);
            }
            res.comm.open('HELO from GGB').done;
          } catch (e) {
            dbg('Failed to open kernel comm for', res.commTarget, e);
          }
          // Attach close handler to surface unexpected closes
          try {
            res.comm.onClose = (m: any) => {
              try {
                const closedId =
                  (m && m.content && m.content.comm_id) ||
                  (res.comm as any)?.comm_id ||
                  (res.comm as any)?.commId ||
                  null;
                dbg('Kernel comm closed', {
                  target: res.commTarget,
                  commId: closedId,
                  message: m
                });
              } catch (e) {
                dbg('Kernel comm closed (no id available)', res.commTarget, m);
              }
            };
          } catch (e) {
            dbg('Unable to attach onClose to kernel comm', e);
          }
        } else {
          // No kernel-level comm target provided: rely on remote socket
          res.comm = null;
          dbg('No commTarget provided; skipping kernel comm creation');
        }
        // comm.send('HELO2').done

        // kernel.registerCommTarget('test', (comm, commMsg) => {
        // console.log("Comm opened from kernel with message:", commMsg['content']['data']);

        res.closeHandler = () => {
          // Attempt to close comm and shutdown helper kernel
          try {
            res.comm?.close?.();
          } catch (e) {
            console.error(e);
          }
          res.kernel2?.shutdown().catch((err: any) => console.error(err));
          dbg('Kernel and comm closed.');
          if (res.resizeHandler) {
            window.removeEventListener('resize', res.resizeHandler);
          }
        };
        window.addEventListener('close', res.closeHandler);
        if (res.comm) {
          try {
            res.comm.onMsg = handleIncomingCommMessage;
          } catch (e) {
            dbg('Failed to attach handleIncomingCommMessage to comm', e);
          }
        } else {
          dbg('No kernel comm available; messages will be sent via remote socket only');
        }

        const addListener = async function (data: any) {
          dbg('Add listener triggered for:', data);
          const msg = {
            type: 'add',
            payload: data
          };
          // console.log("Add detected:", JSON.stringify(msg));
          // Prefer to send via widget comm bridge if available
          const s = JSON.stringify(msg);
          if (res.widgetComm) {
            try {
              res.widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(s);
        };
        api.registerAddListener(addListener);

        const removeListener = async function (data: any) {
          dbg('Remove listener triggered for:', data);
          const msg = {
            type: 'remove',
            payload: data
          };
          // console.log("Remove detected:", JSON.stringify(msg));
          const s = JSON.stringify(msg);
          if (res.widgetComm) {
            try {
              res.widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(s);
        };
        api.registerRemoveListener(removeListener);

        const renameListener = async function (data: any) {
          dbg('Rename listener triggered for:', data);
          const msg = {
            type: 'rename',
            payload: data
          };
          // console.log("Rename detected:", JSON.stringify(msg));
          const s = JSON.stringify(msg);
          if (res.widgetComm) {
            try {
              res.widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(s);
        };
        api.registerRenameListener(renameListener);

        const clearListener = async function (data: any) {
          dbg('Clear listener triggered for:', data);
          const msg = {
            type: 'clear',
            payload: data
          };
          // console.log("Rename detected:", JSON.stringify(msg));
          const s = JSON.stringify(msg);
          if (res.widgetComm) {
            try {
              res.widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(s);
        };
        api.registerClearListener(clearListener);

        // The `clientListener` example below is kept commented out as a
        // reference for future event types. It's disabled because it
        // was not used in production and could generate noisy traffic.
        // // nothing triggered?
        // var clientListener = async function(data: any) {
        // // console.log("Add listener triggered for:", data);
        //     var msg = {
        //         "type": "client",
        //         "payload": data
        //     }
        //     console.log("Client detected:", JSON.stringify(msg));
        //     await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
        // }
        // api.registerClearListener(clientListener);

        res.observer = new MutationObserver(mutations => {
          mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
              try {
                (node as HTMLElement).querySelectorAll('div.dialogMainPanel > div.dialogTitle').forEach(n => {
                  dbg(n.textContent); // detect titles like 'Error'
                  ((node as HTMLElement).querySelector('div.dialogContent') as HTMLElement)
                    .querySelectorAll("[class$='Label']")
                    .forEach(async n2 => {
                      dbg(n2.textContent);
                      const msg = JSON.stringify({
                        type: n.textContent,
                        payload: n2.textContent
                      });
                      // comm.send(msg);
                      await callRemoteSocketSend(msg);
                    });
                });
              } catch (e) {
                // console.log(e, node);
              }
            });
          });
        });
        res.observer.observe(document.body, { childList: true, subtree: true });
      }

      // Avoid duplicate meta/script inserts: reuse if already present
      const existingMeta = document.getElementById('ggblab-viewport-meta') as HTMLMetaElement | null;
      if (existingMeta) {
        res.metaViewport = existingMeta;
      } else {
        res.metaViewport = document.createElement('meta');
        res.metaViewport.id = 'ggblab-viewport-meta';
        res.metaViewport.name = 'viewport';
        res.metaViewport.content = 'width=device-width, initial-scale=1';
        document.head.appendChild(res.metaViewport);
      }

      const existingScript = document.getElementById('ggblab-deployggb-script') as HTMLScriptElement | null;
      const createApplet = () => {
        const params = {
          id: 'ggbApplet' + (props?.kernelId || '').substring(0, 8), // applet ID
          appName: props?.appName || 'suite', // allow overriding appName via props
          width: 800, // applet width
          height: 600, // applet height
          showToolBar: true, // show the toolbar
          showAlgebraInput: false, // show algebra input field
          showMenuBar: true, // show the menu bar
          autoHeight: true,
          scaleContainerClass: 'lm-Panel', // "lm-DockPanel-widget",
          // autoWidth: false,
          // scale: 2,
          allowUpscale: false,
          appletOnLoad: ggbOnLoad
        };
        applet = new (window as any).GGBApplet(params, true);
        applet.inject(elementId);
        // Expose the active applet instance on `window.ggbApplet` for
        // consistency across the codebase and for debug tooling.
        (window as any).ggbApplet = applet;
      };

      if (existingScript) {
        res.scriptTag = existingScript;
        // If script already loaded and GGBApplet is available, instantiate immediately
        if ((window as any).GGBApplet) {
          createApplet();
        } else {
          // Otherwise ensure we call createApplet once it loads
          res.scriptTag.addEventListener('load', createApplet, { once: true });
        }
      } else {
        res.scriptTag = document.createElement('script');
        res.scriptTag.id = 'ggblab-deployggb-script';
        res.scriptTag.src = 'https://cdn.geogebra.org/apps/deployggb.js';
        res.scriptTag.async = true;
        res.scriptTag.onload = createApplet;
        document.body.appendChild(res.scriptTag);
      }
    });

    return () => {
      // Remove resize listener
      if (res.resizeHandler) {
        window.removeEventListener('resize', res.resizeHandler);
        res.resizeHandler = null;
      }
      // Remove close listener
      if (res.closeHandler) {
        window.removeEventListener('close', res.closeHandler);
        res.closeHandler = null;
      }
      // Disconnect mutation observer
      if (res.observer) {
        try {
          res.observer.disconnect();
        } catch (e) {
          console.error(e);
        }
        res.observer = null;
      }
      // Unregister widget comm handlers if we registered them
      try {
        res.unregisterWidgetCommTargets?.();
        res.unregisterWidgetCommTargets = null;
      } catch (e) {
        dbg('Error unregistering widget comm targets', e);
      }
      // Remove injected meta tag
      if (res.metaViewport && res.metaViewport.parentNode) {
        res.metaViewport.parentNode.removeChild(res.metaViewport);
        res.metaViewport = null;
      }
      // Remove injected script tag
      if (res.scriptTag && res.scriptTag.parentNode) {
        res.scriptTag.parentNode.removeChild(res.scriptTag);
        res.scriptTag = null;
      }
      // Clean up GeoGebra applet
      if (applet) {
        try {
          dbg('Cleaning up GeoGebra applet.');
          // Use the unified `window.ggbApplet` reference when available
          const winApplet = (window as any).ggbApplet || applet;
          try {
            winApplet.remove();
          } catch (e) {
            dbg('Error removing applet instance', e);
          }
        } catch (e) {
          dbg('Error while removing GeoGebra applet', e);
        }
        applet = null;
        delete (window as any).ggbApplet;
      }

      // Close comm and shutdown helper kernel asynchronously via resource bag
      (async () => {
        try {
          await res.dispose();
        } catch (e) {
          console.error('Error during cleanup:', e);
        }
      })();
    };
  }, []);

  return <div id={elementId} ref={widgetRef} style={{ width: '100%', height: '100%' }}></div>;
};

export interface IGGAWidgetProps {
  kernelId?: string;
  commTarget?: string;
  insertMode?: string;
  wsPort?: number;
  socketPath?: string;
  appName?: string;
  // Optional WidgetManager module or instance provided by the plugin activation
  widgetManager?: WidgetManagerType;
}

// // Example of attaching the GeoGebraWidget to a DockPanel
// // but commented out to avoid automatic execution.
// const dock = new DockPanel();
// ReactWidget.attach(dock, document.body);
// // window.addEventListener('resize', () => { dock.update(); });
// dock.layoutModified.connect(() => {
//     console.log("Dock layout modified.");
//     dock.update();
// });

export default GGAComponent;
