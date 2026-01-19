# SymPy Geometry Integration Design

This document specifies the integration of SymPy's Geometry module with ggblab, enabling symbolic computation, exact calculations, and bidirectional code generation between GeoGebra and SymPy representations.

## 1. Design Rationale

### The SymPy Opportunity

SymPy's Geometry module provides:
- **Exact symbolic computation**: Intersections, tangents, perpendiculars computed algebraically
- **Analytical solvers**: Constraint solving, locus equations, envelope curves
- **Proof verification**: Symbolic validation of geometric properties (collinearity, concyclicity)
- **Code generation**: Construction steps reproducible as Python source

### Complementary to GeoGebra

| Capability | GeoGebra | SymPy | ggblab Bridge |
|-----------|----------|-------|--------------|
| **2D/3D visualization** | ✅ Native, fast | ❌ Plotting only | GeoGebra renders; SymPy computes |
| **Exact symbolic geometry** | ⚠️ Limited | ✅ Full | SymPy for algebra; GeoGebra for display |
| **Numerical approximation** | ✅ Built-in | ✅ Via float() | Use whichever is natural |
| **Proof / verification** | ❌ No | ✅ Theorem proving | SymPy verifies construction correctness |
| **Code reproducibility** | ❌ XML-based | ✅ Python code | Export construction as importable module |
| **Animation** | ⚠️ Scripting | ❌ No native | Manim bridge (future tier) |

### Educational Value

**Tier 3 Learning Outcomes**:
1. **Exact computation**: Understand why numerical approximation is insufficient (e.g., proving collinearity exactly, not approximately)
2. **Code reproducibility**: "This construction is Python code; commit it; version it; share it"
3. **Proof culture**: Symbolic verification replaces heuristic checking
4. **Hybrid workflows**: When to use exact (SymPy) vs. approximate (GeoGebra) methods

---

## 2. Architecture

### Module Structure

```
ggblab/sympy_bridge.py
├── Conversion Layer
│   ├── geogrebra_to_sympy()        # XML → SymPy geometry objects
│   ├── sympy_to_geogrebra()        # SymPy → GeoGebra Base64
│   └── point_list_conversion()     # Numpy arrays ↔ SymPy Point
│
├── Symbolic Verification
│   ├── verify_collinearity()       # Are these points collinear?
│   ├── verify_concyclicity()       # Do these points lie on a circle?
│   ├── verify_perpendicular()      # Are these lines perpendicular?
│   ├── verify_parallel()           # Are these lines parallel?
│   └── verify_property()           # Generic property verification
│
├── Code Generation
│   ├── to_python_code()            # Construction → reproducible Python module
│   ├── to_construction_string()    # Construction steps → human-readable text
│   └── CodegenContext              # Track variable names, symbol definitions
│
├── Advanced Solvers
│   ├── solve_locus()               # Compute locus equation(s) for point set
│   ├── solve_envelope()            # Compute envelope of curve family
│   └── solve_constraint()          # Satisfy geometric constraints symbolically
│
└── Integration Utilities
    ├── extract_geometry()          # Parse GeoGebra XML; identify geometric objects
    ├── find_dependencies()         # Which SymPy objects depend on which?
    └── parametric_sweep_sympy()    # Substitute parameter values into symbolic expressions
```

### Data Flow

```
User workflow:
1. GeoGebra construction (interactive design)
2. ggblab: geogrebra_to_sympy()
   → Extract XML; parse objects; build SymPy Geometry AST
3. SymPy computation (exact algebra)
   → solve_locus(), verify_property(), etc.
4. Results:
   a. Symbolic expressions (back to user for inspection)
   b. Numeric approximations (send to GeoGebra for visualization)
   c. Python code (export as module)
5. GeoGebra visualization (native rendering)
```

---

## 3. Conversion Layer

### 3.1 GeoGebra XML → SymPy

**Goal**: Parse GeoGebra XML construction; build equivalent SymPy Geometry objects.

