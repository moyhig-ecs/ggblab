import threading
import time


class FakeComm:
    def __init__(self):
        self._on_msg = None
        self.last_sent = None

    def on_msg(self, cb):
        self._on_msg = cb

    def send(self, payload):
        # record payload; caller may inspect and then simulate reply
        self.last_sent = payload

    def simulate_frontend_reply(self, data):
        # Frontend sends a JSON string in content.data
        import json as _json

        msg = {"content": {"data": _json.dumps(data)}}
        if self._on_msg:
            self._on_msg(msg)


def test_kernel_comm_send_recv_simulated():
    from ggblab_core.kernel_comm import KernelComm

    kc = KernelComm(target_name="jupyter.ggblab", timeout=2.0)
    fake = FakeComm()

    # Simulate an open from frontend
    kc._on_msg  # ensure attribute exists
    kc.comm = fake
    fake.on_msg(kc._on_msg)

    result_holder = {}

    def call_send_recv():
        try:
            res = kc.send_recv(
                {"type": "function", "payload": {"name": "ping"}}, timeout=1.0
            )
            result_holder["res"] = res
        except Exception as e:
            result_holder["err"] = e

    t = threading.Thread(target=call_send_recv)
    t.start()

    # Wait until the send has been invoked
    waited = 0.0
    while fake.last_sent is None and waited < 1.0:
        time.sleep(0.01)
        waited += 0.01

    assert fake.last_sent is not None

    # last_sent may be JSON string or dict
    import json as _json

    sent = fake.last_sent
    if isinstance(sent, str):
        sent = _json.loads(sent)
    sent_id = sent.get("id")
    # Simulate frontend reply referencing the same id
    fake.simulate_frontend_reply({"id": sent_id, "value": "pong"})

    t.join(timeout=2.0)
    assert "res" in result_holder and isinstance(result_holder["res"], dict)
    assert result_holder["res"].get("value") == "pong"
