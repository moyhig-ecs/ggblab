#!/usr/bin/env python3
"""C3 instrument for the replay branch (INSTR v0.2 追記 3 / Step 8): rebuild the code graph at EVERY commit of `v2` and
read three predicates per step (R5: sets from predicates, R6: calibrated by a positive control):
  M1 monotone   nodes/edges are only ADDED between consecutive commits (no removal, no re-wiring)
  M2 interface  the frozen interfaces are invariant from first appearance: HEADS (28 command heads, construction.py) and
                the Verb kinds (host/base.py) — sizes and members
  M3 order      birth order of the replay follows the original development: every host/transport module is born no later
                than every construction/parse module (2026: transport 01-12 → Construction 01-21)
plus the spine (betweenness top-3 per commit), the anchor counts (GeoGebra API methods / Jupyter comm tokens / 28 heads), and
  M0 edits      the record INSTR v0.2 asks for: existing modules whose CONTENT changed at a step ("既存段階の編集" — a sign that
                the corrected origin was not yet sufficient; recorded, not failed)
Positive control: a synthetic next state that drops one import edge and one head must fail M1 and M2.
usage: python probes/stage_codegraph_v2.py [--branch v2] [--report probes/stage_codegraph_v2_report.json]"""
import argparse, ast, collections, hashlib, json, re, subprocess, sys
from pathlib import Path
import networkx as nx
HERE = Path(__file__).resolve().parent; REPO = HERE.parent
ap = argparse.ArgumentParser(); ap.add_argument("--branch", default="v2"); ap.add_argument("--report", default=str(HERE / "stage_codegraph_v2_report.json"))
A = ap.parse_args()
API = ["evalCommand","evalCommandGetLabels","getXML","setXML","evalXML","registerObjectUpdateListener","unregisterObjectUpdateListener","registerAddListener",
       "registerRemoveListener","registerUpdateListener","getValueString","getValue","getAllObjectNames","getObjectType","getLayer","getCaption","getBase64",
       "setBase64","deleteObject","newConstruction","undo","getCommandString","exists"]
JUP = ["comm_msg","control_handlers","comm_manager","Comm(","comm_id","ipykernel","IJulia","register_comm_target","comm_open","sendControlMessage","control_socket"]
SRC = re.compile(r"^(ggblab/.*\.py|probes/[^/]*\.py|probes/stage2/[^/]*\.(py|jl)|tests/.*\.py|examples/[^/]*\.ipynb)$")

def git(*a): return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout
commits = git("rev-list", "--reverse", A.branch).split()
def files_at(c): return [f for f in git("ls-tree", "-r", "--name-only", c).splitlines() if SRC.match(f)]
def show(c, f): return git("show", f"{c}:{f}")

def py_edges(path, text, known):
    out = set()
    try: tree = ast.parse(text)
    except SyntaxError: return out
    pkg = path.split("/")
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:   # relative
                base = pkg[:-1]; base = base[:len(base) - (n.level - 1)] if n.level > 1 else base
                mod = "/".join(base + (n.module.split(".") if n.module else []))
                cands = [mod + ".py", mod + "/__init__.py"]
            elif n.module and n.module.split(".")[0] == "ggblab":
                mod = "/".join(n.module.split(".")); cands = [mod + ".py", mod + "/__init__.py"]
            else: continue
            for cnd in cands:
                if cnd in known: out.add(cnd)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "ggblab":
                    mod = "/".join(a.name.split("."))
                    for cnd in (mod + ".py", mod + "/__init__.py"):
                        if cnd in known: out.add(cnd)
    return out

def nb_edges(text, known):
    out = set()
    try: nb = json.loads(text)
    except Exception: return out
    code = "\n".join("".join(c["source"]) for c in nb.get("cells", []) if c.get("cell_type") == "code")
    for m in re.finditer(r"^\s*(?:from\s+(ggblab(?:\.\w+)*)\s+import|import\s+(ggblab(?:\.\w+)*))", code, re.M):
        mod = "/".join((m.group(1) or m.group(2)).split("."))
        for cnd in (mod + ".py", mod + "/__init__.py"):
            if cnd in known: out.add(cnd)
    return out

