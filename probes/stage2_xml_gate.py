#!/usr/bin/env python3
"""Stage 2 gate #2 (browser, C5): the CURRENT route (v1 ggblab 1.8.1 labextension + comm, a plain JupyterLab) and the v2
route (stage-0 HTML host + mailbox, the test server) must leave the same construction in the applet.
Predicate per group: the `<construction>…</construction>` element of getXML is byte-equal (the rest of the XML carries
view/app state and the applet id, not the construction).  Inputs: probes/stage2/gate2/{v1,v2}_g<k>.xml written by
  examples/stage2_xml_gate_v2.ipynb          (v2: one fresh applet per group, `GeoGebra.command(*v2 strings)` → `xml()`)
  probes/stage2/gate2/stage2_xml_gate_v1.ipynb (v1: `GeoGebra().init()`, wait for the comm, `newConstruction` per group,
                                              `command(v1 string)` each → `function('getXML')`)
over the lesson-04 groups of the render gate (probes/stage2/gate2/groups.json: each route gets ITS OWN strings, so
ws / paren / num-class lines test semantic equality, exact-class lines test the transport).
usage: python probes/stage2_xml_gate.py [--dir probes/stage2/gate2]"""
import argparse, difflib, hashlib, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ggblab.construction import canonical_label
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*_(?:\{[^{}]*\}|[A-Za-z0-9]+)")
canon = lambda x: LABEL_RE.sub(lambda m: canonical_label(m.group(0)), x)   # teacher 09-07: v2 sends l_{CA} for l_CA
ap = argparse.ArgumentParser(); ap.add_argument("--dir", default=str(Path(__file__).resolve().parent / "stage2" / "gate2")); A = ap.parse_args()
D = Path(A.dir); groups = json.load(open(D / "groups.json"))
cons = lambda x: (re.search(r"<construction[^>]*>.*?</construction>", x, re.S) or re.search(r"$", x)).group(0)
rows = []; all_ok = True
by_bodies = {}                                    # v1 partners with the same command bodies (lesson 04 repeats two groups; TriangleCenter's
for g in groups: by_bodies.setdefault(tuple(g["bodies"]), []).append(g["id"])   # first call in a page fails lazily, so partners can differ by one element)
for g in groups:
    k = g["id"]; b = D / f"v2_g{k}.xml"
    if g.get("has_dynamic") or not b.exists():
        rows.append({"group": k, "skipped": True}); continue
    cb = cons(b.read_text()); best = None
    for j in by_bodies[tuple(g["bodies"])]:
        a = D / f"v1_g{j}.xml"
        if not a.exists(): continue
        ca = cons(a.read_text()); xa, xb = canon(ca), canon(cb)
        la, lb = [l.strip() for l in xa.splitlines()], [l.strip() for l in xb.splitlines()]
        diff = [d for d in difflib.unified_diff(la, lb, f"v1_g{j}", f"v2_g{k}", lineterm="", n=0)][2:]
        exp_only = bool(diff) and all(d.startswith(("@@", "-<expression", "+<expression")) for d in diff)
        r = {"group": k, "partner_v1": j, "lines": len(g["bodies"]), "classes": {c: g["classes"].count(c) for c in set(g["classes"])},
             "elements_v1": len(re.findall(r"<element ", ca)), "elements_v2": len(re.findall(r"<element ", cb)),
             "byte_equal": ca == cb, "equal_modulo_canonical_labels": xa == xb, "md5_v1": hashlib.md5(ca.encode()).hexdigest()[:8], "md5_v2": hashlib.md5(cb.encode()).hexdigest()[:8],
             "diff_lines_after_label_canon": len([d for d in diff if d[:1] in "+-"]), "diff_only_in_expression_text": exp_only, "diff": diff}
        r["pass"] = r["byte_equal"] or r["equal_modulo_canonical_labels"] or (exp_only and "paren" in r["classes"] and r["elements_v1"] == r["elements_v2"])
        if best is None or (r["pass"] and not best["pass"]) or (r["pass"] == best["pass"] and len(diff) < len(best["diff"])): best = r
    all_ok &= best["pass"]; rows.append(best); r = best
    print(f"g{k} vs v1_g{r['partner_v1']}: {r['lines']} lines {r['classes']} | elements {r['elements_v1']}/{r['elements_v2']} | byte-equal {r['byte_equal']} "
          f"| modulo labels {r['equal_modulo_canonical_labels']} | md5 {r['md5_v1']}/{r['md5_v2']}" + ("" if r["equal_modulo_canonical_labels"] else f" | diff after label canon {r['diff_lines_after_label_canon']} lines, only in <expression exp=…> text: {r['diff_only_in_expression_text']}") + f" | {'⭕' if r['pass'] else '⛔'}")
    for d in r["diff"]: print("     ", d[:160])
print(("⭕ GATE #2 PASS" if all_ok else "⛔ GATE #2 FAIL") + " — byte-equal (modulo canonical labels l_CA→l_{CA}) where the command strings agree; paren-class lines keep the input's parenthesisation in exp=")
json.dump({"rows": rows, "verdict": "PASS" if all_ok else "FAIL"}, open(D / "gate2_report.json", "w"), indent=1)
