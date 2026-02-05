import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { setWidgetManager } from './widgetManager';

/**
 * Plugin that tries to detect the jupyter-widgets manager plugins at runtime
 * and wraps their activate function to call our global registrar
 * `window.__ggblab_register_widget_manager(kernelId, manager)` when a
 * per-kernel manager instance becomes available.
 */
const registerWidgetManagerPlugin: JupyterFrontEndPlugin<void> = {
  id: 'ggblab:register-widget-manager',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    try {
      (window as any).__ggblab_register_widget_manager = function (kernelId: string, manager: any) {
        try {
          setWidgetManager(manager);
          console.debug('ggblab: __ggblab_register_widget_manager called for', kernelId);
        } catch (e) {
          console.debug('ggblab: __ggblab_register_widget_manager handler failed', e);
        }
      };
    } catch (e) {
      console.debug('ggblab: failed to define __ggblab_register_widget_manager', e);
    }

    (async () => {
      try {
        let mod: any = null;
        try {
          if (typeof (globalThis as any).require === 'function') {
            mod = (globalThis as any).require('@jupyter-widgets/jupyterlab-manager');
            console.debug('ggblab: register-widget-manager found jupyter-widgets module via global require');
          }
        } catch (e) {
          console.debug('ggblab: jupyter-widgets manager not available via global require', e);
          mod = null;
        }

        if (!mod) {
          console.debug('ggblab: jupyter-widgets manager not available for auto-plugin');
          return;
        }

        const candidates: any[] = Array.isArray(mod.default) ? mod.default : Array.isArray(mod) ? mod : [];
        console.debug('ggblab: register-widget-manager candidates count', candidates.length);

        for (const p of candidates) {
          if (!p || typeof p.activate !== 'function') {
            continue;
          }

          const origActivate = p.activate.bind(p);
          // Wrap activate to probe its args for manager instances and register them
          // with our global registrar when detected.
          // eslint-disable-next-line @typescript-eslint/ban-ts-comment
          // @ts-ignore
          p.activate = function (appArg: any, ...args: any[]) {
            console.info('ggblab: wrapped widget-manager activate called', { argsCount: args.length });
            const summaries = args.map((a: any) => {
              try { return { type: typeof a, keys: Object.keys(a || {}).slice(0, 10) }; } catch (e) { return { type: typeof a }; }
            });
            console.debug('ggblab: wrapped activate args summary', summaries);
            const result = origActivate(appArg, ...args);
            try {
              for (const a of args) {
                if (!a || typeof a !== 'object') continue;
                const isManager = typeof a.create_view === 'function' || typeof a.display_view_for_model === 'function' || !!a._create_views_for_model;
                if (!isManager) continue;
                const manager = a;
                let kernelId = '';
                try { kernelId = (manager.context && manager.context.session && manager.context.session.kernel && manager.context.session.kernel.id) || (manager.kernel && manager.kernel.id) || ''; } catch (e) { kernelId = ''; }
                if (kernelId && (window as any).__ggblab_register_widget_manager) {
                  try { (window as any).__ggblab_register_widget_manager(kernelId, manager); console.debug('ggblab: auto-registered widgetManager for kernel', kernelId); } catch (e) { console.warn('ggblab: failed to auto-register widgetManager', e); }
                  try { setWidgetManager(manager); } catch (e) { console.debug('ggblab: setWidgetManager failed', e); }
                } else if (manager && manager.context && manager.context.session) {
                  try {
                    const sess = manager.context.session;
                    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                    // @ts-ignore
                    if (sess.kernelChanged && typeof sess.kernelChanged.connect === 'function') {
                      const handler = (_s: any, kernel: any) => {
                        try {
                          const kid = kernel ? kernel.id : '';
                          if (kid && (window as any).__ggblab_register_widget_manager) {
                            (window as any).__ggblab_register_widget_manager(kid, manager);
                            console.debug('ggblab: auto-registered widgetManager on kernelChanged for', kid);
                            try { setWidgetManager(manager); } catch (e) { console.debug('ggblab: setWidgetManager failed', e); }
                            try { /* eslint-disable-next-line @typescript-eslint/ban-ts-comment */ /* @ts-ignore */ sess.kernelChanged.disconnect(handler); } catch (ee) { console.debug('ggblab: ignored', ee); }
                          }
                        } catch (ee) { console.debug('ggblab: ignored', ee); }
                      };
                      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                      // @ts-ignore
                      sess.kernelChanged.connect(handler);
                    }
                  } catch (e) { console.debug('ggblab: ignored', e); }
                }
              }
            } catch (e) { console.warn('ggblab: error while probing widget-manager activate args', e); }
            return result;
          };
        }
      } catch (e) {
        console.debug('ggblab: jupyter-widgets manager not available for auto-plugin', e);
      }
    })();
  }
};

export default registerWidgetManagerPlugin;
