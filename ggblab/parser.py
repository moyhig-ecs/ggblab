import re
import polars as pl
import networkx as nx
from copier import Iterable
from itertools import combinations, chain

class ggb_parser:
    pl.Config.set_tbl_rows(-1)
    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "polygon", "triangle", "quadrilateral"]

    def __init__(self):
        pass

    def parse(self):
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
    """
    Tokenizes a mathematical or GeoGebra-like command string into a structured list representation,
    including commas and parentheses/brackets as part of the structured list.

    Args:
        cmd_string (str): Input command string.

    Returns:
        list: Nested list structure with tokens.
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
    """
    Reconstructs the original string from the tokenized structured list with
    parentheses/brackets and commas.

    Args:
        parsed_tokens (list or str): Tokenized structured list, or a single token as a string.

    Returns:
        str: A reconstructed string matching the original input structure.
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
    if items is None:
        return
    for x in items:
        # イテラブルだが、strではない場合、再帰的に処理
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        else:
            yield x