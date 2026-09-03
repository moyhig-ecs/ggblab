"""stage 0 / Julia: does a comm_msg sent on the CONTROL socket reach an IJulia comm handler while a cell blocks the shell?
Run A: reply via control channel (expected: delivered while the cell waits).
Run B: same message via shell channel (negative control; expected: NOT delivered until the cell finishes)."""
import sys, time, json
from jupyter_client import KernelManager

JULIA = r'''
using IJulia
let ch = Channel{Any}(2)
    reqtask = try IJulia._default_kernel.requests_task[] catch; nothing end
    on_msg = msg -> put!(ch, (data=msg.content["data"], on_requests_task=(current_task() === reqtask)))
    comm = IJulia.CommManager.Comm("ggblab_control", string(IJulia.uuid4()), true, on_msg; data=Dict("role"=>"reply-channel"))
    println("COMM_ID ", comm.id); flush(stdout)
    t0 = time()
    timer = Timer(8.0) do _; put!(ch, (data=Dict("via"=>"TIMEOUT"), on_requests_task=false)); end
    r = take!(ch)          # yields; the control task can run while this cell "blocks" the shell
    close(timer)
    println("GOT|", get(r.data, "via", "?"), "|on_requests_task=", r.on_requests_task, "|after=", round(time()-t0, digits=2), "s"); flush(stdout)
end
'''

def run(kc, channel):
    mid = kc.execute(JULIA)
    cid = None; got = None; buf = ""; busy_seen = False; t_send = None; t_end = time.time() + 60
    while time.time() < t_end:
        try: m = kc.get_iopub_msg(timeout=2)
        except Exception: m = None
        if m and m["parent_header"].get("msg_id") == mid:
            if m["msg_type"] == "status" and m["content"]["execution_state"] == "busy": busy_seen = True
            if m["msg_type"] == "stream":
                buf += m["content"]["text"]
                import re
                mm = re.search(r"COMM_ID (\S+)", buf); cid = mm.group(1) if mm else cid
                mm = re.search(r"GOT\|[^\n]*", buf); got = mm.group(0) if mm else got
            if m["msg_type"] == "error": got = "ERROR " + m["content"]["evalue"][:200]
            if m["msg_type"] == "status" and m["content"]["execution_state"] == "idle" and got: break
        if cid and t_send is None:
            time.sleep(1.5)                      # cell is now blocked in take!
            content = {"comm_id": cid, "data": {"labels": ["A"], "via": channel}}
            msg = kc.session.msg("comm_msg", content)
            (kc.control_channel if channel == "control" else kc.shell_channel).send(msg)
            t_send = time.time()
    return cid, got, busy_seen

km = KernelManager(kernel_name="julia-1.12"); km.start_kernel(cwd=sys.argv[1] if len(sys.argv) > 1 else None)
kc = km.client(); kc.start_channels(); kc.wait_for_ready(timeout=240)
print("kernel ready:", km.kernel_id if hasattr(km, "kernel_id") else "-", flush=True)
try:
    for ch in ("control", "shell"):
        cid, got, busy = run(kc, ch)
        print(f"[{ch:7s}] comm {cid} busy_seen={busy} -> {got}", flush=True)
finally:
    kc.stop_channels(); km.shutdown_kernel(now=True)
