"""C1 host adapter #1: anywidget (JupyterLab / marimo / VS Code) — mounts the GeoGebra applet via deployggb.js.

kernel -> applet : `request` trait (JSON) synced through the widget model (iopub side: fires during execution)
applet -> kernel : reactive hosts only — `last_reply` model sync (marimo). The relay path (C0-A) was retired on 2026-09-09
(ruling (iii)): this adapter is a MIRROR-READ adapter; the Jupyter host is html_host.py (RPC mailbox).
"""
from __future__ import annotations
import json, pathlib
from typing import Callable, Optional
import anywidget, traitlets
from .base import Request, Eval, XmlIn, XmlOut, Listen, Delete, Value, New
from .control import ControlBridge, kernel_id

ESM = r"""
const GGB_SCRIPT = "https://www.geogebra.org/apps/deployggb.js";
function loadScript() {
  if (window.GGBApplet) return Promise.resolve();
  if (window.__ggblabDeploy) return window.__ggblabDeploy;
  window.__ggblabDeploy = new Promise((res, rej) => {
    const s = document.createElement("script"); s.src = GGB_SCRIPT; s.onload = () => res(); s.onerror = rej;
    document.head.appendChild(s);
  });
  return window.__ggblabDeploy;
}
function xsrf() { const m = document.cookie.match(/(?:^|; )_xsrf=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
function baseUrl() { const b = document.body && document.body.dataset && document.body.dataset.baseUrl; return b || "/"; }
async function reply(model, payload) {
  const path = model.get("relay_path");
  if (!path) { model.set("last_reply", JSON.stringify(payload)); model.save_changes(); return; }   // reactive hosts
  await fetch(baseUrl().replace(/\/$/, "") + path, {
    method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-XSRFToken": xsrf()},
    body: JSON.stringify(Object.assign({kernel_id: model.get("kernel_id"), comm_id: model.get("comm_id")}, payload)),
  });
}
function handle(api, req) {                    // C3: one clause per head; unknown kind -> explicit error
  switch (req.kind) {
    case "eval":   return req.commands.map(c => api.evalCommandGetLabels(c));
    case "xml_in": api.setXML(req.xml); return true;
    case "xml_out": return api.getXML();
    case "delete": api.deleteObject(req.label); return true;
    case "value":  return api.getValue(req.label);
    case "new":    api.newConstruction(); return true;
    case "listen": return true;                // listener wiring is done once at mount (see below)
    default: throw new Error("unhandled request kind: " + req.kind);
  }
}
export default {
  async render({ model, el }) {
    await loadScript();
    const id = "ggb-" + Math.random().toString(36).slice(2);
    const div = document.createElement("div"); div.id = id; el.appendChild(div);
    // Declared before inject(): appletOnLoad may fire synchronously when the codebase is already loaded (TDZ otherwise).
    const queue = [];                                     // C2: never block the shell; the host queues until ready
    async function serve(req) {
      try { await reply(model, {req_id: req.req_id, data: handle(el.__api, req)}); }
      catch (e) { await reply(model, {req_id: req.req_id, data: {error: String(e)}}); }
    }
    model.on("change:request", () => {
      const raw = model.get("request"); if (!raw) return;
      const req = JSON.parse(raw);
      if (el.__api) serve(req); else queue.push(req);
    });
    const params = Object.assign({appName: "suite", width: 800, height: 600, showToolBar: true, showAlgebraInput: true, showMenuBar: false,
      appletOnLoad: (api) => {
        try {
          api.registerUpdateListener((label) => reply(model, {kind: "event", data: {type: "update", label}}));
          api.registerAddListener((label) => reply(model, {kind: "event", data: {type: "add", label}}));
          el.__api = api;
          model.set("ready", true); model.save_changes();
          while (queue.length) serve(queue.shift());     // requests that arrived before the applet was ready
        } catch (e) { console.error("ggblab appletOnLoad failed", e); reply(model, {kind: "event", data: {type: "error", error: String(e)}}); }
      }}, JSON.parse(model.get("params") || "{}"));
    // Pass the element, not its id: deployggb's inject(id) does document.getElementById(id) and silently gives up
    // ("possibly bug on ajax loading?") when the output node is not attached to the document yet (kernel restart + run-all).
    new window.GGBApplet(params, true).inject(div);
  }
};
"""


class GeoGebraWidget(anywidget.AnyWidget):
    _esm = ESM
    request = traitlets.Unicode("").tag(sync=True)      # kernel -> applet (JSON: {req_id, kind, ...})
    last_reply = traitlets.Unicode("").tag(sync=True)   # reactive hosts (no relay): reply via model sync
    ready = traitlets.Bool(False).tag(sync=True)
    kernel_id = traitlets.Unicode("").tag(sync=True)
    comm_id = traitlets.Unicode("").tag(sync=True)      # = this widget's own comm (model_id): open on both sides
    relay_path = traitlets.Unicode("/ggblab/reply").tag(sync=True)
    params = traitlets.Unicode("{}").tag(sync=True)

    def __init__(self, bridge: ControlBridge, **kw):
        super().__init__(**kw)
        self.bridge = bridge
        self.comm_id = self.model_id                     # widget comm id -> JS posts it to the relay
        self.on_msg(self._on_custom)                      # relay -> control thread -> here
        self.observe(self._on_last_reply, names=["last_reply"])

    def _on_custom(self, widget, content, buffers):
        if isinstance(content, dict):
            self.bridge.dispatch(content)

    def _on_last_reply(self, change):
        try:
            self.bridge.dispatch(json.loads(change["new"] or "{}"))
        except Exception:
            pass


def _to_json(req: Request, req_id: str) -> str:
    from .base import to_json
    return json.dumps(to_json(req, req_id))


class GeoGebra:
    """Stage-0 façade over the anywidget host (satisfies eg3/eg9 semantics: command / listen / xml)."""
    def __init__(self, relay: bool = False, **params):
        self._listeners: list[Callable[[dict], None]] = []
        self.ctl = ControlBridge()
        self.widget = GeoGebraWidget(self.ctl, kernel_id=kernel_id() or "", relay_path="/ggblab/reply" if relay else "",
                                     params=json.dumps(params))
        self.ctl.on_event(lambda d: [cb(d) for cb in self._listeners])

    def _ipython_display_(self):
        from IPython.display import display
        display(self.widget)

    def _send(self, req: Request, timeout: float = 10.0):
        rid = self.ctl.new_request()
        self.widget.request = _to_json(req, rid)
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
