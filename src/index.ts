import {
  ILayoutRestorer,
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { MainAreaWidget, WidgetTracker } from '@jupyterlab/apputils';
// ILauncher removed: launcher integration is not used in this build
import { ISettingRegistry } from '@jupyterlab/settingregistry';
//import { DockLayout } from '@lumino/widgets';

import { reactIcon } from '@jupyterlab/ui-components';
import { GeoGebraWidget } from './widget';
import { ServerConnection, KernelConnection } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';

// Import package.json to reflect the package version in the UI log.
import pkg from '../package.json';

namespace CommandIDs {
  export const create = 'ggblab:create';
}

// const PANEL_CLASS = 'jp-ggblabPanel';

/**
 * Initialization data for the ggblab extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'ggblab:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  optional: [ISettingRegistry, ILayoutRestorer],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null,
    restorer: ILayoutRestorer | null
  ) => {
    console.debug(`JupyterLab extension ggblab-${pkg.version} is activated!`);

    // Expose a global registration helper so other extensions (for example
    // the jupyter-widgets manager) can notify us when a per-kernel
    // WidgetManager becomes available. This enables automatic integration
    // without patching third-party code: the widget manager can call
    // `window.__ggblab_register_widget_manager(kernelId, manager)` when ready.
    try {
      (window as any).__ggblab_widget_manager = (window as any).__ggblab_widget_manager || {};
      (window as any).__ggblab_register_widget_manager = (kernelId: string, manager: any) => {
        try {
          (window as any).__ggblab_widget_manager[kernelId] = manager;
          console.debug('ggblab: registered widgetManager for kernel', kernelId);
        } catch (e) {
          console.warn('ggblab: failed to register widgetManager', e);
        }
      };
    } catch (e) {
      console.warn('ggblab: unable to install widgetManager global registration', e);
    }

    // Best-effort attempt to detect if the official jupyter-widgets
    // extension is available in the host. If it is, try to wrap its
    // exported plugin(s) and observe the `activate` call so we can obtain
    // the per-kernel WidgetManager instance and call our registrar
    // `window.__ggblab_register_widget_manager(kernelId, manager)`
    // automatically. This uses only the module's public exports and
    // performs structural checks at runtime so it is robust across
    // versions.
    (async () => {
      try {
        const mod: any = await import('@jupyter-widgets/jupyterlab-manager');
        console.debug('ggblab: jupyter-widgets manager module is present');

        // The package may export a single plugin or an array of plugins.
        const candidates: any[] = Array.isArray(mod.default)
          ? mod.default
          : Array.isArray(mod)
          ? mod
          : [];

        for (const p of candidates) {
          if (!p || typeof p.activate !== 'function') {
            continue;
          }

          // Wrap the activate function so that when the widget-manager
          // plugin runs, we can inspect arguments for a manager instance
          // and register it with our global registrar. This is defensive
          // and will not change the plugin's behaviour otherwise.
          const origActivate = p.activate.bind(p);
          // eslint-disable-next-line @typescript-eslint/ban-ts-comment
          // @ts-ignore - runtime wrapping of third-party plugin
          p.activate = function (app: any, ...args: any[]) {
            const result = origActivate(app, ...args);

            try {
              // Look for a manager-like arg in the activate args.
              for (const a of args) {
                if (!a || typeof a !== 'object') {
                  continue;
                }

                // Heuristic: manager typically exposes `create_view` or
                // `display_view_for_model` or similar methods. We check a
                // small set of possibilities to find a likely manager.
                const isManager =
                  typeof a.create_view === 'function' ||
                  typeof a.display_view_for_model === 'function' ||
                  !!a._create_views_for_model;

                if (!isManager) {
                  // Some plugins pass a registry or other helpers; skip them.
                  continue;
                }

                const manager = a;

                // Attempt to determine a kernel id associated with this
                // manager. Different manager implementations expose the
                // session/kernel in different places; probe common paths.
                let kernelId = '';
                try {
                  kernelId = (
                    (manager.context && manager.context.session && manager.context.session.kernel && manager.context.session.kernel.id) ||
                    (manager.kernel && manager.kernel.id) ||
                    ''
                  );
                } catch (e) {
                  kernelId = '';
                }

                // If we have a kernel id, call the registrar immediately.
                if (kernelId && (window as any).__ggblab_register_widget_manager) {
                  try {
                    (window as any).__ggblab_register_widget_manager(kernelId, manager);
                    console.debug('ggblab: auto-registered widgetManager for kernel', kernelId);
                  } catch (e) {
                    console.warn('ggblab: failed to auto-register widgetManager', e);
                  }
                } else if (manager && manager.context && manager.context.session) {
                  // Otherwise, listen for kernel changes and register when
                  // the kernel becomes available or changes.
                  try {
                    const sess = manager.context.session;
                    // Some session implementations expose a `kernelChanged` signal
                    // or similar. Try to connect if present.
                    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                    // @ts-ignore - may not exist on all implementations
                    if (sess.kernelChanged && typeof sess.kernelChanged.connect === 'function') {
                      // Connect once to register when kernel is set.
                      const handler = (_sender: any, kernel: any) => {
                        try {
                          const kid = kernel ? kernel.id : '';
                          if (kid && (window as any).__ggblab_register_widget_manager) {
                            (window as any).__ggblab_register_widget_manager(kid, manager);
                            console.debug('ggblab: auto-registered widgetManager on kernelChanged for', kid);
                            // disconnect handler if possible
                            try {
                              // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                              // @ts-ignore
                              sess.kernelChanged.disconnect(handler);
                            } catch (e) {
                              /* ignore */
                            }
                          }
                        } catch (ee) {
                          /* ignore */
                        }
                      };
                      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                      // @ts-ignore
                      sess.kernelChanged.connect(handler);
                    }
                  } catch (e) {
                    /* ignore */
                  }
                }
              }
            } catch (e) {
              console.warn('ggblab: error while probing widget-manager activate args', e);
            }

            return result;
          };
        }
      } catch (e) {
        console.debug('ggblab: jupyter-widgets manager not available', e);
      }
    })();

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
    // @ts-expect-error TS2344: cross-package Lumino types can differ between
    // @jupyterlab/ui-components and @jupyterlab/apputils; ignore here and
    // prefer structural compatibility at runtime.
    const tracker = new WidgetTracker<MainAreaWidget<GeoGebraWidget>>({
      namespace: 'ggblab-tracker'
    });

    const command = CommandIDs.create;
    commands.addCommand(command, {
      caption: 'Create a new React Widget',
      label: 'React Widget',
      icon: args => (args['isPalette'] ? undefined : reactIcon),
      execute: async (args: any) => {
        console.debug('socketPath:', args['socketPath']);

        // Precompute widget id so we can detect and remove any existing panel
        const idPart = (args['kernelId'] || '').substring(0, 8);
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

        // Attempt to pass a WidgetManager if one was registered in a global
        // store by the widget manager integration. This allows optional
        // ipywidgets-based bridging when the environment provides a
        // WidgetManager for the target kernel. Fallback to `undefined`.
        const widgetManager: any = (window as any).__ggblab_widget_manager && (window as any).__ggblab_widget_manager[args['kernelId']] ? (window as any).__ggblab_widget_manager[args['kernelId']] : undefined;

        // Ensure a frontend-side comm handler is registered early for the
        // requested kernel so that comm_open from the kernel will be accepted
        // even if it happens before the widget fully mounts. Store any
        // accepted comms in a global map keyed by kernel id for the widget
        // instance to consume when it mounts.
        try {
          const baseUrl = PageConfig.getBaseUrl();
          const token = PageConfig.getToken();
          const settings = ServerConnection.makeSettings({ baseUrl, token, appendToken: true });
          const model = { name: 'python3', id: args['kernelId'] || '' };
          const earlyConn = new KernelConnection({ model, serverSettings: settings });
          // create global store if missing
          (window as any).__ggblab_comm_store = (window as any).__ggblab_comm_store || {};
          const store: any = (window as any).__ggblab_comm_store;
          // Register a no-op handler that saves the comm object for later use
          earlyConn.registerCommTarget(args['commTarget'] || 'ggblab-comm', (commOp: any, msg: any) => {
            try {
              store[args['kernelId']] = commOp;
              console.debug('Registered early frontend comm for kernel', args['kernelId']);
            } catch (e) {
              console.warn('Failed to store early frontend comm', e);
            }
          });
        } catch (e) {
          console.warn('Failed to register early frontend comm target', e);
        }

        const content = new GeoGebraWidget({
          kernelId: args['kernelId'] || '',
          commTarget: args['commTarget'] || '',
          insertMode: args['insertMode'] || 'split-right',
          socketPath: args['socketPath'] || '',
          wsPort: args['wsPort'] || 8888,
          widgetManager: widgetManager
        });
        // @ts-expect-error TS2344: cross-package Lumino types can differ between
        // @jupyterlab/ui-components and @jupyterlab/apputils; ignore here and
        // prefer structural compatibility at runtime.
        const widget = new MainAreaWidget<GeoGebraWidget>({ content });
        // make widget id unique so restorer can identify it later
        widget.id = widgetId;
        widget.title.label = `GeoGebra (${idPart})`;
        widget.title.icon = reactIcon;

        // register with tracker so state will be saved for restoration
        try {
          await tracker.add(widget);
        } catch (e) {
          console.warn('Failed to add widget to tracker:', e);
        }

        app.shell.add(widget, 'main', {
          mode: args['insertMode'] || 'split-right'
        });
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
        command,
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
          const kernelId =
            p.kernelId ||
            (id.startsWith('ggblab-') ? id.slice('ggblab-'.length) : '');
          return {
            kernelId,
            commTarget: p.commTarget || '',
            socketPath: p.socketPath || '',
            wsPort: p.wsPort || 8888,
            insertMode: p.insertMode || 'split-right'
          } as any;
        }
      });
    }

    // Launcher integration removed: no launcher item will be added.
  }
};

export default plugin;
