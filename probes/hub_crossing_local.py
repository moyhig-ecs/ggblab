#!/usr/bin/env python3
"""Hub-crossing checklist v0 (2026-09-15) — the items measurable on ONE machine, against a running jupyter_server
that loads `ggblab.host.relay`.  Values are read from the server's real answers (R4), never assumed.

  python probes/hub_crossing_local.py --url http://127.0.0.1:8899 --token stage0token            # base_url = /
  python probes/hub_crossing_local.py --url http://127.0.0.1:8897 --token hubtesttoken --base /user/test/

① base_url : the relay routes live under <base>ggblab/… (registered with url_path_join(settings["base_url"], …));
             with base != "/" the bare /ggblab/… must be 404 — a page that computes `base` wrongly would hit that.
             Also: what list_running_servers() reports as "url" for this server (the kernel-side discovery path).
② XSRF     : a browser-style POST (cookie session, no X-XSRFToken) must be refused (403); the same POST with the
             `_xsrf` cookie echoed in X-XSRFToken must pass (202); a token-header POST without cookies (kernel path)
             must pass (202).
⑥ poller   : one live poller per box — a second client polling the same mount is told held:true and never receives
             the queued request; after the holder stops, the second client takes over once the lease lapses
             (measured hand-over time), and the reply path resolves the parked call exactly once.
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.error, urllib.parse, urllib.request
from http.cookiejar import CookieJar


def http(url, method="GET", data=None, headers=None, opener=None, timeout=20):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    op = opener or urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            txt = r.read().decode()
            try:
                return r.status, json.loads(txt)
            except Exception:
                return r.status, txt[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--base", default="/")
    ap.add_argument("--lease", type=float, default=6.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    U = a.url.rstrip("/"); B = "/" + a.base.strip("/") + "/" if a.base.strip("/") else "/"
    G = U + B + "ggblab/"
    tok = {"Authorization": f"token {a.token}"}
    R = {"url": U, "base": B, "items": {}}

    # ── ① base_url ───────────────────────────────────────────────────────────────────────────────────────────
    st_base, j = http(G + "whoami?kernel_id=probe", headers=tok)
    st_root = None
    if B != "/":
        st_root, _ = http(U + "/ggblab/whoami?kernel_id=probe", headers=tok)
    srv = None
    try:
        from jupyter_server.serverapp import list_running_servers
        port = urllib.parse.urlparse(U).port
        for s in list_running_servers():
            if s.get("port") == port:
                srv = {"url": s["url"], "base_url": s.get("base_url"), "token_set": bool(s.get("token"))}
    except Exception as e:
        srv = {"error": str(e)}
    R["items"]["1_base_url"] = {
        "whoami_under_base": {"status": st_base, "mount": (j or {}).get("mount") if isinstance(j, dict) else j},
        "whoami_at_root": st_root,
        "list_running_servers": srv,
        "pass": st_base == 200 and (B == "/" or st_root == 404),
    }

    # ── ② XSRF ───────────────────────────────────────────────────────────────────────────────────────────────
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    st_login, _ = http(U + B + f"lab?token={a.token}", opener=op)      # token in the query → session cookie + _xsrf
    cookies = {c.name: c for c in jar}
    xsrf = cookies.get("_xsrf")
    xsrf_val = xsrf.value if xsrf else ""
    xsrf_path = xsrf.path if xsrf else None
    body = {"req_id": "xsrf-probe", "data": 1}
    st_nohdr, r_nohdr = http(G + "reply", "POST", body, opener=op)                        # cookies, no header
    st_hdr, r_hdr = http(G + "reply", "POST", body, headers={"X-XSRFToken": xsrf_val}, opener=op)
    st_tok, r_tok = http(G + "reply", "POST", body, headers=tok)                            # token, no cookies
    st_none, r_none = http(G + "reply", "POST", body)                                      # nothing at all
    R["items"]["2_xsrf"] = {
        "login_status": st_login, "cookies_set": sorted(cookies), "xsrf_cookie_path": xsrf_path,
        "post_cookie_no_header": [st_nohdr, r_nohdr if isinstance(r_nohdr, str) else r_nohdr],
        "post_cookie_with_header": [st_hdr, r_hdr],
        "post_token_header_no_cookie": [st_tok, r_tok],
        "post_unauthenticated": [st_none, r_none if isinstance(r_none, str) else r_none],
        "pass": st_nohdr == 403 and st_hdr == 202 and st_tok == 202 and st_none in (401, 403),
    }

    # ── ⑥ one live poller per box ────────────────────────────────────────────────────────────────────────────
    mount = f"probe:hub:{int(time.time())}"
    L = a.lease
    def poll(client, wait=0):
        return http(G + f"poll?mount={urllib.parse.quote(mount)}&wait={wait}&client={client}&lease={L}", headers=tok)
    sA, pA = poll("A"); tA = time.time()
    sB, pB = poll("B")
    sA2, pA2 = poll("A")
    # queue one request; only the holder may receive it
    sc, call = http(G + "call", "POST", {"mount": mount, "request": {"kind": "value", "label": "x"}, "wait": 0}, headers=tok)
    rid = call.get("req_id") if isinstance(call, dict) else None
    sB2, pB2 = poll("B")
    sA3, pA3 = poll("A")
    got_by_A = [r.get("req_id") for r in (pA3.get("requests") or [])] if isinstance(pA3, dict) else []
    got_by_B = [r.get("req_id") for r in (pB2.get("requests") or [])] if isinstance(pB2, dict) else []
    # reply once, then await: exactly one resolution
    sr, rep = http(G + "reply", "POST", {"req_id": rid, "data": 42}, headers=tok)
    sw, aw = http(G + f"await?req_id={rid}&wait=0", headers=tok)
    sr2, rep2 = http(G + "reply", "POST", {"req_id": rid, "data": 43}, headers=tok)  # a second reply must not re-resolve
    # hand-over: A stops; B polls every 0.5 s until held:false
    t_stop = time.time(); handover = None
    for _ in range(int((L + 15) / 0.5)):
        sB3, pB3 = poll("B")
        if isinstance(pB3, dict) and not pB3.get("held"):
            handover = round(time.time() - t_stop, 2); break
        time.sleep(0.5)
    sA4, pA4 = poll("A")   # now B holds it: A must be told so
    R["items"]["6_single_poller"] = {
        "lease_s": L,
        "A_first": pA, "B_while_A_holds": pB, "A_refresh": pA2,
        "call": {"status": sc, "reply_status": call.get("status") if isinstance(call, dict) else call},
        "request_seen_by": {"A": got_by_A, "B": got_by_B},
        "reply_first": rep, "await_after_reply": aw, "reply_second": rep2,
        "handover_after_A_stops_s": handover, "A_after_handover": pA4,
        "pass": (isinstance(pB, dict) and pB.get("held") is True and isinstance(pA2, dict) and pA2.get("held") is False
                 and got_by_A == [rid] and got_by_B == [] and isinstance(aw, dict) and aw.get("data") == 42
                 and isinstance(rep2, dict) and rep2.get("resolved") is False
                 and handover is not None and handover <= L + 1.0 and isinstance(pA4, dict) and pA4.get("held") is True),
    }
    out = json.dumps(R, ensure_ascii=False, indent=1)
    print(out)
    if a.out:
        open(a.out, "w").write(out + "\n")
    return 0 if all(v["pass"] for v in R["items"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
