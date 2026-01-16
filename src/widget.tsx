import { ReactWidget } from '@jupyterlab/ui-components';
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';
import { DockLayout } from '@lumino/widgets';
//import { Message } from '@lumino/messaging';

/**
 * React component for a GeoGebra.
 *
 * @returns The React component
 */
const GGAComponent = (props: GGAWidgetProps): JSX.Element => {
 // const [kernels, setKernels] = React.useState<any[]>([]);
    const widgetRef = useRef<HTMLDivElement>(null);
 // const [size, setSize] = useState<{width: number; height: number}>({width: 800, height: 600});

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

    console.log(props.kernelId, props.commTarget, props.socketPath, props.wsPort);

    var applet: any = null;

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
    async function callRemoteSocketSend(
        kernel2: any,
        message: string,
        socketPath: string | null,
        wsUrl: string
    ): Promise<void> {
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
    }

    useEffect(() => {
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

            const kernelManager = new KernelManager({ serverSettings: settings });
            const kernel2 = await kernelManager.startNew({ name: 'python3' });
            console.log("Started new kernel:", kernel2, props.kernelId);
            await kernel2.requestExecute({ code: `from websockets.sync.client import unix_connect, connect` }).done;

            const wsUrl = `ws://localhost:${props.wsPort}/`;
            const socketPath = props.socketPath || null;

            const kernel = new KernelConnection({
                model: { name: 'python3', id: props.kernelId || kernels[0]['id']},
                serverSettings: settings,
            });
            console.log("Connected to kernel:", kernel);

            async function ggbOnLoad(api: any) {
                console.log("GeoGebra applet loaded:", api);

                var resize = function() {
                    const wrapperDiv = document.getElementById('ggb-element');
                    const parentDiv = wrapperDiv?.parentElement
                    const width  = parseInt(parentDiv?.style.width || "800");
                    const height = parseInt(parentDiv?.style.height || "600");
                 // console.log("Window resized:", width, height);
                    api.recalculateEnvironments()
                    api.setSize(width, height);
                }
                window.addEventListener('resize', resize);
                resize();

                const comm = kernel.createComm(props.commTarget || 'test');
                comm.open('HELO from GGB').done;
             // comm.send('HELO2').done

             // kernel.registerCommTarget('test', (comm, commMsg) => {
             // console.log("Comm opened from kernel with message:", commMsg['content']['data']);
                        
                addEventListener('close', () => {
                 // comm.close().done;
                 // kernel.shutdown().catch(err => console.error(err));
                    kernel2.shutdown().catch(err => console.error(err));
                    console.log("Kernel and comm closed.");
                    window.removeEventListener('resize', resize);
                });

                comm.onMsg = async (msg) => {
                    console.log("Message received from server:", msg['content']['data']);

                    const command = JSON.parse(msg.content.data as any);
                    console.log("Parsed command:", command.type, command.payload);
                    
                    var rmsg: any = null;
                    if (command.type === "command") {
                        var label = api.evalCommandGetLabels(command.payload); // GeoGebraにコマンドを適用
                        
                        rmsg = JSON.stringify({
                            "type": "created",
                            "id": command.id,                  
                            "payload": label
                        }); // .replace(/'/g, "\\'");
                    } else if (command.type === "function") {
                        var apiName = command.payload.name;
                        console.log(apiName);
                        var value: any[] = [];
                        // if (command.payload.args == null) {
                        //     value = api[apiName]();
                        // } else 
                        {
                            var args = command.payload.args;
                            value = [];
                            (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
                                console.log(f, args);
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
                            console.log("Function value:", value);
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

                // var clientListener = function(data: any) {
                //  // console.log("Add listener triggered for:", data);
                //     var msg = {
                //         "type": "add",
                //         "payload": data,
                //     }
                //     console.log("Add detected:", JSON.stringify(msg));
                //     comm.send(JSON.stringify(msg));
                // }
                // api.registerClientListener(clientListener);

                var addListener = async function(data: any) {
                 // console.log("Add listener triggered for:", data);
                    var msg = {
                        "type": "add",
                        "payload": data, // {
                            // "label": data, 
                            // "details": {
                            //     "type": api.getObjectType(data),
                            //     "commandString": api.getCommandString(data, false),
                            //     "visible": api.getVisible(data),
                            //     "layer": api.getLayer(data),
                            // }
                        // }
                    }
                    // console.log("Add detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerAddListener(addListener);

                var removeListener = async function(data: any) {
                 // console.log("Add listener triggered for:", data);
                    var msg = {
                        "type": "remove",
                        "payload": data,
                    }
                    // console.log("Remove detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerRemoveListener(removeListener);

                var renameListener = async function(data: any) {
                 // console.log("Add listener triggered for:", data);
                    var msg = {
                        "type": "rename",
                        "payload": data,
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerRenameListener(renameListener);

                var clearListener = async function(data: any) {
                // console.log("Add listener triggered for:", data);
                    var msg = {
                        "type": "clear",
                        "payload": data
                    }
                    // console.log("Rename detected:", JSON.stringify(msg));
                    await callRemoteSocketSend(kernel2, JSON.stringify(msg), socketPath, wsUrl);
                }
                api.registerClearListener(clearListener);

                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        mutation.addedNodes.forEach((node) => {
                            try {
                                (node as HTMLElement).querySelectorAll('div.dialogMainPanel > div.dialogTitle').forEach((n) => {
                                 // console.log(n.textContent); 'Error'などのタイトルを検出
                                    ((node as HTMLElement).querySelector('div.dialogContent') as HTMLElement)
                                        .querySelectorAll(`[class$='Label']`).forEach(async (n2) => {
                                            // console.log(n2.textContent);
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

            const metaViewport = document.createElement('meta');
            metaViewport.name = "viewport";
            metaViewport.content = "width=device-width, initial-scale=1";
            document.head.appendChild(metaViewport);

            const scriptTag = document.createElement('script');
            scriptTag.src = 'https://cdn.geogebra.org/apps/deployggb.js';
            scriptTag.async = true;
            scriptTag.onload = () => {
                const params = {
                    id: "ggbApplet", // アプレットのID
                    appName: "suite", // GeoGebra Classicスマートアプレットを指定
                    width: 800, // アプレットの横幅
                    height: 600, // アプレットの高さ
                    showToolBar: true, // ツールバーを表示
                    showAlgebraInput: false, // 入力フィールドを表示
                    showMenuBar: true, // メニューバーを表示
                    autoHeight: true,
                 // autoWidth: false,
                 // scale: 2,
                    allowUpscale: false,
                    appletOnLoad: ggbOnLoad
                }
                applet = new (window as any).GGBApplet(params, true);
                applet.inject("ggb-element");
            }
            document.body.appendChild(scriptTag);
        });

        return () => {
         // コンポーネントのアンマウント時にスクリプトとアプレットをクリーンアップ
         // document.head.removeChild(scriptTag);
            if (applet) {
                console.log("Cleaning up GeoGebra applet.");
             // delete (window as any).applet;
                (window as any).ggbApplet.remove();
                applet = null;
                delete (window as any).GGBApplet;
            }
        };
    }, []);

    return (
        <div id="ggb-element" ref={widgetRef} style={{width: "100%", height: "100%"}}></div>
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
 // private kernelId: string;
 // private commTarget: string;
 // private socketPath: string;
    private props: GGAWidgetProps | undefined;

    /**
     * Constructs a new GeoGebraWidget.
     */
    constructor(props?: GGAWidgetProps) {
        super();
        this.addClass('jp-ggblabWidget');
        this.props = props;
     // this.kernelId = props?.kernelId || '';
     // this.commTarget = props?.commTarget || '';
     // this.wsPort = props?.wsPort || 0;
     // this.socketPath = props?.socketPath || '';
    }

    render(): JSX.Element {
        return <GGAComponent kernelId={this.props?.kernelId} commTarget={this.props?.commTarget} wsPort={this.props?.wsPort} socketPath={this.props?.socketPath} />;
    }

//   protected onCloseRequest(msg: Message): void {
//     console.log("GeoGebraWidget is being closed.");
//     super.onCloseRequest(msg);
//     // this.dispose();
//   }

    dispose(): void {
        console.log("GeoGebraWidget is being disposed.");
        window.dispatchEvent(new Event('close'));
     // delete(window.ggbApplet);
        super.dispose();
    }
}
