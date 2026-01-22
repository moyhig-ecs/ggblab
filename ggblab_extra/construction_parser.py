"""Construction parser compatibility implementation.

This module provides a backward-compatible construction parser implementation
kept in ``ggblab_extra`` for callers that have not migrated to the canonical
parser in :mod:`ggblab.parser`.

Notes:
        - Tokenization: the canonical tokenizer lives in :mod:`ggblab.parser` and
            may be exposed either as a top-level function ``tokenize_with_commas``
            or as a method of the lightweight ``ggb_parser`` wrapper. To support
            both shapes this module constructs a local ``_ggb_parser`` and exposes
            a module-level ``tokenize_with_commas`` that delegates to the
            available implementation.
        - Deprecations: ``ConstructionTreeParser.initialize_dataframe`` and
            ``ConstructionTreeParser.write_parquet`` are deprecated and delegate
            to ``ConstructionIO`` in ``ggblab_extra`` when available.
"""

import re
import json
import polars as pl
import networkx as nx
from itertools import combinations, chain
from ggblab.persistent_counter import PersistentCounter
from ggblab.utils import flatten
from ggblab.parser import ggb_parser

# Create a module-level parser instance for tokenization compatibility
_ggb_parser = ggb_parser()


def build_graph_from_df(df, col: str = "DependsOn", reduce_transitive: bool = False) -> nx.DiGraph:
    """Reconstruct a NetworkX DiGraph from a DataFrame's dependency column.

    Args:
        df: Polars DataFrame (or any object with indexable columns) containing
            at least `Name` and the dependency column `col`.
        col: Column name that holds dependency lists (list[str]) or JSON strings.

    Returns:
        NetworkX DiGraph where edges point from dependency -> dependent.

    Behavior: best-effort decoding of JSON strings; missing names are added
    as nodes. Does not raise on malformed entries — they are skipped.
    """
    G = nx.DiGraph()
    try:
        names = df["Name"].to_list()
    except Exception:
        # fallback for dict-like or pandas
        names = list(df["Name"])

    G.add_nodes_from(names)

    # obtain raw dependency column values
    if col not in df.columns:
        return G

    try:
        raw = df[col].to_list()
    except Exception:
        raw = list(df[col])

    for name, v in zip(names, raw):
        if v is None:
            continue
        deps = v
        if isinstance(v, str):
            try:
                deps = json.loads(v)
            except Exception:
                # treat as a single-name dependency string
                deps = [v]
        if not isinstance(deps, (list, tuple)):
            deps = [deps]
        for d in deps:
            if d is None:
                continue
            try:
                G.add_node(d)
                G.add_edge(d, name)
            except Exception:
                # ignore malformed dependency entries
                continue

    # Optionally reduce transitive edges to obtain a minimal parent set
    if reduce_transitive:
        try:
            # Prefer NetworkX transitive_reduction for DAGs when available
            if nx.is_directed_acyclic_graph(G):
                try:
                    from networkx.algorithms.dag import transitive_reduction

                    G = transitive_reduction(G)
                except Exception:
                    # Fallback: remove edges (u,v) if there exists an alternate path u->...->v
                    to_remove = set()
                    for u, v in list(G.edges()):
                        # if there's a path of length >1 from u to v, the direct edge is transitive
                        try:
                            for path in nx.all_simple_paths(G, u, v):
                                if len(path) > 2:
                                    to_remove.add((u, v))
                                    break
                        except Exception:
                            # if path enumeration fails, skip
                            pass
                    G.remove_edges_from(to_remove)
            else:
                # If not a DAG, attempt conservative reduction by checking alternate paths
                to_remove = set()
                for u, v in list(G.edges()):
                    try:
                        for path in nx.all_simple_paths(G, u, v):
                            if len(path) > 2:
                                to_remove.add((u, v))
                                break
                    except Exception:
                        pass
                G.remove_edges_from(to_remove)
        except Exception:
            # best-effort: if reduction fails, return original graph
            pass

        # If reduction above did not remove edges (or graph wasn't reducible by paths),
        # attempt a reduction using the per-row transitive ancestor lists when
        # available. This handles the common case where `DependsOn` lists contain
        # transitive ancestors but inter-dependency edges are not present in G.
        try:
            # build ancestor map from the dataframe column if present
            anc_map = {}
            try:
                raw_col = df[col].to_list()
            except Exception:
                raw_col = list(df[col])

            for name, v in zip(names, raw_col):
                if v is None:
                    anc_map[name] = set()
                    continue
                if isinstance(v, str):
                    try:
                        deps = json.loads(v)
                    except Exception:
                        deps = [v]
                else:
                    deps = v
                if not isinstance(deps, (list, tuple)):
                    deps = [deps]
                anc_map[name] = set(d for d in deps if d is not None)

            # compute minimal parents per node: remove any d if it is an ancestor
            # of some other declared dependency in the same row
            minimal_map = {}
            for name, deps in anc_map.items():
                minimal = set()
                for d in deps:
                    # if d is an ancestor of any other dep in this row, skip it
                    is_transitive = False
                    for other in deps:
                        if other == d:
                            continue
                        # if d appears in other's ancestor list, d is transitive
                        if d in anc_map.get(other, set()):
                            is_transitive = True
                            break
                    if not is_transitive:
                        minimal.add(d)
                minimal_map[name] = minimal

            # rebuild graph from minimal_map
            G_min = nx.DiGraph()
            G_min.add_nodes_from(names)
            for name, deps in minimal_map.items():
                for d in deps:
                    try:
                        G_min.add_node(d)
                        G_min.add_edge(d, name)
                    except Exception:
                        continue

            # use reduced graph if it has fewer edges
            if G_min.number_of_edges() < G.number_of_edges():
                G = G_min
        except Exception:
            pass

    return G


