import React from 'react';
import { createRoot } from 'react-dom/client';
import { ServerConnection } from '@jupyterlab/services';
import GGAComponent, { IGGAWidgetProps } from '../../src/components/GGAComponent';

function App() {
  const [baseUrl, setBaseUrl] = React.useState('http://localhost:8888');
  const [token, setToken] = React.useState('');
  const [connected, setConnected] = React.useState(false);

  const connect = async () => {
    try {
      const settings = ServerConnection.makeSettings({ baseUrl, token, appendToken: true });
      // test a simple status request
      const response = await ServerConnection.makeRequest(settings, 'api', {}, {} as any);
      if (response.ok) {
        setConnected(true);
      } else {
        setConnected(false);
        console.error('Failed to connect', response.status);
      }
    } catch (e) {
      console.error(e);
      setConnected(false);
    }
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: 8, background: '#f3f3f3' }}>
        <label>Jupyter base URL: </label>
        <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} style={{ width: 300 }} />
        <label style={{ marginLeft: 8 }}>Token: </label>
        <input value={token} onChange={e => setToken(e.target.value)} style={{ width: 200 }} />
        <button onClick={connect} style={{ marginLeft: 8 }}>Connect</button>
        <span style={{ marginLeft: 12 }}>{connected ? 'Connected' : 'Disconnected'}</span>
      </div>
      <div style={{ flex: 1 }}>
        <GGAComponent kernelId={''} commTarget={''} socketPath={''} wsPort={8888} appName={'suite'} />
      </div>
    </div>
  );
}

const root = createRoot(document.getElementById('root')!);
root.render(<App />);
