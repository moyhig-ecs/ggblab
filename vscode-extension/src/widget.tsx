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
    // user-scale adjustments disabled — keep only ggb-scale-container tagging
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
      // Optional override for device/user scale factor sent from the
      // extension host. Defaults to 1.
      userScaleFactor: number = 1;

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

    // Canvas reapplication disabled (webview-side scaling removed).

    // Prevent double-initialization if the component is re-rendered
    if (initializedRef.current) {
      dbg('GeoGebraWidget: already initialized, skipping re-initialization');
      return () => {
        /* no-op cleanup here since top-level unmount handles disposal */
      };
    }
    initializedRef.current = true;

    let _applet: any = null;

    (async () => {
      let wrapperRootForSizing: HTMLElement | null = null;
      dbg('VSCode widget: calling setupKernelResources', { kernelId: resources.kernelId, socketPath: resources.socketPath });
      let callRemoteSocketSend: (m: string) => Promise<void> = async () => {};
      let makeIncomingHandler: (h: any) => any = (h: any) => null;
      const res = await setupKernelResources(resources, { kernelId: resources.kernelId, serverSettings }, dbg);
      try {
        // Do not change applet DOM font-size here; setter only persists value.
        if (typeof (window as any).acquireVsCodeApi === 'function') {
          try {
            const _vscode = (window as any).acquireVsCodeApi();
            _vscode.postMessage({ type: 'ready' });
          } catch (e) { /* ignore */ }
        }
      } catch (e) { /* ignore */ }
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
          try { dbg('Initial measurement (vscode):', { targetForSize: targetForSize.id || targetForSize.className || targetForSize.tagName, measuredWidth, measuredHeight }); } catch (e) {}
          // Listen for messages from the extension host (e.g. setUserScaleFactor)
          try {
            window.addEventListener('message', (ev: MessageEvent) => {
              try {
                const data = ev.data || {};
                if (data && data.type === 'setUserScaleFactor') {
                  const f = parseFloat(String(data.scale || 1)) || 1;
                  (resources as any).userScaleFactor = f;
                  dbg('Received setUserScaleFactor (vscode):', f);
                  try { applySize(); } catch (e) { /* ignore */ }
                }
              } catch (e) { /* ignore message handler errors */ }
            });
          } catch (e) { /* ignore */ }
          try { (window as any).__GGBlab_makeIncomingHandler = makeIncomingHandler; } catch (e) {}
        // } catch (e) { /* ignore logging errors */ }
        // kernelConn attached to resources by setupKernelResources
        // Widget comm passthrough registration (webview)
        try {
          // if ((props as any).widgetManager) {
          //   dbg('widgetManager present; skipping raw jupyter.widget comm registration in webview');
          // } else
          {
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
            // Post explicit comm registration status to the extension host
            try {
              // @ts-ignore
              if (typeof (window as any).acquireVsCodeApi === 'function') {
                try {
                  const _vscode = (window as any).acquireVsCodeApi();
                  _vscode.postMessage({ type: 'commStatus', registered: !!resources.unregisterWidgetCommTargets, kernelConn: !!resources.kernelConn, kernelId: resources.kernelId || null });
                } catch (e) { /* ignore */ }
              }
            } catch (e) { /* ignore */ }
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
            // Diagnostic: log container & canvas info to help determine which
            // DOM node GeoGebra uses to compute device scaling.
            try {
              const appletNode = document.getElementById('ggbApplet-' + elementId) || document.getElementById(elementId) || null;
              dbg('ggbOnLoad: elementId=', elementId);
              dbg('ggbOnLoad: found appletNode', appletNode && { id: appletNode.id, className: appletNode.className });
              try { dbg('ggbOnLoad: applet computedStyle', appletNode && window.getComputedStyle(appletNode)); } catch (e) { dbg('ggbOnLoad: computedStyle failed', e); }
              try {
                const canvases = appletNode ? Array.from(appletNode.querySelectorAll('canvas')) as HTMLCanvasElement[] : [];
                dbg('ggbOnLoad: canvases count', canvases.length);
                canvases.forEach((c, i) => {
                  try {
                    const cs = window.getComputedStyle(c);
                    dbg('ggbOnLoad: canvas', i, { cssW: cs.width, cssH: cs.height, backingW: c.width, backingH: c.height });
                  } catch (e) { dbg('ggbOnLoad: canvas diag failed', i, e); }
                });
              } catch (e) { dbg('ggbOnLoad: canvases inspect failed', e); }
              dbg('ggbOnLoad: devicePixelRatio', window.devicePixelRatio);
            } catch (e) { dbg('ggbOnLoad: diag top-level failed', e); }
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
        const outerRootElem = document.getElementById('ggb-root');
        const targetElem = outerRootElem || widgetRef.current || document.getElementById(elementId) as HTMLElement | null;
        const applySize = () => {
          try {
            const el = targetElem;
            if (!el) return;
            const rect = el.getBoundingClientRect();
            const widthV = Math.max(1, Math.floor(rect.width));
            const heightV = Math.max(1, Math.floor(rect.height));
            const scaleF = (resources as any).userScaleFactor || 1;
            const targetWidthPx = Math.max(1, Math.floor(widthV * scaleF));
            const targetHeightPx = Math.max(1, Math.floor(heightV * scaleF));
            try { dbg('applySize (vscode): targetElem info', { id: el.id, className: el.className, bounding: { width: rect.width, height: rect.height } }); } catch (e) {}
                try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
                try {
                  // Temporarily apply explicit pixel dimensions to the wrapper so
                  // GeoGebra recreates its backing canvas at the intended size.
                  try {
                    if (wrapperRootForSizing) {
                      // Use CSS pixel sizes for layout but set backing-pixel
                      // target via setSize below. Keep wrapper CSS at logical
                      // pixels to avoid layout jumps.
                      wrapperRootForSizing.style.width = widthV + 'px';
                      wrapperRootForSizing.style.height = heightV + 'px';
                    }
                  } catch (e) { /* ignore */ }

                  // Prefer setSize when available (forces width+height), fall
                  // back to setHeight for older APIs. Use scaled pixel targets
                  // so the applet's backing canvas matches the device/user scale.
                  if (typeof api?.setSize === 'function') {
                    dbg('Calling api.setSize (vscode) with', targetWidthPx, targetHeightPx);
                    api.setSize?.(targetWidthPx, targetHeightPx);
                  } else if (typeof api?.setHeight === 'function') {
                    dbg('Calling api.setHeight (vscode) with', targetHeightPx);
                    api.setHeight(targetHeightPx);
                  } else {
                    dbg('No setSize/setHeight available on applet API');
                  }

                  // Clear our temporary inline dimensions shortly after to allow
                  // responsive layout to resume.
                  setTimeout(() => {
                    try {
                      if (wrapperRootForSizing) {
                        wrapperRootForSizing.style.width = '';
                        wrapperRootForSizing.style.height = '';
                      }
                    } catch (e) { /* ignore */ }
                  }, 120);
                } catch (e) { dbg('set size/height failed', e); }
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

                  // Apply to the applet node itself only. Avoid traversing and
                  // mutating ancestor nodes to reduce DOM churn and races.
                  applyImportant(appletNode);
                }
              } catch (e) { dbg('Failed to override applet DOM styles (vscode)', e); }
          } catch (e) { dbg('applySize failed', e); }
        };

        let ro: ResizeObserver | null = null;
        try {
          if (typeof (window as any).ResizeObserver === 'function' && targetElem) {
            const roInstance = new (window as any).ResizeObserver(() => applySize());
            roInstance.observe(targetElem);
            ro = roInstance;
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

        // After initial sizing, remove our temporary explicit wrapper dimensions
        // so normal responsive layout can resume. Rely on ResizeObserver to
        // drive subsequent size updates rather than timers.
        try {
          try {
            if (wrapperRootForSizing) {
              wrapperRootForSizing.style.width = '';
              wrapperRootForSizing.style.height = '';
            }
          } catch (e) { /* ignore */ }
          // Immediately apply size once more after clearing inline dims.
          try { applySize(); } catch (e) { /* ignore */ }
        } catch (e) { /* ignore */ }

        // Diagnostic: collect computed font sizes inside the applet and report
        try {
          setTimeout(() => {
            try {
              const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null;
              if (!appletNode) return;
              const els = Array.from(appletNode.querySelectorAll('div,span,p,label,td,th')) as HTMLElement[];
              const sizes: { [k: string]: number } = {};
              for (let i = 0; i < Math.min(els.length, 80); i++) {
                try {
                  const el = els[i];
                  const cs = window.getComputedStyle(el);
                  const fs = parseFloat(cs.fontSize || '0') || 0;
                  const key = `${cs.fontFamily || 'unknown'}|${Math.round(fs)}`;
                  if (!sizes[key]) sizes[key] = 0;
                  sizes[key] += 1;
                } catch (e) { /* ignore per-element errors */ }
              }
              dbg('applet: computed font-size samples', { samples: Object.keys(sizes).slice(0, 10), counts: sizes });
            } catch (e) { dbg('font-size diagnostic failed', e); }
          }, 500);
        } catch (e) { /* ignore */ }

        // Note: kernel comm, basic listeners, close handler and dialog observer
        // are installed by `setupAppletOnLoadCommon` above. Here we keep
        // the resize/stylesheet behavior specific to the webview.
      }

      // Inject the applet using the measured container size and allow upscaling
      try {
        const wrapperDiv = widgetRef.current || document.getElementById(elementId) as HTMLElement | null;
        // Prefer measuring a known outer root if available (in the webview we
        // expose #ggb-root), otherwise fall back to the widget element or its parent.
        const outerRoot = document.getElementById('ggb-root');
        const targetForSize = outerRoot ?? wrapperDiv ?? (wrapperDiv as HTMLElement | null)?.parentElement ?? null;

        // Ensure the wrapper is tagged before GeoGebra inspects ancestors.
        let wrapperRootForSizing: HTMLElement | null = null;
          try {
            wrapperRootForSizing = widgetRef.current || document.getElementById(elementId);
            // Do not tag wrapper with a scale container class; avoid triggering
            // GeoGebra's container-scaling behavior which applies CSS transforms.
          } catch (e) { /* best effort */ }

        // Wait briefly for the container size to stabilise before injecting
        // the applet — this ensures GeoGebra reads the final dimensions.
        const waitForStableSize = async (target: HTMLElement | null, timeout = 1500) => {
          if (!target) return;
          return new Promise<void>((resolve) => {
            try {
              if (typeof (window as any).ResizeObserver === 'function') {
                let lastW = -1;
                let lastH = -1;
                let stableSince = Date.now();
                const ro = new (window as any).ResizeObserver(() => {
                  try {
                    const r = target.getBoundingClientRect();
                    const w = Math.max(1, Math.floor(r.width));
                    const h = Math.max(1, Math.floor(r.height));
                    if (w === lastW && h === lastH) {
                      if (Date.now() - stableSince > 120) {
                        try { ro.disconnect(); } catch (e) {}
                        resolve();
                      }
                    } else {
                      lastW = w; lastH = h; stableSince = Date.now();
                    }
                  } catch (e) {
                    // ignore per-observe errors
                  }
                });
                ro.observe(target);
                setTimeout(() => { try { ro.disconnect(); } catch (e) {} ; resolve(); }, timeout);
                return;
              }
            } catch (e) {
              /* ignore */
            }
            // Fallback polling
            let lastKey = '';
            let stableSince = Date.now();
            const iv = setInterval(() => {
              try {
                const r = target.getBoundingClientRect();
                const w = Math.max(1, Math.floor(r.width));
                const h = Math.max(1, Math.floor(r.height));
                const key = `${w}x${h}`;
                if (key === lastKey) {
                  if (Date.now() - stableSince > 120) {
                    clearInterval(iv);
                    resolve();
                  }
                } else {
                  lastKey = key;
                  stableSince = Date.now();
                }
              } catch (e) {
                // ignore
              }
            }, 60);
            setTimeout(() => { try { clearInterval(iv); } catch (e) {}; resolve(); }, timeout + 10);
          });
        };

        try { await waitForStableSize(targetForSize, 1500); } catch (e) { /* best-effort */ }

        let measuredWidth = 800;
        let measuredHeight = 600;
        try {
          if (targetForSize) {
            const rect = (targetForSize as HTMLElement).getBoundingClientRect();
            measuredWidth = Math.max(1, Math.floor(rect.width));
            measuredHeight = Math.max(1, Math.floor(rect.height));
          }
        } catch (e) {
          dbg('Failed to measure container for initial size, falling back to defaults', e);
        }

        // Temporarily set explicit pixel dimensions on the wrapper so
        // GeoGebra can read a container with concrete sizes at creation time.
        try {
          if (wrapperRootForSizing) {
            wrapperRootForSizing.style.width = measuredWidth + 'px';
            wrapperRootForSizing.style.height = measuredHeight + 'px';
          }
        } catch (e) { /* best-effort */ }

        const { appletPromise, scriptTag, metaViewport, cleanup } = injectGeoGebraApplet({
          elementId,
          appName,
          width: measuredWidth,
          height: measuredHeight,
          scaleContainerClass: 'ggb-root',
          allowUpscale: false,
          autoHeight: false,
          appletOnLoad: ggbOnLoad,
          dbg
        } as any);
        resources.scriptTag = scriptTag || null;
        resources.metaViewport = metaViewport || null;
        resources.injectCleanup = cleanup || null;
        // Webview-side forcing stylesheet and canvas re-scaling removed.
        appletPromise.then((a: any) => {
          _applet = a;
          try {
            const attemptApplySize = async () => {
              // Prefer the API provided via ggbOnLoad when available
              let api: any = resources.appletApi || a;
              const start = Date.now();
              while (typeof api?.setHeight !== 'function' && typeof api?.setSize !== 'function' && Date.now() - start < 1500) {
                await new Promise((r) => setTimeout(r, 100));
                api = resources.appletApi || a;
              }
                if (typeof api?.setHeight === 'function' || typeof api?.setSize === 'function') {
                try { api.recalculateEnvironments?.(); } catch (e) { dbg('recalculateEnvironments failed', e); }
                try {
                  if (typeof api.setHeight === 'function') {
                    api.setHeight(measuredHeight);
                    dbg('Applied initial applet height (vscode)', measuredHeight);
                  } else {
                    api.setSize(measuredWidth, measuredHeight);
                    dbg('Applied initial applet size (vscode)', measuredWidth, measuredHeight);
                  }
                } catch (e) { dbg('api.setHeight/setSize failed', e); }
                // No timed reapply — rely on ResizeObserver and MutationObserver.
              } else {
                dbg('applet API setHeight/setSize unavailable after wait; skipping apply', { haveApi: !!api, api });
              }
            };
            attemptApplySize().catch((e) => dbg('attemptApplySize failed', e));
                // Immediately clear temporary inline dimensions and let observers handle later resizes.
            try {
              if (wrapperRootForSizing) {
                wrapperRootForSizing.style.width = '';
                wrapperRootForSizing.style.height = '';
              }
              try { applySize(); } catch (e) { /* ignore */ }
            } catch (e) { /* ignore */ }
                // No canvas mount-time polling—scaling disabled in webview.
            // Observe the injected applet node for attribute/style changes
            try {
              const appletNode = document.getElementById('ggbApplet-' + elementId) as HTMLElement | null;
              if (appletNode) {
                const aobserver = new MutationObserver(mutations => {
                  try {
                    const rect3 = (appletNode.parentElement ?? appletNode).getBoundingClientRect();
                    const ww = Math.max(1, Math.floor(rect3.width));
                    const hh = Math.max(1, Math.floor(rect3.height));
                    try {
                      const runtimeApi = resources.appletApi || a;
                      if (typeof runtimeApi?.setHeight === 'function') {
                        dbg('MutationObserver: calling setHeight (vscode) with', hh);
                        runtimeApi.setHeight(hh);
                      } else {
                        dbg('MutationObserver: calling setSize (vscode) with', ww, hh);
                        runtimeApi.setSize?.(ww, hh);
                      }
                    } catch (e) { /* ignore */ }
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
                      // If the applet contains iframes, try injecting styles there too
                      try {
                        const root = appletNode;
                        if (root) {
                          const iframes = root.querySelectorAll('iframe');
                          iframes.forEach((f: HTMLIFrameElement) => {
                            try {
                              const doc = f.contentDocument || (f as any).contentWindow?.document;
                              if (doc && doc.head) {
                                const st = doc.createElement('style');
                                st.appendChild(doc.createTextNode(css));
                                doc.head.appendChild(st);
                              }
                            } catch (e) {
                              // ignore cross-origin
                            }
                          });
                        }
                      } catch (e) { /* ignore iframe injection errors */ }
                      // Schedule a debounced reapply to adjust canvases if needed.
                      try { scheduleCanvasReapply(); } catch (e) {}
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
