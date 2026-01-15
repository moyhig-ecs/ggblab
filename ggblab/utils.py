"""Common utility functions for ggblab."""

from collections.abc import Iterable


def flatten(items):
    """Recursively flatten nested iterables.
    
    Converts nested structures like [[1, [2, 3]], 4] into [1, 2, 3, 4].
    Strings and bytes are treated as atomic elements (not iterated).
    
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
    """
    for item in items:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            yield from flatten(item)
        else:
            yield item
