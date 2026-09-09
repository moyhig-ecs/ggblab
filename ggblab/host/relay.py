"""jupyter_server extension — the ggblab mailbox (stage 0 v2, 2026-09-03 evening).

  POST <base>ggblab/send   {mount, request}                      kernel -> queue for that mount (localhost, server token)
  GET  <base>ggblab/poll?mount=<id>&wait=<s>&client=<id>&lease=<s>  browser long-poll -> {"requests": [...], "held": bool}
                                                                 (one live poller per box: the first client holds it for `lease` s)
  GET  <base>ggblab/whoami?kernel_id=<id>[&name=…]               kernel -> {"path", "mount"}: the box key is the DOCUMENT (stage 3)
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
_boxes: dict[str, dict] = {}          # mount -> {"q": deque, "ev": asyncio.Event, "t": last activity, "holder": client id, "holder_t": last poll of the holder, "lease": s}
LEASE_DEFAULT, LEASE_MAX = 40.0, 120.0


def mount_key(path: str | None, kernel_id: str, name: str | None = None) -> str:
    """Stage 3 (2026-09-09): the mailbox address is the DOCUMENT, not the GeoGebra() object — a notebook keeps one applet
    across kernel restarts, cell re-execution and page reloads; a second object in the same kernel is a second view of it.
    Fallback (no session, e.g. a console): the kernel id.  `name` opens a second box for the same document on purpose."""
    base = f"doc:{path}" if path else f"kernel:{kernel_id}"
    return f"{base}:{name}" if name else base


def _session_path(sm, kernel_id: str) -> str | None:
    """Notebook path of the session that owns `kernel_id` (None if the kernel has no session)."""
    try:
        for sess in sm.list_sessions_sync() if hasattr(sm, "list_sessions_sync") else []:
            if sess.get("kernel", {}).get("id") == kernel_id:
                return sess.get("path")
    except Exception:
        pass
    return None


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
        b = _boxes[mount] = {"q": collections.deque(), "ev": asyncio.Event(), "t": 0.0, "holder": None, "holder_t": 0.0, "lease": LEASE_DEFAULT}
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


class WhoAmIHandler(JupyterHandler):
    """GET whoami?kernel_id=… → {"path": notebook path or null, "mount": the box key}. The kernel asks this once at construction."""
    @web.authenticated
    async def get(self):
        kid = self.get_argument("kernel_id"); name = self.get_argument("name", None)
        path = None
        sm = self.settings.get("session_manager")
        if sm is not None:
            try:
                for sess in await sm.list_sessions():
                    if sess.get("kernel", {}).get("id") == kid:
                        path = sess.get("path"); break
            except Exception:
                path = None
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"kernel_id": kid, "path": path, "mount": mount_key(path, kid, name)}))


class PollHandler(JupyterHandler):
    @web.authenticated
    async def get(self):
        mount = self.get_argument("mount")
        wait = min(max(float(self.get_argument("wait", "25")), 0.0), 60.0)
        client = self.get_argument("client", "")
        lease = min(max(float(self.get_argument("lease", str(LEASE_DEFAULT))), 1.0), LEASE_MAX)
        b = _box(mount); now = time.time()
        # one live poller per box: the first client holds the box; others are told so and back off until the lease lapses
        if client:
            if b["holder"] and b["holder"] != client and now - b["holder_t"] < b["lease"]:
                self.set_header("Cache-Control", "no-store"); self.set_header("Content-Type", "application/json")
                self.finish(json.dumps({"requests": [], "held": True, "lease": b["lease"]})); return
            b["holder"], b["holder_t"], b["lease"] = client, now, lease
        b["ev"].clear()                                        # clear first, then look: no lost wake-up
        if not b["q"]:
            try:
                await asyncio.wait_for(b["ev"].wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        reqs = list(b["q"]); b["q"].clear()
        if client:
            b["holder_t"] = time.time()
        self.set_header("Cache-Control", "no-store"); self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"requests": reqs, "held": False}))


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
        (url_path_join(base, "ggblab", "whoami"), WhoAmIHandler),
    ])
    serverapp.log.info("ggblab mailbox: %s{send,poll,reply}", url_path_join(base, "ggblab/"))


load_jupyter_server_extension = _load_jupyter_server_extension
