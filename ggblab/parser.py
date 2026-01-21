"""Lightweight tokenizer utilities used by `ggblab`.

This module provides a compact `ggb_parser` class exposing only the
tokenization and token-reconstruction helpers required by the core package.
For richer parser features and DataFrame-based construction helpers, install
the optional `ggblab_extra` package and import the full implementations from
`ggblab_extra.parser` or `ggblab_extra.construction_parser`.
"""

import re
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
        tokens = re.findall(r'[()\[\],]|[^()\[\]\s,]+', cmd_string)

        stack = [[]]
        commands = set() if extract_commands else None
        prev_token = None

        for token in tokens:
            if token in ['(', '[']:
                # If extracting commands and previous token looks like a command name, save it
                if extract_commands and prev_token and isinstance(prev_token, str) and prev_token[0].isalpha():
                    commands.add(prev_token)
                # Begin a new nested list
                new_list = []
                stack[-1].append(new_list)
                stack.append(new_list)
                prev_token = None
            elif token in [')', ']']:
                # Close an active nested list
                if len(stack) > 1:
                    stack.pop()
                else:
                    raise ValueError("Mismatched parentheses/brackets in input string.")
                prev_token = None
            elif token == ',':
                # Treat commas as tokens
                stack[-1].append(',')
                prev_token = None
            else:
                # Normal token gets added to the current list
                # Future: if register_expr and token in rd:
                #     token = f"${rd[token]}"  # Replace with abstract order-based label
                stack[-1].append(token)
                prev_token = token

        if len(stack) != 1:
            raise ValueError("Mismatched parentheses/brackets in input string.")

        if extract_commands and commands:
            try:
                self.command_cache.increment(commands)
            except Exception:
                pass
            return {'tokens': stack[0], 'commands': commands}

        return stack[0]

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
