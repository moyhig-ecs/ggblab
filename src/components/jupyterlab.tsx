import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';
import { initKernelCommHelpers } from '../comm';
import { isArrayOfArrays } from '../shared/geoGebraCommon';
// Note: import jupyter REST helpers dynamically where needed to keep
// browser/webview bundles small and avoid unused-import build errors.

// Re-export shared utility
export { isArrayOfArrays };

/**
 * Initialize JupyterLab-specific kernel resources.
 * - starts a helper kernel (kernel2)
 * - creates a KernelConnection for the target kernel id
 * - initializes kernel_comm helpers and returns the send/handler factories
 * - registers widget comm passthrough when appropriate
 */
export async function setupKernelResources(resources: any, props: any, dbg: (...args: any[]) => void) {
	let _result: any = null;

	// If requested via props or PageConfig option, clear browser storage on startup.
	// This helps remove stale widget manager state that can conflict after refactors.
	const shouldClearFromProps = !!(props && (props.clearBrowserStorageOnStartup === true || props.clearBrowserStorageOnStartup === 'true'));
	const shouldClearFromPageConfig = (() => {
		try {
			const v = PageConfig.getOption && PageConfig.getOption('ggblab.clearBrowserStorageOnStartup');
			return v === 'true';
		} catch (e) {
			return false;
		}
	})();
	const shouldClearFromGlobal = (() => {
		try {
			return !!((window as any).__ggblab_clearBrowserStorageOnStartup === true || (window as any).__ggblab_clearBrowserStorageOnStartup === 'true');
		} catch (e) {
			return false;
		}
	})();
	let shouldClear = shouldClearFromProps || shouldClearFromPageConfig || shouldClearFromGlobal;

	// If running inside a VS Code webview (props.serverSettings present),
	// do not clear browser storage by default. Allow callers to opt-in by
	// passing `clearBrowserStorageInWebview: true` in props.
	try {
		const runningInWebview = !!(props && props.serverSettings);
		const allowClearInWebview = !!(props && (props.clearBrowserStorageInWebview === true || props.clearBrowserStorageInWebview === 'true'));
		if (runningInWebview && !allowClearInWebview) {
			try {
				console.debug('ggblab: running in VS Code webview — skipping browser storage clear by default');
			} catch (e) {
				// eslint-disable-next-line no-empty
			}
			shouldClear = false;
		}
	} catch (e) {
		/* ignore */
	}

	try {
		console.debug('ggblab: clearBrowserStorage flags', { shouldClearFromProps, shouldClearFromPageConfig, shouldClearFromGlobal, shouldClear });
	} catch (e) {
		// eslint-disable-next-line no-empty
	}

	async function clearBrowserStorage() {
		try {
			// Determine mode: selective (default) or full when explicitly requested
			const selective = !(props && props.clearBrowserStorageFull === true);

			const defaultPatterns = ['ggblab', 'widget', 'jupyterlab-workspace', 'jupyterlab', 'jupyter-widgets', '@jupyter-widgets'];
			const patterns: string[] = props && Array.isArray(props.clearBrowserStoragePatterns) && props.clearBrowserStoragePatterns.length ? props.clearBrowserStoragePatterns : defaultPatterns;

			const matches = (name: string | null | undefined) => {
				if (!name) {
					return false;
				}
				try {
					return patterns.some(p => name.toLowerCase().includes(String(p).toLowerCase()));
				} catch (e) {
					return false;
				}
			};

			// localStorage: either clear all or only keys that match patterns
			const removedLocalKeys: string[] = [];
			try {
				if (!selective) {
					try {
						localStorage.clear();
					} catch (e) {
						/* ignore */
					}
				} else {
					for (let i = localStorage.length - 1; i >= 0; i--) {
						const k = localStorage.key(i);
						if (k && matches(k)) {
							try {
								localStorage.removeItem(k);
								removedLocalKeys.push(k);
							} catch (e) {
								/* ignore */
							}
						}
					}
				}
			} catch (e) {
				/* ignore */
			}

			// sessionStorage: selective removal
			const removedSessionKeys: string[] = [];
			try {
				if (!selective) {
					try {
						sessionStorage.clear();
					} catch (e) {
						/* ignore */
					}
				} else {
					for (let i = sessionStorage.length - 1; i >= 0; i--) {
						const k = sessionStorage.key(i);
						if (k && matches(k)) {
							try {
								sessionStorage.removeItem(k);
								removedSessionKeys.push(k);
							} catch (e) {
								/* ignore */
							}
						}
					}
				}
			} catch (e) {
				/* ignore */
			}

			// indexedDB: delete databases whose name matches patterns (where supported)
			const removedIndexedDB: string[] = [];
			try {
				if (indexedDB && typeof (indexedDB as any).databases === 'function') {
					const dbs = await (indexedDB as any).databases();
					for (const d of dbs) {
						try {
							const name = d && d.name ? d.name : null;
							if (!name) {
								continue;
							}
							if (!selective || matches(name)) {
								try {
									indexedDB.deleteDatabase(name);
									removedIndexedDB.push(name);
								} catch (e) {
									/* ignore */
								}
							}
						} catch (e) {
							/* ignore per-db */
						}
					}
				}
			} catch (e) {
				/* ignore */
			}

			// caches: delete caches whose key matches patterns
			const removedCaches: string[] = [];
			try {
				if (window.caches) {
					const keys = await caches.keys();
					for (const k of keys) {
						try {
							if (!selective || matches(k)) {
								const ok = await caches.delete(k);
								if (ok) {
									removedCaches.push(k);
								}
							}
						} catch (e) {
							/* ignore per-cache */
						}
					}
				}
			} catch (e) {
				/* ignore */
			}

			// cookies: delete cookies whose name matches patterns (best-effort)
			const removedCookies: string[] = [];
			try {
				const cookies = document.cookie ? document.cookie.split(';') : [];
				for (const c of cookies) {
					const name = c.split('=')[0]?.trim();
					if (!name) {
						continue;
					}
					if (!selective || matches(name)) {
						try {
							document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`;
							removedCookies.push(name);
						} catch (e) {
							/* ignore */
						}
					}
				}
			} catch (e) {
				/* ignore */
			}

			try {
				console.info('ggblab: selective browser storage clear complete', {
					removedLocalKeys,
					removedSessionKeys,
					removedIndexedDB,
					removedCaches,
					removedCookies
				});
			} catch (e) {
				/* ignore logging failure */
			}
		} catch (e) {
			try {
				console.warn('ggblab: clearBrowserStorage failed', e);
			} catch (ee) {
				// eslint-disable-next-line no-empty
			}
		}
	}

	if (shouldClear) {
		try {
			console.info('ggblab: clearBrowserStorageOnStartup active — clearing storages (selective mode default)');
		} catch (e) {
			// eslint-disable-next-line no-empty
		}
		clearBrowserStorage().catch(() => {});
	}

	// Determine server settings first. In a VS Code webview we expect
	// `props.serverSettings` to be provided; avoid calling JupyterLab APIs that
	// resolve against the current document origin (vscode-webview://...), which
	// results in 403/invalid requests. Use REST helper to list kernels when
	// explicit serverSettings are present.
	let kernels: any[] = [];
	let settings: any = null;
	if (props && props.serverSettings) {
		// Keep the raw settings for REST calls, but create a ServerConnection
		// settings object for @jupyterlab/services usage (it expects fields
		// like `cache` and other helpers produced by makeSettings).
		const restSettings = props.serverSettings;
		try {
			settings = ServerConnection.makeSettings({
				baseUrl: restSettings.baseUrl || restSettings.base_url || '/',
				token: restSettings.token || '',
				appendToken: true
			});
		} catch (e) {
			dbg('Failed to create ServerConnection settings from props.serverSettings', e);
			settings = ServerConnection.makeSettings({ baseUrl: restSettings.baseUrl || '/', appendToken: true });
		}
		dbg('Using serverSettings from props (webview mode)');
		// For security reasons, REST-based listing of kernels is disabled.
		// Avoid using `../shared/jupyterRest` and default to an empty list.
		dbg('Skipping REST-based kernel listing for webview/serverSettings (disabled)');
		kernels = [];
	} else {
		try {
			kernels = await KernelAPI.listRunning();
			dbg('Running kernels (via KernelAPI):', kernels);
			const baseUrl = PageConfig.getBaseUrl();
			const token = PageConfig.getToken();
			dbg(`Base URL: ${baseUrl}`);
			dbg(`Token: ${token}`);
			settings = ServerConnection.makeSettings({
				baseUrl: baseUrl,
				token: token,
				appendToken: true
			});
		} catch (e) {
			dbg('KernelAPI.listRunning failed', e);
			kernels = [];
			const baseUrl = PageConfig.getBaseUrl ? PageConfig.getBaseUrl() : '/';
			settings = ServerConnection.makeSettings({ baseUrl, appendToken: true });
		}
	}

	resources.kernelManager = new KernelManager({ serverSettings: settings });
	resources.kernel2 = await resources.kernelManager.startNew({ name: 'python3' });
	dbg('Started new kernel:', resources.kernel2, resources.kernelId);
	try {
		await resources.kernel2.requestExecute({ code: 'from websockets.sync.client import unix_connect, connect' }).done;
		dbg('Imported unix_connect/connect in kernel2');
		// If a socketPath is available, perform a light probe to verify unix socket connectivity
		try {
			const probePath = resources.socketPath || (props && props.serverSettings && props.serverSettings.socketPath) || null;
			if (probePath) {
				const probeCode = `
try:
    with unix_connect("${probePath}") as ws:
        ws.send(r'''{"type":"probe","source":"kernel2"}''')
    print('ggblab:kernel2_probe:ok')
except Exception as _e:
    print('ggblab:kernel2_probe:error', repr(_e))
`;
				await resources.kernel2.requestExecute({ code: probeCode }).done;
				dbg('kernel2 unix_connect probe executed (sent probe)');
			} else {
				dbg('No socketPath available to probe from kernel2');
			}
		} catch (e) {
			dbg('kernel2 unix_connect probe failed', e);
		}
	} catch (e) {
		dbg('Failed to import unix_connect/connect in kernel2', e);
	}

	// Request kernel2 to start the Python TCP -> frontend bridge so non-Python
	// kernels can forward requests via that bridge. Historically this could be
	// controlled via a `bridgeMode` prop; that behavior has been removed and
	// the bridge is started unconditionally here.
	// Starting the kernel2-side bridge and probing it is not required in this
	// configuration; skip issuing bridge start/probe code to kernel2.
	dbg('Skipping kernel2 bridge start and probe (not required)');
	// Note: auxiliary kernel3 startup/registration removed — comm targets
	// are handled via the primary kernel or widget registration paths.
	// ws/socket values managed inside kernel_comm helpers
	// Initialize comm helpers from shared module
	const { callRemoteSocketSend, makeIncomingHandler } = initKernelCommHelpers(resources, dbg);
	dbg('Initialized kernel_comm helpers:', { callRemoteSocketSend, makeIncomingHandler });

	// Determine a target kernel id to connect to. `kernels` may be empty
	// (e.g., fresh server), and `resources.kernelId` may also be empty.
	// Prefer an explicit kernel id from props.serverSettings (or the
	// resources bag) if present. Otherwise fall back to the first running
	// kernel (if any).
	const explicitId = (props && props.serverSettings && props.serverSettings.kernelId) || resources.kernelId || null;
	const targetKernelId = explicitId || (Array.isArray(kernels) && kernels.length ? kernels[0] && (kernels[0].id || kernels[0]['kernel_id'] || kernels[0]['name']) : null);
	if (targetKernelId) {
		resources.kernelConn = new KernelConnection({
			model: { name: 'python3', id: targetKernelId },
			serverSettings: settings
		});
		dbg('Connected to kernel:', resources.kernelConn);

		// Ensure the per-kernel connection exposes a control comm target so a
		// kernel-side client can open `jupyter.ggblab.control` and request the
		// frontend to inject/open a widget for that kernel. This mirrors the
		// global registration but guarantees the current kernel's connection
		// has the handler synchronously available.
		try {
			if (resources.kernelConn && typeof resources.kernelConn.registerCommTarget === 'function') {
				resources.kernelConn.registerCommTarget('jupyter.ggblab.control', (commOp: any, msg: any) => {
					try {
						dbg('per-kernel jupyter.ggblab.control opened', { targetKernelId, msg });
						commOp.onMsg = async (m: any) => {
							try {
								const content = m?.content?.data || m;
								const command = typeof content === 'string' ? JSON.parse(content) : content;
								if (command && command.type === 'inject') {
									try {
										const g: any = window as any;
										if (g && typeof g.__ggblab_create_widget_for_kernel === 'function') {
											await g.__ggblab_create_widget_for_kernel(targetKernelId, { insertMode: command.insertMode, socketPath: command.socketPath, wsPort: command.wsPort });
										}
									} catch (e) {
										dbg('per-kernel control inject failed', e);
									}
								}
							} catch (e) {
								dbg('Error in per-kernel control onMsg', e);
							}
						};
					} catch (e) {
						dbg('Error registering per-kernel jupyter.ggblab.control handler', e);
					}
				});
			}
		} catch (e) {
			dbg('Failed to register per-kernel control target', e);
		}
	} else {
		resources.kernelConn = null;
		dbg('No existing kernel id found to create KernelConnection; kernelConn set to null');
	}

	_result = { callRemoteSocketSend, makeIncomingHandler, kernelConn: resources.kernelConn, serverSettings: settings };

	// Widget comm passthrough registration is handled by the applet fallback
	// or by the optional widget-manager detection plugin. Keeping this module
	// focused on kernel/service initialization avoids duplicating registration
	// logic with `GeoGebraApplet.tsx`.

	return _result;
}

export default setupKernelResources;
