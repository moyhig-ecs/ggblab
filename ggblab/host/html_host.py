"""Host adapter #2 — JupyterLab WITHOUT ipywidgets (stage 0 v2, 2026-09-03 evening; teacher's ruling).

mount: a trusted text/html output (div + inline script). The script loads deployggb.js, injects the applet into the div,
and long-polls the mailbox (relay.py) for requests over plain HTTP. Replies/events are POSTed back; the server injects
them into the kernel's phantom comm through the control socket (control.py). The kernel talks to the server over
localhost HTTP with the server's own token. Only HTTP crosses the browser<->server boundary.
"""
from __future__ import annotations
import json, os, uuid, urllib.request
from typing import Callable
from IPython.display import HTML, display
from .base import Request, Eval, XmlIn, XmlOut, Delete, Value, to_json
from .control import ControlBridge, kernel_id

DEPLOY = "https://www.geogebra.org/apps/deployggb.js"

JS = r"""
(function () {
  const M = __CFG__;
  const el = document.getElementById("ggb-" + M.mount);
  if (!el || el.__ggblab) return;
  el.__ggblab = true;
  const base = ((document.body && document.body.dataset && document.body.dataset.baseUrl) || "/").replace(/\/$/, "");
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  function xsrf() { const m = document.cookie.match(/(?:^|; )_xsrf=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function post(payload) {
    return fetch(base + "/ggblab/reply", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-XSRFToken": xsrf()},
      body: JSON.stringify(Object.assign({kernel_id: M.kernel_id, comm_id: M.comm_id}, payload))});
  }
  function handle(api, req) {                       // C3: one clause per head; unknown kind -> explicit error
    switch (req.kind) {
      case "eval":    return req.commands.map(c => api.evalCommandGetLabels(c));
      case "xml_in":  api.setXML(req.xml); return true;
      case "xml_out": return api.getXML();
      case "delete":  api.deleteObject(req.label); return true;
      case "value":   return api.getValue(req.label);
      case "listen":  return true;                  // listeners are wired once at mount
      default: throw new Error("unhandled request kind: " + req.kind);
    }
  }
  let api = null; const queue = [];                 // C2: requests wait here until the applet is ready
  async function serve(req) {
    try { await post({req_id: req.req_id, data: handle(api, req)}); }
    catch (e) { await post({req_id: req.req_id, data: {error: String(e)}}); }
  }
  async function pollLoop() {                       // plain HTTP long-poll; survives proxies, needs no WebSocket
    for (;;) {
      try {
        const r = await fetch(base + "/ggblab/poll?mount=" + M.mount + "&wait=25", {credentials: "same-origin", cache: "no-store"});
        if (r.status === 200) { const j = await r.json(); for (const req of (j.requests || [])) { if (api) serve(req); else queue.push(req); } }
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
    def __init__(self, **params):
        self._listeners: list[Callable[[dict], None]] = []
        self.ctl = ControlBridge()
        self.kernel_id = kernel_id() or ""
        self.mount_id = uuid.uuid4().hex[:12]
        self.params = params
        self.server_url, self._headers = find_server(self.kernel_id)
        self.ctl.on_event(lambda d: [cb(d) for cb in self._listeners])
        self._mounted = False

    def _ipython_display_(self):
        self.mount()

    def mount(self) -> None:
        cfg = {"mount": self.mount_id, "kernel_id": self.kernel_id, "comm_id": self.ctl.comm_id, "params": self.params, "deploy": DEPLOY}
        html = (f'<div id="ggb-{self.mount_id}" style="min-height:600px"></div>'
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
        self._post("/ggblab/send", {"mount": self.mount_id, "request": to_json(req, rid)})
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
    def listen(self, cb: Callable[[dict], None]) -> None:
        self._listeners.append(cb)
