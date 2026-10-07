"""jupyter_server extension — the ggblab mailbox, RPC form (v3, 2026-09-09; teacher's ruling (i): the phantom comm is buried).

  POST <base>ggblab/call    {mount, request, wait?}    kernel -> queue the request for that mount and PARK this HTTP request
                                                        until the browser replies (<= wait s)
                                                        -> {"status": "ok", "req_id", "data"} | {"status": "pending", "req_id"}
                                                        {timeout?} = the request's lifetime: past it, it is never handed to a
                                                        holder; {fail_fast?, grace?} = answer {"status": "no_holder"} at once
                                                        (<= grace s) when no live holder polls the box (A1, 10-07)
  GET  <base>ggblab/await?req_id=<id>&wait=<s>         kernel -> keep waiting for a parked reply (proxy-sized slices)
  GET  <base>ggblab/poll?mount=<id>&wait=<s>&client=<id>&lease=<s>
                                                        browser long-poll -> {"requests": [...], "held": bool}
                                                        (one live poller per box: the first client holds it for `lease` s;
                                                        a second client is parked up to `wait` s and takes over the moment
                                                        the holder's connection closes or its lease lapses — 2026-09-16)
  POST <base>ggblab/reply   {req_id, data} | {kind: "event", mount, data}
                                                        browser -> resolve the parked call / append to the mount's event log
  GET  <base>ggblab/events?mount=<id>&since=<seq|latest>&wait=<s>
                                                        kernel -> pull events (C1 `listen`, pull-first) -> {"events", "next"}
  POST <base>ggblab/cancel  {req_id}                   kernel -> withdraw a queued request (the kernel gave up waiting): it is
                                                        never handed to a holder (A1, 10-07) -> {"cancelled", "queued"}
  GET  <base>ggblab/boxes                               every box the server knows: holder (live?), queued, log_seq, xml_seq (A1)
  GET  <base>ggblab/whoami?kernel_id=<id>[&name=…]     kernel -> {"path", "mount"}: the box key is the DOCUMENT (stage 3)
  GET  <base>ggblab/holder?mount=<id>[&params=<json>][&deploy=<url>]
                                                        a holder that is not a notebook output (headless Chromium, app webview,
                                                        phone) -> the same div + mount.js, same-origin, no CSP sandbox (B2, 10-05)
  GET  <base>ggblab/state?mount=<id>                   the box's own copy of the state (B6, 10-05): latest XML + log of the
                                                        state-changing requests. After each such request the server asks the
                                                        holder for the XML (an xml_out of its own); a NEW holder's first poll
                                                        carries {"restore": {xml, seq}} and mount.js applies it before serving

The kernel is an HTTP client of its own server (blocking urllib on the shell thread). Nothing rides the kernel websocket,
the control socket, ipywidgets, or a comm target: the server keeps the registry (queues, parked replies, event logs).
Browser<->server is plain HTTP (JupyterHub/CHP friendly). Kernel and server are assumed to share one pod/VM.
Enable: c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
"""
from __future__ import annotations
import asyncio, collections, json, time, uuid
from html import escape as html_escape
from pathlib import Path
from typing import Any
from tornado import web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join

