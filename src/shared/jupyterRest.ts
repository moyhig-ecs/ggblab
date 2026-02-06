// Use the global `fetch` when available (browser/webview). Avoid importing
// `cross-fetch` at the top level so bundlers targeting the browser (esbuild)
// don't fail to resolve server-side polyfills. Environments that need a
// Node fetch polyfill can set `globalThis.fetch = require('cross-fetch')`
// or similar before calling these helpers.

export interface IServerSettings {
  baseUrl: string;
  token?: string;
  wsUrl?: string;
}

function apiUrl(serverSettings: IServerSettings, path: string) {
  const base = serverSettings.baseUrl.replace(/\/$/, '');
  const p = path.replace(/^\/+/, '');
  return `${base}/api/${p}`;
}

export async function restRequest(serverSettings: IServerSettings, path: string, method = 'GET', body?: any, extraHeaders: Record<string, string> = {}) {
  const url = apiUrl(serverSettings, path);
  const headers: Record<string, string> = { ...extraHeaders };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (serverSettings.token) {
    headers['Authorization'] = `token ${serverSettings.token}`;
  }

  // Prefer the global fetch (available in browsers and recent Node). If not
  // present, throw a clear error so callers can polyfill as needed.
  const fetchFn = (globalThis as any).fetch;
  if (typeof fetchFn !== 'function') {
    throw new Error('fetch is not available in this environment. Please provide a fetch shim (e.g., globalThis.fetch = require("cross-fetch")).');
  }

  const resp = await fetchFn(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`REST ${method} ${url} failed ${resp.status}: ${text}`);
  }

  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    return resp.json();
  }
  return resp.text();
}

export async function getKernelspecs(serverSettings: IServerSettings) {
  return restRequest(serverSettings, 'kernelspecs');
}

export async function listRunningKernels(serverSettings: IServerSettings) {
  return restRequest(serverSettings, 'kernels');
}

export async function startKernel(serverSettings: IServerSettings, kernelName = 'python3') {
  // POST /api/kernels { name }
  return restRequest(serverSettings, 'kernels', 'POST', { name: kernelName });
}

export async function shutdownKernel(serverSettings: IServerSettings, kernelId: string) {
  return restRequest(serverSettings, `kernels/${encodeURIComponent(kernelId)}`, 'DELETE');
}
