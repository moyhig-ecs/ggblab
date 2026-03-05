/* Shared setup for the front portion of ggbOnLoad used by both
   the JupyterLab widget and the VSCode webview widget. This function
   performs common wiring: expose `appletApi`, send a start message,
   create kernel comm if configured, attach incoming handlers, register
   simple API listeners (add/remove/rename/clear), and install a
   MutationObserver to forward dialog messages.
*/
export default async function setupAppletOnLoadCommon(api: any, resources: any, callRemoteSocketSend: (m: string) => Promise<void>, handleIncomingCommMessage: any, dbg: (...args: any[]) => void) {
	dbg('Shared ggbOnLoad common setup: start');

	// Small runtime trap useful during debugging: it records the
	// latest trap payload on `window.__ggblab_last_trap`, calls an
	// optional `window.__ggblab_trap` callback, and logs to console.
	const trap = (label: string, info?: any) => {
		try {
			const payload = { label, info, ts: Date.now() };
			(window as any).__ggblab_last_trap = payload;
			console.warn('[GGBLAB-TRAP]', payload);
			if ((window as any).__ggblab_trap && typeof (window as any).__ggblab_trap === 'function') {
				try { (window as any).__ggblab_trap(payload); } catch (e) { dbg('__ggblab_trap callback threw', e); }
			}
		} catch (e) {
			dbg('trap() error', e);
		}
	};

	// Expose resources for quick inspection in the page console
	(window as any).__ggblab_resources = resources;
	trap('setup-start');
	resources.appletApi = api;
	(async () => {
		const msg = { type: 'start', payload: {} };
		try {
			await callRemoteSocketSend(JSON.stringify(msg));
		} catch (e) {
			dbg('callRemoteSocketSend failed (start)', e);
		}
	})();

	// Kernel comm creation (when a commTarget is present)
	if (resources.commTarget) {
		try {
			resources.comm = resources.kernelConn.createComm(resources.commTarget);
			try {
				const maybeId = (resources.comm as any)?.comm_id || (resources.comm as any)?.commId || null;
				dbg('Created kernel comm', { target: resources.commTarget, commObject: resources.comm, commId: maybeId });
				try { trap('comm-created', { target: resources.commTarget, commId: maybeId }); } catch (e) { dbg('trap after comm-create failed', e); }
			} catch (e) {
				dbg('Created kernel comm (unable to read id)', resources.commTarget, resources.comm);
			}
			try {
				resources.comm.open && resources.comm.open('HELO from GGB');
			} catch (e) {
				dbg('Failed to open kernel comm', e);
			}
		} catch (e) {
			dbg('Failed to create kernel comm for', resources.commTarget, e);
			resources.comm = null;
		}

		try {
			(resources.comm as any).onClose = (m: any) => {
				try {
					const closedId = (m && m.content && m.content.comm_id) || (resources.comm as any)?.comm_id || (resources.comm as any)?.commId || null;
					dbg('Kernel comm closed', { target: resources.commTarget, commId: closedId, message: m });
					try { trap('comm-closed', { target: resources.commTarget, commId: closedId, message: m }); } catch (e) { dbg('trap in onClose failed', e); }
				} catch (e) {
					dbg('Kernel comm closed (no id available)', resources.commTarget, m);
					try { trap('comm-closed', { target: resources.commTarget, commId: null, message: m }); } catch (e2) { dbg('trap in onClose fallback failed', e2); }
				}

				// Previously we attempted an automatic comm recreate when a
				// `bridgeMode` flag was active. That behavior has been removed;
				// comm recreation is no longer performed automatically here.
			};
		} catch (e) {
			dbg('Unable to attach onClose to kernel comm', e);
		}
	} else {
		resources.comm = null;
		dbg('No commTarget provided; skipping kernel comm creation (shared)');
	}

	// Attach incoming handler if comm exists
	if (resources.comm) {
		try {
			// Wrap incoming comm messages to surface them via the trap helper
			(resources.comm as any).onMsg = (m: any) => {
				trap('comm-onMsg', m);
				try {
					handleIncomingCommMessage && handleIncomingCommMessage(m);
				} catch (e) {
					dbg('handleIncomingCommMessage threw', e);
				}
			};
		} catch (e) {
			dbg('Failed to attach wrapped handleIncomingCommMessage to comm', e);
		}
	} else {
		dbg('No kernel comm available; messages will be sent via remote socket only (shared)');
	}

	// Close handler
	resources.closeHandler = () => {
		try {
			resources.comm?.close?.();
		} catch (e) {
			dbg('Error closing comm', e);
		}
		try {
			resources.kernel2?.shutdown?.();
		} catch (e) {
			dbg('Error shutting down kernel2', e);
		}
		dbg('Kernel and comm closed.');
		if (resources.resizeHandler) {
			try {
				window.removeEventListener('resize', resources.resizeHandler);
			} catch (e) {
				/* ignore */
			}
		}
	};
	try {
		window.addEventListener('close', resources.closeHandler);
	} catch (e) {
		dbg('addEventListener close failed', e);
	}

	// Register basic API listeners that forward events to the kernel/socket
	const addListener = async function (data: any) {
		dbg('Add listener triggered for (shared):', data);
		const msg = { type: 'add', payload: data };
		const s = JSON.stringify(msg);
		if (resources.widgetComm) {
			try {
				resources.widgetComm.send(s);
				return;
			} catch (e) {
				dbg('widgetComm.send failed, falling back', e);
			}
		}
		try {
			await callRemoteSocketSend(s);
		} catch (e) {
			dbg('callRemoteSocketSend failed (add)', e);
		}
	};

	const removeListener = async function (data: any) {
		dbg('Remove listener triggered for (shared):', data);
		const msg = { type: 'remove', payload: data };
		const s = JSON.stringify(msg);
		if (resources.widgetComm) {
			try {
				resources.widgetComm.send(s);
				return;
			} catch (e) {
				dbg('widgetComm.send failed, falling back', e);
			}
		}
		try {
			await callRemoteSocketSend(s);
		} catch (e) {
			dbg('callRemoteSocketSend failed (remove)', e);
		}
	};

	const renameListener = async function (data: any) {
		dbg('Rename listener triggered for (shared):', data);
		const msg = { type: 'rename', payload: data };
		const s = JSON.stringify(msg);
		if (resources.widgetComm) {
			try {
				resources.widgetComm.send(s);
				return;
			} catch (e) {
				dbg('widgetComm.send failed, falling back', e);
			}
		}
		try {
			await callRemoteSocketSend(s);
		} catch (e) {
			dbg('callRemoteSocketSend failed (rename)', e);
		}
	};

	const clearListener = async function (data: any) {
		dbg('Clear listener triggered for (shared):', data);
		const msg = { type: 'clear', payload: data };
		const s = JSON.stringify(msg);
		if (resources.widgetComm) {
			try {
				resources.widgetComm.send(s);
				return;
			} catch (e) {
				dbg('widgetComm.send failed, falling back', e);
			}
		}
		try {
			await callRemoteSocketSend(s);
		} catch (e) {
			dbg('callRemoteSocketSend failed (clear)', e);
		}
	};

	try {
		api.registerAddListener?.(addListener);
	} catch (e) {
		dbg('registerAddListener failed (shared)', e);
	}
	try {
		api.registerRemoveListener?.(removeListener);
	} catch (e) {
		dbg('registerRemoveListener failed (shared)', e);
	}
	try {
		api.registerRenameListener?.(renameListener);
	} catch (e) {
		dbg('registerRenameListener failed (shared)', e);
	}
	try {
		api.registerClearListener?.(clearListener);
	} catch (e) {
		dbg('registerClearListener failed (shared)', e);
	}

	// MutationObserver to forward dialog messages
	try {
		resources.observer = new MutationObserver(mutations => {
			mutations.forEach(mutation => {
				mutation.addedNodes.forEach(node => {
					try {
						(node as HTMLElement).querySelectorAll &&
							(node as HTMLElement).querySelectorAll('div.dialogMainPanel > div.dialogTitle').forEach(n => {
								(node as HTMLElement)
									.querySelector('div.dialogContent')
									?.querySelectorAll("[class$='Label']")
									.forEach(async n2 => {
										const msg = JSON.stringify({ type: n.textContent, payload: n2.textContent });
										try {
											await callRemoteSocketSend(msg);
										} catch (e) {
											dbg('callRemoteSocketSend failed (dialog)', e);
										}
									});
							});
					} catch (e) {
						/* ignore per-node errors */
					}
				});
			});
		});
		resources.observer.observe(document.body, { childList: true, subtree: true });
	} catch (e) {
		dbg('Failed to install MutationObserver (shared)', e);
	}

	dbg('Shared ggbOnLoad common setup: complete');
}
