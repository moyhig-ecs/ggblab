"""Host adapter #2 — JupyterLab WITHOUT ipywidgets (stage 0 v2, 2026-09-03 evening; teacher's ruling).

mount: a trusted text/html output (div + inline script). The script loads deployggb.js, injects the applet into the div,
and long-polls the mailbox (relay.py) for requests over plain HTTP.
Stage 3 (2026-09-09): the mailbox address is the DOCUMENT (relay.mount_key: "doc:<notebook path>"), not the object. A page
keeps one live applet per document (later outputs and re-rendered saved outputs become pointers) and one live poller per
box (lease).
RPC (09-09, ruling (i)): the kernel is an HTTP client of its own server — `POST ggblab/call` parks until the browser's
reply arrives (`GET ggblab/await` continues in proxy-sized slices); events are pulled with `GET ggblab/events`. No comm,
no comm target, no control socket: the server is the registry. Only HTTP crosses the browser<->server boundary.
"""
from __future__ import annotations
import base64, json, os, time, uuid, urllib.parse, urllib.request
from pathlib import Path
from typing import Callable
from IPython.display import HTML, display
from .base import Request, Eval, XmlIn, XmlOut, Delete, Value, Kind, New, Png, Svg, to_json
from .control import kernel_id
from ..xml_errata import without_gui

DEPLOY = "https://www.geogebra.org/apps/deployggb.js"


class NoHolderError(TimeoutError):
    """No applet is polling the box (nothing is open in a browser, or the holder's lease lapsed): the call was withdrawn
    at once instead of waiting out `timeout` (A1, 10-07). A subclass of TimeoutError, so existing handlers still catch it."""

JS = (Path(__file__).with_name("mount.js")).read_text(encoding="utf-8")   # one JS source for every host language (stage 4: julia/host/html_host.jl reads the same file); __CFG__ is substituted at mount


