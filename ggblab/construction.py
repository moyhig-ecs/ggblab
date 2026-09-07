"""C0-B / C4 — Construction: the algebra the replay starts from.

A Construction is an ordered sequence of statements.  Heads (C3, one clause per head):
  * Command   — one of the 28 GeoGebra command heads used by textbook-2026 L04–L13 (先生確定 2026-09-04);
                the set is CLOSED: a name outside HEADS is `UnknownHead` at parse time (closed-world gate).
  * FreePoint — `O=(0,0)` / `A=(1,2,3)`   (free object; the drag handle of the semantic axis)
  * FreeNumber— `k=2`                      (free scalar)
  * Definition— `G="(A+B+C)/3"`, `s=d1+d2`, `S={{1,k},{0,1}}`, `l_t="{Intersect(c,th)}"`  (expression kept verbatim;
                the surface `"…"` is Julia's escape hatch for expressions outside the 28 heads — it is NOT sent to the applet:
                stage 2 gate #1 showed the current route strips it on all 55 quoted lines, so `render` strips it too)
  * Directive — `:const :new`, `:api getVersion()`  (host-side words, not part of the construction)
Arguments are Ref (a label reference, written `:A` in the Julia flavour or bare `A` — teacher 2026-09-07: bare identifiers
are normalised to label references, they never name a host-language variable) / Num / Tup / Str / Raw / nested Command
(nesting is discouraged by the textbook discipline and is reported, not rejected).  Label identity follows GeoGebra 5.4
(measured 2026-09-07 through the API: `l_CA` ≡ `l_{CA}`, `A_12` ≡ `A_{12}`, `G_{s}` ≡ `G_s`, but `l_{C}A` ≠ `l_CA`):
`canonical_label` gives the braced form for identity (DAG), while the wire keeps the surface form (gate #2 byte equality).  Everything here is pure (effects live in host adapters, C1).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal, Union, get_args, assert_never

CommandHead = Literal[
    "Angle", "AngleBisector", "ApplyMatrix", "Circle", "ClosestPoint", "Cone", "Determinant", "Distance",
    "Ellipse", "Intersect", "IntersectConic", "Length", "Line", "Locus", "Midpoint", "Plane", "Point", "Polar",
    "Polygon", "PerpendicularBisector", "PerpendicularLine", "PerpendicularPlane", "Reflect", "Segment", "Slider",
    "Sphere", "TriangleCenter", "Vector",
]
HEADS: tuple[str, ...] = tuple(get_args(CommandHead))   # 28 — frozen interface (C7)
assert len(HEADS) == 28 and len(set(HEADS)) == 28


# ── arguments ──────────────────────────────────────────────────────────────────────────────────────
_SUB = re.compile(r"^([A-Za-z][A-Za-z0-9']*)_(?:\{([^{}]*)\}|([A-Za-z0-9]+))(.*)$")

def canonical_label(s: str) -> str:
    """GeoGebra label identity: `l_CA` and `l_{CA}` name the same object → `l_{CA}`; `l_{C}A` stays `l_{C}A`."""
    m = _SUB.match(s)
    return f"{m.group(1)}_{{{m.group(2) if m.group(2) is not None else m.group(3)}}}{m.group(4)}" if m else s

@dataclass(frozen=True)
class Ref:
    """A label reference: `:A` (Julia flavour) or bare `A`. `name` is the surface form; identity = canonical_label(name)."""
    name: str

@dataclass(frozen=True)
class Num:
    text: str            # verbatim (no float round-trip)

@dataclass(frozen=True)
class Tup:
    items: tuple["Arg", ...]   # (x, y[, z]) — point / vector literal

@dataclass(frozen=True)
class Str:
    text: str            # "…" GeoGebra expression passed as a string

@dataclass(frozen=True)
class Raw:
    text: str            # anything else, verbatim (e.g. `2*Tc - O2`, `{{1, k}, {0, 1}}`)

Arg = Union[Ref, Num, Tup, Str, Raw, "Command"]


# ── statements ─────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Command:
    head: CommandHead
    args: tuple[Arg, ...]
    label: str | None = None
    kind: Literal["command"] = "command"

@dataclass(frozen=True)
class FreePoint:
    label: str
    coords: Tup
    kind: Literal["free_point"] = "free_point"

@dataclass(frozen=True)
class FreeNumber:
    label: str
    value: Num
    kind: Literal["free_number"] = "free_number"

@dataclass(frozen=True)
class Definition:
    label: str | None
    expr: str
    quoted: bool
    kind: Literal["definition"] = "definition"

@dataclass(frozen=True)
class Directive:
    words: tuple[str, ...]
    kind: Literal["directive"] = "directive"

Statement = Union[Directive, FreePoint, FreeNumber, Definition, Command]


# ── rendering (Construction → GeoGebra command strings) ────────────────────────────────────────────
def render_arg(a: Arg) -> str:
    match a:
        case Ref(name=n):     return n
        case Num(text=t):     return t
        case Tup(items=it):   return "(" + ", ".join(render_arg(x) for x in it) + ")"
        case Str(text=t):     return t                       # the surface quotes are the escape hatch of `@ggb`, not GeoGebra text syntax (stage 2 gate #1)
        case Raw(text=t):     return t
        case Command():       return render_call(a)
        case _:               assert_never(a)

def render_call(c: Command) -> str:
    return f"{c.head}({', '.join(render_arg(x) for x in c.args)})"

def render(s: Statement) -> str | None:
    """GeoGebra command text for one statement; None for directives (they are host words, C1)."""
    match s:
        case Command(label=l):          return (f"{l} = " if l else "") + render_call(s)
        case FreePoint(label=l, coords=c): return f"{l} = {render_arg(c)}"
        case FreeNumber(label=l, value=v): return f"{l} = {v.text}"
        case Definition(label=l, expr=e, quoted=q):
            return (f"{l} = " if l else "") + e            # quoted or not, the current route sends the expression bare (stage 2 gate #1: 55 lines)
        case Directive():               return None
        case _:                         assert_never(s)


# ── signatures (one clause per head; arities from the GeoGebra manual, checked against the fixture) ─
@dataclass(frozen=True)
class Signature:
    min_args: int
    max_args: int | None     # None = variadic
    note: str

def signature(h: CommandHead) -> Signature:
    match h:
        case "Angle":                 return Signature(1, 3, "Angle(obj) | Angle(v,w) | Angle(A,B,C) | Angle(A,B,α)")
        case "AngleBisector":         return Signature(2, 3, "AngleBisector(l,m) | AngleBisector(A,B,C)")
        case "ApplyMatrix":           return Signature(2, 2, "ApplyMatrix(M, obj)")
        case "Circle":                return Signature(2, 3, "Circle(M,r) | Circle(M,A) | Circle(A,B,C) | Circle(M,r,axis)")
        case "ClosestPoint":          return Signature(2, 2, "ClosestPoint(path, P)")
        case "Cone":                  return Signature(2, 3, "Cone(circle,h) | Cone(A,B,r) | Cone(A,v,α)")
        case "Determinant":           return Signature(1, 1, "Determinant(M)")
        case "Distance":              return Signature(2, 2, "Distance(P, obj)")
        case "Ellipse":               return Signature(3, 3, "Ellipse(F1,F2,a) | Ellipse(F1,F2,segment) | Ellipse(F1,F2,P)")
        case "Intersect":             return Signature(2, 4, "Intersect(a,b) | Intersect(a,b,i) | Intersect(a,b,P) | Intersect(f,g,x1,x2)")
        case "IntersectConic":        return Signature(2, 2, "IntersectConic(plane, quadric)")
        case "Length":                return Signature(1, 3, "Length(obj) | Length(f,x1,x2) | Length(f,A,B)")
        case "Line":                  return Signature(2, 2, "Line(A,B) | Line(A, parallel) | Line(A, v)")
        case "Locus":                 return Signature(2, 2, "Locus(Q, P) | Locus(Q, slider)")
        case "Midpoint":              return Signature(1, 2, "Midpoint(segment|conic|interval) | Midpoint(A,B)")
        case "Plane":                 return Signature(1, 3, "Plane(polygon|conic) | Plane(A,l) | Plane(l,m) | Plane(A,B,C)")
        case "Point":                 return Signature(1, 2, "Point(obj) | Point(obj,t) | Point(list) | Point(A,v)")
        case "Polar":                 return Signature(2, 2, "Polar(P, conic)")
        case "Polygon":               return Signature(1, None, "Polygon(list) | Polygon(A,B,C,…) | Polygon(A,B,n[,dir])")
        case "PerpendicularBisector": return Signature(1, 3, "PerpendicularBisector(segment) | (A,B) | (A,B,direction)")
        case "PerpendicularLine":     return Signature(2, 3, "PerpendicularLine(P,l) | (P,v) | (P,plane) | (P,l,context)")
        case "PerpendicularPlane":    return Signature(2, 2, "PerpendicularPlane(P, l) | PerpendicularPlane(P, v)")
        case "Reflect":               return Signature(2, 2, "Reflect(obj, mirror)")
        case "Segment":               return Signature(2, 2, "Segment(A,B) | Segment(A, length)")
        case "Slider":                return Signature(2, 9, "Slider(min,max[,inc,speed,width,isAngle,horizontal,animating,random])")
        case "Sphere":                return Signature(2, 2, "Sphere(M, r) | Sphere(M, A)")
        case "TriangleCenter":        return Signature(4, 4, "TriangleCenter(A,B,C, n)")
        case "Vector":                return Signature(1, 2, "Vector(P) | Vector(A,B)")
        case _:                       assert_never(h)

def arity_ok(c: Command) -> bool:
    s = signature(c.head); n = len(c.args)
    return n >= s.min_args and (s.max_args is None or n <= s.max_args)


# ── the construction ───────────────────────────────────────────────────────────────────────────────
def references(a: Arg | Statement) -> tuple[str, ...]:
    """Names an argument/statement refers to (Ref and Ident), in order of appearance."""
    match a:
        case Ref(name=n):                  return (n,)
        case Num() | Str() | Raw():        return ()
        case Tup(items=it):                return tuple(x for i in it for x in references(i))
        case Command(args=ar):             return tuple(x for i in ar for x in references(i))
        case FreePoint(coords=c):          return references(c)
        case FreeNumber() | Definition() | Directive(): return ()
        case _:                            assert_never(a)

def nested_commands(c: Command) -> tuple[Command, ...]:
    out: list[Command] = []
    for x in c.args:
        if isinstance(x, Command): out.append(x); out.extend(nested_commands(x))
        elif isinstance(x, Tup):
            for y in x.items:
                if isinstance(y, Command): out.append(y); out.extend(nested_commands(y))
    return tuple(out)

@dataclass(frozen=True)
class Construction:
    statements: tuple[Statement, ...]

    def commands(self) -> tuple[Command, ...]:
        return tuple(s for s in self.statements if isinstance(s, Command))

    def labels(self) -> tuple[str, ...]:
        out: list[str] = []
        for s in self.statements:
            l = getattr(s, "label", None)
            if l: out.append(l)
        return tuple(out)

    def to_ggb(self) -> tuple[str, ...]:
        return tuple(t for s in self.statements if (t := render(s)) is not None)

    def dependencies(self) -> tuple[tuple[str, str], ...]:
        """Edges (referenced label → defined label) among labels defined in this construction (the DAG of C4), in
        canonical label form (so `l_CA` and `l_{CA}` are one node)."""
        defined = {canonical_label(l) for l in self.labels()}; edges: list[tuple[str, str]] = []
        for s in self.statements:
            l = getattr(s, "label", None)
            if not l: continue
            cl = canonical_label(l)
            for r in references(s):
                cr = canonical_label(r)
                if cr in defined and cr != cl and (cr, cl) not in edges: edges.append((cr, cl))
        return tuple(edges)

    def heads(self) -> dict[str, int]:
        h: dict[str, int] = {}
        for c in self.commands():
            h[c.head] = h.get(c.head, 0) + 1
            for n in nested_commands(c): h[n.head] = h.get(n.head, 0) + 1
        return h