#### Algorithm

1. **Extract object definitions** from GeoGebra XML
   - Points: `<element type="point">` → extract coordinates
   - Lines: `<element type="line">` → extract line equation or two defining points
   - Circles: `<element type="circle">` → extract center + radius
   - Polygons: `<element type="polygon">` → extract vertex list

2. **Build dependency graph**
   - Identify which objects depend on others (e.g., line from two points)
   - Order objects topologically for reconstruction

3. **Instantiate SymPy objects**
   ```python
   from sympy.geometry import Point, Line, Circle, Polygon, Triangle

   # Example: GeoGebra point with coordinates (3.5, 2.1)
   sympy_point = Point(3.5, 2.1)

   # Example: GeoGebra line through two points
   sympy_line = Line(Point(0, 0), Point(1, 1))

   # Example: GeoGebra circle center (1, 2), radius 3
   sympy_circle = Circle(Point(1, 2), 3)
   ```

4. **Handle parametric objects**
   - If construction includes symbolic parameters (e.g., slider `a` in GeoGebra)
   - Create SymPy symbols: `a = symbols('a')`
   - Substitute into geometric definitions

#### Implementation Sketch

```python
def geogrebra_to_sympy(ggb_xml: str) -> Dict[str, Any]:
    """
    Parse GeoGebra XML; return SymPy Geometry objects and metadata.
    
    Args:
        ggb_xml: GeoGebra .ggb file (unzipped XML)
    
    Returns:
        {
            'objects': {
                'point_A': Point(1, 2),
                'line_AB': Line(...),
                'circle_C': Circle(...),
            },
            'parameters': {'a': symbols('a'), 'b': symbols('b')},
            'dependencies': {'line_AB': ['point_A', 'point_B']},
            'metadata': {'creator': '...', 'timestamp': '...'}
        }
    """
    root = ET.fromstring(ggb_xml)
    objects = {}
    parameters = {}
    dependencies = {}
    
    # Extract all geometric elements
    for element in root.findall('.//element'):
        obj_type = element.get('type')
        obj_name = element.get('name')
        
        if obj_type == 'point':
            coord_x = float(element.find('x').text)
            coord_y = float(element.find('y').text)
            objects[obj_name] = Point(coord_x, coord_y)
        
        elif obj_type == 'line':
            # Line defined by two points
            point_a = element.get('point_a')
            point_b = element.get('point_b')
            dependencies[obj_name] = [point_a, point_b]
            objects[obj_name] = Line(objects[point_a], objects[point_b])
        
        elif obj_type == 'circle':
            # Circle: center + radius
            center_name = element.get('center')
            radius_val = float(element.find('radius').text)
            dependencies[obj_name] = [center_name]
            objects[obj_name] = Circle(objects[center_name], radius_val)
        
        # ... handle other types (polygon, slider, etc.)
    
    return {
        'objects': objects,
        'parameters': parameters,
        'dependencies': dependencies,
    }
```

### 3.2 SymPy → GeoGebra Base64

**Goal**: Convert SymPy geometric objects back to GeoGebra-compatible format (Base64 .ggb file).

#### Algorithm

1. **Construct GeoGebra XML** from SymPy objects
   - For each Point, Line, Circle, etc., generate corresponding `<element>` tags
   - Compute numeric approximations (SymPy → float)

2. **Build complete .ggb structure**
   - XML document with `<construction>`, `<objects>`, etc.
   - Include metadata (modification time, etc.)

3. **Compress to .ggb** (ZIP archive)
   ```python
   import zipfile
   
   zf = zipfile.ZipFile('output.ggb', 'w')
   zf.writestr('geogebra.xml', ggb_xml)
   zf.close()
   
   # Convert to Base64 for GeoGebra Applet embedding
   with open('output.ggb', 'rb') as f:
       base64_str = base64.b64encode(f.read()).decode('utf-8')
   ```

