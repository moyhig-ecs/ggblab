import re
import polars as pl
import networkx as nx
from copier import Iterable
from itertools import combinations, chain

class ggb_parser:
    """Dependency graph parser for GeoGebra constructions.
    
    Analyzes object relationships in GeoGebra constructions by building
    directed graphs using NetworkX. Provides two graph representations:
    
    - G (full dependency graph): Complete construction dependencies
    - G2 (simplified subgraph): Minimal construction sequences (DEPRECATED)
    
    The parse() method builds the forward/backward dependency graph (G).
    The parse_subgraph() method attempts minimal extraction but has critical
    performance limitations (see method docstring and ARCHITECTURE.md).
    
    Attributes:
        df (polars.DataFrame): Construction protocol dataframe
        G (nx.DiGraph): Full dependency graph
        G2 (nx.DiGraph): Simplified subgraph (from parse_subgraph)
        roots (list): Objects with no dependencies (in-degree = 0)
        leaves (list): Terminal objects (out-degree = 0)
        rd (dict): Reverse mapping from object name to DataFrame row number
        ft (dict): Tokenized function definitions, flattened
    
    Example:
        >>> parser = ggb_parser()
        >>> parser.df = construction_dataframe
        >>> parser.parse()
        >>> print(parser.roots)  # Independent objects
        >>> print(parser.leaves)  # Terminal constructions
    
    See:
        docs/architecture.md § Dependency Parser Architecture
    """
    pl.Config.set_tbl_rows(-1)
    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "polygon", "triangle", "quadrilateral"]

    def __init__(self):
        pass

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
        
        Example:
            >>> parser.df = polars.DataFrame(construction_protocol)
            >>> parser.parse()
            >>> print(list(parser.G.edges()))  # [(A, B), (B, C), ...]
        """
        # reverse dict from name to row number of dataframe
        self.rd = {v: k for k, v in enumerate(self.df["Name"])}

        # tokenized function, flattened
        self.ft = {n: list([e for e in flatten(tokenize_with_commas(c)) if e != ','])
                   for n, c in self.df.filter(pl.col("Type").is_in(self.SHAPES)).select(["Name", "Command"]).iter_rows()}

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
        if df is not None:
            self.df = df
        elif file is not None:
            self.df = pl.read_parquet(file)
        else:
            raise ValueError("Either df or file must be provided.")
        self.df = (self.df
            .transpose(include_header=True, header_name="Name", column_names=self.COLUMNS)
            .with_columns(pl.col("Layer").cast(pl.Int64).fill_null(0)))
        return self

    def write_parquet(self, file=None):
        if file is not None:
            self.df.write_parquet(file)
        return self

    def vertex_on_regular_polygon(self, v):
        try:
            if self.ft[v][0] == "Polygon" and int(self.ft[v][3]):
                return [self.df.filter((pl.col("Command") == self.df[self.rd[v]]["Command"]) & (pl.col("Type") == "polygon"))["Name"].item()]
        except (IndexError, ValueError):
            return []
        else:
            return []

def tokenize_with_commas(cmd_string):  #, regexp=False
    """Tokenize a GeoGebra command string into a structured list representation.
    
    Parses a mathematical or GeoGebra-like command string and converts it into
    a nested list structure that preserves parentheses, brackets, and commas.
    This is useful for analyzing GeoGebra command syntax and extracting object
    dependencies.
    
    Args:
        cmd_string (str): Input command string (e.g., "Circle(A, Distance(A, B))").
    
    Returns:
        list: Nested list structure with tokens. Parentheses/brackets create
              nested lists; commas are preserved as ',' tokens.
    
    Raises:
        ValueError: If parentheses/brackets are mismatched.
    
    Examples:
        >>> tokenize_with_commas("Circle(A, 2)")
        ['Circle', ['A', ',', '2']]
        
        >>> tokenize_with_commas("Distance(Point(1, 2), B)")
        ['Distance', [['Point', ['1', ',', '2']], ',', 'B']]
    
    Note:
        Empty or non-string input returns an empty list without raising an error.
    """
    if not cmd_string or not isinstance(cmd_string, str):
        # raise ValueError("Input must be a non-empty string.")
        return []

    # Regex pattern to match (1) parentheses, (2) commas, or (3) any sequence of non-spacing characters.
    tokens = re.findall(r'[()\[\],]|[^()\[\]\s,]+', cmd_string)

    stack = [[]]
    for token in tokens:
        if token in ['(', '[']:
            # Begin a new nested list
            new_list = []
            stack[-1].append(new_list)
            stack.append(new_list)
        elif token in [')', ']']:
            # Close an active nested list
            if len(stack) > 1:
                stack.pop()
            else:
                raise ValueError("Mismatched parentheses/brackets in input string.")
        elif token == ',':
            # Treat commas as tokens
            stack[-1].append(',')
        else:
            # Normal token gets added to the current list
            # if regexp and token in rd:
            #     token = f"${rd[token]}"
            stack[-1].append(token)

    if len(stack) != 1:
        raise ValueError("Mismatched parentheses/brackets in input string.")
    return stack[0]


def reconstruct_from_tokens(parsed_tokens):
    """Reconstruct the original command string from tokenized structured list.
    
    Takes a nested list structure produced by tokenize_with_commas() and
    reconstructs the original command string with proper parentheses, commas,
    and spacing.
    
    Args:
        parsed_tokens (list or str): Tokenized structured list, or a single
                                      token as a string.
    
    Returns:
        str: Reconstructed command string matching the original input structure.
    
    Raises:
        ValueError: If parsed_tokens contains unexpected types.
    
    Examples:
        >>> tokens = ['Circle', ['A', ',', '2']]
        >>> reconstruct_from_tokens(tokens)
        'Circle(A, 2)'
        
        >>> tokens = ['Distance', [['Point', ['1', ',', '2']], ',', 'B']]
        >>> reconstruct_from_tokens(tokens)
        'Distance(Point(1, 2), B)'
    
    Note:
        This function is the inverse of tokenize_with_commas(). It handles
        proper spacing around operators and parentheses.
    """
    if isinstance(parsed_tokens, str):
        # If the token is a string, return it directly
        return parsed_tokens

    elif isinstance(parsed_tokens, list):
        result = []
        for i, token in enumerate(parsed_tokens):
            if isinstance(token, list):
                # For nested lists, recursively reconstruct and wrap in parentheses
                result.append(f"({reconstruct_from_tokens(token)})")
            elif token == ',':
                # Append a comma directly
                result.append(',')
            else:
                # For normal tokens, add them to the result list
                result.append(token)

        # Reconstruct the final string with proper spacing and joining rules
        return re.sub(r'^\- ', '-',
                    re.sub(r'([^+\-*/]) \(', r'\1(',
                            ' '.join(result).replace(' , ', ', ')))
    else:
        raise ValueError("Unexpected token type in parsed_tokens.")
    
def flatten(items):
    """Recursively flatten nested iterables into a flat generator.
    
    Takes nested lists, tuples, or other iterables and yields all non-iterable
    elements in depth-first order. Strings and bytes are treated as atomic
    elements (not iterated character-by-character).
    
    Args:
        items: An iterable (possibly nested) to flatten, or None.
    
    Yields:
        Non-iterable elements from the input structure.
    
    Examples:
        >>> list(flatten([1, [2, 3], [[4], 5]]))
        [1, 2, 3, 4, 5]
        
        >>> list(flatten(['a', ['b', 'c'], 'd']))
        ['a', 'b', 'c', 'd']
        
        >>> list(flatten([1, [2, [3, [4]]]]))
        [1, 2, 3, 4]
    
    Note:
        This is particularly useful for flattening tokenized command structures
        to extract all object names referenced in a GeoGebra construction.
    """
    if items is None:
        return
    for x in items:
        # イテラブルだが、strではない場合、再帰的に処理
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        else:
            yield x