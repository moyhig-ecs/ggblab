#!/usr/bin/env python3
"""Stage 2 gate #1 (headless, C5/R5/R6): the v2 typed constructor + `render` must reproduce, line by line, the command
strings the CURRENT route (v1 `@ggb` macro, run verbatim with a recording transport: probes/stage2/current_route_render.jl)
sends to the applet, over textbook-2026 L04–L13.  Classes per line (a predicate each, R5):
  exact     bytes equal                          ws        equal after deleting all whitespace
  quote     equal after also stripping the surrounding "…" (v2 stripped them itself after the first run: 55 lines → 0)
  paren     equal after also deleting parentheses (Julia's Expr printer writes `2π/5` as `(2π) / 5`; GeoGebra-equal, byte-different)
  num       equal after also canonicalising decimal literals (Julia prints 0.6260 as 0.626)
  label     equal after canonicalising GeoGebra labels (`l_CA` → `l_{CA}`) on both sides: a DELIBERATE deviation of v2
            (teacher 09-07: GeoGebra shows an unbraced multi-char subscript as one character, l_C A)
  NOTE the one surviving `quote` line (`G_{s} = "…"`): the CURRENT route keeps the quotes there because Julia parses the
  braces label as Expr(:curly) and falls through to string(ex) — a v1 defect (it would make a text object); v2 renders it bare.
  mismatch  none of the above                    dynamic   current route needs runtime values (UndefVarError) — excluded
  directive host words (:const/:api/…): the current route's API call is recorded, v2 renders None (adapter's job)
  error     current route raised something else  unparsed  v2 raised
Positive control (R6): reverse the argument order in v2's render → the exact/ws/quote classes must lose every
multi-argument command.  usage: python probes/stage2_render_equivalence.py [--fixture DIR] [--chapters 4-13] [--report P]"""
import argparse, collections, glob, json, re, subprocess, sys, tempfile, time
from pathlib import Path
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent))
from ggblab.parse import ggb_lines, parse_statement, ParseError
from ggblab.construction import Command, Definition, Directive, render, render_call, render_arg, Ref, Num, Tup, Str, Raw, canonical_label
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*_(?:\{[^{}]*\}|[A-Za-z0-9]+)")

ap = argparse.ArgumentParser()
ap.add_argument("--fixture", default="/Users/manabu/work/ggblab/textbook-2026"); ap.add_argument("--chapters", default="4-13")
ap.add_argument("--report", default=str(HERE / "stage2_render_equivalence_report.json")); ap.add_argument("--v1src", default="/Users/manabu/work/ggblab/julia/GeoGebra.jl/src")
A = ap.parse_args(); lo, hi = (int(x) for x in A.chapters.split("-"))
files = [f for ch in range(lo, hi + 1) for f in sorted(glob.glob(f"{A.fixture}/chapters/{ch:02d}/*.ipynb")) if "checkpoint" not in f]
rows = []
for f in files:
    nb = json.loads(Path(f).read_text())
    for ci, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code": continue
        for li, body in enumerate(ggb_lines("".join(c["source"]), "julia")):
            rows.append({"file": Path(f).name, "cell": ci, "line": li, "body": body})
print(f"fixture {A.fixture} chapters {A.chapters}: files={len(files)} @ggb lines={len(rows)}")

# ── current route (Julia, verbatim macro) ─────────────────────────────────────────────────────────
t0 = time.time()
with tempfile.TemporaryDirectory() as td:
    lp, op = Path(td) / "lines.json", Path(td) / "out.json"
    lp.write_text(json.dumps([r["body"] for r in rows], ensure_ascii=False))
    p = subprocess.run(["julia", "--startup-file=no", str(HERE / "stage2" / "current_route_render.jl"), str(lp), str(op), A.v1src], capture_output=True, text=True)
    if p.returncode != 0: print(p.stdout[-2000:], p.stderr[-3000:]); sys.exit(2)
    cur = json.loads(op.read_text())
print(f"current route: {cur['n']} lines rendered by {cur['macro_file']} ({time.time()-t0:.1f}s)")

# ── v2 (typed constructor + render) ───────────────────────────────────────────────────────────────
def v2_render(body, mutate=False):
    s = parse_statement(body)
    if isinstance(s, Directive): return None, "directive"
    if mutate and isinstance(s, Command) and len(s.args) >= 2:      # positive control: reverse argument order
        s = Command(s.head, tuple(reversed(s.args)), s.label)
    return render(s), s.kind

