import pprint

import networkx as nx

pp = pprint.PrettyPrinter(indent=2)
import logging

logger = logging.getLogger(__name__)

from ggblab_extra.graph_similarity import hungarian_similarity


def build_graph_from_tuples(nodes, edges):
    G = nx.DiGraph()
    for name, a in nodes:
        G.add_node(name, **(a or {}))
    for u, v in edges:
        G.add_edge(u, v)
    return G


if __name__ == "__main__":
    # Synthetic example
    ref_nodes = [
        ("A", {"Type": "Point"}),
        ("B", {"Type": "Point"}),
        ("C", {"Type": "Point"}),
        ("Seg", {"Type": "Segment"}),
    ]
    ref_edges = [("A", "Seg"), ("B", "Seg"), ("Seg", "C")]
    G_ref = build_graph_from_tuples(ref_nodes, ref_edges)
    sub_nodes = [
        ("P1", {"Type": "Point"}),
        ("P2", {"Type": "Point"}),
        ("Seg_sub", {"Type": "Segment"}),
    ]
    sub_edges = [("P1", "Seg_sub"), ("P2", "Seg_sub")]
    G_sub = build_graph_from_tuples(sub_nodes, sub_edges)
    sim, rpt = hungarian_similarity(G_ref, G_sub)
    print("Similarity:", sim)
    pp.pprint(rpt)
    # Try networkx GED if available
    try:
        ged = nx.graph_edit_distance(G_ref.to_undirected(), G_sub.to_undirected())
        print("graph_edit_distance (generator):", ged)
        # For small graphs, compute min
        if hasattr(ged, "__iter__"):
            ged_vals = list(ged)
            print("GED min value (approx):", min(ged_vals) if ged_vals else None)
    except Exception as e:
        print("networkx GED not available or failed:", e)
