// Minimal widget-manager adapter extracted from plugin/widget code.
// This module centralizes how a frontend WidgetManager (ipywidgets bridge)
// would be created or provided. For now we intentionally return `undefined`
// to preserve the previous behavior (avoiding ipywidgets interference).
// This module centralizes how a frontend WidgetManager (ipywidgets bridge)
// would be created or provided. For now we intentionally return `undefined`
// to preserve the previous behavior (avoiding ipywidgets interference).

/**
 * Opaque WidgetManager type used by the widget code when present.
 */
export type WidgetManagerType = any;
import type { IRegisterWidgetCommOptions } from './types';

/**
 * Create or obtain a WidgetManager instance.
 *
 * Note: The ggblab extension currently avoids providing a WidgetManager
 * to GeoGebra widgets by default to prevent stealing comms from
 * ipywidgets. Keep the factory here so the decision and implementation
 * can be changed in one place in future.
 */
// Internal injected manager (if any) — prefer explicit injection.
let _injectedWidgetManager: WidgetManagerType | undefined = undefined;

/**
 * Inject a WidgetManager instance from the hosting application.
 * Call this when a real ipywidgets manager is available so the
 * ggblab frontend can delegate comm routing to it.
 */
export function setWidgetManager(m?: WidgetManagerType): void {
  _injectedWidgetManager = m;
  try {
    // Also expose on global for other scripts that may want to detect it.
    (globalThis as any).__GGWIDGET_MANAGER__ = m;
    try {
      // Emit a console debug to aid runtime diagnosis when a manager is injected.
      console.debug('ggblab: setWidgetManager called', { hasManager: !!m });
    } catch (e) {
      // ignore
    }
  } catch (e) {
    // ignore
  }
}

function detectWidgetManager(): WidgetManagerType | undefined {
  const g = globalThis as any;
  // Heuristics: check well-known globals that host apps might expose.
  try {
    console.debug('ggblab: detectWidgetManager probing globals');
  } catch (e) {
    // ignore
  }
  if (g && g.__GGWIDGET_MANAGER__) {
    try { console.debug('ggblab: detected manager via __GGWIDGET_MANAGER__'); } catch (_) {}
    return g.__GGWIDGET_MANAGER__ as WidgetManagerType;
  }
  if (g && g.jupyterWidgetManager) {
    try { console.debug('ggblab: detected manager via jupyterWidgetManager'); } catch (_) {}
    return g.jupyterWidgetManager as WidgetManagerType;
  }
  if (g && g.widgetManager) {
    try { console.debug('ggblab: detected manager via widgetManager'); } catch (_) {}
    return g.widgetManager as WidgetManagerType;
  }
  try { console.debug('ggblab: no widget manager detected in globals'); } catch (_) {}
  return undefined;
}

export function createWidgetManager(): WidgetManagerType | undefined {
  // Priority: explicitly injected manager, then detected global manager.
  if (_injectedWidgetManager) {
    return _injectedWidgetManager;
  }
  return detectWidgetManager();
}

// IRegisterWidgetCommOptions is imported from ./types

/**
 * Register simple passthrough handlers for `jupyter.widget` and
 * `jupyter.widget.control` on the given `kernelConn` when no
 * `widgetManager` is present.
 *
 * Returns a cleanup function that will attempt to unregister the
 * comm targets when called.
 */
