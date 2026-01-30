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

  // Normalize kernelId early to avoid undefined issues when props are missing
  const kernelId = props?.kernelId || '';
  dbg(
    'Component props: ',
    kernelId,
    props.commTarget,
    props.socketPath,
    props.wsPort
  );

  const elementId = 'ggb-element-' + kernelId.substring(0, 8);
  dbg('Element ID:', elementId);

  let applet: any = null;

  // Prefer a widget manager explicitly passed via props. Global manager
  // registration has been removed; do not attempt to read `window.__ggblab_widget_manager`.
  const effectiveWidgetManager = (props as any).widgetManager;
  dbg('effectiveWidgetManager resolved:', !!effectiveWidgetManager, {
    kernelId
  });

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
  // Serialize outgoing socket sends to avoid kernel-side requestExecute jams.
  // `sendChain` is a promise chain that ensures each send completes before
  // the next begins. We also add a small inter-send delay to give the
  // remote helper kernel time to tear down connections.
  let sendChain: Promise<void> = Promise.resolve();

  async function callRemoteSocketSend(
    kernel2: any,
    message: string,
    socketPath: string | null,
    wsUrl: string
  ): Promise<void> {
    try {
      dbg('callRemoteSocketSend: sending message', {
        socketPath,
        wsUrl,
        messagePreview: message.slice(0, 200)
      });
      // Queue the actual send work on the chain so sends are serialized.
      const doSend = async () => {
        if (socketPath) {
          await kernel2.requestExecute({
            code: `
with unix_connect("${socketPath}") as ws:
    ws.send(r"""${message}""")
`
          }).done;
        } else {
          await kernel2.requestExecute({
            code: `
with connect("${wsUrl}") as ws:
    ws.send(r"""${message}""")
`
          }).done;
        }

        await new Promise(resolve => setTimeout(resolve, 30));
      };

      // Append to chain and ensure errors don't break future sends.
      const next = sendChain.then(() => doSend());
      // swallow errors on chain so chain remains healthy
      sendChain = next.catch(() => {
        /* ignore errors to keep chain alive */
      });
      await next;
      try {
        dbg('callRemoteSocketSend: sent', { idPreview: message.slice(0, 40) });
      } catch (e) {
        /* ignore */
      }
    } catch (err) {
      try {
        console.error('callRemoteSocketSend: error sending message', err);
      } catch (e) {
        /* ignore */
      }
      throw err;
    }
  }

  useEffect(() => {
    // No global widget-manager events are used now.
    // Track resources created during effect so we can clean them up precisely
    let kernel2: any = null;
    let kernelManager: any = null;
    let kernelConn: any = null;
    let comm: any = null;
    // Reserved for future ipywidgets-based bridge (kept intentionally).
    // When enabled, `widgetComm` will be assigned to a frontend-managed
    // widget comm to allow in-kernel widgets to be routed directly to
    // the GeoGebra instance without using the remote socket.
    let widgetComm: any = null;
    let managerAdopted = false;
    const registeredKernelTargets: string[] = [];
    let appletApi: any = null;
    let observer: MutationObserver | null = null;
    let resizeHandler: (() => void) | null = null;
    let closeHandler: (() => void) | null = null;
    let metaViewport: HTMLMetaElement | null = null;
    let scriptTag: HTMLScriptElement | null = null;

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

      kernelManager = new KernelManager({ serverSettings: settings });
      kernel2 = await kernelManager.startNew({ name: 'python3' });
      dbg('Started new kernel:', kernel2, kernelId);
      await kernel2.requestExecute({
        code: 'from websockets.sync.client import unix_connect, connect'
      }).done;

      const wsUrl = `ws://localhost:${props.wsPort}/`;
      const socketPath = props.socketPath || null;

      // Try an early out-of-band probe so the kernel may mark the
      // helper-server channel as ready for same-cell replies. This is
      // a fire-and-forget probe executed on the helper kernel (`kernel2`).
      try {
        const probeMsg = JSON.stringify({ type: 'probe', payload: 'ready' });
        // fire-and-forget the probe so we don't block the widget mount
        callRemoteSocketSend(kernel2, probeMsg, socketPath, wsUrl).catch(
          (e: any) => dbg('probe send failed', e)
        );
        dbg('Sent early OOB probe via helper kernel');
        // Also send an explicit oob_ready signal so the kernel can
        // mark the out-of-band channel as ready for same-cell replies.
        try {
          const readyMsg = JSON.stringify({
            type: 'oob_ready',
            payload: 'frontend'
          });
          callRemoteSocketSend(kernel2, readyMsg, socketPath, wsUrl).catch(
            (e: any) => dbg('oob_ready send failed', e)
          );
          dbg('Sent explicit oob_ready via helper kernel');
        } catch (e) {
          dbg('Failed to schedule oob_ready send', e);
        }
      } catch (e) {
        dbg('Failed to schedule early OOB probe', e);
      }

      kernelConn = new KernelConnection({
        model: { name: 'python3', id: kernelId || kernels[0]['id'] },
        serverSettings: settings
      });
      dbg('Connected to kernel:', kernelConn);

      // Keep comm lifecycle state and helpers for recovery when comms close
      let commClosed = false;
      const attachCommCloseHandler = (c: any) => {
        try {
          (c as any).onClose = (m: any) => {
            try {
              commClosed = true;
              const closedId =
                (m && m.content && m.content.comm_id) ||
                (c as any)?.comm_id ||
                (c as any)?.commId ||
                null;
              dbg('Kernel comm closed', {
                target: props.commTarget,
                commId: closedId,
                message: m
              });
            } catch (e) {
              dbg('Kernel comm closed (no id available)', props.commTarget, m);
            }
              try {
                // cleanup global stores when this comm closes
                let cid: string | null = null;
                try {
                  cid = (m && m.content && m.content.comm_id) || (c as any)?.comm_id || (c as any)?.commId || null;
                  if (cid && (window as any).__ggblab_comm_by_id) {
                    try {
                      delete (window as any).__ggblab_comm_by_id[cid];
                    } catch (ee) {
                      /* ignore */
                    }
                  }
                } catch (ee) {
                  /* ignore */
                }
              try {
                const sk = kernelId || (kernelConn as any)?.id || null;
                if (sk && (window as any).__ggblab_comm_store) {
                  try {
                    const cur = (window as any).__ggblab_comm_store[sk];
                    if (cur === c) {
                      delete (window as any).__ggblab_comm_store[sk];
                      dbg('Removed comm from __ggblab_comm_store on close', sk, cid);
                    }
                  } catch (ee) {
                    /* ignore */
                  }
                }
              } catch (ee) {
                /* ignore */
              }
            } catch (ee) {
              /* ignore cleanup errors */
            }
          };
        } catch (e) {
          dbg('Unable to attach onClose to kernel comm', e);
        }
      };

      // Centralized processing of a parsed command and sending replies.
      // `sourceComm` is optional and, when provided, will be used to
      // send the reply. Otherwise we fall back to the kernel-side `comm`
      // or the remote socket.
      const processCommand = async (command: any, sourceComm?: any) => {
        try {
          dbg('processCommand:', command?.type, command?.payload);
          let rmsg: any = null;
          if (!appletApi) {
            dbg('Applet API not ready; cannot service command');
            return;
          }

          if (command.type === 'command') {
            const label = appletApi.evalCommandGetLabels(command.payload);
            rmsg = JSON.stringify({
              type: 'created',
              id: command.id,
              payload: label
            });
          } else if (command.type === 'function') {
            const apiName = command.payload.name;
            const args = command.payload.args;
            let value: any[] = [];
            (Array.isArray(apiName) ? apiName : [apiName]).forEach(
              (f: string) => {
                if (isArrayOfArrays(args)) {
                  const v2: any[] = [];
                  args.forEach((a: any[]) => {
                    v2.push(appletApi[f](...a) || null);
                  });
                  value.push(v2);
                } else {
                  value.push(
                    args
                      ? appletApi[f](...args) || null
                      : appletApi[f]() || null
                  );
                }
              }
            );
            value = Array.isArray(apiName) ? value : value[0];
            rmsg = JSON.stringify({
              type: 'value',
              id: command.id,
              payload: { value }
            });
          }

          if (!rmsg) {
            return;
          }

          // Prefer replying on the source comm (widget-manager comm)
          // if provided. Next prefer the kernel-created comm. Fallback
          // to callRemoteSocketSend.
          try {
            if (sourceComm && typeof sourceComm.send === 'function') {
              try {
                sourceComm.send(rmsg);
                dbg('Replied via sourceComm');
              } catch (e) {
                dbg('sourceComm.send failed', e);
                throw e;
              }
              return;
            }
          } catch (e) {
            dbg('Error sending via sourceComm', e);
          }

          try {
            if (!comm || commClosed) {
              await ensureKernelComm();
            }
            if (comm && typeof comm.send === 'function') {
              try {
                comm.send(rmsg);
                dbg('Replied via kernel comm');
                return;
              } catch (e) {
                dbg('kernel comm.send failed', e);
                try {
                  dbg('Fallback: send failed, forwarding to remote socket');
                  await callRemoteSocketSend(kernel2, rmsg, socketPath, wsUrl);
                  dbg('Fallback: forwarded to remote socket');
                } catch (ee) {
                  dbg('Fallback remote socket send failed', ee);
                }

                // Attempt to re-warm a frontend comm on failure and retry
                try {
                  if (kernelConn && typeof (kernelConn as any).createComm === 'function') {
                    try {
                      const newComm: any = (kernelConn as any).createComm(props.commTarget);
                      try {
                        newComm.onMsg = handleIncomingCommMessage;
                      } catch (ee) {
                        /* ignore */
                      }
                      attachCommCloseHandler(newComm);
                      try {
                        newComm.open && newComm.open('re-warm from ggblab');
                      } catch (ee) {
                        /* ignore */
                      }
                      try {
                        (window as any).__ggblab_comm_store = (window as any).__ggblab_comm_store || {};
                        const sk = kernelId || (kernelConn as any)?.id || null;
                        if (sk) (window as any).__ggblab_comm_store[sk] = newComm;
                      } catch (ee) {
                        /* ignore */
                      }
                      try {
                        (window as any).__ggblab_comm_by_id = (window as any).__ggblab_comm_by_id || {};
                        const mid = newComm && (newComm.comm_id || newComm.commId || null);
                        if (mid) {
                          (window as any).__ggblab_comm_by_id[mid] = newComm;
                          try {
                            (window as any).__ggblab_comm_by_id[mid].__ggblab_meta = {
                              source: 're-warmed',
                              kernelId: kernelId || (kernelConn as any)?.id || null,
                              when: new Date().toISOString()
                            };
                          } catch (ee) {
                            /* ignore */
                          }
                        }
                      } catch (ee) {
                        /* ignore */
                      }
                      // replace comm reference and retry send
                      comm = newComm;
                      commClosed = false;
                      try {
                        comm.send(rmsg);
                        dbg('Replied via re-warmed comm');
                        return;
                      } catch (ee) {
                        dbg('re-warmed comm send failed', ee);
                      }
                    } catch (ee) {
                      dbg('Failed to re-warm comm', ee);
                    }
                  }
                } catch (ee) {
                  dbg('Re-warm attempt failed', ee);
                }
              }
            }
          } catch (e) {
            dbg('Error sending via kernel comm', e);
          }

          // Last resort: mirror to remote socket
          try {
            await callRemoteSocketSend(kernel2, rmsg, socketPath, wsUrl);
            dbg('Replied via remote socket');
          } catch (e) {
            dbg('Failed to reply via remote socket', e);
          }
        } catch (e) {
          dbg('processCommand error', e);
        }
      };

      // Handler for incoming messages on the kernel-created comm; defined
      // once so it can be reattached if we recreate the comm. This assumes
      // kernel comm messages place the command JSON in `msg.content.data`.
      const handleIncomingCommMessage = async (msg: any) => {
        dbg('handleIncomingCommMessage:', msg);
        try {
          const data = msg?.content?.data || msg;
          const command = typeof data === 'string' ? JSON.parse(data) : data;
          await processCommand(command, /* sourceComm */ comm);
        } catch (e) {
          dbg('Error in handleIncomingCommMessage', e);
        }
      };

      // Ensure a kernel comm exists; create and attach handlers if missing.
      const ensureKernelComm = async () => {
        if (comm && !commClosed) {
          return comm;
        }
        try {
          // If an early frontend-side comm was registered (plugin activation)
          // reuse it. This allows comm_open from the kernel to be accepted
          // before the widget fully mounts.
          let pre: any = null;
          try {
            const store = (window as any).__ggblab_comm_store || {};
            // Prefer any comm in the by-id map that was tagged for this kernelId
            try {
              const byId = (window as any).__ggblab_comm_by_id || {};
              const lookupKeyForById = kernelId || (kernelConn as any)?.id || '';
              let firstNoMeta: any = null;
              const byIdKeys = Object.keys(byId || {});
              if (lookupKeyForById) {
                for (const k in byId) {
                  try {
                    const candidate = (byId as any)[k];
                    const meta = candidate && (candidate.__ggblab_meta || {});
                    if (meta && meta.kernelId) {
                      const mid = meta.kernelId;
                      const matches =
                        mid === lookupKeyForById ||
                        (lookupKeyForById && mid.startsWith(lookupKeyForById)) ||
                        (mid && lookupKeyForById && lookupKeyForById.startsWith(mid));
                      if (matches) {
                        pre = candidate;
                        dbg('Found pre-registered comm by by_id map', k, lookupKeyForById, meta && meta.source, 'meta.kernelId=', mid);
                        break;
                      }
                    }
                    // remember first candidate that lacks meta for fallback
                    if (!meta && !firstNoMeta) {
                      firstNoMeta = candidate;
                    }
                  } catch (ee) {
                    /* ignore per-entry errors */
                  }
                }
              }
              // Fallback: if no meta-based match found but there is exactly
              // one by-id entry, accept it as the pre-registered comm. This
              // is a pragmatic fallback for older builds that didn't attach
              // meta; prefer explicit meta matches when available.
              try {
                if (!pre && !firstNoMeta && byIdKeys.length === 1) {
                  firstNoMeta = (byId as any)[byIdKeys[0]];
                }
                if (!pre && firstNoMeta && byIdKeys.length === 1) {
                  pre = firstNoMeta;
                  dbg('Using sole by-id candidate without meta as fallback', byIdKeys[0]);
                }
              } catch (ee) {
                /* ignore fallback errors */
              }
            } catch (ee) {
              /* ignore by-id lookup errors */
            }
            // Prefer an explicit kernelId passed via props. If missing,
            // fallback to the id exposed by the connected kernelConn so
            // that widgets that omitted `kernelId` still reuse pre-registered
            // comms created during plugin activation.
            const lookupKey = kernelId || (kernelConn as any)?.id || '';
            // Try exact key first; if not found, allow prefix matches so
            // short kernelId values (e.g. "269127d0") match full UUID keys.
            let storeKey = lookupKey;
            if (lookupKey && !store[lookupKey]) {
              for (const sk in store) {
                try {
                  if (sk.startsWith(lookupKey) || lookupKey.startsWith(sk)) {
                    storeKey = sk;
                    dbg('Mapped lookupKey to store key', lookupKey, '->', sk);
                    break;
                  }
                } catch (ee) {
                  /* ignore */
                }
              }
            }
            if (storeKey && store[storeKey]) {
              pre = store[storeKey];
            } else if (lookupKey) {
              // If no direct store entry, check for queued comm-open messages
              try {
                const qstore = (window as any).__ggblab_comm_queue || {};
                const q = qstore[lookupKey] || [];
                if (q && q.length) {
                  // Attempt to extract a comm id from the queued message
                  const m0 = q.shift();
                  try {
                    const maybeCommId =
                      (m0 && m0.content && m0.content.comm_id) ||
                      (m0 && m0.comm_id) ||
                      null;
                    if (maybeCommId) {
                      const byId = (window as any).__ggblab_comm_by_id || {};
                      if (byId[maybeCommId]) {
                        pre = byId[maybeCommId];
                        dbg(
                          'Found pre-registered comm by commId from queue',
                          maybeCommId
                        );
                        // update the queue store after shifting
                        (window as any).__ggblab_comm_queue[lookupKey] = q;
                      }
                    }
                  } catch (ee) {
                    /* ignore parsing errors */
                  }
                }
              } catch (ee) {
                /* ignore queue errors */
              }
            }
            if (pre) {
              comm = pre;
              try {
                comm.onMsg = handleIncomingCommMessage;
              } catch (e) {
                dbg('Failed to attach onMsg to pre-registered comm', e);
              }
              attachCommCloseHandler(comm);
              commClosed = false;
              dbg(
                'Using pre-registered frontend comm for kernel',
                kernelId || (kernelConn as any).id
              );
              try {
                (window as any).__ggblab_comm_by_id = (window as any).__ggblab_comm_by_id || {};
                const maybeId = (comm as any)?.comm_id || (comm as any)?.commId || null;
                if (maybeId) {
                  (window as any).__ggblab_comm_by_id[maybeId] = comm;
                  (window as any).__ggblab_comm_by_id[maybeId].__ggblab_meta = {
                    source: 'pre-registered',
                    kernelId: kernelId || (kernelConn as any)?.id || null,
                    when: new Date().toISOString()
                  };
                  dbg('Marked comm as pre-registered', maybeId);
                }
              } catch (e) {
                dbg('Failed to mark pre-registered comm by id', e);
              }
              try {
                // Visible, persistent console output for timing/debugging
                // eslint-disable-next-line no-console
                console.log('[ggblab] using pre-registered comm', {
                  when: new Date().toISOString(),
                  lookupKey: kernelId || (kernelConn as any).id,
                  commId:
                    (comm as any)?.comm_id || (comm as any)?.commId || null
                });
              } catch (e) {
                /* ignore logging errors */
              }
              return comm;
            }
          } catch (e) {
            dbg('Error checking pre-registered comm store', e);
          }
          // If no pre-registered comm found yet, wait briefly for one to arrive
          // (mitigates race where comm_open arrives just after we check).
          if (!pre) {
            try {
              dbg('No pre-registered comm found — waiting briefly for arrival');
              const waitForPre = async (timeout = 2000, interval = 50) => {
                const end = Date.now() + timeout;
                const lookupKey = kernelId || (kernelConn as any)?.id || '';
                while (Date.now() < end) {
                  // check by-id map
                  try {
                    const byId = (window as any).__ggblab_comm_by_id || {};
                    if (lookupKey) {
                      for (const k in byId) {
                        try {
                          const candidate = (byId as any)[k];
                          const meta = candidate && (candidate.__ggblab_meta || {});
                                  if (meta && meta.kernelId) {
                                    const mid = meta.kernelId;
                                    const matches =
                                      mid === lookupKey ||
                                      (lookupKey && mid.startsWith(lookupKey)) ||
                                      (mid && lookupKey && lookupKey.startsWith(mid));
                                    if (matches) {
                                      dbg('waitForPre: found by-id', k, 'meta.kernelId=', mid);
                                      return (byId as any)[k];
                                    }
                                  }
                        } catch (ee) {
                          /* ignore */
                        }
                      }
                    }
                  } catch (ee) {
                    /* ignore */
                  }
                  // check store
                  try {
                    const store2 = (window as any).__ggblab_comm_store || {};
                    if (lookupKey && store2[lookupKey]) {
                      dbg('waitForPre: found in store', lookupKey);
                      return store2[lookupKey];
                    }
                    // allow prefix matches for short kernel ids
                    if (lookupKey) {
                      for (const sk in store2) {
                        try {
                          if (sk.startsWith(lookupKey) || lookupKey.startsWith(sk)) {
                            dbg('waitForPre: found in store by prefix', lookupKey, '->', sk);
                            return store2[sk];
                          }
                        } catch (ee) {
                          /* ignore */
                        }
                      }
                    }
                  } catch (ee) {
                    /* ignore */
                  }
                  // check queue
                  try {
                    const qstore = (window as any).__ggblab_comm_queue || {};
                    const q = lookupKey ? qstore[lookupKey] || [] : [];
                    if (q && q.length) {
                      const m0 = q[0];
                      const maybeCommId = (m0 && m0.content && m0.content.comm_id) || (m0 && m0.comm_id) || null;
                      if (maybeCommId) {
                        const byId2 = (window as any).__ggblab_comm_by_id || {};
                        if (byId2[maybeCommId]) {
                          dbg('waitForPre: found byId from queue', maybeCommId);
                          return byId2[maybeCommId];
                        }
                      }
                    }
                  } catch (ee) {
                    /* ignore */
                  }
                  await new Promise(r => setTimeout(r, interval));
                }
                return null;
              };
              const arrived = await waitForPre(2000, 50);
              if (arrived) {
                pre = arrived;
                dbg('Pre-registered comm arrived during wait');
              } else {
                dbg('No pre-registered comm arrived within wait period');
                try {
                  if ((window as any).ggblabDebugMessages) {
                    // Verbose dump for debugging old/new frontend mismatch
                    try {
                      // eslint-disable-next-line no-console
                      console.log('[ggblab] debug dump: __ggblab_comm_store keys', Object.keys((window as any).__ggblab_comm_store || {}));
                      // eslint-disable-next-line no-console
                      console.log('[ggblab] debug dump: __ggblab_comm_by_id keys', Object.keys((window as any).__ggblab_comm_by_id || {}));
                      const byId = (window as any).__ggblab_comm_by_id || {};
                      for (const k of Object.keys(byId)) {
                        try {
                          // eslint-disable-next-line no-console
                          console.log('[ggblab] debug dump: by_id entry', k, byId[k] && byId[k].__ggblab_meta);
                        } catch (ee) {
                          /* ignore */
                        }
                      }
                    } catch (ee) {
                      /* ignore debug dump errors */
                    }
                  }
                } catch (ee) {
                  /* ignore */
                }
              }
            } catch (ee) {
              /* ignore wait errors */
            }
          }
          // If no pre-registered comm arrived, do not create a fallback
          // comm here. Removing the recreate fallback simplifies reasoning
          // and ensures widgets only reuse frontend-accepted comms.
          if (!pre) {
            dbg('No pre-registered comm available; skipping recreate fallback');
            return null;
          }
        } catch (e) {
          dbg('ensureKernelComm failed', e);
          return null;
        }
      };

      // Register handlers to accept widget-model comms created by the kernel's
      // ipywidgets machinery. When the kernel creates a widget (e.g. IntSlider)
      // it will open a comm to the frontend with target 'jupyter.widget'
      // (and sometimes 'jupyter.widget.control'). We register a simple
      // passthrough handler only when no widgetManager is present; if a
      // widgetManager is available we must not intercept those comms.
      try {
        // Small delay to give any late-arriving manager passed via props
        await new Promise(res => setTimeout(res, 120));
        const lateMgr = (props as any).widgetManager;
        if (lateMgr) {
          dbg(
            'Widget manager provided via props; skipping passthrough registration'
          );
        } else {
          dbg(
            'No widget manager provided; registering passthrough comm targets'
          );
          const registerTarget = (target: string) => {
            try {
              if (registeredKernelTargets.includes(target)) {
                dbg('Skipping duplicate registration for target', target);
                return;
              }
              kernelConn.registerCommTarget(target, (c: any, msg: any) => {
                try {
                  dbg('Accepted comm open for target', target, { msg });
                  try {
                    c.onMsg = handleIncomingCommMessage;
                  } catch (e) {
                    dbg('Failed to attach onMsg to incoming comm', e);
                  }
                  attachCommCloseHandler(c);
                  comm = c;
                  try {
                    (window as any).__ggblab_comm_by_id = (window as any).__ggblab_comm_by_id || {};
                    const cid = (c && (c.comm_id || c.commId)) || null;
                    if (cid) {
                      (window as any).__ggblab_comm_by_id[cid] = c;
                      (window as any).__ggblab_comm_by_id[cid].__ggblab_meta = {
                        source: 'accepted-target',
                        target,
                        kernelId: props?.kernelId || (kernelConn as any)?.id || null,
                        when: new Date().toISOString()
                      };
                      dbg('Marked accepted incoming comm', cid, target);
                    }
                  } catch (e) {
                    dbg('Failed to mark accepted incoming comm', e);
                  }
                  try {
                    // eslint-disable-next-line no-console
                    console.log('[ggblab] accepted comm open', {
                      when: new Date().toISOString(),
                      target,
                      kernelId: props?.kernelId || kernelConn?.id || null,
                      msg
                    });
                  } catch (e) {
                    /* ignore */
                  }
                } catch (e) {
                  dbg('Error handling incoming comm open', e);
                }
              });
              registeredKernelTargets.push(target);
              dbg('Registered comm target', target);
            } catch (e) {
              dbg('Failed to register comm target', target, e);
            }
          };

          // Register common widget manager targets and the ggblab-specific target
          // try { registerTarget('jupyter.widget.control'); } catch (e) { /* ignore */ }
          try {
            registerTarget(props.commTarget || 'ggblab-comm');
          } catch (e) {
            /* ignore */
          }
        }
      } catch (e) {
        dbg('Widget comm target registration skipped or failed', e);
      }

      // Adopt a WidgetManager if/when it appears at runtime.
      const adoptWidgetManager = (mgr: any) => {
        try {
          if (!mgr) {
            return;
          }
          if (managerAdopted) {
            return;
          }
          const commManager =
            mgr?.comm_manager ||
            mgr?.commManager ||
            mgr?._commManager ||
            mgr?._manager?.comm_manager ||
            mgr?._kernel?.comm_manager ||
            null;
          if (
            !commManager ||
            typeof commManager.register_target !== 'function'
          ) {
            dbg(
              'adoptWidgetManager: no comm_manager available on manager',
              !!commManager
            );
            return;
          }
          managerAdopted = true;
          dbg('Adopting widget manager; registering targets on commManager');

          const attachHandler = (commOp: any, msg: any, sourceName: string) => {
            dbg('manager adapter: comm opened', sourceName, commOp, msg);
            try {
              widgetComm = commOp;
              const handler = async (m: any) => {
                const data = m?.content?.data || m;
                const command =
                  typeof data === 'string' ? JSON.parse(data) : data;
                await processCommand(command, widgetComm);
              };
              try {
                if (typeof commOp.on_msg === 'function') {
                  commOp.on_msg(handler);
                } else if (typeof commOp.onMsg === 'function') {
                  commOp.onMsg = handler;
                } else if (typeof commOp.on === 'function') {
                  commOp.on('msg', handler);
                } else if ('on_msg' in commOp) {
                  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                  // @ts-ignore
                  commOp.on_msg = handler;
                } else {
                  try {
                    commOp.onMsg = handler;
                  } catch (e) {
                    dbg('Unable to attach handler to commOp', e);
                  }
                }
              } catch (e) {
                dbg(
                  'Failed to attach message handler to manager-provided comm',
                  e
                );
              }
            } catch (e) {
              dbg('Error in manager adapter comm handler', e);
            }
          };

          const tryRegister = (mgr: any, t: string) => {
            try {
              if (typeof mgr.register_target === 'function') {
                mgr.register_target(t, (commOp: any, msg: any) =>
                  attachHandler(commOp, msg, t)
                );
                dbg('commManager.register_target succeeded for', t);
                return true;
              }
              if (typeof mgr.registerTarget === 'function') {
                mgr.registerTarget(t, (commOp: any, msg: any) =>
                  attachHandler(commOp, msg, t)
                );
                dbg('commManager.registerTarget succeeded for', t);
                return true;
              }
              if (typeof mgr.register === 'function') {
                mgr.register(t, (commOp: any, msg: any) =>
                  attachHandler(commOp, msg, t)
                );
                dbg('commManager.register succeeded for', t);
                return true;
              }
              dbg('commManager has no known register API for target', t);
              return false;
            } catch (e) {
              dbg('Failed to register target on commManager', t, e);
              return false;
            }
          };

          const targetsToRegister = [props.commTarget || 'ggblab-comm', 'jupyter.widget', 'jupyter.widget.control'];
          for (const t of targetsToRegister) {
            tryRegister(commManager, t);
          }

          // Publish the adopted manager to a global store so other mounts
          // can adopt the same manager if they mount later.
          try {
            (window as any).__ggblab_widget_manager = (window as any).__ggblab_widget_manager || {};
            const key = props?.kernelId || ((kernelConn as any)?.id) || 'last';
            (window as any).__ggblab_widget_manager[key] = mgr;
            (window as any).__ggblab_widget_manager['last'] = mgr;
            try {
              window.dispatchEvent(new CustomEvent('ggblab:widget-manager-registered'));
              dbg('Dispatched ggblab:widget-manager-registered');
            } catch (ee) {
              dbg('Failed to dispatch ggblab:widget-manager-registered', ee);
            }
          } catch (ee) {
            dbg('Failed to publish widget manager to global store', ee);
          }

          // Attempt to remove kernelConn passthrough targets if possible
          try {
            if (kernelConn && (kernelConn as any).removeCommTarget) {
              registeredKernelTargets.forEach(t => {
                try {
                  (kernelConn as any).removeCommTarget(t);
                  dbg('Removed kernelConn target', t);
                } catch (e) {
                  /* ignore */
                }
              });
            }
          } catch (e) {
            dbg('Error while removing kernelConn targets', e);
          }
        } catch (e) {
          dbg('adoptWidgetManager error', e);
        }
      };

      const onGlobalManager = () => {
        try {
          // If a specific comm target was provided by the kernel, do
          // not adopt a manager from the global store — the kernel
          // explicitly requested the comm target and we should avoid
          // overriding that decision.
          if (props?.commTarget) {
            dbg('props.commTarget present; skipping adoptWidgetManager');
            return;
          }
          const store = (window as any).__ggblab_widget_manager || {};
          if (props?.kernelId && store[props.kernelId]) {
            return adoptWidgetManager(store[props.kernelId]);
          }
          const keys = Object.keys(store || {});
          if (keys.length) {
            return adoptWidgetManager(store['last'] || store[keys[0]]);
          }
        } catch (e) {
          dbg('onGlobalManager error', e);
        }
      };
      window.addEventListener(
        'ggblab:widget-manager-registered',
        onGlobalManager as EventListener
      );

      // If a manager was already present at mount, adopt immediately
      try {
        if (effectiveWidgetManager) {
          adoptWidgetManager(effectiveWidgetManager);
        }
      } catch (e) {
        dbg('Immediate adopt failed', e);
      }

      async function ggbOnLoad(api: any) {
        dbg('GeoGebra applet loaded:', api);
        // expose applet API to other handlers (widgetComm etc.)
        appletApi = api;
        // "start" is unnecessary because the frontend emits an
        // explicit "oob_ready" when the applet loads; kernel-side
        // logic should treat that as the readiness/start signal.

        resizeHandler = function () {
          const wrapperDiv = document.getElementById(elementId);
          const parentDiv = wrapperDiv?.parentElement;
          const width = parseInt(parentDiv?.style.width || '800');
          const height = parseInt(parentDiv?.style.height || '600');
          api.recalculateEnvironments();
          api.setSize(width, height);
        };
        window.addEventListener('resize', resizeHandler);
        resizeHandler();

        // Create kernel-side Comm now that the applet is initialized.
        // Use the shared helper `ensureKernelComm()` so we reuse the
        // same creation / attach logic (and avoid duplicating open/handler setup).
        if (props.commTarget) {
          try {
            // Request the main kernel to register the requested comm target
            // into a persistent instance so the kernel will accept the
            // frontend's `createComm` open. Use a module-level
            // `ggb_comm_instance` to keep the instance alive.
            try {
              const regCode = `from ggblab.comm import ggb_comm\nif 'ggb_comm_instance' not in globals():\n    ggb_comm_instance = ggb_comm()\nggb_comm_instance.register_target("${props.commTarget}")\n`;
              await kernelConn.requestExecute({ code: regCode }).done;
            } catch (e) {
              dbg('Failed to request kernel to register comm target', e);
            }

            const maybeComm = await ensureKernelComm();
            if (maybeComm) {
              comm = maybeComm;
              try {
                const maybeId =
                  (comm as any)?.comm_id ||
                  (comm as any)?.commId ||
                  (comm as any)?.id ||
                  null;
                dbg('Created kernel comm via ensureKernelComm', {
                  target: props.commTarget,
                  commObject: comm,
                  commId: maybeId
                });
              } catch (e) {
                dbg(
                  'Created kernel comm via ensureKernelComm (unable to read id)',
                  props.commTarget,
                  comm
                );
              }
            } else {
              comm = null;
              dbg(
                'ensureKernelComm returned null; skipping kernel comm creation'
              );
            }
          } catch (e) {
            comm = null;
            dbg('ensureKernelComm failed; skipping kernel comm creation', e);
          }
        } else {
          comm = null;
          dbg('No commTarget provided; skipping kernel comm creation');
        }

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

        // Defer kernel-side Comm creation until the applet is loaded.
        // The comm will be created inside `ggbOnLoad` to ensure the
        // applet exists before we attempt to wire kernel↔frontend comms.
        // comm.send('HELO2').done

        // kernel.registerCommTarget('test', (comm, commMsg) => {
        // console.log("Comm opened from kernel with message:", commMsg['content']['data']);

        closeHandler = () => {
          // Attempt to close comm and shutdown helper kernel
          try {
            comm?.close?.();
          } catch (e) {
            console.error(e);
          }
          kernel2?.shutdown().catch((err: any) => console.error(err));
          dbg('Kernel and comm closed.');
          if (resizeHandler) {
            window.removeEventListener('resize', resizeHandler);
          }
        };
        window.addEventListener('close', closeHandler);
        if (comm) {
          try {
            comm.onMsg = handleIncomingCommMessage;
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
          if (widgetComm) {
            try {
              widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
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
          if (widgetComm) {
            try {
              widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
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
          if (widgetComm) {
            try {
              widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
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
          if (widgetComm) {
            try {
              widgetComm.send(s);
              return;
            } catch (e) {
              dbg('widgetComm.send failed, falling back', e);
            }
          }
          await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
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

        observer = new MutationObserver(mutations => {
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
                        await callRemoteSocketSend(
                          kernel2,
                          msg,
                          socketPath,
                          wsUrl
                        );
                      });
                  });
              } catch (e) {
                // console.log(e, node);
              }
            });
          });
        });
        observer.observe(document.body, { childList: true, subtree: true });
      }

      // Avoid duplicate meta/script inserts: reuse if already present
      const existingMeta = document.getElementById(
        'ggblab-viewport-meta'
      ) as HTMLMetaElement | null;
      if (existingMeta) {
        metaViewport = existingMeta;
      } else {
        metaViewport = document.createElement('meta');
        metaViewport.id = 'ggblab-viewport-meta';
        metaViewport.name = 'viewport';
        metaViewport.content = 'width=device-width, initial-scale=1';
        document.head.appendChild(metaViewport);
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
        try {
          (window as any).ggbApplet = applet;
        } catch (e) {
          /* ignore */
        }
      };

      if (existingScript) {
        scriptTag = existingScript;
        // If script already loaded and GGBApplet is available, instantiate immediately
        if ((window as any).GGBApplet) {
          createApplet();
        } else {
          // Otherwise ensure we call createApplet once it loads
          scriptTag.addEventListener('load', createApplet, { once: true });
        }
      } else {
        scriptTag = document.createElement('script');
        scriptTag.id = 'ggblab-deployggb-script';
        scriptTag.src = 'https://cdn.geogebra.org/apps/deployggb.js';
        scriptTag.async = true;
        scriptTag.onload = createApplet;
        document.body.appendChild(scriptTag);
      }
    });

    return () => {
      // Remove resize listener
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler);
        resizeHandler = null;
      }
      // Remove close listener
      if (closeHandler) {
        window.removeEventListener('close', closeHandler);
        closeHandler = null;
      }
      // Disconnect mutation observer
      if (observer) {
        try {
          observer.disconnect();
        } catch (e) {
          console.error(e);
        }
        observer = null;
      }
      // Remove injected meta tag
      if (metaViewport && metaViewport.parentNode) {
        metaViewport.parentNode.removeChild(metaViewport);
        metaViewport = null;
      }
      // Remove injected script tag
      if (scriptTag && scriptTag.parentNode) {
        scriptTag.parentNode.removeChild(scriptTag);
        scriptTag = null;
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
        try {
          delete (window as any).ggbApplet;
        } catch (e) {
          console.debug('ggblab: ignored', e);
        }
      }

      // Close comm and shutdown helper kernel asynchronously
      (async () => {
        try {
          if (comm) {
            try {
              comm.close?.();
            } catch (e) {
              dbg('Error closing comm during cleanup', e);
            }
            comm = null;
          }
          if (kernel2) {
            await kernel2.shutdown();
            kernel2 = null;
          }
          // Clear any widget comm bridge reference
          try {
            widgetComm = null;
          } catch (e) {
            /* ignore */
          }
          try {
            appletApi = null;
          } catch (e) {
            /* ignore */
          }
          if (kernelManager) {
            try {
              await kernelManager.shutdown?.();
            } catch (e) {
              /* ignore */
            }
            kernelManager = null;
          }
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
  widgetManager?: any;
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
    this.props = props || {};
    // Ensure a sensible default comm target so frontend and kernel
    // consistently use the same channel when callers omit it.
    this.props.commTarget = this.props.commTarget || 'ggblab-comm';
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
