"""
GGBLab — the Julia package form of ggblab's Julia host (2026-09-30; the name is provisional until 2.0.0, C7).

The package is the directory `julia/` of the ggblab repository: the same two source files that the Python wheel ships
(`julia/host/html_host.jl`, `julia/host/ggb_macro.jl`) wrapped in one module, so that

    using Pkg; Pkg.add(url="https://github.com/moyhig-ecs/ggblab", rev="v2", subdir="julia")
    using GGBLab

is the whole install on the Julia side. The Python package `ggblab` must still be installed where the kernel's
jupyter_server runs: it carries the mailbox (`ggblab.host.relay`), the mount JavaScript and the parser that `ggb"…"`
calls through PythonCall. Nothing in this file is new behaviour — it is the two modules, re-exported.
"""
module GGBLab

include(joinpath(@__DIR__, "..", "host", "html_host.jl"))   # module GGBLabHost  (the 8 verbs over the HTTP mailbox)
include(joinpath(@__DIR__, "..", "host", "ggb_macro.jl"))   # module GGBLabMacro (`ggb"…"`; `import ..GGBLabHost` resolves to GGBLab.GGBLabHost)

using .GGBLabHost, .GGBLabMacro

# the host façade
export GeoGebra, mount, command, xml, set_xml, delete, value, new_construction, kind, listen, unlisten, events, errors, wait_update, request
# the string macro and its helpers
export @ggb_str, parse_ggb, apply, plan, to_ggb, labels, flatten_labels, ClosedWorldError

end # module
