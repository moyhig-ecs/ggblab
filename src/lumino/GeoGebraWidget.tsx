import { ReactWidget } from '@jupyterlab/ui-components';
import { Widget } from '@lumino/widgets';
import { Message } from '@lumino/messaging';
import React from 'react';
import GGAComponent, { IGGAWidgetProps } from '../components/GGAComponent';

/**
 * A GeoGebra Lumino Widget that wraps the pure `GGAComponent` React component.
 * This thin wrapper isolates Lumino-specific lifecycle methods so the React
 * component can be reused in other hosts (e.g. VS Code webviews).
 */
export class GeoGebraWidget extends ReactWidget {
  private props: IGGAWidgetProps | undefined;

  constructor(props?: IGGAWidgetProps) {
    super();
    this.addClass('jp-ggblabWidget');
    this.props = props;
  }

  render(): JSX.Element {
    return (
      <GGAComponent
        kernelId={this.props?.kernelId}
        commTarget={this.props?.commTarget}
        wsPort={this.props?.wsPort}
        socketPath={this.props?.socketPath}
        appName={this.props?.appName}
        widgetManager={this.props?.widgetManager}
      />
    );
  }

  protected onResize(msg: Widget.ResizeMessage): void {
    // Inform the component that layout changed; component listens to window resize
    window.dispatchEvent(new Event('resize'));
    super.onResize(msg);
  }

  protected onCloseRequest(msg: Message): void {
    // Trigger cleanup in the component via a window event
    window.dispatchEvent(new Event('close'));
    super.onCloseRequest(msg);
  }

  dispose(): void {
    super.dispose();
  }
}
