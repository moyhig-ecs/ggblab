"""jupyter_server extension — the ggblab mailbox, RPC form (v3, 2026-09-09; teacher's ruling (i): the phantom comm is buried).

  POST <base>ggblab/call    {mount, request, wait?}    kernel -> queue the request for that mount and PARK this HTTP request
                                                        until the browser replies (<= wait s)
                                                        -> {"status": "ok", "req_id", "data"} | {"status": "pending", "req_id"}
  GET  <base>ggblab/await?req_id=<id>&wait=<s>         kernel -> keep waiting for a parked reply (proxy-sized slices)
  GET  <base>ggblab/poll?mount=<id>&wait=<s>&client=<id>&lease=<s>
                                                        browser long-poll -> {"requests": [...], "held": bool}
                                                        (one live poller per box: the first client holds it for `lease` s)
  POST <base>ggblab/reply   {req_id, data} | {kind: "event", mount, data}
                                                        browser -> resolve the parked call / append to the mount's event log
  GET  <base>ggblab/events?mount=<id>&since=<seq|latest>&wait=<s>
                                                        kernel -> pull events (C1 `listen`, pull-first) -> {"events", "next"}
  GET  <base>ggblab/whoami?kernel_id=<id>[&name=…]     kernel -> {"path", "mount"}: the box key is the DOCUMENT (stage 3)

The kernel is an HTTP client of its own server (blocking urllib on the shell thread). Nothing rides the kernel websocket,
the control socket, ipywidgets, or a comm target: the server keeps the registry (queues, parked replies, event logs).
Browser<->server is plain HTTP (JupyterHub/CHP friendly). Kernel and server are assumed to share one pod/VM.
Enable: c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
"""
from __future__ import annotations
import asyncio, collections, json, time, uuid
from typing import Any
from tornado import web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join

LEASE_DEFAULT, LEASE_MAX = 40.0, 120.0
WAIT_MAX = 55.0                    # one parked HTTP request never outlives a typical proxy timeout (60 s)
KEEP = 600.0                       # parked / late replies and idle boxes are forgotten after this


def mount_key(path: str | None, kernel_id: str, name: str | None = None) -> str:
    """Stage 3 (2026-09-09): the mailbox address is the DOCUMENT, not the GeoGebra() object — a notebook keeps one applet
    across kernel restarts, cell re-execution and page reloads; a second object in the same kernel is a second view of it.
    Fallback (no session, e.g. a console): the kernel id.  `name` opens a second box for the same document on purpose."""
    base = f"doc:{path}" if path else f"kernel:{kernel_id}"
    return f"{base}:{name}" if name else base