export function registerWidgetCommTargets(kernelConn: any, opts: IRegisterWidgetCommOptions): () => void {
  // Dynamically enable passthrough when no WidgetManager is available.
  // If a manager exists, avoid registering raw handlers that could
  // interfere with ipywidgets. Otherwise enable passthrough so kernel
  // comms to `jupyter.widget` are handled.
  const managerAvailable = Boolean(createWidgetManager());
  const ENABLE_WIDGET_COMM_PASSTHROUGH = !managerAvailable;

  if (!ENABLE_WIDGET_COMM_PASSTHROUGH) {
    opts.dbg && opts.dbg('Widget comm passthrough disabled: WidgetManager present');
    return () => {
      /* noop unregister */
    };
  }
  opts.dbg && opts.dbg('Widget comm passthrough enabled: no WidgetManager detected');
  const dbg = opts.dbg || (() => {});

  const simpleHandler = (commOp: any, msg: any) => {
    dbg('widget comm opened (jupyter.widget)', commOp, msg);
    try {
      commOp.onMsg = async (m: any) => {
        const content = m?.content?.data || m;
        try {
          const command = typeof content === 'string' ? JSON.parse(content) : content;
          let rmsg: any = null;
          const appletApi = opts.getAppletApi();
          if (command.type === 'command' && appletApi && typeof appletApi.evalCommandGetLabels === 'function') {
            const label = appletApi.evalCommandGetLabels(command.payload);
            rmsg = JSON.stringify({
              type: 'created',
              id: command.id,
              payload: label
            });
          } else if (command.type === 'function' && appletApi) {
            const apiName = command.payload.name;
            const args = command.payload.args;
            let value: any[] = [];
            (Array.isArray(apiName) ? apiName : [apiName]).forEach((f: string) => {
              if (typeof (opts as any).isArrayOfArrays === 'function' && (opts as any).isArrayOfArrays(args)) {
                const v2: any[] = [];
                args.forEach((a: any[]) => {
                  v2.push(typeof appletApi[f] === 'function' ? appletApi[f](...a) : null);
                });
                value.push(v2);
              } else {
                value.push(args ? (typeof appletApi[f] === 'function' ? appletApi[f](...args) : null) : typeof appletApi[f] === 'function' ? appletApi[f]() : null);
              }
            });
            value = Array.isArray(apiName) ? value : value[0];
            rmsg = JSON.stringify({
              type: 'value',
              id: command.id,
              payload: { value }
            });
          }
          if (rmsg) {
            try {
              commOp.send(rmsg);
            } catch (e) {
              dbg('commOp.send failed', e);
            }
            try {
              await opts.callRemoteSocketSend(rmsg);
            } catch (e) {
              dbg('callRemoteSocketSend failed', e);
            }
          }
        } catch (e) {
          dbg('Error handling widget comm message', e);
        }
      };
    } catch (e) {
      dbg('Failed to attach onMsg to widget comm', e);
    }
  };

  try {
    kernelConn.registerCommTarget('jupyter.widget', simpleHandler);
    kernelConn.registerCommTarget('jupyter.widget.control', simpleHandler);
  } catch (e) {
    dbg('Widget comm target registration failed', e);
  }

  return () => {
    try {
      if (typeof kernelConn.unregisterCommTarget === 'function') {
        kernelConn.unregisterCommTarget('jupyter.widget');
        kernelConn.unregisterCommTarget('jupyter.widget.control');
      }
    } catch (e) {
      dbg('Error during widget comm cleanup', e);
    }
  };
}

// -- Global registration helper ------------------------------------------------
import { KernelAPI, KernelConnection } from '@jupyterlab/services';
import { ServerConnection } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';

/**
 * Toggle whether the frontend should attach to `KernelAPI.runningChanged`
 * (or use polling) to detect new/removed kernels. Set to `false` to
 * disable dynamic detection; initial registration still runs.
 */
export const ENABLE_RUNNING_CHANGED = false;

/**
 * Register a global comm target `jupyter.ggblab` on all currently
 * running kernels by creating lightweight KernelConnection instances
 * and registering a simple handler. Returns an unregister function.
 *
 * Note: This is a pragmatic approach (B). It creates front-end KernelConnection
 * objects for each running kernel so the front-end can listen for comm opens
 * from kernels that target `jupyter.ggblab`.
 */
