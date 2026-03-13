"""Simple Julia OOB client to connect to a ggblab websocket server and
print incoming messages.

Usage:
  julia comm_bridge/oob_client.jl ws://localhost:12345
Or set environment variable GGB_WS_PORT to connect to localhost by port.
"""

try
    using Sockets
    using Observables
    using JSON
catch e
    @error "Sockets, Observables.jl and JSON.jl are required. Install with `import Pkg; Pkg.add([\"Observables\", \"JSON\"])`"
    rethrow(e)
end

# Determine host/port: accept `host:port` or just a port as first arg, or use ENV GGB_WS_PORT.
host = "127.0.0.1"
port = nothing

function parse_args()
    local_host = "127.0.0.1"
    local_port = nothing
    i = 1
    while i <= length(ARGS)
        a = ARGS[i]
        if startswith(a, "--port=")
            try
                local_port = parse(Int, split(a, '=', limit=2)[2])
            catch
            end
        elseif a == "--port" && i < length(ARGS)
            try
                local_port = parse(Int, ARGS[i+1])
            catch
            end
            i += 1
        elseif startswith(a, "--host=")
            local_host = split(a, '=', limit=2)[2]
        elseif a == "--host" && i < length(ARGS)
            local_host = ARGS[i+1]
            i += 1
        elseif occursin(':', a)
            parts = split(a, ':')
            local_host = parts[1]
            try
                local_port = parse(Int, parts[2])
            catch
            end
        else
            try
                local_port = parse(Int, a)
            catch
                local_host = a
            end
        end
        i += 1
    end
    return local_host, local_port
end

host, port = parse_args()
if port === nothing
    envp = get(ENV, "GGB_WS_PORT", nothing)
    if envp !== nothing
        port = parse(Int, envp)
    else
        port = 8765
    end
end

println("Connecting to $host:$port...")

# Observable carrying the latest message; users can subscribe handlers.
messages = Observable(nothing)

function _run_tcp_client(host::AbstractString, port::Integer, messages::Observable)
    while true
        try
            sock = connect(host, port)
            io = sock
                try
                    # request shared snapshot on connect
                    try
                        req = Dict("op" => "get_shared_snapshot")
                        write(io, JSON.json(req))
                        write(io, '\n')
                        flush(io)
                    catch e
                        @warn "Failed to request snapshot: $e"
                    end

                    local_seq = 0
                    local_objs = Dict{Any,Any}()

                    while true
                        line = readline(io)
                        if line === nothing
                            break
                        end
                        text = String(line)
                        parsed = try
                            JSON.parse(text)
                        catch
                            text
                        end

                        # handle snapshot / updates
                        try
                            if isa(parsed, Dict) && get(parsed, "type", nothing) == "shared_objects_snapshot"
                                local_seq = get(parsed, "seq", 0)
                                local_objs = get(parsed, "payload", Dict())
                                notify!(messages, parsed)
                                continue
                            elseif isa(parsed, Dict) && get(parsed, "type", nothing) == "shared_objects_update"
                                seq = get(parsed, "seq", 0)
                                payload = get(parsed, "payload", Dict())
                                if seq > local_seq
                                    for (k,v) in payload
                                        local_objs[k] = v
                                    end
                                    local_seq = seq
                                    notify!(messages, parsed)
                                    continue
                                else
                                    continue
                                end
                            end
                        catch e
                            @warn "Error processing shared_objects message: $e"
                        end

                        notify!(messages, parsed)
                    end
                catch e
                    @error "Error while reading from socket: $e"
                    notify!(messages, e)
                finally
                    try
                        close(sock)
                    catch
                    end
                end
        catch e
            @error "Connection failed to $host:$port — $e"
            notify!(messages, e)
            sleep(0.5)
        end
    end
end

# Start client in a background Task so handlers can be registered.
@async _run_tcp_client(host, port, messages)

println("Observable `messages` created — register handlers with `on` from Observables.jl.")

# Convenience helper to register handlers
function add_handler(fn::Function)
    on(messages) do msg
        try
            fn(msg)
        catch e
            @error "Handler error: $e"
        end
    end
end

export messages, add_handler
