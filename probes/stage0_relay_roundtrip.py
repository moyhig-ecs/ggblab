#!/usr/bin/env python3
"""Stage-0 headless probe #2: the full Jupyter host path minus the applet JS.
jupyter_server (with ggblab.host.relay enabled) -> REST start kernel -> connect via jupyter_client to that kernel ->
open ControlComm and block the shell -> simulate the browser: HTTP POST <base>/ggblab/reply (token auth) ->
relay sends comm_msg on the kernel's CONTROL socket -> the blocked cell returns. PASS = cell prints GOT ... via relay.
"""
import os, sys, time, json, subprocess, socket, urllib.request, secrets, glob
WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {**os.environ, "PYTHONPATH": WT + os.pathsep + os.environ.get("PYTHONPATH", "")}
port = 8000 + secrets.randbelow(1000); token = secrets.token_hex(8)
runtime = os.path.join(WT, "probes", ".runtime_" + token[:4]); os.makedirs(runtime, exist_ok=True)
env["JUPYTER_RUNTIME_DIR"] = runtime
cfg = os.path.join(runtime, "jupyter_server_config.py")
open(cfg, "w").write('c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}\n')
srv = subprocess.Popen([sys.executable, "-m", "jupyter_server", "--config=%s" % cfg, "--ServerApp.port=%d" % port, "--ServerApp.token=%s" % token,
                        "--ServerApp.open_browser=False", "--ServerApp.root_dir=%s" % WT, "--ServerApp.allow_remote_access=False", "--no-browser"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
base = f"http://127.0.0.1:{port}"
def api(path, data=None, method=None):
    req = urllib.request.Request(base + path, data=(json.dumps(data).encode() if data is not None else None),
                                 headers={"Authorization": "token " + token, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"{}")
# wait for server
for _ in range(60):
    try: s, _ = api("/api/status"); break
    except Exception: time.sleep(0.5)
else: print("server did not start"); print(srv.stdout.read()); sys.exit(1)
print("server up on", base)
s, k = api("/api/kernels", {"name": "python3"}, "POST"); kid = k["id"]; print("kernel started via REST:", kid)
# connect to that kernel with jupyter_client (same machine; connection file in the runtime dir)
from jupyter_client import BlockingKernelClient
cf = None
for _ in range(60):
    c = glob.glob(os.path.join(runtime, f"kernel-{kid}.json"))
    if c: cf = c[0]; break
    time.sleep(0.5)
kc = BlockingKernelClient(); kc.load_connection_file(cf); kc.start_channels(); kc.wait_for_ready(timeout=120)
def run(code, timeout=60):
    mid = kc.execute(code); out=[]; t_end=time.time()+timeout
    while time.time()<t_end:
        try: m=kc.get_iopub_msg(timeout=5)
        except Exception: continue
        if m["parent_header"].get("msg_id")!=mid: continue
        if m["msg_type"]=="stream": out.append(m["content"]["text"])
        elif m["msg_type"]=="error": out.append("ERROR: "+m["content"]["ename"]+": "+m["content"]["evalue"])
        elif m["msg_type"]=="status" and m["content"]["execution_state"]=="idle": break
    return "".join(out).strip()
print(run("import threading; from ggblab import GeoGebra, kernel_id; g = GeoGebra(); c = g.ctl; c._pending['R']={'event':threading.Event(),'data':None,'t0':0}; print('kernel_id(from connection file) =', kernel_id()); print('widget comm_id (model_id) =', g.widget.model_id); print('control wired =', c.control_wired)"))
cid = run("print(g.widget.model_id)"); kid_in_kernel = run("print(kernel_id())")
print("kernel_id match (REST vs in-kernel):", kid == kid_in_kernel)
mid = kc.execute("import time; t0=time.time(); d=c.wait('R', timeout=20); print('GOT', d, 'after', round(time.time()-t0,2), 's; threads', sorted(c.thread_seen))")
time.sleep(1.5)
print("POST /ggblab/reply (simulated browser) ->", end=" ")
try:
    s, rep = api("/ggblab/reply", {"kernel_id": kid, "comm_id": cid, "req_id": "R", "data": {"labels": ["A"], "via": "relay"}}, "POST"); print(s, rep)
except urllib.error.HTTPError as e: print("HTTP", e.code, e.read()[:200])
out=[]; t_end=time.time()+30
while time.time()<t_end:
    try: m=kc.get_iopub_msg(timeout=5)
    except Exception: continue
    if m["parent_header"].get("msg_id")!=mid: continue
    if m["msg_type"]=="stream": out.append(m["content"]["text"])
    elif m["msg_type"]=="error": out.append("ERROR: "+m["content"]["ename"]+": "+m["content"]["evalue"])
    elif m["msg_type"]=="status" and m["content"]["execution_state"]=="idle": break
res="".join(out).strip(); print(res)
print("RESULT:", "PASS (browser-side POST -> relay -> control socket -> widget on_msg -> blocked cell returned)" if ("GOT" in res and "'via': 'relay'" in res and "Control" in res) else "FAIL")
kc.stop_channels()
try: api(f"/api/kernels/{kid}", None, "DELETE")
except Exception: pass
srv.terminate()
try: srv.wait(timeout=10)
except Exception: srv.kill()
if "PASS" not in res and "GOT" not in res:
    print("--- server log tail:"); print("".join(srv.stdout.readlines()[-30:]))
