"""B6 "paper" (10-05): png / svg are verbs of the closed subset (allow-list ruling pending), one API method each."""
import re
from pathlib import Path
from ggblab.host.base import Png, Svg, Verb, to_json

ROOT = Path(__file__).resolve().parents[1]


def test_to_json_of_the_projections():
    assert to_json(Png(2, True, 96), "r1") == {"kind": "png", "scale": 2, "transparent": True, "dpi": 96, "req_id": "r1"}
    assert to_json(Png(), "r2") == {"kind": "png", "scale": 1.0, "transparent": False, "dpi": 72, "req_id": "r2"}
    assert to_json(Svg(), "r3") == {"kind": "svg", "req_id": "r3"}
    assert {Verb.PNG.value, Verb.SVG.value} == {"png", "svg"}


def test_mount_js_handles_every_verb_and_the_restore():
    js = (ROOT / "ggblab/host/mount.js").read_text(encoding="utf-8")
    handled = set(re.findall(r'case "([a-z_]+)":', js))
    assert {v.value for v in Verb} <= handled, {v.value for v in Verb} - handled
    assert "applyRestore()" in js and "j.restore" in js and "getPNGBase64" in js and "exportSVG" in js
