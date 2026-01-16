# Scoping Implementation: Recursive Functions and Exception-Based Level Control

This document describes the technical implementation of ggblab's core architectural pattern: **using recursive function calls to create scopes** and **try-except blocks to control dependency levels** in geometric scene construction.

---

## Architectural Foundation

### The Core Insight

**The only practical way to create scopes in Python is through function definition**

Python's scoping rules are limited:
- ✅ **Functions** (`def`, `lambda`) create new scopes
- ✅ **Classes** create scopes (but overkill for most cases)
- ✅ **Modules** create scopes (file-level isolation)
- ❌ **try-except** does NOT create scopes
- ❌ **with** statements do NOT create scopes
- ❌ **if/for/while** do NOT create scopes

**ggblab's approach**: Use recursive function calls to mirror the hierarchical dependency structure of geometric constructions, where each construction step creates a new scope level.

### Exception Propagation Across Recursive Calls

**Python exceptions can hook raised exceptions even across recursive function calls**

When an exception is raised in a deep recursive call, Python unwinds the call stack until it finds a matching `except` block:

```python
def level_3():
    raise ValueError("Error at deepest level")

def level_2():
    return level_3()  # No try-except → propagates upward

def level_1():
    try:
        return level_2()
    except ValueError as e:
        # Catches error from level_3
        print(f"Caught at level 1: {e}")
        return "recovered"
```

**Key properties**:
1. Exceptions traverse the entire call stack
2. Any ancestor can intercept the exception
3. Unhandled exceptions propagate to the top level
4. This models **dependency chain validation**: if a deeply nested object fails, all ancestors are notified

---

## Geometric Scene ↔ Function Call Isomorphism

### Mapping Structure

| Geometric Concept | Implementation Pattern |
|------------------|----------------------|
| **Base objects** (points A, B) | Top-level function scope (parameters) |
| **Derived objects** (line AB) | Nested function call: `construct_line(A, B)` |
| **Transitive dependencies** (perpendicular L from AB) | Recursive call: `construct_perpendicular(construct_line(A, B))` |
| **Dependency validation** | `try-except` at each level |
| **Scope level** | Call stack depth |
| **Scope chain** | Call stack trace |
| **Invalid dependency** | Exception raised and propagated upward |

### Example: Isosceles Triangle Construction

**Geometric construction**:
```
Given: Points A, B
1. Construct line AB
2. Construct midpoint M of AB
3. Construct perpendicular L through M
4. Construct point C on L
5. Triangle ABC is isosceles
```

**Implementation with scoped functions**:

