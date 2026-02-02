import networkx as nx
import numpy as np
from scipy.optimize import linear_sum_assignment
import pprint
pp = pprint.PrettyPrinter(indent=2)
import sympy as sp
import logging
logger = logging.getLogger(__name__)

def normalize_label(name: str) -> str:
    if name is None:
        return ''
    return ''.join(ch for ch in name if ch.isalnum()).upper()

def node_feature(n, attrs=None):
    attrs = attrs or {}
    t = attrs.get('Type', '')
    label = attrs.get('Name', n) if attrs.get('Name', None) else n
    return (t, normalize_label(label))

def build_graph_from_tuples(nodes, edges):
    G = nx.DiGraph()
    for name, a in nodes:
        G.add_node(name, **(a or {}))
    for u, v in edges:
        G.add_edge(u, v)
    return G


def collapse_scc(G: nx.DiGraph, prefix='S'):
    """Collapse strongly connected components into super-nodes.

    Returns (G2, comp_map, members) where comp_map maps original node -> supernode,
    and members maps supernode -> list of original nodes.
    """
    comps = list(nx.strongly_connected_components(G))
    comp_map = {}
    members = {}
    G2 = nx.DiGraph()
    for i, comp in enumerate(comps):
        sid = f"{prefix}{i}"
        members[sid] = list(comp)
        # aggregate attributes conservatively
        attrs = {}
        types = []
        names = []
        vals = set()
        xs = []
        ys = []
        for n in comp:
            comp_map[n] = sid
            a = G.nodes.get(n, {})
            t = a.get('Type')
            if t:
                types.append(t)
            nm = a.get('Name') or n
            if nm:
                names.append(str(nm))
            v = a.get('Value')
            if v is not None:
                vals.add(str(v))
            x = a.get('x')
            y = a.get('y')
            if x is not None and y is not None:
                try:
                    xs.append(float(x))
                    ys.append(float(y))
                except Exception:
                    logger.exception("Failed to parse coordinates for node %s", n)
        if types:
            attrs['Type'] = '|'.join(sorted(set(types)))
        if names:
            attrs['Name'] = '|'.join(sorted(set(names)))
        if len(vals) == 1:
            attrs['Value'] = next(iter(vals))
        if xs and ys:
            attrs['x'] = sum(xs) / len(xs)
            attrs['y'] = sum(ys) / len(ys)
        attrs['members'] = members[sid]
        G2.add_node(sid, **attrs)

    # add edges between supernodes
    for u, v in G.edges():
        su = comp_map.get(u)
        sv = comp_map.get(v)
        if su is None or sv is None:
            continue
        if su != sv:
            G2.add_edge(su, sv)

    return G2, comp_map, members

def cost_between(node_a, node_b, Ga, Gb):
    fa = node_feature(node_a, Ga.nodes.get(node_a, {}))
    fb = node_feature(node_b, Gb.nodes.get(node_b, {}))
    # If Value attributes exist, try symbolic equivalence first
    va = Ga.nodes.get(node_a, {}).get('Value')
    vb = Gb.nodes.get(node_b, {}).get('Value')
    try:
        if va and vb:
            ea = sp.sympify(va)
            eb = sp.sympify(vb)
            diff = sp.simplify(ea - eb)
            if diff == 0:
                return 0.0
    except Exception:
        # fallback to numeric sampling via lambdify
        try:
            if va and vb:
                sa = sp.sympify(va)
                sb = sp.sympify(vb)
                vars = list(sa.free_symbols.union(sb.free_symbols))
                if vars:
                    f1 = sp.lambdify(vars, sa, 'numpy')
                    f2 = sp.lambdify(vars, sb, 'numpy')
                    pts = [0, 1, 2, 3]
                    for p in pts:
                        vals = [p for _ in vars]
                        try:
                            if float(f1(*vals)) != float(f2(*vals)):
                                break
                        except Exception:
                            logger.exception("Numeric sampling failed for symbolic comparison between %s and %s", va, vb)
                            break
                    else:
                        return 0.0
        except Exception:
            logger.exception("Fallback numeric sampling failed for symbolic comparison between %s and %s", va, vb)

    # coordinate distance check
    ax = Ga.nodes.get(node_a, {}).get('x')
    ay = Ga.nodes.get(node_a, {}).get('y')
    bx = Gb.nodes.get(node_b, {}).get('x')
    by = Gb.nodes.get(node_b, {}).get('y')
    if None not in (ax, ay, bx, by):
        try:
            d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            # scale distance to cost (threshold 0.1 -> cost 0)
            if d < 1e-6:
                return 0.0
            if d < 0.1:
                return 0.1
            return min(1.0, d)
        except Exception:
            pass

    if fa == fb:
        return 0.0
    if fa[0] and fa[0] == fb[0]:
        return 0.5
    return 1.0