def find_server(kid: str) -> tuple[str, dict]:
    """(url, headers) of the jupyter_server that owns kernel `kid`.
    Standalone: runtime jpserver-*.json (url + token). JupyterHub: JUPYTERHUB_SERVICE_URL + JUPYTERHUB_API_TOKEN (pilot pending)."""
    cands: list[tuple[str, dict]] = []
    hub_url, hub_tok = os.environ.get("JUPYTERHUB_SERVICE_URL"), os.environ.get("JUPYTERHUB_API_TOKEN")
    if hub_url and hub_tok:
        cands.append((hub_url, {"Authorization": f"token {hub_tok}"}))
    try:
        from jupyter_server.serverapp import list_running_servers
        for s in list_running_servers():
            cands.append((s["url"], {"Authorization": f"token {s['token']}"} if s.get("token") else {}))
    except Exception:
        pass
    for url, headers in cands:
        try:
            req = urllib.request.Request(url.rstrip("/") + f"/api/kernels/{kid}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    return url, headers
        except Exception:
            continue
    raise RuntimeError(f"no running jupyter_server owns kernel {kid!r} (candidates: {[u for u, _ in cands]})")


class GeoGebra:
    """Stage-0 façade (command / xml / set_xml / delete / value / new_construction / listen / events) over the HTML + mailbox host."""
    SLICE = 25.0                                                # one parked HTTP request per proxy-sized slice

    def __init__(self, mount: str | None = None, doc: str | None = None, server_url: str | None = None, token: str | None = None,
                 fail_fast: bool = True, holder_grace: float = 2.0, **params):
        """`server_url` + `token`: the jupyter_server to talk to, named explicitly — required outside a kernel (A6, 10-07:
        `find_server("")` would pick the first server that answers, which is a guess), optional inside one.
        `fail_fast`: a call on a box nobody holds returns NoHolderError within `holder_grace` s instead of waiting out its
        timeout (A1). `doc` is required outside a kernel (the box key is the document)."""
        self._listeners: list[Callable[[dict], None]] = []
        self.kernel_id = kernel_id() or ""
        self.dom_id = uuid.uuid4().hex[:12]                     # the output element of the LATEST display (mount() stamps a fresh one per display)
        self.params = params
        self.fail_fast, self.holder_grace = fail_fast, holder_grace
        self.events_dropped = 0                                 # events that fell off the box's log before we pulled them (A1)
        if server_url:
            self.server_url, self._headers = server_url, ({"Authorization": f"token {token}"} if token else {})
        elif not self.kernel_id:
            raise ValueError("outside a kernel, name the server: GeoGebra(server_url=..., token=..., doc=...) — there is no kernel to find it by")
        else:
            self.server_url, self._headers = find_server(self.kernel_id)
        if not self.kernel_id and not doc:
            raise ValueError("outside a kernel the box must be named: GeoGebra(..., doc='<document>')")
        if doc:                                                 # an agent-started kernel with no session names its document explicitly
            from .relay import mount_key
            self.path, self.mount_id = doc, mount_key(doc, self.kernel_id, mount)
        else:
            self.path, self.mount_id = self._whoami(mount)      # the mailbox address = the document (stage 3)
        self._mounted = False
        try:                                                    # events start from now, not from the box's birth
            self._event_seq = int(self._http("GET", f"/ggblab/events?mount={self._q(self.mount_id)}&since=latest&wait=0")["next"])
        except Exception:
            self._event_seq = 0

    @staticmethod
    def _q(s: str) -> str:
        return urllib.parse.quote(s, safe="")

    def _whoami(self, name: str | None) -> tuple[str | None, str]:
        """Ask the relay which document owns this kernel; the box key follows relay.mount_key (fallback: kernel id)."""
        try:
            d = self._http("GET", f"/ggblab/whoami?kernel_id={self.kernel_id}" + (f"&name={self._q(name)}" if name else ""), timeout=3)
            if d.get("path"):
                return d["path"], d["mount"]
        except Exception:
            pass
        # no session owns this kernel (e.g. a kernel started through /api/kernels by an agent): fall back to the path the
        # server put in the environment when it launched us, then to the kernel id
        from .relay import mount_key
        path = os.environ.get("JPY_SESSION_NAME") or None
        return path, mount_key(path, self.kernel_id, name)

    def _ipython_display_(self):
        self.mount()

    def mount(self) -> None:
        # One id per DISPLAY, not per object: displaying the same object twice on one page used to emit two divs with one id,
        # and the second script found the first (initialised) div and returned, leaving its own div empty (09-15 所見 2).
        # With a fresh id the later output becomes a pointer to the live applet, like a second object's output does.
        self.dom_id = uuid.uuid4().hex[:12]
        cfg = {"mount": self.mount_id, "dom": self.dom_id, "params": self.params, "deploy": DEPLOY}
        cfg_js = json.dumps(cfg).replace("</", "<\\/")   # "</script>" in a param must not end the script (A4); kept out of the
                                                        # f-string: a backslash inside {} is a SyntaxError before Python 3.12
        html = (f'<div id="ggb-{self.dom_id}" style="min-height:600px"></div>'
                f'<script>{JS.replace("__CFG__", cfg_js)}</script>')
        display(HTML(html))
        self._mounted = True

    def _http(self, method: str, path: str, body: dict | None = None, timeout: float = 5.0) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.server_url.rstrip("/") + path, data=data, method=method,
                                     headers={**self._headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def _rpc(self, req: Request, timeout: float = 10.0):
        """One request, one reply: the server parks our HTTP request until the browser answers (C2: the reply never rides
        the shell channel; the cell blocks on a socket, not on a message queue). Long waits are sliced for proxies."""
        if not self._mounted:
            self.mount()
        rid = uuid.uuid4().hex[:12]
        body = to_json(req, rid)
        t0 = time.time()
        wait = min(timeout, self.SLICE)
        d = self._http("POST", "/ggblab/call", {"mount": self.mount_id, "request": body, "wait": wait, "timeout": timeout,
                                                "fail_fast": self.fail_fast, "grace": self.holder_grace}, timeout=wait + 10)
        if d.get("status") == "no_holder":                      # A1: nobody polls the box; the request was withdrawn, not queued
            raise NoHolderError(f"no applet holds box {self.mount_id} (open the notebook's applet, or "
                                f"GET {self.server_url.rstrip('/')}/ggblab/holder?mount={self._q(self.mount_id)} in a browser)")
        while d.get("status") == "pending":
            left = timeout - (time.time() - t0)
            if left <= 0:
                try:                                            # A1: withdraw it, so a holder that turns up later never runs it
                    self._http("POST", "/ggblab/cancel", {"req_id": rid}, timeout=3)
                except Exception:
                    pass
                raise TimeoutError(f"no reply for {rid} within {timeout}s (box {self.mount_id}: is its applet open in a browser?)")
            wait = min(left, self.SLICE)
            d = self._http("GET", f"/ggblab/await?req_id={rid}&wait={wait}", timeout=wait + 10)
        return d.get("data")

    def boxes(self) -> list[dict]:
        """Every box this server knows and whether a live holder polls it (GET ggblab/boxes, A1)."""
        return self._http("GET", "/ggblab/boxes").get("boxes", [])

    def command(self, *cmds: str, timeout: float = 10.0):
        """C1 `eval`: one reply entry per command — the label string(s) GeoGebra returned, None when it refused (error modal →
        `errors()`, or a redefinition), or {"error": …} when the Apps API threw for that command (2026-09-10: e.g. TriangleCenter's
        lazy "Discrete commands not loaded yet"); the rest of the batch still runs."""
        return self._rpc(Eval(tuple(cmds)), timeout)
    def xml(self, timeout: float = 10.0) -> str:
        return self._rpc(XmlOut(), timeout)
    def png(self, scale: float = 1.0, transparent: bool = False, dpi: int = 72, timeout: float = 20.0) -> bytes:
        """The view as PNG bytes (getPNGBase64): the "paper" projection (B6, 10-05) — a still picture for a chat or a record."""
        return base64.b64decode(self._rpc(Png(scale, transparent, dpi), timeout))
    def svg(self, timeout: float = 20.0) -> str:
        """The view as SVG text (exportSVG): the same projection, scalable."""
        return self._rpc(Svg(), timeout)
    def set_xml(self, xml: str, timeout: float = 10.0, gui: bool = False):
        """C1 `xml_in`. The `<gui>` element of the document (the layout the file was saved with) is not sent, so the applet
        keeps its own layout; `gui=True` sends the document as it is."""
        return self._rpc(XmlIn(xml if gui else without_gui(xml)), timeout)
    def delete(self, label: str, timeout: float = 10.0):
        return self._rpc(Delete(label), timeout)
    def value(self, label: str, timeout: float = 10.0):
        return self._rpc(Value(label), timeout)
    def new_construction(self, timeout: float = 10.0):
        return self._rpc(New(), timeout)
    def kind(self, label: str, timeout: float = 10.0) -> str:
        """C1 read verb #8 (getObjectType): the runtime type (circle/triangle/…), which can change under drag. The static
        XML class stays in the DataFrame `Type` column (C6). Use ConstructionIO.with_kind to join {label: kind} in."""
        return self._rpc(Kind(label), timeout)

    def listen(self, cb: Callable[[dict], None], label: str | None = None) -> None:
        """C1 `listen` (v1 eg9: `listen('a')` = subscribe to one object's updates). The applet's listeners are wired once at
        mount; here a callback is registered, optionally for one label, and it is called from `events()` — pull-first
        (ruling (ii) 09-09; whether a pump is needed is judged in eg9)."""
        self._listeners.append((cb, label))

    def unlisten(self, cb: Callable[[dict], None] | None = None) -> None:
        """v1 `listen(name, False)`: drop one callback (or all)."""
        self._listeners = [] if cb is None else [(c, l) for c, l in self._listeners if c is not cb]

    def errors(self, wait: float = 0.0) -> list[dict]:
        """Pull the applet's error events (scraped from the GeoGebra modal by the page) since the last pull. Each is
        {"type":"error","title":...,"text":...}. `null` from `command()` on a bad command is disambiguated here: an
        error event means it failed; no error event means it was a redefinition (C6/§7). Shares the event cursor."""
        return [e for e in self.events(wait) if e.get("type") == "error"]

    def events(self, wait: float = 0.0) -> list[dict]:
        """Pull the applet events (add / update / error) recorded since the last pull and fan them out to the listeners.
        `wait` > 0 parks the request on the server until an event arrives (blocking pull; no thread in the kernel)."""
        d = self._http("GET", f"/ggblab/events?mount={self._q(self.mount_id)}&since={self._event_seq}&wait={wait}", timeout=wait + 10)
        evs = [e["data"] for e in d.get("events", [])]
        self.events_dropped += int(d.get("dropped", 0) or 0)   # A1: a gap in the log is counted here, never silent
        self._event_seq = int(d.get("next", self._event_seq))
        for e in evs:
            for cb, label in self._listeners:
                if label is None or e.get("label") == label:
                    try: cb(e)
                    except Exception: pass
        return evs

    def wait_update(self, label: str, timeout: float = 30.0) -> dict | None:
        """Block (in the cell) until the applet reports an update/add of `label`, or `timeout` s: the pull-side answer to
        'react to the user's manipulation' without a background thread. Returns the event, or None on timeout."""
        t0 = time.time()
        while True:
            left = timeout - (time.time() - t0)
            if left <= 0:
                return None
            for e in self.events(wait=min(left, self.SLICE)):
                if e.get("label") == label and e.get("type") in ("update", "add"):
                    return e
