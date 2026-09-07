from ggblab.parse import parse_cell
from ggblab.adapter import plan, apply, HostWord, UnsupportedHostWord
from ggblab.host.base import Eval
import pytest

CELL = """@ggb :const :new
@ggb O=(0,0)
@ggb Circle(:O, 1)
@ggb P=(1, 0)
@ggb Q=(-1, 0)
@ggb Segment(:P, :Q)
@ggb :api getVersion()
"""

def test_plan_batches_between_directives():
    st = plan(parse_cell(CELL))
    assert st == (HostWord("newConstruction"),
                  Eval(("O = (0, 0)", "Circle(O, 1)", "P = (1, 0)", "Q = (-1, 0)", "Segment(P, Q)")),
                  HostWord("api", "getVersion()"))

class FakeHost:
    def __init__(self): self.sent = []
    def command(self, *cmds, timeout=10.0): self.sent.append(("eval", cmds)); return [["lbl"] for _ in cmds]
    def delete(self, label, timeout=10.0): self.sent.append(("delete", label)); return True
    def new_construction(self, timeout=10.0): self.sent.append(("new",)); return True

def test_apply_new_then_eval_then_stops_at_api():
    h = FakeHost()
    with pytest.raises(UnsupportedHostWord):
        apply(h, parse_cell(CELL))                     # :const :new → New verb; :api f() is still not a verb → raised after the batch
    assert h.sent == [("new",), ("eval", ("O = (0, 0)", "Circle(O, 1)", "P = (1, 0)", "Q = (-1, 0)", "Segment(P, Q)"))]

def test_apply_sends_one_eval_per_batch():
    h = FakeHost()
    body = "\n".join(l for l in CELL.splitlines() if not l.startswith("@ggb :"))
    out = apply(h, parse_cell(body))
    assert h.sent == [("eval", ("O = (0, 0)", "Circle(O, 1)", "P = (1, 0)", "Q = (-1, 0)", "Segment(P, Q)"))] and len(out) == 1

def test_undo_deletes_last_label():
    h = FakeHost()
    apply(h, parse_cell("@ggb O=(0,0)\n@ggb c = Circle(:O, 1)\n@ggb :const :undo"))
    assert h.sent[-1] == ("delete", "c")
