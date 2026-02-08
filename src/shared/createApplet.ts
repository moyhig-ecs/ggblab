export interface IInjectOptions {
	elementId: string;
	appName?: string;
	width?: number;
	height?: number;
	scaleContainerClass?: string;
	allowUpscale?: boolean;
	appletOnLoad?: ((api: any) => void) | null;
	scriptId?: string;
	metaId?: string;
	dbg?: (...args: any[]) => void;
}

export interface IInjectResult {
	appletPromise: Promise<any>;
	scriptTag: HTMLScriptElement | null;
	metaViewport: HTMLMetaElement | null;
	cleanup?: () => void;
}

export function injectGeoGebraApplet(opts: IInjectOptions): IInjectResult {
	const {
		elementId,
		appName = 'suite',
		width = 800,
		height = 600,
		scaleContainerClass = 'applet-wrapper',
		allowUpscale = false,
		appletOnLoad = null,
		scriptId = 'ggblab-deployggb-script',
		metaId = 'ggblab-viewport-meta',
		dbg = () => {}
	} = opts;

	let scriptTag: HTMLScriptElement | null = null;
	let metaViewport: HTMLMetaElement | null = null;
	let createdScript = false;
	let createdMeta = false;
	let createdApplet: any = null;

	// Ensure viewport meta exists
	const existingMeta = document.getElementById(metaId) as HTMLMetaElement | null;
	if (existingMeta) {
		metaViewport = existingMeta;
	} else {
		metaViewport = document.createElement('meta');
		metaViewport.id = metaId;
		metaViewport.name = 'viewport';
		metaViewport.content = 'width=device-width, initial-scale=1';
		document.head.appendChild(metaViewport);
	}

	const existingScript = document.getElementById(scriptId) as HTMLScriptElement | null;
	dbg('injectGeoGebraApplet: script lookup', { existingScript: !!existingScript, scriptId });

	const createAppletInternal = () => {
		const params: any = {
			id: 'ggbApplet-' + elementId,
			appName,
			width,
			height,
			showToolBar: true,
			showAlgebraInput: false,
			showMenuBar: true,
			autoHeight: true,
			allowUpscale
		};
		// Only include scaleContainerClass if a non-empty value was provided.
		// When omitted, the applet will use explicit width/height instead of
		// applying container-scaling which preserves aspect ratio and can leave
		// vertical letterbox space.
		if (scaleContainerClass) {
			params.scaleContainerClass = scaleContainerClass;
		}
		if (appletOnLoad) {
			params.appletOnLoad = appletOnLoad;
		}
		const applet = new (window as any).GGBApplet(params, true);
		applet.inject(elementId);
		(window as any).ggbApplet = applet;
		return applet;
	};

	const appletPromise = new Promise<any>((resolve, reject) => {
		try {
			if (existingScript) {
				scriptTag = existingScript;
				if ((window as any).GGBApplet) {
					dbg('GGBApplet already on window; creating applet immediately');
					const a = createAppletInternal();
					createdApplet = a;
					resolve(a);
				} else {
					dbg('Attaching load listener to existing script');
					const listener = () => {
						try {
							const a = createAppletInternal();
							createdApplet = a;
							resolve(a);
						} catch (e) {
							reject(e);
						}
					};
					existingScript.addEventListener('load', listener, { once: true });
				}
			} else {
				scriptTag = document.createElement('script');
				scriptTag.id = scriptId;
				scriptTag.src = 'https://cdn.geogebra.org/apps/deployggb.js';
				scriptTag.async = true;
				scriptTag.onload = () => {
					try {
						const a = createAppletInternal();
						createdApplet = a;
						resolve(a);
					} catch (e) {
						reject(e);
					}
				};
				scriptTag.onerror = e => {
					reject(new Error('Failed to load deployggb.js'));
				};
				createdScript = true;
				document.body.appendChild(scriptTag);
			}
		} catch (e) {
			reject(e);
		}
	});

	const cleanup = () => {
		try {
			if (createdApplet) {
				try {
					createdApplet.remove();
				} catch (e) {
					/* ignore */
				}
				createdApplet = null;
			}
			if ((window as any).ggbApplet) {
				try {
					(window as any).ggbApplet.remove();
				} catch (e) {
					/* ignore */
				}
				try {
					delete (window as any).ggbApplet;
				} catch (e) {
					/* ignore */
				}
			}
			if (createdScript && scriptTag && scriptTag.parentNode) {
				scriptTag.parentNode.removeChild(scriptTag);
				scriptTag = null;
			}
			if (createdMeta && metaViewport && metaViewport.parentNode) {
				metaViewport.parentNode.removeChild(metaViewport);
				metaViewport = null;
			}
		} catch (e) {
			dbg('Error during inject cleanup', e);
		}
	};

	// mark whether we created the meta tag (existingMeta was null)
	createdMeta = existingMeta ? false : true;

	return { appletPromise, scriptTag, metaViewport, cleanup };
}

export default injectGeoGebraApplet;
