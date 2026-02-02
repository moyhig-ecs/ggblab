
// Kernel communication helpers extracted from `src/widget.tsx`.
// Provides an initializer that accepts a resource bag (`res`) and a
// debug function and returns comm-related helpers bound to that bag.

export type KernelCommHelpers = {
	callRemoteSocketSend: (message: string) => Promise<void>;
	ensureKernelComm: (opts: any) => Promise<any | null>;
	attachCommCloseHandler: (opts: { c: any; setClosed: (b: boolean) => void; commTarget: string; dbg?: any }) => void;
	makeIncomingHandler: (processCommandMessage: (cmd: any) => Promise<string>) => (msg: any) => Promise<void>;
};

export function initKernelCommHelpers(res: any, dbg?: any): KernelCommHelpers {
	// Per-init send chain to serialize socket sends
	let sendChain: Promise<void> = Promise.resolve();

	async function callRemoteSocketSend(message: string): Promise<void> {
		try {
			dbg && dbg('callRemoteSocketSend: sending message', {
				socketPath: res.socketPath,
				wsUrl: `ws://localhost:${res.wsPort}/`,
				messagePreview: (message || '').slice(0, 200)
			});

			const wsUrl = `ws://localhost:${res.wsPort}/`;
			const socketPath = res.socketPath;

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
			sendChain = next.catch((e) => {
				dbg && dbg('callRemoteSocketSend chain error', e);
			});
			await next;
			dbg && dbg('callRemoteSocketSend: sent', { idPreview: (message || '').slice(0, 40) });
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
			res.comm = kconn.createComm(ct);
			try {
				const maybeId = (res.comm as any)?.comm_id || (res.comm as any)?.commId || (res.comm as any)?.id || null;
				_dbg && _dbg('Recreated kernel comm', { target: ct, commObject: res.comm, commId: maybeId });
			} catch (err) {
				_dbg && _dbg('Recreated kernel comm (unable to read id)', ct, res.comm);
			}
			try {
				(res.comm as any).onMsg = h;
			} catch (err) {
				_dbg && _dbg('Failed to attach onMsg to recreated comm', err);
			}
			try {
				ach && ach(res.comm);
			} catch (err) {
				_dbg && _dbg('Failed to attach close handler to recreated comm', err);
			}
			try {
				(res.comm as any).open && (res.comm as any).open('REOPEN from GGB').done;
			} catch (err) {
				_dbg && _dbg('Failed to open recreated comm', err);
			}
			return res.comm;
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
				commTarget: res.commTarget,
				dbg
			});

		return async function handler(msg: any) {
			const _dbg = dbg || (() => {});
			_dbg('handleIncomingCommMessage:', msg);
			try {
				_dbg('Kernel comm onMsg received', { commTarget: res.commTarget || '', msg });

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
	}

	return {
		callRemoteSocketSend,
		ensureKernelComm,
		attachCommCloseHandler,
		makeIncomingHandler
	};
}
