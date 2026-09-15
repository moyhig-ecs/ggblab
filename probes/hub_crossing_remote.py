#!/usr/bin/env python3
"""Hub-crossing checklist — the items driven from OUTSIDE a live JupyterHub with a service token (2026-09-15).

  python probes/hub_crossing_remote.py --hub https://vioras-jh2500.japaneast.cloudapp.azure.com --token $TOK --user ggblab-probe

What it does (every value comes from the hub's / server's real answers; R4):
  0. ensure the user exists, start its server, wait until ready (image pull can take minutes)
  ① base_url : GET /user/<u>/ggblab/whoami with the token → 200 proves (a) the relay extension is loaded in the image (④)
               and (b) the routes live under the hub prefix
  ③ proxy    : GET /user/<u>/ggblab/poll?wait=55 through the ingress → 200 after ~55 s (a 502/504 earlier = the proxy cut it)
  ⑤ kernel   : python3 kernel over the websocket: ggblab.host.html_host.find_server(kernel_id()) → (url, headers) = the kernel
               found its own server inside the pod; then the in-pod probe (①②⑥ relay-level, hub_crossing_local.py) with
               JUPYTERHUB_API_TOKEN / JUPYTERHUB_SERVICE_PREFIX
  ⑦ julia    : julia-ggblab-v2 kernel: include html_host.jl + ggb_macro.jl, ggb"A=(1,2)" → a Construction (PythonCall → parser)
Browser-only items (mount.js base in the real page, cookie XSRF, two tabs) are left to a logged-in human; see CHECKLIST §3.
"""
from __future__ import annotations
import argparse, json, ssl, sys, time, uuid, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

def http(url, method="GET", data=None, headers=None, timeout=90, insecure=False):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl._create_unverified_context() if insecure else None
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            txt = r.read().decode()
            try:
                return r.status, json.loads(txt) if txt else None, round(time.time() - t0, 2)
            except Exception:
                return r.status, txt[:300], round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], round(time.time() - t0, 2)
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", round(time.time() - t0, 2)


