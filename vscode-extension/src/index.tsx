import React from 'react';
import { createRoot } from 'react-dom/client';
import GeoGebraWidget from './widget';
import { setupKernelResources } from '../../src/components/jupyterlab';

// Mount the widget into a given container id. This is the entry point
// that should be bundled and referenced from the webview HTML.
export function mountGeoGebra(containerId = 'root') {
  const container = document.getElementById(containerId);
  if (!container) {
    throw new Error('Container not found: ' + containerId);
  }
  const root = createRoot(container);
  try {
    // If the host injected server settings onto `window`, forward them
    // into the widget so it can initialize safely in webview mode.
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    const ss = (typeof window !== 'undefined' && (window as any).__GGBlab_ServerSettings) ? (window as any).__GGBlab_ServerSettings : null;
    root.render(<GeoGebraWidget elementId="ggb-element-debug" serverSettings={ss} />);
  } catch (e) {
    root.render(<GeoGebraWidget elementId="ggb-element-debug" />);
  }
}

// For convenience, auto-mount if `#root` is present (useful during dev)
if (typeof document !== 'undefined' && document.getElementById('root')) {
  try {
    // Enable verbose debug messages for development builds / webview.
    // Consumers may set this globally as well; only set if not already true.
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    if (!(window as any).ggblabDebugMessages) {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      (window as any).ggblabDebugMessages = true;
    }
  } catch (e) {
    // ignore
  }
  try {
    mountGeoGebra('root');
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('Auto-mount failed', e);
  }
}

export default mountGeoGebra;
