// Kernel communication helpers used by the webview to send messages to the kernel.

export type KernelCommHelpers = {
	callRemoteSocketSend: (message: string) => Promise<void>;
	ensureKernelComm: (opts: any) => Promise<any | null>;
	attachCommCloseHandler: (opts: { c: any; setClosed: (b: boolean) => void; commTarget: string; dbg?: any }) => void;
	makeIncomingHandler: (processCommandMessage: (cmd: any) => Promise<string>) => (msg: any) => Promise<void>;
};

// Global handle so external code (e.g. WebIO handlers) can call the
// kernel-side send helper without holding the `resources` closure.
export let globalCallRemoteSocketSend: (message: string) => Promise<void> = async (
	_message: string
) => {
	throw new Error(
		'globalCallRemoteSocketSend not initialized - call initKernelCommHelpers first'
	);
};

export function callRemoteSocketSendGlobal(message: string): Promise<void> {
	return globalCallRemoteSocketSend(message);
}

export function initKernelCommHelpers(resources: any, dbg?: any): KernelCommHelpers {
	// Default: enable fire-and-forget for kernel2 unless explicitly disabled.
	if (resources && typeof resources.kernel2FireAndForget === 'undefined') {
		resources.kernel2FireAndForget = true;
	}
	let sendChain: Promise<void> = Promise.resolve();

	// (kernel-only mode) browser WebSocket fallback removed: sending is via kernel2

	// batching for action messages (add/remove/rename/clear and object_update)
	let actionBatchBuffer: Array<{ type: string; payload: any; ts?: number }> = [];
	let actionBatchTimer: any = null;
	const batchInterval = resources && resources.batchInterval ? resources.batchInterval : 30;

	const log = dbg || (() => {});

	async function performSend(msgToSend: string) {
		const wsUrl = resources && resources.wsUrl ? resources.wsUrl : undefined;
		const socketPath = resources && resources.socketPath ? resources.socketPath : undefined;

		if (resources && resources.kernel2 && typeof resources.kernel2.requestExecute === 'function') {
			try {
				try {
					log && log('performSend: using kernel2.requestExecute', { kernel2: !!resources.kernel2, socketPath: socketPath || undefined, wsUrlPreview: wsUrl || undefined });
				} catch (e) {
					// eslint-disable-next-line no-empty
				}
				let code: string;
				if (socketPath) {
					code = `\nwith unix_connect(${JSON.stringify(socketPath)}) as ws:\n\tws.send(r"""${msgToSend}""")\n`;
				} else if (wsUrl) {
					code = `\nwith connect(${JSON.stringify(wsUrl)}) as ws:\n\tws.send(r"""${msgToSend}""")\n`;
				} else {
					// Neither socketPath nor wsUrl configured — fail fast rather than guessing
					throw new Error('No socketPath or wsUrl configured in resources for performSend');
				}
				const exec = resources.kernel2.requestExecute({ code });
				// fire-and-forget mode avoids awaiting exec.done
				if (resources.kernel2FireAndForget) {
					exec.done &&
						exec.done.catch((err: any) => {
							log('kernel2 async exec failed', err);
						});
				} else {
					await exec.done;
				}
			} catch (e) {
				log('performSend kernel2.requestExecute failed', e);
				throw e;
			}
		} else {
			log('performSend: kernel2.requestExecute not available');
			throw new Error('kernel2.requestExecute not available');
		}

		// small inter-send gap to avoid jamming
		await new Promise(resolve => setTimeout(resolve, 30));
	}

	const enqueueSend = (msgStr: string) => {
		const next = sendChain.then(() => performSend(msgStr));
		sendChain = next.catch(e => {
			log('callRemoteSocketSend chain error', e);
		});
		return next;
	};

	const flushActionBatch = () => {
		if (!actionBatchBuffer.length) {
			return;
		}
		const toSend = actionBatchBuffer.slice();
		actionBatchBuffer = [];
		if (actionBatchTimer) {
			clearTimeout(actionBatchTimer);
			actionBatchTimer = null;
		}
		const batchMsg = JSON.stringify({ type: 'bulk_actions', payload: toSend });
		enqueueSend(batchMsg).catch(() => {});
	};

	const scheduleActionBatchFlush = () => {
		if (actionBatchTimer) {
			return;
		}
		actionBatchTimer = setTimeout(() => {
			try {
				flushActionBatch();
			} catch (e) {
				log('flushActionBatch failed', e);
			}
		}, batchInterval);
	};

	async function callRemoteSocketSend(message: string): Promise<void> {
		try {
			// Debug: trace incoming messages to help diagnose why sends may be missing
			try {
				log && log('callRemoteSocketSend received', message);
			} catch (e) {
				// eslint-disable-next-line no-empty
			}

			try {
				const parsed = JSON.parse(message as string);
				// Treat object_update the same as UI action messages (add/remove/rename/clear)
				// and batch them into `bulk_actions` for kernel-side processing.
				if (parsed && (parsed.type === 'add' || parsed.type === 'remove' || parsed.type === 'rename' || parsed.type === 'clear' || parsed.type === 'object_update')) {
					try {
						const entry = { type: parsed.type, payload: parsed.payload, ts: parsed.ts ?? Date.now() };
						actionBatchBuffer.push(entry);
						try {
							log && log('Queued bulk action entry', entry, { actionBatchBufferLength: actionBatchBuffer.length });
						} catch (e) {
							// eslint-disable-next-line no-empty
						}
						// For object_update we prefer immediate delivery rather than waiting
						// for the action batch timer to fire, to reduce perceived latency.
						if (parsed.type === 'object_update') {
							try {
								flushActionBatch();
							} catch (e) {
								log('Immediate flushActionBatch failed', e);
							}
						} else {
							scheduleActionBatchFlush();
						}
						return;
					} catch (e) {
						log('Batch queue failed', e);
					}
				}
			} catch (e) {
				/* not JSON or other message */
			}

			await enqueueSend(message);
		} catch (err) {
			console.error('callRemoteSocketSend: error sending message', err);
			throw err;
		}
	}

	function attachCommCloseHandler(opts: any) {
		const { c, setClosed, commTarget, dbg: _dbg } = opts;
		try {
			(c as any).onClose = (m: any) => {
				try {
					setClosed(true);
					const closedId = (m && m.content && m.content.comm_id) || (c as any)?.comm_id || (c as any)?.commId || null;
					_dbg && _dbg('Kernel comm closed', { target: commTarget, commId: closedId, message: m });
					// Automatic comm recreation removed; consumers may recreate manually if needed.
				} catch (e) {
					_dbg && _dbg('Kernel comm closed (no id available)', commTarget, m);
				}
			};
		} catch (e) {
			_dbg && _dbg('Unable to attach onClose to kernel comm', e);
		}
	}

	async function ensureKernelComm(opts: any): Promise<any | null> {
		const { kernelConn: kconn, commTarget: ct, handleIncomingCommMessage: h, attachCloseHandler: ach, dbg: _dbg } = opts;
		try {
			if (!kconn) {
				throw new Error('No kernelConn available to create comm');
			}
			resources.comm = kconn.createComm(ct);
			try {
				const maybeId = (resources.comm as any)?.comm_id || (resources.comm as any)?.commId || (resources.comm as any)?.id || null;
				_dbg && _dbg('Recreated kernel comm', { target: ct, commObject: resources.comm, commId: maybeId });
			} catch (err) {
				_dbg && _dbg('Recreated kernel comm (unable to read id)', ct, resources.comm);
			}
			try {
				(resources.comm as any).onMsg = h;
			} catch (err) {
				_dbg && _dbg('Failed to attach onMsg to recreated comm', err);
			}
			try {
				ach && ach(resources.comm);
			} catch (err) {
				_dbg && _dbg('Failed to attach close handler to recreated comm', err);
			}
			try {
				(resources.comm as any).open && (resources.comm as any).open('REOPEN from GGB').done;
			} catch (err) {
				_dbg && _dbg('Failed to open recreated comm', err);
			}
			return resources.comm;
		} catch (e) {
			_dbg && _dbg('ensureKernelComm failed', e);
			return null;
		}
	}

	function makeIncomingHandler(processCommandMessage: (cmd: any) => Promise<string>) {
		let commClosed = false;
		const attachCommCloseHandlerLocal = (c: any) =>
			attachCommCloseHandler({
				c,
				setClosed: (v: boolean) => {
					commClosed = v;
				},
				commTarget: resources.commTarget,
				dbg
			});

		const handler = async function (msg: any) {
			const _dbg = dbg || (() => {});
			_dbg('handleIncomingCommMessage:', msg);
			try {
				_dbg('Kernel comm onMsg received', { commTarget: resources.commTarget || '', msg });

				const command = JSON.parse(msg.content.data as any);
				_dbg('Parsed command:', command.type, command.payload);

				let rmsg: any = null;
				try {
					rmsg = await processCommandMessage(command);
				} catch (e) {
					_dbg('Error processing command', e);
					rmsg = JSON.stringify({ type: 'error', id: command?.id || null, payload: { message: 'Processing failed' } });
				}

				try {
					const cId = (resources.comm as any)?.comm_id || (resources.comm as any)?.commId || null;
					_dbg('Sending via kernel comm', { commTarget: resources.commTarget, commId: cId, preview: (rmsg || '').slice(0, 200) });
					if (!resources.comm || commClosed) {
						try {
							const created = await ensureKernelComm({
								kernelConn: resources.kernelConn,
								commTarget: resources.commTarget,
								handleIncomingCommMessage: handler,
								attachCloseHandler: attachCommCloseHandlerLocal,
								dbg: _dbg
							});
							if (created) {
								resources.comm = created;
								commClosed = false;
							}
						} catch (e) {
							_dbg('ensureKernelComm failed before sending reply', e);
						}
					}
					if (resources.comm) {
						try {
							resources.comm.send(rmsg);
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
		// handler assigned directly; no external ref required
		return handler;
	}

		// expose the concrete implementation to global export so external
		// WebIO handlers can call it without keeping the `resources` closure.
		globalCallRemoteSocketSend = callRemoteSocketSend;
		try {
			// Also attach to globalThis so non-module consumers (WebIO inline handlers)
			// can call `globalCallRemoteSocketSend(...)` directly in the browser.
			(globalThis as any).globalCallRemoteSocketSend = callRemoteSocketSend;
		} catch (e) {
			// ignore if we can't assign to globalThis in some environments
		}
	return { callRemoteSocketSend, ensureKernelComm, attachCommCloseHandler, makeIncomingHandler };
}
