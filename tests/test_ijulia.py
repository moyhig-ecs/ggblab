import json

import pytest

from ggblab_core import ijulia


def test_request_delegates(monkeypatch):
    called = {}

    def fake_request(payload, host='127.0.0.1', port=8765, timeout=10.0):
        called['payload'] = payload
        return {'ok': True, 'payload': payload}

    monkeypatch.setattr('comm_bridge.client.request', fake_request)

    payload = {'type': 'function', 'payload': {'name': 'getVersion', 'args': []}}
    resp = ijulia.request(payload, host='127.0.0.1', port=8765)
    assert resp == {'ok': True, 'payload': payload}
    assert called['payload'] == payload


def test_request_json_returns_json_string(monkeypatch):
    def fake_request(payload, host='127.0.0.1', port=8765, timeout=10.0):
        return {'reply': 'hello'}

    monkeypatch.setattr('comm_bridge.client.request', fake_request)

    j = ijulia.request_json(json.dumps({'type': 'function'}))
    parsed = json.loads(j)
    assert parsed == {'reply': 'hello'}
