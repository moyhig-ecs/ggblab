import { ILayoutRestorer, JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { MainAreaWidget, WidgetTracker, ICommandPalette } from '@jupyterlab/apputils';
import { ILauncher } from '@jupyterlab/launcher';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
//import { DockLayout } from '@lumino/widgets';

import { LabIcon } from '@jupyterlab/ui-components';
import { GeoGebraWidget } from './widget';
import { createWidgetManager  } from './widgets';
import geogebraSvg from '../style/Geogebra.svg';

export const geogebraIcon = new LabIcon({ name: 'ggblab:geogebra', svgstr: geogebraSvg });

/**
 * Legacy/compatibility note:
 * Historically the plugin created a `widgetManager` inline in this
 * module during activation. The implementation has been moved to
 * `src/widgetManager.ts` to centralize widget-manager logic and to
 * allow different manager implementations (or `undefined`) to be
 * swapped in. We keep a tiny forwarding helper here as a documented
 * placeholder so future maintainers can see the original intent and
 * have a single place to adapt call-sites if needed.
 */
export function createWidgetManagerLegacy() {
	// Forward to the real factory in widgetManager.ts for now.
	return createWidgetManager();
}

// Import package.json to reflect the package version in the UI log.
import pkg from '../package.json';
// import { registerWidgetManagerPlugin } from './widgets';
import { registerWidgetManagerPlugin, registerGlobalGGBlabCommTargets } from './widgets';

namespace CommandIDs {
	export const create = 'ggblab:create';
	export const create_from_bridge = 'ggblab:create_from_bridge';
}

// const PANEL_CLASS = 'jp-ggblabPanel';

/**
 * Initialization data for the ggblab extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
	id: 'ggblab:plugin',
	description: 'A JupyterLab extension.',
	autoStart: true,
	optional: [ISettingRegistry, ILayoutRestorer, ILauncher, ICommandPalette],
	activate: (app: JupyterFrontEnd, settingRegistry: ISettingRegistry | null, restorer: ILayoutRestorer | null, launcher: ILauncher | null, palette: ICommandPalette | null) => {
		console.debug(`JupyterLab extension ggblab-${pkg.version} is activated!`);

		// // Global flags to avoid duplicate bridge starts / widget creation
		// if (!(window as any).__ggblab_bridge_started) {
		// 	(window as any).__ggblab_bridge_started = false;
		// }
		// if (!(window as any).__ggblab_last_created_time) {
		// 	(window as any).__ggblab_last_created_time = 0;
		// }

		// Pragmatic global registration: register a `jupyter.ggblab` comm
		// target on all currently running kernels so kernels that open
		// comms to that target will be delivered to the front-end. Keep the
		// returned unregister function so we can clean up on unload.
		let _unregisterGlobalGGBlab: (() => void) | null = null;
		try {
			console.warn('Registering global ggblab comm targets for all kernels');
			registerGlobalGGBlabCommTargets(app)
				.then(unreg => {
					_unregisterGlobalGGBlab = unreg;
				})
				.catch(e => console.warn('Failed to register global ggblab comm targets', e));
		} catch (e) {
			console.warn('registerGlobalGGBlabCommTargets threw', e);
		}

		// Ensure we cleanup registrations on page unload so KernelConnections
		// are not left dangling. Reference `_unregisterGlobalGGBlab` here so
		// TypeScript recognizes the variable as used.
		try {
			window.addEventListener('beforeunload', () => {
				try {
					_unregisterGlobalGGBlab && _unregisterGlobalGGBlab();
				} catch (_e) {
					// ignore
				}
			});
		} catch (e) {
			// ignore environments where addEventListener isn't available
		}

		// Small global helper so comm handlers running in the kernelConn scope
		// can ask the frontend to create/open a ggblab widget for a kernel id.
		try {
			(window as any).__ggblab_create_widget_for_kernel = async function (kernelId: string, opts?: any) {
				try {
					return await app.commands.execute('ggblab:create', Object.assign({ kernelId, commTarget: 'jupyter.ggblab' }, opts || {}));
				} catch (e) {
					console.warn('ggblab: __ggblab_create_widget_for_kernel failed', e);
				}
			};
		} catch (e) {
			console.debug('ggblab: failed to define __ggblab_create_widget_for_kernel', e);
		}

		// // Ensure we clean up registrations when the page unloads to avoid
		// // leaving dangling front-end KernelConnection objects.
		// window.addEventListener('beforeunload', () => {
		// 	_unregisterGlobalGGBlab?.();
		// });

		if (settingRegistry) {
			settingRegistry
				.load(plugin.id)
				.then(settings => {
					console.debug('ggblab settings loaded:', settings.composite);
				})
				.catch(reason => {
					console.error('Failed to load settings for ggblab.', reason);
				});
		}

		const { commands } = app;

		// Tracker for created GeoGebra widgets so they can be restored after reload
		const tracker = new WidgetTracker<MainAreaWidget<GeoGebraWidget>>({
			namespace: 'ggblab-tracker'
		});

		const createCommand = CommandIDs.create;
		const bridgeCommand = CommandIDs.create_from_bridge;
		commands.addCommand(createCommand, {
			caption: 'Create a new GeoGebra Widget',
			label: 'GeoGebra Widget',
			icon: geogebraIcon,
			execute: async (args: any) => {
				console.debug('socketPath:', args['socketPath']);

				// Normal create flow (assume comm_bridge already running or kernel supplied)

				// Precompute widget id so we can detect and remove any existing panel.
				// If no kernelId is provided (launcher case), generate a short
				// unique suffix so widgets are tracked correctly instead of
				// colliding on the empty id.
				const rawId = (args && args['kernelId']) || (`no-kernel-${Date.now().toString(36).slice(-6)}`);
				const idPart = String(rawId).substring(0, 8);
				const widgetId = `ggblab-${idPart}`;

				// If a widget with the same id exists, close and remove it first.
				try {
					const existing = (tracker as any).find((w: any) => w.id === widgetId);
					if (existing) {
						try {
							existing.close();
						} catch (e) {
							console.warn('Failed to close existing widget:', e);
						}
						try {
							// tracker.remove may return a Promise
							await (tracker as any).remove(existing);
						} catch (e) {
							// non-fatal
							console.warn('Failed to remove existing widget from tracker:', e);
						}
					}
				} catch (e) {
					// If tracker API differs, ignore and continue
				}

				// Centralized widget-manager factory (currently returns `undefined`)
				// to avoid interfering with ipywidgets. See src/widgetManager.ts
				// for future changes to this behavior.
				const widgetManager = createWidgetManager();

				// console.log('Creating GeoGebraWidget with args:', args, 'and widgetManager:', widgetManager);
				const content = new GeoGebraWidget({
					kernelId: args['kernelId'] || '',
					commTarget: args['commTarget'] || '',
					insertMode: args['insertMode'] || 'split-right',

					socketPath: args['socketPath'] || '',
					appName: args['appName'] || 'suite',
					wsPort: args['wsPort'] || 8888,
					widgetManager: widgetManager
				});


				const widget = new MainAreaWidget<GeoGebraWidget>({ content });
				// make widget id unique so restorer can identify it later
				widget.id = widgetId;
				widget.title.label = `GeoGebra (${idPart})`;
				widget.title.icon = geogebraIcon;

				// register with tracker so state will be saved for restoration
				try {
					await tracker.add(widget);
					// // mark creation time so bridge-start logic can detect kernel-driven creation
					// (window as any).__ggblab_last_created_time = Date.now();
				} catch (e) {
					console.warn('Failed to add widget to tracker:', e);
				}

				app.shell.add(widget, 'main', {
					mode: args['insertMode'] || 'split-right'
				});
			}
		});
		// Command that starts the comm_bridge via a background console and then
		// delegates to the normal create command. Launcher tiles should invoke
		// this command so the backend proxy is started automatically.
		commands.addCommand(bridgeCommand, {
			caption: 'Create ggblab widget (start bridge)',
			label: 'GeoGebra (comm_bridge)',
			icon: geogebraIcon,
			execute: async (args: any) => {
				// If bridge already started, skip injection.
				// if (!(window as any).__ggblab_bridge_started) {
				app.commands.execute('console:create', {
					kernelPreference: { 
						name: 'python3',
						shutdownOnDispose: true,
					},
					name: 'ggblab-bridge-console',
					path: 'ggblab_console.ipynb',
					activate: false
				}).then(() => {
					new Promise(res => setTimeout(res, 1000)).then(() => {
					// retry injecting a few times; some consoles take a moment to be ready
						const injectCode = "from ggblab_core import AppletInjector\ninfo = AppletInjector.start_proxy_mode()\n";
						// let injected = false;
						// for (let attempt = 0; attempt < 6 && !injected; attempt++) {
						app.commands.execute('console:inject', {
							path: 'ggblab_console.ipynb',
							code: injectCode,
							activate: false
						}).finally(() => {
							// injected = true;
							// (window as any).__ggblab_bridge_started = true;
							console.debug('ggblab: started comm_bridge via console injection (bridge)');
						});
					});
				}).catch(e => {
					console.warn('ggblab: failed to start comm_bridge via console injection (bridge)', e);
				}).finally(() => {
					// (window as any).__ggblab_bridge_started = true;
					console.debug('ggblab: marked bridge as started (bridge command)');
				});
					
				// // Wait briefly to see if the kernel-side auto-creates a widget.
				// const startWait = Date.now();
				// let createdByKernel = false;
				// for (let i = 0; i < 10; i++) {
				// 	if ((window as any).__ggblab_last_created_time > startWait) {
				// 		createdByKernel = true;
				// 		break;
				// 	}
				// 	// wait 100ms
				// 	await new Promise(res => setTimeout(res, 100));
				// }
				// if (createdByKernel) {
				// 	console.debug('ggblab: widget created by kernel-side bridge; skipping frontend create');
				// 	return;
				// }

				// // No kernel-created widget detected; create one from the frontend.
				// try {
				// 	await commands.execute(createCommand, args || {});
				// } catch (e) {
				// 	console.warn('ggblab: failed to execute create after bridge start', e);
				// }
			}
		});

		// palette.addItem({
		//   command,
		//   category: "Tutorial",
		// });

		if (restorer) {
			// Note: we may in future support restoring the applet's internal
			// state from an autosave (e.g. localStorage or a persistent store).
			// That would involve fetching a saved XML/Base64 snapshot and
			// passing it through `args` or a dedicated `initialXml` prop so the
			// recreated widget can rehydrate the GeoGebra applet.
			restorer.restore(tracker, {
				command: createCommand,
				// use widget.id as the saved name so it is unique per widget
				name: widget => widget.id,
				// reconstruct args (kernelId) from the saved widget id so the
				// command can recreate the widget with the same kernel association
				args: widget => {
					// Prefer to read the original creation props from the widget content
					const content: any = (widget && (widget as any).content) || {};
					const p = content.props || {};
					// Fallback to reconstructing kernelId from the widget id if not present
					const id = widget.id || '';
					const kernelId = p.kernelId || (id.startsWith('ggblab-') ? id.slice('ggblab-'.length) : '');
					return {
						kernelId,
						commTarget: p.commTarget || '',
						socketPath: p.socketPath || '',

						appName: p.appName || 'suite',
						wsPort: p.wsPort || 8888,
						insertMode: p.insertMode || 'split-right'
					} as any;
				}
			});
		}

		// If a Launcher was provided, add a launcher tile so users can
		// create a ggblab widget (and start the comm_bridge via console
		// injection when launched from the launcher).
		if (launcher) {
			launcher.add({
				command: bridgeCommand,
				category: 'Other',
				rank: 1,
				args: { launcherIconUrl: geogebraSvg }
			});
		}

		// if (palette) {
		// 	palette.addItem({ command: bridgeCommand, category: 'ggblab' });
		// }
	}
};

// Export both the main plugin and the manager-detection plugin so JupyterLab
// will activate the manager probe and allow `setWidgetManager` to be called
// when the jupyter-widgets manager becomes available.
export default [plugin, registerWidgetManagerPlugin];
