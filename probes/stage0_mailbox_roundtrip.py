"""stage 0 v2 headless: jupyter_server + mailbox extension. The kernel runs GeoGebra() (HTML mount goes to iopub and is
ignored); this script plays the browser: long-poll /ggblab/poll for the request, POST /ggblab/reply -> control socket ->
phantom comm -> the blocked cell returns."""
import json, os, re, subprocess, sys, time, urllib.request
from jupyter_client import BlockingKernelClient, find_connection_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "probes", ".runtime_mailbox")
os.makedirs(RUN, exist_ok=True)
PORT, TOKEN = 8897, "probetoken"
BASE = f"http://127.0.0.1:{PORT}"
H = {"Authorization": f"token {TOKEN}", "Content-Type": "application/json"}
open(os.path.join(RUN, "jupyter_server_config.py"), "w").write(
    'c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True, "jupyter_server_documents": False}\n')

def http(method, path, body=None, timeout=30):
    req = urllib.request.Request(BASE + path, data=(json.dumps(body).encode() if body is not None else None), method=method, headers=H)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        try: return r.status, json.loads(raw or b"null")
        except Exception: return r.status, raw[:200]

env = dict(os.environ, PYTHONPATH=ROOT)
srv = subprocess.Popen([sys.executable, "-m", "jupyter_server", f"--config={RUN}/jupyter_server_config.py", f"--ServerApp.port={PORT}",
                        "--ServerApp.ip=127.0.0.1", f"--IdentityProvider.token={TOKEN}", "--ServerApp.open_browser=False",
                        f"--ServerApp.root_dir={RUN}"], env=env, stdout=open(os.path.join(RUN, "server.log"), "w"), stderr=subprocess.STDOUT)
try:
    for _ in range(60):
        try: http("GET", "/api/status"); break
        except Exception: time.sleep(0.5)
    st, k = http("POST", "/api/kernels", {"name": "python3"}); kid = k["id"]
    kc = BlockingKernelClient(); kc.load_connection_file(find_connection_file(f"kernel-{kid}.json")); kc.start_channels(); kc.wait_for_ready(timeout=60)
    code = r'''
import time
from ggblab import GeoGebra
g = GeoGebra()
print("MOUNT", g.mount_id, "COMM", g.ctl.comm_id, "SERVER", g.server_url, flush=True)
t0 = time.time()
try:
    r = g.command("A=(1,2)", timeout=20)
    print("GOT", r, "after", round(time.time()-t0, 2), "s | threads", sorted(g.ctl.thread_seen), flush=True)
except Exception as e:
    print("ERR", type(e).__name__, e, flush=True)
'''
    mid = kc.execute(code); buf = ""; mount = comm = None; replied = False; result = None; t_end = time.time() + 60
    while time.time() < t_end:
        try: m = kc.get_iopub_msg(timeout=1)
        except Exception: m = None
        if m and m["parent_header"].get("msg_id") == mid:
            if m["msg_type"] == "stream": buf += m["content"]["text"]
            if m["msg_type"] == "error": result = "ERROR " + m["content"]["evalue"][:300]; break
            if m["msg_type"] == "status" and m["content"]["execution_state"] == "idle" and ("GOT" in buf or "ERR" in buf): break
        mm = re.search(r"MOUNT (\S+) COMM (\S+) SERVER (\S+)", buf)
        if mm and not replied:
            mount, comm, server = mm.groups()
            st, j = http("GET", f"/ggblab/poll?mount={mount}&wait=10", timeout=20)          # browser side: long-poll
            reqs = j["requests"]
            print("poll ->", st, reqs, flush=True)
            if reqs:
                req = reqs[0]
                st2, j2 = http("POST", "/ggblab/reply", {"kernel_id": kid, "comm_id": comm, "req_id": req["req_id"],
                                                          "data": {"labels": ["A"], "via": "mailbox", "kind_seen": req["kind"]}})
                print("reply ->", st2, j2, flush=True)
            replied = True
    print("kernel said:", (re.search(r"(GOT|ERR)[^\n]*", buf) or [result or buf[-300:]])[0], "| server seen by kernel:", server if mount else None)
    kc.stop_channels()
    http("DELETE", f"/api/kernels/{kid}")
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
