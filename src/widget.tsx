/* eslint-disable */
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

    console.log("Component props: ", props.kernelId, props.commTarget, props.socketPath, props.wsPort);
    // window.dispatchEvent(new Event('resize'));

    const elementId = "ggb-element-" + (props?.kernelId || '').substring(0, 8);
    console.log("Element ID:", elementId);

    let applet: any = null;

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
        let observer: MutationObserver | null = null;
        let resizeHandler: (() => void) | null = null;
        let closeHandler: (() => void) | null = null;
        let metaViewport: HTMLMetaElement | null = null;
        let scriptTag: HTMLScriptElement | null = null;

        (async () => {
            return await KernelAPI.listRunning();
        })().then(async (kernels) => {
         // setKernels(kernels);
            console.log("Running kernels:", kernels);

            const baseUrl = PageConfig.getBaseUrl();
            const token   = PageConfig.getToken();
            console.log(`Base URL: ${baseUrl}`);
            console.log(`Token: ${token}`);
            const settings = ServerConnection.makeSettings({
                baseUrl: baseUrl, //'http://localhost:8889/',
                token: token,     //'7e89be30eb93ee7c149a839d4c7577e08c2c25b3c7f14647',
                appendToken: true,
            });

            kernelManager = new KernelManager({ serverSettings: settings });
            kernel2 = await kernelManager.startNew({ name: 'python3' });
            console.log("Started new kernel:", kernel2, props.kernelId);
            await kernel2.requestExecute({ code: `from websockets.sync.client import unix_connect, connect` }).done;

            const wsUrl = `ws://localhost:${props.wsPort}/`;
            const socketPath = props.socketPath || null;

            kernelConn = new KernelConnection({
                model: { name: 'python3', id: props.kernelId || kernels[0]['id']},
                serverSettings: settings,
            });
            console.log("Connected to kernel:", kernelConn);

            async function ggbOnLoad(api: any) {
                console.log("GeoGebra applet loaded:", api);
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

                comm = kernelConn.createComm(props.commTarget || 'test');
                comm.open('HELO from GGB').done;
             // comm.send('HELO2').done

             // kernel.registerCommTarget('test', (comm, commMsg) => {
             // console.log("Comm opened from kernel with message:", commMsg['content']['data']);
                        
                closeHandler = () => {
                    // Attempt to close comm and shutdown helper kernel
                    try { comm?.close?.(); } catch (e) { console.error(e); }
                    kernel2?.shutdown().catch((err: any) => console.error(err));
                    console.log("Kernel and comm closed.");
                    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
                };
                window.addEventListener('close', closeHandler);

                comm.onMsg = async (msg: any) => {
                    dbg("Message received from server:", msg['content']['data']);

                    const command = JSON.parse(msg.content.data as any);
                    dbg("Parsed command:", command.type, command.payload);
                    
                    var rmsg: any = null;
                    if (command.type === "command") {
                        var label = api.evalCommandGetLabels(command.payload);
                        
                        rmsg = JSON.stringify({
                            "type": "created",
                            "id": command.id,                  
                            "payload": label
                        }); // .replace(/'/g, "\\'");
                    } else if (command.type === "function") {
                        var apiName = command.payload.name;
                        dbg("apiName:", apiName);
                        var value: any[] = [];

                        {
                            var args = command.payload.args;
                            value = [];
                                (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
                                dbg("call", f, args);
                                if (isArrayOfArrays(args)) {
                                    var value2: any[] = [];
                                    args.forEach((arg2: any[]) => {
                                        if (args) {
                                            value2.push(api[f](...arg2) || null);
                                        } else {
                                            value2.push(api[f]() || null);
                                        }
                                    });
                                    value.push(value2);
                                } else {
                                    if (args) {
                                        value.push(api[f](...args) || null);
                                    } else {
                                        value.push(api[f]() || null);
                                    }
                                }
                            });
                            value = (Array.isArray(apiName) ? value : value[0]);
                            dbg("Function value:", value);
                        }
                        rmsg = JSON.stringify({
                            "type": "value",
                            "id": command.id,
                            "payload": {
                                //"label": command.payload,
                                "value": value
                            }
                        }); // .replace(/'/g, "\\'");
                    }
                    comm.send(rmsg);
                    await callRemoteSocketSend(kernel2, rmsg, socketPath, wsUrl);
                }

                var addListener = async function(data: any) {
                 dbg("Add listener triggered for:", data);
                    var msg = {
                        "type": "add",
                        "payload": data, 
                    }
                    // console.log("Add detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerAddListener(addListener);

                var removeListener = async function(data: any) {
                 dbg("Remove listener triggered for:", data);
                    var msg = {
                        "type": "remove",
                        "payload": data,
                    }
                    // console.log("Remove detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerRemoveListener(removeListener);

                var renameListener = async function(data: any) {
                 dbg("Rename listener triggered for:", data);
                    var msg = {
                        "type": "rename",
                        "payload": data,
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerRenameListener(renameListener);

                var clearListener = async function(data: any) {
                dbg("Clear listener triggered for:", data);
                    var msg = {
                        "type": "clear",
                        "payload": data
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerClearListener(clearListener);

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
                    console.log("Cleaning up GeoGebra applet.");
                    (window as any).ggbApplet.remove();
                } catch (e) {
                    console.error(e);
                }
                applet = null;
                try { delete (window as any).GGBApplet; } catch {}
            }

            // Close comm and shutdown helper kernel asynchronously
            (async () => {
                try {
                    if (comm) {
                        try { comm.close?.(); } catch (e) { console.error(e); }
                        comm = null;
                    }
                    if (kernel2) {
                        await kernel2.shutdown();
                        kernel2 = null;
                    }
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
        this.props = props;
    }

    render(): JSX.Element {
        return <GGAComponent kernelId={this.props?.kernelId} commTarget={this.props?.commTarget} wsPort={this.props?.wsPort} socketPath={this.props?.socketPath} />;
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
        console.log('GeoGebraWidget onCloseRequest — performing cleanup.');
        window.dispatchEvent(new Event('close'));
        super.onCloseRequest(msg);
    }

    // dispose should not trigger cleanup again; allow normal disposal to proceed
    // without duplicating shutdown logic.
    dispose(): void {
        console.log('GeoGebraWidget disposed.');
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