def classify(sent, v2):
    if v2 is None: return "directive"
    if not sent: return "nosend"
    if len(sent) == 1 and sent[0] == v2: return "exact"
    nows = lambda x: re.sub(r"\s+", "", x)
    if len(sent) == 1 and nows(sent[0]) == nows(v2): return "ws"
    unq = lambda x: re.sub(r'"([^"]*)"', r"\1", x)
    if len(sent) == 1 and nows(unq(sent[0])) == nows(unq(v2)): return "quote"
    nop = lambda x: re.sub(r"[()\s]", "", x)
    if len(sent) == 1 and nop(sent[0]) == nop(v2): return "paren"      # Julia's Expr printer re-parenthesises `2π/5` as `(2π) / 5`
    num = lambda x: re.sub(r"\d+\.\d+", lambda m: repr(float(m.group(0))), nop(x))
    if len(sent) == 1 and num(sent[0]) == num(v2): return "num"        # Julia prints the literal 0.6260 as 0.626
    lab = lambda x: LABEL_RE.sub(lambda m: canonical_label(m.group(0)), x)
    if len(sent) == 1 and lab(sent[0]) == lab(v2): return "label"      # v2 sends l_{CA} where the current route sends l_CA (teacher 09-07: GeoGebra displays l_CA as l_C A)
    if len(sent) == 1 and num(lab(sent[0])) == num(lab(v2)): return "label"
    return "mismatch"

def run(mutate=False):
    cls = collections.Counter(); detail = []
    for r, c in zip(rows, cur["rows"]):
        assert r["body"] == c["body"]
        try: v2, kind = v2_render(r["body"], mutate)
        except ParseError as e: cls["unparsed"] += 1; detail.append({**r, "class": "unparsed", "sent": c["sent"], "v2": None, "err": str(e)}); continue
        if c["status"] == "dynamic": k = "dynamic"
        elif c["status"] == "error": k = "error"
        else: k = classify(c["sent"], v2)
        cls[k] += 1; detail.append({**r, "kind": kind, "class": k, "sent": c["sent"], "v2": v2, "err": c["error"]})
    return cls, detail

cls, detail = run(False)
print("  classes:", dict(cls))
static = cls["exact"] + cls["ws"] + cls["quote"] + cls["paren"] + cls["num"] + cls["label"] + cls["mismatch"]
print(f"  static (comparable) lines = {static}; exact {cls['exact']} / ws {cls['ws']} / quote {cls['quote']} / paren {cls['paren']} / num {cls['num']} / label {cls['label']} / mismatch {cls['mismatch']}")
for k in ("mismatch", "label", "quote", "num", "paren", "ws", "error", "nosend", "dynamic"):
    ex = [d for d in detail if d["class"] == k][:4]
    for d in ex: print(f"    [{k}] {d['body']!r}\n         v1 sent {d['sent']}  | v2 {d['v2']!r}" + (f"  | {d['err']}" if d.get("err") else ""))
# directives: what does the current route do with each?
dirs = collections.Counter((d["body"].split()[0], tuple(d["sent"])) for d in detail if d["class"] == "directive")
print("  directives (word → current-route action):", {f"{k[0]}": list(k[1]) for k in dirs})
# positive control
cls_m, _ = run(True)
multi = sum(1 for d in detail if d["class"] in ("exact", "ws", "quote", "paren", "num", "label") and d.get("kind") == "command" and len(parse_statement(d["body"]).args) >= 2
            and len({render_arg(a) for a in parse_statement(d["body"]).args}) >= 2)
lost = (cls["exact"] + cls["ws"] + cls["quote"] + cls["paren"] + cls["num"] + cls["label"]) - (cls_m["exact"] + cls_m["ws"] + cls_m["quote"] + cls_m["paren"] + cls_m["num"] + cls_m["label"])
ok_ctrl = lost == multi and multi > 0
print(f"  {'⭕' if ok_ctrl else '⛔'} positive control: reversing v2 argument order loses {lost} lines (expected {multi} multi-arg commands)")
verdict = cls["mismatch"] == 0 and cls["unparsed"] == 0 and cls["error"] == 0 and ok_ctrl
print(("⭕ GATE PASS (every static line is GeoGebra-equal under the named normalisations)" if verdict else "⛔ GATE FAIL") + f"  — byte-different but GeoGebra-equal: ws {cls['ws']} / paren {cls['paren']} / num {cls['num']} / quote {cls['quote']} / label {cls['label']} (see report; XML-level equality is gate #2)")
rep = {"fixture": A.fixture, "chapters": A.chapters, "files": len(files), "lines": len(rows), "macro_file": cur["macro_file"], "classes": dict(cls),
       "positive_control": {"lost": lost, "expected": multi, "pass": ok_ctrl}, "verdict": "PASS" if verdict else "FAIL", "rows": detail}
Path(A.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1)); print("report →", A.report)
