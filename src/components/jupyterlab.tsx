import { ServerConnection, KernelAPI, KernelConnection, KernelManager } from '@jupyterlab/services';
import { PageConfig } from '@jupyterlab/coreutils';
import { initKernelCommHelpers } from '../comm/kernel_comm';

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
