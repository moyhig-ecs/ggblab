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
import argparse, difflib, hashlib, json, re
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("--dir", default=str(Path(__file__).resolve().parent / "stage2" / "gate2")); A = ap.parse_args()
D = Path(A.dir); groups = json.load(open(D / "groups.json"))
cons = lambda x: (re.search(r"<construction[^>]*>.*?</construction>", x, re.S) or re.search(r"$", x)).group(0)
rows = []; all_ok = True
for g in groups:
    k = g["id"]; a, b = D / f"v1_g{k}.xml", D / f"v2_g{k}.xml"
    if g.get("has_dynamic") or not (a.exists() and b.exists()):
        rows.append({"group": k, "skipped": True}); continue
    ca, cb = cons(a.read_text()), cons(b.read_text())
    la, lb = [l.strip() for l in ca.splitlines()], [l.strip() for l in cb.splitlines()]
    diff = [d for d in difflib.unified_diff(la, lb, "v1", "v2", lineterm="", n=0)][2:]
    exp_only = all(d.startswith(("@@", "-<expression", "+<expression")) for d in diff)
    r = {"group": k, "lines": len(g["bodies"]), "classes": {c: g["classes"].count(c) for c in set(g["classes"])},
         "elements_v1": len(re.findall(r"<element ", ca)), "elements_v2": len(re.findall(r"<element ", cb)),
         "byte_equal": ca == cb, "md5_v1": hashlib.md5(ca.encode()).hexdigest()[:8], "md5_v2": hashlib.md5(cb.encode()).hexdigest()[:8],
         "diff_lines": len([d for d in diff if d[:1] in "+-"]), "diff_only_in_expression_text": bool(diff) and exp_only, "diff": diff}
    ok = r["byte_equal"] or (exp_only and "paren" in r["classes"] and r["elements_v1"] == r["elements_v2"])
    all_ok &= ok; r["pass"] = ok; rows.append(r)
    print(f"g{k}: {r['lines']} lines {r['classes']} | elements {r['elements_v1']}/{r['elements_v2']} | byte-equal {r['byte_equal']} "
          f"| md5 {r['md5_v1']}/{r['md5_v2']}" + ("" if r["byte_equal"] else f" | diff {r['diff_lines']} lines, only in <expression exp=…> text: {exp_only}"))
    for d in diff: print("     ", d[:160])
print(("⭕ GATE #2 PASS" if all_ok else "⛔ GATE #2 FAIL") + " — byte-equal where the command strings are byte-equal (exact / ws); paren-class lines keep the input's parenthesisation in exp=")
json.dump({"rows": rows, "verdict": "PASS" if all_ok else "FAIL"}, open(D / "gate2_report.json", "w"), indent=1)