#### Implementation Sketch

```python
def sympy_to_geogrebra(sympy_objects: Dict[str, Any]) -> str:
    """
    Convert SymPy geometric objects to GeoGebra Base64.
    
    Args:
        sympy_objects: {
            'point_A': Point(1, 2),
            'line_AB': Line(...),
            ...
        }
    
    Returns:
        Base64-encoded .ggb file ready for GeoGebra Applet
    """
    # Build GeoGebra XML
    root = ET.Element('geogebra')
    construction = ET.SubElement(root, 'construction')
    
    for name, obj in sympy_objects.items():
        element = ET.SubElement(construction, 'element')
        element.set('name', name)
        
        if isinstance(obj, Point):
            element.set('type', 'point')
            ET.SubElement(element, 'x').text = str(float(obj.x))
            ET.SubElement(element, 'y').text = str(float(obj.y))
        
        elif isinstance(obj, Line):
            element.set('type', 'line')
            # Store line equation or two-point definition
            ...
        
        elif isinstance(obj, Circle):
            element.set('type', 'circle')
            center = obj.center
            radius = obj.radius
            ET.SubElement(element, 'center').text = f"{float(center.x)},{float(center.y)}"
            ET.SubElement(element, 'radius').text = str(float(radius))
    
    # Serialize, compress, encode
    ggb_xml = ET.tostring(root, encoding='unicode')
    
    with tempfile.NamedTemporaryFile(suffix='.ggb', delete=False) as tmp:
        with zipfile.ZipFile(tmp.name, 'w') as zf:
            zf.writestr('geogebra.xml', ggb_xml)
        tmp_path = tmp.name
    
    with open(tmp_path, 'rb') as f:
        base64_str = base64.b64encode(f.read()).decode('utf-8')
    
    os.remove(tmp_path)
    return base64_str
```

### 3.3 Point List Conversion

**Goal**: Convert between NumPy arrays (Python, GeoGebra interchange format) and SymPy Points.

```python
def numpy_to_sympy_points(arr: np.ndarray) -> List[Point]:
    """
    Convert Nx2 or Nx3 NumPy array to list of SymPy Points.
    
    Args:
        arr: Shape (N, 2) for 2D, (N, 3) for 3D
    
    Returns:
        List of SymPy Point objects
    """
    points = []
    for row in arr:
        if len(row) == 2:
            points.append(Point(row[0], row[1]))
        elif len(row) == 3:
            points.append(Point(row[0], row[1], row[2]))
    return points

def sympy_points_to_numpy(points: List[Point]) -> np.ndarray:
    """
    Convert list of SymPy Points to NumPy array.
    
    Returns:
        Shape (N, 2) or (N, 3) depending on dimension
    """
    coords = [tuple(float(c) for c in p.args) for p in points]
    return np.array(coords)
```

---

## 4. Symbolic Verification

### 4.1 Collinearity Verification

**Goal**: Prove (or disprove) that a set of points are collinear.

```python
def verify_collinearity(points: List[Point]) -> Tuple[bool, Optional[str]]:
    """
    Verify that all points lie on the same line.
    
    Args:
        points: List of SymPy Point objects
    
    Returns:
        (is_collinear, proof_expression)
        - is_collinear: True if provably collinear; False otherwise
        - proof_expression: Symbolic proof (e.g., determinant = 0)
    """
    if len(points) < 2:
        return True, "Fewer than 2 points; trivially collinear"
    
    # Use determinant: points are collinear iff det([[x1, y1, 1], [x2, y2, 1], ...]) = 0
    p1, p2 = points[0], points[1]
    line = Line(p1, p2)
    
    for p in points[2:]:
        if p not in line:
            return False, f"Point {p} is not on line through {p1} and {p2}"
    
    return True, f"All points lie on line: {line.equation()}"

# Example usage:
from sympy.geometry import Point
pts = [Point(0, 0), Point(1, 1), Point(2, 2)]
is_collinear, proof = verify_collinearity(pts)
print(proof)  # "All points lie on line: ..."
```

