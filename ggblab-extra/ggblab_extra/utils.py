"""Common utility functions for ggblab.

Python's Design: Strengths and Grievances
==========================================

**Strengths** (Worth Celebrating)
---------------------------------

1. **Arbitrary-Precision Integers (No Overflow)**
   
   Python's integers grow without bound—no overflow, no underflow:
   
   >>> 2 ** 1000  # Works perfectly; other languages crash
   10715086071862673209486401838653240326034519584122143271853696
   
   This is genuinely excellent for numerical computation. Combined with
   float handling, Python is unexpectedly robust for scientific work.

2. **Generators: Interactive Computing Gold**
   
   Generators are often criticized for "being hard," but they're invaluable
   for interactive computing and data exploration:
   
   >>> def fib():
   ...     a, b = 0, 1
   ...     while True:
   ...         yield a
   ...         a, b = b, a + b
   >>> for val in fib():
   ...     if val > 100: break
   ...     print(val)
   
   In interactive notebooks (like Jupyter), generators enable lazy evaluation—
   essential for large datasets that can't fit in memory.

3. **Pattern Matching (Python 3.10+): Excellent Structural Decomposition**
   
   Structural pattern matching with tuple unpacking is genuinely beautiful:
   
   >>> match edges:
   ...     case []:
   ...         return "no edges"
   ...     case [single]:
   ...         return f"one edge: {single}"
   ...     case [first, second]:
   ...         return f"two edges: {first}, {second}"
   ...     case [first, *rest]:
   ...         return f"multiple edges starting with {first}"
   
   Real-world example: In construction.py, detecting file types by magic bytes
   uses match elegantly. Without pattern matching, you'd write:
   
   >>> magic = tuple(f.read(4).decode())
   # Without match (old Python):
   # if len(magic) >= 4:
   #     if magic[0] == 'U' and magic[1] == 'E' and magic[2] == 's' and magic[3] == 'D':
   #         # base64 detection
   #     elif magic[0] == 'P' and magic[1] == 'K':
   #         # ZIP detection
   #     elif magic[0] in ('{', '['):
   #         # JSON detection
   
   # With match (Python 3.10+):
   >>> match magic:
   ...     case ('U', 'E', 's', 'D'):
   ...         handle_base64()
   ...     case ('P', 'K', _, _):
   ...         handle_zip()
   ...     case ('{', _, _, _) | ('[', _, _, _):
   ...         handle_json()
   
   This is expressive, readable, and far superior to length-checking boilerplate.

**Grievances** (Design Flaws)
-----------------------------

4. **String as Iterable: The Perpetual Footgun**
   
   str being iterable causes endless bugs because iterating strings is rarely
   what you want. Strings should have required explicit type conversion to tuple
   or list before being treated as iterable sequences:
   
   >>> def process(items):
   ...     return [x for item in items for x in item]
   >>> process(['abc', 'def'])  # Expected: ['abc', 'def']
   ['a', 'b', 'c', 'd', 'e', 'f']  # Oops!
   
   Real-world example: In construction.py, file magic byte detection reveals the trap:
   
   >>> magic = f.read(4).decode()  # Returns str like 'UEsD', 'PK\x03\x04', etc.
   >>> match magic:  # WRONG! This iterates characters: 'U', 'E', 's', 'D'
   ...     case ('U', 'E', 's', 'D'):  # Never matches!
   ...         handle_base64()
   
   The fix requires explicit conversion:
   
   >>> match tuple(magic):  # MUST convert string to tuple manually
   ...     case ('U', 'E', 's', 'D'):
   ...         handle_base64()
   ...     case ('P', 'K', _, _):
   ...         handle_zip()
   
   We have to write explicit `tuple()` conversions EVERYWHERE because of this design flaw.
   This violates the Principle of Least Surprise and is a genuine design flaw.
   
   **The Fix** (Should Have Been Done):
   ```python
   # Strings should require explicit conversion:
   for char in str('hello'):  # Not: for char in 'hello'
       print(char)
   ```
   
   This one design decision cascades into complexity throughout the ecosystem.

5. **flatten() Not Standardized**
   
   Despite being one of the most common operations, Python refuses to include
   it in the standard library. You must either:
   - Use itertools.chain.from_iterable() (only 1-level deep)
   - Install external dependencies
   - Implement it yourself every single time
   
   JavaScript has Array.flat(). Why doesn't Python?
   
   The excuse: "Strings are iterable, so it's ambiguous."
   The reality: This is a solvable problem (see point 4 above).

6. **Education Gap: Modern Features Ignored**
   
   Python keeps adding excellent features that go largely unused:
   - Walrus operator (:=) for cleaner loops
   - Union types (X | Y instead of Union[X, Y])
   - Structural pattern matching (match/case)
   - Positional-only parameters (def f(x, /))
   
   But most tutorials, Stack Overflow answers, and even production code
   still use ancient patterns. This is educator negligence, not a language fault—
   but it's a systemic problem that weakens adoption of better code practices.

7. **Scope Management Ambiguity: global, nonlocal, and Closures**
   
   Python's scoping rules are fundamentally limited and confusing:
   
   **The Problem**:
   - ✅ **Functions create scopes** (the only practical way)
   - ✅ **Classes create scopes** (but overkill for most cases)
   - ✅ **Modules create scopes** (file-level isolation)
   - ❌ **try-except does NOT create scopes** — variables leak out!
   - ❌ **with statements do NOT create scopes** — no local isolation
   - ❌ **if/for/while do NOT create scopes** — loop variables pollute the outer scope
   
   **Real example from scoping_implementation.md**:
   
   When building geometric dependency graphs, you might want to group objects
   by scope level:
   
   ```python
   # Attempt 1: Using if/for (won't work for isolation)
   for level in range(max_level):
       if level == current:
           objects_at_level = [...]  # Variables leak into outer scope!
       # objects_at_level is still accessible here (undesired)
   
   # Attempt 2: Using try-except (won't work for isolation)
   try:
       temp_cache = load_cache()
       process(temp_cache)
   finally:
       pass
   # temp_cache is STILL accessible here (should be scoped!)
   ```
   
   **The workaround**: Use functions (unnecessarily verbose):
   
   ```python
   # Attempt 3: Only solution—wrap in a function
   def process_at_level(level):
       objects_at_level = [...]
       temp_cache = load_cache()
       return results
   # True scope isolation, but requires extra function definition
   ```
   
   **The cure that doesn't exist**: Python should have provided:
   - `scope { ... }` blocks (like JavaScript's blocks in ES6+)
   - Explicit scope declarations in comprehensions
   - `let` / `const` keywords (instead of bare `=`)
   
   **Why this matters for ggblab**: 
   In construction.py's magic byte detection and scope level calculation,
   we resort to tuple wrapping and manual scope management because Python
   won't let us isolate variables naturally in conditional or loop blocks.
   
   This is especially painful in geometry where hierarchical scope levels
   are natural to the problem but awkward in Python's model.

8. **Asyncio Scope Separation: Global State Required for Concurrent Operations**
   
   A particularly insidious scoping problem emerges when using Python's asyncio:
   **data exchange buffers for concurrent tasks must be class variables (global scope),
   not instance variables**. This violates object-oriented encapsulation principles.
   
   **The Problem**:
   
   When multiple async tasks share data (e.g., one task populates a buffer, another reads it),
   you might naturally write:
   
   ```python
   class AsyncHandler:
       def __init__(self):
           self.recv_logs = {}      # ❌ Instance variable
       
       async def send_request(self, msg_id):
           # This task reads from recv_logs
           while not (msg_id in self.recv_logs):
               await asyncio.sleep(0.01)
           return self.recv_logs[msg_id]
       
       async def handle_response(self, msg_id, data):
           # This task writes to recv_logs
           self.recv_logs[msg_id] = data
   ```
   
   This **appears to work** because both methods are on the same object. But it breaks
   in concurrent contexts where async tasks are scheduled unpredictably. The issue is not
   a Python scoping bug—it's that **the scope boundaries don't match the concurrency model**.
   
   **The Fix** (Ugly):
   
   ```python
   class AsyncHandler:
       # ⚠️ MUST be class variable, not instance variable
       recv_logs = {}  # Shared across all instances and async tasks!
       
       async def send_request(self, msg_id):
           # Now both tasks see THE SAME recv_logs
           while not (msg_id in AsyncHandler.recv_logs):  # or just self.recv_logs
               await asyncio.sleep(0.01)
           return AsyncHandler.recv_logs[msg_id]
   ```
   
   **Why this is a design flaw**:
   - ✅ Instance variables are semantically correct (encapsulation)
   - ❌ Instance variables don't work with asyncio's concurrency model
   - ⚠️ No clear error; the code silently fails due to scope mismatch
   - ⚠️ Developers must understand asyncio's execution model to debug this
   
   **Real-world impact in ggblab**:
   In `ggblab/comm.py`, message buffers (recv_logs, recv_events) must be class variables:
   
   ```python
   class ggb_comm:
       # These MUST be class variables
       recv_logs = {}          # Response storage for send_recv() tasks
       recv_events = queue.Queue()  # Event queue for client_handle() task
       
       async def send_recv(self, msg):
           # Sends request, reads from recv_logs
           _id = str(uuid.uuid4())
           self.send(msg)
           while not (_id in self.recv_logs):  # Checks class-level dict
               await asyncio.sleep(0.01)
       
       async def client_handle(self, client_id):
           # Receives response, writes to recv_logs
           async for msg in client_id:
               _id = msg.get('id')
               self.recv_logs[_id] = msg['payload']  # Populates class-level dict
   ```
   
   This coupling of instance-based OOP with class-based asyncio shared state is
   **inelegant and error-prone**. It's a symptom of Python's conflicting design principles.

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
