# ijulia_comm.jl
# Example IJulia comm proxy responder for ggblab
#
# Usage:
# 1. In a Julia REPL inside Jupyter (IJulia), `include("ijulia_comm.jl")`
# 2. This registers a comm target named "jupyter.ggblab" which will
#    receive frontend messages. The handler here echoes back a simple
#    ggblab-style reply JSON string.
#
# Note: IJulia's public API for comm targets may differ between versions.
# This file provides a conservative template using IJulia's lower-level
# `comm` support. If your IJulia version exposes helper functions like
# `IJulia.register_comm_target`, use those instead.

try
    using IJulia
    using JSON
catch e
    @warn "IJulia or JSON not available: $e"
end

module GGBlabIJuliaComm
export register_ggblab_comm, unregister_ggblab_comm

const TARGET_NAME = "jupyter.ggblab"
# store comm objects so we can close/unregister
const _active_comms = Dict{Any,Any}()

# Resolve IJulia/JSON modules from Main (IJulia may be loaded in the
# top-level IJulia environment rather than inside this module's scope).
const IJulia_mod = isdefined(Main, :IJulia) ? Main.IJulia : nothing
const JSON_mod = isdefined(Main, :JSON) ? Main.JSON : nothing

function _handle_open(comm, msg)
    # comm: an IJulia.Comm object
    # msg: open message dict
    @info "ggblab comm opened" target=TARGET_NAME
    # attach message handler
    try
        comm.on_msg((m) -> _handle_msg(comm, m))
    catch e
        @warn "Failed to attach on_msg handler: $e"
    end
    _active_comms[comm] = true
end

function _handle_msg(comm, msg)
    try
        # msg.content.data may be a JSON string; parse if needed
            data = msg["content"]["data"]
            if isa(data, String)
                if JSON_mod !== nothing
                    payload = JSON_mod.parse(data)
                else
                    # fallback: attempt to use Base.Meta.parse? not ideal
                    @warn "JSON not available in module scope; cannot parse incoming string"
                    return
                end
            else
                payload = data
            end
        # Expect payload to be a dict with 'type' and 'id'
        t = get(payload, "type", "")
        id = get(payload, "id", nothing)
        @info "ggblab received" type=t id=id

        # Example handlers: function / command
        if t == "function"
            name = payload["payload"]["name"]
            args = payload["payload"]["args"]
            # (Implement actual GeoGebra call bridging here)
            value = "simulated-result-for-" * string(name)
            reply = Dict("type" => "value", "id" => id, "payload" => Dict("value" => value))
        elseif t == "command"
            cmd = payload["payload"]
            # perform command (simulate)
            reply = Dict("type" => "created", "id" => id, "payload" => Dict("label" => "A"))
        else
            reply = Dict("type" => "error", "id" => id, "payload" => Dict("message" => "Unsupported type"))
        end

        # Send JSON-stringified reply in the same format frontend expects
        try
            if JSON_mod !== nothing
                comm.send(JSON_mod.json(reply))
            else
                # fallback: send string repr
                comm.send(string(reply))
            end
        catch e
            @warn "Failed to send reply via comm: $e"
        end
    catch e
        @warn "Error handling incoming comm message: $e"
    end
end

function register_ggblab_comm()
    # IJulia provides register(message_type, handler) for custom messages
    # but comm-target registration is handled via `IJulia.install_comm` in some versions.
    # We attempt to use lower-level API exposed as `IJulia.install_comm` if present.
    try
        if IJulia_mod !== nothing && hasproperty(IJulia_mod, :install_comm)
            IJulia_mod.install_comm(TARGET_NAME, _handle_open)
            @info "Registered comm target via IJulia.install_comm" target=TARGET_NAME
            return true
        elseif IJulia_mod !== nothing && hasproperty(IJulia_mod, :register_comm)
            # IJulia.register_comm(target, open_handler)
            try
                IJulia_mod.register_comm(TARGET_NAME, _handle_open)
                @info "Registered comm target via IJulia.register_comm" target=TARGET_NAME
                return true
            catch e
                @warn "IJulia.register_comm call failed: $e"
            end
        elseif IJulia_mod !== nothing && hasproperty(IJulia_mod, :register_comm_target)
            # hypothetical API
            IJulia_mod.register_comm_target(TARGET_NAME, _handle_open)
            @info "Registered comm target via IJulia.register_comm_target" target=TARGET_NAME
            return true
                else
                        @warn "IJulia does not appear to expose install_comm/register_comm_target; manual wiring required"
                        println("""
Manual wiring instructions (paste into the Julia kernel / REPL running IJulia):

using IJulia, JSON

const TARGET_NAME = "jupyter.ggblab"

function on_open(comm, msg)
    println("ggblab comm opened (manual)")
    # attach message handler
    comm.on_msg(function(m)
        data = m["content"]["data"]
        payload = isa(data, String) ? JSON.parse(data) : data
        id = get(payload, "id", nothing)
        # simple example handler: echo or simulate
        if get(payload, "type", "") == "function"
            value = "simulated-result-for-" * string(payload["payload"]["name"])
            reply = Dict("type" => "value", "id" => id, "payload" => Dict("value" => value))
        else
            reply = Dict("type" => "error", "id" => id, "payload" => Dict("message" => "unsupported type"))
        end
        comm.send(JSON.json(reply))
    end)
end

# If IJulia exposes register_comm, use it. Otherwise, run the on_open registration manually
if hasproperty(IJulia, :register_comm)
    IJulia.register_comm(TARGET_NAME, on_open)
    println("Registered manual handler via IJulia.register_comm(\"$TARGET_NAME\")")
else
    println("No automatic registration API detected. Define and call the snippet above to register a comm open handler.")
end

                        """
                        )
                        return false
        end
    catch e
        @warn "Failed to register comm target: $e"
        return false
    end
end

function unregister_ggblab_comm()
    try
        if IJulia_mod !== nothing && hasproperty(IJulia_mod, :remove_comm)
            IJulia_mod.remove_comm(TARGET_NAME)
            return true
        else
            @warn "IJulia does not expose remove_comm; unregister manually if needed"
            return false
        end
    catch e
        @warn "Failed to unregister comm target: $e"
        return false
    end
end

end # module

# Autoregister when included (optional)
try
    GGBlabIJuliaComm.register_ggblab_comm()
catch e
    @warn "Auto-register failed: $e"
end