export async function registerGlobalGGBlabCommTargets(app?: any): Promise<() => void> {
  const baseUrl = PageConfig.getBaseUrl();
  const token = PageConfig.getToken();
  const settings = ServerConnection.makeSettings({
    baseUrl: baseUrl,
    token: token,
    appendToken: true
  });

  // Map kernelId -> unregister function
  const registry = new Map<string, () => void>();

  const dbg = (..._args: any[]) => {
    // Only emit debug logs when dynamic detection is enabled to avoid
    // noisy 'Already registered' messages during normal startup.
    if (!ENABLE_RUNNING_CHANGED) {
      return;
    }
    console.debug(..._args);
  };

  const registerKernel = (k: any) => {
    const id = k.id || k.kernelId || (k.model && k.model.id) || null;
    if (!id) {
      return;
    }
    if (registry.has(id)) {
      dbg('Already registered jupyter.ggblab for kernel', id);
      return;
    }
    try {
      // If a widget manager is available and implements a GGBlab comm
      // registration API, delegate the handler registration to it so that
      // message routing can be handled by the manager (DOM lifecycle etc.).
      const manager = createWidgetManager();
      if (manager && typeof manager.registerGGBlabHandler === 'function') {
        try {
          const unregisterFromManager = manager.registerGGBlabHandler(id, (commOp: any, msg: any) => {
            try {
              // Delegate to manager for message routing.
              // Manager may handle commOp and msg directly.
              // If it does not, manager implementors should call commOp.onMsg themselves.
            } catch (e) {
              console.warn('Error delegating jupyter.ggblab to manager', e);
            }
          });
          registry.set(id, () => {
            unregisterFromManager && unregisterFromManager();
          });
          return;
        } catch (e) {
          console.warn('Widget manager failed to register jupyter.ggblab', id, e);
        }
      }

      // Fallback: register a lightweight KernelConnection-based handler
      const kc = new KernelConnection({
        model: { name: 'python3', id },
        serverSettings: settings
      });
      try {
        kc.registerCommTarget('jupyter.ggblab', (commOp: any, msg: any) => {
          try {
            dbg('jupyter.ggblab comm opened', { kernelId: id, msg });
            commOp.onMsg = (m: any) => {
              dbg('jupyter.ggblab message', { kernelId: id, m });
            };
          } catch (e) {
            console.warn('Error in jupyter.ggblab handler', e);
          }
        });
      } catch (e) {
        console.warn('Failed to register jupyter.ggblab on kernel', id, e);
      }

      const unregister = () => {
        try {
          if (typeof (kc as any).unregisterCommTarget === 'function') {
            (kc as any).unregisterCommTarget('jupyter.ggblab');
          }
        } catch (e) {
          console.warn('Error while unregistering jupyter.ggblab', e);
        }
      };
      registry.set(id, unregister);
    } catch (e) {
      console.warn('Failed to create KernelConnection for kernel', id, e);
    }
  };

  const unregisterKernel = (id: string) => {
    const fn = registry.get(id);
    if (fn) {
      try {
        fn();
      } catch (e) {
        console.warn('Error during unregister for kernel', id, e);
      }
      registry.delete(id);
    }
  };

  // Initial registration for running kernels
  try {
    const kernels = await KernelAPI.listRunning();
    (kernels || []).forEach(registerKernel);
  } catch (e) {
    console.warn('Failed to list running kernels for ggblab registration', e);
  }

  // Watch for changes in running kernels and keep registry in sync.
  const onRunningChanged = async () => {
    try {
      const current = await KernelAPI.listRunning();
      const currentIds = new Set((current || []).map((k: any) => k.id));
      // register new
      (current || []).forEach(k => registerKernel(k));
      // unregister removed
      Array.from(registry.keys()).forEach(id => {
        if (!currentIds.has(id)) {
          unregisterKernel(id);
        }
      });
    } catch (e) {
      console.warn('Error handling runningChanged for ggblab', e);
    }
  };

  try {
    // Optionally attach to runningChanged or poll; respect global flag.
    if (ENABLE_RUNNING_CHANGED) {
      // Prefer JupyterLab's session manager signal when `app` is provided.
      try {
        if (
          app &&
          app.serviceManager &&
          app.serviceManager.sessions &&
          typeof app.serviceManager.sessions.runningChanged === 'object' &&
          typeof app.serviceManager.sessions.runningChanged.connect === 'function'
        ) {
          app.serviceManager.sessions.runningChanged.connect(onRunningChanged);
        } else if ((KernelAPI as any).runningChanged && typeof (KernelAPI as any).runningChanged.connect === 'function') {
          (KernelAPI as any).runningChanged.connect(onRunningChanged);
        } else {
          // Fallback: poll periodically (conservative) — safe but less efficient.
          const pollInterval = 5000;
          const timer = setInterval(onRunningChanged, pollInterval);
          // store a dummy unregister that clears timer
          registry.set('__poll_timer__', () => clearInterval(timer));
        }
      } catch (e) {
        console.warn('Failed to attach runningChanged listener', e);
      }
    } else {
      // Dynamic detection disabled by flag; do nothing here.
      dbg('Kernel runningChanged detection is disabled (ENABLE_RUNNING_CHANGED=false)');
    }
  } catch (e) {
    console.warn('Failed to attach runningChanged listener', e);
  }

  // Return an unregister-all function
  return () => {
    try {
      if (
        app &&
        app.serviceManager &&
        app.serviceManager.sessions &&
        typeof app.serviceManager.sessions.runningChanged === 'object' &&
        typeof app.serviceManager.sessions.runningChanged.disconnect === 'function'
      ) {
        app.serviceManager.sessions.runningChanged.disconnect(onRunningChanged as any);
      } else if ((KernelAPI as any).runningChanged && typeof (KernelAPI as any).runningChanged.disconnect === 'function') {
        (KernelAPI as any).runningChanged.disconnect(onRunningChanged as any);
      }
      // Call all unregister functions
      Array.from(registry.keys()).forEach(k => {
        const fn = registry.get(k);
        if (fn) {
          fn();
        }
      });
      registry.clear();
    } catch (e) {
      console.warn('Error during global ggblab unregister-all', e);
    }
  };
}