def heads_of(text):
    m = re.search(r"CommandHead = Literal\[(.*?)\]", text, re.S)
    return sorted(re.findall(r'"([A-Za-z]+)"', m.group(1))) if m else None
def verbs_of(text):
    m = re.search(r"class Verb\(str, Enum\):(.*?)\n\n", text, re.S)
    return sorted(re.findall(r'^\s*([A-Z_]+)\s*=', m.group(1), re.M)) if m else None

LANE = lambda f: ("host" if f.startswith("ggblab/host/") else "construction" if f in ("ggblab/construction.py", "ggblab/parse.py")
                  else "package" if f.startswith("ggblab/") else "probe" if f.startswith("probes/") else "test" if f.startswith("tests/") else "example")
def build(c, override=None):
    fl = files_at(c); texts = {f: show(c, f) for f in fl}
    if override: texts = override(texts)
    known = set(texts); G = nx.DiGraph(); G.graph["hash"] = {f: hashlib.md5(t.encode()).hexdigest()[:8] for f, t in texts.items()}
    for f, t in texts.items():
        G.add_node(f, lane=LANE(f), loc=t.count("\n"), api=sum(len(re.findall(r"\b%s\b" % m, t)) for m in API),
                   jup=sum(t.count(x) for x in JUP), heads=(len(heads_of(t) or []) if f == "ggblab/construction.py" else 0))
        deps = nb_edges(t, known) if f.endswith(".ipynb") else py_edges(f, t, known)
        for d in deps:
            if d != f: G.add_edge(f, d, kind="import")
    iface = {"heads": heads_of(texts.get("ggblab/construction.py", "")), "verbs": verbs_of(texts.get("ggblab/host/base.py", ""))}
    return G, iface

steps, births, prev = [], {}, None
for i, c in enumerate(commits):
    G, iface = build(c)
    for f in G.nodes: births.setdefault(f, (i, c[:7]))
    U = G.to_undirected(); bc = nx.betweenness_centrality(U) if U.number_of_nodes() > 2 else {}
    spine = sorted(bc, key=bc.get, reverse=True)[:3]
    E = {(a, b) for a, b in G.edges}; N = set(G.nodes)
    st = {"i": i, "commit": c[:7], "subject": git("log", "-1", "--format=%s", c).strip()[:80], "nodes": len(N), "edges": len(E),
          "added_nodes": sorted(N - prev[0]) if prev else sorted(N), "removed_nodes": sorted(prev[0] - N) if prev else [],
          "added_edges": len(E - prev[1]) if prev else len(E), "removed_edges": sorted(prev[1] - E) if prev else [],
          "spine_top3": spine, "anchors": {"api": sum(d["api"] for _, d in G.nodes(data=True)), "jup": sum(d["jup"] for _, d in G.nodes(data=True))},
          "heads": (len(iface["heads"]) if iface["heads"] else None), "verbs": iface["verbs"]}
    st["M1"] = not st["removed_nodes"] and not st["removed_edges"]
    H = G.graph["hash"]; st["modified_nodes"] = sorted(f for f in N if prev and f in prev[3] and prev[3][f] != H[f])
    steps.append(st); prev = (N, E, iface, H)
# M2: interface invariance from first appearance
def invariant(key):
    seen = [ (s["commit"], build(commits[s["i"]])[1][key]) for s in steps ]
    vals = [v for _, v in seen if v is not None]
    return {"first": next((c for c, v in seen if v is not None), None), "n_states": len({tuple(v) for v in vals}), "size": (len(vals[-1]) if vals else None), "members": vals[-1] if vals else None}
