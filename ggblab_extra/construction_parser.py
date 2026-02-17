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

import hashlib
import json
import json as _json
import logging
import os
import re
import time
from itertools import chain, combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence, Union

import networkx as nx
import polars as pl

from ggblab.parser import ggb_parser
from ggblab.persistent_counter import PersistentCounter
from ggblab.utils import flatten

if TYPE_CHECKING:
    from ggblab.ggbapplet import GeoGebra

# module logger
logger = logging.getLogger(__name__)

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
    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
        # fallback for dict-like or pandas
        names = list(df["Name"])

    G.add_nodes_from(names)

    # attach Type attribute for known nodes from the dataframe
    try:
        if "Type" in df.columns:
            try:
                types_list = df["Type"].to_list()
            except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                types_list = list(df["Type"])
            type_map = {name: t for name, t in zip(names, types_list)}
            nx.set_node_attributes(G, type_map, "Type")
    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
        pass

    # obtain raw dependency column values
    if col not in df.columns:
        return G

    try:
        raw = df[col].to_list()
    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
        raw = list(df[col])

    for name, v in zip(names, raw):
        if v is None:
            continue
        deps = v
        if isinstance(v, str):
            try:
                deps = json.loads(v)
            except (json.JSONDecodeError, TypeError, ValueError):
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
            except (TypeError, ValueError, nx.NetworkXError):
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
                except (ImportError, nx.NetworkXError):
                    # Fallback: remove edges (u,v) if there exists an alternate path u->...->v
                    to_remove = set()
                    for u, v in list(G.edges()):
                        # if there's a path of length >1 from u to v, the direct edge is transitive
                        try:
                            for path in nx.all_simple_paths(G, u, v):
                                if len(path) > 2:
                                    to_remove.add((u, v))
                                    break
                        except nx.NetworkXError:
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
                    except nx.NetworkXError:
                        pass
                G.remove_edges_from(to_remove)
        except (AttributeError, TypeError, nx.NetworkXError, ValueError):
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
            except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                raw_col = list(df[col])

            for name, v in zip(names, raw_col):
                if v is None:
                    anc_map[name] = set()
                    continue
                if isinstance(v, str):
                    try:
                        deps = json.loads(v)
                    except (json.JSONDecodeError, TypeError, ValueError):
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
                        try:
                            if nx.is_directed_acyclic_graph(G):
                                try:
                                    from networkx.algorithms.dag import transitive_reduction

                                    G = transitive_reduction(G)
                                except (ImportError, nx.NetworkXError):
                                    # Fallback: remove edges (u,v) if there exists an alternate path u->...->v
                                    to_remove = set()
                                    for u, v in list(G.edges()):
                                        # if there's a path of length >1 from u to v, the direct edge is transitive
                                        try:
                                            for path in nx.all_simple_paths(G, u, v):
                                                if len(path) > 2:
                                                    to_remove.add((u, v))
                                                    break
                                        except nx.NetworkXError:
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
                                    except nx.NetworkXError:
                                        pass
                                G.remove_edges_from(to_remove)
                        except (AttributeError, TypeError, nx.NetworkXError, ValueError):
                            # best-effort: if reduction fails, return original graph
                            pass
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
            pass

    return G


