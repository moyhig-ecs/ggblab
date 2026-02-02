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
import {
  createWidgetManager,
  registerGlobalGGBlabCommTargets
} from './widgetManager';

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

    // Pragmatic global registration (option B): register a `jupyter.ggblab`
    // comm target on all currently running kernels so kernels that open
    // comms to that target will be delivered to the front-end. Keep the
    // returned unregister function so we can clean up on unload.
    let _unregisterGlobalGGBlab: (() => void) | null = null;
    registerGlobalGGBlabCommTargets(app)
      .then(unreg => {
        _unregisterGlobalGGBlab = unreg;
      })
      .catch(e =>
        console.warn('Failed to register global ggblab comm targets', e)
      );

    // Ensure we clean up registrations when the page unloads to avoid
    // leaving dangling front-end KernelConnection objects.
    window.addEventListener('beforeunload', () => {
      _unregisterGlobalGGBlab?.();
    });

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
    // @ts-ignore: cross-package Lumino types may differ in consumers
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

        // Centralized widget-manager factory (currently returns `undefined`)
        // to avoid interfering with ipywidgets. See src/widgetManager.ts
        // for future changes to this behavior.
        const widgetManager = createWidgetManager();

        const content = new GeoGebraWidget({
          kernelId: args['kernelId'] || '',
          commTarget: args['commTarget'] || '',
          insertMode: args['insertMode'] || 'split-right',
          socketPath: args['socketPath'] || '',
          wsPort: args['wsPort'] || 8888,
          widgetManager: widgetManager
        });
        // @ts-ignore: cross-package Lumino Title/Layout type mismatch
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