class Mailbox:
    """Server-side registry: per-mount request queue (+ poller lease), parked replies by req_id, per-mount event log."""

    def __init__(self, keep: float = KEEP) -> None:
        self.boxes: dict[str, dict] = {}       # mount -> {"q", "ev", "t", "holder", "holder_t", "lease"}
        self.pending: dict[str, dict] = {}     # req_id -> {"fut", "t", "mount"}
        self.results: dict[str, tuple] = {}    # req_id -> (data, t): replies that arrived after the waiter left
        self.events: dict[str, dict] = {}      # mount -> {"seq", "q", "ev", "t"}
        self.keep = keep

    # -- housekeeping ------------------------------------------------------------------------------------------
    def gc(self) -> None:
        now = time.time()
        for rid in [r for r, e in self.pending.items() if now - e["t"] > self.keep]:
            e = self.pending.pop(rid)
            if not e["fut"].done():
                e["fut"].cancel()
        for rid in [r for r, (_, t) in self.results.items() if now - t > self.keep]:
            self.results.pop(rid, None)
        if len(self.boxes) > 512:
            for k in sorted(self.boxes, key=lambda k: self.boxes[k]["t"])[:64]:
                self.boxes.pop(k, None); self.events.pop(k, None)

    def box(self, mount: str) -> dict:
        b = self.boxes.get(mount)
        if b is None:
            b = self.boxes[mount] = {"q": collections.deque(), "ev": asyncio.Event(), "t": 0.0, "holder": None, "holder_t": 0.0, "lease": LEASE_DEFAULT}
        b["t"] = time.time()
        return b

    def _log(self, mount: str) -> dict:
        log = self.events.get(mount)
        if log is None:
            log = self.events[mount] = {"seq": 0, "q": collections.deque(maxlen=4096), "ev": asyncio.Event(), "t": 0.0}
        log["t"] = time.time()
        return log

    # -- kernel side: call / await ------------------------------------------------------------------------------
    def submit(self, mount: str, request: dict) -> str:
        """Queue `request` for the browser holding `mount`; park a future for its reply. Returns the req_id."""
        self.gc()
        rid = request.get("req_id") or uuid.uuid4().hex[:12]
        request["req_id"] = rid
        b = self.box(mount)
        b["q"].append(request); b["ev"].set()
        self.pending[rid] = {"fut": asyncio.get_running_loop().create_future(), "t": time.time(), "mount": mount}
        return rid

    async def wait_reply(self, rid: str, wait: float) -> tuple[str, Any]:
        """("ok", data) once the browser replied; ("pending", None) after `wait` s; ("unknown", None) for a foreign id."""
        if rid in self.results:
            return "ok", self.results.pop(rid)[0]
        ent = self.pending.get(rid)
        if ent is None:
            return "unknown", None
        try:
            data = await asyncio.wait_for(asyncio.shield(ent["fut"]), timeout=max(wait, 0.0))
        except asyncio.TimeoutError:
            return "pending", None
        self.pending.pop(rid, None)
        return "ok", data

    # -- browser side: poll / reply -----------------------------------------------------------------------------
    async def take_requests(self, mount: str, wait: float, client: str, lease: float) -> dict:
        b = self.box(mount); now = time.time()
        # one live poller per box: the first client holds the box; others are told so and back off until the lease lapses
        if client:
            if b["holder"] and b["holder"] != client and now - b["holder_t"] < b["lease"]:
                return {"requests": [], "held": True, "lease": b["lease"]}
            b["holder"], b["holder_t"], b["lease"] = client, now, lease
        b["ev"].clear()                                        # clear first, then look: no lost wake-up
        if not b["q"] and wait > 0:
            try:
                await asyncio.wait_for(b["ev"].wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        reqs = list(b["q"]); b["q"].clear()
        if client:
            b["holder_t"] = time.time()
        return {"requests": reqs, "held": False, "lease": b["lease"]}

    def resolve(self, rid: str, data: Any) -> bool:
        """Deliver the browser's reply to the parked call. A reply nobody is waiting for is kept for a later `await`."""
        ent = self.pending.get(rid)
        if ent is not None and not ent["fut"].done():
            ent["fut"].set_result(data)
            return True
        self.results[rid] = (data, time.time())
        return False

    # -- events: the applet's add / update / error notifications, pulled by the kernel (C1 listen) ---------------
    def push_event(self, mount: str, data: Any) -> int:
        log = self._log(mount)
        log["seq"] += 1
        log["q"].append((log["seq"], data)); log["ev"].set()
        return log["seq"]

    async def pull_events(self, mount: str, since: int | str, wait: float) -> tuple[list[dict], int]:
        log = self._log(mount)
        if since == "latest":                                  # a new object starts from now, not from the box's birth
            return [], log["seq"]
        since = int(since)
        log["ev"].clear()
        items = [{"seq": s, "data": d} for s, d in log["q"] if s > since]
        if not items and wait > 0:
            try:
                await asyncio.wait_for(log["ev"].wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            items = [{"seq": s, "data": d} for s, d in log["q"] if s > since]
        return items, log["seq"]


MB = Mailbox()


def _json_body(handler) -> dict:
    try:
        return json.loads(handler.request.body or b"{}")
    except Exception as e:
        raise web.HTTPError(400, f"bad body: {e}")


def _clamp(v, lo, hi) -> float:
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        raise web.HTTPError(400, f"bad number: {v!r}")


class _Json(JupyterHandler):
    def send(self, obj: dict, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json"); self.set_header("Cache-Control", "no-store")
        self.finish(json.dumps(obj))


class CallHandler(_Json):
    @web.authenticated
    async def post(self):
        body = _json_body(self)
        try:
            mount, req = body["mount"], body["request"]
        except KeyError as e:
            raise web.HTTPError(400, f"missing {e}")
        wait = _clamp(body.get("wait", 25.0), 0.0, WAIT_MAX)
        rid = MB.submit(mount, req)
        status, data = await MB.wait_reply(rid, wait)
        self.send({"status": status, "req_id": rid, "data": data})


class AwaitHandler(_Json):
    @web.authenticated
    async def get(self):
        rid = self.get_argument("req_id")
        wait = _clamp(self.get_argument("wait", "25"), 0.0, WAIT_MAX)
        status, data = await MB.wait_reply(rid, wait)
        if status == "unknown":
            raise web.HTTPError(404, f"unknown req_id {rid}")
        self.send({"status": status, "req_id": rid, "data": data})


class PollHandler(_Json):
    @web.authenticated
    async def get(self):
        mount = self.get_argument("mount")
        wait = _clamp(self.get_argument("wait", "25"), 0.0, 60.0)
        client = self.get_argument("client", "")
        lease = _clamp(self.get_argument("lease", str(LEASE_DEFAULT)), 1.0, LEASE_MAX)
        self.send(await MB.take_requests(mount, wait, client, lease))


class ReplyHandler(_Json):
    @web.authenticated
    async def post(self):
        body = _json_body(self)
        if body.get("kind") == "event":
            mount = body.get("mount")
            if not mount:
                raise web.HTTPError(400, "event without mount")
            self.send({"ok": True, "seq": MB.push_event(mount, body.get("data"))}, 202)
        elif body.get("req_id"):
            self.send({"ok": True, "resolved": MB.resolve(body["req_id"], body.get("data"))}, 202)
        else:
            raise web.HTTPError(400, "reply needs req_id or kind=event")


class EventsHandler(_Json):
    @web.authenticated
    async def get(self):
        mount = self.get_argument("mount")
        since = self.get_argument("since", "0")
        wait = _clamp(self.get_argument("wait", "0"), 0.0, 60.0)
        if since != "latest":
            try:
                since = int(since)
            except ValueError:
                raise web.HTTPError(400, f"bad since: {since!r}")
        events, nxt = await MB.pull_events(mount, since, wait)
        self.send({"events": events, "next": nxt})


class WhoAmIHandler(_Json):
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
        self.send({"kernel_id": kid, "path": path, "mount": mount_key(path, kid, name)})


def _jupyter_server_extension_points():
    return [{"module": "ggblab.host.relay"}]


def _load_jupyter_server_extension(serverapp):
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [
        (url_path_join(base, "ggblab", "call"), CallHandler),
        (url_path_join(base, "ggblab", "await"), AwaitHandler),
        (url_path_join(base, "ggblab", "poll"), PollHandler),
        (url_path_join(base, "ggblab", "reply"), ReplyHandler),
        (url_path_join(base, "ggblab", "events"), EventsHandler),
        (url_path_join(base, "ggblab", "whoami"), WhoAmIHandler),
    ])
    serverapp.log.info("ggblab mailbox (RPC): %s{call,await,poll,reply,events,whoami}", url_path_join(base, "ggblab/"))


load_jupyter_server_extension = _load_jupyter_server_extension