LEASE_DEFAULT, LEASE_MAX = 40.0, 120.0
GRACE_DEFAULT, GRACE_MAX = 2.0, 10.0   # fail_fast: how long a call waits for a holder to appear before "no_holder" (A1, 10-07)
EV_MAX = 4096                          # events kept per box; older ones are dropped and the drop is reported (A1)
STATE_KINDS = {"eval", "xml_in", "delete", "new"}   # requests that change the construction: logged, then a snapshot is taken (B6, 10-05)
SNAP_PREFIX = "snap-"                                 # req_id prefix of the server's own xml_out requests (the snapshot)
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

    def __init__(self, keep: float = KEEP, ev_max: int = EV_MAX) -> None:
        self.ev_max = ev_max
        self.boxes: dict[str, dict] = {}       # mount -> {"q", "ev", "t", "holder", "holder_t", "holder_poll", "lease", "free"}
        self.pending: dict[str, dict] = {}     # req_id -> {"fut", "t", "mount"}
        self.results: dict[str, tuple] = {}    # req_id -> (data, t): replies that arrived after the waiter left
        self.events: dict[str, dict] = {}      # mount -> {"seq", "q", "ev", "t"}
        self.keep = keep

    # -- housekeeping ------------------------------------------------------------------------------------------
    def gc(self) -> None:
        now = time.time()
        for rid in [r for r, e in self.pending.items() if now - e["t"] > self.keep or (e.get("deadline") and now > e["deadline"])]:
            self._withdraw(rid, "expired")
        for rid in [r for r, (_, t) in self.results.items() if now - t > self.keep]:
            self.results.pop(rid, None)
        if len(self.boxes) > 512:
            for k in sorted(self.boxes, key=lambda k: self.boxes[k]["t"])[:64]:
                self.boxes.pop(k, None); self.events.pop(k, None)

    def box(self, mount: str) -> dict:
        b = self.boxes.get(mount)
        if b is None:
            b = self.boxes[mount] = {"q": collections.deque(), "ev": asyncio.Event(), "t": 0.0,
                                     "holder": None, "holder_t": 0.0, "holder_poll": None, "lease": LEASE_DEFAULT,
                                     "free": asyncio.Event(),              # set when the holder releases the box
                                     "arrived": asyncio.Event(),           # set when a holder takes the box (fail_fast waits on it, A1)
                                     # B6 (10-05): the box's own copy of the state = the latest XML (restore) + the log of the
                                     # state-changing requests (replay). The XML is asked of the holder after each change.
                                     "xml": None, "xml_t": 0.0, "xml_seq": 0, "xml_by": None, "snap": None, "dirty": False,
                                     "log": collections.deque(maxlen=4096), "log_seq": 0, "restored": None}
        b["t"] = time.time()
        return b

    def _log(self, mount: str) -> dict:
        log = self.events.get(mount)
        if log is None:
            log = self.events[mount] = {"seq": 0, "q": collections.deque(maxlen=self.ev_max), "ev": asyncio.Event(), "t": 0.0,
                                        "dropped": 0}                       # events pushed out of the deque (A1: reported, not silent)
        log["t"] = time.time()
        return log

    # -- kernel side: call / await ------------------------------------------------------------------------------
    def submit(self, mount: str, request: dict, timeout: float | None = None) -> str:
        """Queue `request` for the browser holding `mount`; park a future for its reply. Returns the req_id.
        `timeout` is the request's lifetime (A1, 10-07): past `now + timeout` it is never handed to a holder — a holder that
        turns up later must not run a command the kernel stopped waiting for minutes ago."""
        self.gc()
        rid = request.get("req_id") or uuid.uuid4().hex[:12]
        request["req_id"] = rid
        b = self.box(mount)
        b["q"].append(request); b["ev"].set()
        kind = request.get("kind")
        if kind in STATE_KINDS:                                # the log = what changed the construction, in order (replay, B4)
            b["log_seq"] += 1
            b["log"].append({"seq": b["log_seq"], "t": time.time(), "request": {k: v for k, v in request.items() if k != "req_id"}})
        self.pending[rid] = {"fut": asyncio.get_running_loop().create_future(), "t": time.time(), "mount": mount, "kind": kind,
                             "deadline": (time.time() + timeout) if timeout else None}
        return rid

    # -- A1 (10-07): a request has a lifetime; a kernel can withdraw it; a call can refuse to wait for a holder ------
    def _withdraw(self, rid: str, why: str) -> dict:
        """Take `rid` out of its box's queue (if still there) and out of pending (the waiter, if any, sees {"error": why})."""
        ent = self.pending.pop(rid, None)
        queued = False
        if ent is not None:
            b = self.boxes.get(ent["mount"])
            if b is not None:
                before = len(b["q"])
                b["q"] = collections.deque(r for r in b["q"] if r.get("req_id") != rid)
                queued = len(b["q"]) != before
            if not ent["fut"].done():
                ent["fut"].set_result({"error": why})
        return {"cancelled": ent is not None, "queued": queued}

    def cancel(self, rid: str) -> dict:
        """The kernel gave up waiting (its timeout passed): the request must not run later. Returns {"cancelled", "queued"}."""
        return self._withdraw(rid, "cancelled")

    def _drain(self, b: dict) -> list[dict]:
        """Hand the holder the live requests only: an expired one (its lifetime passed while nobody held the box) or a
        withdrawn one (no pending entry) is dropped here, and the waiter — if still there — is told {"error": "expired"}."""
        now = time.time(); live = []
        for r in b["q"]:
            ent = self.pending.get(r.get("req_id"))
            if ent is None and not str(r.get("req_id", "")).startswith(SNAP_PREFIX):
                continue                                       # withdrawn by the kernel
            if ent is not None and ent.get("deadline") and now > ent["deadline"]:
                self._withdraw(r["req_id"], "expired")
                continue
            live.append(r)
        b["q"].clear()
        return live

    def has_live_holder(self, mount: str) -> bool:
        b = self.boxes.get(mount)
        return bool(b and b["holder"] and time.time() - b["holder_t"] < b["lease"])

    async def wait_holder(self, mount: str, timeout: float) -> bool:
        """True as soon as a holder polls the box; False after `timeout` s with none (fail_fast, A1)."""
        b = self.box(mount)
        if self.has_live_holder(mount):
            return True
        b["arrived"].clear()
        if self.has_live_holder(mount):
            return True
        await self._wait_any([b["arrived"]], timeout)
        return self.has_live_holder(mount)

    def summary(self) -> list[dict]:
        """GET /boxes: one row per box the server knows (for an agent or a human asking "which applets are open?")."""
        now = time.time(); out = []
        for mount, b in self.boxes.items():
            live = bool(b["holder"]) and now - b["holder_t"] < b["lease"]
            out.append({"mount": mount, "holder": live, "holder_age_s": round(now - b["holder_t"], 1) if b["holder"] else None,
                        "queued": len(b["q"]), "pending": sum(1 for e in self.pending.values() if e["mount"] == mount),
                        "log_seq": b["log_seq"], "xml_seq": b["xml_seq"], "idle_s": round(now - b["t"], 1)})
        return out

    # -- B6 (10-05): the box keeps the latest XML; a new holder is told to restore it on its first poll ------------
    def _snapshot(self, mount: str) -> None:
        """Ask the holder for the XML (an ordinary xml_out through the queue). One in flight per box; a change that lands
        while it is out marks the box dirty and another is taken when the reply arrives."""
        b = self.box(mount)
        if b["snap"]:
            b["dirty"] = True
            return
        b["dirty"] = False
        rid = SNAP_PREFIX + uuid.uuid4().hex[:10]
        self.submit(mount, {"kind": "xml_out", "req_id": rid})
        self.pending[rid]["snap"] = True
        b["snap"] = rid

    def _restore_for(self, b: dict, client: str) -> dict | None:
        """The state a holder other than the one that produced it has not been given yet (once per xml_seq per client)."""
        if not client or b["xml"] is None or client == b["xml_by"] or b["restored"] == (client, b["xml_seq"]):
            return None
        b["restored"] = (client, b["xml_seq"])
        return {"xml": b["xml"], "seq": b["xml_seq"]}

    def state(self, mount: str) -> dict:
        b = self.box(mount)
        return {"mount": mount, "xml": b["xml"], "xml_t": b["xml_t"], "xml_seq": b["xml_seq"], "holder": bool(b["holder"]),
                "log_seq": b["log_seq"], "log": list(b["log"])}

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
    @staticmethod
    def _held_by_other(b: dict, client: str, now: float) -> bool:
        return bool(b["holder"]) and b["holder"] != client and now - b["holder_t"] < b["lease"]

    @staticmethod
    async def _wait_any(events: list[asyncio.Event], timeout: float) -> None:
        """Park until one of `events` is set or `timeout` s pass (the waiters are cancelled either way)."""
        if timeout <= 0:
            return
        tasks = [asyncio.ensure_future(e.wait()) for e in events]
        try:
            await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()

    async def take_requests(self, mount: str, wait: float, client: str, lease: float,
                            poll_id: str | None = None, closed: asyncio.Event | None = None) -> dict:
        """The browser's long-poll. `poll_id` names this one HTTP request (so a late close of an OLD poll cannot release a
        NEWER one by the same client); `closed` is set by the handler when the browser went away mid-poll (tab closed):
        the parked wait ends at once, the queue is NOT drained (the next poller gets the requests), and `release()` frees
        the lease so a second tab takes over immediately instead of after lease + wait (measured 67 s on the Hub, 09-15)."""
        b = self.box(mount); now = time.time(); deadline = now + max(wait, 0.0)
        # one live poller per box: the first client holds the box. A second client is PARKED (up to `wait`) on the box's
        # `free` event and re-checks when the holder releases or the lease lapses; with wait=0 it is told `held` at once.
        parked = False
        if client:
            while self._held_by_other(b, client, now):
                left = min(deadline - now, b["holder_t"] + b["lease"] - now)
                if left <= 0 or (closed is not None and closed.is_set()):
                    return {"requests": [], "held": True, "lease": b["lease"]}
                b["free"].clear()                              # clear first, then look: no lost wake-up
                if self._held_by_other(b, client, time.time()):
                    parked = True
                    await self._wait_any([b["free"]] + ([closed] if closed is not None else []), left)
                now = time.time()
            if closed is not None and closed.is_set():         # woke because the browser left: a dead poll must not take the box
                return {"requests": [], "held": True, "lease": b["lease"], "closed": True}
            b["holder"], b["holder_t"], b["lease"], b["holder_poll"] = client, now, lease, poll_id
            b["arrived"].set()                                 # a fail_fast call parked on this box may proceed (A1)
        if parked:                                             # a take-over answers at once: the browser drops its `held` mark and re-polls
            reqs = self._drain(b)
            out = {"requests": reqs, "held": False, "lease": b["lease"]}
            r = self._restore_for(b, client)
            if r:
                out["restore"] = r
            return out
        b["ev"].clear()                                        # clear first, then look: no lost wake-up
        if not b["q"] and wait > 0:
            await self._wait_any([b["ev"]] + ([closed] if closed is not None else []), deadline - time.time())
        if closed is not None and closed.is_set():             # the browser is gone: leave the requests for the next poller
            return {"requests": [], "held": False, "lease": b["lease"], "closed": True}
        if client and b["holder"] != client:                   # the lease lapsed while parked and another tab took over
            return {"requests": [], "held": True, "lease": b["lease"]}
        reqs = self._drain(b)
        if client:
            b["holder_t"] = time.time()
        out = {"requests": reqs, "held": False, "lease": b["lease"]}
        r = self._restore_for(b, client)
        if r:
            out["restore"] = r
        return out

    def release(self, mount: str, client: str, poll_id: str | None = None) -> bool:
        """Free the box if `client` holds it through the poll `poll_id` (None = any poll of that client). Called by the
        poll handler's on_connection_close; wakes a parked second poller. Returns whether anything was released."""
        b = self.boxes.get(mount)
        if b is None or not client or b["holder"] != client or (poll_id is not None and b["holder_poll"] != poll_id):
            return False
        b["holder"], b["holder_t"], b["holder_poll"] = None, 0.0, None
        b["free"].set()
        return True

    def resolve(self, rid: str, data: Any) -> bool:
        """Deliver the browser's reply to the parked call. A reply nobody is waiting for is kept for a later `await`.
        The reply to the server's own snapshot request becomes the box's XML; the reply to a state-changing request
        triggers the next snapshot (B6)."""
        ent = self.pending.get(rid)
        if ent is not None and ent.get("snap"):
            b = self.box(ent["mount"])
            self.pending.pop(rid, None)
            if not ent["fut"].done():
                ent["fut"].set_result(data)
            if isinstance(data, str):
                b["xml"], b["xml_t"], b["xml_seq"], b["xml_by"] = data, time.time(), b["xml_seq"] + 1, b["holder"]
            b["snap"] = None
            if b["dirty"]:
                self._snapshot(ent["mount"])
            return True
        ok = False
        if ent is not None and not ent["fut"].done():
            ent["fut"].set_result(data)
            ok = True
        else:
            self.results[rid] = (data, time.time())
        if ent is not None and ent.get("kind") in STATE_KINDS:
            self._snapshot(ent["mount"])
        return ok

    # -- events: the applet's add / update / error notifications, pulled by the kernel (C1 listen) ---------------
    def push_event(self, mount: str, data: Any) -> int:
        log = self._log(mount)
        log["seq"] += 1
        if len(log["q"]) == log["q"].maxlen:
            log["dropped"] += 1                                # the oldest event falls off: counted, reported by pull_events (A1)
        log["q"].append((log["seq"], data)); log["ev"].set()
        return log["seq"]

    async def pull_events(self, mount: str, since: int | str, wait: float) -> tuple[list[dict], int, int]:
        """(events after `since`, next cursor, dropped): `dropped` > 0 means events between `since` and the oldest kept one
        fell off the box's log before this reader came for them (A1: a gap is reported, not silent)."""
        log = self._log(mount)
        if since == "latest":                                  # a new object starts from now, not from the box's birth
            return [], log["seq"], 0
        since = int(since)
        log["ev"].clear()
        items = [{"seq": s, "data": d} for s, d in log["q"] if s > since]
        if not items and wait > 0:
            try:
                await asyncio.wait_for(log["ev"].wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            items = [{"seq": s, "data": d} for s, d in log["q"] if s > since]
        first = log["q"][0][0] if log["q"] else log["seq"] + 1
        dropped = max(0, first - since - 1) if since < log["seq"] else 0
        return items, log["seq"], dropped


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
        timeout = _clamp(body["timeout"], 0.0, 3600.0) if body.get("timeout") is not None else None   # the request's lifetime (A1)
        rid = MB.submit(mount, req, timeout=timeout)
        if body.get("fail_fast") and not MB.has_live_holder(mount):   # A1: no applet polls this box -> say so within `grace` s
            grace = _clamp(body.get("grace", GRACE_DEFAULT), 0.0, GRACE_MAX)
            if not await MB.wait_holder(mount, min(wait, grace)):
                MB.cancel(rid)                                 # never run later by a holder that turns up afterwards
                self.send({"status": "no_holder", "req_id": rid, "data": None, "box": MB.state(mount) | {"log": None}})
                return
        status, data = await MB.wait_reply(rid, wait)
        self.send({"status": status, "req_id": rid, "data": data})


class CancelHandler(_Json):
    """POST cancel {req_id}: the kernel stopped waiting; the request leaves the queue and is never handed to a holder (A1)."""
    @web.authenticated
    async def post(self):
        body = _json_body(self)
        rid = body.get("req_id")
        if not rid:
            raise web.HTTPError(400, "cancel needs req_id")
        self.send({"req_id": rid, **MB.cancel(rid)})


class BoxesHandler(_Json):
    """GET boxes: every box the server knows, with whether a live holder polls it (A1)."""
    @web.authenticated
    async def get(self):
        self.send({"boxes": MB.summary()})


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
    _poll: tuple[str, str, str] | None = None            # (mount, client, poll_id) of the request in flight
    _closed: asyncio.Event | None = None

    @web.authenticated
    async def get(self):
        mount = self.get_argument("mount")
        wait = _clamp(self.get_argument("wait", "25"), 0.0, 60.0)
        client = self.get_argument("client", "")
        lease = _clamp(self.get_argument("lease", str(LEASE_DEFAULT)), 1.0, LEASE_MAX)
        self._poll, self._closed = (mount, client, uuid.uuid4().hex), asyncio.Event()
        self.send(await MB.take_requests(mount, wait, client, lease, poll_id=self._poll[2], closed=self._closed))

    def on_connection_close(self):
        """The browser dropped this poll (tab closed, page navigated): end the parked wait without draining the queue and
        free the lease at once — a second tab then takes over on its next poll instead of after lease + wait."""
        if self._closed is not None:
            self._closed.set()
        if self._poll is not None:
            MB.release(*self._poll)
        super().on_connection_close()


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
        events, nxt, dropped = await MB.pull_events(mount, since, wait)
        out = {"events": events, "next": nxt}
        if dropped:
            out["dropped"] = dropped                           # A1: the reader learns that events fell off the log
        self.send(out)


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


_HOLDER_JS = Path(__file__).with_name("mount.js")                   # the same mount.js a notebook output runs (html_host.JS)
DEPLOY_DEFAULT = "https://www.geogebra.org/apps/deployggb.js"       # = html_host.DEPLOY (kept here: relay must not import the kernel-side host)


def holder_html(base_url: str, mount: str, params: dict | None = None, deploy: str | None = None, token: str | None = None) -> str:
    """The page of a holder that is not a notebook output: a headless Chromium (B6), an app's webview, a phone's browser (B2).
    Same-origin, no CSP sandbox (the /files/ route serves with `sandbox` -> origin null -> the poll's preflight is refused; 10-02
    finding 1), one div + the same mount.js with the same cfg a notebook output gets. The page config carries baseUrl and -
    only when the page was opened with ?token=... (no login cookie) - that token, exactly as a Lab page opened with ?token= does;
    a cookie-authenticated page gets no token and mount.js falls back to the cookie + _xsrf header."""
    dom = uuid.uuid4().hex[:12]
    cfg = {"mount": mount, "dom": dom, "params": params or {}, "deploy": deploy or DEPLOY_DEFAULT}
    page_cfg = {"baseUrl": (base_url or "/")}
    if token:
        page_cfg["token"] = token
    js = _HOLDER_JS.read_text(encoding="utf-8").replace("__CFG__", json.dumps(cfg).replace("</", "<\\/"))   # a "</script>" inside a param must not end the script (A4)
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>ggblab holder {html_escape(mount)}</title>'
            f'<script id="jupyter-config-data" type="application/json">{json.dumps(page_cfg)}</script></head>'
            f'<body style="margin:0"><div id="ggb-{dom}" style="min-height:600px"></div><script>{js}</script></body></html>')


