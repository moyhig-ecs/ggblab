// Minimal widget-manager adapter extracted from plugin/widget code.
// This module centralizes how a frontend WidgetManager (ipywidgets bridge)
// would be created or provided.

export type WidgetManagerType = any;
import type { IRegisterWidgetCommOptions } from '../types';

let _injectedWidgetManager: WidgetManagerType | undefined = undefined;

export function setWidgetManager(m?: WidgetManagerType): void {
	_injectedWidgetManager = m;
	try {
		(globalThis as any).__GGWIDGET_MANAGER__ = m;
		try {
			console.debug('ggblab: setWidgetManager called', { hasManager: !!m });
		} catch (e) {
			// eslint-disable-next-line no-empty
		}
	} catch (e) {
		// eslint-disable-next-line no-empty
	}
}

function detectWidgetManager(): WidgetManagerType | undefined {
	const g = globalThis as any;
	try {
		console.debug('ggblab: detectWidgetManager probing globals');
	} catch (e) {
		// eslint-disable-next-line no-empty
	}
	if (g && g.__GGWIDGET_MANAGER__) {
		try {
			console.debug('ggblab: detected manager via __GGWIDGET_MANAGER__');
		} catch (_) {
			// eslint-disable-next-line no-empty
		}
		return g.__GGWIDGET_MANAGER__ as WidgetManagerType;
	}
	if (g && g.jupyterWidgetManager) {
		try {
			console.debug('ggblab: detected manager via jupyterWidgetManager');
		} catch (_) {
			// eslint-disable-next-line no-empty
		}
		return g.jupyterWidgetManager as WidgetManagerType;
	}
	if (g && g.widgetManager) {
		try {
			console.debug('ggblab: detected manager via widgetManager');
		} catch (_) {
			// eslint-disable-next-line no-empty
		}
		return g.widgetManager as WidgetManagerType;
	}
	try {
		console.debug('ggblab: no widget manager detected in globals');
	} catch (_) {
		// eslint-disable-next-line no-empty
	}
	return undefined;
}

export function createWidgetManager(): WidgetManagerType | undefined {
	if (_injectedWidgetManager) {
		return _injectedWidgetManager;
	}
	return detectWidgetManager();
}

export function registerWidgetCommTargets(kernelConn: any, opts: IRegisterWidgetCommOptions): () => void {
	// Defensive: if no kernelConn is provided, skip and surface debug info
	try {
		if (!kernelConn) {
			(opts && opts.dbg) && opts.dbg('registerWidgetCommTargets: kernelConn is null or undefined — skipping registration');
			return () => { /* noop */ };
		}
	} catch (e) {
		try { (opts && opts.dbg) && opts.dbg('registerWidgetCommTargets: error checking kernelConn', e); } catch (ee) {}
		return () => { /* noop */ };
	}

	const managerAvailable = Boolean(createWidgetManager());
	const ENABLE_WIDGET_COMM_PASSTHROUGH = !managerAvailable;

	if (!ENABLE_WIDGET_COMM_PASSTHROUGH) {
		opts.dbg && opts.dbg('Widget comm passthrough disabled: WidgetManager present');
		return () => {
			/* noop unregister */
		};
	}
	opts.dbg && opts.dbg('Widget comm passthrough enabled: no WidgetManager detected');
	const dbg = opts.dbg || (() => {});

	const simpleHandler = (commOp: any, msg: any) => {
		dbg('widget comm opened (jupyter.widget)', commOp, msg);
		try {
			commOp.onMsg = async (m: any) => {
				const content = m?.content?.data || m;
				try {
					const command = typeof content === 'string' ? JSON.parse(content) : content;
					let rmsg: any = null;
					const appletApi = opts.getAppletApi();
					if (command.type === 'command' && appletApi && typeof appletApi.evalCommandGetLabels === 'function') {
						const label = appletApi.evalCommandGetLabels(command.payload);
						rmsg = JSON.stringify({ type: 'created', id: command.id, payload: label });
					} else if (command.type === 'function' && appletApi) {
						const apiName = command.payload.name;
						const args = command.payload.args;
						let value: any[] = [];
						(Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
							if (typeof (opts as any).isArrayOfArrays === 'function' && (opts as any).isArrayOfArrays(args)) {
								const v2: any[] = [];
								args.forEach((a: any[]) => {
									v2.push(typeof appletApi[f] === 'function' ? appletApi[f](...a) : null);
								});
								value.push(v2);
							} else {
								value.push(args ? (typeof appletApi[f] === 'function' ? appletApi[f](...args) : null) : typeof appletApi[f] === 'function' ? appletApi[f]() : null);
							}
						});
						value = Array.isArray(apiName) ? value : value[0];
						rmsg = JSON.stringify({ type: 'value', id: command.id, payload: { value } });
					}
					if (rmsg) {
						try {
							commOp.send(rmsg);
						} catch (e) {
							dbg('commOp.send failed', e);
						}
						try {
							await opts.callRemoteSocketSend(rmsg);
						} catch (e) {
							dbg('callRemoteSocketSend failed', e);
						}
					}
				} catch (e) {
					dbg('Error handling widget comm message', e);
				}
			};
		} catch (e) {
			dbg('Failed to attach onMsg to widget comm', e);
		}
	};

	try {
		kernelConn.registerCommTarget('jupyter.widget', simpleHandler);
		kernelConn.registerCommTarget('jupyter.widget.control', simpleHandler);
	} catch (e) {
		dbg('Widget comm target registration failed', e);
	}

	return () => {
		try {
			if (typeof kernelConn.unregisterCommTarget === 'function') {
				kernelConn.unregisterCommTarget('jupyter.widget');
				kernelConn.unregisterCommTarget('jupyter.widget.control');
			}
		} catch (e) {
			dbg('Error during widget comm cleanup', e);
		}
	};
}

