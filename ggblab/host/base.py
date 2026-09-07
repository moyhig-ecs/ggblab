"""C1 — the frozen host interface: the closed subset of the GeoGebra Apps API that hosts implement (+ mount).

Each Verb kind is exactly one API method (teacher 2026-09-07: "respect the GeoGebra API"); the surface words of the
Julia macro / Python magic (`:const :new`, `:api f()`) are a separate matter.  Heads (C3): every request from the kernel
to the applet is one of the kinds below; a host adapter must handle all of them (`assert_never`).  Adding a kind is an
interface change: the C3 instrument (probes/stage_codegraph_v2.py, M2) records it against its allow-list.
  eval → evalCommandGetLabels   xml_in → setXML   xml_out → getXML   listen → register*Listener
  delete → deleteObject         value → getValue  new → newConstruction (stage 2, 2026-09-07)
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Callable, Literal, Union


class Verb(str, Enum):
    EVAL = "eval"          # command string(s) -> labels
    XML_IN = "xml_in"      # replace construction from XML
    XML_OUT = "xml_out"    # get construction XML
    LISTEN = "listen"      # (un)register object update listener
    DELETE = "delete"      # delete object by label
    VALUE = "value"        # numeric / string value of an object
    NEW = "new"            # newConstruction(): empty the construction (stage 2 adapter: `:const :new`)


@dataclass(frozen=True)
class Eval:
    commands: tuple[str, ...]
    kind: Literal["eval"] = "eval"


@dataclass(frozen=True)
class XmlIn:
    xml: str
    kind: Literal["xml_in"] = "xml_in"


@dataclass(frozen=True)
class XmlOut:
    kind: Literal["xml_out"] = "xml_out"


@dataclass(frozen=True)
class Listen:
    enable: bool
    kind: Literal["listen"] = "listen"


@dataclass(frozen=True)
class Delete:
    label: str
    kind: Literal["delete"] = "delete"


@dataclass(frozen=True)
class Value:
    label: str
    kind: Literal["value"] = "value"


@dataclass(frozen=True)
class New:
    kind: Literal["new"] = "new"


Request = Union[Eval, XmlIn, XmlOut, Listen, Delete, Value, New]


class Host(Protocol):
    """A substrate that can mount the applet and answer Requests.

    `send` must NOT block on the shell channel: replies arrive through the control channel (Jupyter)
    or the reactive runtime (marimo / Pluto). `wait` blocks the caller (shell thread) on an Event
    that the control thread sets — that is the allowed shape (C2).
    """
    def mount(self) -> None: ...
    def send(self, req: Request) -> str: ...            # returns req_id
    def wait(self, req_id: str, timeout: float) -> object: ...
    def on_event(self, cb: Callable[[dict], None]) -> None: ...


def to_json(req: Request, req_id: str) -> dict:
    """One clause per head (C3); `assert_never` makes a missing clause a type error."""
    match req:
        case Eval(commands=c):   d = {"kind": "eval", "commands": list(c)}
        case XmlIn(xml=x):       d = {"kind": "xml_in", "xml": x}
        case XmlOut():           d = {"kind": "xml_out"}
        case Listen(enable=e):   d = {"kind": "listen", "enable": e}
        case Delete(label=l):    d = {"kind": "delete", "label": l}
        case Value(label=l):     d = {"kind": "value", "label": l}
        case New():              d = {"kind": "new"}
        case _:
            from typing import assert_never
            assert_never(req)
    d["req_id"] = req_id
    return d
