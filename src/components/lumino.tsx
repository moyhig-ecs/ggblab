import { ReactWidget } from '@jupyterlab/ui-components';
import React from 'react';
import { Widget } from '@lumino/widgets';
import { Message } from '@lumino/messaging';
import GeoGebraApplet, { IGeoGebraAppletProps } from './widget';

/**
 * Lumino wrapper that renders the React `GeoGebraApplet` inside a widget.
 */
export class GeoGebraWidget extends ReactWidget {
	private props?: IGeoGebraAppletProps;

	constructor(props?: IGeoGebraAppletProps) {
		super();
		this.addClass('jp-ggblabWidget');
		this.props = props;
	}

	render(): React.ReactElement {
		return (
			<GeoGebraApplet
				kernelId={this.props?.kernelId}
				commTarget={this.props?.commTarget}
				insertMode={this.props?.insertMode}
				wsPort={this.props?.wsPort}
				socketPath={this.props?.socketPath}
				appName={this.props?.appName}
				bridgeMode={this.props?.bridgeMode}
				widgetManager={this.props?.widgetManager}
			/>
		);
	}

	protected onResize(msg: Widget.ResizeMessage): void {
		// Let the React component handle resize via window resize events
		window.dispatchEvent(new Event('resize'));
		super.onResize(msg);
	}

	protected onCloseRequest(msg: Message): void {
		window.dispatchEvent(new Event('close'));
		super.onCloseRequest(msg);
	}

	dispose(): void {
		super.dispose();
	}
}

export default GeoGebraWidget;
