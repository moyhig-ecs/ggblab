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
  // <base>ggblab/…: under JupyterHub the server lives at /user/<name>/. JupyterLab 4 / Notebook 7 stamp the base URL in the
  // page config (what PageConfig.getBaseUrl() reads); <body data-base-url> is the older stamp (absent in Lab 4.5: measured 09-15).
  const pageCfg = (function () { try { const c = document.getElementById("jupyter-config-data"); return c ? JSON.parse(c.textContent) : {}; } catch (e) { return {}; } })();
  const base = (pageCfg.baseUrl || (document.body && document.body.dataset && document.body.dataset.baseUrl) || "/").replace(/\/$/, "");
  // Auth exactly as @jupyterlab/services does: the page-config token (when the page was opened with ?token=… there is no OAuth
  // cookie, only this token) plus the _xsrf cookie echoed as a header on POST. Measured on the Hub 2026-09-15: cookie-only fetches
  // from a token-opened page are redirected to OAuth; the token header is what Lab itself sends.
  const authHeaders = pageCfg.token ? {"Authorization": "token " + pageCfg.token} : {};
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  function xsrf() { const m = document.cookie.match(/(?:^|; )_xsrf=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function post(payload) {                          // reply -> the parked call (req_id); event -> the mount's event log
    return fetch(base + "/ggblab/reply", {method: "POST", credentials: "same-origin",
      headers: Object.assign({"Content-Type": "application/json", "X-XSRFToken": xsrf()}, authHeaders),
      body: JSON.stringify(Object.assign({mount: M.mount}, payload))});
  }
  function handle(api, req) {                       // C3: one clause per head; unknown kind -> explicit error
    switch (req.kind) {
      case "eval":    return req.commands.map(c => { try { return api.evalCommandGetLabels(c); }   // one entry per command: labels, null (GeoGebra refused: modal/redefinition), or {error} (the API threw — e.g. "Discrete commands not loaded yet"); the batch keeps going
                                                 catch (e) { return {error: String(e)}; } });
      case "xml_in":  api.setXML(req.xml); return true;
      case "xml_out": return api.getXML();
      case "delete":  api.deleteObject(req.label); return true;
      case "value":   return api.getValue(req.label);
      case "kind":    return api.getObjectType(req.label);   // runtime type (drag-varying); the XML class stays in the DataFrame Type column
      case "new":     api.newConstruction(); return true;
      case "listen":  return true;                  // listeners are wired once at mount
      default: throw new Error("unhandled request kind: " + req.kind);
    }
  }
  let api = null; const queue = [];                 // C2: requests wait here until the applet is ready
  async function serve(req) {
    try { await post({req_id: req.req_id, data: handle(api, req)}); }
    catch (e) { await post({req_id: req.req_id, data: {error: String(e)}}); }
  }
  let held = false;
  async function pollLoop() {                       // plain HTTP long-poll; survives proxies, needs no WebSocket
    for (;;) {
      try {
        const r = await fetch(base + "/ggblab/poll?mount=" + encodeURIComponent(M.mount) + "&wait=25&client=" + clientId + "&lease=40", {credentials: "same-origin", cache: "no-store", headers: authHeaders});
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
  function installErrorScraper() {                  // v1 idea (MutationObserver on the dialog) + auto-dismiss (ruling 09-09)
    // GeoGebra's error modal (suite build): a `.dialogComponent` holding `.dialogTitle` ("Error") + `.dialogContent`.
    // Selector is GeoGebra-private CSS and may drift across releases: on no match nothing fires (no crash), and the
    // fallback below still reports *that* an error dialog appeared.
    if (window.__ggblabErrObs) return;
    const scrape = (root) => {
      const dlgs = root.querySelectorAll ? root.querySelectorAll(".dialogComponent, div.dialogMainPanel") : [];
      dlgs.forEach((raw) => {
        const d = (raw.closest && raw.closest(".dialogComponent")) || raw;   // one modal = one event (the selector matches nested nodes)
        if (d.__ggblabSeen) return; d.__ggblabSeen = true;
        const title = (d.querySelector(".dialogTitle") || {}).textContent || "Error";
        const content = d.querySelector(".dialogContent");
        const text = content ? (content.textContent || "").trim() : (d.textContent || "").trim();
        if (!/error/i.test(title) && !/error/i.test(text)) return;   // not an error modal (e.g. a save dialog): leave it
        post({kind: "event", data: {type: "error", title: title.trim(), text: text}});
        const ok = d.querySelector("button");                        // dismiss so the modal never wedges the browser
        if (ok) ok.click(); else { d.remove && d.remove(); }
        const glass = document.querySelector(".gwt-PopupPanelGlass"); if (glass && glass.remove) glass.remove();
      });
    };
    const obs = new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => { try { scrape(n); if (n.nodeType === 1) scrape(document.body); } catch (e) {} })));
    obs.observe(document.body, {childList: true, subtree: true});
    window.__ggblabErrObs = obs;
  }
  pollLoop();
  loadScript().then(() => {
    const params = Object.assign({appName: "suite", width: 800, height: 600, showToolBar: true, showAlgebraInput: true, showMenuBar: false,
      appletOnLoad: (a) => {
        try {
          a.registerUpdateListener((label) => post({kind: "event", data: {type: "update", label}}));
          a.registerAddListener((label) => post({kind: "event", data: {type: "add", label}}));
          installErrorScraper();                         // 09-09: GeoGebra reports errors only as a BLOCKING modal in the applet (never in the cell; evalCommandGetLabels just returns null). Scrape the modal text into an error event, then auto-dismiss it.
          api = a; el.__api = a;
          while (queue.length) serve(queue.shift());
        } catch (e) { console.error("ggblab appletOnLoad failed", e); post({kind: "event", data: {type: "error", error: String(e)}}); }
      }}, M.params || {});
    new window.GGBApplet(params, true).inject(el);   // element, not id (deployggb gives up silently on a missing id)
  }).catch(e => console.error("ggblab: deployggb load failed", e));
})();
