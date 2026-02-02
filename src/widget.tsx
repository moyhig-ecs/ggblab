// comm helper functions inlined from kernel_comm.ts to reduce indirection
import { ReactWidget } from '@jupyterlab/ui-components';
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import {
  ServerConnection,
  KernelAPI,
  KernelConnection,
  KernelManager
} from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';
import { DockLayout, Widget } from '@lumino/widgets';
import { Message } from '@lumino/messaging';
import type { WidgetManagerType } from './widgetManager';

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

/**
 * React component for a GeoGebra.
 *
 * @returns The React component
 */
const GGAComponent = (props: IGGAWidgetProps): JSX.Element => {
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

  dbg(
    'Component props: ',
    props.kernelId,
    props.commTarget,
    props.socketPath,
    props.wsPort
  );
  // window.dispatchEvent(new Event('resize'));

  const elementId = 'ggb-element-' + (props?.kernelId || '').substring(0, 8);
  dbg('Element ID:', elementId);

  let applet: any = null;

  function isArrayOfArrays(value: any): boolean {
    return (
      Array.isArray(value) && value.every(subArray => Array.isArray(subArray))
    );
  }

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
  // `sendChain` serializes outgoing socket sends from the helper kernel.
  // The actual send helper is defined inside `useEffect` so it can close
  // over `kernel2`, `socketPath`, and `wsUrl` which are stable for the
  // widget instance.
  let sendChain: Promise<void> = Promise.resolve();

  useEffect(() => {
    // Move frequently-used props into the resource bag for consistency

    // Resource bag: consolidate disposable resources into a single
    // object with a `dispose()` helper so teardown is consistent.
    class Resources {
      kernelId: string;
      commTarget: string;
      socketPath: string | null;
      wsPort: number;
      kernel2: any = null;
      kernelManager: any = null;
      kernelConn: any = null;
      comm: any = null;
      widgetComm: any = null;
      appletApi: any = null;
      _unregisterWidgetComms: (() => void) | null = null;
      observer: MutationObserver | null = null;
      resizeHandler: (() => void) | null = null;
      closeHandler: (() => void) | null = null;
      metaViewport: HTMLMetaElement | null = null;
      scriptTag: HTMLScriptElement | null = null;

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
            this._unregisterWidgetComms?.();
            this._unregisterWidgetComms = null;
          } catch (err) {
            dbg('Error unregistering widget comm targets', err);
          }
        } catch (err) {
          console.error('Error during resources.dispose():', err);
        }
      }
    }

    const res = new Resources(props.kernelId || '', props.commTarget || '', props.socketPath || null, props.wsPort || 8888);

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
      const wsUrl = `ws://localhost:${res.wsPort}/`;
      const socketPath = res.socketPath;
      // callRemoteSocketSend and comm helpers live here so they can use
      // local variables (kernel2, socketPath, wsUrl, kernelConn) without
      // needing cross-file indirection. Interfaces were removed to
      // reduce complexity; opts are plain objects.
      async function callRemoteSocketSend(message: string): Promise<void> {
        try {
          dbg('callRemoteSocketSend: sending message', {
            socketPath,
            wsUrl,
            messagePreview: message.slice(0, 200)
          });
          const doSend = async () => {
            if (socketPath) {
              await res.kernel2.requestExecute({
                code: `
with unix_connect("${socketPath}") as ws:
    ws.send(r"""${message}""")
`
              }).done;
            } else {
              await res.kernel2.requestExecute({
                code: `
with connect("${wsUrl}") as ws:
    ws.send(r"""${message}""")
`
              }).done;
            }
            await new Promise(resolve => setTimeout(resolve, 30));
          };

          const next = sendChain.then(() => doSend());
          // Keep the chain alive but log errors so they are visible during
          // development rather than silently swallowed.
          sendChain = next.catch((e) => {
            dbg && dbg('callRemoteSocketSend chain error', e);
          });
          await next;
          dbg('callRemoteSocketSend: sent', { idPreview: message.slice(0, 40) });
        } catch (err) {
          console.error('callRemoteSocketSend: error sending message', err);
          throw err;
        }
      }

      function attachCommCloseHandler(opts: any) {
        const { c, setClosed, commTarget, dbg } = opts;
        try {
          (c as any).onClose = (m: any) => {
            try {
              setClosed(true);
              const closedId = (m && m.content && m.content.comm_id) || (c as any)?.comm_id || (c as any)?.commId || null;
              dbg && dbg('Kernel comm closed', { target: commTarget, commId: closedId, message: m });
            } catch (e) {
              dbg && dbg('Kernel comm closed (no id available)', commTarget, m);
            }
          };
        } catch (e) {
          dbg && dbg('Unable to attach onClose to kernel comm', e);
        }
      }

      async function ensureKernelComm(opts: any): Promise<any | null> {
        const { kernelConn: kconn, commTarget: ct, handleIncomingCommMessage: h, attachCloseHandler: ach, dbg } = opts;
        try {
          if (!kconn) {
            throw new Error('No kernelConn available to create comm');
          }
          res.comm = kconn.createComm(ct);
          try {
            const maybeId = (res.comm as any)?.comm_id || (res.comm as any)?.commId || (res.comm as any)?.id || null;
            dbg && dbg('Recreated kernel comm', { target: ct, commObject: res.comm, commId: maybeId });
          } catch (err) {
            dbg && dbg('Recreated kernel comm (unable to read id)', ct, res.comm);
          }
          try {
            (res.comm as any).onMsg = h;
          } catch (err) {
            dbg && dbg('Failed to attach onMsg to recreated comm', err);
          }
          try {
            ach && ach(res.comm);
          } catch (err) {
            dbg && dbg('Failed to attach close handler to recreated comm', err);
          }
          try {
            (res.comm as any).open && (res.comm as any).open('REOPEN from GGB').done;
          } catch (err) {
            dbg && dbg('Failed to open recreated comm', err);
          }
          return res.comm;
        } catch (e) {
          dbg && dbg('ensureKernelComm failed', e);
          return null;
        }
      }

      function createHandleIncomingCommMessage() {
        const handler = async (msg: any) => {
          const _dbg = dbg || (() => {});
          _dbg('handleIncomingCommMessage:', msg);
          try {
            _dbg('Kernel comm onMsg received', { commTarget: props.commTarget || '', msg });

            const command = JSON.parse(msg.content.data as any);
            _dbg('Parsed command:', command.type, command.payload);

            let rmsg: any = null;
            try {
              rmsg = await processCommandMessage(command);
            } catch (e) {
              _dbg('Error processing command', e);
              rmsg = JSON.stringify({
                type: 'error',
                id: command?.id || null,
                payload: { message: 'Processing failed' }
              });
            }

            try {
              const cId = (res.comm as any)?.comm_id || (res.comm as any)?.commId || null;
              _dbg('Sending via kernel comm', { commTarget: res.commTarget, commId: cId, preview: (rmsg || '').slice(0, 200) });
              if (!res.comm || commClosed) {
                try {
                  const created = await ensureKernelComm({
                    kernelConn: res.kernelConn,
                    commTarget: res.commTarget,
                    handleIncomingCommMessage: handler,
                    attachCloseHandler: attachCommCloseHandlerLocal,
                    dbg: _dbg
                  });
                  if (created) {
                    res.comm = created;
                    commClosed = false;
                  }
                } catch (e) {
                  _dbg('ensureKernelComm failed before sending reply', e);
                }
              }
              if (res.comm) {
                try {
                  res.comm.send(rmsg);
                } catch (e) {
                  _dbg('Failed to send via kernel comm, will still attempt remote socket send', e, { rmsgPreview: (rmsg || '').slice(0, 200) });
                }
              } else {
                _dbg('No kernel comm available to send reply; will mirror via remote socket');
              }
            } catch (e) {
              _dbg('Failed to send via kernel comm, will still attempt remote socket send', e, { rmsgPreview: (rmsg || '').slice(0, 200) });
            }
            await callRemoteSocketSend(rmsg);
          } catch (e) {
            (dbg || (() => {}))('Error in handleIncomingCommMessage', e);
          }
        };
        return handler;
      }

      res.kernelConn = new KernelConnection({
        model: { name: 'python3', id: res.kernelId || kernels[0]['id'] },
        serverSettings: settings
      });
      dbg('Connected to kernel:', res.kernelConn);

      // Keep comm lifecycle state and helpers for recovery when comms close
      let commClosed = false;
      const attachCommCloseHandlerLocal = (c: any) =>
        attachCommCloseHandler({
          c,
          setClosed: (v: boolean) => {
            commClosed = v;
          },
          commTarget: res.commTarget,
          dbg
        });

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
            const label = res.appletApi.evalCommandGetLabels(cmd.payload);
            return JSON.stringify({
              type: 'created',
              id: cmd.id,
              payload: label
            });
          },
          function: async (cmd: any) => {
            const apiName = cmd.payload.name;
            dbg('apiName:', apiName);
            let value: any[] = [];
            const args = cmd.payload.args;
            value = [];
            (Array.isArray(apiName) ? apiName : [apiName]).forEach(
              (f: string) => {
                dbg('call', f, args);
                if (isArrayOfArrays(args)) {
                  const value2: any[] = [];
                          args.forEach((arg2: any[]) => {
                    if (args) {
                      value2.push(res.appletApi[f](...arg2) || null);
                    } else {
                      value2.push(res.appletApi[f]() || null);
                    }
                  });
                  value.push(value2);
                } else {
                    if (args) {
                    value.push(res.appletApi[f](...args) || null);
                  } else {
                    value.push(res.appletApi[f]() || null);
                  }
                }
              }
            );
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
                if (
                    typeof res.appletApi.registerObjectUpdateListener === 'function'
                ) {
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
                          value = (res.appletApi.getValueString as any)(name);
                        } catch (e) {
                          dbg('getValueString failed', e);
                          value = null;
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
                    result = await Promise.resolve(
                      (res.appletApi.registerObjectUpdateListener as any)(name, cb)
                    );
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
                if (
                  typeof res.appletApi.unregisterObjectUpdateListener === 'function'
                ) {
                  try {
                    result = await Promise.resolve(
                      (res.appletApi.unregisterObjectUpdateListener as any)(name)
                    );
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
      // once so it can be reattached if we recreate the comm.
      const handleIncomingCommMessage = createHandleIncomingCommMessage();

      // Kernel comm lifecycle is managed by kernel_comm helpers.

      // Register simple passthrough handlers for jupyter.widget when no
      // widgetManager is present. The helper returns a cleanup function.
      try {
          if (props.widgetManager) {
          dbg(
            'widgetManager present; skipping raw jupyter.widget comm registration to avoid stealing widget opens'
          );
        } else {
          // Inline lightweight widget comm passthrough to avoid passing
          // scope-shared arguments around; feature is behind a flag in
          // the original module but we keep the same behavior here.
          const registerWidgetCommTargetsLocal = (kconn: any) => {
            const ENABLE_WIDGET_COMM_PASSTHROUGH = false;
            if (!ENABLE_WIDGET_COMM_PASSTHROUGH) {
              dbg && dbg('Widget comm passthrough disabled by flag');
              return () => {};
            }

            const _dbg = dbg || (() => {});

            const simpleHandler = (commOp: any, msg: any) => {
              _dbg('widget comm opened (jupyter.widget)', commOp, msg);
              try {
                commOp.onMsg = async (m: any) => {
                  const content = m?.content?.data || m;
                  try {
                    const command = typeof content === 'string' ? JSON.parse(content) : content;
                    let rmsg: any = null;
                    const applet = res.appletApi;
                    if (command.type === 'command' && applet) {
                      const label = applet.evalCommandGetLabels(command.payload);
                      rmsg = JSON.stringify({ type: 'created', id: command.id, payload: label });
                    } else if (command.type === 'function' && applet) {
                      const apiName = command.payload.name;
                      const args = command.payload.args;
                      let value: any[] = [];
                      (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
                        if (isArrayOfArrays(args)) {
                          const v2: any[] = [];
                          args.forEach((a: any[]) => {
                            v2.push(applet[f](...a) || null);
                          });
                          value.push(v2);
                        } else {
                          value.push(args ? applet[f](...args) || null : applet[f]() || null);
                        }
                      });
                      value = Array.isArray(apiName) ? value : value[0];
                      rmsg = JSON.stringify({ type: 'value', id: command.id, payload: { value } });
                    }
                    if (rmsg) {
                      try {
                        commOp.send(rmsg);
                      } catch (e) {
                        _dbg('commOp.send failed', e);
                      }
                      try {
                        await callRemoteSocketSend(rmsg);
                      } catch (e) {
                        _dbg('callRemoteSocketSend failed', e);
                      }
                    }
                  } catch (e) {
                    _dbg('Error handling widget comm message', e);
                  }
                };
              } catch (e) {
                _dbg('Failed to attach onMsg to widget comm', e);
              }
            };

            try {
              kconn.registerCommTarget('jupyter.widget', simpleHandler);
              kconn.registerCommTarget('jupyter.widget.control', simpleHandler);
            } catch (e) {
              _dbg('Widget comm target registration failed', e);
            }

            return () => {
              try {
                if (typeof kconn.unregisterCommTarget === 'function') {
                  kconn.unregisterCommTarget('jupyter.widget');
                  kconn.unregisterCommTarget('jupyter.widget.control');
                }
              } catch (e) {
                _dbg('Error during widget comm cleanup', e);
              }
            };
          };

          res._unregisterWidgetComms = registerWidgetCommTargetsLocal(res.kernelConn);
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
        // if (widgetRef.current) {
        //     const resizeObserver = new ResizeObserver(() => {
        //         console.log("Panel resized.");
        //         resize();
        //     });
        //     resizeObserver.observe(widgetRef.current); //widgetElemnt);
        // }

        if (res.commTarget) {
          res.comm = res.kernelConn.createComm(res.commTarget);
          try {
            // Log comm creation details for debugging 'Comm not found' issues
            try {
              const maybeId =
                (res.comm as any)?.comm_id ||
                (res.comm as any)?.commId ||
                (res.comm as any)?.id ||
                null;
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
          dbg(
            'No kernel comm available; messages will be sent via remote socket only'
          );
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
                (node as HTMLElement)
                  .querySelectorAll('div.dialogMainPanel > div.dialogTitle')
                  .forEach(n => {
                    dbg(n.textContent); // detect titles like 'Error'
                    (
                      (node as HTMLElement).querySelector(
                        'div.dialogContent'
                      ) as HTMLElement
                    )
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
      const existingMeta = document.getElementById(
        'ggblab-viewport-meta'
      ) as HTMLMetaElement | null;
      if (existingMeta) {
        res.metaViewport = existingMeta;
      } else {
        res.metaViewport = document.createElement('meta');
        res.metaViewport.id = 'ggblab-viewport-meta';
        res.metaViewport.name = 'viewport';
        res.metaViewport.content = 'width=device-width, initial-scale=1';
        document.head.appendChild(res.metaViewport);
      }

      const existingScript = document.getElementById(
        'ggblab-deployggb-script'
      ) as HTMLScriptElement | null;
      const createApplet = () => {
        const params = {
          id: 'ggbApplet' + (props?.kernelId || '').substring(0, 8), // applet ID
          appName: 'suite', // specify GeoGebra Classic smart applet
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
        res._unregisterWidgetComms?.();
        res._unregisterWidgetComms = null;
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

  return (
    <div
      id={elementId}
      ref={widgetRef}
      style={{ width: '100%', height: '100%' }}
    ></div>
  );
};

interface IGGAWidgetProps {
  kernelId?: string;
  commTarget?: string;
  insertMode?: DockLayout.InsertMode;
  wsPort?: number;
  socketPath?: string;
  // Optional WidgetManager module or instance provided by the plugin activation
  widgetManager?: WidgetManagerType;
}

/**
 * A GeoGebra Lumino Widget that wraps a GeoGebraComponent.
 */
export class GeoGebraWidget extends ReactWidget {
  private props: IGGAWidgetProps | undefined;

  /**
   * Constructs a new GeoGebraWidget.
   */
  constructor(props?: IGGAWidgetProps) {
    super();
    this.addClass('jp-ggblabWidget');
    this.props = props;
  }

  render(): JSX.Element {
    return (
      <GGAComponent
        kernelId={this.props?.kernelId}
        commTarget={this.props?.commTarget}
        wsPort={this.props?.wsPort}
        socketPath={this.props?.socketPath}
        widgetManager={this.props?.widgetManager}
      />
    );
  }

  // only onResize is responsible for size changes in Lumino,
  // but onAfterAttach and onAfterShow and onFitRequest may also be relevant in some cases.
  protected onResize(msg: Widget.ResizeMessage): void {
    // console.log("GeoGebraWidget resized:", msg.width, msg.height);
    window.dispatchEvent(new Event('resize'));
    super.onResize(msg);
  }

  // Only perform cleanup when the widget is explicitly closed by the user.
  // Use onCloseRequest to trigger cleanup so that transient disposals
  // during layout/restore operations do not tear down the internal state.
  protected onCloseRequest(msg: Message): void {
    dbg('GeoGebraWidget onCloseRequest — performing cleanup.');
    window.dispatchEvent(new Event('close'));
    super.onCloseRequest(msg);
  }

  // dispose should not trigger cleanup again; allow normal disposal to proceed
  // without duplicating shutdown logic.
  dispose(): void {
    dbg('GeoGebraWidget disposed.');
    super.dispose();
  }
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
