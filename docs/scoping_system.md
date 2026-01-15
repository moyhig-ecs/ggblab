# GeoGebra Scoping System Design

## Overview

The ggblab scoping system manages geometric object visibility and accessibility within evolving construction sequences. It integrates with GeoGebra's layer system and Python's variable scoping metaphor to provide:

1. **Geometric Scope Trees**: Objects grouped by dependency and layer
2. **Visibility Control**: Layer-based filtering of accessible objects
3. **Scope-Aware Validation**: Ensuring object references are within appropriate scope

## Core Concepts

### Layer-Based Visibility

GeoGebra's construction protocol includes layer information (0-9, default 0). Objects on different layers can be:
- Hidden/shown independently
- Used to organize complexity
- Mapped to Python scope levels (global → function → nested)

### Dependency-Driven Scoping

The parser's dependency graph naturally forms a scope tree:
```
Root objects (global scope)
  ├─ Point A
  ├─ Point B
  │
  ├─ Circle(A, B)
  │   ├─ Derived: Line segment
  │   └─ Derived: Intersection point C
  │
  └─ Polygon([A, B, C])
      └─ Derived: Area calculation
```

Objects can only reference their ancestors and siblings in this tree.

## Implementation Strategy

### Phase 1: Passive Tracking (Current)
- Track object creation via `command()` responses
- Cache visible objects in `_applet_objects`
- Validate references against cached set

### Phase 2: Layer-Based Scoping (Planned)
- Extract layer information from construction protocol
- Group objects by layer in the dependency graph
- Validate references respect layer visibility

### Phase 3: Scope Tree Navigation (Future)
- Build a scope tree mirroring dependency relationships
- Support queries like "all objects derived from A" or "all objects in scope of B"
- Enable partial construction extraction respecting scope

## Type System (Future)

GeoGebra's implicit types should be validated:

```python
# Type hierarchy
GeometricObject:
  ├─ Point
  ├─ Line (variants: segment, ray, line)
  ├─ Circle
  ├─ Polygon
  ├─ Conic
  └─ ...

# Commands expect specific types
Circle(center: Point, radius: Number | Point) -> Circle
Polygon(points: List[Point]) -> Polygon
Distance(obj1: GeometricObject, obj2: GeometricObject) -> Number
```

## Data Structures

### ObjectMetadata
```python
class ObjectMetadata:
    name: str           # 'A', 'circle1', etc.
    type: str          # 'point', 'line', 'circle', etc.
    layer: int         # 0-9 (visibility group)
    command: str       # Creation command string
    dependencies: set  # {objects_this_depends_on}
    created_at: int    # Construction step index
```

### ScopeContext
```python
class ScopeContext:
    visible_objects: set  # Objects visible in current scope
    visible_layers: set   # Visible layer numbers
    parent_scope: ScopeContext | None
```

## Validation Rules (Progressive)

### Current (Phase 1)
- ✅ Object existence: referenced object is in applet

### Planned (Phase 2)
- ⏳ Layer visibility: object's layer is visible
- ⏳ Type compatibility: command argument matches expected type
- ⏳ Arity checking: correct number of arguments

### Future (Phase 3)
- ⏳ Scope accessibility: object is in accessible scope
- ⏳ Circularity detection: prevent circular dependencies
- ⏳ Reachability: ensure all object references are derivable

## Integration Points

### GeoGebra XML Protocol
- Layer information available in `<construction>` element
- Object metadata in `<element>` tags with `type` and `layer` attributes
- Command strings in `Command` attribute

### Parser Integration
- `ggb_parser.parse()` can extract metadata
- Store metadata in DataFrame alongside protocol
- Use for scope-aware subgraph extraction

### Validation in command()
```python
async def command(self, c):
    if self.check_semantics:
        # Existing: object existence
        validate_object_existence(c)
        
        # Phase 2: layer visibility
        # validate_layer_visibility(c)
        
        # Phase 2: type compatibility
        # validate_command_types(c)
        
    await self.comm.send_recv(...)
```

## Error Handling

### GeoGebraScopeError (Future)
```python
class GeoGebraScopeError(GeoGebraSemanticsError):
    """Object reference violates scope rules."""
    def __init__(self, command, message, out_of_scope_objects=None):
        super().__init__(command, message, out_of_scope_objects)
```

## Testing Strategy

1. **Unit tests**: Scope tree construction from sample protocols
2. **Integration tests**: Command validation in scoped contexts
3. **Edge cases**: 
   - Empty construction
   - Single object (no dependencies)
   - Circular-like references (e.g., reflected points)
   - Dynamic layer changes

## See Also

- [validation_strategy.md](validation_strategy.md) - Current validation approach
- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system design
- [scoping.md](scoping.md) - Educational philosophy on scoping
