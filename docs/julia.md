# Julia

The Julia host is two files inside the installed Python package. The same server extension and the same JavaScript
serve the Python and the Julia kernel. The two files can be loaded by `include` from the installed Python package
(below), or as the Julia package `GGBLab` (the directory `julia/` of the repository; the name is provisional until 2.0.0):

```julia
using Pkg; Pkg.add(url="https://github.com/moyhig-ecs/ggblab", rev="v2", subdir="julia")
using GGBLab            # GeoGebra, command, …, ggb"…"
```

Either way the Python package `ggblab` must be installed for the Jupyter server that runs the kernel: it carries the
mailbox, the mount JavaScript and the parser. The package finds the JavaScript through that Python package (or through
`GGBLAB_MOUNT_JS`). `PythonCall` must point at the same Python: for a kernel started by Jupyter,
`JULIA_CONDAPKG_BACKEND=Null` and `JULIA_PYTHONCALL_EXE=python` in the kernel's environment do that.

| Needs | For |
|---|---|
| the Julia packages `JSON` and `IJulia` | the host |
| the Julia package `PythonCall` | the string macro (it calls the Python parser) |

```julia
host = strip(read(`python -c "import ggblab, pathlib; print(pathlib.Path(ggblab.__file__).parent / 'julia' / 'host')"`, String))
include(joinpath(host, "html_host.jl")); using .GGBLabHost

g = GeoGebra(appName="suite", showAlgebraInput=true)
g
```

```julia
command(g, "O = (0, 0)", "c1 = Circle(O, 1)", "A = (1, 0)", "c2 = Circle(A, 1)", "l1 = {Intersect(c1, c2)}", "a = Length(l1)")
value(g, "a")
```

```julia
include(joinpath(host, "ggb_macro.jl")); using .GGBLabMacro
ggb"""
A = (0, 0)
c = Circle(:A, 1)
"""g
```

The functions are those of the [ten verbs](verbs.md): `command`, `new_construction`, `delete`, `set_xml`, `xml`,
`value`, `kind`, `listen`, `png`, `svg`, and `events`, `errors`, `wait_update`, `unlisten`.

The module names (`GGBLabHost`, `GGBLabMacro`) may change before 2.0.0.
