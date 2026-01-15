"""Common utility functions for ggblab.

Python's Design Grievances
==========================

This module exists because Python's standard library refuses to include basic
utilities that every developer needs. Here are some legitimate complaints:

1. **flatten() is not standardized**
   
   Despite being one of the most common operations, Python forces you to either:
   - Use itertools.chain.from_iterable() (only 1-level deep)
   - Install more-itertools (external dependency)
   - Write it yourself every single time
   
   JavaScript has Array.flat(). Why doesn't Python have list.flatten()?
   
   The excuse: "Strings are iterable, so it's ambiguous."
   The reality: This is a solvable problem. Just treat str/bytes as atomic by default.
   
2. **String as Iterable: The Perpetual Footgun**
   
   str being iterable causes endless bugs:
   
   >>> def process(items):
   ...     return [x for item in items for x in item]
   >>> process(['abc', 'def'])  # Expected: ['abc', 'def']
   ['a', 'b', 'c', 'd', 'e', 'f']  # Oops!
   
   We have to write `isinstance(x, (str, bytes))` checks EVERYWHERE.
   This is a design flaw, not a feature.
   
3. **Pattern Matching Underutilized (Since Python 3.10)**
   
   Python 3.10 introduced structural pattern matching with beautiful tuple unpacking:
   
   >>> match edges:
   ...     case []:
   ...         return "no edges"
   ...     case [single]:
   ...         return f"one edge: {single}"
   ...     case [first, second]:
   ...         return f"two edges: {first}, {second}"
   ...     case [first, *rest]:
   ...         return f"multiple edges starting with {first}"
   
   Yet most Python code still uses:
   - if len(edges) == 0: ...
   - if len(edges) == 1: x = edges[0]; ...
   - if len(edges) >= 2: first, second = edges[0], edges[1]; ...
   
   Why? Because Python educators haven't caught up with modern features.
   The language evolves, but teaching materials stay stuck in 2015.
   
4. **Education Gap: Modern Python Features Ignored**
   
   Python keeps adding excellent features that go unused:
   - Walrus operator (:=) for cleaner loops
   - Union types (X | Y instead of Union[X, Y])
   - Structural pattern matching (match/case)
   - Positional-only parameters (def f(x, /))
   
   But most tutorials, Stack Overflow answers, and even production code
   still use ancient patterns. This is educator negligence, plain and simple.
   
   If you introduce a feature, TEACH IT. Otherwise, what's the point?

Now, the actual utilities:
"""

from collections.abc import Iterable


def flatten(items):
    """Recursively flatten nested iterables.
    
    Converts nested structures like [[1, [2, 3]], 4] into [1, 2, 3, 4].
    Strings and bytes are treated as atomic elements (not iterated).
    
    Note: This function exists because Python refuses to standardize it.
          Yes, we have to explicitly check for str/bytes because Python
          decided strings should be iterable. Thanks for that footgun.
    
    Args:
        items: Any iterable that may contain nested iterables.
        
    Yields:
        Flattened items from the nested structure.
        
    Examples:
        >>> list(flatten([1, [2, 3], [[4], 5]]))
        [1, 2, 3, 4, 5]
        
        >>> list(flatten(['a', ['b', 'c'], 'd']))
        ['a', 'b', 'c', 'd']
        
        >>> list(flatten([1, [2, [3, [4]]]]))
        [1, 2, 3, 4]
        
        # Without the str check, this would break:
        >>> list(flatten(['hello', 'world']))
        ['hello', 'world']  # Not ['h', 'e', 'l', 'l', 'o', 'w', 'o', 'r', 'l', 'd']
    """
    for item in items:
        # The infamous "str is iterable" check we all have to write
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            yield from flatten(item)
        else:
            yield item
