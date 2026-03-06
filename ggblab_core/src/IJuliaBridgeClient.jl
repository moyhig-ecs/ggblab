"""
`IJuliaBridgeClient` package entry point.

This thin wrapper includes the living source `ijulia_client.jl` in the
parent directory so the module defined there becomes available as a
registered package when the package path is added via `Pkg.develop`.

Note: Keeping the authoritative source at `ggblab_core/ijulia_client.jl`
avoids duplication while enabling `using IJuliaBridgeClient` after a
`Pkg.develop(path=...)` call in Julia.
"""

module IJuliaBridgeClient

include(joinpath(@__DIR__, "..", "ijulia_client.jl"))

end # module
