/* eslint-disable */
import React, { useEffect, useRef } from 'react';
import { injectGeoGebraApplet } from '../../src/shared/createApplet';
import setupKernelResources from '../../src/components/jupyterlab';
import { registerWidgetCommTargets } from '../../src/widgets';
import { isArrayOfArrays, createProcessCommandMessage } from '../../src/shared/geoGebraCommon';
import setupAppletOnLoadCommon from '../../src/shared/appletOnLoadCommon';

export interface GeoGebraWidgetProps {
  elementId?: string;
  appName?: string;
  width?: number;
  height?: number;
  // VS Code webview will provide these
  kernelId?: string;
  commTarget?: string;
  socketPath?: string;
  wsPort?: number;
  serverSettings?: any;
}

export const GeoGebraWidget: React.FC<GeoGebraWidgetProps> = ({
  elementId = 'ggb-element-debug',
  appName = 'suite',
  width = undefined,
  height = undefined,
  kernelId = '',
  commTarget = 'jupyter.ggblab',
  socketPath = '',
  wsPort = 8888,
  serverSettings = null
}) => {
  const widgetRef = useRef<HTMLDivElement | null>(null);
  const initializedRef = useRef<boolean>(false);
  const resourcesRef = useRef<any | null>(null);

  function dbg(...args: any[]) {
    // Local console output when enabled
    if ((window as any).ggblabDebugMessages) {
      // eslint-disable-next-line no-console
      console.log(...args);
    }
    // If running inside a VS Code webview, forward debug messages to the
    // extension host so they appear in the `ggblab` OutputChannel.
    try {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      if (typeof (window as any).acquireVsCodeApi === 'function') {
        try {
          const vscode = (window as any).acquireVsCodeApi();
          const text = args.map((a: any) => {
            try { return typeof a === 'string' ? a : JSON.stringify(a); } catch (e) { return String(a); }
          }).join(' ');
          vscode.postMessage({ type: 'dbg', level: 'debug', text });
        } catch (e) {
          // ignore
        }
      }
    } catch (e) { /* ignore */ }
  }

  useEffect(() => {
    // Resources bag (lightweight)
    class Resources {
      kernelId: string;
      commTarget: string;
      socketPath: string | null;
      wsPort: number;
      kernel2: any = null;
      kernelManager: any = null;
      kernelConn: any = null;
      comm: any = null;
      widgetComm: any = null;
      appletApi: any = null;
      // unregister function returned by `registerWidgetCommTargets`
      unregisterWidgetCommTargets: (() => void) | null = null;
      injectCleanup: (() => void) | null = null;
      observer: MutationObserver | null = null;
      appletStyleObserver: MutationObserver | null = null;
      styleTag: HTMLStyleElement | null = null;
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
          try { this.comm?.close?.(); } catch (e) { dbg('Error closing comm', e); }
          try { await this.kernel2?.shutdown?.(); } catch (e) { dbg('Error shutting down kernel2', e); }
          this.widgetComm = null;
          this.appletApi = null;
          try { await this.kernelManager?.shutdown?.(); } catch (e) { dbg('Error shutting down kernelManager', e); }
          try { this.observer?.disconnect(); } catch (e) { dbg('Error disconnecting observer', e); }
          if (this.resizeHandler) { try { window.removeEventListener('resize', this.resizeHandler); } catch (e) {} }
          if (this.closeHandler) { try { window.removeEventListener('close', this.closeHandler); } catch (e) {} }
          if (this.metaViewport && this.metaViewport.parentNode) { this.metaViewport.parentNode.removeChild(this.metaViewport); }
          if (this.scriptTag && this.scriptTag.parentNode) { this.scriptTag.parentNode.removeChild(this.scriptTag); }
          if (this.styleTag && this.styleTag.parentNode) { this.styleTag.parentNode.removeChild(this.styleTag); }
          try { this.injectCleanup?.(); } catch (e) { dbg('Error during inject cleanup', e); }
          if (this.appletStyleObserver) { try { this.appletStyleObserver.disconnect(); } catch (e) { dbg('Error disconnecting appletStyleObserver', e); } this.appletStyleObserver = null; }
        } catch (err) {
          console.error('Error during resources.dispose():', err);
        }
      }
    }

    const resources = new Resources(kernelId || '', commTarget || '', socketPath || null, wsPort || 8888);
    // Normalize socketPath/ wsUrl on the resources bag so kernel-side helpers
    // always see a defined value when available. Avoid leaving a literal null
    // which complicates downstream checks; prefer undefined for "not set".
    try {
      (resources as any).socketPath = socketPath || undefined;
      // Ensure a wsUrl field exists for kernel_comm to prefer over wsPort
      (resources as any).wsUrl = (resources as any).wsUrl || `ws://localhost:${resources.wsPort}/`;
    } catch (e) { /* ignore normalization errors */ }
    resourcesRef.current = resources;

    // Prevent double-initialization if the component is re-rendered
    if (initializedRef.current) {
      dbg('GeoGebraWidget: already initialized, skipping re-initialization');
      return () => {
        /* no-op cleanup here since top-level unmount handles disposal */
      };
    }
    initializedRef.current = true;

    let applet: any = null;

    (async () => {
      dbg('VSCode widget: calling setupKernelResources', { kernelId: resources.kernelId, socketPath: resources.socketPath });
      let callRemoteSocketSend: (m: string) => Promise<void> = async () => {};
      let makeIncomingHandler: (h: any) => any = (h: any) => null;
      // try {
        const res = await setupKernelResources(resources, { kernelId: resources.kernelId, serverSettings }, dbg);
        callRemoteSocketSend = res.callRemoteSocketSend;
        makeIncomingHandler = res.makeIncomingHandler;
        // Ensure resources.socketPath is populated from any available source
        try {
          const fromResSettings = res && res.serverSettings && (res.serverSettings.socketPath || res.serverSettings.socket_path);
          const fromProps = (serverSettings && (serverSettings.socketPath || (serverSettings as any).socket_path)) || undefined;
          (resources as any).socketPath = (resources as any).socketPath || fromResSettings || fromProps || undefined;
          dbg('Normalized resources.socketPath', (resources as any).socketPath);
        } catch (e) {
          dbg('Failed to normalize resources.socketPath', e);
        }
        // try {
          dbg('setupKernelResources returned', {
            hasCallRemoteSocketSend: typeof callRemoteSocketSend === 'function',
            hasMakeIncomingHandler: typeof makeIncomingHandler === 'function',
            kernelConn: !!res.kernelConn,
            serverSettings: !!res.serverSettings
          });
          // expose helpers for interactive debugging
          try { (window as any).__GGBlab_callRemoteSocketSend = callRemoteSocketSend; } catch (e) {}
          try { (window as any).__GGBlab_makeIncomingHandler = makeIncomingHandler; } catch (e) {}
        // } catch (e) { /* ignore logging errors */ }
        // kernelConn attached to resources by setupKernelResources
        // Widget comm passthrough registration (webview)
        try {
          if ((props as any).widgetManager) {
            dbg('widgetManager present; skipping raw jupyter.widget comm registration in webview');
          } else {
            const opts = {
              callRemoteSocketSend,
              kernel2: resources.kernel2,
              socketPath: resources.socketPath,
              wsUrl: `ws://localhost:${resources.wsPort}/`,
              getAppletApi: () => resources.appletApi,
              isArrayOfArrays: isArrayOfArrays,
              dbg
            };

            try {
              const unregisterFn = registerWidgetCommTargets(resources.kernelConn, opts as any);
              resources.unregisterWidgetCommTargets = unregisterFn;
            } catch (e) {
              dbg('registerWidgetCommTargets failed in webview', e);
            }
          }
        } catch (e) {
          dbg('Widget comm target registration skipped or failed (webview)', e);
        }
      // } catch (e) {
      //   dbg('setupKernelResources failed or not applicable in this environment', e);
      // }

      const processCommandMessage = createProcessCommandMessage(resources, callRemoteSocketSend, isArrayOfArrays, dbg);

      const handleIncomingCommMessage = makeIncomingHandler(processCommandMessage);


      async function ggbOnLoad(api: any) {
        dbg('GeoGebra applet loaded (vscode):', api);
        resources.appletApi = api;
        (async () => {
          const msg = { type: 'start', payload: {} };
          try { await callRemoteSocketSend(JSON.stringify(msg)); } catch (e) { dbg('callRemoteSocketSend failed', e); }
        })();

        // Run shared common setup (comm, listeners, dialog observer, close handler)
        try {
          await setupAppletOnLoadCommon(api, resources, callRemoteSocketSend, handleIncomingCommMessage, dbg);
        } catch (e) {
          dbg('setupAppletOnLoadCommon failed (vscode)', e);
        }

        // Prefer ResizeObserver to detect size changes of the container.
        const targetElem = widgetRef.current || document.getElementById(elementId) as HTMLElement | null;
        const applySize = () => {
          try {
            const el = targetElem;
            if (!el) return;
            const rect = el.getBoundingClientRect();
            const widthV = Math.max(1, Math.floor(rect.width));
            const heightV = Math.max(1, Math.floor(rect.height));
              try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
              try { api.setSize(widthV, heightV); } catch (e) { dbg('setSize failed', e); }
              // Force the injected applet DOM to avoid transform scaling and fill
              // the measured container exactly (avoid letterbox due to aspect ratio).
              try {
                const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null;
                if (appletNode) {
                  const applyImportant = (node: HTMLElement) => {
                    try {
                      node.style.setProperty('width', '100%', 'important');
                      node.style.setProperty('height', '100%', 'important');
                      node.style.setProperty('max-width', '100%', 'important');
                      node.style.setProperty('transform', 'none', 'important');
                      node.style.setProperty('transform-origin', '0 0', 'important');
                    } catch (e) {
                      // best-effort fallback
                      try { node.style.width = '100%'; } catch (e) {}
                      try { node.style.height = '100%'; } catch (e) {}
                      try { node.style.maxWidth = '100%'; } catch (e) {}
                      try { node.style.transform = 'none'; } catch (e) {}
                      try { node.style.transformOrigin = '0 0'; } catch (e) {}
                    }
                  };

                  // Apply to the applet node itself
                  applyImportant(appletNode);

                  // Also apply to nearby ancestors that may carry the transform
                  // (look for computed transform != 'none' or data-scalex attributes).
                  try {
                    let p: HTMLElement | null = appletNode.parentElement;
                    let depth = 0;
                    while (p && depth < 6) {
                      try {
                        const cs = window.getComputedStyle(p);
                        if ((cs && cs.transform && cs.transform !== 'none') || p.hasAttribute('data-scalex') || p.classList.contains('applet-wrapper') || p.id?.startsWith('ggbApplet')) {
                          applyImportant(p);
                        }
                      } catch (e) {
                        /* ignore per-ancestor errors */
                      }
                      p = p.parentElement;
                      depth += 1;
                    }
                  } catch (e) { /* ignore ancestor application errors */ }
                }
              } catch (e) { dbg('Failed to override applet DOM styles (vscode)', e); }
          } catch (e) { dbg('applySize failed', e); }
        };

        let ro: ResizeObserver | null = null;
        try {
          if (typeof (window as any).ResizeObserver === 'function' && targetElem) {
            ro = new (window as any).ResizeObserver(() => applySize());
            ro.observe(targetElem);
            resources.observer = ro as any;
          }
        } catch (e) {
          dbg('ResizeObserver unavailable or failed', e);
          ro = null;
        }

        // Fallback to window resize events
        resources.resizeHandler = () => applySize();
        try { window.addEventListener('resize', resources.resizeHandler); } catch (e) { dbg('addEventListener resize failed', e); }
        // Initial apply
        applySize();

        // Note: kernel comm, basic listeners, close handler and dialog observer
        // are installed by `setupAppletOnLoadCommon` above. Here we keep
        // the resize/stylesheet behavior specific to the webview.
      }

      // Inject the applet using the measured container size and allow upscaling
      try {
        const wrapperDiv = widgetRef.current || document.getElementById(elementId) as HTMLElement | null;
        // Prefer measuring the widget element itself so height is based on the
        // element that is styled to fill the webview; fallback to parent.
        const targetForSize = wrapperDiv ?? (wrapperDiv as HTMLElement | null)?.parentElement ?? null;
        let measuredWidth = 800;
        let measuredHeight = 600;
        // noop
        try {
          if (targetForSize) {
            const rect = (targetForSize as HTMLElement).getBoundingClientRect();
            measuredWidth = Math.max(1, Math.floor(rect.width));
            measuredHeight = Math.max(1, Math.floor(rect.height));
          }
        } catch (e) {
          dbg('Failed to measure container for initial size, falling back to defaults', e);
        }

        const { appletPromise, scriptTag, metaViewport, cleanup } = injectGeoGebraApplet({
          elementId,
          appName,
          width: measuredWidth,
          height: measuredHeight,
          // Use the same responsive class as the webview container so
          // the applet's internal scaling math stays consistent.
          scaleContainerClass: 'applet-wrapper',
          // allow the applet to upscale when the panel grows
          allowUpscale: true,
          appletOnLoad: ggbOnLoad,
          dbg
        } as any);
        resources.scriptTag = scriptTag || null;
        resources.metaViewport = metaViewport || null;
        resources.injectCleanup = cleanup || null;
        try {
          // Insert a forcing stylesheet to override runtime transforms and sizing
          const css = `
            .applet_scaler.ggbTransform, #ggbApplet, .applet-wrapper, .GeoGebraFrame, [id^="ggbApplet-"] {
              width: 100% !important;
              height: 100% !important;
              max-width: 100% !important;
              transform: none !important;
              transform-origin: 0 0 !important;
            }
            .applet_scaler.ggbTransform canvas, #ggbApplet canvas, .applet-wrapper canvas, .GeoGebraFrame canvas, [id^="ggbApplet-"] canvas {
              width: 100% !important;
              height: 100% !important;
            }
          `;
          const styleTag = document.createElement('style');
          styleTag.id = 'ggblab-force-applet-styles';
          styleTag.appendChild(document.createTextNode(css));
          (document.head || document.documentElement).appendChild(styleTag);
          resources.styleTag = styleTag;
        } catch (e) { dbg('Failed to insert forcing stylesheet', e); }
        appletPromise.then((a: any) => {
          applet = a;
          try {
            const api = a;
            // apply size and reapply after short delays to override internal resets
            try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
            try { api.setSize(measuredWidth, measuredHeight); dbg('Applied initial applet size (vscode)', measuredWidth, measuredHeight); } catch (e) { dbg('api.setSize failed', e); }
            setTimeout(() => { try { api.setSize(measuredWidth, measuredHeight); dbg('Reapplied size (250ms)'); } catch (e) { dbg('reapply failed', e); } }, 250);
            setTimeout(() => { try { api.setSize(measuredWidth, measuredHeight); dbg('Reapplied size (1000ms)'); } catch (e) { dbg('reapply failed', e); } }, 1000);
            // Observe the injected applet node for attribute/style changes
            try {
              const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null;
              if (appletNode) {
                const aobserver = new MutationObserver(mutations => {
                  try {
                    const rect3 = (appletNode.parentElement ?? appletNode).getBoundingClientRect();
                    const ww = Math.max(1, Math.floor(rect3.width));
                    const hh = Math.max(1, Math.floor(rect3.height));
                    try { api.setSize(ww, hh); } catch (e) { /* ignore */ }
                    try {
                      const applyImportant = (node: HTMLElement) => {
                        try {
                          node.style.setProperty('transform', 'none', 'important');
                          node.style.setProperty('width', '100%', 'important');
                          node.style.setProperty('height', '100%', 'important');
                          node.style.setProperty('max-width', '100%', 'important');
                          node.style.setProperty('transform-origin', '0 0', 'important');
                        } catch (e) {
                          try { node.style.transform = 'none'; } catch (e) {}
                          try { node.style.width = '100%'; } catch (e) {}
                          try { node.style.height = '100%'; } catch (e) {}
                        }
                      };
                      applyImportant(appletNode);
                      try {
                        let p: HTMLElement | null = appletNode.parentElement;
                        let depth = 0;
                        while (p && depth < 6) {
                          try {
                            const cs = window.getComputedStyle(p);
                            if ((cs && cs.transform && cs.transform !== 'none') || p.hasAttribute('data-scalex') || p.classList.contains('applet-wrapper') || p.id?.startsWith('ggbApplet')) {
                              applyImportant(p);
                            }
                          } catch (e) { /* ignore */ }
                          p = p.parentElement;
                          depth += 1;
                        }
                      } catch (e) { /* ignore ancestor errors */ }
                    } catch (e) { /* ignore */ }
                  } catch (e) { dbg('appletStyleObserver handler error (vscode)', e); }
                });
                aobserver.observe(appletNode, { attributes: true, attributeFilter: ['style', 'class'], subtree: false });
                resources.appletStyleObserver = aobserver;
              }
            } catch (e) { dbg('Failed to create appletStyleObserver (vscode)', e); }
          } catch (e) { dbg('Error applying size to applet', e); }
        }).catch((e: any) => dbg('Applet creation failed', e));
      } catch (e) {
        dbg('injectGeoGebraApplet failed', e);
      }
    })();

    return () => {
      try {
        // remove resize/close listeners and observer
        (async () => {
          try {
            // call dispose on resources if present
            // (resources variable is in closure)
            // @ts-ignore
            const r = resourcesRef.current || resources;
            if (r && typeof r.dispose === 'function') {
              await r.dispose();
            }
          } catch (e) { dbg('dispose on unmount failed', e); }
        })();
        // remove injected DOM
        const el = document.getElementById(elementId);
        if (el) el.innerHTML = '';
        const winApplet = (window as any).ggblab_applet || (window as any).ggbApplet;
        if (winApplet && typeof winApplet.remove === 'function') { try { winApplet.remove(); } catch (e) { /* ignore */ } }
      } catch (e) { /* ignore */ }
    };
  }, []);

  return (
    <div id={elementId} ref={widgetRef} className="applet-wrapper" style={{ width: '100%', height: '100%' }} />
  );
};

export default GeoGebraWidget;