```python
class GeometricScene:
    """Manages geometric construction with scope-based dependency tracking."""
    
    def __init__(self):
        self.objects = {}  # Global object registry
        self.scope_stack = []  # Track current scope depth
    
    def construct_isosceles_triangle(self, A, B):
        """Top-level construction: establishes base scope."""
        try:
            # Level 0: Base objects (global scope)
            self._register_base_objects(A, B)
            
            # Level 1: Derived objects depending on base
            AB = self._construct_line(A, B)
            M = self._construct_midpoint(A, B)
            
            # Level 2: Objects depending on Level 1
            L = self._construct_perpendicular(M, AB)
            
            # Level 3: Objects depending on Level 2
            C = self._construct_point_on_line(L)
            
            # Verification: property check across all scopes
            return self._verify_isosceles(A, B, C)
            
        except DependencyError as e:
            # Catch any dependency chain failure
            print(f"Construction failed: {e}")
            return None
    
    def _register_base_objects(self, A, B):
        """Level 0: Register base points (global scope)."""
        self.scope_stack.append("base")
        try:
            self.objects['A'] = A
            self.objects['B'] = B
        finally:
            self.scope_stack.pop()
    
    def _construct_line(self, A, B):
        """Level 1: Create line from two points (nested scope)."""
        self.scope_stack.append("line_AB")
        try:
            if A == B:
                raise DependencyError(
                    f"Cannot create line: points A and B are identical. "
                    f"Scope chain: {' → '.join(self.scope_stack)}"
                )
            line = Line(A, B)
            self.objects['AB'] = line
            return line
        finally:
            self.scope_stack.pop()
    
    def _construct_midpoint(self, A, B):
        """Level 1: Create midpoint (sibling scope to line_AB)."""
        self.scope_stack.append("midpoint_M")
        try:
            # This function creates its own scope
            # Independent of _construct_line but same level
            midpoint = Midpoint(A, B)
            self.objects['M'] = midpoint
            return midpoint
        finally:
            self.scope_stack.pop()
    
    def _construct_perpendicular(self, M, AB):
        """Level 2: Create perpendicular line (depends on Level 1)."""
        self.scope_stack.append("perpendicular_L")
        try:
            # Validate dependencies from parent scopes
            if AB not in self.objects.values():
                raise DependencyError(
                    f"Perpendicular requires line AB from parent scope. "
                    f"Current scope chain: {' → '.join(self.scope_stack)}"
                )
            
            perp = PerpendicularLine(M, AB)
            self.objects['L'] = perp
            return perp
        finally:
            self.scope_stack.pop()
    
    def _construct_point_on_line(self, L):
        """Level 3: Create point constrained to line (deeply nested)."""
        self.scope_stack.append("point_C")
        try:
            # Recursive dependency validation
            if not self._validate_dependency_chain(L):
                raise DependencyError(
                    f"Point C requires valid line L from ancestor scopes. "
                    f"Scope chain: {' → '.join(self.scope_stack)}"
                )
            
            point = PointOnLine(L)
            self.objects['C'] = point
            return point
        finally:
            self.scope_stack.pop()
    
    def _validate_dependency_chain(self, obj):
        """Recursively validate all dependencies exist."""
        try:
            # Check if object is registered
            if obj not in self.objects.values():
                return False
            
            # Recursively check dependencies
            for dep in obj.dependencies:
                if not self._validate_dependency_chain(dep):
                    return False
            
            return True
        except AttributeError:
            # Object has no dependencies attribute
            return True
    
    def _verify_isosceles(self, A, B, C):
        """Verification scope: read from all levels."""
        self.scope_stack.append("verify")
        try:
            # Access objects from multiple scopes
            dist_AC = distance(A, C)
            dist_BC = distance(B, C)
            
            if abs(dist_AC - dist_BC) < 1e-10:
                return True
            else:
                raise VerificationError(
                    f"Triangle is not isosceles: "
                    f"|AC| = {dist_AC:.6f}, |BC| = {dist_BC:.6f}"
                )
        finally:
            self.scope_stack.pop()


class DependencyError(Exception):
    """Raised when geometric dependency chain is broken."""
    pass


class VerificationError(Exception):
    """Raised when geometric property verification fails."""
    pass
```

### Execution Flow

When `construct_isosceles_triangle(A, B)` is called:

```
Scope Stack Evolution:
├─ [] (empty)
├─ ['base']                    → Register A, B
├─ ['base', 'line_AB']         → Construct AB
├─ ['base', 'midpoint_M']      → Construct M
├─ ['base', 'perpendicular_L'] → Construct L (depends on M, AB)
├─ ['base', 'point_C']         → Construct C (depends on L)
└─ ['base', 'verify']          → Verify triangle property
```

**Scope depth = dependency level**. Each function creates a new scope, mirroring geometric hierarchy.

---

## Exception-Based Level Control

### Propagation Strategy

**Exceptions propagate upward through the call stack**, allowing higher-level scopes to handle errors from nested constructions:

```python
def top_level_construction():
    try:
        result = mid_level_construction()
    except DependencyError as e:
        # Handle dependency failures from any nested level
        log_error(f"Construction chain broken: {e}")
        return fallback_construction()
    except VerificationError as e:
        # Handle property verification failures
        log_warning(f"Property not satisfied: {e}")
        return partial_result()

def mid_level_construction():
    # No try-except → propagates errors upward
    derived_obj = deep_level_construction()
    return process(derived_obj)

def deep_level_construction():
    if invalid_state():
        raise DependencyError("Cannot proceed: invalid base objects")
    return construct_object()
```

**Benefits**:
1. **Centralized error handling**: Top-level function decides recovery strategy
2. **Scope transparency**: Intermediate functions don't need to know about error handling
3. **Dependency chain tracing**: Exception message includes full scope stack
4. **Clean separation**: Construction logic vs. error recovery logic

### Error Recovery Patterns

#### Pattern 1: Retry with Modified Parameters

```python
def construct_with_retry(self, A, B, max_attempts=3):
    """Attempt construction, adjusting parameters on failure."""
    for attempt in range(max_attempts):
        try:
            return self.construct_isosceles_triangle(A, B)
        except DependencyError as e:
            if "identical" in str(e) and attempt < max_attempts - 1:
                # Points are identical; perturb slightly
                B = (B[0] + 0.01, B[1] + 0.01)
                continue
            raise  # Give up after max attempts
```

#### Pattern 2: Fallback to Simpler Construction

```python
def construct_with_fallback(self, A, B):
    """Try complex construction, fall back to simple version."""
    try:
        # Attempt full construction with perpendicular
        return self.construct_isosceles_triangle(A, B)
    except DependencyError:
        # Fall back to simple triangle
        return self.construct_simple_triangle(A, B)
```

#### Pattern 3: Partial Results

```python
def construct_partial(self, A, B):
    """Return partial construction if full construction fails."""
    partial_objects = {}
    
    try:
        AB = self._construct_line(A, B)
        partial_objects['line'] = AB
        
        M = self._construct_midpoint(A, B)
        partial_objects['midpoint'] = M
        
        L = self._construct_perpendicular(M, AB)
        partial_objects['perpendicular'] = L
        
        C = self._construct_point_on_line(L)
        partial_objects['point'] = C
        
    except DependencyError as e:
        # Return whatever was constructed successfully
        partial_objects['error'] = str(e)
    
    return partial_objects
```

---

## Scope Lifecycle Management

### Resource Cleanup

Each scope function uses `try-finally` to ensure proper cleanup:

```python
def _construct_with_cleanup(self, dependencies):
    """Create object with guaranteed cleanup."""
    self.scope_stack.append("construct")
    temp_resources = []
    
    try:
        # Allocate resources
        temp_obj = allocate_temporary_object()
        temp_resources.append(temp_obj)
        
        # Perform construction
        result = build_object(temp_obj, dependencies)
        
        # Register in global registry
        self.objects[result.name] = result
        
        return result
        
    except Exception:
        # Clean up on error
        for resource in temp_resources:
            resource.dispose()
        raise
        
    finally:
        # Always pop scope, even if exception occurred
        self.scope_stack.pop()
```

### Scope Inspection

Debugging utilities for scope introspection:

```python
def get_current_scope_depth(self):
    """Return current nesting level."""
    return len(self.scope_stack)

def get_scope_chain(self):
    """Return human-readable scope chain."""
    return " → ".join(self.scope_stack)

def get_objects_in_scope(self, scope_name):
    """Return all objects created within a specific scope."""
    # Implementation depends on metadata tracking
    return [obj for obj in self.objects.values() 
            if obj.creation_scope == scope_name]
```

---

## Part 2: Integration and Advanced Topics

### Integration with GeoGebra Construction Protocol

#### Mapping to GeoGebra Commands

Each geometric construction function maps to GeoGebra commands:

```python
async def construct_isosceles_triangle(self, ggb: GeoGebra, A_coords, B_coords):
    """Construct isosceles triangle in GeoGebra with scope tracking."""
    try:
        # Level 0: Base points
        await ggb.command(f"A={A_coords}")
        await ggb.command(f"B={B_coords}")
        
        # Level 1: Line and midpoint
        AB = await self._ggb_construct_line(ggb, "A", "B")
        M = await self._ggb_construct_midpoint(ggb, "A", "B")
        
        # Level 2: Perpendicular
        L = await self._ggb_construct_perpendicular(ggb, "M", "AB")
        
        # Level 3: Point on line
        C = await self._ggb_construct_point_on_line(ggb, "L")
        
        return await self._ggb_verify_isosceles(ggb, "A", "B", "C")
        
    except Exception as e:
        # GeoGebra command failed
        raise DependencyError(f"GeoGebra construction failed: {e}")

async def _ggb_construct_line(self, ggb: GeoGebra, point1: str, point2: str):
    """Level 1: Create line in GeoGebra."""
    self.scope_stack.append(f"line_{point1}{point2}")
    try:
        await ggb.command(f"{point1}{point2} = Line[{point1}, {point2}]")
        return f"{point1}{point2}"
    finally:
        self.scope_stack.pop()
```

#### Dependency Graph Parsing

ggblab's `ggb_parser` class builds NetworkX graphs directly from GeoGebra construction protocols:

```python
from ggblab import ggb_parser

# Initialize parser and load construction
parser = ggb_parser()
parser.initialize_dataframe(file="construction.parquet")

# Build full dependency graph (NetworkX DiGraph)
parser.parse()

# Access the NetworkX graph
print(f"Graph has {parser.G.number_of_nodes()} nodes, {parser.G.number_of_edges()} edges")
print(f"Roots (no dependencies): {parser.roots}")
print(f"Leaves (terminal objects): {parser.leaves}")

# Example graph structure:
# Nodes: ['A', 'B', 'AB', 'M', 'L', 'C']
# Edges: [('A', 'AB'), ('B', 'AB'), ('A', 'M'), ('B', 'M'), 
#         ('M', 'L'), ('AB', 'L'), ('L', 'C')]

# Calculate scope levels from the graph
def calculate_scope_levels(G):
    """Calculate scope level as longest path from any root."""
    levels = {}
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    
    for node in G.nodes():
        if node in roots:
            levels[node] = 0
        else:
            # Level = max(parent_level) + 1
            parent_levels = [levels[pred] for pred in G.predecessors(node)]
            levels[node] = max(parent_levels) + 1
    
    return levels

scope_levels = calculate_scope_levels(parser.G)
# {
#   'A': 0, 'B': 0,        # Global scope (roots)
#   'AB': 1, 'M': 1,       # Level 1 (depend on roots)
#   'L': 2,                # Level 2 (depends on Level 1)
#   'C': 3                 # Level 3 (depends on Level 2)
# }
```

---

### NetworkX Graph Traversal Integration

#### Dependency Graph as Directed Acyclic Graph (DAG)

The geometric dependency structure is isomorphic to a **directed acyclic graph (DAG)**, where:
- **Nodes** = geometric objects (points, lines, circles, etc.)
- **Edges** = dependency relationships (A → B means "B depends on A")
- **Topological order** = valid construction sequence
- **Scope level** = longest path from root nodes

**ggblab's `ggb_parser.parse()` already builds this NetworkX DiGraph** as `parser.G`. The following sections show how to leverage NetworkX's graph algorithms for educational purposes.

#### Human-Centered Subgraph Extraction: `parse_subgraph()`

**Design Philosophy**: ggblab's `parse_subgraph()` method prioritizes **pedagogical clarity over algorithmic efficiency**. Rather than using theoretically optimal algorithms (e.g., topological sort + reachability pruning), it implements a **human-intuitive exploration process** that mirrors how students actually think about geometric construction:

> "If I have points A and B, what can I construct?"
> "If I add point C, what additional constructions become possible?"

