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
import polars as pl
import networkx as nx
from itertools import combinations, chain
from ggblab.persistent_counter import PersistentCounter
from ggblab.utils import flatten
from ggblab.parser import ggb_parser

# Create a module-level parser instance for tokenization compatibility
_ggb_parser = ggb_parser()


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
                    # print(n, o)
                    self.G.add_edge(o, n)
            for o in self.fbd(n):
                # print(o, ggb.ft[o])
                if n in self.ft[o]:
                    # print(o, n)
                    self.G.add_edge(n, o)

        self.roots = [v for v, d in self.G.in_degree() if d == 0]
        self.leaves = [v for v, d in self.G.out_degree() if d == 0]
        return self.G
    
    def parse_subgraph(self):
        """
        Extract a simplified dependency subgraph (G2) from the full graph (G).
        
        WARNING: This implementation has significant performance limitations and 
        should be replaced in v1.0. See ARCHITECTURE.md for details.
        
        Algorithm:
        - Enumerates all combinations of root objects (O(2^n) combinations)
        - For each combination, identifies dependent objects that exclusively depend on that combination
        - Adds edges to G2 when dependencies are uniquely determined
        
        KNOWN LIMITATIONS (Critical):
        1. **Combinatorial Explosion**: O(2^n) time complexity where n = number of root objects.
           - With 15 roots: ~32,000 paths (manageable)
           - With 20 roots: ~1,000,000 paths (slow)
           - With 25+ roots: computation becomes intractable
           
        2. **Infinite Loop Risk**: The while loop may not terminate under certain graph topologies
           where _nodes1 is not updated in each iteration.
           
        3. **Limited N-ary Dependency Support**: Only handles 1-2 parents. Constructions where
           3+ objects jointly create one output (e.g., polygon from 3+ points) have incomplete
           representation in G2 (these edges are silently skipped).
           
        4. **Redundant Computation**: Neighbor lists are recomputed on every iteration
           of inner loops, causing O(n) redundant work.
           
        5. **Debug Output**: Contains print() statements that should be removed for production.
        
        WORKAROUND:
        - Use with constructions having <15 independent root objects
        - For larger constructions, consider implementing the optimized algorithm
          described in ARCHITECTURE.md § Dependency Parser Architecture
        
        FUTURE: Replace with topological sort + reachability pruning in v1.0 for O(n(n+m)) complexity.
        
        See: https://github.com/[repo]/ARCHITECTURE.md#dependency-parser-architecture
        """
        self.G2 = nx.DiGraph()
        self.G2.clear()

        _nodes0 = set()
        _nodes1 = {n for n in self.roots if n in self.ft}  # set(['C', 'A'])

        while _nodes1:
            # print(f"path: {_nodes0} {_nodes1}")

            _paths = []
            for __p in (list(chain.from_iterable(combinations(_nodes1, r)
                        for r in range(1, len(_nodes1) + 1)))):
                _paths.append(_nodes0 | set(__p))

            for _nodes2 in _paths:
                # _nodes2 = set(__p)
                # print(f"to: {_nodes2 - _nodes0}")

                _nodes3 = set()
                for n1 in _nodes2:
                    _n = [set(self.G.neighbors(__n)) for __n in _nodes2]
                    # print(set().union(*_n))

                    for n0 in set().union(*_n):
                        # print(f"{n0} {ggb.ft[n0]}")
                        d = {n: nx.descendants(self.G, n) for n in self.G.neighbors(n0)}
                        for n1 in sorted(d.keys(), key=lambda e: len(d[e]), reverse=True):
                            # if len(d[n1]) and not ggb.fbd(n0) - (_nodes2 | {n1}):
                            if len(d[n1]) and not nx.ancestors(self.G, n0) - (_nodes2 | {n1}):
                                _nodes3 |= {n0}

                for n in _nodes3 - _nodes2 - _nodes1:
                    match len(_nodes2 - _nodes0):
                        case 1:
                            o, = tuple(_nodes2 - _nodes0)
                            print(f"found: '{o}' => '{n}'")
                            self.G2.add_edge(o, n)
                        case 2:
                            o1, o2, = tuple(_nodes2 - _nodes0)
                            if o1 in self.G2 and n in self.G2.neighbors(o1):
                                pass
                            elif o2 in self.G2 and n in self.G2.neighbors(o2):
                                pass
                            else:
                                print(f"found: '{o1}', '{o2}' => '{n}'")
                                self.G2.add_edge(o1, n)
                                self.G2.add_edge(o2, n)
                        case _:
                            pass

            _nodes0 |= _nodes1
            _nodes1 = _nodes3 - _nodes2 - _nodes1

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
