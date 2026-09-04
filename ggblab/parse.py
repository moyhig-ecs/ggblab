"""Typed constructor (鞭毛 of stage 1): `@ggb` / `%%ggb` surface text → Construction (C4).

Closed world: a command name that is not one of the 28 HEADS raises UnknownHead — the gate over the textbook fixture
(probes/stage1_closed_world.py) requires 0 of them and, as its positive control, must see them when a head is removed.
Pure functions only.
"""
from __future__ import annotations
import re
from .construction import (Arg, Command, Construction, Definition, Directive, FreeNumber, FreePoint, HEADS, Ident, Num,
                           Raw, Ref, Statement, Str, Tup)

class ParseError(ValueError):
    def __init__(self, msg: str, line: str):
        super().__init__(f"{msg}: {line!r}"); self.line = line

class UnknownHead(ParseError):
    def __init__(self, head: str, line: str):
        super().__init__(f"unknown command head {head!r} (closed world of {len(HEADS)} heads)", line); self.head = head

_LABEL = r"[A-Za-z_][A-Za-z0-9_'{}]*"
_NUM = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")
_HEADCALL = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*\((.*)\)\s*$", re.S)
_ASSIGN = re.compile(rf"^({_LABEL})\s*=\s*(.*)$", re.S)

def strip_comment(text: str) -> str:
    """Remove a trailing `# …` comment that is outside string quotes."""
    out, q = [], None
    for ch in text:
        if q:
            out.append(ch)
            if ch == q: q = None
        elif ch in '"\'': q = ch; out.append(ch)
        elif ch == "#": break
        else: out.append(ch)
    return "".join(out).strip()

def split_top(text: str) -> list[str]:
    """Split on top-level commas (respecting (), [], {} and quotes)."""
    parts, cur, depth, q = [], [], 0, None
    for ch in text:
        if q:
            cur.append(ch)
            if ch == q: q = None
            continue
        if ch in '"\'': q = ch; cur.append(ch); continue
        if ch in "([{": depth += 1
        elif ch in ")]}": depth -= 1
        if ch == "," and depth == 0: parts.append("".join(cur).strip()); cur = []
        else: cur.append(ch)
    tail = "".join(cur).strip()
    if tail or parts: parts.append(tail)
    return [p for p in parts if p != ""]

def parse_arg(text: str, heads: tuple[str, ...] = HEADS) -> Arg:
    t = text.strip()
    if re.fullmatch(r":[A-Za-z_][A-Za-z0-9_'{}]*", t): return Ref(t[1:])
    if _NUM.fullmatch(t): return Num(t)
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"': return Str(t[1:-1])
    if t.startswith("(") and t.endswith(")") and _balanced(t[1:-1]):
        return Tup(tuple(parse_arg(x, heads) for x in split_top(t[1:-1])))
    m = _HEADCALL.match(t)
    if m and m.group(1)[0].isupper() and _balanced(m.group(2)):
        if m.group(1) not in heads: raise UnknownHead(m.group(1), text)
        return Command(m.group(1), tuple(parse_arg(x, heads) for x in split_top(m.group(2))))   # nested (reported by the gate)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'{}]*", t): return Ident(t)
    return Raw(t)

def _balanced(s: str) -> bool:
    depth, q = 0, None
    for ch in s:
        if q:
            if ch == q: q = None
            continue
        if ch in '"\'': q = ch
        elif ch in "([{": depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0: return False
    return depth == 0 and q is None

def parse_statement(body: str, heads: tuple[str, ...] = HEADS) -> Statement:
    """One `@ggb` body (the text after `@ggb`, comment already stripped)."""
    b = body.strip()
    if not b: raise ParseError("empty statement", body)
    if b.startswith(":"): return Directive(tuple(b.split()))
    m = _ASSIGN.match(b)
    label, rhs = (m.group(1), m.group(2).strip()) if m else (None, b)
    hm = _HEADCALL.match(rhs)
    if hm and hm.group(1)[0].isupper() and _balanced(hm.group(2)):
        if hm.group(1) not in heads: raise UnknownHead(hm.group(1), body)
        return Command(hm.group(1), tuple(parse_arg(x, heads) for x in split_top(hm.group(2))), label)
    if rhs.startswith("(") and rhs.endswith(")") and _balanced(rhs[1:-1]) and label:
        return FreePoint(label, Tup(tuple(parse_arg(x, heads) for x in split_top(rhs[1:-1]))))
    if _NUM.fullmatch(rhs) and label: return FreeNumber(label, Num(rhs))
    if len(rhs) >= 2 and rhs[0] == '"' and rhs[-1] == '"': return Definition(label, rhs[1:-1], True)
    return Definition(label, rhs, False)

def ggb_lines(cell: str, dialect: str = "julia") -> list[str]:
    """Statement bodies of a cell. julia: lines `@ggb …`; python (`%%ggb` cell): every non-empty line after the magic."""
    out = []
    for ln in cell.splitlines():
        if dialect == "julia":
            m = re.match(r"^\s*@ggb\s+(.*)$", ln)
            if not m: continue
            body = strip_comment(m.group(1))
        else:
            if re.match(r"^\s*%%ggb", ln): continue
            body = strip_comment(ln)
        if body: out.append(body)
    return out

def parse_cell(cell: str, dialect: str = "julia", heads: tuple[str, ...] = HEADS) -> Construction:
    return Construction(tuple(parse_statement(b, heads) for b in ggb_lines(cell, dialect)))
