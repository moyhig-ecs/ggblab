/* eslint-disable */
import React, { useEffect, useRef } from 'react';
import { injectGeoGebraApplet } from '../../src/shared/createApplet';
import setupKernelResources from '../../src/components/jupyterlab';
import { isArrayOfArrays } from '../../src/shared/geoGebraCommon';
import { createProcessCommandMessage } from '../../src/shared/geoGebraCommon';
import setupAppletOnLoadCommon from '../../src/shared/appletOnLoadCommon';
import { initKernelCommHelpers } from '../../src/comm/kernel_comm';
import { registerWidgetCommTargets } from '../../src/widgets';

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
      globalResizeObserver: ResizeObserver | null = null;
      visualViewportHandler: (() => void) | null = null;
      pollerId: number | null = null;
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
          try { this.globalResizeObserver?.disconnect(); } catch (e) { dbg('Error disconnecting globalResizeObserver', e); }
          try { if (this.visualViewportHandler && (window as any).visualViewport) { (window as any).visualViewport.removeEventListener('resize', this.visualViewportHandler); } } catch (e) { dbg('Error removing visualViewport handler', e); }
          try { if (this.pollerId) { clearInterval(this.pollerId); this.pollerId = null; } } catch (e) { dbg('Error clearing poller', e); }
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
      // const { callRemoteSocketSend, makeIncomingHandler } 
      const res = await setupKernelResources(resources, { kernelId: resources.kernelId, serverSettings }, dbg);
      // Prefer the shared kernel_comm helpers for consistent behavior
      // with the main widget. Fall back to values returned by
      // setupKernelResources when initialization fails.
      // try {
      //   const kh = initKernelCommHelpers(resources, dbg);
      //   callRemoteSocketSend = kh.callRemoteSocketSend;
      //   makeIncomingHandler = kh.makeIncomingHandler;
      // } catch (e) {
      callRemoteSocketSend = res.callRemoteSocketSend;
      makeIncomingHandler = res.makeIncomingHandler;
      // }

      const processCommandMessage = createProcessCommandMessage(resources, callRemoteSocketSend, isArrayOfArrays, dbg);
      const handleIncomingCommMessage = makeIncomingHandler(processCommandMessage);

      // Ensure resources.socketPath is populated from any available source
      try {
        const fromResSettings = res && res.serverSettings && (res.serverSettings.socketPath || res.serverSettings.socket_path);
        const fromProps = (serverSettings && (serverSettings.socketPath || (serverSettings as any).socket_path)) || undefined;
        (resources as any).socketPath = (resources as any).socketPath || fromResSettings || fromProps || undefined;
        dbg('Normalized resources.socketPath', (resources as any).socketPath);
      } catch (e) {
        dbg('Failed to normalize resources.socketPath', e);
      }

      dbg('setupKernelResources returned', {
        hasCallRemoteSocketSend: typeof callRemoteSocketSend === 'function',
        hasMakeIncomingHandler: typeof makeIncomingHandler === 'function',
        kernelConn: !!res.kernelConn,
        serverSettings: !!res.serverSettings
      });

      // expose helpers for interactive debugging
      try { (window as any).__GGBlab_callRemoteSocketSend = callRemoteSocketSend; } catch (e) {}
      try { (window as any).__GGBlab_makeIncomingHandler = makeIncomingHandler; } catch (e) {}

      // kernelConn attached to resources by setupKernelResources
      // Widget comm passthrough registration (webview)
      try {
        // In the VSCode webview we don't have a Jupyter widgetManager, so
        // always register the widget comm passthrough if possible.
        try {
          const opts = {
            callRemoteSocketSend,
            kernel2: resources.kernel2,
            socketPath: resources.socketPath,
            wsUrl: `ws://localhost:${resources.wsPort}/`,
            getAppletApi: () => resources.appletApi,
            isArrayOfArrays: isArrayOfArrays,
            dbg
          };
          const unregisterFn = registerWidgetCommTargets(resources.kernelConn, opts as any);
          resources.unregisterWidgetCommTargets = unregisterFn;
        } catch (e) {
          dbg('registerWidgetCommTargets failed in webview', e);
        }
      } catch (e) {
        dbg('Widget comm target registration skipped or failed (webview)', e);
      }

      async function ggbOnLoad(api: any) {
        dbg('GeoGebra applet loaded (vscode):', api);
        // Use the shared common setup to mirror behavior with the main widget.
        try {
          await setupAppletOnLoadCommon(api, resources, callRemoteSocketSend, handleIncomingCommMessage, dbg);
        } catch (e) {
          dbg('setupAppletOnLoadCommon failed', e);
        }

        // Prefer ResizeObserver to detect size changes of the container.
        // Measurement target is evaluated on every apply so that layout
        // changes (panel open/close, DevTools toggles) are always reflected.
        

        const applySize = () => {
          try {
            const el = (document.getElementById('ggb-container') as HTMLElement | null) || widgetRef.current || document.getElementById(elementId) as HTMLElement | null || document.documentElement;
            if (!el) return;
            const rect = el.getBoundingClientRect();
            // Use CSS pixels for the applet API; avoid multiplying by devicePixelRatio
            // here because the applet expects CSS pixel dimensions.
            let widthV = Math.max(1, Math.floor(rect.width));
            let heightV = Math.max(1, Math.floor(rect.height));
            // Cap reported size by the visible document/client size to avoid
            // inflated measurements from offscreen/overflowing elements.
            const maxW = Math.max(1, Math.floor(document.documentElement.clientWidth));
            const maxH = Math.max(1, Math.floor(document.documentElement.clientHeight));
            widthV = Math.min(widthV, maxW);
            heightV = Math.min(heightV, maxH);
              try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
              try { api.setSize(widthV, heightV); } catch (e) { dbg('setSize failed', e); }
              // (canvas DPR adjustment removed)
              // Force a minimal reflow of the applet internals: call setSize again
              // on the next animation frame and dispatch a window resize event.
                    try {
                      requestAnimationFrame(() => {
                        try {
                          try { api.recalculateEnvironments?.(); } catch (e) { /* ignore */ }
                          try { api.setSize(widthV, heightV); } catch (e) { /* ignore */ }
                          // (canvas DPR adjustment removed)
                        } catch (e) {
                          dbg('rAF reflow failed', e);
                        }
                      });
                    } catch (e) { dbg('Failed scheduling reflow rAF', e); }
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

        // Debounce resize handling to avoid rapid re-entry from multiple
        // sources (ResizeObserver, visualViewport, window resize, poller).
        const debounce = (fn: () => void, wait = 100) => {
          let t: number | null = null;
          return () => {
            if (t) { clearTimeout(t); }
            t = window.setTimeout(() => { t = null; try { fn(); } catch (e) { dbg('debounced fn failed', e); } }, wait) as unknown as number;
          };
        };

        const targetElem = (document.getElementById('ggb-container') as HTMLElement | null) || widgetRef.current || document.getElementById(elementId) as HTMLElement | null || document.documentElement;
        let ro: ResizeObserver | null = null;
        // Wrap applySize with a debounce for use by observers/listeners.
        const debouncedApplySize = debounce(applySize, 100);

        try {
          if (typeof (window as any).ResizeObserver === 'function' && targetElem) {
            ro = new (window as any).ResizeObserver(() => debouncedApplySize());
            ro.observe(targetElem);
            resources.observer = ro as any;
          }
        } catch (e) {
          dbg('ResizeObserver unavailable or failed', e);
          ro = null;
        }

        // Fallback to window resize events
        resources.resizeHandler = () => debouncedApplySize();
        try { window.addEventListener('resize', resources.resizeHandler); } catch (e) { dbg('addEventListener resize failed', e); }
        // Initial apply (immediate)
        applySize();

        // Also observe root/body for layout changes (DevTools open/close can
        // change document geometry without affecting the widget element). Use a
        // separate global ResizeObserver and visualViewport listener to detect
        // those cases and trigger a re-measure.
        try {
          if (typeof (window as any).ResizeObserver === 'function') {
            const gro = new (window as any).ResizeObserver(() => debouncedApplySize());
            try { gro.observe(document.documentElement); } catch (e) { /* ignore */ }
            try { gro.observe(document.body); } catch (e) { /* ignore */ }
            resources.globalResizeObserver = gro as any;
          }
        } catch (e) {
          dbg('global ResizeObserver unavailable or failed', e);
        }

        try {
          if ((window as any).visualViewport && typeof (window as any).visualViewport.addEventListener === 'function') {
            const vvHandler = () => debouncedApplySize();
            (window as any).visualViewport.addEventListener('resize', vvHandler);
            resources.visualViewportHandler = vvHandler;
          }
        } catch (e) {
          dbg('visualViewport listener setup failed', e);
        }

        // Polling fallback: some host layout changes (e.g. VSCode panel toggles)
        // may not reliably fire ResizeObserver/visualViewport events in this
        // environment. Use a lightweight interval to detect client size changes
        // and reapply sizing when needed.
        try {
          let lastW = document.documentElement.clientWidth;
          let lastH = document.documentElement.clientHeight;
          const id = window.setInterval(() => {
            try {
              const cw = document.documentElement.clientWidth;
              const ch = document.documentElement.clientHeight;
              if (cw !== lastW || ch !== lastH) {
                lastW = cw; lastH = ch;
                debouncedApplySize();
              }
            } catch (e) { /* ignore per-tick errors */ }
          }, 250);
          resources.pollerId = id as any;
        } catch (e) {
          dbg('poller setup failed', e);
        }

        if (resources.kernelConn && resources.commTarget) {
          try {
            resources.comm = resources.kernelConn.createComm(resources.commTarget);
            try { resources.comm.open('HELO from GGB'); } catch (e) { dbg('Comm open failed', e); }
          } catch (e) {
            dbg('Failed to create kernel comm', e);
            resources.comm = null;
          }
          try {
            resources.comm.onMsg = handleIncomingCommMessage;
          } catch (e) { dbg('attach onMsg failed', e); }
          try {
            // attach onClose to surface kernel-side close events
            (resources.comm as any).onClose = (m: any) => {
              try {
                const closedId = (m && m.content && m.content.comm_id) || (resources.comm as any)?.comm_id || (resources.comm as any)?.commId || null;
                dbg('Comm closed (webview side)', { target: resources.commTarget, closedId, message: m });
              } catch (ee) {
                dbg('Comm closed (webview side, no id available)', resources.commTarget, m);
              }
            };
          } catch (e) { dbg('attach onClose failed', e); }
        } else {
          dbg('No kernelConn available; using remote socket only');
        }

        resources.closeHandler = () => {
          try { resources.comm?.close?.(); } catch (e) { dbg('close comm failed', e); }
          try { resources.kernel2?.shutdown?.(); } catch (e) { dbg('shutdown helper failed', e); }
          if (resources.resizeHandler) { try { window.removeEventListener('resize', resources.resizeHandler); } catch (e) {} resources.resizeHandler = null; }
          try { if (resources.observer) { (resources.observer as ResizeObserver).disconnect(); resources.observer = null; } } catch (e) { dbg('disconnect observer failed', e); }
        };
        window.addEventListener('close', resources.closeHandler);

        // Register simple listeners exposed by the API (add/remove/etc.)
          try {
          const addListener = async function (data: any) {
            const msg = { type: 'add', ts: Date.now(), payload: data };
            const s = JSON.stringify(msg);
            try {
              if (resources.widgetComm) { resources.widgetComm.send(s); return; }
            } catch (e) { dbg('widgetComm send failed', e); }
            try { await callRemoteSocketSend(s); } catch (e) { dbg('socket send add failed', e); }
          };
          api.registerAddListener?.(addListener);
          api.registerRemoveListener?.(async (data: any) => { const s = JSON.stringify({ type: 'remove', ts: Date.now(), payload: data }); await callRemoteSocketSend(s); });
          api.registerRenameListener?.(async (data: any) => { const s = JSON.stringify({ type: 'rename', ts: Date.now(), payload: data }); await callRemoteSocketSend(s); });
          api.registerClearListener?.(async (data: any) => { const s = JSON.stringify({ type: 'clear', ts: Date.now(), payload: data }); await callRemoteSocketSend(s); });
        } catch (e) { dbg('register listeners failed', e); }

        resources.observer = new MutationObserver(mutations => {
          mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
              try {
                (node as HTMLElement).querySelectorAll && (node as HTMLElement)
                  .querySelectorAll('div.dialogMainPanel > div.dialogTitle')
                  .forEach(n => {
                    (node as HTMLElement).querySelector('div.dialogContent')?.querySelectorAll("[class$='Label']").forEach(async n2 => {
                      const msg = JSON.stringify({ type: n.textContent, payload: n2.textContent });
                      await callRemoteSocketSend(msg);
                    });
                  });
              } catch (e) { /* ignore per-node errors */ }
            });
          });
        });
        resources.observer.observe(document.body, { childList: true, subtree: true });
      }

      // Inject the applet using the measured container size and allow upscaling
      try {
        const hostContainer = document.getElementById('ggb-container') as HTMLElement | null;
        const wrapperDiv = widgetRef.current || document.getElementById(elementId) as HTMLElement | null;
        // Prefer host-provided container, then the widget node, then the widget's parent
        const targetForSize = hostContainer || wrapperDiv || (wrapperDiv as HTMLElement | null)?.parentElement || document.documentElement;
        let measuredWidth = 800;
        let measuredHeight = 600;
        try {
          if (targetForSize) {
            const rect = (targetForSize as HTMLElement).getBoundingClientRect();
            measuredWidth = Math.max(1, Math.floor(rect.width));
            measuredHeight = Math.max(1, Math.floor(rect.height));
            // Cap by visible client size to avoid oversized values
            const maxW = Math.max(1, Math.floor(document.documentElement.clientWidth));
            const maxH = Math.max(1, Math.floor(document.documentElement.clientHeight));
            measuredWidth = Math.min(measuredWidth, maxW);
            measuredHeight = Math.min(measuredHeight, maxH);
          }
        } catch (e) {
          dbg('Failed to measure container for initial size, falling back to defaults', e);
        }

        // Use a stable class name for the scale container (not a DOM element)
        const scaleContainerClass = 'applet-wrapper';
        const { appletPromise, scriptTag, metaViewport, cleanup } = injectGeoGebraApplet({
          elementId,
          appName,
          width: measuredWidth,
          height: measuredHeight,
          // Use the same responsive class as the webview container so
          // the applet's internal scaling math stays consistent.
          scaleContainerClass,
          // allow the applet to upscale when the panel grows
          allowUpscale: false,
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
            // apply size once; rely on ResizeObserver / MutationObserver for subsequent changes
            try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
            try { api.setSize(measuredWidth, measuredHeight); } catch (e) { dbg('api.setSize failed', e); }
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
