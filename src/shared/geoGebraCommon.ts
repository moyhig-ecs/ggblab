// Shared helpers extracted from GeoGebraApplet and VSCode widget
export function isArrayOfArrays(value: any): boolean {
	return Array.isArray(value) && value.every((subArray: any) => Array.isArray(subArray));
}

export function createProcessCommandMessage(resources: any, callRemoteSocketSend: (m: string) => Promise<void>, isArrayOfArraysFn: (v: any) => boolean, dbg: (...args: any[]) => void) {
	return async (command: any): Promise<string> => {
		let rmsg: any = null;

		const handlers: { [k: string]: (cmd: any) => Promise<any> } = {
			command: async (cmd: any) => {
				if (resources.appletApi && typeof resources.appletApi.evalCommandGetLabels === 'function') {
					const label = resources.appletApi.evalCommandGetLabels(cmd.payload);
					return JSON.stringify({ type: 'created', id: cmd.id, payload: label });
				}
				return JSON.stringify({ type: 'error', id: cmd.id, payload: { message: 'applet API not available' } });
			},
			function: async (cmd: any) => {
				const apiName = cmd.payload.name;
				dbg('apiName:', apiName);
				let value: any[] = [];
				const args = cmd.payload.args;
				value = [];
				(Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
					dbg('call', f, args);
					if (isArrayOfArraysFn(args)) {
						const value2: any[] = [];
						args.forEach((arg2: any[]) => {
							if (resources.appletApi && typeof resources.appletApi[f] === 'function') {
								value2.push(resources.appletApi[f](...arg2) || null);
							} else {
								value2.push(null);
							}
						});
						value.push(value2);
					} else {
						if (args) {
							value.push(resources.appletApi && typeof resources.appletApi[f] === 'function' ? resources.appletApi[f](...args) || null : null);
						} else {
							value.push(resources.appletApi && typeof resources.appletApi[f] === 'function' ? resources.appletApi[f]() || null : null);
						}
					}
				});
				value = Array.isArray(apiName) ? value : value[0];
				dbg('Function value:', value);
				return JSON.stringify({ type: 'value', id: cmd.id, payload: { value: value } });
			},
			listen: async (cmd: any) => {
				dbg('Register listen request:', cmd.payload);
				try {
					let name: string | null = null;
					let enabled = true;
					const p = cmd.payload;
					if (Array.isArray(p)) {
						name = p[0];
						enabled = !!p[1];
					} else if (p && typeof p === 'object') {
						if (typeof p.name === 'string') {
							name = p.name;
						}
						if (p.enabled !== undefined) {
							enabled = !!p.enabled;
						} else if (p.enable !== undefined) {
							enabled = !!p.enable;
						}
					} else if (typeof p === 'string') {
						name = p;
						enabled = true;
					}

					if (!name) {
						throw new Error('listen payload must include object name');
					}

					let result: any = null;
					if (enabled) {
						if (resources.appletApi && typeof resources.appletApi.registerObjectUpdateListener === 'function') {
							try {
								const cb = () => {
									try {
										let value: any = null;
										try {
											if (resources.appletApi && typeof resources.appletApi.getValueString === 'function') {
												value = (resources.appletApi.getValueString as any)(name);
											} else {
												value = null;
											}
										} catch (e) {
											dbg('getValueString failed', e);
											value = null;
										}
										try {
											const last = resources._lastValues[name] ?? null;
											const cur = value === null || value === undefined ? null : String(value);
											if (last !== null && last === cur) {
												dbg('Suppressing unchanged value for', name, ':', cur);
												return;
											}
											resources._lastValues[name] = cur;
										} catch (e) {
											dbg('value-comparison in object update failed', e);
										}

										const msg = JSON.stringify({ type: 'object_update', payload: { name, value } });
										callRemoteSocketSend(msg).catch((e: any) => dbg('object_update send failed', e));
									} catch (e) {
										dbg('Error in object update callback', e);
									}
								};
								result = await Promise.resolve((resources.appletApi.registerObjectUpdateListener as any)(name, cb));
								try {
									cb();
								} catch (e) {
									dbg('initial object_update send failed', e);
								}
							} catch (e) {
								dbg('registerObjectUpdateListener failed', e);
								result = { ok: false, error: String(e) };
							}
						} else {
							result = { ok: false, error: 'registerObjectUpdateListener not available' };
						}
					} else {
						if (resources.appletApi && typeof resources.appletApi.unregisterObjectUpdateListener === 'function') {
							try {
								result = await Promise.resolve((resources.appletApi.unregisterObjectUpdateListener as any)(name));
							} catch (e) {
								dbg('unregisterObjectUpdateListener failed', e);
								result = { ok: false, error: String(e) };
							}
						} else {
							result = { ok: false, error: 'unregisterObjectUpdateListener not available' };
						}
					}

					return JSON.stringify({ type: 'listen', id: cmd.id, payload: { result } });
				} catch (e) {
					dbg('Error in listen handler', e);
					return JSON.stringify({ type: 'error', id: cmd.id, payload: { message: String(e) } });
				}
			}
		};

		try {
			const h = handlers[command.type];
			if (h) {
				rmsg = await h(command);
			} else {
				dbg('No handler for command type', command.type);
				rmsg = JSON.stringify({ type: 'error', id: command.id, payload: { message: 'Unsupported command type' } });
			}
		} catch (e) {
			dbg('Handler error for command type', command.type, e);
			rmsg = JSON.stringify({ type: 'error', id: command.id, payload: { message: 'Handler execution failed' } });
		}

		return rmsg;
	};
}
