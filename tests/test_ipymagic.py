"""Stage 3 `%%ggb` magic: explicit host, closed-world parse, one Eval per batch, labels flattened as v1 returned them."""
import pytest
from IPython.testing.globalipapp import get_ipython

from ggblab.host.base import Eval
from ggblab.adapter import HostWord
from ggblab.parse import UnknownHead


class FakeHost:
    def __init__(self): self.sent = []
    def command(self, *cmds, timeout=10.0):
        self.sent.append(("eval", cmds))
        return ["t1,c,a,b" if c.startswith("Polygon") else (None if c.startswith("Bad") else f"L{i}") for i, c in enumerate(cmds)]
    def delete(self, label, timeout=10.0): self.sent.append(("delete", label)); return True
    def new_construction(self, timeout=10.0): self.sent.append(("new",)); return True


@pytest.fixture(scope="module")
def ip():
    ip = get_ipython()
    ip.run_line_magic("load_ext", "ggblab.ipymagic")
    return ip


def test_magic_sends_one_eval_and_returns_flat_labels(ip):
    h = FakeHost(); ip.user_ns["g"] = h
    out = ip.run_cell_magic("ggb", "g", "A = (2, 1)\nB = (-1, 2)\nCircle(:A, 1)\nPolygon(:A, :B, :B)\n")
    assert h.sent == [("eval", ("A = (2, 1)", "B = (-1, 2)", "Circle(A, 1)", "Polygon(A, B, B)"))]
    assert out == ["L0", "L1", "L2", "t1", "c", "a", "b"]          # "t1,c,a,b" (one command, four objects) is split


def test_magic_new_directive_uses_the_new_verb(ip):
    h = FakeHost(); ip.user_ns["g"] = h
    ip.run_cell_magic("ggb", "g", ":const :new\nO = (0, 0)\n")
    assert h.sent == [("new",), ("eval", ("O = (0, 0)",))]


def test_magic_plan_does_not_send(ip):
    h = FakeHost(); ip.user_ns["g"] = h
    st = ip.run_cell_magic("ggb", "g --plan", "O = (0, 0)\nCircle(:O, 1)\n")
    assert st == (Eval(("O = (0, 0)", "Circle(O, 1)")),) and h.sent == []


def test_magic_unknown_head_is_an_error_not_a_guess(ip):
    ip.user_ns["g"] = FakeHost()
    with pytest.raises(UnknownHead):
        ip.run_cell_magic("ggb", "g", "a = Cylinder(C, D, 1)\n")


def test_magic_requires_an_explicit_host(ip):
    ip.user_ns.pop("nohost", None)
    with pytest.raises(NameError):
        ip.run_cell_magic("ggb", "nohost", "O = (0, 0)\n")
