// comm helper functions inlined from kernel_comm.ts to reduce indirection
import React, { useEffect, useRef /*, useState */ } from 'react';
//import MetaTags from 'react-meta-tags';

import setupKernelResources from './jupyterlab';
import { registerWidgetCommTargets } from '../widgets';
import { DockLayout } from '@lumino/widgets';
import type { WidgetManagerType } from '../widgets';
// widgetManager registration is handled inside `setupKernelResources`
import type { IGeoGebraAppletApi, IGeoGebraResources } from '../types';
import { injectGeoGebraApplet } from '../shared/createApplet';
import { isArrayOfArrays, createProcessCommandMessage } from '../shared/geoGebraCommon';
import setupAppletOnLoadCommon from '../shared/appletOnLoadCommon';

// Global typings are provided in src/declarations.d.ts; avoid duplicate declarations here.

// Debug logging helper controlled from the browser console.
// Enable message logging in the JS console by running:
//   window.ggblabDebugMessages = true
function dbg(...args: any) {
  if ((window as any).ggblabDebugMessages) {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
}

/**
 * React component for a GeoGebra.
 *
 * @returns The React component
 */
const GeoGebraApplet = (props: IGeoGebraAppletProps): JSX.Element => {
  // const [kernels, setKernels] = React.useState<any[]>([]);
  const widgetRef = useRef<HTMLDivElement>(null);

  dbg('Component props: ', props.kernelId, props.commTarget, props.socketPath, props.wsPort);

  const elementId = 'ggb-element-' + (props?.kernelId || '').substring(0, 8);
  dbg('Element ID:', elementId);

  let applet: any = null;

  useEffect(() => {
    class Resources implements IGeoGebraResources {
      kernelId: string;
      commTarget: string;
      socketPath: string | null;
      wsPort: number;
      kernel2: any = null;
      kernelManager: any = null;
      kernelConn: any = null;
      comm: any = null;
      widgetComm: any = null;
      appletApi: IGeoGebraAppletApi | null = null;
      appletStyleObserver: MutationObserver | null = null;
      unregisterWidgetCommTargets: (() => void) | null = null;
      injectCleanup: (() => void) | null = null;
      observer: MutationObserver | null = null;
      resizeHandler: (() => void) | null = null;
      closeHandler: (() => void) | null = null;
      metaViewport: HTMLMetaElement | null = null;
      scriptTag: HTMLScriptElement | null = null;
      _lastValues: { [name: string]: string | null } = {};

      constructor(kernelId: string, commTarget: string, socketPath: string | null, wsPort: number) {
        this.kernelId = kernelId;
        this.commTarget = commTarget;
        this.socketPath = socketPath;
        this.wsPort = wsPort;
      }

      async dispose() {
        try {
          if (this.comm) {
            try { this.comm.close?.(); } catch (err) { dbg('Error closing comm during cleanup', err); }
            this.comm = null;
          }
          if (this.kernel2) {
            try { await this.kernel2.shutdown(); } catch (err) { dbg('Error shutting down kernel2 during cleanup', err); }
            this.kernel2 = null;
          }
          this.widgetComm = null;
          this.appletApi = null;
          if (this.kernelManager) {
            try { await this.kernelManager.shutdown?.(); } catch (err) { dbg('Error shutting down kernelManager', err); }
            this.kernelManager = null;
          }
          if (this.observer) { try { this.observer.disconnect(); } catch (err) { dbg('Error disconnecting observer', err); } this.observer = null; }
          if (this.appletStyleObserver) { try { this.appletStyleObserver.disconnect(); } catch (err) { dbg('Error disconnecting appletStyleObserver', err); } this.appletStyleObserver = null; }
          if (this.resizeHandler) { try { window.removeEventListener('resize', this.resizeHandler); } catch (err) { dbg('Error removing resize handler', err); } this.resizeHandler = null; }
          if (this.closeHandler) { try { window.removeEventListener('close', this.closeHandler); } catch (err) { dbg('Error removing close handler', err); } this.closeHandler = null; }
          if (this.metaViewport && this.metaViewport.parentNode) { this.metaViewport.parentNode.removeChild(this.metaViewport); this.metaViewport = null; }
          if (this.scriptTag && this.scriptTag.parentNode) { this.scriptTag.parentNode.removeChild(this.scriptTag); this.scriptTag = null; }
          try { this.unregisterWidgetCommTargets?.(); this.unregisterWidgetCommTargets = null; try { this.injectCleanup?.(); } catch (err) { dbg('Error during inject cleanup', err); } this.injectCleanup = null; } catch (err) { dbg('Error unregistering widget comm targets', err); }
        } catch (err) { console.error('Error during resources.dispose():', err); }
      }
    }

    const resources: IGeoGebraResources = new Resources(props.kernelId || '', props.commTarget || '', props.socketPath || null, props.wsPort || 8888);

    dbg('useEffect: created Resources, about to run setup IIFE', { kernelId: props.kernelId, commTarget: props.commTarget }, []);

    (async () => {
      dbg('IIFE: entered - calling setupKernelResources');
      const { callRemoteSocketSend, makeIncomingHandler } = await setupKernelResources(resources, props, dbg);
      const processCommandMessage = createProcessCommandMessage(resources, callRemoteSocketSend, isArrayOfArrays, dbg);
      const handleIncomingCommMessage = makeIncomingHandler(processCommandMessage);

      try {
        if (props.widgetManager) {
          dbg('widgetManager present; skipping raw jupyter.widget comm registration');
        } else {
          const opts = { callRemoteSocketSend, kernel2: resources.kernel2, socketPath: resources.socketPath, wsUrl: `ws://localhost:${resources.wsPort}/`, getAppletApi: () => resources.appletApi, isArrayOfArrays: isArrayOfArrays, dbg };
          const unregisterFn = registerWidgetCommTargets(resources.kernelConn, opts as any);
          resources.unregisterWidgetCommTargets = unregisterFn;
        }
      } catch (e: any) { dbg('Widget comm target registration skipped or failed', e); }

      async function ggbOnLoad(api: any) {
        dbg('GeoGebra applet loaded:', api);
        try { await setupAppletOnLoadCommon(api, resources, callRemoteSocketSend, handleIncomingCommMessage, dbg); } catch (e) { dbg('setupAppletOnLoadCommon failed', e); }
        resources.resizeHandler = function () {
          try {
            const wrapperDiv = document.getElementById(elementId) as HTMLElement | null;
            const target = wrapperDiv?.parentElement ?? wrapperDiv;
            if (!target) return;
            const rect = target.getBoundingClientRect();
            const width = Math.max(1, Math.floor(rect.width));
            const height = Math.max(1, Math.floor(rect.height));
            try { api.recalculateEnvironments(); } catch (e) { dbg('recalculateEnvironments failed', e); }
            try { api.setSize(width, height); } catch (e) { dbg('setSize failed', e); }
          } catch (e) { dbg('resizeHandler error', e); }
        };
        window.addEventListener('resize', resources.resizeHandler);
        resources.resizeHandler();
      }

      try {
        const wrapperDiv = widgetRef.current ?? document.getElementById(elementId);
        const targetForSize = (wrapperDiv as HTMLElement | null)?.parentElement ?? (wrapperDiv as HTMLElement | null);
        let measuredWidth = 800;
        let measuredHeight = 600;
        try { if (targetForSize) { const rect = (targetForSize as HTMLElement).getBoundingClientRect(); measuredWidth = Math.max(1, Math.floor(rect.width)); measuredHeight = Math.max(1, Math.floor(rect.height)); } } catch (e) { dbg('Failed to measure container for initial size, falling back to defaults', e); }

        const { appletPromise, scriptTag, metaViewport, cleanup } = injectGeoGebraApplet({ elementId, appName: props?.appName || 'suite', width: measuredWidth, height: measuredHeight, scaleContainerClass: undefined, allowUpscale: true, appletOnLoad: ggbOnLoad, dbg });
        resources.scriptTag = scriptTag;
        resources.metaViewport = metaViewport;
        resources.injectCleanup = cleanup || null;

        appletPromise.then((a: any) => {
          applet = a;
          try {
            const api = a;
            const wrapperDiv2 = widgetRef.current ?? document.getElementById(elementId);
            const target2 = wrapperDiv2?.parentElement ?? wrapperDiv2;
            let w = measuredWidth;
            let h = measuredHeight;
            try { if (target2) { const rect2 = (target2 as HTMLElement).getBoundingClientRect(); w = Math.max(1, Math.floor(rect2.width)); h = Math.max(1, Math.floor(rect2.height)); } } catch (e) { dbg('Failed to re-measure container for sizing', e); }
            try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
            try { api.setSize(w, h); dbg('Applied initial applet size', w, h); } catch (e) { dbg('api.setSize failed', e); }
            try { const appletNode = document.getElementById('ggbApplet-' + elementId); if (appletNode) { (appletNode as HTMLElement).style.width = '100%'; (appletNode as HTMLElement).style.height = '100%'; (appletNode as HTMLElement).style.maxWidth = '100%'; (appletNode as HTMLElement).style.transform = 'none'; (appletNode as HTMLElement).style.transformOrigin = '0 0'; } } catch (e) { dbg('Failed to override applet DOM styles', e); }
            setTimeout(() => { try { api.setSize(w, h); dbg('Reapplied size (250ms)'); } catch (e) { dbg('reapply failed', e); } }, 250);
            setTimeout(() => { try { api.setSize(w, h); dbg('Reapplied size (1000ms)'); } catch (e) { dbg('reapply failed', e); } }, 1000);
            try { const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null; if (appletNode) { const observer = new MutationObserver(mutations => { try { const rect3 = (appletNode.parentElement ?? appletNode).getBoundingClientRect(); const ww = Math.max(1, Math.floor(rect3.width)); const hh = Math.max(1, Math.floor(rect3.height)); try { api.setSize(ww, hh); } catch (e) { /* ignore */ } try { appletNode.style.transform = 'none'; appletNode.style.width = '100%'; appletNode.style.height = '100%'; } catch (e) { /* ignore */ } } catch (e) { dbg('appletStyleObserver handler error', e); } }); observer.observe(appletNode, { attributes: true, attributeFilter: ['style', 'class'], subtree: false }); resources.appletStyleObserver = observer; } } catch (e) { dbg('Failed to create appletStyleObserver', e); }
          } catch (e) { dbg('Error applying size to applet', e); }
        }).catch((e: any) => dbg('Applet creation failed', e));
      } catch (e) { dbg('injectGeoGebraApplet failed', e); }
    })();

    return () => {
      if (resources.resizeHandler) { window.removeEventListener('resize', resources.resizeHandler); resources.resizeHandler = null; }
      if (resources.closeHandler) { window.removeEventListener('close', resources.closeHandler); resources.closeHandler = null; }
      if (resources.observer) { try { resources.observer.disconnect(); } catch (e) { console.error(e); } resources.observer = null; }
      try { resources.unregisterWidgetCommTargets?.(); resources.unregisterWidgetCommTargets = null; } catch (e) { dbg('Error unregistering widget comm targets', e); }
      if (resources.metaViewport && resources.metaViewport.parentNode) { resources.metaViewport.parentNode.removeChild(resources.metaViewport); resources.metaViewport = null; }
      if (resources.scriptTag && resources.scriptTag.parentNode) { resources.scriptTag.parentNode.removeChild(resources.scriptTag); resources.scriptTag = null; }
      if (applet) { try { dbg('Cleaning up GeoGebra applet.'); const winApplet = (window as any).ggbApplet || applet; try { winApplet.remove(); } catch (e) { dbg('Error removing applet instance', e); } } catch (e) { dbg('Error while removing GeoGebra applet', e); } applet = null; delete (window as any).ggbApplet; }
      (async () => { try { await resources.dispose(); } catch (e) { console.error('Error during cleanup:', e); } })();
    };
  }, []);

  return <div id={elementId} ref={widgetRef} style={{ width: '100%', height: '100%' }}></div>;
};

export interface IGeoGebraAppletProps {
  kernelId?: string;
  commTarget?: string;
  insertMode?: DockLayout.InsertMode;
  wsPort?: number;
  socketPath?: string;
  appName?: string;
  widgetManager?: WidgetManagerType;
}

export default GeoGebraApplet;