This combinatorial approach:
1. **Enumerates all combinations of root objects** (base points/givens)
2. **Identifies which derived objects require exactly that combination** of roots
3. **Builds a simplified subgraph (G2)** showing minimal construction paths

```python
# Human-centered exploration: try all combinations of starting objects
parser.parse_subgraph()

# Result: G2 contains only "essential" edges
print(f"Full graph G: {parser.G.number_of_edges()} edges")
print(f"Simplified G2: {parser.G2.number_of_edges()} edges")

# G2 shows: "To construct X, you need exactly objects {A, B}"
# rather than: "X depends on A, B, and their transitive dependencies"
```

**Why this design choice?**

1. **Mirrors student thinking**: Students explore "what if" scenarios by trying different combinations of starting conditions
2. **Explicit enumeration is transparent**: Each step is visible and debuggable
3. **Matches classroom workflow**: Teachers ask "What can we build from these givens?"
4. **Computational thinking pedagogy**: Teaches exhaustive search as a valid problem-solving strategy

**Trade-offs acknowledged**:
- ⚠️ **O(2^n) complexity**: With 20+ root objects, enumeration becomes slow
- ⚠️ **Limited n-ary support**: Constructions requiring 3+ simultaneous inputs are simplified
- ✅ **Learning value**: Students see the exploration process explicitly
- ✅ **Correctness**: Finds valid construction paths, even if not always optimal

For classroom use with typical constructions (5-15 root objects), this approach provides **understandable, traceable results** that support learning goals.

#### Alternative Approaches (For Reference)

For production systems or complex constructions, theoretically efficient algorithms exist:

```python
# Efficient algorithm (not implemented in ggblab): topological sort + pruning
def extract_subgraph_efficient(G):
    """O(n(n+m)) algorithm for minimal subgraph extraction."""
    G_minimal = nx.DiGraph()
    
    for node in nx.topological_sort(G):
        direct_parents = list(G.predecessors(node))
        
        # Keep only parents with no alternative path
        for parent in direct_parents:
            G_without = G.copy()
            G_without.remove_edge(parent, node)
            
            # If removing this edge disconnects node from parent, it's essential
            if not nx.has_path(G_without, parent, node):
                G_minimal.add_edge(parent, node)
    
    return G_minimal
```

**ggblab intentionally does NOT use this approach** because:
- Students cannot trace the logic of "remove edge, check connectivity"
- The algorithm is opaque to learners
- Educational value is lost in pursuit of efficiency

**The lesson**: In educational software, **understandability > performance**. ggblab's `parse_subgraph()` sacrifices algorithmic elegance to preserve pedagogical transparency.

#### Leveraging NetworkX for Educational Analysis

NetworkX provides powerful tools for analyzing ggblab's dependency graphs:

```python
import networkx as nx
from typing import Dict, List, Set

class DependencyGraph:
    """Manages geometric dependencies as a NetworkX DAG."""
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self._scope_levels = {}
    
    def add_object(self, name: str, dependencies: List[str]):
        """Add geometric object with its dependencies."""
        self.graph.add_node(name)
        for dep in dependencies:
            # Edge from dependency to dependent
            self.graph.add_edge(dep, name)
    
    def build_from_scene(self, scene_dependencies: Dict[str, List[str]]):
        """Build graph from ggblab parser output."""
        for obj_name, deps in scene_dependencies.items():
            self.add_object(obj_name, deps)
        
        # Verify DAG property
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            raise DependencyError(
                f"Circular dependency detected: {cycles[0]}"
            )
    
    def calculate_scope_levels(self) -> Dict[str, int]:
        """Calculate scope level for each object (longest path from roots)."""
        if self._scope_levels:
            return self._scope_levels
        
        # Find root nodes (no dependencies)
        roots = [n for n in self.graph.nodes() if self.graph.in_degree(n) == 0]
        
        # Calculate longest path from any root
        for node in self.graph.nodes():
            if node in roots:
                self._scope_levels[node] = 0
            else:
                # Level = max(parent_level) + 1
                parent_levels = [
                    self._scope_levels[pred]
                    for pred in self.graph.predecessors(node)
                ]
                self._scope_levels[node] = max(parent_levels) + 1
        
        return self._scope_levels
    
    def topological_construction_order(self) -> List[str]:
        """Return valid construction order (topological sort)."""
        try:
            return list(nx.topological_sort(self.graph))
        except nx.NetworkXError:
            raise DependencyError("Cannot construct: circular dependencies exist")
    
    def get_transitive_dependencies(self, obj_name: str) -> Set[str]:
        """Get all objects that obj_name depends on (transitively)."""
        # All ancestors in the DAG
        return nx.ancestors(self.graph, obj_name)
    
    def get_dependent_objects(self, obj_name: str) -> Set[str]:
        """Get all objects that depend on obj_name (transitively)."""
        # All descendants in the DAG
        return nx.descendants(self.graph, obj_name)
```