import { KernelAPI, KernelConnection, ServerConnection } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';

export const ENABLE_RUNNING_CHANGED = false;

export async function registerGlobalGGBlabCommTargets(app?: any): Promise<() => void> {
	const baseUrl = PageConfig.getBaseUrl();
	const token = PageConfig.getToken();
	const settings = ServerConnection.makeSettings({ baseUrl: baseUrl, token: token, appendToken: true });

	const registry = new Map<string, () => void>();

	const dbg = (..._args: any[]) => {
		if (!ENABLE_RUNNING_CHANGED) {
			return;
		}
		console.debug(..._args);
	};

	const registerKernel = (k: any) => {
		const id = k.id || k.kernelId || (k.model && k.model.id) || null;
		if (!id) {
			return;
		}
		if (registry.has(id)) {
			dbg('Already registered jupyter.ggblab for kernel', id);
			return;
		}
		try {
			const manager = createWidgetManager();
			if (manager && typeof manager.registerGGBlabHandler === 'function') {
				try {
					const unregisterFromManager = manager.registerGGBlabHandler(id, (commOp: any, msg: any) => {
						try {
							void 0;
						} catch (e) {
							console.warn('Error delegating jupyter.ggblab to manager', e);
						}
					});
					registry.set(id, () => {
						unregisterFromManager && unregisterFromManager();
					});
					return;
				} catch (e) {
					console.warn('Widget manager failed to register jupyter.ggblab', id, e);
				}
			}

			const kc = new KernelConnection({ model: { name: 'python3', id }, serverSettings: settings });
			try {
				kc.registerCommTarget('jupyter.ggblab', (commOp: any, msg: any) => {
					try {
						dbg('jupyter.ggblab comm opened', { kernelId: id, msg });
						commOp.onMsg = (m: any) => {
							dbg('jupyter.ggblab message', { kernelId: id, m });
						};
					} catch (e) {
						console.warn('Error in jupyter.ggblab handler', e);
					}
				});
			} catch (e) {
				console.warn('Failed to register jupyter.ggblab on kernel', id, e);
			}

			const unregister = () => {
				try {
					if (typeof (kc as any).unregisterCommTarget === 'function') {
						(kc as any).unregisterCommTarget('jupyter.ggblab');
					}
				} catch (e) {
					console.warn('Error while unregistering jupyter.ggblab', e);
				}
			};
			registry.set(id, unregister);
		} catch (e) {
			console.warn('Failed to create KernelConnection for kernel', id, e);
		}
	};

	const unregisterKernel = (id: string) => {
		const fn = registry.get(id);
		if (fn) {
			try {
				fn();
			} catch (e) {
				console.warn('Error during unregister for kernel', id, e);
			}
			registry.delete(id);
		}
	};

	try {
		const kernels = await KernelAPI.listRunning();
		(kernels || []).forEach(registerKernel);
	} catch (e) {
		console.warn('Failed to list running kernels for ggblab registration', e);
	}

	const onRunningChanged = async () => {
		try {
			const current = await KernelAPI.listRunning();
			const currentIds = new Set((current || []).map((k: any) => k.id));
			(current || []).forEach(k => registerKernel(k));
			Array.from(registry.keys()).forEach(id => {
				if (!currentIds.has(id)) {
					unregisterKernel(id);
				}
			});
		} catch (e) {
			console.warn('Error handling runningChanged for ggblab', e);
		}
	};

	try {
		if (ENABLE_RUNNING_CHANGED) {
			try {
				if (
					app &&
					app.serviceManager &&
					app.serviceManager.sessions &&
					typeof app.serviceManager.sessions.runningChanged === 'object' &&
					typeof app.serviceManager.sessions.runningChanged.connect === 'function'
				) {
					app.serviceManager.sessions.runningChanged.connect(onRunningChanged);
				} else if ((KernelAPI as any).runningChanged && typeof (KernelAPI as any).runningChanged.connect === 'function') {
					(KernelAPI as any).runningChanged.connect(onRunningChanged);
				} else {
					const pollInterval = 5000;
					const timer = setInterval(onRunningChanged, pollInterval);
					registry.set('__poll_timer__', () => clearInterval(timer));
				}
			} catch (e) {
				console.warn('Failed to attach runningChanged listener', e);
			}
		} else {
			dbg('Kernel runningChanged detection is disabled (ENABLE_RUNNING_CHANGED=false)');
		}
	} catch (e) {
		console.warn('Failed to attach runningChanged listener', e);
	}

	return () => {
		try {
			if (
				app &&
				app.serviceManager &&
				app.serviceManager.sessions &&
				typeof app.serviceManager.sessions.runningChanged === 'object' &&
				typeof app.serviceManager.sessions.runningChanged.disconnect === 'function'
			) {
				app.serviceManager.sessions.runningChanged.disconnect(onRunningChanged as any);
			} else if ((KernelAPI as any).runningChanged && typeof (KernelAPI as any).runningChanged.disconnect === 'function') {
				(KernelAPI as any).runningChanged.disconnect(onRunningChanged as any);
			}
			Array.from(registry.keys()).forEach(k => {
				const fn = registry.get(k);
				if (fn) {
					fn();
				}
			});
			registry.clear();
		} catch (e) {
			console.warn('Error during global ggblab unregister-all', e);
		}
	};
}
