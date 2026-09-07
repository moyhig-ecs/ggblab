"""Stage 2 — applet adapter: Construction → host Requests (C1), pure planning + one effectful `apply`.

`plan` turns a Construction into the sequence the current route would send: consecutive renderable statements are
batched into one `Eval` (the JS host evaluates them in order with evalCommandGetLabels); a Directive becomes a `HostWord`,
the host-side action the current route performs for it (stage 2 gate #1 recorded them verbatim from the v1 macro):
    :const :new   → newConstruction()        :const :undo → deleteObject(last label)
    :api f(args)  → applet API call f(args)  (not a construction statement; passed through for the host)
Teacher 2026-09-07: respect the GeoGebra API → `newConstruction()` became the Verb `New` (host.new_construction());
`:api f(args)` (arbitrary API calls) and the surface words of the Julia macro / Python magic are a separate matter, so
`apply` still raises UnsupportedHostWord for them instead of guessing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Union, assert_never
from .construction import Construction, Directive, Statement, render
from .host.base import Eval, Request, Delete


@dataclass(frozen=True)
class HostWord:
    """A host-side action requested by a Directive (never sent as a GeoGebra command)."""
    action: str                 # "newConstruction" | "undo" | "api"
    detail: str = ""            # for "api": the call text, e.g. "getVersion()"
    kind: str = "host_word"


Step = Union[Eval, HostWord]


def host_word(d: Directive) -> HostWord:
    w = d.words
    if len(w) >= 2 and w[0] == ":const" and w[1] == ":new":  return HostWord("newConstruction")
    if len(w) >= 2 and w[0] == ":const" and w[1] == ":undo": return HostWord("undo")
    if len(w) >= 2 and w[0] == ":api":                        return HostWord("api", " ".join(w[1:]))
    return HostWord("unknown", " ".join(w))


def plan(c: Construction) -> tuple[Step, ...]:
    """One clause per statement kind (C3); commands are batched between directives, in order."""
    steps: list[Step] = []; batch: list[str] = []
    def flush():
        if batch: steps.append(Eval(tuple(batch))); batch.clear()
    for s in c.statements:
        match s:
            case Directive():
                flush(); steps.append(host_word(s))
            case _:
                t = render(s)
                if t is not None: batch.append(t)
    flush()
    return tuple(steps)


class UnsupportedHostWord(NotImplementedError):
    pass


def apply(host, c: Construction, timeout: float = 10.0) -> list:
    """Send the plan to a stage-0 host (GeoGebra façade: .command / .delete / …). Returns the per-step replies."""
    out = []
    for st in plan(c):
        match st:
            case Eval(commands=cmds):
                out.append(host.command(*cmds, timeout=timeout))
            case HostWord(action="newConstruction"):
                out.append(host.new_construction(timeout=timeout))
            case HostWord(action="undo"):
                labels = c.labels()
                if not labels: raise UnsupportedHostWord(":const :undo with no labelled statement before it")
                out.append(host.delete(labels[-1], timeout=timeout))
            case HostWord(action="api", detail=d):
                raise UnsupportedHostWord(f":api {d}: applet API calls are not construction statements (no Verb)")
            case HostWord(action=a, detail=d):
                raise UnsupportedHostWord(f"unknown directive {a} {d}")
            case _:
                assert_never(st)
    return out
