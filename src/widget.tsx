import { ReactWidget } from '@jupyterlab/ui-components';
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
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
const GGAComponent = (props: GGAWidgetProps): JSX.Element => {
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
    dbg("Component props: ", kernelId, props.commTarget, props.socketPath, props.wsPort);

    const elementId = "ggb-element-" + kernelId.substring(0, 8);
    dbg("Element ID:", elementId);

    let applet: any = null;

    // Prefer a widget manager explicitly passed via props; otherwise try
    // to pick up a manager placed in the global store by integration code.
    const widgetManagerFromWindow = (window as any).__ggblab_widget_manager ? (window as any).__ggblab_widget_manager[kernelId] : undefined;
    const effectiveWidgetManager = (props as any).widgetManager || widgetManagerFromWindow;

    function isArrayOfArrays(value: any): boolean {
        return Array.isArray(value) && value.every(subArray => Array.isArray(subArray));
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
            dbg("callRemoteSocketSend: sending message", { socketPath, wsUrl, messagePreview: message.slice(0,200) });
            // Queue the actual send work on the chain so sends are serialized.
            const doSend = async () => {
                if (socketPath) {
                    await kernel2.requestExecute({ code: `
with unix_connect("${socketPath}") as ws:
    ws.send(r"""${message}""")
`
                    }).done;
                } else {
                    await kernel2.requestExecute({ code: `
with connect("${wsUrl}") as ws:
    ws.send(r"""${message}""")
`
                    }).done;
                }

                // small delay to give the helper kernel a moment to tear down
                // and to avoid immediate back-to-back requestExecute calls.
                await new Promise(resolve => setTimeout(resolve, 30));
            };

            // Append to chain and ensure errors don't break future sends.
            const next = sendChain.then(() => doSend());
            // swallow errors on chain so chain remains healthy
            sendChain = next.catch(() => { /* ignore errors to keep chain alive */ });
            await next;
            try { dbg("callRemoteSocketSend: sent", { idPreview: message.slice(0,40) }); } catch (e) { /* ignore */ }
        } catch (err) {
            try { console.error("callRemoteSocketSend: error sending message", err); } catch (e) { /* ignore */ }
            throw err;
        }
    }

    useEffect(() => {
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
        let appletApi: any = null;
        let observer: MutationObserver | null = null;
        let resizeHandler: (() => void) | null = null;
        let closeHandler: (() => void) | null = null;
        let metaViewport: HTMLMetaElement | null = null;
        let scriptTag: HTMLScriptElement | null = null;

        (async () => {
            return await KernelAPI.listRunning();
        })().then(async (kernels) => {
         // setKernels(kernels);
            dbg("Running kernels:", kernels);

            const baseUrl = PageConfig.getBaseUrl();
            const token   = PageConfig.getToken();
            dbg(`Base URL: ${baseUrl}`);
            dbg(`Token: ${token}`);
            const settings = ServerConnection.makeSettings({
                baseUrl: baseUrl, //'http://localhost:8889/',
                token: token,     //'7e89be30eb93ee7c149a839d4c7577e08c2c25b3c7f14647',
                appendToken: true,
            });

            kernelManager = new KernelManager({ serverSettings: settings });
            kernel2 = await kernelManager.startNew({ name: 'python3' });
            dbg("Started new kernel:", kernel2, kernelId);
            await kernel2.requestExecute({ code: `from websockets.sync.client import unix_connect, connect` }).done;

            const wsUrl = `ws://localhost:${props.wsPort}/`;
            const socketPath = props.socketPath || null;

            kernelConn = new KernelConnection({
                model: { name: 'python3', id: kernelId || kernels[0]['id']},
                serverSettings: settings,
            });
            dbg("Connected to kernel:", kernelConn);

            // Keep comm lifecycle state and helpers for recovery when comms close
            let commClosed = false;
            const attachCommCloseHandler = (c: any) => {
                try {
                    (c as any).onClose = (m: any) => {
                        try {
                            commClosed = true;
                            const closedId = (m && m.content && m.content.comm_id) || (c as any)?.comm_id || (c as any)?.commId || null;
                            dbg('Kernel comm closed', { target: props.commTarget, commId: closedId, message: m });
                        } catch (e) {
                            dbg('Kernel comm closed (no id available)', props.commTarget, m);
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
                        rmsg = JSON.stringify({ type: 'created', id: command.id, payload: label });
                    } else if (command.type === 'function') {
                        const apiName = command.payload.name;
                        const args = command.payload.args;
                        let value: any[] = [];
                        (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
                            if (isArrayOfArrays(args)) {
                                const v2: any[] = [];
                                args.forEach((a: any[]) => { v2.push(appletApi[f](...a) || null); });
                                value.push(v2);
                            } else {
                                value.push(args ? appletApi[f](...args) || null : appletApi[f]() || null);
                            }
                        });
                        value = Array.isArray(apiName) ? value : value[0];
                        rmsg = JSON.stringify({ type: 'value', id: command.id, payload: { value } });
                    }

                    if (!rmsg) return;

                    // Prefer replying on the source comm (widget-manager comm)
                    // if provided. Next prefer the kernel-created comm. Fallback
                    // to callRemoteSocketSend.
                    try {
                        if (sourceComm && typeof sourceComm.send === 'function') {
                            try { sourceComm.send(rmsg); dbg('Replied via sourceComm'); } catch (e) { dbg('sourceComm.send failed', e); throw e; }
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
                            try { comm.send(rmsg); dbg('Replied via kernel comm'); } catch (e) { dbg('kernel comm.send failed', e); throw e; }
                            return;
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
                if (comm && !commClosed) return comm;
                try {
                    // If an early frontend-side comm was registered (plugin activation)
                    // reuse it. This allows comm_open from the kernel to be accepted
                    // before the widget fully mounts.
                    try {
                        const store = (window as any).__ggblab_comm_store || {};
                        const pre = kernelId ? store[kernelId] : null;
                        if (pre) {
                            comm = pre;
                            try { comm.onMsg = handleIncomingCommMessage; } catch (e) { dbg('Failed to attach onMsg to pre-registered comm', e); }
                            attachCommCloseHandler(comm);
                            commClosed = false;
                            dbg('Using pre-registered frontend comm for kernel', kernelId);
                            return comm;
                        }
                    } catch (e) {
                        dbg('Error checking pre-registered comm store', e);
                    }
                    if (!kernelConn) {
                        throw new Error('No kernelConn available to create comm');
                    }
                    comm = kernelConn.createComm(props.commTarget);
                    try {
                        const maybeId = (comm as any)?.comm_id || (comm as any)?.commId || (comm as any)?.id || null;
                        dbg('Recreated kernel comm', { target: props.commTarget, commObject: comm, commId: maybeId });
                    } catch (e) {
                        dbg('Recreated kernel comm (unable to read id)', props.commTarget, comm);
                    }
                    // attach handlers
                    try { comm.onMsg = handleIncomingCommMessage; } catch (e) { dbg('Failed to attach onMsg to recreated comm', e); }
                    attachCommCloseHandler(comm);
                    // open the comm
                    try { comm.open('REOPEN from GGB').done; } catch (e) { dbg('Failed to open recreated comm', e); }
                    commClosed = false;
                    return comm;
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
                if (effectiveWidgetManager) {
                    dbg('widgetManager present; installing manager-based comm adapter');
                    try {
                        const mgr: any = effectiveWidgetManager;
                        // Heuristics to find the underlying comm manager
                        const commManager = mgr.comm_manager || mgr.commManager || mgr._commManager || mgr._manager?.comm_manager || mgr._kernel?.comm_manager || null;
                        if (commManager && typeof commManager.register_target === 'function') {
                            const target = props.commTarget || 'ggblab-comm';

                            const attachHandler = (commOp: any, msg: any, sourceName: string) => {
                                dbg('manager adapter: comm opened', sourceName, commOp, msg);
                                try {
                                    widgetComm = commOp;
                                    // Attach a message handler in a defensive way; different
                                    // comm implementations use different callback names.
                                    const handler = async (m: any) => {
                                        const data = m?.content?.data || m;
                                        const command = typeof data === 'string' ? JSON.parse(data) : data;
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
                                            // sometimes on_msg is an attribute to assign
                                            // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                                            // @ts-ignore
                                            commOp.on_msg = handler;
                                        } else {
                                            try { commOp.onMsg = handler; } catch (e) { dbg('Unable to attach handler to commOp', e); }
                                        }
                                    } catch (e) {
                                        dbg('Failed to attach message handler to manager-provided comm', e);
                                    }
                                } catch (e) {
                                    dbg('Error in manager adapter comm handler', e);
                                }
                            };

                            // Register our ggblab target
                            commManager.register_target(target, (commOp: any, msg: any) => attachHandler(commOp, msg, target));
                            dbg('Registered manager-based comm adapter for target', target);

                            // Also register standard ipywidgets targets so we can reuse
                            // ipywidgets-created comms and route them into our command
                            // processing. This allows existing widget code to open a
                            // comm and have messages handled by ggblab.
                            try {
                                commManager.register_target('jupyter.widget', (commOp: any, msg: any) => attachHandler(commOp, msg, 'jupyter.widget'));
                                commManager.register_target('jupyter.widget.control', (commOp: any, msg: any) => attachHandler(commOp, msg, 'jupyter.widget.control'));
                                dbg('Registered manager-based adapters for jupyter.widget targets');
                            } catch (e) {
                                dbg('Failed to register jupyter.widget targets on commManager', e);
                            }
                        } else {
                            dbg('No comm manager found on widgetManager; falling back to kernelConn registration');
                            // Fall back to raw kernelConn registration
                            const simpleHandler = (commOp: any, msg: any) => {
                                dbg('widget comm opened (fallback jupyter.widget)', commOp, msg);
                                try {
                                    commOp.onMsg = async (m: any) => {
                                        const data = m?.content?.data || m;
                                        const command = typeof data === 'string' ? JSON.parse(data) : data;
                                        await processCommand(command, commOp);
                                    };
                                } catch (e) { dbg('Failed to attach onMsg to widget comm (fallback)', e); }
                            };
                            kernelConn.registerCommTarget('jupyter.widget', simpleHandler);
                            kernelConn.registerCommTarget('jupyter.widget.control', simpleHandler);
                        }
                    } catch (e) {
                        dbg('Error installing manager-based adapter', e);
                    }
                } else {
                    const simpleHandler = (commOp: any, msg: any) => {
                        dbg('widget comm opened (jupyter.widget)', commOp, msg);
                        try {
                            commOp.onMsg = async (m: any) => {
                                let content = m?.content?.data || m;
                                try {
                                    const command = typeof content === 'string' ? JSON.parse(content) : content;
                                    await processCommand(command, commOp);
                                } catch (e) {
                                    dbg('Error handling widget comm message', e);
                                }
                            };
                        } catch (e) {
                            dbg('Failed to attach onMsg to widget comm', e);
                        }
                    };

                    kernelConn.registerCommTarget('jupyter.widget', simpleHandler);
                    kernelConn.registerCommTarget('jupyter.widget.control', simpleHandler);
                }
            } catch (e) {
                dbg('Widget comm target registration skipped or failed', e);
            }

            async function ggbOnLoad(api: any) {
                dbg("GeoGebra applet loaded:", api);
                // expose applet API to other handlers (widgetComm etc.)
                appletApi = api;
                (async function () {
                    var msg = {
                        "type": "start",
                        "payload": {}
                    }
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                })();

                resizeHandler = function() {
                    const wrapperDiv = document.getElementById(elementId);
                    const parentDiv = wrapperDiv?.parentElement
                    const width  = parseInt(parentDiv?.style.width || "800");
                    const height = parseInt(parentDiv?.style.height || "600");
                    api.recalculateEnvironments()
                    api.setSize(width, height);
                }
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
                                const maybeId = (comm as any)?.comm_id || (comm as any)?.commId || (comm as any)?.id || null;
                                dbg('Created kernel comm via ensureKernelComm', { target: props.commTarget, commObject: comm, commId: maybeId });
                            } catch (e) {
                                dbg('Created kernel comm via ensureKernelComm (unable to read id)', props.commTarget, comm);
                            }
                        } else {
                            comm = null;
                            dbg('ensureKernelComm returned null; skipping kernel comm creation');
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
                    try { comm?.close?.(); } catch (e) { console.error(e); }
                    kernel2?.shutdown().catch((err: any) => console.error(err));
                    dbg("Kernel and comm closed.");
                    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
                };
                window.addEventListener('close', closeHandler);
                if (comm) {
                    try { comm.onMsg = handleIncomingCommMessage; } catch (e) { dbg('Failed to attach handleIncomingCommMessage to comm', e); }
                } else {
                    dbg('No kernel comm available; messages will be sent via remote socket only');
                }

                var addListener = async function(data: any) {
                 dbg("Add listener triggered for:", data);
                    var msg = {
                        "type": "add",
                        "payload": data, 
                    }
                    // console.log("Add detected:", JSON.stringify(msg));
                    // Prefer to send via widget comm bridge if available
                    const s = JSON.stringify(msg);
                    if (widgetComm) {
                        try { widgetComm.send(s); return; } catch (e) { dbg('widgetComm.send failed, falling back', e); }
                    }
                    await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
                }
                api.registerAddListener(addListener);

                var removeListener = async function(data: any) {
                 dbg("Remove listener triggered for:", data);
                    var msg = {
                        "type": "remove",
                        "payload": data,
                    }
                    // console.log("Remove detected:", JSON.stringify(msg));
                    const s = JSON.stringify(msg);
                    if (widgetComm) {
                        try { widgetComm.send(s); return; } catch (e) { dbg('widgetComm.send failed, falling back', e); }
                    }
                    await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
                }
                api.registerRemoveListener(removeListener);

                var renameListener = async function(data: any) {
                 dbg("Rename listener triggered for:", data);
                    var msg = {
                        "type": "rename",
                        "payload": data,
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    const s = JSON.stringify(msg);
                    if (widgetComm) {
                        try { widgetComm.send(s); return; } catch (e) { dbg('widgetComm.send failed, falling back', e); }
                    }
                    await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
                }
                api.registerRenameListener(renameListener);

                var clearListener = async function(data: any) {
                dbg("Clear listener triggered for:", data);
                    var msg = {
                        "type": "clear",
                        "payload": data
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    const s = JSON.stringify(msg);
                    if (widgetComm) {
                        try { widgetComm.send(s); return; } catch (e) { dbg('widgetComm.send failed, falling back', e); }
                    }
                    await callRemoteSocketSend(kernel2, s, socketPath, wsUrl);
                }
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

                observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        mutation.addedNodes.forEach((node) => {
                            try {
                                (node as HTMLElement).querySelectorAll('div.dialogMainPanel > div.dialogTitle').forEach((n) => {
                                    dbg(n.textContent); // detect titles like 'Error'
                                    ((node as HTMLElement).querySelector('div.dialogContent') as HTMLElement)
                                            .querySelectorAll(`[class$='Label']`).forEach(async (n2) => {
                                                dbg(n2.textContent);
                                            const msg = JSON.stringify({
                                                "type": n.textContent,
                                                "payload": n2.textContent
                                            });
                                            // comm.send(msg);
                                            await callRemoteSocketSend(kernel2, msg, socketPath, wsUrl);
                                        })
                                })
                            } catch (e) {
                             // console.log(e, node);
                            }
                        });
                    });
                });
                observer.observe(document.body, { childList: true, subtree: true });  
            }    

            // Avoid duplicate meta/script inserts: reuse if already present
            const existingMeta = document.getElementById('ggblab-viewport-meta') as HTMLMetaElement | null;
            if (existingMeta) {
                metaViewport = existingMeta;
            } else {
                metaViewport = document.createElement('meta');
                metaViewport.id = 'ggblab-viewport-meta';
                metaViewport.name = "viewport";
                metaViewport.content = "width=device-width, initial-scale=1";
                document.head.appendChild(metaViewport);
            }

            const existingScript = document.getElementById('ggblab-deployggb-script') as HTMLScriptElement | null;
            const createApplet = () => {
                const params = {
                    id: "ggbApplet" + (props?.kernelId || '').substring(0, 8), // applet ID
                    appName: "suite", // specify GeoGebra Classic smart applet
                    width: 800, // applet width
                    height: 600, // applet height
                    showToolBar: true, // show the toolbar
                    showAlgebraInput: false, // show algebra input field
                    showMenuBar: true, // show the menu bar
                    autoHeight: true,
                    scaleContainerClass: "lm-Panel", // "lm-DockPanel-widget",
                    // autoWidth: false,
                    // scale: 2,
                    allowUpscale: false,
                    appletOnLoad: ggbOnLoad
                }
                applet = new (window as any).GGBApplet(params, true);
                applet.inject(elementId);
                // Expose the active applet instance on `window.ggbApplet` for
                // consistency across the codebase and for debug tooling.
                try { (window as any).ggbApplet = applet; } catch (e) { /* ignore */ }
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
                try { observer.disconnect(); } catch (e) { console.error(e); }
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
                    dbg("Cleaning up GeoGebra applet.");
                    // Use the unified `window.ggbApplet` reference when available
                    const winApplet = (window as any).ggbApplet || applet;
                    try { winApplet.remove(); } catch (e) { dbg('Error removing applet instance', e); }
                } catch (e) {
                    dbg('Error while removing GeoGebra applet', e);
                }
                applet = null;
                try { delete (window as any).ggbApplet; } catch {}
            }

            // Close comm and shutdown helper kernel asynchronously
            (async () => {
                try {
                    if (comm) {
                        try { comm.close?.(); } catch (e) { dbg('Error closing comm during cleanup', e); }
                        comm = null;
                    }
                    if (kernel2) {
                        await kernel2.shutdown();
                        kernel2 = null;
                    }
                        // Clear any widget comm bridge reference
                        try { widgetComm = null; } catch (e) { /* ignore */ }
                        try { appletApi = null; } catch (e) { /* ignore */ }
                    if (kernelManager) {
                        try { await kernelManager.shutdown?.(); } catch (e) { /* ignore */ }
                        kernelManager = null;
                    }
                } catch (e) {
                    console.error('Error during cleanup:', e);
                }
            })();
        };
    }, []);

    return (
        <div id={elementId} ref={widgetRef} style={{width: "100%", height: "100%"}}></div>
    );
};

interface GGAWidgetProps {
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

    private props: GGAWidgetProps | undefined;

    /**
     * Constructs a new GeoGebraWidget.
     */
    constructor(props?: GGAWidgetProps) {
        super();
        this.addClass('jp-ggblabWidget');
        this.props = props || {};
        // Ensure a sensible default comm target so frontend and kernel
        // consistently use the same channel when callers omit it.
        this.props.commTarget = this.props.commTarget || 'ggblab-comm';
    }

    render(): JSX.Element {
        return <GGAComponent kernelId={this.props?.kernelId} commTarget={this.props?.commTarget} wsPort={this.props?.wsPort} socketPath={this.props?.socketPath} widgetManager={this.props?.widgetManager} />;
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