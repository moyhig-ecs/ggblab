import json

from ggblab_core import ijulia


def test_request_delegates(monkeypatch):
    called = {}

    def fake_request(payload, host="127.0.0.1", port=8765, timeout=10.0):
        called["payload"] = payload
        return {"ok": True, "payload": payload}

    monkeypatch.setattr("comm_bridge.client.request", fake_request)

    payload = {"type": "function", "payload": {"name": "getVersion", "args": []}}
    resp = ijulia.request(payload, host="127.0.0.1", port=8765)
    assert resp == {"ok": True, "payload": payload}
    assert called["payload"] == payload


def test_request_json_returns_json_string(monkeypatch):
    def fake_request(payload, host="127.0.0.1", port=8765, timeout=10.0):
        return {"reply": "hello"}

    monkeypatch.setattr("comm_bridge.client.request", fake_request)

    j = ijulia.request_json(json.dumps({"type": "function"}))
    parsed = json.loads(j)
    assert parsed == {"reply": "hello"}


def test_uses_local_send_when_available(monkeypatch):
    # create a fake server module with running state and local_send
    class FakeServer:
        def get_state(self):
            return {"running": True}

        def local_send(self, payload, timeout=10.0):
            return {"local": True, "payload": payload}

    fake = FakeServer()
    # Patch ijulia's server discovery to return our fake server module
    monkeypatch.setattr("ggblab_core.ijulia._get_server_module", lambda: fake)

    # ensure client.request is not called
    called = {}

    def fake_client_request(payload, host="127.0.0.1", port=8765, timeout=10.0):
        called["client"] = True
        return {"client": True}

    monkeypatch.setattr("comm_bridge.client.request", fake_client_request)

    payload = {"type": "function", "payload": {"name": "getVersion", "args": []}}
    resp = ijulia.request(payload)
    assert resp == {"local": True, "payload": payload}
    assert "client" not in called
