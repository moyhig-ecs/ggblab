"""jupyter_server extension — the ggblab mailbox (stage 0 v2, 2026-09-03 evening).

  POST <base>ggblab/send   {mount, request}                      kernel -> queue for that mount (localhost, server token)
  GET  <base>ggblab/poll?mount=<id>&wait=<s>                     browser long-poll -> {"requests": [...]} (queue drained)
  POST <base>ggblab/reply  {kernel_id, comm_id, req_id?, kind?, data?}
                                                                 browser -> comm_msg on the kernel's CONTROL socket (phantom comm)

Nothing here rides the kernel websocket, ipywidgets, or a comm target visible to the frontend. Browser<->server is plain
HTTP (JupyterHub/CHP friendly); server->kernel is ZMQ inside the pod.
Enable: c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
"""
from __future__ import annotations
import asyncio, collections, json, time
from tornado import web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join

_clients: dict[str, object] = {}
_boxes: dict[str, dict] = {}          # mount -> {"q": deque, "ev": asyncio.Event, "t": last activity}


def _control_client(km, kernel_id: str):
    c = _clients.get(kernel_id)
    if c is None:
        kernel = km.get_kernel(kernel_id)                      # KeyError if unknown
        c = kernel.client()
        c.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
        _clients[kernel_id] = c
    return c


def _box(mount: str) -> dict:
    b = _boxes.get(mount)
    if b is None:
        b = _boxes[mount] = {"q": collections.deque(), "ev": asyncio.Event(), "t": 0.0}
    b["t"] = time.time()
    if len(_boxes) > 512:                                      # forget the oldest idle mounts
        for k in sorted(_boxes, key=lambda k: _boxes[k]["t"])[:64]:
            _boxes.pop(k, None)
    return b


def _json_body(handler) -> dict:
    try:
        return json.loads(handler.request.body or b"{}")
    except Exception as e:
        raise web.HTTPError(400, f"bad body: {e}")


class SendHandler(JupyterHandler):
    @web.authenticated
    async def post(self):
        body = _json_body(self)
        try:
            mount, req = body["mount"], body["request"]
        except KeyError as e:
            raise web.HTTPError(400, f"missing {e}")
        b = _box(mount)
        b["q"].append(req)
        b["ev"].set()
        self.set_status(202); self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"ok": True, "queued": len(b["q"])}))


class PollHandler(JupyterHandler):
    @web.authenticated
    async def get(self):
        mount = self.get_argument("mount")
        wait = min(max(float(self.get_argument("wait", "25")), 0.0), 60.0)
        b = _box(mount)
        b["ev"].clear()                                        # clear first, then look: no lost wake-up
        if not b["q"]:
            try:
                await asyncio.wait_for(b["ev"].wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        reqs = list(b["q"]); b["q"].clear()
        self.set_header("Cache-Control", "no-store"); self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"requests": reqs}))


class ReplyHandler(JupyterHandler):
    @web.authenticated
    async def post(self):
        body = _json_body(self)
        try:
            kid, cid = body["kernel_id"], body["comm_id"]
        except KeyError as e:
            raise web.HTTPError(400, f"missing {e}")
        km = self.settings["kernel_manager"]
        try:
            client = _control_client(km, kid)
        except KeyError:
            raise web.HTTPError(404, f"no kernel {kid}")
        payload = {k: body.get(k) for k in ("req_id", "kind", "data") if k in body}
        msg = client.session.msg("comm_msg", {"comm_id": cid, "data": payload})
        client.control_channel.send(msg)
        self.set_status(202); self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"ok": True, "msg_id": msg["header"]["msg_id"]}))


def _jupyter_server_extension_points():
    return [{"module": "ggblab.host.relay"}]


def _load_jupyter_server_extension(serverapp):
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [
        (url_path_join(base, "ggblab", "send"), SendHandler),
        (url_path_join(base, "ggblab", "poll"), PollHandler),
        (url_path_join(base, "ggblab", "reply"), ReplyHandler),
    ])
    serverapp.log.info("ggblab mailbox: %s{send,poll,reply}", url_path_join(base, "ggblab/"))


load_jupyter_server_extension = _load_jupyter_server_extension
