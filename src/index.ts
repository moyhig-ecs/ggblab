import {
  ILayoutRestorer,
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { 
  ICommandPalette,
  MainAreaWidget,
  WidgetTracker
} from '@jupyterlab/apputils';
import { ILauncher } from '@jupyterlab/launcher';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
//import { DockLayout } from '@lumino/widgets';

import { reactIcon } from '@jupyterlab/ui-components';
import { GeoGebraWidget } from './widget';

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
  requires: [ICommandPalette],
  optional: [ISettingRegistry, ILayoutRestorer, ILauncher],
  activate: (app: JupyterFrontEnd, palette: ICommandPalette, settingRegistry: ISettingRegistry | null, restorer: ILayoutRestorer | null, launcher: ILauncher | null) => {
    console.log('JupyterLab extension ggblab-0.0.1 is activated!');

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


    const command = CommandIDs.create;
    commands.addCommand(command, {
      caption: 'Create a new React Widget',
      label: 'React Widget',
      icon: args => (args['isPalette'] ? undefined : reactIcon),
      execute: (args: any) => {
        console.log('socketPath:', args['socketPath']);
        const content = new GeoGebraWidget({
          kernelId: args['kernelId'] || '', 
          commTarget: args['commTarget'] || '', 
          insertMode: args['insertMode'] || 'split-right',
          socketPath: args['socketPath'] || '',
          wsPort: args['wsPort'] || 8888,
        });
        const widget = new MainAreaWidget<GeoGebraWidget>({ content });
        widget.title.label = 'GeoGebra (' + (args['kernelId'] || '').substring(0, 8) + ')';
        widget.title.icon = reactIcon;
        app.shell.add(widget, 'main', {
          mode: args['insertMode'] || 'insert-right',
        });
      }
    });

    palette.addItem({
      command,
      category: "Tutorial",
    });

    let tracker = new WidgetTracker<MainAreaWidget<GeoGebraWidget>>({
      namespace: "ggblab",
    })
    if (restorer) {
      restorer.restore(tracker, {
        command,
        name: () => "ggblab",
      })
    }

    if (launcher) {
      launcher.add({
        command,
        category: "example",
        rank: 1,
      })
    }

  }
};

export default plugin;