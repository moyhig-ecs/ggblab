"""Stage 4: the Julia host speaks the SAME request JSON as the Python host (the browser's `handle` is one function for
both) and mounts the SAME JavaScript.  The contract is checked by running julia (skipped when julia is not installed)."""
import json, shutil, subprocess
from pathlib import Path
import pytest

from ggblab.host.base import Eval, XmlIn, XmlOut, Listen, Delete, Value, Kind, New, to_json
import ggblab.host.html_host as H

ROOT = Path(__file__).resolve().parents[1]
JL = ROOT / "julia/host/html_host.jl"
julia = shutil.which("julia")


def test_mount_js_is_one_file_for_both_hosts():
    js = (ROOT / "ggblab/host/mount.js").read_text(encoding="utf-8")
    assert H.JS == js and "__CFG__" in js and "pollLoop" in js
    assert 'joinpath(@__DIR__, "..", "..", "ggblab", "host", "mount.js")' in JL.read_text(encoding="utf-8")


@pytest.mark.skipif(julia is None, reason="julia not installed")
def test_request_json_parity_for_all_eight_verbs():
    py = {
        "eval": to_json(Eval(("A = (1, 2)", "Circle(A, 1)")), "r"),
        "xml_in": to_json(XmlIn("<construction/>"), "r"),
        "xml_out": to_json(XmlOut(), "r"),
        "listen": to_json(Listen(True), "r"),
        "delete": to_json(Delete("A"), "r"),
        "value": to_json(Value("a"), "r"),
        "kind": to_json(Kind("c"), "r"),
        "new": to_json(New(), "r"),
    }
    code = f'''
include("{JL}"); using .GGBLabHost, JSON
out = Dict(
  "eval" => GGBLabHost.request(:eval; commands=["A = (1, 2)", "Circle(A, 1)"], req_id="r"),
  "xml_in" => GGBLabHost.request(:xml_in; xml="<construction/>", req_id="r"),
  "xml_out" => GGBLabHost.request(:xml_out; req_id="r"),
  "listen" => GGBLabHost.request(:listen; enable=true, req_id="r"),
  "delete" => GGBLabHost.request(:delete; label="A", req_id="r"),
  "value" => GGBLabHost.request(:value; label="a", req_id="r"),
  "kind" => GGBLabHost.request(:kind; label="c", req_id="r"),
  "new" => GGBLabHost.request(:new; req_id="r"))
println(JSON.json(out))
println(GGBLabHost.mount_key("examples/x.ipynb", "k", nothing), "|", GGBLabHost.mount_key(nothing, "k", nothing), "|", GGBLabHost.mount_key("p", "k", "two"))
println(GGBLabHost._q("doc:examples/x.ipynb"))
'''
    r = subprocess.run([julia, "-e", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    lines = r.stdout.strip().splitlines()
    jl = json.loads(lines[-3])
    assert jl == py, (jl, py)
    assert lines[-2] == "doc:examples/x.ipynb|kernel:k|doc:p:two"
    assert lines[-1] == "doc%3Aexamples%2Fx.ipynb"


@pytest.mark.skipif(julia is None, reason="julia not installed")
def test_julia_kernel_id_is_empty_outside_a_kernel():
    r = subprocess.run([julia, "-e", f'include("{JL}"); using .GGBLabHost; print(repr(GGBLabHost.kernel_id()))'], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1000:]
    assert r.stdout.strip() == '""'