### 4.2 Concyclicity Verification

**Goal**: Prove that points lie on the same circle.

```python
def verify_concyclicity(points: List[Point]) -> Tuple[bool, Optional[str]]:
    """
    Verify that all points lie on the same circle.
    
    Returns:
        (is_concyclic, circle_or_proof)
    """
    if len(points) < 3:
        return True, f"Fewer than 3 points; any two points determine infinite circles"
    
    p1, p2, p3 = points[0], points[1], points[2]
    
    try:
        circle = Circle(p1, p2, p3)
    except:
        return False, "First three points do not determine a circle (collinear)"
    
    for p in points[3:]:
        if p not in circle:
            return False, f"Point {p} is not on circle: {circle}"
    
    return True, f"All points lie on circle: center={circle.center}, radius={circle.radius}"
```

### 4.3 Perpendicularity Verification

```python
def verify_perpendicular(line1: Line, line2: Line) -> Tuple[bool, str]:
    """
    Verify that two lines are perpendicular.
    
    Returns:
        (is_perpendicular, explanation)
    """
    if line1.is_perpendicular(line2):
        return True, f"{line1} ⊥ {line2}"
    else:
        # Compute angle
        slope1 = line1.slope
        slope2 = line2.slope
        return False, f"Slopes: {slope1} and {slope2} (not negative reciprocals)"
```

### 4.4 Generic Verification Interface

```python
def verify_property(property_name: str, *objects) -> Tuple[bool, str]:
    """
    Unified verification interface.
    
    Example:
        verify_property('collinear', point_A, point_B, point_C)
        verify_property('perpendicular', line_AB, line_CD)
        verify_property('concyclic', point_A, point_B, point_C, point_D)
    """
    if property_name == 'collinear':
        return verify_collinearity(list(objects))
    elif property_name == 'concyclic':
        return verify_concyclicity(list(objects))
    elif property_name == 'perpendicular':
        return verify_perpendicular(objects[0], objects[1])
    elif property_name == 'parallel':
        return verify_parallel(objects[0], objects[1])
    else:
        raise ValueError(f"Unknown property: {property_name}")
```

---

## 5. Code Generation

### 5.1 Construction → Reproducible Python Code

**Goal**: Export geometric construction as importable Python module.

```python
def to_python_code(sympy_objects: Dict[str, Any], 
                   output_file: Optional[str] = None) -> str:
    """
    Generate Python code that reconstructs the geometric objects.
    
    Args:
        sympy_objects: {'point_A': Point(...), 'line_AB': Line(...), ...}
        output_file: If provided, write generated code to file
    
    Returns:
        Python source code as string
    """
    lines = [
        "# Auto-generated construction code",
        "# Export from ggblab + GeoGebra",
        "",
        "from sympy.geometry import Point, Line, Circle, Triangle, Polygon",
        "from sympy import symbols, solve, Eq",
        "",
    ]
    
    # Add symbolic parameters
    params = [name for name, obj in sympy_objects.items() 
              if isinstance(obj, symbols.__class__)]
    if params:
        lines.append(f"a, b, c, ... = symbols('a b c ...')  # Add parameters as needed")
        lines.append("")
    
    # Add object definitions
    for name, obj in sympy_objects.items():
        if isinstance(obj, Point):
            lines.append(f"{name} = Point({obj.x}, {obj.y})")
        elif isinstance(obj, Line):
            # Try to identify defining points
            lines.append(f"{name} = Line({obj.p1}, {obj.p2})")
        elif isinstance(obj, Circle):
            lines.append(f"{name} = Circle({obj.center}, {obj.radius})")
        elif isinstance(obj, Triangle):
            points_str = ", ".join(str(p) for p in obj.vertices)
            lines.append(f"{name} = Triangle({points_str})")
    
    code = "\n".join(lines)
    
    if output_file:
        with open(output_file, 'w') as f:
            f.write(code)
    
    return code

# Example output:
"""
from sympy.geometry import Point, Line, Circle

A = Point(0, 0)
B = Point(1, 1)
C = Point(2, 0)
line_AB = Line(A, B)
circle_circumscribed = Circle(A, B, C)
"""
```

