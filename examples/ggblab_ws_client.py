"""
Lightweight WebSocket client for use inside a Jupyter kernel to connect
to the ggblab extension WebSocket broker running on the local loopback.

Usage (in a notebook cell):

    # pip install websocket-client
    from ggblab_ws_client import GGBlabWSClient

    def handler(msg):
        print('received from broker:', msg)

    c = GGBlabWSClient('ws://127.0.0.1:PORT', token='TOK', kernel_id='YOUR_KERNEL_ID')
    c.set_message_handler(handler)
    c.start()

    # send:
    c.send({ 'type':'broker', 'to':'webview', 'payload': { 'text':'hello from kernel' } })

    # stop when done
    c.stop()

This client runs a background thread and attempts to reconnect with
exponential backoff. It uses the `websocket-client` package.
"""
# pylint: disable=broad-except,unused-argument,import-error
from __future__ import annotations
import threading
import time
import json
import traceback
from typing import Callable, Optional

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover - import may fail in some envs
    websocket = None

# Pylint: this example runs in kernels where broad exception handling,
# unused callback args, and optional imports are acceptable.
# pylint: disable=broad-except,unused-argument,import-error


class GGBlabWSClient:
    def __init__(self, url: str, token: Optional[str] = None, kernel_id: Optional[str] = None, reconnect=True):
        self.url = url
        self.token = token
        self.kernel_id = kernel_id
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._handler: Optional[Callable[[dict], None]] = None
        self._reconnect = reconnect

    def set_message_handler(self, fn: Callable[[dict], None]):
        self._handler = fn

    def start(self):
        if websocket is None:
            raise RuntimeError('websocket-client package not installed. pip install websocket-client')
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, wait: bool = False):
        self._stop.set()
        try:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
        finally:
            if wait and self._thread:
                self._thread.join(3.0)

    def send(self, obj: dict):
        s = json.dumps(obj)
        try:
            if self._ws and getattr(self._ws, 'sock', None) and getattr(self._ws.sock, 'connected', False):
                self._ws.send(s)
                return True
        except Exception:
            pass
        return False

    def _on_message(self, _ws, message):
        try:
            data = json.loads(message)
        except Exception:
            data = message
        if self._handler:
            try:
                self._handler(data)
            except Exception:
                print('ggblab handler error', traceback.format_exc())

    def _on_open(self, _ws):
        self._connected.set()
        # send hello/auth
        try:
            hello = {'type': 'hello', 'token': self.token, 'kind': 'kernel', 'kernelId': self.kernel_id}
            # send using the ws reference in run loop via self._ws when available
            try:
                if self._ws:
                    self._ws.send(json.dumps(hello))
                else:
                    _ = json.dumps(hello)
            except Exception:
                pass
        except Exception:
            pass

    def _on_close(self, _ws, _close_status_code, _close_msg):
        self._connected.clear()

    def _on_error(self, _ws, err):
        try:
            print('ggblab ws error:', err)
        except Exception:
            pass

    def _run(self):
        backoff = 0.5
        max_backoff = 10.0
        while not self._stop.is_set():
            try:
                ws = websocket.WebSocketApp(self.url,
                                            on_message=self._on_message,
                                            on_open=self._on_open,
                                            on_error=self._on_error,
                                            on_close=self._on_close)
                self._ws = ws
                # run_forever blocks until closed; use small ping_interval
                ws.run_forever(ping_interval=10, ping_timeout=5)
            except Exception as e:
                print('ggblab ws run error', e)
            # post-connection cleanup and reconnect handling
            self._connected.clear()
            if not self._reconnect or self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(max_backoff, backoff * 1.5)


if __name__ == '__main__':
    print('This module provides GGBlabWSClient for use inside kernels. Import it from your notebook.')
