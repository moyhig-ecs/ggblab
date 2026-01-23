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
    console.log(`JupyterLab extension ggblab-${pkg.version} is activated!`);

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('ggblab settings loaded:', settings.composite);
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

    const command = CommandIDs.create;
    commands.addCommand(command, {
      caption: 'Create a new React Widget',
      label: 'React Widget',
      icon: args => (args['isPalette'] ? undefined : reactIcon),
      execute: async (args: any) => {
        console.log('socketPath:', args['socketPath']);
        const content = new GeoGebraWidget({
          kernelId: args['kernelId'] || '',
          commTarget: args['commTarget'] || '',
          insertMode: args['insertMode'] || 'split-right',
          socketPath: args['socketPath'] || '',
          wsPort: args['wsPort'] || 8888
        });
        const widget = new MainAreaWidget<GeoGebraWidget>({ content });
        // make widget id unique so restorer can identify it later
        const idPart = (args['kernelId'] || '').substring(0, 8);
        widget.id = `ggblab-${idPart}`;
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