### 5.2 Construction Steps → Human-Readable Text

```python
def to_construction_string(sympy_objects: Dict[str, Any],
                          dependencies: Dict[str, List[str]]) -> str:
    """
    Generate a human-readable description of the construction.
    
    Returns:
        Markdown-formatted construction steps
    """
    lines = ["# Construction Steps", ""]
    
    # Topological sort of objects
    topo_order = topological_sort(dependencies)
    
    for obj_name in topo_order:
        obj = sympy_objects[obj_name]
        deps = dependencies.get(obj_name, [])
        
        if isinstance(obj, Point):
            if deps:
                lines.append(f"1. **{obj_name}**: Point (defined by: {', '.join(deps)})")
            else:
                lines.append(f"1. **{obj_name}**: Point at ({obj.x}, {obj.y})")
        
        elif isinstance(obj, Line):
            if deps:
                lines.append(f"2. **{obj_name}**: Line through points {deps[0]} and {deps[1]}")
        
        # ... other types
    
    return "\n".join(lines)
```

---

## 6. Advanced Solvers

### 6.1 Locus Computation

**Goal**: Given a point whose position depends on a parameter, compute the locus (curve) it traces.

**Educational Context**: "As slider `t` varies from 0 to 2π, point P traces a circle. Prove it."

```python
def solve_locus(point: Point, parameter: Symbol, 
                param_range: Tuple[float, float]) -> Optional[Curve]:
    """
    Compute the locus of a point as a parameter varies.
    
    Args:
        point: SymPy Point with symbolic parameter (e.g., Point(cos(t), sin(t)))
        parameter: The varying parameter (e.g., t)
        param_range: (t_min, t_max)
    
    Returns:
        Locus equation (e.g., "x^2 + y^2 = 1" for unit circle)
    """
    x, y = symbols('x y')
    
    # Eliminate parameter: find relationship between x and y
    # If point = (cos(t), sin(t)), then x = cos(t), y = sin(t)
    # Eliminate t: x^2 + y^2 = 1
    
    point_x = point.x
    point_y = point.y
    
    # Solve for parameter in terms of x
    eq1 = Eq(x, point_x)
    eq2 = Eq(y, point_y)
    
    # Eliminate parameter
    locus_eq = eliminate([eq1, eq2], [parameter])
    
    return locus_eq

# Example:
from sympy import cos, sin, symbols, Eq, eliminate
t = symbols('t', real=True)
P = Point(cos(t), sin(t))
locus = solve_locus(P, t, (0, 2*pi))
print(locus)  # x^2 + y^2 = 1 (unit circle)
```

### 6.2 Envelope Computation

**Goal**: Compute the envelope of a family of curves (e.g., tangent lines to a parabola).

```python
def solve_envelope(curve_family: Callable,
                  parameter: Symbol) -> Optional[Curve]:
    """
    Compute the envelope of a family of curves.
    
    Args:
        curve_family: Function F(x, y, t) defining the family of curves
        parameter: The family parameter (e.g., t)
    
    Returns:
        Envelope curve equation
    
    Mathematical background:
    The envelope of F(x, y, t) = 0 is found by solving:
      F(x, y, t) = 0
      ∂F/∂t = 0
    and eliminating t.
    """
    x, y = symbols('x y')
    
    # Compute partial derivative w.r.t. parameter
    F = curve_family(x, y, parameter)
    dF_dt = diff(F, parameter)
    
    # Solve for envelope
    # Result: envelope equation in x, y
    envelope_eq = eliminate([F, dF_dt], [parameter])
    
    return envelope_eq
```

