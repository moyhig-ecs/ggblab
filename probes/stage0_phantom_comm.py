"""Phantom comm: a comm that exists only in the kernel's registry (no comm_open ever reaches the frontend).
Can the relay still inject a reply into it via the CONTROL socket while the cell blocks?  Python + Julia."""
import sys, time, re
from jupyter_client import KernelManager

PY = r'''
import threading, time
from comm import get_comm_manager
from ipykernel.comm import Comm
k = get_ipython().kernel
for t in ("comm_msg", "comm_close", "comm_open"):
    k.control_handlers[t] = getattr(k.comm_manager, t)
ev = threading.Event(); box = {}
c = Comm(target_name="ggblab_control", primary=False)      # no comm_open is published
get_comm_manager().register_comm(c)
c.on_msg(lambda msg: (box.update(data=msg["content"]["data"], thread=threading.current_thread().name), ev.set()))
print("COMM_ID", c.comm_id, flush=True)
t0 = time.time(); ok = ev.wait(8.0)
print("GOT|", box.get("data", {}).get("via", "TIMEOUT"), "|thread=", box.get("thread"), "|after=", round(time.time()-t0, 2), "s", sep="", flush=True)
'''
JL = r'''
using IJulia
let ch = Channel{Any}(2)
    reqtask = try IJulia._default_kernel.requests_task[] catch; nothing end
    on_msg = msg -> put!(ch, (data=msg.content["data"], on_requests_task=(current_task() === reqtask)))
    comm = IJulia.CommManager.Comm("ggblab_control", string(IJulia.uuid4()), false, on_msg)   # primary=false: no comm_open
    println("COMM_ID ", comm.id); flush(stdout)
    t0 = time()
    timer = Timer(8.0) do _; put!(ch, (data=Dict("via"=>"TIMEOUT"), on_requests_task=false)); end
    r = take!(ch); close(timer)
    println("GOT|", get(r.data, "via", "?"), "|on_requests_task=", r.on_requests_task, "|after=", round(time()-t0, digits=2), "s"); flush(stdout)
end
'''
def run(kc, code):
    mid = kc.execute(code); cid = got = None; buf = ""; sent = False; comm_open_seen = False; t_end = time.time() + 60
    while time.time() < t_end:
        try: m = kc.get_iopub_msg(timeout=2)
        except Exception: m = None
        if m and m["parent_header"].get("msg_id") == mid:
            if m["msg_type"] == "comm_open": comm_open_seen = True
            if m["msg_type"] == "stream":
                buf += m["content"]["text"]
                mm = re.search(r"COMM_ID (\S+)", buf); cid = mm.group(1) if mm else cid
                mm = re.search(r"GOT\|[^\n]*", buf); got = mm.group(0) if mm else got
            if m["msg_type"] == "error": got = "ERROR " + m["content"]["evalue"][:200]
            if m["msg_type"] == "status" and m["content"]["execution_state"] == "idle" and got: break
        if cid and not sent:
            time.sleep(1.5)
            kc.control_channel.send(kc.session.msg("comm_msg", {"comm_id": cid, "data": {"labels": ["A"], "via": "control"}})); sent = True
    return cid, got, comm_open_seen

for name, code in (("python3", PY), ("julia-1.12", JL)):
    km = KernelManager(kernel_name=name); km.start_kernel(cwd=sys.argv[1] if len(sys.argv) > 1 else None)
    kc = km.client(); kc.start_channels(); kc.wait_for_ready(timeout=240)
    try:
        cid, got, seen = run(kc, code)
        print(f"[{name:10s}] comm_open published to frontend: {seen} | comm {cid} -> {got}", flush=True)
    finally:
        kc.stop_channels(); km.shutdown_kernel(now=True)
