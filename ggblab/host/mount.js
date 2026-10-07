(function () {
  const M = __CFG__;
  // The output element. `getElementById` returns the FIRST element with the id; when the same object was displayed twice
  // on one page (cell 3 of probes/hub_two_tabs.ipynb, 09-15: "同一 object の再表示 = 空箱") the two outputs shared one id and
  // the second script found the first, already-initialised div and returned — leaving its own div empty. Take the newest
  // element with this id that nobody has claimed yet (the host now also stamps a fresh id per display; this is the belt).
  const cands = Array.from(document.querySelectorAll('[id="ggb-' + M.dom + '"]')).filter(e => !e.__ggblab);
  const el = cands.length ? cands[cands.length - 1] : null;
  if (!el) return;
  el.__ggblab = true;
  // stage 3: one live applet per document. If this page already holds an applet for M.mount (an earlier output, a saved
  // output re-rendered on reload), this output becomes a pointer to it instead of a second applet + second poller.
  window.__ggblabBoxes = window.__ggblabBoxes || {};
  const prev = window.__ggblabBoxes[M.mount];
  if (prev && prev.el && document.contains(prev.el) && prev.el !== el) {
    el.style.minHeight = "0"; el.textContent = "";             // A4: build the pointer with DOM calls, never innerHTML of the mount string
    const note = document.createElement("div"); note.style.cssText = "font:12px system-ui;color:#666;padding:4px 6px;border-left:3px solid #ccc";
    note.appendChild(document.createTextNode("ggblab: the applet for this notebook is already mounted above (" + M.mount + ") \u2014 "));
    const a = document.createElement("a"); a.href = "#"; a.textContent = "show";
    a.onclick = (ev) => { ev.preventDefault(); const live = window.__ggblabBoxes[M.mount]; if (live && live.el) live.el.scrollIntoView({behavior: "smooth"}); };
    note.appendChild(a); el.appendChild(note);
    return;
  }
  const box = {el, dom: M.dom, take: null};        // take: how another poller of this page hands a request to this applet
  window.__ggblabBoxes[M.mount] = box;
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
      case "png":     return api.getPNGBase64(req.scale || 1, !!req.transparent, req.dpi || 72);   // projection (B6, 10-05): the view as a picture
      case "svg":     return new Promise((res) => api.exportSVG((svg) => res(svg)));               // projection: exportSVG is callback-based
      default: throw new Error("unhandled request kind: " + req.kind);
    }
  }
  let api = null; const queue = [];                 // C2: requests wait here until the applet is ready
  let pendingRestore = null;                        // B6 (10-05): the state the server handed this NEW holder on its first poll
  function applyRestore() {                         // applied once the applet is ready, before any request of the same poll is served
    if (!api || pendingRestore == null) return;
    const x = pendingRestore; pendingRestore = null;
    try { api.setXML(x); } catch (e) { post({kind: "event", data: {type: "error", error: "restore: " + String(e)}}); }
  }
  async function serve(req) {
    try { const data = await handle(api, req); await post({req_id: req.req_id, data}); }   // await: svg's reply is a Promise
    catch (e) { await post({req_id: req.req_id, data: {error: String(e)}}); }
  }
  const take = (req) => { if (api) serve(req); else queue.push(req); };
  box.take = take;
  let held = false;
  function notice(text) {                           // A4 (10-07): a failure is shown in the output, not only in the console
    let n = el.querySelector(".ggblab-notice");
    if (!n) { n = document.createElement("div"); n.className = "ggblab-notice"; n.style.cssText = "font:12px system-ui;color:#a00;padding:4px 6px;border-left:3px solid #a00;white-space:pre-wrap"; el.prepend(n); }
    n.textContent = "ggblab: " + text;
  }
  function clearNotice() { const n = el.querySelector(".ggblab-notice"); if (n) n.remove(); }
  async function gone() {                           // the output left the page (cell re-run cleared it, notebook closed)?
    if (document.contains(el)) return false;        // two looks 2 s apart: Lab detaches and re-attaches nodes when it moves cells
    await sleep(2000);
    return !document.contains(el);
  }
  async function pollLoop() {                       // plain HTTP long-poll; survives proxies, needs no WebSocket
    let failures = 0;                               // A4: consecutive poll failures; auth / not-found stops the loop with a visible reason
    for (;;) {
      if (await gone()) {                           // 09-16: no zombie poller serving a detached applet (it shares clientId with
        const reg = window.__ggblabBoxes[M.mount];  // the live one, so the server could hand it the requests)
        if (reg && reg.el === el) delete window.__ggblabBoxes[M.mount];
        return;
      }
      try {
        const r = await fetch(base + "/ggblab/poll?mount=" + encodeURIComponent(M.mount) + "&wait=25&client=" + clientId + "&lease=40", {credentials: "same-origin", cache: "no-store", headers: authHeaders});
        if (r.status === 200) {
          if (failures) { failures = 0; clearNotice(); }
          const j = await r.json();
          if (j.held) { if (!held) { held = true; el.dataset.ggblabHeld = "1"; } await sleep(1000); continue; }   // another tab holds it. The server parks us (<= wait) until it releases; the 1 s is for a server that answers at once
          if (held) { held = false; delete el.dataset.ggblabHeld; }
          if (j.restore && typeof j.restore.xml === "string") { pendingRestore = j.restore.xml; applyRestore(); }   // B6: the box's state comes with the lease
          const reqs = j.requests || [];
          if (reqs.length && !document.contains(el)) {   // 09-29: this output left the page while the poll was parked (the cell was run again).
            const live = window.__ggblabBoxes[M.mount];  // The requests belong to the applet that replaced it, not to the detached one.
            if (live && live.el !== el && live.take) { reqs.forEach(live.take); return; }
          }
          for (const req of reqs) take(req);
        }
        else {                                        // A4: a non-2xx poll is reported; 401/403/404 (auth, no relay) will not heal by retrying
          failures += 1;
          const fatal = r.status === 401 || r.status === 403 || r.status === 404;
          if (fatal || failures >= 5) notice("poll " + base + "/ggblab/poll -> HTTP " + r.status + (fatal ? " (not retrying: " + (r.status === 404 ? "is the ggblab server extension enabled?" : "not authorized — reload the page or log in") + ")" : " (" + failures + " failures, retrying)"));
          if (fatal && failures >= 3) return;
          await sleep(Math.min(1000 * failures, 5000));
        }
      } catch (e) {                                   // network / CORS: keep trying, but say so after a while
        failures += 1;
        if (failures >= 5) notice("cannot reach " + base + "/ggblab/poll (" + failures + " failures: " + String(e) + ") — retrying");
        await sleep(Math.min(1000 * failures, 5000));
      }
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
          applyRestore();                                // B6: the state first, then the requests that were waiting
          while (queue.length) serve(queue.shift());
        } catch (e) { console.error("ggblab appletOnLoad failed", e); post({kind: "event", data: {type: "error", error: String(e)}}); }
      }}, M.params || {});
    new window.GGBApplet(params, true).inject(el);   // element, not id (deployggb gives up silently on a missing id)
  }).catch(e => { console.error("ggblab: deployggb load failed", e); notice("could not load " + M.deploy + " (the GeoGebra applet script): " + String(e && e.type ? e.type : e)); });   // A4: visible, not only in the console
})();