### 6.3 Constraint Solving

**Goal**: Find points satisfying geometric constraints (e.g., "point on line AND distance 3 from another point").

```python
def solve_constraint(constraints: List[Eq], 
                    unknowns: List[Symbol]) -> List[Tuple]:
    """
    Solve a system of geometric constraints.
    
    Args:
        constraints: List of SymPy Equations (e.g., [Eq(distance(P, Q), 3), ...])
        unknowns: Variables to solve for
    
    Returns:
        List of solution tuples
    
    Example:
        # Find point P on line y=x at distance 5 from origin
        from sympy import sqrt
        x, y = symbols('x y')
        constraints = [
            Eq(y, x),                           # On line y=x
            Eq(sqrt(x**2 + y**2), 5)            # Distance 5 from origin
        ]
        solutions = solve_constraint(constraints, [x, y])
        # solutions = [(5/sqrt(2), 5/sqrt(2)), (-5/sqrt(2), -5/sqrt(2))]
    """
    solutions = solve(constraints, unknowns)
    return solutions if isinstance(solutions, list) else [solutions]
```

---

## 7. Jupyter Integration

### 7.1 Verification in Notebooks

```python
# In Jupyter cell:
from ggblab.sympy_bridge import (
    geogrebra_to_sympy, verify_property, to_python_code
)

# Load GeoGebra construction
ggb_data = await ggb.function("getBase64", [])  # Get GeoGebra Base64
sympy_objs = geogrebra_to_sympy(ggb_data)

# Verify property
is_correct, proof = verify_property('collinear', 
                                    sympy_objs['A'], 
                                    sympy_objs['B'], 
                                    sympy_objs['C'])
print(f"Collinear? {is_correct}")
print(f"Proof: {proof}")

# Export as code
code = to_python_code(sympy_objs, output_file='my_construction.py')
print("Construction exported to my_construction.py")
```

### 7.2 Interactive Verification Dashboard

```python
# Cell in Jupyter notebook
from ipywidgets import Button, Output, VBox
from IPython.display import display, Markdown

verify_button = Button(description="Verify Construction")
output_area = Output()

async def on_verify_click(b):
    with output_area:
        # Fetch GeoGebra data
        ggb_data = await ggb.function("getBase64", [])
        sympy_objs = geogrebra_to_sympy(ggb_data)
        
        # Run verification checks
        checks = [
            ('Collinear (A, B, C)', verify_property('collinear', 
                                                      sympy_objs['A'], 
                                                      sympy_objs['B'], 
                                                      sympy_objs['C'])),
            ('Concyclic (A, B, C, D)', verify_property('concyclic', 
                                                        sympy_objs['A'], 
                                                        sympy_objs['B'], 
                                                        sympy_objs['C'], 
                                                        sympy_objs['D'])),
        ]
        
        # Display results
        for check_name, (is_true, proof) in checks:
            status = "✓" if is_true else "✗"
            display(Markdown(f"{status} **{check_name}**: {proof}"))

verify_button.on_click(on_verify_click)
display(VBox([verify_button, output_area]))
```

---

## 8. Implementation Roadmap

### v1.1 (SymPy Bridge: Basic)

- [ ] `geogrebra_to_sympy()`: Parse GeoGebra XML → SymPy objects
- [ ] `sympy_to_geogrebra()`: Reverse conversion
- [ ] Point list conversion utilities
- [ ] Unit tests: conversion round-trip consistency
- [ ] Example notebook: "GeoGebra ↔ SymPy Conversion"

### v1.2 (Symbolic Verification)

- [ ] `verify_collinearity()`, `verify_concyclicity()`, etc.
- [ ] Generic `verify_property()` interface
- [ ] Proof generation and explanation
- [ ] Example notebook: "Proving Geometric Properties Symbolically"
- [ ] Interactive Jupyter dashboard for property checking

### v1.3 (Code Generation)

