def test_applet_function_and_command_sync_simulated():
    from ggblab_core.applet import command_sync, function_sync
    from ggblab_core.kernel_comm import get_kernel_comm

    # Prepare fake comm similar to earlier test
    class FakeComm:
        def __init__(self):
            self._on_msg = None
            self.last_sent = None

        def on_msg(self, cb):
            self._on_msg = cb

        def send(self, payload):
            self.last_sent = payload

        def simulate_frontend_reply(self, data):
            import json as _json

            msg = {"content": {"data": _json.dumps(data)}}
            if self._on_msg:
                self._on_msg(msg)

    kc = get_kernel_comm()
    fake = FakeComm()
    kc.comm = fake
    fake.on_msg(kc._on_msg)

    # Test function_sync: simulate a reply
    # Start send in a thread to allow simulate
    import threading

    results = {}

    def call_fn():
        try:
            v = function_sync("getAllObjectNames", args=None, timeout=1.0)
            results["fn"] = v
        except Exception as e:
            results["err_fn"] = e

    t = threading.Thread(target=call_fn)
    t.start()

    # wait for send
    import time

    waited = 0.0
    while fake.last_sent is None and waited < 1.0:
        time.sleep(0.01)
        waited += 0.01

    assert fake.last_sent is not None
    import json as _json

    s = fake.last_sent
    if isinstance(s, str):
        s = _json.loads(s)
    sent_id = s.get("id")
    fake.simulate_frontend_reply({"id": sent_id, "value": ["A", "B"]})
    t.join(timeout=2.0)
    assert results.get("fn") == ["A", "B"]

    # Test command_sync
    results = {}
    # reset last_sent before next call
    fake.last_sent = None

    def call_cmd():
        try:
            v = command_sync("A=(0,0)", timeout=1.0)
            results["cmd"] = v
        except Exception as e:
            results["err_cmd"] = e

    t2 = threading.Thread(target=call_cmd)
    t2.start()
    waited = 0.0
    while fake.last_sent is None and waited < 1.0:
        time.sleep(0.01)
        waited += 0.01
    s2 = fake.last_sent
    if isinstance(s2, str):
        s2 = _json.loads(s2)
    sent_id = s2.get("id")
    fake.simulate_frontend_reply({"id": sent_id, "value": {"label": "A"}})
    t2.join(timeout=2.0)
    assert isinstance(results.get("cmd"), dict)
    assert results.get("cmd").get("value") == {"label": "A"}
