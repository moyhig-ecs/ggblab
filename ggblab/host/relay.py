"""jupyter_server extension: POST <base_url>ggblab/reply -> comm_msg on the kernel's CONTROL socket.

Why: browser-side JS (anywidget ESM or any output script) has no kernel connection object, but it can
fetch a same-origin endpoint (JupyterHub's proxy passes it like any other request). The server holds the
kernel's connection info, so it can speak ZMQ to the control socket directly (no proxy involved).

Enable: c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
Body:   {"kernel_id": ..., "comm_id": ..., "req_id": ..., "data": <json>}   (or kind="event")
"""
from __future__ import annotations
import json
from tornado import web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join

_clients: dict[str, object] = {}   # kernel_id -> KernelClient with only the control channel started


def _control_client(km, kernel_id: str):
    c = _clients.get(kernel_id)
    if c is None:
        kernel = km.get_kernel(kernel_id)          # raises KeyError -> 404
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
        content = {"comm_id": cid, "data": {k: body.get(k) for k in ("req_id", "kind", "data") if k in body}}
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
