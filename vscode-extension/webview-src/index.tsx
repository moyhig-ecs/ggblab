import React from 'react';
import { createRoot } from 'react-dom/client';
import { ServerConnection } from '@jupyterlab/services';
// Use a lightweight local stub for debugging to avoid bundling the
// large shared component (which pulls in additional react copies).
const GGAComponent: React.FC<any> = () => {
  return <div style={{ padding: 8 }}>GGBlab placeholder component</div>;
};

function App() {
  const [baseUrl, setBaseUrl] = React.useState('http://localhost:8888');
  const [token, setToken] = React.useState('');
  const [connected, setConnected] = React.useState(false);
  const [kernels, setKernels] = React.useState<any[]>([]);
  const [kernelName, setKernelName] = React.useState('python3');
  const [comms, setComms] = React.useState<any[]>([]);
  const [commTarget, setCommTarget] = React.useState('ggblab');
  const [commId, setCommId] = React.useState('');
  const [commMsg, setCommMsg] = React.useState('hello');
  const [currentKernelId, setCurrentKernelId] = React.useState<string | null>(null);
  const lastProxyId = React.useRef<string | null>(null);
  const [localLogs, setLocalLogs] = React.useState<string[]>([]);
  const appendLocalLog = (msg: string) => {
    setLocalLogs(prev => [...prev.slice(-200), `${new Date().toISOString()} ${msg}`]);
  };

  const vsRef = React.useRef<any>(null);
  const getVs = () => {
    if (vsRef.current) return vsRef.current;
    try {
      const a = (window as any).acquireVsCodeApi && (window as any).acquireVsCodeApi();
      vsRef.current = a;
      return a;
    } catch (e) {
      return null;
    }
  };

  const connect = async () => {
    try {
      appendLocalLog('connect invoked');
      try {
        const vs = getVs();
        if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-start', baseUrl] });
      } catch (e) {}
      // Use extension-side proxy if available to avoid CORS issues
      const apiUrl = `${baseUrl.replace(/\/$/, '')}/api`;
      try {
        const headers: any = {};
        if (token) headers['Authorization'] = `Token ${token}`;
        appendLocalLog('acquireVsCodeApi -> about to acquire');
        const vs = getVs();
        appendLocalLog('acquireVsCodeApi -> got vs=' + (!!vs));
        if (vs && vs.postMessage) {
          const reqId = String(Date.now()) + Math.random().toString(36).slice(2);
          appendLocalLog(`sending connect-request id=${reqId}`);
          try { vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-request-send', apiUrl] }); } catch (e) {}
          // also send a generic webview-log that extensions reliably log
          try { vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-request-generic', apiUrl, reqId] }); } catch (e) {}
          try { vs.postMessage({ type: 'connect-request', id: reqId, url: apiUrl, headers }); appendLocalLog('posted connect-request'); } catch (e) { appendLocalLog('failed posting connect-request ' + String(e)); }
          return;
        } else {
          appendLocalLog('vs is not available - will fallback to fetch');
        }

        // fallback to direct fetch if no proxy available
        const resp = await fetch(apiUrl, { method: 'GET', headers });
        try { const vs2 = getVs(); if (vs2 && vs2.postMessage) vs2.postMessage({ type: 'webview-log', level: 'log', args: ['fetch-status', resp.status] }); } catch (e) {}
        const text = await resp.text().catch(() => '<no-body>');
        try { const vs3 = getVs(); if (vs3 && vs3.postMessage) vs3.postMessage({ type: 'webview-log', level: 'log', args: ['fetch-body', text.slice(0, 200)] }); } catch (e) {}
        if (resp.ok) {
          setConnected(true);
          try { const vs4 = getVs(); if (vs4 && vs4.postMessage) vs4.postMessage({ type: 'webview-log', level: 'log', args: ['connect-success', resp.status] }); } catch (e) {}
        } else {
          setConnected(false);
          try { const vs5 = getVs(); if (vs5 && vs5.postMessage) vs5.postMessage({ type: 'webview-log', level: 'error', args: ['connect-failed', resp.status] }); } catch (e) {}
        }
      } catch (fetchErr) {
        try { const vs6 = getVs(); if (vs6 && vs6.postMessage) vs6.postMessage({ type: 'webview-log', level: 'error', args: ['fetch-exception', String(fetchErr)] }); } catch (e) {}
        setConnected(false);
      }
    } catch (e) {
      console.error(e);
      try { const vs = (window as any).acquireVsCodeApi && (window as any).acquireVsCodeApi(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'error', args: ['connect-exception', String(e)] }); } catch (err) {}
      setConnected(false);
    }
  };

  const probeKernels = () => {
    appendLocalLog('kernel-probe invoked');
    try {
      const vs = getVs();
      if (vs && vs.postMessage) {
        const id = String(Date.now());
        try { vs.postMessage({ type: 'webview-log', level: 'log', args: ['kernel-probe-send'] }); } catch (e) {}
        vs.postMessage({ type: 'kernel-probe', id });
      } else {
        appendLocalLog('acquireVsCodeApi not available for kernel-probe');
      }
    } catch (e) { appendLocalLog('kernel-probe exception ' + String(e)); }
  };

  const startKernel = (name?: string) => {
    const kn = name || kernelName || 'python3';
    appendLocalLog(`kernel-start invoked name=${kn}`);
    try {
      const vs = getVs();
      if (vs && vs.postMessage) {
        const id = String(Date.now());
        try { vs.postMessage({ type: 'webview-log', level: 'log', args: ['kernel-start-send', kn] }); } catch (e) {}
        vs.postMessage({ type: 'kernel-start', id, kernelName: kn });
      } else {
        appendLocalLog('acquireVsCodeApi not available for kernel-start');
      }
    } catch (e) { appendLocalLog('kernel-start exception ' + String(e)); }
  };

  // Forward webview console logs to extension host for easier debugging
  React.useEffect(() => {
    let origLog: any = null;
    let origError: any = null;
    let timer: any = null;
    let attempts = 0;

    const tryAttach = () => {
      attempts++;
      const a = getVs();
      if (!a) return false;
      vsRef.current = a;
      // attach console wrappers
      origLog = console.log.bind(console);
      origError = console.error.bind(console);
      console.log = (...args: any[]) => {
        try { a.postMessage({ type: 'webview-log', level: 'log', args }); } catch (e) {}
        try { appendLocalLog((args || []).map((x: any) => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ')); } catch (e) {}
        origLog(...args);
      };
      console.error = (...args: any[]) => {
        try { a.postMessage({ type: 'webview-log', level: 'error', args }); } catch (e) {}
        origError(...args);
      };

      // notify extension we're ready
      try { a.postMessage({ type: 'webview-ready' }); } catch (e) {}
      return true;
    };

    // try immediately, then poll briefly if not available yet
    if (!tryAttach()) {
      timer = setInterval(() => {
        if (tryAttach() || attempts > 10) {
          if (timer) { clearInterval(timer); timer = null; }
        }
      }, 200);
    }

    return () => {
      if (timer) clearInterval(timer);
      if (origLog) console.log = origLog;
      if (origError) console.error = origError;
    };
  }, []);

  // Listen for settings sent from the extension host
  React.useEffect(() => {
    const handler = (ev: MessageEvent) => {
      const msg = ev.data;
      if (!msg) return;
      // respond to extension ping
      if (msg.type === 'extension-ping') {
        try {
          const vs = getVs();
          if (vs && vs.postMessage) vs.postMessage({ type: 'webview-pong' });
        } catch (e) {}
        return;
      }

      // explicit connection status message from extension
      if (msg.type === 'connection-status') {
        appendLocalLog(`connection-status connected=${!!msg.connected} status=${msg.status}`);
        if (msg.connected) setConnected(true);
        else setConnected(false);
        return;
      }

      // WebSocket broker info from extension host
      if (msg.type === 'ws-broker') {
        appendLocalLog(`ws-broker: ${msg.url}`);
        try {
          // store broker URL in state via custom event
          (window as any).ggblabWsBrokerUrl = msg.url;
          (window as any).ggblabWsBrokerToken = msg.token || '';
          appendLocalLog('ws-broker token received');
        } catch (e) {
          appendLocalLog('ws-broker message handling failed');
        }
        return;
      }

      // handle proxy responses (legacy/auxiliary)
      if (msg.type === 'proxy-response') {
        // Process proxy responses either when they match the lastProxyId
        // or when they are initial probe responses sent by the extension
        // (ids like 'initial-...'). This lets the extension inject a
        // probe response that the UI will react to even before the
        // webview-initiated proxy request exists.
        const isInitial = typeof msg.id === 'string' && msg.id.startsWith('initial-');
        const matches = !msg.id || (lastProxyId.current && msg.id === lastProxyId.current) || isInitial;
          if (matches) {
          if (msg.error) {
            try { const vs = getVs(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'error', args: ['proxy-error', msg.error] }); } catch (e) {}
            setConnected(false);
            return;
          }
          try { const vs = getVs(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['proxy-status', msg.status] }); } catch (e) {}
          try { const vs = getVs(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['proxy-body', (msg.body || '') .slice(0,200)] }); } catch (e) {}
          appendLocalLog(`proxy-response id=${msg.id} status=${msg.status} bodylen=${(msg.body||'').length}`);
          if (msg.status && msg.status >= 200 && msg.status < 300) {
            setConnected(true);
            try { const vs = (window as any).acquireVsCodeApi && (window as any).acquireVsCodeApi(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-success', msg.status] }); } catch (e) {}
          } else {
            setConnected(false);
            try { const vs = (window as any).acquireVsCodeApi && (window as any).acquireVsCodeApi(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'error', args: ['connect-failed', msg.status] }); } catch (e) {}
          }
        }
        return;
      }
      // kernel probe/start responses
      if (msg.type === 'kernel-probe-response') {
        appendLocalLog(`kernel-probe-response id=${msg.id} status=${msg.status || 'err'} bodylen=${(msg.body||'').length || 0}`);
        if (msg.error) {
          appendLocalLog(`kernel-probe-error: ${msg.error}`);
        } else {
          try {
            const list = JSON.parse(msg.body || '[]');
            setKernels(list);
            appendLocalLog(`kernels: ${list.length}`);
          } catch (e) {
            appendLocalLog('kernel-probe parse error ' + String(e));
          }
        }
        return;
      }
      if (msg.type === 'kernel-start-response') {
        appendLocalLog(`kernel-start-response id=${msg.id} status=${msg.status || 'err'}`);
        if (msg.error) appendLocalLog(`kernel-start-error: ${msg.error}`);
        else {
          appendLocalLog(`kernel-start body: ${(msg.body||'').slice(0,200)}`);
          try {
            const body = JSON.parse(msg.body || '{}');
            if (body && body.id) {
              setCurrentKernelId(body.id);
              setKernels(prev => [body, ...prev]);
              appendLocalLog(`active kernel id set: ${body.id}`);
            }
          } catch (e) {
            appendLocalLog('kernel-start parse error ' + String(e));
          }
        }
        return;
      }
      // comm events from extension (kernel -> webview)
      if (msg.type === 'comm-open' || msg.type === 'comm-msg' || msg.type === 'comm-close') {
        appendLocalLog(`kernel->webview ${msg.type} kernel=${msg.kernelId} comm=${msg.commId} target=${msg.target} data=${JSON.stringify(msg.data)}`);
        setComms(prev => [...prev, { type: msg.type, kernelId: msg.kernelId, commId: msg.commId, target: msg.target, data: msg.data }]);
        return;
      }
      if (msg.type === 'comm-open-response' || msg.type === 'comm-msg-response') {
        appendLocalLog(`${msg.type} id=${msg.id} status=${msg.status || ''} error=${msg.error || ''}`);
        return;
      }

      if (msg.type !== 'jupyter-settings') return;
      if (msg.baseUrl) setBaseUrl(msg.baseUrl);
      if (msg.token) setToken(msg.token);
      // auto-connect when settings received
      setTimeout(() => connect(), 100);
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [baseUrl, token]);

  // Attach a DOM-level click listener to the connect button so we always
  // receive a message even if React events are broken (helps diagnose synthetic
  // event issues / duplicate-React runtime problems).
  React.useEffect(() => {
    const el = document.getElementById('ggblab-connect-btn');
    if (!el) return;
    const handler = () => {
      try { const vs = getVs(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-clicked-dom'] }); } catch (e) {}
    };
    el.addEventListener('click', handler);
    return () => el.removeEventListener('click', handler);
  }, []);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: 8, background: '#f3f3f3' }}>
        <label>Jupyter base URL: </label>
        <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} style={{ width: 300 }} />
        <label style={{ marginLeft: 8 }}>Token: </label>
        <input value={token} onChange={e => setToken(e.target.value)} style={{ width: 200 }} />
        <button id="ggblab-connect-btn" onClick={() => { try { const vs = getVs(); if (vs && vs.postMessage) vs.postMessage({ type: 'webview-log', level: 'log', args: ['connect-clicked'] }); } catch (e) {} ; connect(); }} style={{ marginLeft: 8 }}>Connect</button>
        <button onClick={() => { appendLocalLog('force-connect clicked'); setConnected(true); }} style={{ marginLeft: 8 }}>Force Connected</button>
        <label style={{ marginLeft: 12 }}>Kernel: </label>
        <input value={kernelName} onChange={e => setKernelName(e.target.value)} style={{ width: 140, marginLeft: 6 }} />
        <button onClick={() => probeKernels()} style={{ marginLeft: 8 }}>Probe Kernels</button>
        <button onClick={() => startKernel()} style={{ marginLeft: 8 }}>Start Kernel</button>
        <label style={{ marginLeft: 12 }}>Comm target:</label>
        <input value={commTarget} onChange={e => setCommTarget(e.target.value)} style={{ width: 120, marginLeft: 6 }} />
        <input placeholder="commId (opt)" value={commId} onChange={e => setCommId(e.target.value)} style={{ width: 160, marginLeft: 6 }} />
        <button onClick={() => {
          try {
            const vs = getVs();
            if (vs && vs.postMessage) {
              const id = String(Date.now());
              const kid = currentKernelId || (kernels[0] && kernels[0].id) || undefined;
              const chosenCommId = commId && commId.length ? commId : `comm-${Date.now().toString(36).slice(2)}`;
              vs.postMessage({ type: 'webview-log', level: 'log', args: ['comm-open-send', commTarget, chosenCommId] });
              vs.postMessage({ type: 'comm-open', id, kernelId: kid, target: commTarget, commId: chosenCommId, data: {} });
              setCommId(chosenCommId);
              appendLocalLog('comm-open sent');
            }
          } catch (e) { appendLocalLog('comm-open error ' + String(e)); }
        }} style={{ marginLeft: 8 }}>Open Comm</button>
        <input value={commMsg} onChange={e => setCommMsg(e.target.value)} style={{ width: 220, marginLeft: 8 }} />
        <button onClick={() => {
          try {
            const vs = getVs();
            if (vs && vs.postMessage) {
              const id = String(Date.now());
              const kid = currentKernelId || (kernels[0] && kernels[0].id) || undefined;
              vs.postMessage({ type: 'webview-log', level: 'log', args: ['comm-msg-send', commId, commMsg] });
              vs.postMessage({ type: 'comm-msg', id, kernelId: kid, commId: commId, data: { text: commMsg } });
              appendLocalLog('comm-msg sent');
            }
          } catch (e) { appendLocalLog('comm-msg error ' + String(e)); }
        }} style={{ marginLeft: 8 }}>Send Comm Msg</button>
        <span style={{ marginLeft: 12 }}>{connected ? 'Connected' : 'Disconnected'}</span>
      </div>
      <div style={{ height: 140, overflow: 'auto', background: '#111', color: '#dcdcdc', fontFamily: 'monospace', padding: 8 }}>
        <div style={{ fontSize: 12, marginBottom: 6, color: '#9cdcfe' }}>Debug log (local)</div>
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{localLogs.join('\n')}</pre>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ padding: 8 }}>
          <div style={{ marginBottom: 8 }}>
            <strong>Available kernels:</strong> {kernels.length}
          </div>
          <pre style={{ background: '#f6f6f6', padding: 8, height: 240, overflow: 'auto' }}>{JSON.stringify(kernels, null, 2)}</pre>
        </div>
        <GGAComponent kernelId={''} commTarget={''} socketPath={''} wsPort={8888} appName={'suite'} />
      </div>
    </div>
  );
}

const root = createRoot(document.getElementById('root')!);
root.render(<App />);