def group_list_nodes(G: nx.DiGraph, list_name: str, parents: Sequence[str], elements: Sequence[str], *, group_suffix: str = '__group') -> str:
    """Create a grouping node for a list-like construction and wire parents/elements.

    Given a directed graph ``G``, a ``list_name`` (e.g. ``l1``), a sequence
    of parent node names (e.g. ``['c', 'g']``) and element node names
    (e.g. ``['D', 'E']``), this helper will:

    - create a synthetic group node named ``f"{list_name}{group_suffix}"``
    - attach the group node as a dependent of each parent (parent -> group)
    - attach each element as dependent of the group (group -> element)
    - record the members on the group node under the ``group_members`` attribute

    Returns the group node name.

    Example:
        >>> G = nx.DiGraph()
        >>> G.add_nodes_from(['c','g','l1','D','E'])
        >>> group = group_list_nodes(G, 'l1', ['c','g'], ['D','E'])
        >>> list(G.predecessors(group))
        ['c','g']
        >>> list(G.successors(group))
        ['D','E']
    """
    if not isinstance(G, nx.DiGraph):
        raise TypeError("G must be a networkx.DiGraph")

    group_node = f"{list_name}{group_suffix}"
    if group_node not in G:
        G.add_node(group_node)

    # Ensure parents and elements exist as nodes and wire edges
    for p in parents or ():
        if p is None:
            continue
        if p not in G:
            G.add_node(p)
        try:
            G.add_edge(p, group_node)
        except Exception:
            pass

    for e in elements or ():
        if e is None:
            continue
        if e not in G:
            G.add_node(e)
        try:
            G.add_edge(group_node, e)
        except Exception:
            pass

    # Record group membership for downstream consumers
    try:
        nx.set_node_attributes(G, {group_node: {'group_members': [list_name] + list(elements)}})
    except Exception:
        # best-effort: ignore attribute setting failures
        pass

    return group_node


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
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral", "boolean", "numeric", "angle"]
    # Default container types to include when searching for composite objects
    DEFAULT_CONTAINER_TYPES = {"polygon", "segment", "circle"}

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

        # Initialize commonly-used attributes here to avoid
        # `attribute-defined-outside-init` (W0201) warnings and to make the
        # object's shape explicit for consumers and static analysis.
        self.rd = {}
        self.ft = {}
        self.G = nx.DiGraph()
        self.G2 = nx.DiGraph()
        self.roots = []
        self.leaves = []

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
            for n in ['xAxis', 'yAxis', 'zAxis', 'xOyPlane', 'xOzPlane', 'yOzPlane']:
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

        # attach Type attributes from the dataframe to graph nodes when available
        try:
            if hasattr(self, 'df') and self.df is not None and "Type" in self.df.columns:
                try:
                    types_list = self.df["Type"].to_list()
                except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                    types_list = list(self.df["Type"])
                try:
                    names_list = self.df["Name"].to_list()
                except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                    names_list = list(self.df["Name"])
                type_map = {name: t for name, t in zip(names_list, types_list)}
                nx.set_node_attributes(self.G, type_map, "Type")
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
            pass

        self.roots = [v for v, d in self.G.in_degree() if d == 0]
        self.leaves = [v for v, d in self.G.out_degree() if d == 0]

        # If a DataFrame is present, ensure `DependsOn` is a list-type column.
        # If the column exists as JSON strings, decode; otherwise compute
        # transitively from the graph. Best-effort: do not fail parse() on errors.
        try:
            if hasattr(self, 'df') and self.df is not None:
                if "DependsOn" in self.df.columns:
                    try:
                        raw_col = self.df["DependsOn"].to_list()
                    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                        raw_col = list(self.df["DependsOn"])
                    converted = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted.append(json.loads(v))
                            except (json.JSONDecodeError, TypeError, ValueError):
                                converted.append(sorted(nx.ancestors(self.G, n)) if n in self.G else [])
                        elif v is None:
                            converted.append(sorted(nx.ancestors(self.G, n)) if n in self.G else [])
                        else:
                            converted.append(v)
                else:
                    converted = [sorted(nx.ancestors(self.G, n)) if n in self.G else [] for n in self.df["Name"]]

                # attach or replace DependsOn as a polars List(Utf8) column
                self.df = self.df.with_columns(pl.Series("DependsOn", converted).cast(pl.List(pl.Utf8)))
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
            pass

        # Validate token map (self.ft) for anomalies: self-references, missing refs, cycles
        try:
            # determine FT report output path:
            # precedence: instance attribute `ft_report_dir` -> env `GGBLAB_FT_REPORT_DIR`
            # Default: disabled (do not write reports) unless explicitly set.
            out_dir = getattr(self, 'ft_report_dir', None) or os.environ.get('GGBLAB_FT_REPORT_DIR')
            if out_dir:
                out_dir = Path(out_dir)
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError):
                    # best-effort: ignore directory creation errors
                    pass

                # allow overriding filename via instance attribute `ft_report_name`
                fname = getattr(self, 'ft_report_name', None)
                if not fname:
                    # deterministic default: short sha1 of canonicalized ft content
                    try:
                        canonical = [(k, list(self.ft.get(k) or [])) for k in sorted(self.ft.keys())]
                        canonical_json = _json.dumps(canonical, ensure_ascii=False, sort_keys=True)
                        digest = hashlib.sha1(canonical_json.encode('utf8')).hexdigest()[:8]
                        fname = f'ft_anomalies_{digest}.json'
                    except (TypeError, ValueError):
                        # fallback to fixed name if hashing fails
                        fname = 'ft_anomalies.json'

                report_path = str(out_dir / fname)
                self._validate_ft(out_path=report_path)
            else:
                # Writing ft anomaly reports is disabled by default. To enable,
                # set the env `GGBLAB_FT_REPORT_DIR` or assign `ft_report_dir`
                # on the parser instance.
                pass
        except (OSError, PermissionError):
            # Do not fail parse on logging or I/O errors
            logger.exception('ft validation failed')

        return self.G

    def parse_subgraph(self, max_depth: Optional[int] = None, timeout_seconds: Optional[float] = 10.0):
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

        Args:
            max_depth: Optional[int] maximum number of frontier expansion
                iterations to perform. If ``None`` (default) the algorithm
                runs to completion. Use this to bound execution time on
                large graphs; each while-iteration corresponds to one level
                of frontier expansion.
            timeout_seconds: Optional[float] wall-clock timeout in seconds.
                If provided and exceeded during exploration, the method will
                log a warning and fall back to ``parse_subgraph_legacy``.
                Set to ``None`` to disable time-based timeout. Default: 10.0.

        Returns:
            The constructed `G2` (assigned to `self.G2`).
        """
        start_time = time.monotonic()

        self.G2 = nx.DiGraph()
        self.G2.clear()

        # attach Type attributes from the dataframe to G2 nodes when available
        try:
            if hasattr(self, 'df') and self.df is not None and "Type" in self.df.columns:
                try:
                    types_list = self.df["Type"].to_list()
                except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                    types_list = list(self.df["Type"])
                try:
                    names_list = self.df["Name"].to_list()
                except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                    names_list = list(self.df["Name"])
                type_map = {name: t for name, t in zip(names_list, types_list)}
                nx.set_node_attributes(self.G2, type_map, "Type")
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
            pass

        explored = set()
        frontier = {n for n in self.roots if n in self.ft}
        depth = 0

        while frontier:
            # Check timeout at start of each iteration
            if timeout_seconds is not None and (time.monotonic() - start_time) > timeout_seconds:
                logger.warning("parse_subgraph: timeout exceeded (%.2fs), falling back to parse_subgraph_legacy", timeout_seconds)
                return self.parse_subgraph_legacy()
            # Build all candidate active-sets from the current frontier
            candidate_active_sets = [explored | set(combo)
                                     for combo in chain.from_iterable(combinations(frontier, r)
                                                                     for r in range(1, len(frontier) + 1))]

            collected_matches = set()

            for active_set in candidate_active_sets:
                # Periodically check timeout inside heavy loops
                if timeout_seconds is not None and (time.monotonic() - start_time) > timeout_seconds:
                    logger.warning("parse_subgraph: timeout exceeded during candidate evaluation (%.2fs), falling back to parse_subgraph_legacy", timeout_seconds)
                    return self.parse_subgraph_legacy()
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

            # increment depth and enforce max_depth if provided
            depth += 1
            if max_depth is not None and depth >= max_depth:
                # stop exploring further to bound runtime
                break

            # attempt to attach Type attributes from the dataframe to G2 nodes
            try:
                if hasattr(self, 'df') and self.df is not None and "Type" in self.df.columns:
                    try:
                        types_list = self.df["Type"].to_list()
                    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                        types_list = list(self.df["Type"])
                    try:
                        names_list = self.df["Name"].to_list()
                    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                        names_list = list(self.df["Name"])
                    type_map = {name: t for name, t in zip(names_list, types_list)}
                    nx.set_node_attributes(self.G2, type_map, "Type")
            except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                pass

            # If a DataFrame is present, ensure `DependsOn_minimal` is a list-type column.
        # If the column exists as JSON strings, decode; otherwise compute using
        # direct predecessors from G2 (fallback to G). Best-effort: do not fail.
        try:
            if hasattr(self, 'df') and self.df is not None:
                if "DependsOn_minimal" in self.df.columns:
                    try:
                        raw_col = self.df["DependsOn_minimal"].to_list()
                    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                        raw_col = list(self.df["DependsOn_minimal"])
                    converted_min = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted_min.append(json.loads(v))
                            except (json.JSONDecodeError, TypeError, ValueError):
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
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
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
                    try:
                        raw_col = self.df["DependsOn_minimal"].to_list()
                    except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
                        raw_col = list(self.df["DependsOn_minimal"])
                    converted_min = []
                    for v, n in zip(raw_col, self.df["Name"]):
                        if isinstance(v, str):
                            try:
                                converted_min.append(json.loads(v))
                            except (json.JSONDecodeError, TypeError, ValueError):
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
        except (AttributeError, TypeError, KeyError, IndexError, ValueError, OSError, json.JSONDecodeError, nx.NetworkXError):
            pass

        return self.G2

    # def parse_subgraph_improved(self):
    #     """
    #     Identify minimal construction sequences by analyzing the dependency graph.
    #     Uses a topological sort + pruning approach instead of exhaustive path enumeration.
    #     """
    #     self.G2 = nx.DiGraph()
    #
    #     # Identify which nodes are essential (no alternative path)
    #     for node in self.G.nodes():
    #         direct_parents = list(self.G.predecessors(node))
    #         if not direct_parents:
    #             continue
    #
    #         # Check if all direct parents are needed
    #         # A parent is needed if removing it disconnects node from any root
    #         parents_to_keep = []
    #         for parent in direct_parents:
    #             # Check if there's an alternative path without this parent
    #             G_without = self.G.copy()
    #             G_without.remove_edge(parent, node)
    #             has_alternative = nx.has_path(G_without, parent, node)
    #
    #             if not has_alternative:
    #                 parents_to_keep.append(parent)
    #
    #         # Add edges for essential parents
    #         for parent in parents_to_keep:
    #             self.G2.add_edge(parent, node)

    def ffd(self, k, recursive=True):
        """Return forward-facing dependencies for node `k`."""
        if recursive:
            def _ffd(k, seen):
                # Protect against cycles by tracking visited nodes in `seen`.
                if k in seen:
                    return []
                seen.add(k)
                try:
                    if k in self.ft:
                        results = []
                        # forward references: nodes that list k in their tokenized args
                        for e in self.ft:
                            if k in self.ft[e]:
                                results.append([e, _ffd(e, seen)])
                        # include explicit returns if present
                        for e in self.find_returns(k)[1:]:
                            results.append([e, _ffd(e, seen)])
                        seen.remove(k)
                        return results
                    else:
                        seen.remove(k)
                        return []
                except (RuntimeError, TypeError, ValueError, KeyError, IndexError):
                    # On unexpected errors, be conservative and stop recursion
                    if k in seen:
                        seen.remove(k)
                    return []

            return set(flatten(_ffd(k, set())))
        else:
            return {e for e in self.ft if k in self.ft[e]}

    def fbd(self, k, recursive=True):
        """Return backward-facing dependencies for node `k`."""
        if recursive:
            def _fbd(k, seen):
                # Protect against cycles by tracking visited nodes in `seen`.
                if k in seen:
                    return []
                seen.add(k)
                try:
                    if k in self.ft:
                        results = []
                        for e in self.ft[k]:
                            if e in self.ft:
                                results.append([e, _fbd(e, seen)])
                        # include potential polygon vertex helper
                        results.append(self.vertex_on_regular_polygon(k))
                        seen.remove(k)
                        return results
                    else:
                        seen.remove(k)
                        return []
                except (RuntimeError, TypeError, ValueError, KeyError, IndexError):
                    if k in seen:
                        seen.remove(k)
                    return []

            return set(flatten(_fbd(k, set()))) - {k}
        else:
            return {e for e in self.ft[k] if e in self.ft}

    def roots_to_targets_with_containers(self, targets, roots=None, include_types=None, max_container_depth=1):
        """Return an induced subgraph containing paths from roots to targets
        and composite objects that contain those targets.

        Args:
            targets: iterable of target node names.
            roots: iterable of root node names (defaults to self.roots).
            include_types: list or set of Type strings to treat as 'containers'
                (None => include all types). If provided as a list it will be
                coerced to a set for efficient membership tests.
            max_container_depth: how deep to walk descendants from each target to find containers.

        Returns:
            nx.DiGraph: induced subgraph containing paths and selected containers.
        """
        if roots is None:
            roots = getattr(self, 'roots', [])
        targets = set(targets)

        # determine include_types: if None, use class default; otherwise coerce to set
        if include_types is None:
            include_types = set(getattr(self, 'DEFAULT_CONTAINER_TYPES', []))
        else:
            try:
                include_types = set(include_types)
            except (TypeError, ValueError):
                include_types = {include_types}

        nodes = set()

        # 1) collect nodes on any path from any root to each target
        for r in roots:
            for t in list(targets):
                try:
                    for path in nx.all_simple_paths(self.G, r, t):
                        nodes.update(path)
                except nx.NetworkXError:
                    # fallback: include ancestors if path enumeration fails
                    if t in self.G:
                        nodes.update(nx.ancestors(self.G, t))
                        nodes.add(t)

        # 2) ensure targets themselves are present
        nodes.update(targets)

        # 3) find container objects reachable from each target (descendants)
        containers = set()
        for t in targets:
            if t not in self.G:
                continue
            frontier = {t}
            depth = 0
            visited = {t}
            while frontier and depth < max_container_depth:
                next_front = set()
                for n in frontier:
                    for child in self.G.successors(n):
                        if child in visited:
                            continue
                        visited.add(child)
                        node_type = self.G.nodes.get(child, {}).get('Type')
                        if include_types is None or node_type in include_types:
                            containers.add(child)
                        next_front.add(child)
                frontier = next_front
                depth += 1

        # 4) include containers and their immediate components
        nodes |= containers
        for c in list(containers):
            try:
                comps = list(self.G.predecessors(c))
                nodes.update(comps)
                nodes.add(c)
            except (nx.NetworkXError, TypeError, ValueError):
                pass

        # 5) build induced subgraph and return copy as DiGraph
        try:
            G_sub = self.G.subgraph(nodes).copy()
            return nx.DiGraph(G_sub)
        except (nx.NetworkXError, TypeError, ValueError):
            return nx.DiGraph()

    # Note: use `roots_to_targets_with_containers` to obtain a subtree from
    # roots to targets that also includes container objects (polygons, segments, circles).

    def initialize_dataframe(self, df=None, file=None):
        """Initialize the parser from `df` or delegate to ConstructionIO when given a file."""
        import asyncio
        import warnings

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
        import asyncio
        import warnings

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

    def _validate_ft(self, out_path=None):
        """Detect anomalies in self.ft, log them and optionally write a JSON report.

        Args:
            out_path (str|None): If provided, writes a JSON report to this path.

        Returns:
            dict: Structured report containing lists of anomalies and diagnostics.
        """
        report = {'self_refs': [], 'unknown_refs': {}, 'cycles': []}
        if not hasattr(self, 'ft') or not isinstance(self.ft, dict):
            logger.debug('No ft to validate')
            return report

        # direct self-references
        self_refs = [n for n, toks in self.ft.items() if isinstance(toks, (list, tuple)) and n in toks]
        report['self_refs'] = self_refs
        if self_refs:
            logger.warning('Direct self-references detected in ft: %s', self_refs)

        # unknown references
        known = set(self.ft.keys())
        unknown_refs = {}
        for n, toks in self.ft.items():
            if not isinstance(toks, (list, tuple)):
                continue
            bad = [t for t in toks if isinstance(t, str) and t not in known]
            if bad:
                unknown_refs[n] = bad
        report['unknown_refs'] = unknown_refs
        if unknown_refs:
            logger.info('Unknown token references found in ft (node -> unknowns): %s', unknown_refs)

        # build ft-graph and detect cycles
        H = nx.DiGraph()
        H.add_nodes_from(self.ft.keys())
        for n, toks in self.ft.items():
            if not isinstance(toks, (list, tuple)):
                continue
            for t in toks:
                if t in known:
                    H.add_edge(n, t)

        cycles = list(nx.simple_cycles(H))
        report['cycles'] = cycles
        if cycles:
            logger.warning('Cycles detected in ft token graph: %d cycles (showing up to 10): %s', len(cycles), cycles[:10])

        # optional JSON dump
        if out_path:
            try:
                safe = {
                    'self_refs': report['self_refs'],
                    'unknown_refs': report['unknown_refs'],
                    'cycles': [list(c) for c in report['cycles']],
                    'node_count': len(self.ft),
                }
                with open(out_path, 'w', encoding='utf8') as fh:
                    json.dump(safe, fh, ensure_ascii=False, indent=2)
                logger.info('Wrote ft validation report to %s', out_path)
            except (OSError, PermissionError):
                logger.exception('Failed to write ft validation report to %s', out_path)

        return report

    # Note: Tokenization and reconstruction utilities were moved to the
    # external `ggblab` package. The implementation has been removed from
    # `ggblab_extra` to avoid duplication. See _tokenize_with_commas above
    # which delegates to the external implementation.


# Module-level wrapper for convenience: allow direct import
# `tokenize_with_commas_str` wrapper removed — use `ggblab.parser.tokenize_with_commas` directly.


# Backwards-compatible name used by imports in `ggblab`
ggb_parser = ConstructionTreeParser

__all__ = ["ConstructionTreeParser", "ggb_parser"]
