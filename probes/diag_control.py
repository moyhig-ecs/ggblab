import os, sys, time
from jupyter_client import KernelManager
WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
km = KernelManager(kernel_name="python3")
km.start_kernel(env={**os.environ, "PYTHONPATH": WT + os.pathsep + os.environ.get("PYTHONPATH", "")})
kc = km.client(); kc.start_channels(); kc.wait_for_ready(timeout=120)
def run(code, timeout=30):
    mid = kc.execute(code); out = []; t_end = time.time() + timeout
    while time.time() < t_end:
        try: m = kc.get_iopub_msg(timeout=5)
        except Exception: continue
        if m["parent_header"].get("msg_id") != mid: continue
        if m["msg_type"] == "stream": out.append(m["content"]["text"])
        elif m["msg_type"] == "error": out.append("ERROR: " + m["content"]["ename"] + ": " + m["content"]["evalue"])
        elif m["msg_type"] == "status" and m["content"]["execution_state"] == "idle": break
    return "".join(out).strip()
print("[1] control channel alive? kernel_info_request on CONTROL ->", end=" ")
kc2 = km.client(); kc2.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
msg = kc2.session.msg("kernel_info_request", {}); kc2.control_channel.send(msg)
try:
    rep = kc2.get_control_msg(timeout=15); print(rep["msg_type"], "(ok)")
except Exception as e: print("NO REPLY", repr(e))
print("[2] open comm in kernel ->", run("import threading; from ggblab.host.control import ControlComm; c = ControlComm(); print('comm', c.comm_id); c._pending['S']={'event':threading.Event(),'data':None,'t0':0}; c._pending['C']={'event':threading.Event(),'data':None,'t0':0}; c._pending['B']={'event':threading.Event(),'data':None,'t0':0}"))
cid = run("print(c.comm_id)")
print("[3] comm_msg on SHELL while idle ->", end=" ")
kc.shell_channel.send(kc.session.msg("comm_msg", {"comm_id": cid, "data": {"req_id": "S", "data": 1}}))
time.sleep(1.0); print(run("print('S set =', c._pending['S']['event'].is_set(), '| threads seen =', sorted(c.thread_seen))"))
print("[4] comm_msg on CONTROL while idle ->", end=" ")
kc2.control_channel.send(kc2.session.msg("comm_msg", {"comm_id": cid, "data": {"req_id": "C", "data": 2}}))
time.sleep(1.0); print(run("print('C set =', c._pending['C']['event'].is_set(), '| threads seen =', sorted(c.thread_seen))"))
print("[5] comm_msg on CONTROL while the shell is BLOCKED ->")
mid = kc.execute("import time; t0=time.time(); d=c.wait('B', timeout=15); print('GOT', d, 'after', round(time.time()-t0,2), 's; threads', sorted(c.thread_seen))")
time.sleep(1.5); kc2.control_channel.send(kc2.session.msg("comm_msg", {"comm_id": cid, "data": {"req_id": "B", "data": 3}}))
out=[]; t_end=time.time()+30
while time.time()<t_end:
    try: m=kc.get_iopub_msg(timeout=5)
    except Exception: continue
    if m["parent_header"].get("msg_id")!=mid: continue
    if m["msg_type"]=="stream": out.append(m["content"]["text"])
    elif m["msg_type"]=="error": out.append("ERROR: "+m["content"]["ename"]+": "+m["content"]["evalue"])
    elif m["msg_type"]=="status" and m["content"]["execution_state"]=="idle": break
print("   ", "".join(out).strip())
kc.stop_channels(); kc2.stop_channels(); km.shutdown_kernel(now=True)
