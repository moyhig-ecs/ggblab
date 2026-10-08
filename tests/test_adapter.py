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


# A2 (2026-10-08): `:const :undo` deletes the last label defined BEFORE the directive.  The expectations are literal
# (not "whatever the other language does"), so a defect shared by Python and Julia cannot pass.  The same cells and the
# same literals are checked on the Julia side in tests/test_julia_macro_parity.py.
UNDO_CASES = [   # (cell, the host calls in order, the labels alive at the end)
    ("A = (0, 0)\nB = (1, 0)\n:const :undo\nC = (2, 0)",
     [("eval", ("A = (0, 0)", "B = (1, 0)")), ("delete", "B"), ("eval", ("C = (2, 0)",))], ["A", "C"]),
    ("A = (0, 0)\nB = (1, 0)\n:const :undo\n:const :undo\nC = (2, 0)",
     [("eval", ("A = (0, 0)", "B = (1, 0)")), ("delete", "B"), ("delete", "A"), ("eval", ("C = (2, 0)",))], ["C"]),
    ("A = (0, 0)\n:const :new\nB = (1, 0)\n:const :undo",
     [("eval", ("A = (0, 0)",)), ("new",), ("eval", ("B = (1, 0)",)), ("delete", "B")], []),
]


class LiveHost(FakeHost):
    """FakeHost that also keeps the set of labels the applet would hold (delete of an absent label is a no-op False)."""
    def __init__(self): super().__init__(); self.live = []
    def command(self, *cmds, timeout=10.0):
        self.live += [c.split(" = ")[0] for c in cmds]; return super().command(*cmds, timeout=timeout)
    def delete(self, label, timeout=10.0):
        ok = label in self.live
        if ok: self.live.remove(label)
        super().delete(label, timeout=timeout); return ok
    def new_construction(self, timeout=10.0): self.live = []; return super().new_construction(timeout=timeout)


@pytest.mark.parametrize("cell,sent,live", UNDO_CASES)
def test_undo_deletes_the_label_before_the_directive(cell, sent, live):
    h = LiveHost()
    apply(h, parse_cell(cell, dialect="python"))
    assert h.sent == sent and h.live == live


def test_undo_plan_carries_the_label():
    st = plan(parse_cell(UNDO_CASES[0][0], dialect="python"))
    assert st == (Eval(("A = (0, 0)", "B = (1, 0)")), HostWord("undo", "B"), Eval(("C = (2, 0)",)))


def test_undo_with_nothing_before_it_raises():
    h = LiveHost()
    with pytest.raises(UnsupportedHostWord):
        apply(h, parse_cell(":const :undo\nA = (0, 0)", dialect="python"))
    assert h.sent == []