#### Graph Traversal Strategies

##### Depth-First Search (DFS) - Recursive Scope Exploration

DFS naturally corresponds to recursive function calls:

```python
def construct_with_dfs(self, target_object: str):
    """Construct object using DFS (recursive dependencies first)."""
    visited = set()
    
    def dfs_construct(obj_name: str):
        """Recursively construct dependencies."""
        if obj_name in visited:
            return  # Already constructed
        
        # DFS: Process dependencies first (recursive scope creation)
        for dep in self.graph.predecessors(obj_name):
            dfs_construct(dep)  # Nested function call = nested scope
        
        # Construct current object after dependencies are ready
        self.scope_stack.append(obj_name)
        try:
            self._construct_object(obj_name)
            visited.add(obj_name)
        except Exception as e:
            raise DependencyError(
                f"Failed to construct {obj_name}. "
                f"Scope chain: {' → '.join(self.scope_stack)}"
            ) from e
        finally:
            self.scope_stack.pop()
    
    dfs_construct(target_object)
```

**DFS characteristics**:
- ✅ Mirrors recursive function call structure
- ✅ Naturally creates scope depth hierarchy
- ✅ Exception propagation follows DFS backtracking
- ❌ May hit stack overflow for deep graphs

##### Breadth-First Search (BFS) - Level-by-Level Construction

BFS constructs all objects at the same scope level before proceeding:

```python
def construct_with_bfs(self):
    """Construct all objects level-by-level (BFS by scope depth)."""
    levels = self.calculate_scope_levels()
    max_level = max(levels.values())
    
    for level in range(max_level + 1):
        # Get all objects at current scope level
        objects_at_level = [
            obj for obj, lvl in levels.items() if lvl == level
        ]
        
        print(f"Constructing scope level {level}: {objects_at_level}")
        
        for obj_name in objects_at_level:
            try:
                self._construct_object(obj_name)
            except Exception as e:
                raise DependencyError(
                    f"Failed at scope level {level}, object {obj_name}: {e}"
                )
```

**BFS characteristics**:
- ✅ Iterative (no stack overflow risk)
- ✅ Clear level-by-level progress
- ✅ Easy to parallelize objects at same level
- ❌ Doesn't mirror recursive structure as naturally

##### Topological Sort - Guaranteed Valid Order

Topological sort provides any valid construction sequence:

```python
def construct_topological(self):
    """Construct objects in topologically sorted order."""
    construction_order = self.topological_construction_order()
    
    for obj_name in construction_order:
        scope_level = self._scope_levels[obj_name]
        
        # All dependencies are guaranteed to be constructed
        dependencies = list(self.graph.predecessors(obj_name))
        
        print(f"[Level {scope_level}] Constructing {obj_name} "
              f"(depends on: {dependencies})")
        
        try:
            self._construct_object(obj_name)
        except Exception as e:
            # Find which dependency caused the failure
            failed_deps = [
                dep for dep in dependencies 
                if not self._is_constructed(dep)
            ]
            raise DependencyError(
                f"Cannot construct {obj_name}: "
                f"missing dependencies {failed_deps}"
            ) from e
```