def tokenize_with_commas(cmd_string, extract_commands=False):
    return _ggb_parser.tokenize_with_commas(cmd_string, extract_commands=extract_commands)


# Tokenization is provided by the core package `ggblab.parser`.
# We import `tokenize_with_commas` directly above and use it in-place.


class ConstructionTreeParser:
    """Dependency graph parser for GeoGebra constructions.
    
    Analyzes object relationships in GeoGebra constructions by building
    directed graphs using NetworkX. Provides two graph representations:
    
    - G (full dependency graph): Complete construction dependencies
    - G2 (simplified subgraph): Minimal construction sequences (DEPRECATED)
    
    The parse() method builds the forward/backward dependency graph (G).
    The parse_subgraph() method attempts minimal extraction but has critical
    performance limitations (see method docstring and ARCHITECTURE.md).
    
    Command learning:
    - Automatically extracts and caches GeoGebra commands from construction protocols
    - Persists command names to a shelve database for cross-project learning
    - Supports enable/disable of persistence via cache_enabled flag
    
    Attributes:
        df (polars.DataFrame): Construction protocol dataframe
        G (nx.DiGraph): Full dependency graph
        G2 (nx.DiGraph): Simplified subgraph (from parse_subgraph)
        roots (list): Objects with no dependencies (in-degree = 0)
        leaves (list): Terminal objects (out-degree = 0)
        rd (dict): Reverse mapping from object name to DataFrame row number
        ft (dict): Tokenized function definitions, flattened
        command_cache (shelve.DbfilenameShelf): Persistent command database
        cache_enabled (bool): Enable/disable automatic persistence
    
    Example:
        >>> parser = ggb_parser()
        >>> parser.df = construction_dataframe
        >>> parser.parse()
        >>> print(parser.roots)  # Independent objects
        >>> print(parser.leaves)  # Terminal constructions
        >>> commands = parser.get_known_commands()  # Retrieved cached commands
    
    See:
        docs/architecture.md § Dependency Parser Architecture
    """
    
    pl.Config.set_tbl_rows(-1)
    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral"]

    def __init__(self, df=None, cache_path=None, cache_enabled=True):
        """Initialize the parser with optional construction dataframe and command caching.

        Args:
            df (polars.DataFrame, optional): Construction protocol dataframe to parse.
            cache_path (str, optional): Path to shelve database for command persistence.
                                       Defaults to '.ggblab_command_cache' in current directory.
            cache_enabled (bool): Enable automatic persistence of discovered commands.
                                 Default: True
        """
        # store dataframe if provided; callers can also call `initialize_dataframe` later
        self.df = df

        cache_path = cache_path or '.ggblab_command_cache'
        self.command_cache = PersistentCounter(cache_path=cache_path, enabled=cache_enabled)

    def parse(self):
        """Build the full dependency graph (G) from construction protocol.
        
        Analyzes the construction dataframe (self.df) and builds:
        - Forward dependencies: Object A depends on B (B → A edge)
        - Backward dependencies: Object A is used by B (A → B edge)
        
        The graph nodes are GeoGebra object names; edges represent dependencies.
        
        Attributes set:
            - self.G: NetworkX DiGraph of dependencies
            - self.roots: Objects with no dependencies (starting points)
            - self.leaves: Objects with no dependents (endpoints)
            - self.rd: Reverse dict (name → DataFrame row index)
            - self.ft: Tokenized function calls for each object
        
        Also extracts and persists command names if caching is enabled.
        
        Example:
            >>> parser.df = polars.DataFrame(construction_protocol)
            >>> parser.parse()
            >>> print(list(parser.G.edges()))  # [(A, B), (B, C), ...]
        """
        # reverse dict from name to row number of dataframe
        self.rd = {v: k for k, v in enumerate(self.df["Name"])}

        # tokenized function, flattened (delegate to external tokenizer)
        self.ft = {n: list([e for e in flatten(tokenize_with_commas(c)) if e != ','])
             for n, c in self.df.filter(pl.col("Type").is_in(self.SHAPES)).select(["Name", "Command"]).iter_rows()}

        for o in list(self.rd.keys()):
            for n in ['xAxis', 'yAxis', 'zAxis']:
                if n in self.ft.get(o, []):
                    # print(f"found {n} dependency in {o}")
                    self.rd[n] = None
                    self.ft[n] = []

        # Extract and cache command names from all commands in the dataframe
        for command_str in self.df["Command"]:
            if command_str:
                result = tokenize_with_commas(command_str, extract_commands=True)
                if 'commands' in result:
                    self.command_cache.increment(result['commands'])

        # graph in forward/backward dependency
        # self.graph  = {k: self.ffd(k) for k in self.df.filter(pl.col("Type") != "text")["Name"]}
        # self.rgraph = {k: self.fbd(k) for k in self.ft}

        self.G = nx.DiGraph()
        self.G.clear()

        for n in self.ft:
            for o in self.ft[n]:
                if o in self.rd:
                    # print(f"Adding edge from {o} to {n}")
                    self.G.add_edge(o, n)
            for o in self.fbd(n):
                if n in self.ft.get(o, []):
                    # print(f"Adding edge from {n} to {o}")
                    self.G.add_edge(n, o)

        self.roots = [v for v, d in self.G.in_degree() if d == 0]
        self.leaves = [v for v, d in self.G.out_degree() if d == 0]
        
        # If a DataFrame is present, ensure `DependsOn` is a list-type column.
        # If the column exists as JSON strings, decode; otherwise compute
        # transitively from the graph. Best-effort: do not fail parse() on errors.
        try:
            if hasattr(self, 'df') and self.df is not None:
                if "DependsOn" in self.df.columns:
                    raw_col = self.df["DependsOn"].to_list()
                    converted = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted.append(json.loads(v))
                            except Exception:
                                converted.append(sorted(nx.ancestors(self.G, n)) if n in self.G else [])
                        elif v is None:
                            converted.append(sorted(nx.ancestors(self.G, n)) if n in self.G else [])
                        else:
                            converted.append(v)
                else:
                    converted = [sorted(nx.ancestors(self.G, n)) if n in self.G else [] for n in self.df["Name"]]

                # attach or replace DependsOn as a polars List(Utf8) column
                self.df = self.df.with_columns(pl.Series("DependsOn", converted).cast(pl.List(pl.Utf8)))
        except Exception:
            pass

        return self.G
    
    def parse_subgraph(self):
        """
        Extract a simplified dependency subgraph (G2) from the full graph (G).

        This method implements a forward-search heuristic that attempts to find
        compact, human-interpretable parent sets for nodes. It starts from
        independent root objects and explores small combinations of active
        objects (practically singletons and pairs) to determine downstream
        objects that appear to depend uniquely on those combinations.

        Notes:
        - The algorithm is intentionally heuristic and prioritizes readability
          over theoretical minimality. Results may differ from strict
          transitive-reduction methods.
        - Performance is combinatorial in the number of active roots; avoid
          using this on constructions with many independent roots.

        Returns:
            The constructed `G2` (assigned to `self.G2`).
        """
        self.G2 = nx.DiGraph()
        self.G2.clear()

        explored = set()
        frontier = {n for n in self.roots if n in self.ft}

        while frontier:
            # Build all candidate active-sets from the current frontier
            candidate_active_sets = [explored | set(combo)
                                     for combo in chain.from_iterable(combinations(frontier, r)
                                                                     for r in range(1, len(frontier) + 1))]

            collected_matches = set()

            for active_set in candidate_active_sets:
                # neighbors_of_active: union of neighbors of each node in active_set
                neighbor_sets = [set(self.G.neighbors(node)) for node in active_set]
                potential_targets = set().union(*neighbor_sets) if neighbor_sets else set()

                matched_targets = set()
                for target in potential_targets:
                    # Build a map of predecessor -> descendants for this target
                    pred_desc_map = {pred: nx.descendants(self.G, pred) for pred in self.G.predecessors(target)}

                    # If some predecessor's descendants indicate unique reachability
                    for pred in sorted(pred_desc_map.keys(), key=lambda e: len(pred_desc_map[e]), reverse=True):
                        if len(pred_desc_map[pred]) and not nx.ancestors(self.G, target) - (active_set | {pred}):
                            matched_targets.add(target)
                            break

                # For each newly matched target, add edges from the newly-activated parents
                for target in matched_targets - active_set - frontier:
                    new_parents = active_set - explored
                    if len(new_parents) == 1:
                        parent = next(iter(new_parents))
                        self.G2.add_edge(parent, target)
                    elif len(new_parents) == 2:
                        p1, p2 = tuple(new_parents)
                        if not (p1 in self.G2 and target in self.G2.neighbors(p1)) and not (p2 in self.G2 and target in self.G2.neighbors(p2)):
                            self.G2.add_edge(p1, target)
                            self.G2.add_edge(p2, target)
                    else:
                        # skip higher-arity parent sets in this heuristic
                        pass

                collected_matches |= matched_targets

            # advance frontier: mark current frontier as explored and set new frontier
            explored |= frontier
            frontier = collected_matches - explored

        # If a DataFrame is present, ensure `DependsOn_minimal` is a list-type column.
        # If the column exists as JSON strings, decode; otherwise compute using
        # direct predecessors from G2 (fallback to G). Best-effort: do not fail.
        try:
            if hasattr(self, 'df') and self.df is not None:
                if "DependsOn_minimal" in self.df.columns:
                    raw_col = self.df["DependsOn_minimal"].to_list()
                    converted_min = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted_min.append(json.loads(v))
                            except Exception:
                                if hasattr(self, 'G2') and n in self.G2:
                                    converted_min.append(sorted(list(self.G2.predecessors(n))))
                                elif hasattr(self, 'G') and n in self.G:
                                    converted_min.append(sorted(list(self.G.predecessors(n))))
                                else:
                                    converted_min.append([])
                        elif v is None:
                            if hasattr(self, 'G2') and n in self.G2:
                                converted_min.append(sorted(list(self.G2.predecessors(n))))
                            elif hasattr(self, 'G') and n in self.G:
                                converted_min.append(sorted(list(self.G.predecessors(n))))
                            else:
                                converted_min.append([])
                        else:
                            converted_min.append(v)
                else:
                    converted_min = []
                    for n in self.df["Name"]:
                        if hasattr(self, 'G2') and n in self.G2:
                            converted_min.append(sorted(list(self.G2.predecessors(n))))
                        elif hasattr(self, 'G') and n in self.G:
                            converted_min.append(sorted(list(self.G.predecessors(n))))
                        else:
                            converted_min.append([])

                self.df = self.df.with_columns(pl.Series("DependsOn_minimal", converted_min).cast(pl.List(pl.Utf8)))
        except Exception:
            pass

        return self.G2

    # Note: the legacy implementation below is preserved for reproducibility
    # and because its heuristic has a 'human-like' behaviour valued by some
    # users. Prefer `parse_subgraph` for the cleaned/refactored variant.
    def parse_subgraph_legacy(self):
        """
        Legacy implementation of `parse_subgraph` kept for compatibility.

        This method preserves the original forward-search heuristic and
        variable naming to allow comparison and fallback when the newer,
        refactored `parse_subgraph` behavior is not desired.

        It intentionally retains the original control flow and (now-removed)
        debug-oriented prints to keep behavior identical to earlier releases.
        Use this method when deterministic reproduction of legacy outputs
        is required.
        """

        self.G2 = nx.DiGraph()
        self.G2.clear()

        _nodes0 = set()
        _nodes1 = {n for n in self.roots if n in self.ft}  # set(['C', 'A'])

        while _nodes1:
            _paths = []
            for __p in (list(chain.from_iterable(combinations(_nodes1, r)
                        for r in range(1, len(_nodes1) + 1)))):
                _paths.append(_nodes0 | set(__p))

            for _nodes2 in _paths:
                _nodes3 = set()
                for n1 in _nodes2:
                    _n = [set(self.G.neighbors(__n)) for __n in _nodes2]

                    for n0 in set().union(*_n):
                        d = {n: nx.descendants(self.G, n) for n in self.G.neighbors(n0)}
                        for n1 in sorted(d.keys(), key=lambda e: len(d[e]), reverse=True):
                            if len(d[n1]) and not nx.ancestors(self.G, n0) - (_nodes2 | {n1}):
                                _nodes3 |= {n0}

                for n in _nodes3 - _nodes2 - _nodes1:
                    match len(_nodes2 - _nodes0):
                        case 1:
                            o, = tuple(_nodes2 - _nodes0)
                            # legacy: originally printed debug info here
                            self.G2.add_edge(o, n)
                        case 2:
                            o1, o2, = tuple(_nodes2 - _nodes0)
                            if o1 in self.G2 and n in self.G2.neighbors(o1):
                                pass
                            elif o2 in self.G2 and n in self.G2.neighbors(o2):
                                pass
                            else:
                                # legacy: originally printed debug info here
                                self.G2.add_edge(o1, n)
                                self.G2.add_edge(o2, n)
                        case _:
                            pass

            _nodes0 |= _nodes1
            _nodes1 = _nodes3 - _nodes2 - _nodes1

        # Preserve original post-processing: attach DependsOn_minimal similar to
        # the refactored version to keep DataFrame outputs compatible.
        try:
            if hasattr(self, 'df') and self.df is not None:
                if "DependsOn_minimal" in self.df.columns:
                    raw_col = self.df["DependsOn_minimal"].to_list()
                    converted_min = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted_min.append(json.loads(v))
                            except Exception:
                                if hasattr(self, 'G2') and n in self.G2:
                                    converted_min.append(sorted(list(self.G2.predecessors(n))))
                                elif hasattr(self, 'G') and n in self.G:
                                    converted_min.append(sorted(list(self.G.predecessors(n))))
                                else:
                                    converted_min.append([])
                        elif v is None:
                            if hasattr(self, 'G2') and n in self.G2:
                                converted_min.append(sorted(list(self.G2.predecessors(n))))
                            elif hasattr(self, 'G') and n in self.G:
                                converted_min.append(sorted(list(self.G.predecessors(n))))
                            else:
                                converted_min.append([])
                        else:
                            converted_min.append(v)
                else:
                    converted_min = []
                    for n in self.df["Name"]:
                        if hasattr(self, 'G2') and n in self.G2:
                            converted_min.append(sorted(list(self.G2.predecessors(n))))
                        elif hasattr(self, 'G') and n in self.G:
                            converted_min.append(sorted(list(self.G.predecessors(n))))
                        else:
                            converted_min.append([])

                self.df = self.df.with_columns(pl.Series("DependsOn_minimal", converted_min).cast(pl.List(pl.Utf8)))
        except Exception:
            pass

        return self.G2

    # def parse_subgraph_improved(self):
    #     """
    #     Identify minimal construction sequences by analyzing the dependency graph.
    #     Uses a topological sort + pruning approach instead of exhaustive path enumeration.
    #     """
    #     self.G2 = nx.DiGraph()
        
    #     # Identify which nodes are essential (no alternative path)
    #     for node in self.G.nodes():
    #         direct_parents = list(self.G.predecessors(node))
    #         if not direct_parents:
    #             continue
                
    #         # Check if all direct parents are needed
    #         # A parent is needed if removing it disconnects node from any root
    #         parents_to_keep = []
    #         for parent in direct_parents:
    #             # Check if there's an alternative path without this parent
    #             G_without = self.G.copy()
    #             G_without.remove_edge(parent, node)
    #             has_alternative = nx.has_path(G_without, parent, node)
                
    #             if not has_alternative:
    #                 parents_to_keep.append(parent)
            
    #         # Add edges for essential parents
    #         for parent in parents_to_keep:
    #             self.G2.add_edge(parent, node)

    def ffd(self, k, recursive=True):
        """Return forward-facing dependencies for node `k`."""
        if recursive:
            def _ffd(k):
                if k in self.ft:
                    # regular polygon contain not much dependency (includes new vertices and auxiliary edges)
                    # return [[e, _ffd(e)] for e in ft if k in (ft[e] + find_returns(k)[1:])]
                    return ([[e, _ffd(e)] for e in self.ft if k in self.ft[e]]
                        + [[e, _ffd(e)] for e in self.find_returns(k)[1:]])
                else:
                    return []

            return set(flatten(_ffd(k)))
        else:
            return {e for e in self.ft if k in self.ft[e]}

    def fbd(self, k, recursive=True):
        """Return backward-facing dependencies for node `k`."""
        if recursive:
            def _fbd(k):
                if k in self.ft:
                    return [[e, _fbd(e)] for e in self.ft[k] if e in self.ft] + [self.vertex_on_regular_polygon(k)]
                else:
                    return []

            return set(flatten(_fbd(k))) - {k}
        else:
            return {e for e in self.ft[k] if e in self.ft}

    def initialize_dataframe(self, df=None, file=None):
        """Initialize the parser from `df` or delegate to ConstructionIO when given a file."""
        import warnings
        import asyncio
        import ggblab.construction_io as _cio

        warnings.warn(
            "ConstructionTreeParser.initialize_dataframe is deprecated; use ggblab.construction_io.ConstructionIO.initialize_dataframe",
            DeprecationWarning,
            stacklevel=2,
        )

        # If a DataFrame is already provided, keep previous behavior (no async call).
        if df is not None:
            self.df = df
            return self

        # Delegate to the canonical ConstructionIO initializer for file/parquet paths.
        if file is not None:
            # Import real implementation class from ggblab.construction_io and call its async initializer
            Impl, _ = _cio._import_impl()
            norm_df = asyncio.run(Impl.initialize_dataframe(None, parquet_file=file, file=file))
            self.df = norm_df
            return self

        raise ValueError("Either df or file must be provided.")

    def write_parquet(self, file=None):
        """Write the parser's DataFrame by delegating to ConstructionIO.save_dataframe."""
        import warnings
        import asyncio
        import ggblab.construction_io as _cio

        warnings.warn(
            "ConstructionTreeParser.write_parquet is deprecated; use ggblab.construction_io.ConstructionIO.save_dataframe",
            DeprecationWarning,
            stacklevel=2,
        )

        # Delegate to canonical implementation
        Impl, _ = _cio._import_impl()
        # call sync wrapper if needed
        return Impl.save_dataframe(self.df, ggb=None, fmt='parquet', out_dir=None, overwrite=False)

    def vertex_on_regular_polygon(self, v):
        """Return vertex name on a regular polygon if applicable, else empty list."""
        try:
            if self.ft[v][0] == "Polygon" and int(self.ft[v][3]):
                return [self.df.filter((pl.col("Command") == self.df[self.rd[v]]["Command"]) & (pl.col("Type") == "polygon"))["Name"].item()]
        except (IndexError, ValueError):
            return []
        else:
            return []

    # Note: Tokenization and reconstruction utilities were moved to the
    # external `ggblab` package. The implementation has been removed from
    # `ggblab_extra` to avoid duplication. See _tokenize_with_commas above
    # which delegates to the external implementation.


# Module-level wrapper for convenience: allow direct import
# `tokenize_with_commas_str` wrapper removed — use `ggblab.parser.tokenize_with_commas` directly.


# Backwards-compatible name used by imports in `ggblab`
ggb_parser = ConstructionTreeParser

__all__ = ["ConstructionTreeParser", "ggb_parser"]
