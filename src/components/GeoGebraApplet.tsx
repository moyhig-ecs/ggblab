// comm helper functions inlined from kernel_comm.ts to reduce indirection
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import setupKernelResources from './jupyterlab';
import { registerWidgetCommTargets } from '../widgets';
import { DockLayout } from '@lumino/widgets';
import type { WidgetManagerType } from '../widgets';
// widgetManager registration is handled inside `setupKernelResources`
import type { IGeoGebraAppletApi, IGeoGebraResources } from '../types';
import { injectGeoGebraApplet } from '../shared/createApplet';
import { isArrayOfArrays, createProcessCommandMessage } from '../shared/geoGebraCommon';
import setupAppletOnLoadCommon from '../shared/appletOnLoadCommon';

// Global typings are provided in src/declarations.d.ts; avoid duplicate declarations here.

// Debug logging helper controlled from the browser console.
// Enable message logging in the JS console by running:
//   window.ggblabDebugMessages = true
function dbg(...args: any) {
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
const GeoGebraApplet = (props: IGeoGebraAppletProps): JSX.Element => {
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
		class Resources implements IGeoGebraResources {
			kernelId: string;
			commTarget: string;
			socketPath: string | null;
			wsPort: number;
			kernel2: any = null;
			kernelManager: any = null;
			kernelConn: any = null;
			comm: any = null;
			widgetComm: any = null;
			appletApi: IGeoGebraAppletApi | null = null;
			appletStyleObserver: MutationObserver | null = null;
			// unregister function returned by `registerWidgetCommTargets`
			unregisterWidgetCommTargets: (() => void) | null = null;
			// cleanup function returned by injectGeoGebraApplet
			injectCleanup: (() => void) | null = null;
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

					if (this.appletStyleObserver) {
						try {
							this.appletStyleObserver.disconnect();
						} catch (err) {
							dbg('Error disconnecting appletStyleObserver', err);
						}
						this.appletStyleObserver = null;
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
						// call injector cleanup if present
						try {
							this.injectCleanup?.();
						} catch (err) {
							dbg('Error during inject cleanup', err);
						}
						this.injectCleanup = null;
					} catch (err) {
						dbg('Error unregistering widget comm targets', err);
					}
				} catch (err) {
					console.error('Error during resources.dispose():', err);
				}
			}
		}

		const resources: IGeoGebraResources = new Resources(props.kernelId || '', props.commTarget || '', props.socketPath || null, props.wsPort || 8888);

		// Quick debug probe: confirm the IIFE below is entered at runtime.
		dbg(
			'useEffect: created Resources, about to run setup IIFE',
			{
				kernelId: props.kernelId,
				commTarget: props.commTarget
			},
			[]
		);

		(async () => {
			dbg('IIFE: entered - calling setupKernelResources');
			const { callRemoteSocketSend, makeIncomingHandler } = await setupKernelResources(resources, props, dbg);

			// Kernel comm lifecycle is managed inside kernel_comm helpers

			// Process a parsed command and return the reply message string.
			// This function lives in the same `useEffect` scope so it can be
			// called from multiple places (including outside
			// `handleIncomingCommMessage`). It captures `appletApi` and other
			// surrounding variables as needed.
			const processCommandMessage = createProcessCommandMessage(resources, callRemoteSocketSend, isArrayOfArrays, dbg);

			// Handler for incoming messages on the kernel-created comm; defined
			// via kernel_comm helper so it can reuse the shared logic.
			const handleIncomingCommMessage = makeIncomingHandler(processCommandMessage);

			/*
			  Widget comm passthrough fallback
			  -------------------------------
			  Reason: In some host environments (non-JupyterLab pages, timing differences,
			  or when the optional ipywidgets bridge isn't available), the centralized
			  `register_widget_manager_plugin` may not be able to detect or register a
			  frontend `WidgetManager` early enough for the GeoGebra applet to handle
			  incoming widget-related comms. To avoid breaking ipywidgets (which expect
			  the `jupyter.widget` comm target to be handled), we provide a lightweight
			  passthrough here as a guarded fallback.
			
			  How this relates to `register_widget_manager_plugin`:
			  - `register_widget_manager_plugin` (exported from `src/register_widget_manager_plugin.ts`
			    and exposed in `src/index.ts`) is the preferred mechanism: it runs
			    during JupyterLab activation and attempts to detect the real
			    ipywidgets manager and call `setWidgetManager(...)` so the applet can
			    delegate message routing to the manager.
			  - However, that plugin may be unavailable (optional dependency), run
			    later, or be ineffective in non-Lab contexts. This inline fallback
			    ensures correct behavior in those cases while remaining no-op when a
			    real manager is present (`props.widgetManager` guard).
			*/
			try {
				if (props.widgetManager) {
					dbg('widgetManager present; skipping raw jupyter.widget comm registration to avoid stealing widget opens');
				} else {
					const opts = {
						callRemoteSocketSend,
						kernel2: resources.kernel2,
						socketPath: resources.socketPath,
						wsUrl: `ws://localhost:${resources.wsPort}/`,
						getAppletApi: () => resources.appletApi,
						isArrayOfArrays: isArrayOfArrays,
						dbg
					};

					const unregisterFn = registerWidgetCommTargets(resources.kernelConn, opts as any);
					resources.unregisterWidgetCommTargets = unregisterFn;
				}
			} catch (e: any) {
				dbg('Widget comm target registration skipped or failed', e);
			}

			async function ggbOnLoad(api: any) {
				dbg('GeoGebra applet loaded:', api);
				// Run shared common setup and wiring for ggbOnLoad
				try {
					await setupAppletOnLoadCommon(api, resources, callRemoteSocketSend, handleIncomingCommMessage, dbg);
				} catch (e) {
					dbg('setupAppletOnLoadCommon failed', e);
				}

				// Environment-specific resize handler (JupyterLab/Lumino)
				resources.resizeHandler = function () {
					try {
						const wrapperDiv = document.getElementById(elementId) as HTMLElement | null;
						const target = wrapperDiv?.parentElement ?? wrapperDiv;
						if (!target) {
							return;
						}
						// Prefer measured size over style strings
						const rect = target.getBoundingClientRect();
						const width = Math.max(1, Math.floor(rect.width));
						const height = Math.max(1, Math.floor(rect.height));
						try {
							api.recalculateEnvironments();
						} catch (e) {
							dbg('recalculateEnvironments failed', e);
						}
						try {
							api.setSize(width, height);
						} catch (e) {
							dbg('setSize failed', e);
						}
					} catch (e) {
						dbg('resizeHandler error', e);
					}
				};
				window.addEventListener('resize', resources.resizeHandler);
				resources.resizeHandler();
			}

			// Use shared injector to create the GeoGebra applet and manage
			// the script/meta insertion. This centralizes logic so the same
			// behavior can be reused by the vscode-extension React widget.
			try {
				// Measure container so applet is created at the current panel size
				const wrapperDiv = widgetRef.current ?? document.getElementById(elementId);
				const targetForSize = (wrapperDiv as HTMLElement | null)?.parentElement ?? (wrapperDiv as HTMLElement | null);
				let measuredWidth = 800;
				let measuredHeight = 600;
				try {
					if (targetForSize) {
						const rect = (targetForSize as HTMLElement).getBoundingClientRect();
						measuredWidth = Math.max(1, Math.floor(rect.width));
						measuredHeight = Math.max(1, Math.floor(rect.height));
					}
				} catch (e) {
					dbg('Failed to measure container for initial size, falling back to defaults', e);
				}

				const { appletPromise, scriptTag, metaViewport, cleanup } = injectGeoGebraApplet({
					elementId,
					appName: props?.appName || 'suite',
					width: measuredWidth,
					height: measuredHeight,
					// disable container-scaling so the applet uses exact measured size
					scaleContainerClass: undefined,
					// Allow the applet to upscale when the panel grows
					allowUpscale: true,
					appletOnLoad: ggbOnLoad,
					dbg
				});
				resources.scriptTag = scriptTag;
				resources.metaViewport = metaViewport;
				resources.injectCleanup = cleanup || null;

				// capture the created applet instance for later cleanup and
				// apply measured sizing. Reapply size after short delays to
				// override any internal resets performed by the runtime.
				appletPromise
					.then((a: any) => {
						applet = a;
						try {
							const api = a;
							// measure current container again for accuracy
							const wrapperDiv2 = widgetRef.current ?? document.getElementById(elementId);
							const target2 = wrapperDiv2?.parentElement ?? wrapperDiv2;
							let w = measuredWidth;
							let h = measuredHeight;
							try {
								if (target2) {
									const rect2 = (target2 as HTMLElement).getBoundingClientRect();
									w = Math.max(1, Math.floor(rect2.width));
									h = Math.max(1, Math.floor(rect2.height));
								}
							} catch (e) {
								dbg('Failed to re-measure container for sizing', e);
							}
							try {
								api.recalculateEnvironments?.();
							} catch (e) {
								dbg('recalculateEnvironments failed', e);
							}
							try {
								api.setSize(w, h);
								dbg('Applied initial applet size', w, h);
							} catch (e) {
								dbg('api.setSize failed', e);
							}
							// Force applet DOM to use exact width/height and remove any
							// transform-based scaling that preserves initial aspect ratio.
							try {
								const appletNode = document.getElementById('ggbApplet-' + elementId);
								if (appletNode) {
									(appletNode as HTMLElement).style.width = '100%';
									(appletNode as HTMLElement).style.height = '100%';
									(appletNode as HTMLElement).style.maxWidth = '100%';
									(appletNode as HTMLElement).style.transform = 'none';
									(appletNode as HTMLElement).style.transformOrigin = '0 0';
								}
							} catch (e) {
								dbg('Failed to override applet DOM styles', e);
							}
							// reapply after short delays to outlast internal resets
							setTimeout(() => {
								try {
									api.setSize(w, h);
									dbg('Reapplied size (250ms)');
								} catch (e) {
									dbg('reapply failed', e);
								}
							}, 250);
							setTimeout(() => {
								try {
									api.setSize(w, h);
									dbg('Reapplied size (1000ms)');
								} catch (e) {
									dbg('reapply failed', e);
								}
							}, 1000);

							// Observe the applet node for style/attribute changes and
							// reapply our desired styles immediately when the runtime
							// attempts to change them.
							try {
								const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null;
								if (appletNode) {
									const observer = new MutationObserver(mutations => {
										try {
											// On any attribute change, enforce styles & size
											const rect3 = (appletNode.parentElement ?? appletNode).getBoundingClientRect();
											const ww = Math.max(1, Math.floor(rect3.width));
											const hh = Math.max(1, Math.floor(rect3.height));
											try {
												api.setSize(ww, hh);
											} catch (e) {
												/* ignore */
											}
											try {
												appletNode.style.transform = 'none';
												appletNode.style.width = '100%';
												appletNode.style.height = '100%';
											} catch (e) {
												/* ignore */
											}
										} catch (e) {
											dbg('appletStyleObserver handler error', e);
										}
									});
									observer.observe(appletNode, { attributes: true, attributeFilter: ['style', 'class'], subtree: false });
									resources.appletStyleObserver = observer;
								}
							} catch (e) {
								dbg('Failed to create appletStyleObserver', e);
							}
						} catch (e) {
							dbg('Error applying size to applet', e);
						}
					})
					.catch((e: any) => dbg('Applet creation failed', e));
			} catch (e) {
				dbg('injectGeoGebraApplet failed', e);
			}
		})();

		return () => {
			// Remove resize listener
			if (resources.resizeHandler) {
				window.removeEventListener('resize', resources.resizeHandler);
				resources.resizeHandler = null;
			}
			// Remove close listener
			if (resources.closeHandler) {
				window.removeEventListener('close', resources.closeHandler);
				resources.closeHandler = null;
			}
			// Disconnect mutation observer
			if (resources.observer) {
				try {
					resources.observer.disconnect();
				} catch (e) {
					console.error(e);
				}
				resources.observer = null;
			}
			// Unregister widget comm handlers if we registered them
			try {
				resources.unregisterWidgetCommTargets?.();
				resources.unregisterWidgetCommTargets = null;
			} catch (e) {
				dbg('Error unregistering widget comm targets', e);
			}
			// Remove injected meta tag
			if (resources.metaViewport && resources.metaViewport.parentNode) {
				resources.metaViewport.parentNode.removeChild(resources.metaViewport);
				resources.metaViewport = null;
			}
			// Remove injected script tag
			if (resources.scriptTag && resources.scriptTag.parentNode) {
				resources.scriptTag.parentNode.removeChild(resources.scriptTag);
				resources.scriptTag = null;
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
					await resources.dispose();
				} catch (e) {
					console.error('Error during cleanup:', e);
				}
			})();
		};
	}, []);

	return <div id={elementId} ref={widgetRef} style={{ width: '100%', height: '100%' }}></div>;
};

export interface IGeoGebraAppletProps {
	kernelId?: string;
	commTarget?: string;
	insertMode?: DockLayout.InsertMode;
	wsPort?: number;
	socketPath?: string;
	appName?: string;
	// Optional WidgetManager module or instance provided by the plugin activation
	widgetManager?: WidgetManagerType;
}

/**
 * A GeoGebra Lumino Widget that wraps a GeoGebraComponent.
 */
// Lumino-specific `GeoGebraWidget` has been moved to `lumino.tsx`.

// // Example of attaching the GeoGebraWidget to a DockPanel
// // but commented out to avoid automatic execution.
// const dock = new DockPanel();
// ReactWidget.attach(dock, document.body);
// // window.addEventListener('resize', () => { dock.update(); });
// dock.layoutModified.connect(() => {
//     console.log("Dock layout modified.");
//     dock.update();
// });

export default GeoGebraApplet;
