"""jupyter_server extension: POST <base_url>ggblab/reply -> ipywidgets `custom` message on the kernel's CONTROL socket.

Body: {"kernel_id", "comm_id" (= the widget's model_id), "req_id"?, "kind"?, "data"?}
The kernel-side widget's on_msg receives {req_id, kind, data} on the control thread (see control.py).
Enable: c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
"""
from __future__ import annotations
import json
from tornado import web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join

_clients: dict[str, object] = {}


def _control_client(km, kernel_id: str):
    c = _clients.get(kernel_id)
    if c is None:
        kernel = km.get_kernel(kernel_id)
        c = kernel.client()
        c.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
        _clients[kernel_id] = c
    return c


class ReplyHandler(JupyterHandler):
    @web.authenticated
    async def post(self):
        try:
            body = json.loads(self.request.body or b"{}")
            kid, cid = body["kernel_id"], body["comm_id"]
        except Exception as e:
            raise web.HTTPError(400, f"bad body: {e}")
        km = self.settings["kernel_manager"]
        try:
            client = _control_client(km, kid)
        except KeyError:
            raise web.HTTPError(404, f"no kernel {kid}")
        payload = {k: body.get(k) for k in ("req_id", "kind", "data") if k in body}
        content = {"comm_id": cid, "data": {"method": "custom", "content": payload}}   # ipywidgets custom message
        msg = client.session.msg("comm_msg", content)
        client.control_channel.send(msg)
        self.set_status(202)
        self.finish(json.dumps({"ok": True, "msg_id": msg["header"]["msg_id"]}))


def _jupyter_server_extension_points():
    return [{"module": "ggblab.host.relay"}]


def _load_jupyter_server_extension(serverapp):
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [(url_path_join(base, "ggblab", "reply"), ReplyHandler)])
    serverapp.log.info("ggblab relay: POST %s", url_path_join(base, "ggblab", "reply"))


load_jupyter_server_extension = _load_jupyter_server_extension