M2 = {"heads": invariant("heads"), "verbs": invariant("verbs")}
M2["pass"] = M2["heads"]["n_states"] == 1 and M2["heads"]["size"] == 28 and M2["verbs"]["n_states"] == 1
# M3: host modules born no later than construction modules
host_b = [births[f][0] for f in births if LANE(f) == "host"]; cons_b = [births[f][0] for f in births if LANE(f) == "construction"]
M3 = {"host_birth_max": max(host_b) if host_b else None, "construction_birth_min": min(cons_b) if cons_b else None,
      "pass": bool(host_b and cons_b and max(host_b) <= min(cons_b))}
# positive control: synthetic next state = drop one import (parse.py no longer imports construction) and one head
def mutate(texts):
    t = dict(texts)
    if "ggblab/parse.py" in t: t["ggblab/parse.py"] = t["ggblab/parse.py"].replace("from .construction import", "from ._nowhere import")
    if "ggblab/construction.py" in t: t["ggblab/construction.py"] = t["ggblab/construction.py"].replace('"Locus", ', "")
    return t
Gm, ifm = build(commits[-1], mutate)
Em = {(a, b) for a, b in Gm.edges}; removed_m = sorted(prev[1] - Em)
ctrl = {"removed_edges": removed_m, "heads_after": len(ifm["heads"] or []), "M1_fails": bool(removed_m), "M2_fails": len(ifm["heads"] or []) != 28}
ctrl["pass"] = ctrl["M1_fails"] and ctrl["M2_fails"]
M1_all = all(s["M1"] for s in steps)
print(f"branch {A.branch}: {len(commits)} commits")
print(f"{'i':>2} {'commit':7} {'nodes':>5} {'edges':>5} {'+n':>3} {'-n':>3} {'+e':>3} {'-e':>3} {'mod':>3} heads verbs  spine top-3")
for s in steps:
    print(f"{s['i']:>2} {s['commit']:7} {s['nodes']:>5} {s['edges']:>5} {len(s['added_nodes']):>3} {len(s['removed_nodes']):>3} {s['added_edges']:>3} {len(s['removed_edges']):>3} {len(s['modified_nodes']):>3} "
          f"{str(s['heads'] or '-'):>5} {len(s['verbs']) if s['verbs'] else '-':>5}  {', '.join(p.replace('ggblab/','') for p in s['spine_top3'])}")
mods = [(s['commit'], s['modified_nodes']) for s in steps if s['modified_nodes']]
print(f"  M0 edits of existing modules (recorded): " + ("; ".join(f"{c}: {', '.join(m)}" for c, m in mods) if mods else "none"))
print(f"  {'⭕' if M1_all else '⛔'} M1 monotone (additions only) at every step" + ("" if M1_all else f"  removals at {[s['commit'] for s in steps if not s['M1']]}: {[s['removed_edges'] or s['removed_nodes'] for s in steps if not s['M1']]}"))
print(f"  {'⭕' if M2['pass'] else '⛔'} M2 interface invariant: HEADS {M2['heads']['size']} (states {M2['heads']['n_states']}, since {M2['heads']['first']}) / Verb {M2['verbs']['size']} {M2['verbs']['members']} (states {M2['verbs']['n_states']}, since {M2['verbs']['first']})")
print(f"  {'⭕' if M3['pass'] else '⛔'} M3 birth order: host modules born ≤ step {M3['host_birth_max']}, construction modules ≥ step {M3['construction_birth_min']}")
print(f"  {'⭕' if ctrl['pass'] else '⛔'} positive control: dropped import → removed edges {ctrl['removed_edges']}; dropped head → HEADS {ctrl['heads_after']}")
verdict = M1_all and M2["pass"] and M3["pass"] and ctrl["pass"]
print("⭕ C3 PASS" if verdict else "⛔ C3 FAIL")
rep = {"branch": A.branch, "commits": [c[:7] for c in commits], "steps": steps, "M2": M2, "M3": M3, "births": {f: b for f, b in sorted(births.items(), key=lambda kv: kv[1])},
       "positive_control": ctrl, "verdict": "PASS" if verdict else "FAIL"}
Path(A.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1)); print("report →", A.report)
