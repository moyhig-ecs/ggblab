#!/usr/bin/env python3
"""Stage-0 headless probe (no browser): start ipykernel, open ControlComm in the kernel, block the shell in a cell
waiting for req 'R', and from OUTSIDE send comm_msg on the CONTROL socket. PASS = the cell returns the data and
reports the handler ran on the control thread. This validates C0-A on the real ipykernel.
Run: PYTHONPATH=<worktree> python probes/stage0_control_roundtrip.py
"""
import os, sys, time, json
from jupyter_client import KernelManager

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
km = KernelManager(kernel_name="python3")
km.start_kernel(env={**os.environ, "PYTHONPATH": WT + os.pathsep + os.environ.get("PYTHONPATH", "")})
kc = km.client(); kc.start_channels(); kc.wait_for_ready(timeout=120)
print("kernel ready:", km.kernel_name, "| connection:", os.path.basename(km.connection_file))

def run(code, timeout=60):
    mid = kc.execute(code)
    out, seen = [], []
    t_end = time.time() + timeout
    while time.time() < t_end:
        try:
            m = kc.get_iopub_msg(timeout=5)
        except Exception:
            continue
        seen.append(m["msg_type"])
        if m["parent_header"].get("msg_id") != mid:
            continue
        t = m["msg_type"]
        if t == "stream": out.append(m["content"]["text"])
        elif t == "error": out.append("ERROR: " + "\n".join(m["content"]["traceback"]))
        elif t == "status" and m["content"]["execution_state"] == "idle": break
    else:
        out.append(f"TIMEOUT (seen iopub types: {seen[-8:]})")
    return "".join(out)

print("--- step 1: open ControlComm in the kernel")
print(run("import threading, sys; print('py', sys.version.split()[0]); from ggblab.host.control import ControlComm; c = ControlComm(); "
          "c._pending['R'] = {'event': threading.Event(), 'data': None, 't0': 0}; print('COMM', c.comm_id)"))
cid = run("print(c.comm_id)").strip().splitlines()[-1]
print("comm_id =", cid)

print("--- step 2: block the shell in a cell (wait up to 20 s for 'R')")
mid = kc.execute("import time; t0=time.time(); d = c.wait('R', timeout=20); print('GOT', d, 'after', round(time.time()-t0,2), 's; handler thread =', sorted(c.thread_seen))")
time.sleep(1.5)   # shell is now blocked inside wait()
print("--- step 3: send comm_msg on the CONTROL channel from outside (what relay.py does)")
kc2 = km.client(); kc2.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
msg = kc2.session.msg("comm_msg", {"comm_id": cid, "data": {"req_id": "R", "data": {"labels": ["A", "B"], "via": "control"}}})
kc2.control_channel.send(msg)
print("sent at t+1.5s; waiting for the cell to return")
out, seen = [], []
t_end = time.time() + 40
while time.time() < t_end:
    try: m = kc.get_iopub_msg(timeout=5)
    except Exception: continue
    if m["parent_header"].get("msg_id") != mid: continue
    if m["msg_type"] == "stream": out.append(m["content"]["text"])
    elif m["msg_type"] == "error": out.append("ERROR: " + "\n".join(m["content"]["traceback"]))
    elif m["msg_type"] == "status" and m["content"]["execution_state"] == "idle": break
res = "".join(out); print(res.strip())
ok = ("GOT" in res) and ("'via': 'control'" in res) and ("Control" in res) and ("after 1." in res or "after 2." in res)
print("RESULT:", "PASS (reply delivered on the control thread while the shell was blocked)" if ok else "FAIL")
kc.stop_channels(); kc2.stop_channels(); km.shutdown_kernel(now=True)
