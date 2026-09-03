#!/usr/bin/env python3
"""Stage-0 headless probe (no browser): start ipykernel, open ControlComm in the kernel, block the shell in a cell
waiting for req 'R', and from OUTSIDE send comm_msg on the CONTROL socket. PASS = the cell returns the data and
reports the handler ran on the control thread. This validates C0-A on the real ipykernel.
Run: PYTHONPATH=<worktree> python probes/stage0_control_roundtrip.py
"""
import json, os, sys, time, queue
from jupyter_client import KernelManager

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
km = KernelManager(kernel_name="python3")
km.start_kernel(env={**os.environ, "PYTHONPATH": WT + os.pathsep + os.environ.get("PYTHONPATH", "")})
kc = km.client(); kc.start_channels(); kc.wait_for_ready(timeout=60)

def run(code, timeout=30):
    mid = kc.execute(code)
    out = []
    while True:
        m = kc.get_iopub_msg(timeout=timeout)
        if m["parent_header"].get("msg_id") != mid: continue
        t = m["msg_type"]
        if t == "stream": out.append(m["content"]["text"])
        elif t == "error": out.append("ERROR: " + "\n".join(m["content"]["traceback"]))
        elif t == "status" and m["content"]["execution_state"] == "idle": break
    return "".join(out)

print(run("from ggblab.host.control import ControlComm; c = ControlComm(); print('COMM', c.comm_id); rid = 'R'; c._pending[rid] = {'event': __import__('threading').Event(), 'data': None, 't0': 0}"))
# find comm_id from the output above
kc2 = km.client(); kc2.start_channels()
# read comm_id by re-running a print (simplest)
cid = run("print(c.comm_id)").strip().splitlines()[-1]
print("comm_id =", cid)
# now block the shell: the cell waits for 'R' up to 15 s
mid = kc.execute("import threading, time; t0=time.time(); d = c.wait('R', timeout=15); print('GOT', json.dumps(d) if False else d, 'after', round(time.time()-t0,2), 's; handler thread =', c.thread_seen)")
time.sleep(1.0)   # shell is now blocked inside wait()
# send comm_msg on CONTROL from outside (what relay.py does)
msg = kc2.session.msg("comm_msg", {"comm_id": cid, "data": {"req_id": "R", "data": {"labels": ["A", "B"], "via": "control"}}})
kc2.control_channel.send(msg)
print("sent comm_msg on control at t+1.0s")
out = []
while True:
    m = kc.get_iopub_msg(timeout=30)
    if m["parent_header"].get("msg_id") != mid: continue
    if m["msg_type"] == "stream": out.append(m["content"]["text"])
    elif m["msg_type"] == "error": out.append("ERROR: " + "\n".join(m["content"]["traceback"]))
    elif m["msg_type"] == "status" and m["content"]["execution_state"] == "idle": break
res = "".join(out); print(res)
print("RESULT:", "PASS" if ("GOT" in res and "'via': 'control'" in res and "Control" in res) else "FAIL")
kc.stop_channels(); kc2.stop_channels(); km.shutdown_kernel(now=True)