#### Scope Level Calculation via Longest Path

Scope level is the **longest path** from any root node:

```python
def calculate_scope_level_detailed(self, obj_name: str) -> int:
    """Calculate scope level using longest path algorithm."""
    # Root nodes have level 0
    if self.graph.in_degree(obj_name) == 0:
        return 0
    
    # Level = max(predecessor_level) + 1
    predecessor_levels = []
    for pred in self.graph.predecessors(obj_name):
        pred_level = self.calculate_scope_level_detailed(pred)
        predecessor_levels.append(pred_level)
    
    return max(predecessor_levels) + 1

# Using NetworkX's built-in longest path
def get_longest_path_to_object(self, obj_name: str) -> List[str]:
    """Get the longest dependency chain leading to obj_name."""
    # Find all root nodes
    roots = [n for n in self.graph.nodes() if self.graph.in_degree(n) == 0]
    
    longest_path = []
    for root in roots:
        if nx.has_path(self.graph, root, obj_name):
            # Use DAG longest path
            path = nx.dag_longest_path(
                self.graph.subgraph(
                    nx.ancestors(self.graph, obj_name) | {obj_name, root}
                ),
                weight=None
            )
            if len(path) > len(longest_path):
                longest_path = path
    
    return longest_path
```

#### Detecting and Handling Circular Dependencies

```python
def detect_circular_dependencies(self) -> List[List[str]]:
    """Find all circular dependency chains."""
    if nx.is_directed_acyclic_graph(self.graph):
        return []
    
    # Find all simple cycles
    cycles = list(nx.simple_cycles(self.graph))
    return cycles

def break_cycle_interactive(self, cycle: List[str]) -> str:
    """Suggest how to break a circular dependency."""
    return (
        f"Circular dependency detected: {' → '.join(cycle + [cycle[0]])}\n"
        f"Suggestions:\n"
        f"  1. Remove dependency: {cycle[-1]} → {cycle[0]}\n"
        f"  2. Reorder construction to avoid forward reference\n"
        f"  3. Introduce intermediate object to break cycle"
    )
```

#### Example: Complete Integration

```python
from ggblab import ggb_parser
import networkx as nx

# Parse GeoGebra construction
scene = await ggb_parser.parse("isosceles_triangle.ggb")

# Build dependency graph
dep_graph = DependencyGraph()
dep_graph.build_from_scene(scene.dependencies)

# Analyze structure
print("Topological order:", dep_graph.topological_construction_order())
# Output: ['A', 'B', 'AB', 'M', 'L', 'C']

print("Scope levels:", dep_graph.calculate_scope_levels())
# Output: {'A': 0, 'B': 0, 'AB': 1, 'M': 1, 'L': 2, 'C': 3}

# Find what C depends on
print("C depends on:", dep_graph.get_transitive_dependencies('C'))
# Output: {'L', 'M', 'AB', 'A', 'B'}

# Find what depends on AB
print("Depends on AB:", dep_graph.get_dependent_objects('AB'))
# Output: {'L', 'C'}

# Get longest dependency chain to C
longest_path = dep_graph.get_longest_path_to_object('C')
print("Longest path to C:", ' → '.join(longest_path))
# Output: A → AB → L → C  (or B → AB → L → C, both length 3)

# Construct using DFS (recursive)
dep_graph.construct_with_dfs('C')

# Or construct all using BFS (iterative, level-by-level)
dep_graph.construct_with_bfs()
```

#### Correspondence: Function Calls ↔ Graph Traversal

