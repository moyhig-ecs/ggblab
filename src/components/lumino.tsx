// Minimal lumino wrapper: re-export the `GeoGebraWidget` from the applet
// copy so other imports succeed during the staged refactor.

import { ReactWidget } from '@jupyterlab/ui-components';
import React from 'react';
import { Widget } from '@lumino/widgets';
import { Message } from '@lumino/messaging';
import GGAComponent, { IGGAWidgetProps } from './GeoGebraApplet';

/**
 * Lumino wrapper: provides `GeoGebraWidget` as a `ReactWidget` that
 * renders the host-agnostic `GGAComponent`.
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

