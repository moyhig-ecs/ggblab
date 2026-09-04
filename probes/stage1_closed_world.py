#!/usr/bin/env python3
"""Stage 1 gate (C5/R5/R6): every `@ggb` line of textbook-2026 L04–L13 must fall into a head (Unknown = 0), every command
arity must sit inside its signature, and the observed head set must be exactly the 28.  Positive control (R6): remove one
head from the closed world and the gate must FAIL by seeing UnknownHead for exactly that head's lines.
usage: python probes/stage1_closed_world.py [--fixture DIR] [--chapters 4-13] [--report PATH]"""
import argparse, collections, glob, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ggblab.construction import HEADS, Command, arity_ok, nested_commands, signature
from ggblab.parse import UnknownHead, ParseError, ggb_lines, parse_statement

ap = argparse.ArgumentParser()
ap.add_argument("--fixture", default="/Users/manabu/work/ggblab/textbook-2026")
ap.add_argument("--chapters", default="4-13"); ap.add_argument("--report", default=None); ap.add_argument("--control-head", default="Locus")
A = ap.parse_args(); lo, hi = (int(x) for x in A.chapters.split("-"))
files = [f for ch in range(lo, hi + 1) for f in sorted(glob.glob(f"{A.fixture}/chapters/{ch:02d}/*.ipynb")) if "checkpoint" not in f]

def run(heads):
    st = {"lines": 0, "kinds": collections.Counter(), "heads": collections.Counter(), "unknown": [], "errors": [], "arity_bad": [],
          "nested": [], "arity_obs": collections.defaultdict(lambda: [10**9, 0])}
    for f in files:
        nb = json.loads(Path(f).read_text())
        for c in nb["cells"]:
            if c["cell_type"] != "code": continue
            for body in ggb_lines("".join(c["source"]), "julia"):
                st["lines"] += 1
                try: s = parse_statement(body, heads)
                except UnknownHead as e: st["unknown"].append((e.head, body)); continue
                except ParseError as e: st["errors"].append(str(e)); continue
                st["kinds"][s.kind] += 1
                if isinstance(s, Command):
                    for cmd in (s, *nested_commands(s)):
                        st["heads"][cmd.head] += 1; n = len(cmd.args); o = st["arity_obs"][cmd.head]; o[0] = min(o[0], n); o[1] = max(o[1], n)
                        if not arity_ok(cmd): st["arity_bad"].append((cmd.head, n, body))
                    if nested_commands(s): st["nested"].append(body)
    return st

t0 = time.time(); st = run(HEADS)
observed = set(st["heads"]); expected = set(HEADS)
ok_unknown = not st["unknown"]; ok_err = not st["errors"]; ok_arity = not st["arity_bad"]; ok_set = observed == expected
print(f"fixture {A.fixture} chapters {A.chapters}: files={len(files)} @ggb lines={st['lines']} ({time.time()-t0:.1f}s)")
print(f"  kinds: {dict(st['kinds'])}")
print(f"  heads: {len(observed)} observed / {len(expected)} closed world; occurrences={sum(st['heads'].values())}")
print(f"  {'⭕' if ok_unknown else '⛔'} Unknown = {len(st['unknown'])}" + (f"  {st['unknown'][:5]}" if st["unknown"] else ""))
print(f"  {'⭕' if ok_err else '⛔'} parse errors = {len(st['errors'])}" + (f"  {st['errors'][:3]}" if st["errors"] else ""))
print(f"  {'⭕' if ok_arity else '⛔'} arity violations = {len(st['arity_bad'])}" + (f"  {st['arity_bad'][:5]}" if st["arity_bad"] else ""))
print(f"  {'⭕' if ok_set else '⛔'} observed head set == HEADS" + ("" if ok_set else f"  missing={sorted(expected-observed)} extra={sorted(observed-expected)}"))
print(f"  ⚠ nested command lines = {len(st['nested'])}  {st['nested'][:3]}")
# positive control: drop one head
ctrl = tuple(h for h in HEADS if h != A.control_head); st2 = run(ctrl)
n_ctrl = sum(1 for h, _ in st2["unknown"] if h == A.control_head); exp_ctrl = st["heads"][A.control_head]
ok_ctrl = n_ctrl == exp_ctrl and n_ctrl > 0 and all(h == A.control_head for h, _ in st2["unknown"])
print(f"  {'⭕' if ok_ctrl else '⛔'} positive control: HEADS − {A.control_head} → Unknown = {n_ctrl} (expected {exp_ctrl})")
verdict = ok_unknown and ok_err and ok_arity and ok_set and ok_ctrl
print(("⭕ GATE PASS" if verdict else "⛔ GATE FAIL"))
rep = {"fixture": A.fixture, "chapters": A.chapters, "files": len(files), "lines": st["lines"], "kinds": dict(st["kinds"]),
       "heads": dict(st["heads"].most_common()), "arity_observed": {h: v for h, v in st["arity_obs"].items()},
       "signatures": {h: [signature(h).min_args, signature(h).max_args] for h in HEADS},
       "unknown": st["unknown"], "errors": st["errors"], "arity_bad": st["arity_bad"], "nested": st["nested"],
       "positive_control": {"removed": A.control_head, "unknown_seen": n_ctrl, "expected": exp_ctrl, "pass": ok_ctrl}, "verdict": "PASS" if verdict else "FAIL"}
if A.report: Path(A.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1)); print(f"report -> {A.report}")
sys.exit(0 if verdict else 1)
