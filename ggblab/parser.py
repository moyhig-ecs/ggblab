"""Lightweight tokenizer utilities used by `ggblab`.

This module provides a compact `ggb_parser` class exposing only the
tokenization and token-reconstruction helpers required by the core package.
For richer parser features and DataFrame-based construction helpers, install
the optional `ggblab_extra` package and import the full implementations from
`ggblab_extra.parser` or `ggblab_extra.construction_parser`.
"""

import logging
import re
import math
import itertools

from ggblab.persistent_counter import PersistentCounter


class ggb_parser:
    """Minimal parser exposing only `tokenize_with_commas` and `reconstruct_from_tokens`.

    This lightweight class preserves the original implementations of the two
    methods while removing other parser functionality. For richer parser
    features or DataFrame-based construction helpers, install ``ggblab_extra``.
    The core implementation intentionally keeps a compact surface area so
    that importing ``ggblab`` remains lightweight.
    """
    
    def __init__(self, cache_path=None, cache_enabled=True):
        """Initialize the lightweight parser and optional command cache."""
        cache_path = cache_path or '.ggblab_command_cache'
        try:
            self.command_cache = PersistentCounter(cache_path=cache_path, enabled=cache_enabled)
        except Exception:
            # Fallback: simple no-op cache when PersistentCounter fails
            class _Noop:
                def increment(self, *args, **kwargs):
                    return
            self.command_cache = _Noop()

    def tokenize_with_commas(self, cmd_string, extract_commands=False):  # register_expr=False
        """Tokenize a GeoGebra command string into a structured list representation.
        
        Parses a mathematical or GeoGebra-like command string and converts it into
        a nested list structure that preserves parentheses, brackets, and commas.
        This is useful for analyzing GeoGebra command syntax and extracting object
        dependencies.
        
        === COMMA PRESERVATION AND GEOGEBRA'S IMPLICIT MULTIPLICATION ===
        
        This tokenizer preserves commas as explicit tokens for a critical reason:
        GeoGebra outputs commands with implicit multiplication operators omitted.
        
        Example:
            Internal representation: Circle(2 * a, b)
            GeoGebra output:         Circle(2a, b)  <- Information loss!
        
        The '*' operator is completely omitted, destroying information. This is a
        one-way transformation: we can't reliably reconstruct "2*a" from "2a" without
        external context (is it "2 times a" or "variable named 2a"?).
        
        BUT: GeoGebra ALWAYS uses comma-separation for parameter lists. We exploit
        this invariant. By preserving commas in the token stream, we can:
        1. Identify parameter boundaries (comma = separator)
        2. Use whitespace/context to infer where implicit multiplication occurred
        
        This is a workaround for GeoGebra's poor design. So the question becomes:
        
        - BLAME GeoGebra for being a one-way encoder (lose the *? Why?)
        - PRAISE the developer who recognized the comma-separation invariant
        
        Engineering lesson: deal with imperfect systems and find creative solutions.
        GeoGebra didn't help us. We had to be smarter than it.
        
        Args:
            cmd_string (str): Input command string (e.g., "Circle(A, Distance(A, B))").
            extract_commands (bool, optional): If True, also extract command name candidates
                                              (tokens preceding '(' or '['). Returns a dict
                                              with 'tokens' and 'commands' keys. If False
                                              (default), returns only the token list for
                                              backward compatibility. Default: False
            # register_expr (bool, optional): Future feature - if True, replace object references
            #                          with abstract labels like ${0}, ${1}, etc. based on
            #                          generation order in the construction protocol.
            #                          This is useful because GeoGebra applets may rename
            #                          objects at runtime, but the generation order remains
            #                          stable within a construction. Not yet implemented.
        
        Returns:
            list or dict: 
                - If extract_commands=False (default): Nested list structure with tokens.
                  Parentheses/brackets create nested lists; commas are preserved as ','.
                - If extract_commands=True: Dict with keys:
                  - 'tokens': Nested list structure (as above)
                  - 'commands': Set of command name candidates (tokens preceding '(' or '[')
        
        Raises:
            ValueError: If parentheses/brackets are mismatched.
        
        Examples:
            >>> tokenize_with_commas("Circle(A, 2)")
            ['Circle', ['A', ',', '2']]
            
            >>> tokenize_with_commas("Circle(A, 2)", extract_commands=True)
            {'tokens': ['Circle', ['A', ',', '2']], 'commands': {'Circle'}}
            
            >>> tokenize_with_commas("Distance(Point(1, 2), B)")
            ['Distance', [['Point', ['1', ',', '2']], ',', 'B']]
            
            >>> tokenize_with_commas("Distance(Point(1, 2), B)", extract_commands=True)
            {'tokens': ['Distance', [['Point', ['1', ',', '2']], ',', 'B']], 'commands': {'Distance', 'Point'}}
        
        Note:
            Empty or non-string input returns an empty list (or empty dict if
            extract_commands=True) without raising an error.
            
            Commas are INTENTIONALLY preserved as tokens to work around GeoGebra's
            implicit multiplication. This is not a quirk; it's the core design decision.
            
            Future (register_expr parameter): When implemented, would enable stable object
            references by using construction order indices instead of runtime labels.
            Example output: ['Circle', ['${0}', ',', '${1}']] if register_expr=True
            and the objects were the 0th and 1st in the protocol.
        """
        if not cmd_string or not isinstance(cmd_string, str):
            # raise ValueError("Input must be a non-empty string.")
            if extract_commands:
                return {'tokens': [], 'commands': set()}
            return []

        # Regex pattern to match (1) parentheses, (2) commas, or (3) any sequence of non-spacing characters.
        tokens = re.findall(r'[()\[\]\{\},]|[^()\[\]\{\}\s,]+', cmd_string)

        # GeoGebra often emits implicit multiplication as juxtaposed tokens like "-1.0x".
        # Detect a leading numeric coefficient and split it into two tokens so downstream
        # code can treat it as an explicit multiplication (e.g. ['-1.0', 'x']).
        coeff_re = re.compile(r"^([-+]?\d*\.\d+|\d+)(.*)$")

        # Stack holds tuples: (current_list, suppress_commas_flag)
        stack = [([], False)]
        commands = set() if extract_commands else None
        prev_token = None

        i = 0
        n = len(tokens)
        while i < n:
            token = tokens[i]
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            if token in ['(', '[', '{']:
                # If extracting commands and previous token looks like a command name, save it
                if extract_commands and prev_token and isinstance(prev_token, str) and prev_token[0].isalpha():
                    commands.add(prev_token)
                # Determine whether this brace group should suppress comma-splitting
                suppress = False
                if token == '{' and isinstance(prev_token, str):
                    # If previous token ends with '^' or '_' (e.g. A^{...} or A_{...}),
                    # treat this as a sub/superscript grouping and DO NOT split on commas.
                    # If the caret/underscore is attached to the previous token (e.g. 'C_'),
                    # split it off so the symbol is the standalone prev_token ('_').
                    if prev_token.endswith('^') or prev_token.endswith('_') or prev_token in ('^', '_'):
                        # detach trailing '^' or '_' if attached
                        if (prev_token.endswith('^') or prev_token.endswith('_')) and len(prev_token) > 1:
                            try:
                                cur_list, _ = stack[-1]
                                # replace last element with the base (without trailing symbol)
                                base = prev_token[:-1]
                                symbol = prev_token[-1]
                                cur_list[-1] = base
                                prev_token = symbol
                            except Exception:
                                # best-effort: leave prev_token unchanged on error
                                pass
                        suppress = True
                # Special-case: suppressed brace means we should consume the brace
                # content and attach it to the preceding token (e.g., C_{t} -> 'C_{t}')
                if token == '{' and suppress:
                    # consume inner tokens until matching '}'
                    depth = 1
                    inner_parts = []
                    i += 1
                    while i < n and depth > 0:
                        tk = tokens[i]
                        if tk == '{':
                            depth += 1
                            inner_parts.append(tk)
                        elif tk == '}':
                            depth -= 1
                            if depth > 0:
                                inner_parts.append(tk)
                        else:
                            inner_parts.append(tk)
                        i += 1
                    # build inner string without added spaces
                    inner_str = ''.join(inner_parts)
                    try:
                        cur_list, _ = stack[-1]
                        # previous element should be the base (we detached it earlier)
                        base = cur_list[-1]
                        symbol = prev_token if isinstance(prev_token, str) else ''
                        combined = f"{base}{symbol}{{{inner_str}}}"
                        cur_list[-1] = combined
                        prev_token = combined
                    except Exception:
                        # fallback: create a nested list as before
                        new_list = []
                        stack[-1][0].append(new_list)
                        stack.append((new_list, True))
                        prev_token = None
                    i += 0
                    continue
                # Begin a new nested list (non-suppressed)
                new_list = []
                stack[-1][0].append(new_list)
                stack.append((new_list, suppress))
                prev_token = None
                i += 1
                continue
            elif token in [')', ']', '}']:
                # Close an active nested list
                if len(stack) > 1:
                    stack.pop()
                else:
                    raise ValueError("Mismatched parentheses/brackets in input string.")
                prev_token = None
                i += 1
            elif token == ',':
                # Treat commas as tokens, unless the current group suppresses comma-splitting
                cur_list, suppress = stack[-1]
                if suppress:
                    # Attach comma to previous string token if possible so it is
                    # not treated as a separator later (e.g., in A^{1,2}).
                    if cur_list and isinstance(cur_list[-1], str):
                        cur_list[-1] = cur_list[-1] + ','
                        prev_token = cur_list[-1]
                    else:
                        # No previous token to append to; store comma as literal
                        cur_list.append(',')
                        prev_token = ','
                else:
                    stack[-1][0].append(',')
                    prev_token = None
                i += 1
            else:
                # Normal token gets added to the current list
                # Handle GeoGebra-style coefficient tokens like "-1.0x" -> "-1.0", "x"
                m = coeff_re.match(token)
                cur_list, _ = stack[-1]
                if m and m.group(2):
                    # Split into coefficient and remainder token
                    rem = m.group(2)
                    cur_list.append(m.group(1))
                    cur_list.append(rem)
                    prev_token = rem
                else:
                    t = token
                    cur_list.append(t)
                    prev_token = t
                i += 1

        if len(stack) != 1:
            raise ValueError("Mismatched parentheses/brackets in input string.")

        if extract_commands and commands:
            try:
                self.command_cache.increment(commands)
            except Exception:
                logging.getLogger(__name__).exception("Failed to increment command_cache with commands")
            return {'tokens': stack[0], 'commands': commands}

        return stack[0]

    def strip_comma(self, parsed_tokens):
        """Return a copy of `parsed_tokens` with all comma tokens removed.

        The input should be the nested list structure returned by
        `ggb_parser.tokenize_with_commas`. This method recursively walks the
        structure and omits any element equal to the literal comma token `','`.
        """
        if not isinstance(parsed_tokens, list):
            return parsed_tokens

        # No top-level commas: recurse normally and collapse trivial single-item lists
        if not any(t == ',' for t in parsed_tokens):
            res = [self.strip_comma(t) for t in parsed_tokens]
            for idx, elem in enumerate(res):
                if isinstance(elem, list) and all(isinstance(i, list) and len(i) == 1 for i in elem):
                    res[idx] = [[i[0] for i in elem]]
            return res

        # Use itertools.groupby to split on comma tokens into segments
        segments = []
        for is_comma, group in itertools.groupby(parsed_tokens, key=lambda x: x == ','):
            if is_comma:
                continue
            seg = list(group)
            seg_processed = [self.strip_comma(x) for x in seg]
            # Flatten single-item lists inside a segment
            new_seg = [e[0] if isinstance(e, list) and len(e) == 1 else e for e in seg_processed]
            segments.append(new_seg)

        # Collapse wrapped one-level-deep patterns: [[['a'], ['b']]] -> ['a', 'b']
        for idx, elem in enumerate(segments):
            if isinstance(elem, list) and len(elem) == 1 and isinstance(elem[0], list):
                inner = elem[0]
                if all(isinstance(x, list) and len(x) == 1 for x in inner):
                    segments[idx] = [x[0] for x in inner]

        # Single-level unwrap: [[['1','0']]] -> [['1','0']]
        def _unwrap_once(obj):
            if isinstance(obj, list):
                if len(obj) == 1 and isinstance(obj[0], list):
                    return obj[0]
                return [_unwrap_once(e) for e in obj]
            return obj

        segments = _unwrap_once(segments)

        # Final top-level unwrap if appropriate
        if isinstance(segments, list) and len(segments) == 1 and isinstance(segments[0], list):
            return segments[0]
        return segments

    def tokenize(self, cmd_string, extract_commands=False, simplify=False):
        """Tokenize input then remove comma tokens.

        This is a convenience wrapper that calls `tokenize_with_commas` and
        then `strip_comma` to return a comma-free token structure. If
        `extract_commands` is True, returns the same dict produced by
        `tokenize_with_commas` but with the 'tokens' value stripped of commas.
        """
        res = self.tokenize_with_commas(cmd_string, extract_commands=extract_commands)
        def convert_q_to_nan(obj):
            if isinstance(obj, list):
                return [convert_q_to_nan(x) for x in obj]
            if isinstance(obj, str) and obj == '?':
                return math.nan
            return obj

        def _normalize_triple_nesting(obj):
            # Recursively replace patterns like [[['a','b']]] -> [['a','b']]
            if isinstance(obj, list):
                out = []
                for e in obj:
                    ne = _normalize_triple_nesting(e)
                    # If ne is a single-item list whose only element is itself
                    # a single-item list which contains a list, unwrap one level.
                    if (
                        isinstance(ne, list)
                        and len(ne) == 1
                        and isinstance(ne[0], list)
                        and len(ne[0]) == 1
                        and isinstance(ne[0][0], list)
                    ):
                        out.append(ne[0])
                    else:
                        out.append(ne)
                return out
            return obj

        def _prune_nans(obj):
            # Prune NaN values while preserving empty group placeholders.
            # Heuristic: if a list's children are all lists, treat it as a
            # comma-separated segment list and remove empty segments but
            # return [] when all segments were removed (so the parent keeps
            # an empty list placeholder). Otherwise, remove float NaNs but
            # keep empty lists.
            if isinstance(obj, list):
                pruned_children = [_prune_nans(e) for e in obj]

                # If all children are lists, consider this a segment-list: drop
                # empty child lists but return empty list if all were removed.
                if pruned_children and all(isinstance(c, list) for c in pruned_children):
                    non_empty = [c for c in pruned_children if len(c) != 0]
                    if not non_empty:
                        return []
                    return non_empty

                # General case: drop NaN floats but keep empty lists
                out = []
                for c in pruned_children:
                    if isinstance(c, float) and math.isnan(c):
                        continue
                    out.append(c)
                return out
            return obj

        if extract_commands:
            if not res:
                return {'tokens': [], 'commands': set()}
            cleaned = self.strip_comma(res['tokens'])
            cleaned = _normalize_triple_nesting(cleaned)
            converted = convert_q_to_nan(cleaned)
            pruned = _prune_nans(converted)
            if simplify:
                pruned = self.tokenize_simplify(pruned)
            return {'tokens': pruned, 'commands': res.get('commands', set())}
        cleaned = self.strip_comma(res)
        cleaned = _normalize_triple_nesting(cleaned)
        converted = convert_q_to_nan(cleaned)
        pruned = _prune_nans(converted)
        if simplify:
            pruned = self.tokenize_simplify(pruned)
        return pruned

    def reconstruct_from_tokens(self, parsed_tokens):
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
            >>> parser.reconstruct_from_tokens(['Circle', ['A', ',', '2']])
            'Circle(A, 2)'
            
            >>> parser.reconstruct_from_tokens(['Distance', [['Point', ['1', ',', '2']], ',', 'B']])
            'Distance(Point(1, 2), B)'
        
        Note:
            This function is the inverse of tokenize_with_commas(). It handles
            proper spacing around operators and parentheses.
            
            The 'register_expr' parameter (commented out) was intended for register expressions,
            where applet-assigned labels could be replaced with construction-order-based
            abstract expressions like '${n}', since GeoGebra may reassign object labels
            but construction order remains stable.
        """
        if isinstance(parsed_tokens, str):
            # If the token is a string, return it directly
            return parsed_tokens

        elif isinstance(parsed_tokens, list):
            result = []
            for token in parsed_tokens:
                if isinstance(token, list):
                    # For nested lists, recursively reconstruct and wrap in parentheses
                    result.append(f"({self.reconstruct_from_tokens(token)})")
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

    def tokenize_simplify(self, tokens, rel_tol=1e-9, abs_tol=1e-12):
        """Return a simplified token structure by removing duplicate list elements.

        For any list whose elements are all lists, duplicate elements are removed
        (keeping first occurrence). When comparing numeric tokens, floating
        point values are compared with `math.isclose` using the provided
        tolerances. This preserves semantics for coefficient tokens.

        Args:
            tokens: Token structure (as returned by `tokenize`).
            rel_tol, abs_tol: Tolerances passed to `math.isclose` for numeric comparisons.

        Returns:
            Simplified token structure.
        """
        def _is_float_like(x):
            if isinstance(x, float):
                return True
            if not isinstance(x, str):
                return False
            try:
                float(x)
                return True
            except Exception:
                return False

        def _deep_eq(a, b):
            # List vs list: elementwise compare
            if isinstance(a, list) and isinstance(b, list):
                if len(a) != len(b):
                    return False
                return all(_deep_eq(x, y) for x, y in zip(a, b))

            # Numeric comparison when both are float-like
            if _is_float_like(a) and _is_float_like(b):
                try:
                    af = float(a)
                    bf = float(b)
                except Exception:
                    return a == b
                if math.isnan(af) and math.isnan(bf):
                    return True
                return math.isclose(af, bf, rel_tol=rel_tol, abs_tol=abs_tol)

            # Fallback: direct equality
            return a == b

        def _recurse(obj):
            if isinstance(obj, list):
                children = [_recurse(e) for e in obj]
                # If this is a list-of-lists, deduplicate by deep equality
                if children and all(isinstance(c, list) for c in children):
                    seen = []
                    out = []
                    for c in children:
                        if not any(_deep_eq(c, s) for s in seen):
                            seen.append(c)
                            out.append(c)
                    return out
                return children
            return obj

        return _recurse(tokens)
