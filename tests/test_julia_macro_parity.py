"""Stage 4 (ruling A, 2026-09-11): the Julia string macro `ggb"…"` hands the RAW text to the Python closed-world parser
through PythonCall — so the Julia side sees exactly what the Python side sees (one parser, one Construction), and what
Julia's own parser would have rewritten (prime labels, juxtaposition, numeric literals) reaches the host byte for byte.
Skipped when julia / PythonCall are not available."""
import json, os, shutil, subprocess
from pathlib import Path
import pytest

from ggblab.parse import parse_cell

ROOT = Path(__file__).resolve().parents[1]
julia = shutil.which("julia")
PY = os.environ.get("JULIA_PYTHONCALL_EXE", "/Users/manabu/miniforge3/envs/py314/bin/python3")
ENV = {**os.environ, "JULIA_CONDAPKG_BACKEND": "Null", "JULIA_PYTHONCALL_EXE": PY, "PYTHONPATH": str(ROOT)}

BODIES = [
    "\n".join(json.loads((ROOT / "probes/stage2/gate2/groups.json").read_text())[1]["bodies"]),   # gate #2 g1 (lesson 04)
    "C' = l1(1)\nO'' = Intersect(f, g)\nsph1 = Sphere((0, 0, 1.8257), 0.6260)\nB = (cos(2π/5), sin(2π/5))\nm = (u v) / (v v)\nx = Distance(O, P)² + 1",
]


def _julia(code: str) -> str:
    r = subprocess.run([julia, "-e", code], capture_output=True, text=True, env=ENV, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout


@pytest.mark.skipif(julia is None or not Path(PY).exists(), reason="julia or the conda python not installed")
def test_string_macro_is_byte_identical_to_the_python_parser():
    code = f'''
include("{ROOT / 'julia/host/html_host.jl'}"); include("{ROOT / 'julia/host/ggb_macro.jl'}"); using .GGBLabHost, .GGBLabMacro, PythonCall, JSON
bodies = JSON.parse(raw"""{json.dumps(BODIES)}""")
out = [to_ggb(parse_ggb(b)) for b in bodies]
plans = [[pyconvert(String, pytype(st).__name__) for st in plan(parse_ggb(b))] for b in bodies]
println(JSON.json(Dict("out" => out, "plans" => plans)))
'''
    d = json.loads(_julia(code).strip().splitlines()[-1])
    for body, jl in zip(BODIES, d["out"]):
        assert jl == list(parse_cell(body, dialect="python").to_ggb())
    # the v1-breaking constructs reach the host unchanged
    assert d["out"][1][:2] == ["C' = l1(1)", "O'' = Intersect(f, g)"]
    assert "0.6260" in d["out"][1][2] and "2π/5" in d["out"][1][3] and "(u v) / (v v)" in d["out"][1][4] and "²" in d["out"][1][5]
    assert d["plans"][0] == ["Eval"]


@pytest.mark.skipif(julia is None or not Path(PY).exists(), reason="julia or the conda python not installed")
def test_closed_world_crosses_the_boundary():
    code = f'''
include("{ROOT / 'julia/host/html_host.jl'}"); include("{ROOT / 'julia/host/ggb_macro.jl'}"); using .GGBLabHost, .GGBLabMacro, PythonCall
for s in ("Cylinder(A, B, 1)", "Circle(_1, 1)", "l1 = {{Intersect(c, p)}}\\nA = L1(1)")
    try
        parse_ggb(s); println("NO-ERROR")
    catch e
        println(e isa ClosedWorldError ? "ClosedWorldError: " * first(e.msg, 60) : "OTHER: " * string(typeof(e)))
    end
end
c = ggb"""
:const :new
A = (0, 0)
c = Circle(:A, 1)
"""
println(join(to_ggb(c), " | "), " || ", join(labels(c), ","))
'''
    lines = _julia(code).strip().splitlines()
    assert lines[0].startswith("ClosedWorldError") and "Cylinder" in lines[0]
    assert lines[1].startswith("ClosedWorldError") and "relative reference" in lines[1]
    assert lines[2].startswith("ClosedWorldError") and "L1" in lines[2]
    assert lines[3] == "A = (0, 0) | c = Circle(A, 1) || A,c"
