"""`%%ggb <host>` — the Python surface of the Construction type (stage 3, PLAN 09-03: "`%%ggb` は Construction 型を吐く").

    %load_ext ggblab.ipymagic
    g = GeoGebra(...)            # any v2 host façade (command / delete / new_construction)
    %%ggb g
    A = (2, 1)
    Circle(:A, 1)

The cell body is parsed with the closed-world parser (`parse_cell(..., dialect="python")`: 28 heads, `:label` refs,
an unknown head is an error, not a guess), planned by the stage-2 adapter (consecutive statements → ONE `Eval`;
`:const :new` → the `new` verb; `:api f()` is not a verb and raises) and applied to the host you name.  The result
(`_`) is the flat list of labels the applet returned, as v1's magic returned them (eg12: `ls[0] |= set(_)`).

No hidden state: v1's magic looked for an implicit applet (`GeoGebra._instance`, `user_ns["ggb"]`); here the host is
an explicit argument, resolved from the user namespace by name.  `--plan` returns the plan instead of sending.
"""
from __future__ import annotations

import shlex
from typing import Any

from IPython.core.magic import Magics, cell_magic, magics_class

from .adapter import apply, plan
from .parse import parse_cell


def flatten_labels(replies: list) -> list:
    """Per-step replies → the flat label list (an Eval reply is a list per command, each a list of labels or None)."""
    out: list = []
    for r in replies:
        if isinstance(r, list):
            for x in r:
                if isinstance(x, list):
                    out.extend(x)
                elif isinstance(x, str):
                    out.extend(l for l in x.split(",") if l)      # evalCommandGetLabels: "t1,c,a,b" for Polygon(A, B, C)
                elif x is not None and not isinstance(x, bool):
                    out.append(x)                                  # {"error": …}: the Apps API threw for that command
    return out


@magics_class
class GGBMagics(Magics):
    @cell_magic
    def ggb(self, line: str, cell: str) -> Any:
        args = shlex.split(line or "")
        if not args:
            raise ValueError("usage: %%ggb <host-variable> [--plan] [--timeout S]")
        name = args[0]
        want_plan = "--plan" in args
        timeout = float(args[args.index("--timeout") + 1]) if "--timeout" in args else 10.0
        host = self.shell.user_ns.get(name)
        if host is None and not want_plan:
            raise NameError(f"%%ggb: no host named {name!r} in the notebook namespace")
        construction = parse_cell(cell, dialect="python")
        if want_plan:
            return plan(construction)
        return flatten_labels(apply(host, construction, timeout=timeout))


def load_ipython_extension(ip) -> None:
    ip.register_magics(GGBMagics)


__all__ = ["GGBMagics", "flatten_labels", "load_ipython_extension"]
