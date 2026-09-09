"""Host adapter #2 — JupyterLab WITHOUT ipywidgets (stage 0 v2, 2026-09-03 evening; teacher's ruling).

mount: a trusted text/html output (div + inline script). The script loads deployggb.js, injects the applet into the div,
and long-polls the mailbox (relay.py) for requests over plain HTTP.
Stage 3 (2026-09-09): the mailbox address is the DOCUMENT (relay.mount_key: "doc:<notebook path>"), not the object. A page
keeps one live applet per document (later outputs and re-rendered saved outputs become pointers), one live poller per box
(lease), and every request carries `reply_to` so an applet mounted by an earlier kernel serves a later kernel's objects. Replies/events are POSTed back; the server injects
them into the kernel's phantom comm through the control socket (control.py). The kernel talks to the server over
localhost HTTP with the server's own token. Only HTTP crosses the browser<->server boundary.
"""
from __future__ import annotations
import json, os, uuid, urllib.request
from typing import Callable
from IPython.display import HTML, display
from .base import Request, Eval, XmlIn, XmlOut, Delete, Value, New, to_json
from .control import ControlBridge, kernel_id

DEPLOY = "https://www.geogebra.org/apps/deployggb.js"

JS = r"""
(function () {
  const M = __CFG__;
  const el = document.getElementById("ggb-" + M.dom);
  if (!el || el.__ggblab) return;
  el.__ggblab = true;
  // stage 3: one live applet per document. If this page already holds an applet for M.mount (an earlier output, a saved
  // output re-rendered on reload), this output becomes a pointer to it instead of a second applet + second poller.
  window.__ggblabBoxes = window.__ggblabBoxes || {};
  const prev = window.__ggblabBoxes[M.mount];
  if (prev && prev.el && document.contains(prev.el) && prev.el !== el) {
    el.style.minHeight = "0"; el.innerHTML = '<div style="font:12px system-ui;color:#666;padding:4px 6px;border-left:3px solid #ccc">ggblab: the applet for this notebook is already mounted above (' + M.mount + ') — <a href="#" onclick="event.preventDefault(); this.closest(\'body\').querySelector(\'#ggb-\' + window.__ggblabBoxes[' + JSON.stringify(M.mount) + '].dom).scrollIntoView({behavior:\'smooth\'})">show</a></div>';
    return;
  }
  window.__ggblabBoxes[M.mount] = {el, dom: M.dom};
  const clientId = (window.__ggblabClient = window.__ggblabClient || Math.random().toString(16).slice(2));
  let route = {kernel_id: M.kernel_id, comm_id: M.comm_id};   // where replies/events go: updated from each request (reply_to)
  const base = ((document.body && document.body.dataset && document.body.dataset.baseUrl) || "/").replace(/\/$/, "");
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  function xsrf() { const m = document.cookie.match(/(?:^|; )_xsrf=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function post(payload, to) {
    return fetch(base + "/ggblab/reply", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-XSRFToken": xsrf()},
      body: JSON.stringify(Object.assign({}, to || route, payload))});
  }
  function handle(api, req) {                       // C3: one clause per head; unknown kind -> explicit error
    switch (req.kind) {
      case "eval":    return req.commands.map(c => api.evalCommandGetLabels(c));
      case "xml_in":  api.setXML(req.xml); return true;
      case "xml_out": return api.getXML();
      case "delete":  api.deleteObject(req.label); return true;
      case "value":   return api.getValue(req.label);
      case "new":     api.newConstruction(); return true;
      case "listen":  return true;                  // listeners are wired once at mount
      default: throw new Error("unhandled request kind: " + req.kind);
    }
  }
  let api = null; const queue = [];                 // C2: requests wait here until the applet is ready
  async function serve(req) {
    if (req.reply_to && req.reply_to.kernel_id) route = req.reply_to;     // a newer kernel object took the document over
    const to = req.reply_to || route;
    try { await post({req_id: req.req_id, data: handle(api, req)}, to); }
    catch (e) { await post({req_id: req.req_id, data: {error: String(e)}}, to); }
  }
  let held = false;
  async function pollLoop() {                       // plain HTTP long-poll; survives proxies, needs no WebSocket
    for (;;) {
      try {
        const r = await fetch(base + "/ggblab/poll?mount=" + encodeURIComponent(M.mount) + "&wait=25&client=" + clientId + "&lease=40", {credentials: "same-origin", cache: "no-store"});
        if (r.status === 200) {
          const j = await r.json();
          if (j.held) { if (!held) { held = true; el.dataset.ggblabHeld = "1"; } await sleep(10000); continue; }   // another tab holds it; retry after the lease lapses
          if (held) { held = false; delete el.dataset.ggblabHeld; }
          for (const req of (j.requests || [])) { if (api) serve(req); else queue.push(req); }
        }
        else await sleep(1000);
      } catch (e) { await sleep(1000); }
    }
  }
  function loadScript() {
    if (window.__ggblabDeploy) return window.__ggblabDeploy;
    window.__ggblabDeploy = new Promise((res, rej) => {
      if (window.GGBApplet) return res();
      const s = document.createElement("script"); s.src = M.deploy; s.onload = () => res(); s.onerror = rej;
      document.head.appendChild(s);
    });
    return window.__ggblabDeploy;
  }
  pollLoop();
  loadScript().then(() => {
    const params = Object.assign({appName: "suite", width: 800, height: 600, showToolBar: true, showAlgebraInput: true, showMenuBar: false,
      appletOnLoad: (a) => {
        try {
          a.registerUpdateListener((label) => post({kind: "event", data: {type: "update", label}}));
          a.registerAddListener((label) => post({kind: "event", data: {type: "add", label}}));
          api = a; el.__api = a;
          while (queue.length) serve(queue.shift());
        } catch (e) { console.error("ggblab appletOnLoad failed", e); post({kind: "event", data: {type: "error", error: String(e)}}); }
      }}, M.params || {});
    new window.GGBApplet(params, true).inject(el);   // element, not id (deployggb gives up silently on a missing id)
  }).catch(e => console.error("ggblab: deployggb load failed", e));
})();
"""


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
    """Stage-0 façade (command / xml / set_xml / delete / value / listen) over the HTML + mailbox host."""
    def __init__(self, mount: str | None = None, doc: str | None = None, **params):
        self._listeners: list[Callable[[dict], None]] = []
        self.ctl = ControlBridge()
        self.kernel_id = kernel_id() or ""
        self.dom_id = uuid.uuid4().hex[:12]                     # the output element (one per display)
        self.params = params
        self.server_url, self._headers = find_server(self.kernel_id)
        if doc:                                                 # an agent-started kernel with no session names its document explicitly
            from .relay import mount_key
            self.path, self.mount_id = doc, mount_key(doc, self.kernel_id, mount)
        else:
            self.path, self.mount_id = self._whoami(mount)      # the mailbox address = the document (stage 3)
        self.ctl.on_event(lambda d: [cb(d) for cb in self._listeners])
        self._mounted = False

    def _whoami(self, name: str | None) -> tuple[str | None, str]:
        """Ask the relay which document owns this kernel; the box key follows relay.mount_key (fallback: kernel id)."""
        try:
            q = f"/ggblab/whoami?kernel_id={self.kernel_id}" + (f"&name={name}" if name else "")
            req = urllib.request.Request(self.server_url.rstrip("/") + q, headers=self._headers)
            with urllib.request.urlopen(req, timeout=3) as r:
                d = json.loads(r.read().decode())
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
        cfg = {"mount": self.mount_id, "dom": self.dom_id, "kernel_id": self.kernel_id, "comm_id": self.ctl.comm_id, "params": self.params, "deploy": DEPLOY}
        html = (f'<div id="ggb-{self.dom_id}" style="min-height:600px"></div>'
                f'<script>{JS.replace("__CFG__", json.dumps(cfg))}</script>')
        display(HTML(html))
        self._mounted = True

    def _post(self, path: str, body: dict) -> int:
        req = urllib.request.Request(self.server_url.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                     headers={**self._headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    def _send(self, req: Request, timeout: float = 10.0):
        if not self._mounted:
            self.mount()
        rid = self.ctl.new_request()
        body = to_json(req, rid); body["reply_to"] = {"kernel_id": self.kernel_id, "comm_id": self.ctl.comm_id}
        self._post("/ggblab/send", {"mount": self.mount_id, "request": body})
        return self.ctl.wait(rid, timeout)

    def command(self, *cmds: str, timeout: float = 10.0):
        return self._send(Eval(tuple(cmds)), timeout)
    def xml(self, timeout: float = 10.0) -> str:
        return self._send(XmlOut(), timeout)
    def set_xml(self, xml: str, timeout: float = 10.0):
        return self._send(XmlIn(xml), timeout)
    def delete(self, label: str, timeout: float = 10.0):
        return self._send(Delete(label), timeout)
    def value(self, label: str, timeout: float = 10.0):
        return self._send(Value(label), timeout)
    def new_construction(self, timeout: float = 10.0):
        return self._send(New(), timeout)
    def listen(self, cb: Callable[[dict], None]) -> None:
        self._listeners.append(cb)
