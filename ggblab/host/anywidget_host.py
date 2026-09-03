"""C1 host adapter #1: anywidget (JupyterLab / marimo / VS Code) — mounts the GeoGebra applet via deployggb.js.

kernel -> applet : `request` trait (JSON) synced through the widget model (iopub side: fires during execution)
applet -> kernel : fetch(<base_url>ggblab/reply) -> relay.py -> comm_msg on the CONTROL socket (C0-A)
In marimo the reactive runtime makes the relay unnecessary; `relay_path` may then be "".
"""
from __future__ import annotations
import json, pathlib
from typing import Callable, Optional
import anywidget, traitlets
from .base import Request, Eval, XmlIn, XmlOut, Listen, Delete, Value
from .control import ControlComm, kernel_id

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
    case "listen": return true;                // listener wiring is done once at mount (see below)
    default: throw new Error("unhandled request kind: " + req.kind);
  }
}
export default {
  async render({ model, el }) {
    await loadScript();
    const id = "ggb-" + Math.random().toString(36).slice(2);
    const div = document.createElement("div"); div.id = id; el.appendChild(div);
    const params = Object.assign({appName: "suite", width: 800, height: 600, showToolBar: true, showAlgebraInput: true, showMenuBar: false,
      appletOnLoad: (api) => {
        api.registerUpdateListener((label) => reply(model, {kind: "event", data: {type: "update", label}}));
        api.registerAddListener((label) => reply(model, {kind: "event", data: {type: "add", label}}));
        model.set("ready", true); model.save_changes();
        el.__api = api;
      }}, JSON.parse(model.get("params") || "{}"));
    new window.GGBApplet(params, true).inject(id);
    model.on("change:request", async () => {
      const raw = model.get("request"); if (!raw) return;
      const req = JSON.parse(raw); const api = el.__api;
      if (!api) { await reply(model, {req_id: req.req_id, data: {error: "applet not ready"}}); return; }
      try { await reply(model, {req_id: req.req_id, data: handle(api, req)}); }
      catch (e) { await reply(model, {req_id: req.req_id, data: {error: String(e)}}); }
    });
  }
};
"""


class GeoGebraWidget(anywidget.AnyWidget):
    _esm = ESM
    request = traitlets.Unicode("").tag(sync=True)      # kernel -> applet (JSON: {req_id, kind, ...})
    last_reply = traitlets.Unicode("").tag(sync=True)   # reactive hosts only
    ready = traitlets.Bool(False).tag(sync=True)
    kernel_id = traitlets.Unicode("").tag(sync=True)
    comm_id = traitlets.Unicode("").tag(sync=True)
    relay_path = traitlets.Unicode("/ggblab/reply").tag(sync=True)
    params = traitlets.Unicode("{}").tag(sync=True)


def _to_json(req: Request, req_id: str) -> str:
    match req:                                   # C3: exhaustive over the Request union
        case Eval(commands=c):   d = {"kind": "eval", "commands": list(c)}
        case XmlIn(xml=x):       d = {"kind": "xml_in", "xml": x}
        case XmlOut():           d = {"kind": "xml_out"}
        case Listen(enable=e):   d = {"kind": "listen", "enable": e}
        case Delete(label=l):    d = {"kind": "delete", "label": l}
        case Value(label=l):     d = {"kind": "value", "label": l}
        case _:
            from typing import assert_never
            assert_never(req)
    d["req_id"] = req_id
    return json.dumps(d)


class GeoGebra:
    """Stage-0 façade over the anywidget host (satisfies eg3/eg9 semantics: command / listen / xml)."""
    def __init__(self, relay: bool = True, **params):
        self.ctl = ControlComm() if relay else None
        self.widget = GeoGebraWidget(kernel_id=kernel_id() or "", comm_id=self.ctl.comm_id if self.ctl else "",
                                     relay_path="/ggblab/reply" if relay else "", params=json.dumps(params))
        if self.ctl:
            self.ctl.on_event(lambda d: [cb(d) for cb in self._listeners])
        self._listeners: list[Callable[[dict], None]] = []

    def _ipython_display_(self):
        from IPython.display import display
        display(self.widget)

    def _send(self, req: Request, timeout: float = 10.0):
        rid = self.ctl.new_request() if self.ctl else "reactive"
        self.widget.request = _to_json(req, rid)
        if not self.ctl:
            return None
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
