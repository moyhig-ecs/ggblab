"""set_xml leaves out the <gui> element (2026-09-29): the layout a file was saved with must not replace the applet's layout."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ggblab.host import html_host as H
from ggblab.host.base import XmlIn
from ggblab.xml_errata import construction_xml, without_gui
from ggblab_extra import read_ggb

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "examples").glob("*.ggb"))
JL = ROOT / "julia" / "host" / "html_host.jl"
julia = shutil.which("julia")


def julia_has(*pkgs):
    if not julia:
        return False
    r = subprocess.run([julia, "-e", "using " + ", ".join(pkgs)], capture_output=True, text=True, timeout=300)
    return r.returncode == 0


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_only_the_gui_element_is_removed(path):
    x = read_ggb(path)
    y = without_gui(x)
    assert "<gui>" in x and "<gui" not in y                      # positive control: the file has one; the result has none
    assert construction_xml(y) == construction_xml(x)            # the construction is untouched
    for keep in ("<euclidianView", "<kernel>", "<construction"):
        assert x.count(keep) == y.count(keep) >= 1 or x.count(keep) == y.count(keep) == 0
    head = x[: x.index("<gui>")]
    assert y.startswith(head.rstrip(" \t"))                      # everything before <gui> is byte-identical
    assert without_gui(y) == y                                   # idempotent


def test_a_document_without_gui_is_returned_as_it_is():
    for x in ("<construction/>", '<geogebra format="5.0"><construction></construction></geogebra>', ""):
        assert without_gui(x) == x
    assert without_gui('<geogebra><gui/>\n<construction/></geogebra>') == "<geogebra><construction/></geogebra>"


def test_set_xml_sends_the_document_without_gui_unless_asked(monkeypatch):
    sent = []
    g = object.__new__(H.GeoGebra)
    monkeypatch.setattr(H.GeoGebra, "_rpc", lambda self, req, timeout: sent.append(req) or True, raising=True)
    x = read_ggb(FILES[0])
    assert g.set_xml(x) is True and g.set_xml(x, gui=True) is True
    assert isinstance(sent[0], XmlIn) and "<gui" not in sent[0].xml and sent[0].xml == without_gui(x)
    assert sent[1].xml == x


@pytest.mark.skipif(not julia_has("JSON"), reason="needs julia with the package JSON")
def test_julia_without_gui_is_byte_identical_to_python(tmp_path):
    want = {}
    for p in FILES:
        x = read_ggb(p)
        (tmp_path / (p.stem + ".xml")).write_text(x, encoding="utf-8")
        want[p.stem] = without_gui(x)
    code = f'''
include("{JL}"); using .GGBLabHost, JSON
out = Dict(splitext(basename(f))[1] => GGBLabHost.without_gui(read(f, String)) for f in readdir("{tmp_path}"; join=true))
println(JSON.json(out))
'''
    r = subprocess.run([julia, "-e", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got == want