| Concept | Recursive Functions | NetworkX Graph |
|---------|-------------------|----------------|
| **Scope creation** | Function call creates new scope | DFS visit creates new stack frame |
| **Scope level** | Call stack depth | Longest path from root |
| **Dependency** | Function parameter | Directed edge in DAG |
| **Construction order** | Call sequence | Topological sort order |
| **Error propagation** | Exception unwinds stack | Traverse ancestors |
| **Impact analysis** | Modify parameter → rerun dependents | Modify node → traverse descendants |
| **Circular dependency** | Infinite recursion | Cycle detection in graph |

#### Educational Benefits

Students learn that:
1. **Graph structure = Scope structure**: Both are hierarchical dependency trees
2. **DFS = Recursive construction**: Natural isomorphism
3. **BFS = Level-by-level construction**: Iterative alternative
4. **Topological sort = Valid execution order**: Any valid sequence works
5. **Longest path = Scope depth**: Measures nesting level

This bridges **graph theory**, **recursive algorithms**, and **programming scopes** through a single geometric construction example.

---

### Educational Implications

#### Teaching Scoping Through Geometry

**Students see the correspondence**:

1. **Geometric construction steps** ↔ **Function call hierarchy**
2. **Dependency chains** ↔ **Scope chains**
3. **Construction errors** ↔ **Exception propagation**
4. **Parameter changes** ↔ **Scope re-evaluation**

#### Classroom Workflow

```python
# Lesson: Understanding nested scopes through geometric construction

# Step 1: Show simple construction
A = (0, 0)
B = (3, 0)
scene = GeometricScene()
result = scene.construct_isosceles_triangle(A, B)

# Step 2: Inspect scope chain
print(scene.get_scope_chain())
# Output: base → line_AB → perpendicular_L → point_C → verify

# Step 3: Introduce error
A = (0, 0)
B = (0, 0)  # Identical points!
try:
    result = scene.construct_isosceles_triangle(A, B)
except DependencyError as e:
    print(f"Error: {e}")
    # Output: Cannot create line: points A and B are identical.
    #         Scope chain: base → line_AB

# Step 4: Discuss how error propagated from nested scope to top level
```

#### Assessment Rubric

Students demonstrate understanding by:
1. Predicting scope depth from geometric construction sequence
2. Identifying which scope level an error originated from
3. Writing recovery code at the appropriate scope level
4. Explaining dependency chains using scope vocabulary

---

### Performance Considerations

#### Stack Depth Limits

Python's default recursion limit is ~1000. For complex scenes:

```python
import sys
sys.setrecursionlimit(5000)  # Increase if needed

# Or use iterative approach for very deep constructions
def construct_iterative(self, base_objects):
    """Iterative construction to avoid stack overflow."""
    current_objects = base_objects
    for level in range(max_depth):
        try:
            current_objects = self._construct_level(current_objects, level)
        except DependencyError as e:
            print(f"Construction stopped at level {level}: {e}")
            break
    return current_objects
```

#### Optimization Strategies

1. **Memoization**: Cache constructed objects to avoid redundant computation
2. **Lazy evaluation**: Only construct objects when accessed
3. **Batch operations**: Group GeoGebra commands to reduce async overhead

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def _construct_line_cached(self, point1_hash, point2_hash):
    """Cached line construction."""
    # Implementation
    pass
```

---

## Summary

**ggblab's scoping architecture leverages Python's fundamental limitation**—that functions are the only practical way to create scopes—and **turns it into a teaching tool**.

**Core principles**:
1. **Recursive functions create scope hierarchy** matching geometric dependency structure
2. **try-except propagates exceptions upward** through scope chains for validation
3. **Scope depth = dependency level** provides a visual, intuitive model
4. **Exception handling = error recovery strategy** at each abstraction level

**Result**: Students learn programming scopes through a domain they already understand (geometry), with immediate visual feedback (GeoGebra) and concrete error messages (scope chain traces).

This is not just a technical implementation—it's a **pedagogical framework** that makes abstract concepts tangible.