class StateHandler(_Json):
    """GET state?mount=<box key> -> the box's own copy of the state (B6): latest XML (+ when, by which holder) and the log of
    state-changing requests (replay). Read by a kernel, an agent, or a replay script; the holder is not asked."""
    @web.authenticated
    async def get(self):
        self.send(MB.state(self.get_argument("mount")))


class HolderHandler(JupyterHandler):
    """GET holder?mount=<box key>[&params=<json>][&deploy=<url>] -> an HTML page that holds the applet of that box (B2)."""
    @web.authenticated
    def get(self):
        mount = self.get_argument("mount", None)
        if not mount:
            raise web.HTTPError(400, "holder needs mount=<box key> (a kernel-less holder names its document explicitly)")
        try:
            params = json.loads(self.get_argument("params", "{}"))
        except ValueError:
            raise web.HTTPError(400, "bad params (JSON expected)")
        if not isinstance(params, dict):
            raise web.HTTPError(400, "params must be a JSON object")
        deploy = self.get_argument("deploy", None)
        if deploy and not (deploy.startswith("https://") or deploy.startswith("/")):
            raise web.HTTPError(400, "deploy must be https or a same-origin path")
        token = self.get_argument("token", None)              # present only when the page itself was opened with ?token=...
        self.set_header("Content-Type", "text/html; charset=utf-8"); self.set_header("Cache-Control", "no-store")
        self.finish(holder_html(self.settings.get("base_url", "/"), mount, params, deploy, token))


def _jupyter_server_extension_points():
    return [{"module": "ggblab.host.relay"}]


def _load_jupyter_server_extension(serverapp):
    base = serverapp.web_app.settings["base_url"]
    serverapp.web_app.add_handlers(".*$", [
        (url_path_join(base, "ggblab", "call"), CallHandler),
        (url_path_join(base, "ggblab", "await"), AwaitHandler),
        (url_path_join(base, "ggblab", "cancel"), CancelHandler),
        (url_path_join(base, "ggblab", "boxes"), BoxesHandler),
        (url_path_join(base, "ggblab", "poll"), PollHandler),
        (url_path_join(base, "ggblab", "reply"), ReplyHandler),
        (url_path_join(base, "ggblab", "events"), EventsHandler),
        (url_path_join(base, "ggblab", "whoami"), WhoAmIHandler),
        (url_path_join(base, "ggblab", "holder"), HolderHandler),
        (url_path_join(base, "ggblab", "state"), StateHandler),
    ])
    serverapp.log.info("ggblab mailbox (RPC): %s{call,await,cancel,boxes,poll,reply,events,whoami,holder,state}", url_path_join(base, "ggblab/"))


load_jupyter_server_extension = _load_jupyter_server_extension
