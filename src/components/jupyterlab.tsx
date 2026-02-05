import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';
import { initKernelCommHelpers } from '../comm';

// Small utility copied from the applet to avoid circular imports
export function isArrayOfArrays(value: any): boolean {
  return Array.isArray(value) && value.every((subArray: any) => Array.isArray(subArray));
}

/**
 * Initialize JupyterLab-specific kernel resources.
 * - starts a helper kernel (kernel2)
 * - creates a KernelConnection for the target kernel id
 * - initializes kernel_comm helpers and returns the send/handler factories
 * - registers widget comm passthrough when appropriate
 */
export async function setupKernelResources(resources: any, props: any, dbg: (...args: any[]) => void) {
  let _result: any = null;

  // If requested via props or PageConfig option, clear browser storage on startup.
  // This helps remove stale widget manager state that can conflict after refactors.
  const shouldClearFromProps = !!(props && (props.clearBrowserStorageOnStartup === true || props.clearBrowserStorageOnStartup === 'true'));
  const shouldClearFromPageConfig = (() => {
    try {
      const v = PageConfig.getOption && PageConfig.getOption('ggblab.clearBrowserStorageOnStartup');
      return v === 'true';
    } catch (e) {
      return false;
    }
  })();
  const shouldClearFromGlobal = (() => {
    try {
      return !!((window as any).__ggblab_clearBrowserStorageOnStartup === true || (window as any).__ggblab_clearBrowserStorageOnStartup === 'true');
    } catch (e) {
      return false;
    }
  })();
  const shouldClear = shouldClearFromProps || shouldClearFromPageConfig || shouldClearFromGlobal;

  try {
    console.debug('ggblab: clearBrowserStorage flags', { shouldClearFromProps, shouldClearFromPageConfig, shouldClearFromGlobal, shouldClear });
  } catch (e) {}

  async function clearBrowserStorage() {
    try {
      // Determine mode: selective (default) or full when explicitly requested
      const selective = !(props && props.clearBrowserStorageFull === true);

      const defaultPatterns = [
        'ggblab',
        'widget',
        'jupyterlab-workspace',
        'jupyterlab',
        'jupyter-widgets',
        '@jupyter-widgets'
      ];
      const patterns: string[] = (props && Array.isArray(props.clearBrowserStoragePatterns) && props.clearBrowserStoragePatterns.length)
        ? props.clearBrowserStoragePatterns
        : defaultPatterns;

      const matches = (name: string | null | undefined) => {
        if (!name) return false;
        try {
          return patterns.some(p => name.toLowerCase().includes(String(p).toLowerCase()));
        } catch (e) {
          return false;
        }
      };

      // localStorage: either clear all or only keys that match patterns
      const removedLocalKeys: string[] = [];
      try {
        if (!selective) {
          try { localStorage.clear(); } catch (e) { /* ignore */ }
        } else {
          for (let i = localStorage.length - 1; i >= 0; i--) {
            const k = localStorage.key(i);
            if (k && matches(k)) {
              try { localStorage.removeItem(k); removedLocalKeys.push(k); } catch (e) { /* ignore */ }
            }
          }
        }
      } catch (e) { /* ignore */ }

      // sessionStorage: selective removal
      const removedSessionKeys: string[] = [];
      try {
        if (!selective) {
          try { sessionStorage.clear(); } catch (e) { /* ignore */ }
        } else {
          for (let i = sessionStorage.length - 1; i >= 0; i--) {
            const k = sessionStorage.key(i);
            if (k && matches(k)) {
              try { sessionStorage.removeItem(k); removedSessionKeys.push(k); } catch (e) { /* ignore */ }
            }
          }
        }
      } catch (e) { /* ignore */ }

      // indexedDB: delete databases whose name matches patterns (where supported)
      const removedIndexedDB: string[] = [];
      try {
        if (indexedDB && typeof (indexedDB as any).databases === 'function') {
          const dbs = await (indexedDB as any).databases();
          for (const d of dbs) {
            try {
              const name = d && d.name ? d.name : null;
              if (!name) continue;
              if (!selective || matches(name)) {
                try { indexedDB.deleteDatabase(name); removedIndexedDB.push(name); } catch (e) { /* ignore */ }
              }
            } catch (e) { /* ignore per-db */ }
          }
        }
      } catch (e) { /* ignore */ }

      // caches: delete caches whose key matches patterns
      const removedCaches: string[] = [];
      try {
        if (window.caches) {
          const keys = await caches.keys();
          for (const k of keys) {
            try {
              if (!selective || matches(k)) {
                const ok = await caches.delete(k);
                if (ok) { removedCaches.push(k); }
              }
            } catch (e) { /* ignore per-cache */ }
          }
        }
      } catch (e) { /* ignore */ }

      // cookies: delete cookies whose name matches patterns (best-effort)
      const removedCookies: string[] = [];
      try {
        const cookies = document.cookie ? document.cookie.split(';') : [];
        for (const c of cookies) {
          const name = c.split('=')[0]?.trim();
          if (!name) continue;
          if (!selective || matches(name)) {
            try { document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`; removedCookies.push(name); } catch (e) { /* ignore */ }
          }
        }
      } catch (e) { /* ignore */ }

      try {
        console.info('ggblab: selective browser storage clear complete', {
          removedLocalKeys,
          removedSessionKeys,
          removedIndexedDB,
          removedCaches,
          removedCookies
        });
      } catch (e) { /* ignore logging failure */ }
    } catch (e) {
      try { console.warn('ggblab: clearBrowserStorage failed', e); } catch (ee) {}
    }
  }

  if (shouldClear) {
    try { console.info('ggblab: clearBrowserStorageOnStartup active — clearing storages (selective mode default)'); } catch (e) {}
    clearBrowserStorage().catch(() => {});
  }
  
  await (async () => {
    return await KernelAPI.listRunning();
  })().then(async (kernels) => {
    // setKernels(kernels);
    dbg('Running kernels:', kernels);

    const baseUrl = PageConfig.getBaseUrl();
    const token = PageConfig.getToken();
    dbg(`Base URL: ${baseUrl}`);
    dbg(`Token: ${token}`);
    const settings = ServerConnection.makeSettings({
      baseUrl: baseUrl,
      token: token,
      appendToken: true
    });

    resources.kernelManager = new KernelManager({ serverSettings: settings });
    resources.kernel2 = await resources.kernelManager.startNew({ name: 'python3' });
    dbg('Started new kernel:', resources.kernel2, resources.kernelId);
    await resources.kernel2.requestExecute({ code: 'from websockets.sync.client import unix_connect, connect' }).done;
    // ws/socket values managed inside kernel_comm helpers
    // Initialize comm helpers from shared module
    const { callRemoteSocketSend, makeIncomingHandler } = initKernelCommHelpers(resources, dbg);

    resources.kernelConn = new KernelConnection({
      model: { name: 'python3', id: resources.kernelId || kernels[0]['id'] },
      serverSettings: settings
    });
    dbg('Connected to kernel:', resources.kernelConn);

    _result = { callRemoteSocketSend, makeIncomingHandler, kernelConn: resources.kernelConn };
  });

  // Widget comm passthrough registration is handled by the applet fallback
  // or by the optional widget-manager detection plugin. Keeping this module
  // focused on kernel/service initialization avoids duplicating registration
  // logic with `GeoGebraApplet.tsx`.

  return _result;
}

export default setupKernelResources;
