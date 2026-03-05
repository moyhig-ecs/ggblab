# ijulia_sync_call.jl
# Helper to perform synchronous function/command calls over a control comm
# using IJulia.send (avoids using comm.send which some IJulia Comm types lack).

try
    using IJulia, JSON, UUIDs
catch e
    @warn "Required packages missing: $e"
end

# Robust send helper used by sync callers
function _send_payload(comm, payload_str)
    # Preferred path observed in some IJulia builds: IJulia.send_comm with parsed Dict
    try
        parsed = try JSON.parse(payload_str) catch; nothing end
        if parsed !== nothing
            try
                Main.IJulia.send_comm(comm, parsed)
                return true
            catch e
                @debug "IJulia.send_comm attempt failed: $e"
            end
        end
    catch e
        @debug "IJulia.send_comm parse/attempt failed: $e"
    end

    # Next: try IJulia.send(comm, str) (may fail on some builds)
    try
        Main.IJulia.send(comm, payload_str)
        return true
    catch e
        @debug "IJulia.send attempt failed: $e"
    end

    # Try an underlying primary object's send (only if it's callable)
    try
        if hasproperty(comm, :primary)
            prim = getproperty(comm, :primary)
            if prim !== nothing && hasproperty(prim, :send)
                getproperty(prim, :send)(payload_str)
                return true
            end
        end
    catch e
        @debug "comm.primary.send attempt failed: $e"
    end

    # Last resort: try CommManager.send if present
    try
        Main.IJulia.CommManager.send(comm, payload_str)
        return true
    catch e
        @debug "IJulia.CommManager.send attempt failed: $e"
    end

    return false
end

const _SYNC_REPLIES = Dict{Any,Dict{String,Channel{Any}}}()

function _ensure_reply_map(comm)
    key = objectid(comm)
    if !haskey(_SYNC_REPLIES, key)
        _SYNC_REPLIES[key] = Dict{String,Channel{Any}}()
        # attach on_msg once
        try
            comm.on_msg(function(m)
                try
                    data = m["content"]["data"]
                    payload = isa(data, String) ? JSON.parse(data) : data
                    id = get(payload, "id", nothing)
                    if id !== nothing && haskey(_SYNC_REPLIES[key], id)
                        put!(_SYNC_REPLIES[key][id], payload)
                    else
                        @info "ijulia_sync_call unsolicited payload" payload=payload
                    end
                catch e
                    @warn "sync on_msg handler error: $e"
                end
            end)
        catch e
            @warn "Failed to attach sync on_msg: $e"
        end
    end
    return _SYNC_REPLIES[key]
end

"""
call_function_sync(comm, name, args; timeout=5.0)

Call a frontend-exposed function and wait for a reply. Uses `IJulia.send` to
avoid `FieldError` when `comm.send` is not available.
Returns the parsed reply Dict on success, or `nothing` on error/timeout.
"""
function call_function_sync(comm, name::AbstractString, args::AbstractVector; timeout::Real = 5.0)
    if comm === nothing
        @warn "call_function_sync: comm is nothing"
        return nothing
    end
    replies = _ensure_reply_map(comm)
    id = string(UUIDs.uuid4())
    ch = Channel{Any}(1)
    replies[id] = ch
    req = Dict("type" => "function", "id" => id, "payload" => Dict("name" => name, "args" => args))
    payload = JSON.json(req)
    # Send with multiple fallbacks because IJulia builds differ
    ok = _send_payload(comm, payload)
    if !ok
        @warn "call_function_sync: all send attempts failed for id=$id"
        delete!(replies, id)
        return nothing
    end
    t0 = time()
    while true
        if isready(ch)
            resp = take!(ch)
            delete!(replies, id)
            return resp
        elseif time() - t0 > timeout
            @warn "call_function_sync timeout waiting for reply id=$id"
            delete!(replies, id)
            return nothing
        else
            sleep(0.01)
        end
    end
end

"""
call_command_sync(comm, command, ; timeout=5.0)

Send a command to the applet and wait for 'created' reply similarly.
"""
function call_command_sync(comm, command; timeout::Real = 5.0)
    if comm === nothing
        @warn "call_command_sync: comm is nothing"
        return nothing
    end
    replies = _ensure_reply_map(comm)
    id = string(UUIDs.uuid4())
    ch = Channel{Any}(1)
    replies[id] = ch
    req = Dict("type" => "command", "id" => id, "payload" => command)
    payload = JSON.json(req)
    ok = _send_payload(comm, payload)
    if !ok
        @warn "IJulia: all send attempts failed for call_command_sync id=$id"
        delete!(replies, id)
        return nothing
    end
    t0 = time()
    while true
        if isready(ch)
            resp = take!(ch)
            delete!(replies, id)
            return resp
        elseif time() - t0 > timeout
            @warn "call_command_sync timeout waiting for reply id=$id"
            delete!(replies, id)
            return nothing
        else
            sleep(0.01)
        end
    end
end