def hungarian_similarity(G_ref: nx.DiGraph, G_sub: nx.DiGraph, insertion_cost=1.0, collapse_cycles=True):
    # Optionally collapse strongly-connected components (cycles)
    comp_report = None
    if collapse_cycles:
        G_ref_c, ref_map, ref_members = collapse_scc(G_ref, prefix='R')
        G_sub_c, sub_map, sub_members = collapse_scc(G_sub, prefix='S')
        comp_report = {'ref_map': ref_map, 'sub_map': sub_map, 'ref_members': ref_members, 'sub_members': sub_members}
        G_ref_use = G_ref_c
        G_sub_use = G_sub_c
    else:
        G_ref_use = G_ref
        G_sub_use = G_sub

    ref_nodes = list(G_ref_use.nodes)
    sub_nodes = list(G_sub_use.nodes)
    if len(ref_nodes) == 0 and len(sub_nodes) == 0:
        return 1.0, {}
    cost = np.zeros((len(ref_nodes), len(sub_nodes)))
    for i, a in enumerate(ref_nodes):
        for j, b in enumerate(sub_nodes):
            # compare using the chosen graph (possibly collapsed)
            cost[i, j] = cost_between(a, b, G_ref_use, G_sub_use)
    row_ind, col_ind = linear_sum_assignment(cost)
    total_node_cost = cost[row_ind, col_ind].sum()
    matched_ref = set(ref_nodes[i] for i in row_ind)
    matched_sub = set(sub_nodes[j] for j in col_ind)
    unmatched_ref = set(ref_nodes) - matched_ref
    unmatched_sub = set(sub_nodes) - matched_sub
    total_node_cost += insertion_cost * (len(unmatched_ref) + len(unmatched_sub))
    mapping = {ref_nodes[i]: sub_nodes[j] for i, j in zip(row_ind, col_ind)}
    edge_penalty = 0
    for u, v in G_ref.edges():
        if u in mapping and v in mapping:
            u2 = mapping[u]
            v2 = mapping[v]
            if not G_sub.has_edge(u2, v2):
                edge_penalty += 1
    inv_map = {v2: k for k, v2 in mapping.items()}
    for u, v in G_sub.edges():
        if u in inv_map and v in inv_map:
            u1 = inv_map[u]
            v1 = inv_map[v]
            if not G_ref.has_edge(u1, v1):
                edge_penalty += 1
    total_cost = total_node_cost + edge_penalty
    worst = insertion_cost * (len(ref_nodes) + len(sub_nodes)) + max(G_ref.number_of_edges(), G_sub.number_of_edges())
    similarity = 1.0 - min(1.0, total_cost / (worst if worst > 0 else 1))
    report = {
        'ref_nodes': ref_nodes,
        'sub_nodes': sub_nodes,
        'collapse_report': comp_report,
        'matched_pairs': list(zip([ref_nodes[i] for i in row_ind], [sub_nodes[j] for j in col_ind])),
        'unmatched_ref': list(unmatched_ref),
        'unmatched_sub': list(unmatched_sub),
        'node_cost': float(total_node_cost),
        'edge_penalty': int(edge_penalty),
        'total_cost': float(total_cost),
        'similarity': float(similarity),
    }
    return similarity, report

if __name__ == '__main__':
    # Synthetic example
    ref_nodes = [('A', {'Type':'Point'}), ('B', {'Type':'Point'}), ('C', {'Type':'Point'}), ('Seg', {'Type':'Segment'})]
    ref_edges = [('A','Seg'), ('B','Seg'), ('Seg','C')]
    G_ref = build_graph_from_tuples(ref_nodes, ref_edges)
    sub_nodes = [('P1', {'Type':'Point'}), ('P2', {'Type':'Point'}), ('Seg_sub', {'Type':'Segment'})]
    sub_edges = [('P1','Seg_sub'), ('P2','Seg_sub')]
    G_sub = build_graph_from_tuples(sub_nodes, sub_edges)
    sim, rpt = hungarian_similarity(G_ref, G_sub)
    print('Similarity:', sim)
    pp.pprint(rpt)
    # Try networkx GED if available
    try:
        ged = nx.graph_edit_distance(G_ref.to_undirected(), G_sub.to_undirected())
        print('graph_edit_distance (generator):', ged)
        # For small graphs, compute min
        if hasattr(ged, '__iter__'):
            ged_vals = list(ged)
            print('GED min value (approx):', min(ged_vals) if ged_vals else None)
    except Exception as e:
        print('networkx GED not available or failed:', e)
