"""Shim: include package-local OOBClient implementation and run as script.

This file delegates to `julia/GeoGebra.jl/src/OOBClient.jl`. When invoked
directly it starts the client and prints messages; when included you can
`using .OOBClient` after the include in order to use the module API.
"""

include(joinpath(@__DIR__, "..", "julia", "GeoGebra.jl", "src", "OOBClient.jl"))
using .OOBClient
if abspath(PROGRAM_FILE) == @__FILE__
    host, port = OOBClient.parse_args()
    println("Connecting to $host:$port...")
    t, stop_ref = OOBClient.start_oob_client(host, port)

    # Default printer: mirror the Python client by printing messages to stdout
    on(OOBClient.messages) do msg
        try
            if isa(msg, Dict)
                println(JSON.json(msg))
            else
                println(msg)
            end
        catch
            println(msg)
        end
    end

    wait(t)
end