- [ ] `to_python_code()`: Export construction as importable module
- [ ] `to_construction_string()`: Human-readable steps
- [ ] Version control integration (commit construction code to Git)
- [ ] Example notebook: "Reproducible Constructions as Code"

### v1.4 (Advanced Solvers)

- [ ] `solve_locus()`: Parametric curve elimination
- [ ] `solve_envelope()`: Family of curves envelope
- [ ] `solve_constraint()`: Geometric constraint solving
- [ ] Example notebook: "Loci and Envelope Curves"

### v1.5 (Manim + SymPy Integration)

- [ ] Export SymPy geometry to manim animation code
- [ ] Symbolic transformations as manim Animations
- [ ] Locus visualization (trace curve as parameter varies)

---

## 9. Success Criteria

### v1.1 Success

- [ ] Round-trip conversion: GeoGebra → SymPy → GeoGebra preserves geometry
- [ ] SymPy objects preserve symbolic parameters (e.g., slider values)
- [ ] Example constructions (triangle, circle, square) convert flawlessly

### v1.2 Success

- [ ] Educators report: "Students understand *why* constructions work (symbolic proof)"
- [ ] Property verification scales to 20+ point constructions without timeout
- [ ] Proof explanations are clear and actionable for classroom use

### v1.3 Success

- [ ] Exported Python code is clean, readable, and matches original construction
- [ ] Constructions can be version-controlled and reviewed (code review culture)

### v1.4 Success

- [ ] Locus computation is exact for algebraic curves (circle, ellipse, parabola, etc.)
- [ ] Envelope computation enables teaching advanced calculus concepts

### Overall Educational Impact

- [ ] 3+ lesson modules leveraging SymPy integration
- [ ] Adoption by 1+ institution (use in actual geometry course)
- [ ] Community contribution: extension examples for other geometric properties

---

## 10. Related Resources

### SymPy Geometry Module
- Documentation: https://docs.sympy.org/latest/modules/geometry/
- Key classes: `Point`, `Line`, `Circle`, `Triangle`, `Polygon`, `Ellipse`, `Parabola`
- Theorem proving: `Triangle.is_isoceles()`, `is_equilateral()`, etc.

### GeoGebra XML Format
- GeoGebra File Format Specification: https://wiki.geogebra.org/en/Reference:GeoGebra_File_Format
- Object types and properties: https://wiki.geogebra.org/en/Category:GeoGebra_Applet_Embed

### Educational Context
- Constructivism in geometry education: Emphasis on *why* constructions work
- Symbolic proof culture: Moving beyond numerical verification
- Open-source STEM pipeline: From interactive exploration (GeoGebra) to publishable content (Manim)

---

## 11. Design Decisions

### Why Not Just SymPy.plotting?

SymPy's plotting is functional but slow and not suitable for interactive use. GeoGebra's native rendering is far superior. The bridge delegates visualization to GeoGebra.

### Why Layered Verification?

Generic `verify_property()` interface allows future extension. Specific verifiers (collinearity, etc.) are optimized for their domain.

### Why Code Generation?

Reproducibility + version control + educational value: "This construction is a Python module; commit it; share it."

### Why Constraint Solving?

Enables advanced problems: "Find all points satisfying constraints A and B." Foundational for optimization, feasibility analysis, parametric design.

---

## Summary

SymPy integration transforms ggblab from a **communication bridge** into a **symbolic computation + code generation platform** for geometric education. The tight coupling with GeoGebra's visualization and Manim's animation creates a unified pipeline:

$$\text{GeoGebra (design)} \xrightarrow{\text{extract}} \text{SymPy (prove)} \xrightarrow{\text{codegen}} \text{Python (reproducible)}$$

$$\xrightarrow{\text{export}} \text{Manim (animate)} \xrightarrow{\text{render}} \text{Video (teach)}$$

This realizes the Wolfram `GeometricScene` vision in the open-source ecosystem.