def run_code(ws_url, headers, kernel_name, code, timeout, insecure):
    """Execute `code` in a fresh kernel over the Jupyter websocket; return {'stdout', 'stderr', 'error', 'result'}."""
    from tornado import ioloop, websocket, httpclient
    out = {"stdout": "", "stderr": "", "error": None, "result": None, "status": None}
    async def go():
        req = httpclient.HTTPRequest(ws_url, headers=headers, validate_cert=not insecure, request_timeout=60)
        ws = await websocket.websocket_connect(req)
        msg_id = uuid.uuid4().hex
        hdr = {"msg_id": msg_id, "username": "probe", "session": uuid.uuid4().hex, "msg_type": "execute_request",
               "version": "5.3", "date": datetime.now(timezone.utc).isoformat()}
        await ws.write_message(json.dumps({"header": hdr, "parent_header": {}, "metadata": {}, "channel": "shell",
                                           "content": {"code": code, "silent": False, "store_history": False,
                                                       "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
                                           "buffers": []}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await ws.read_message()
            if raw is None:
                out["status"] = "closed"; break
            m = json.loads(raw)
            if m.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            mt = m["header"]["msg_type"]; c = m.get("content", {})
            if mt == "stream":
                out[c.get("name", "stdout")] += c.get("text", "")
            elif mt == "execute_result":
                out["result"] = c.get("data", {}).get("text/plain")
            elif mt == "error":
                out["error"] = c.get("ename", "") + ": " + c.get("evalue", "")
            elif mt == "status" and c.get("execution_state") == "idle" and m["channel"] == "iopub":
                # idle after our request: done (busy→idle pair)
                if out["status"] == "busy":
                    out["status"] = "done"; break
            elif mt == "status" and c.get("execution_state") == "busy":
                out["status"] = "busy"
        ws.close()
    ioloop.IOLoop.current().run_sync(go, timeout=timeout + 30)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", required=True); ap.add_argument("--token", required=True); ap.add_argument("--user", default="ggblab-probe")
    ap.add_argument("--insecure", action="store_true"); ap.add_argument("--spawn-timeout", type=int, default=900)
    ap.add_argument("--skip-julia", action="store_true"); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    H = a.hub.rstrip("/"); tok = {"Authorization": f"token {a.token}"}; u = a.user; ins = a.insecure
    R = {"hub": H, "user": u, "items": {}}
    # 0. user + server
    st, info, _ = http(f"{H}/hub/api/users/{u}", headers=tok, insecure=ins)
    if st == 404:
        st, info, _ = http(f"{H}/hub/api/users/{u}", "POST", {}, headers=tok, insecure=ins)
    print("user:", st, (info or {}).get("name") if isinstance(info, dict) else info)
    st, info, _ = http(f"{H}/hub/api/users/{u}", headers=tok, insecure=ins)
    if not (isinstance(info, dict) and info.get("server")):
        st, resp, _ = http(f"{H}/hub/api/users/{u}/server", "POST", {}, headers=tok, timeout=120, insecure=ins)
        print("spawn requested:", st, resp if st >= 400 else "")
    t0 = time.time(); ready = False
    while time.time() - t0 < a.spawn_timeout:
        st, info, _ = http(f"{H}/hub/api/users/{u}", headers=tok, insecure=ins)
        srv = info.get("servers", {}).get("", {}) if isinstance(info, dict) else {}
        if srv.get("ready"):
            ready = True; break
        prog = srv.get("progress_url") or ""
        print(f"  waiting… pending={srv.get('pending')} t={int(time.time()-t0)}s"); time.sleep(15)
    R["items"]["0_spawn"] = {"ready": ready, "seconds": int(time.time() - t0), "url": srv.get("url") if ready else None,
                             "state": {k: srv.get(k) for k in ("pending", "last_activity", "started")}}
    print("server ready:", ready, srv.get("url"))
    if not ready:
        st, log, _ = http(f"{H}/hub/api/users/{u}", headers=tok, insecure=ins); print(json.dumps(R, indent=1)); return 2
    base = f"{H}/user/{u}"
    # ① + ④
    st, who, dt = http(f"{base}/ggblab/whoami?kernel_id=probe", headers=tok, insecure=ins)
    R["items"]["1_4_whoami_under_prefix"] = {"status": st, "body": who, "pass": st == 200 and isinstance(who, dict) and "mount" in who}
    print("① whoami:", st, who)
    st_root, _, _ = http(f"{H}/ggblab/whoami?kernel_id=probe", headers=tok, insecure=ins)
    R["items"]["1_root_is_not_relay"] = {"status": st_root}
    # ③
    st, body, dt = http(f"{base}/ggblab/poll?mount=probe%3Ahub&wait=55&client=probe&lease=40", headers=tok, timeout=90, insecure=ins)
    R["items"]["3_longpoll_55s_via_ingress"] = {"status": st, "seconds": dt, "body": body, "pass": st == 200 and dt >= 54}
    print("③ poll wait=55:", st, f"{dt}s", body if st != 200 else "")
    # ⑤ python kernel
    st, k, _ = http(f"{base}/api/kernels", "POST", {"name": "python3"}, headers=tok, insecure=ins)
    kid = k.get("id") if isinstance(k, dict) else None
    print("python kernel:", st, kid)
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    code_py = r'''
import os, json, subprocess, sys
from ggblab.host.html_host import find_server, kernel_id
url, headers = find_server(kernel_id())
print("FIND_SERVER", json.dumps({"url": url, "auth": list(headers)[:1], "prefix": os.environ.get("JUPYTERHUB_SERVICE_PREFIX"),
      "hub_service_url": os.environ.get("JUPYTERHUB_SERVICE_URL")}))
probe = os.path.join(sys.prefix, "share", "ggblab-v2", "probes", "hub_crossing_local.py")
r = subprocess.run([sys.executable, probe, "--url", "http://127.0.0.1:8888", "--token", os.environ["JUPYTERHUB_API_TOKEN"],
                    "--base", os.environ["JUPYTERHUB_SERVICE_PREFIX"], "--lease", "4"], capture_output=True, text=True, timeout=120)
print("PROBE_RC", r.returncode)
try:
    rep = json.loads(r.stdout); print("PROBE", json.dumps({k: v["pass"] for k, v in rep["items"].items()}))
    print("PROBE_DETAIL", json.dumps({"xsrf": rep["items"]["2_xsrf"]["post_cookie_no_header"][0], "handover_s": rep["items"]["6_single_poller"]["handover_after_A_stops_s"], "srv": rep["items"]["1_base_url"]["list_running_servers"]}))
except Exception as e:
    print("PROBE_RAW", r.stdout[-800:], r.stderr[-800:])
'''
    if kid:
        o = run_code(f"{ws_base}/api/kernels/{kid}/channels", tok, "python3", code_py, 240, ins)
        R["items"]["5_kernel_find_server_and_inpod_probe"] = o
        print("⑤ python kernel:", o["status"], "\n" + o["stdout"].strip(), "\nERR:" + o["stderr"].strip() if o["stderr"].strip() else "", o["error"] or "")
        http(f"{base}/api/kernels/{kid}", "DELETE", headers=tok, insecure=ins)
    # ⑦ julia kernel
    if not a.skip_julia:
        st, ks, _ = http(f"{base}/api/kernelspecs", headers=tok, insecure=ins)
        names = list((ks or {}).get("kernelspecs", {}).keys()) if isinstance(ks, dict) else []
        jname = next((n for n in names if "ggblab" in n), next((n for n in names if n.startswith("julia")), None))
        print("kernelspecs:", names, "→ julia:", jname)
        if jname:
            st, k, _ = http(f"{base}/api/kernels", "POST", {"name": jname}, headers=tok, insecure=ins)
            kid = k.get("id") if isinstance(k, dict) else None
            code_jl = r'''
const D = joinpath(ENV["NB_PYTHON_PREFIX"], "share", "ggblab-v2", "julia", "host")
include(joinpath(D, "html_host.jl")); include(joinpath(D, "ggb_macro.jl"))
using .GGBLabMacro
c = ggb"A=(1,2)"
println("GGB_MACRO_OK ", typeof(c), " ", string(c)[1:min(end,160)])
'''
            if kid:
                o = run_code(f"{ws_base}/api/kernels/{kid}/channels", tok, jname, code_jl, 600, ins)
                R["items"]["7_julia_ggb_macro"] = {**o, "kernel": jname, "pass": "GGB_MACRO_OK" in o["stdout"]}
                print("⑦ julia:", o["status"], "\n" + o["stdout"].strip()[-600:], "\nERR:" + o["stderr"].strip()[-600:] if o["stderr"].strip() else "", (o["error"] or "")[:300])
                http(f"{base}/api/kernels/{kid}", "DELETE", headers=tok, insecure=ins)
        else:
            R["items"]["7_julia_ggb_macro"] = {"pass": False, "kernelspecs": names}
    if a.out:
        open(a.out, "w").write(json.dumps(R, ensure_ascii=False, indent=1) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
