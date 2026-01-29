import {
  ILayoutRestorer,
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { MainAreaWidget, WidgetTracker } from '@jupyterlab/apputils';
// ILauncher removed: launcher integration is not used in this build
import { ISettingRegistry } from '@jupyterlab/settingregistry';
//import { DockLayout } from '@lumino/widgets';

import { reactIcon } from '@jupyterlab/ui-components';
import { GeoGebraWidget } from './widget';
import {
  ServerConnection,
  KernelConnection,
  KernelManager
} from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';

// Import package.json to reflect the package version in the UI log.
import pkg from '../package.json';

namespace CommandIDs {
  export const create = 'ggblab:create';
}

// const PANEL_CLASS = 'jp-ggblabPanel';

/**
 * Initialization data for the ggblab extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'ggblab:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  optional: [ISettingRegistry, ILayoutRestorer],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null,
    restorer: ILayoutRestorer | null
  ) => {
    console.debug(`JupyterLab extension ggblab-${pkg.version} is activated!`);

    // Note: widget manager global registration removed — no global registrar
    // is installed. WidgetManager must be passed explicitly via `widgetManager`
    // in the widget creation args when available.

    // Pre-register comm targets for any kernels visible to the front-end
    // KernelManager. This helps accept `comm_open` messages that arrive
    // before a widget mounts. Factor the logic into a function so we can
    // re-run it when sessions change (e.g. kernels start/stop).
    const defaultCommTarget = 'ggblab-comm';
    const registered = new Set<string>();

    const scanAndRegisterKernels = async () => {
      console.debug('ggblab: scanAndRegisterKernels start');
      console.debug('ggblab: currently registered (start)', Array.from(registered));
      try {
        const base = PageConfig.getBaseUrl() || '/';
        const token = PageConfig.getToken();
        const serverSettings = ServerConnection.makeSettings({
          baseUrl: base,
          token,
          appendToken: true
        });

        const registerKernel = async (kid: string, model: any) => {
          console.debug('ggblab: registerKernel called', kid);
          console.debug('ggblab: registerKernel model snapshot', model && typeof model === 'object' ? { id: model.id, name: model.name } : model);
          if (!kid) {
            console.debug('ggblab: registerKernel - empty kid, skipping');
            return;
          }
          if (registered.has(kid)) {
            console.debug('ggblab: registerKernel - already registered', kid);
            return;
          }
          try {
            (window as any).__ggblab_comm_store =
              (window as any).__ggblab_comm_store || {};
            const store: any = (window as any).__ggblab_comm_store;
            // Prefer using an existing live kernel connection object when
            // the `model` argument already exposes `registerCommTarget`.
            // This ensures we attach to the same frontend-managed connection
            // that receives comm_open messages from the kernel. If `model`
            // is only a kernel model object, fall back to creating a
            // dedicated `KernelConnection` instance.
            const kernel: any = (model && typeof (model as any).registerCommTarget === 'function')
              ? model
              : new KernelConnection({ model, serverSettings });
            try {
              console.debug('ggblab: using KernelConnection for registration', { id: kernel?.id || (model && model.id) || null, hasRegister: typeof kernel.registerCommTarget === 'function' });
            } catch (ee) {
              console.debug('ggblab: unable to inspect kernel connection', ee);
            }

            console.debug('ggblab: calling registerCommTarget on KernelConnection', kid, defaultCommTarget);
            kernel.registerCommTarget(
              defaultCommTarget,
              (commOp: any, msg: any) => {
                console.debug('ggblab: registerCommTarget handler invoked', { kernelId: kid, msgSummary: msg && msg.content ? Object.keys(msg.content) : null });
                try {
                  store[kid] = commOp;
                  // Ensure by-id and queue stores exist
                  (window as any).__ggblab_comm_by_id =
                    (window as any).__ggblab_comm_by_id || {};
                  (window as any).__ggblab_comm_queue =
                    (window as any).__ggblab_comm_queue || {};

                  // Attempt to determine comm id from the incoming message or comm object
                  let commId: string | null = null;
                  try {
                    commId = (msg && msg.content && msg.content.comm_id) ||
                      (commOp && (commOp.comm_id || commOp.commId || commOp.commId)) ||
                      null;
                  } catch (ee) {
                    commId = null;
                  }

                  if (commId) {
                    try {
                      (window as any).__ggblab_comm_by_id[commId] = commOp;
                      try {
                        (window as any).__ggblab_comm_by_id[commId].__ggblab_meta = {
                          source: 'pre-registered',
                          kernelId: kid,
                          when: new Date().toISOString()
                        };
                      } catch (ee) {
                        /* ignore metadata attach errors */
                      }
                      console.debug('[ggblab] pre-registered frontend comm by id', kid, commId);
                    } catch (ee) {
                      console.warn('ggblab: failed to store comm by id', ee);
                    }
                  } else {
                    // If no comm id yet, push the open message into a queue keyed by kernel id
                    try {
                      (window as any).__ggblab_comm_queue = (window as any).__ggblab_comm_queue || {};
                      (window as any).__ggblab_comm_queue[kid] = (window as any).__ggblab_comm_queue[kid] || [];
                      (window as any).__ggblab_comm_queue[kid].push(msg || {});
                      console.debug('[ggblab] queued comm open message for kernel', kid);
                    } catch (ee) {
                      console.warn('ggblab: failed to queue comm open message', ee);
                    }
                  }

                  // Attach logging handlers to commOp for debugging
                  try {
                    const prevOnMsg = (commOp as any).onMsg;
                    (commOp as any).onMsg = (m: any) => {
                      try {
                        const now = new Date().toISOString();
                        const mid = (m && m.content && m.content.comm_id) || commId || (commOp && (commOp.comm_id || commOp.commId)) || null;
                        console.debug('[ggblab] comm.onMsg', { when: now, kernelId: kid, commId: mid, msg: m });
                      } catch (ee) {
                        console.debug('[ggblab] comm.onMsg (logging failed)', ee);
                      }
                      try {
                        if (typeof prevOnMsg === 'function') prevOnMsg(m);
                      } catch (ee) {
                        /* ignore handler errors */
                      }
                    };
                  } catch (ee) {
                    /* ignore */
                  }

                  try {
                    const prevOnClose = (commOp as any).onClose;
                    (commOp as any).onClose = (m: any) => {
                      try {
                        const now = new Date().toISOString();
                        const closedId = (m && m.content && m.content.comm_id) || commId || (commOp && (commOp.comm_id || commOp.commId)) || null;
                        console.debug('[ggblab] comm.onClose', { when: now, kernelId: kid, commId: closedId, msg: m });
                      } catch (ee) {
                        console.debug('[ggblab] comm.onClose (logging failed)', ee);
                      }
                      try {
                        if (typeof prevOnClose === 'function') prevOnClose(m);
                      } catch (ee) {
                        /* ignore */
                      }
                    };
                  } catch (ee) {
                    /* ignore */
                  }

                  console.debug('[ggblab] pre-registered frontend comm', kid);
                  try {
                    // mark the per-kernel store comm with metadata for widget lookup
                    try {
                      store[kid].__ggblab_meta = {
                        source: 'pre-registered',
                        kernelId: kid,
                        when: new Date().toISOString()
                      };
                    } catch (ee) {
                      /* ignore */
                    }
                  } catch (ee) {
                    /* ignore */
                  }
                } catch (e) {
                  console.warn('ggblab: failed to store pre-registered comm', e);
                }
              }
            );
              registered.add(kid);
              console.debug('ggblab: registerKernel - registered', kid);
              console.debug('ggblab: currently registered (after add)', Array.from(registered));
              try {
                // Attempt to create a frontend-originated "pre-warm" comm
                // so widgets mounting shortly after kernel registration
                // can reuse an already-open comm instead of recreating one.
                if (typeof kernel.createComm === 'function') {
                  try {
                    const preComm: any = kernel.createComm(defaultCommTarget);
                    try {
                      const prevOnMsg = preComm.onMsg;
                      preComm.onMsg = (m: any) => {
                        try {
                          console.debug('[ggblab] pre-warm comm.onMsg', { kernelId: kid, msg: m });
                        } catch (ee) {
                          /* ignore */
                        }
                        try {
                          if (typeof prevOnMsg === 'function') prevOnMsg(m);
                        } catch (ee) {
                          /* ignore */
                        }
                      };
                    } catch (ee) {
                      /* ignore */
                    }
                    try {
                      const prevOnClose = preComm.onClose;
                      preComm.onClose = (m: any) => {
                        try {
                          console.debug('[ggblab] pre-warm comm.onClose', { kernelId: kid, msg: m });
                        } catch (ee) {
                          /* ignore */
                        }
                        try {
                          if (typeof prevOnClose === 'function') prevOnClose(m);
                        } catch (ee) {
                          /* ignore */
                        }
                      };
                    } catch (ee) {
                      /* ignore */
                    }
                    try {
                      preComm.open && preComm.open('pre-warm from ggblab');
                    } catch (ee) {
                      /* ignore open errors */
                    }
                    try {
                      (window as any).__ggblab_comm_store = (window as any).__ggblab_comm_store || {};
                      (window as any).__ggblab_comm_store[kid] = preComm;
                    } catch (ee) {
                      /* ignore store errors */
                    }
                    try {
                      (window as any).__ggblab_comm_by_id = (window as any).__ggblab_comm_by_id || {};
                      const mid = preComm && (preComm.comm_id || preComm.commId || null);
                      if (mid) {
                        (window as any).__ggblab_comm_by_id[mid] = preComm;
                        try {
                          (window as any).__ggblab_comm_by_id[mid].__ggblab_meta = {
                            source: 'pre-warmed',
                            kernelId: kid,
                            when: new Date().toISOString()
                          };
                        } catch (ee) {
                          /* ignore */
                        }
                        console.debug('[ggblab] pre-warmed frontend comm by id', kid, mid);
                      } else {
                        console.debug('[ggblab] pre-warmed frontend comm (no id yet)', kid);
                      }
                    } catch (ee) {
                      console.warn('ggblab: failed to publish pre-warmed comm', ee);
                    }
                  } catch (ee) {
                    console.warn('ggblab: failed to create pre-warm comm', kid, ee);
                  }
                }
              } catch (ee) {
                /* ignore pre-warm pathway errors */
              }
          } catch (e) {
            console.warn('ggblab: failed to register comm target for kernel', kid, e);
          }
        };

        const km = new KernelManager({ serverSettings });
        const kmAny = km as any;
        if (typeof kmAny.listRunning === 'function') {
          const list = await kmAny.listRunning();
          console.debug('ggblab: KernelManager.listRunning returned', Array.isArray(list) ? list.length : 'non-array');
          if (Array.isArray(list)) {
            for (const k of list) {
              const kid = (k && k.id) || '';
              await registerKernel(kid, k);
            }
          }
        } else if (kmAny.running && typeof kmAny.running === 'function') {
          console.debug('ggblab: using KernelManager.running async iterator');
          for await (const k of kmAny.running()) {
            try {
              const kid = (k && (k.id as string)) || '';
              await registerKernel(kid, k);
            } catch (e) {
              /* ignore individual kernel errors */
            }
          }
        }
        // Additionally, if a serviceManager.sessions API is available use
        // session listings to detect kernels that may not yet be visible
        // through the KernelManager running list immediately after start.
        try {
          const svc = (app as any).serviceManager;
          const sessAny = svc && svc.sessions as any;
          if (sessAny) {
            console.debug('ggblab: serviceManager.sessions available - scanning sessions');
            if (typeof sessAny.listRunning === 'function') {
              const sl = await sessAny.listRunning();
              console.debug('ggblab: sessions.listRunning returned', Array.isArray(sl) ? sl.length : 'non-array');
              if (Array.isArray(sl)) {
                for (const s of sl) {
                  try {
                    const kmod = (s && (s.kernel as any)) || null;
                    const kid = (kmod && (kmod.id as string)) || '';
                    console.debug('ggblab: session entry kernel id', kid);
                    if (kid) {
                      await registerKernel(kid, kmod);
                    }
                  } catch (ee) {
                    /* ignore per-session errors */
                  }
                }
              }
            } else if (sessAny.running && typeof sessAny.running === 'function') {
              console.debug('ggblab: using sessions.running async iterator');
              for await (const s of sessAny.running()) {
                try {
                  const kmod = (s && (s.kernel as any)) || null;
                  const kid = (kmod && (kmod.id as string)) || '';
                  console.debug('ggblab: session stream kernel id', kid);
                  if (kid) {
                    await registerKernel(kid, kmod);
                  }
                } catch (ee) {
                  /* ignore per-session errors */
                }
              }
            }
          }
        } catch (ee) {
          /* ignore serviceManager.session listing errors */
        }
        console.debug('ggblab: scanAndRegisterKernels complete');
        console.debug('ggblab: currently registered (end)', Array.from(registered));
      } catch (e) {
        console.warn('ggblab: KernelManager scan failed', e);
      }
    };

    // Run initial scan
    void scanAndRegisterKernels();

    // If the app exposes a serviceManager.sessions signal, re-scan when
    // running sessions change so newly-started kernels get pre-registered.
    try {
      const svc = (app as any).serviceManager;
      if (svc) {
        // sessions.runningChanged
        if (svc.sessions && svc.sessions.runningChanged) {
          try {
            svc.sessions.runningChanged.connect(() => {
              console.debug('ggblab: sessions.runningChanged — rescanning kernels');
              void scanAndRegisterKernels();
            });
            console.debug('ggblab: connected sessions.runningChanged');
          } catch (e) {
            console.warn('ggblab: failed to connect sessions.runningChanged', e);
          }
        }

        // kernels.runningChanged (catch kernel start/stop/restart events)
        try {
          const kv = svc.kernels as any;
          if (kv && kv.runningChanged) {
            try {
              kv.runningChanged.connect(() => {
                console.debug('ggblab: kernels.runningChanged — rescanning kernels');
                void scanAndRegisterKernels();
              });
              console.debug('ggblab: connected kernels.runningChanged');
            } catch (e) {
              console.warn('ggblab: failed to connect kernels.runningChanged', e);
            }
          }
        } catch (e) {
          /* ignore kernels signal hookup errors */
        }
      }
    } catch (e) {
      /* non-fatal if serviceManager is absent */
    }

    // Auto-detection and wrapping of the jupyter-widgets manager removed.
    // The `widgetManager` must be supplied explicitly when creating widgets
    // (passed in `args.widgetManager`), if available in the host.

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.debug('ggblab settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for ggblab.', reason);
        });
    }

    const { commands } = app;

    // Tracker for created GeoGebra widgets so they can be restored after reload
    // @ts-expect-error TS2344: cross-package Lumino types can differ between
    // @jupyterlab/ui-components and @jupyterlab/apputils; ignore here and
    // prefer structural compatibility at runtime.
    const tracker = new WidgetTracker<MainAreaWidget<GeoGebraWidget>>({
      namespace: 'ggblab-tracker'
    });

    const command = CommandIDs.create;
    commands.addCommand(command, {
      caption: 'Create a new React Widget',
      label: 'React Widget',
      icon: args => (args['isPalette'] ? undefined : reactIcon),
      execute: async (args: any) => {
        console.debug('socketPath:', args['socketPath']);

        // Precompute widget id so we can detect and remove any existing panel
        const idPart = (args['kernelId'] || '').substring(0, 8);
        const widgetId = `ggblab-${idPart}`;

        // If a widget with the same id exists, close and remove it first.
        try {
          const existing = (tracker as any).find((w: any) => w.id === widgetId);
          if (existing) {
            try {
              existing.close();
            } catch (e) {
              console.warn('Failed to close existing widget:', e);
            }
            try {
              // tracker.remove may return a Promise
              await (tracker as any).remove(existing);
            } catch (e) {
              // non-fatal
              console.warn('Failed to remove existing widget from tracker:', e);
            }
          }
        } catch (e) {
          // If tracker API differs, ignore and continue
        }

        // WidgetManager must be provided explicitly via args if available.
        const widgetManager: any = args['widgetManager'] || undefined;

        // Ensure a frontend-side comm handler is registered early for the
        // requested kernel so that comm_open from the kernel will be accepted
        // even if it happens before the widget fully mounts. Store any
        // accepted comms in a global map keyed by kernel id for the widget
        // instance to consume when it mounts.
        try {
          const baseUrl = PageConfig.getBaseUrl();
          const token = PageConfig.getToken();
          const settings = ServerConnection.makeSettings({
            baseUrl,
            token,
            appendToken: true
          });
          const model = { name: 'python3', id: args['kernelId'] || '' };
          const earlyConn = new KernelConnection({
            model,
            serverSettings: settings
          });
          // create global store if missing
          (window as any).__ggblab_comm_store =
            (window as any).__ggblab_comm_store || {};
          const store: any = (window as any).__ggblab_comm_store;
          // Register a no-op handler that saves the comm object for later use
          earlyConn.registerCommTarget(
            args['commTarget'] || 'ggblab-comm',
            (commOp: any, msg: any) => {
              try {
                store[args['kernelId']] = commOp;
                console.debug(
                  'Registered early frontend comm for kernel',
                  args['kernelId']
                );
              } catch (e) {
                console.warn('Failed to store early frontend comm', e);
              }
            }
          );
        } catch (e) {
          console.warn('Failed to register early frontend comm target', e);
        }

        const content = new GeoGebraWidget({
          kernelId: args['kernelId'] || '',
          commTarget: args['commTarget'] || 'ggblab-comm',
          insertMode: args['insertMode'] || 'split-right',
          socketPath: args['socketPath'] || '',
          wsPort: args['wsPort'] || 8888,
          widgetManager: widgetManager
        });
        // @ts-expect-error TS2344: cross-package Lumino types can differ between
        // @jupyterlab/ui-components and @jupyterlab/apputils; ignore here and
        // prefer structural compatibility at runtime.
        const widget = new MainAreaWidget<GeoGebraWidget>({ content });
        // make widget id unique so restorer can identify it later
        widget.id = widgetId;
        widget.title.label = `GeoGebra (${idPart})`;
        widget.title.icon = reactIcon;

        // register with tracker so state will be saved for restoration
        try {
          await tracker.add(widget);
        } catch (e) {
          console.warn('Failed to add widget to tracker:', e);
        }

        app.shell.add(widget, 'main', {
          mode: args['insertMode'] || 'split-right'
        });
      }
    });

    // palette.addItem({
    //   command,
    //   category: "Tutorial",
    // });

    if (restorer) {
      // Note: we may in future support restoring the applet's internal
      // state from an autosave (e.g. localStorage or a persistent store).
      // That would involve fetching a saved XML/Base64 snapshot and
      // passing it through `args` or a dedicated `initialXml` prop so the
      // recreated widget can rehydrate the GeoGebra applet.
      restorer.restore(tracker, {
        command,
        // use widget.id as the saved name so it is unique per widget
        name: widget => widget.id,
        // reconstruct args (kernelId) from the saved widget id so the
        // command can recreate the widget with the same kernel association
        args: widget => {
          // Prefer to read the original creation props from the widget content
          const content: any = (widget && (widget as any).content) || {};
          const p = content.props || {};
          // Fallback to reconstructing kernelId from the widget id if not present
          const id = widget.id || '';
          const kernelId =
            p.kernelId ||
            (id.startsWith('ggblab-') ? id.slice('ggblab-'.length) : '');
          return {
            kernelId,
            commTarget: p.commTarget || '',
            socketPath: p.socketPath || '',
            wsPort: p.wsPort || 8888,
            insertMode: p.insertMode || 'split-right'
          } as any;
        }
      });
    }

    // Launcher integration removed: no launcher item will be added.
  }
};

// Export the main plugin only.
export default plugin;
