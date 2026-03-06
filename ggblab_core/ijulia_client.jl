"""Simple TCP JSON bridge client for use from Julia (IJulia/PyCall testing).

Provides `request`, `poll_reply`, and `request_with_retry` functions equivalent
to the Python bridge client. Intended for verification when Julia cannot
communicate with the frontend comm and a separate Python process hosts the
`comm_bridge` server.

Quick snippet (Julia)
---------------------
```julia
using IJuliaBridgeClient

# assume the Python bridge is running on localhost:8765
payload = Dict("type"=>"function", "payload"=>Dict("name"=>"getVersion", "args"=>[]))
resp = IJuliaBridgeClient.request_with_retry(payload; host="127.0.0.1", port=8765)
println(resp)
```

"""

using JSON

# Defaults are mutable so users can change the bridge host/port at runtime
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

"""Low-level helper: send a JSON line to the bridge and return parsed reply.

This is an internal helper; callers should use the exported `request`.
"""
function _send_and_recv(msg::String; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=10.0)
    # Ensure the Sockets stdlib is available at runtime without declaring it
    # as a package dependency in Project.toml. Use `eval` to load it dynamically.
    sockets_mod = try
        Base.require(@__MODULE__, :Sockets)
    catch
        try
            Base.require(Main, :Sockets)
        catch
            try
                eval(@__MODULE__, :(using Sockets))
                getfield(@__MODULE__, :Sockets)
            catch err
                throw(ErrorException("Failed to load Sockets stdlib: $(err)"))
            end
        end
    end
    sock = sockets_mod.connect(host, port)
    try
        write(sock, msg * "\n")
        flush(sock)
        # readline will block until newline or EOF; rely on TCP server to reply
        line = readline(sock)
        return JSON.parse(String(line))
    finally
        close(sock)
    end
end


"""Normalize bridge reply by unwrapping top-level `reply` key when present."""
function _unwrap_reply(resp)
    if resp isa AbstractDict && haskey(resp, "reply")
        return resp["reply"]
    else
        return resp
    end
end

"""Send `payload` to the comm bridge and return parsed reply.

Parameters
- payload: Dict/Array/String
    The JSON-serializable payload to send. If a Julia object is provided
    it will be converted to JSON. If a string is provided it will be sent
    as-is (and must be valid JSON expected by the bridge).
- host, port, timeout: connection parameters

Returns
- Parsed JSON reply (as Julia Dict/Array/primitive) or throws on network errors.
"""
function request(payload; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=10.0)
    # Accept raw String or Julia object (Dict/Array/etc.)
    data = isa(payload, String) ? payload : JSON.json(payload)
    return _unwrap_reply(_send_and_recv(data; host=host, port=port, timeout=timeout))
end


"""Send a command by name and runtime arguments.

Example: `send_command(:Circle, (0,0), 1)` will send `Circle((0,0), 1)`.
"""
function send_command(name, args...; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT)
    # Build textual command from runtime-evaluated args
    name_str = isa(name, Symbol) ? string(name) : string(name)
    arg_strs = [string(a) for a in args]
    cmd_text = string(name_str, "(", join(arg_strs, ", "), ")")
    payload = Dict("type"=>"command", "payload"=>cmd_text)
    return request(payload; host=host, port=port)
end


"""Call a named function on the bridge with runtime-evaluated args.

Example: `send_function(:getVersion)` sends a function payload.
"""
function send_function(name, args...; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT)
    name_str = isa(name, Symbol) ? string(name) : string(name)
    arg_strs = [string(a) for a in args]
    payload = Dict("type"=>"function", "payload"=>Dict("name"=>name_str, "args"=>arg_strs))
    return request(payload; host=host, port=port)
end


"""Evaluate a tuple of runtime arguments and call `send_command` with module defaults."""
function send_command_eval(name, args_tuple)
    return send_command(name, args_tuple...; host=DEFAULT_HOST, port=DEFAULT_PORT)
end


"""Evaluate a tuple of runtime arguments and call `send_function` with module defaults."""
function send_function_eval(name, args_tuple)
    return send_function(name, args_tuple...; host=DEFAULT_HOST, port=DEFAULT_PORT)
end

# Export symbols after they are defined
export request, poll_reply, request_with_retry, set_default_host, set_default_port, send_command, send_function
export @ggblab

"""Poll the bridge for a previously stored reply by `reply_id`.

This sends the ``{"op": "get_reply", "id": reply_id}`` request to the bridge
and returns the stored reply if available.
"""
function poll_reply(reply_id::AbstractString; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=5.0)
    payload = Dict("op"=>"get_reply", "id"=>reply_id)
    return request(payload; host=host, port=port, timeout=timeout)
end

"""Send `payload` with retry/backoff and optional stored-reply polling.

Attempts `retries` sends with exponential backoff. If all attempts fail and
``allow_get_reply`` is true, this will poll the bridge for a stored reply
using the message id (if one was included or injected into the payload).
"""
function request_with_retry(payload; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT,
                            timeout::Real=10.0, retries::Int=3, backoff::Real=0.5,
                            allow_get_reply::Bool=true, poll_interval::Real=0.5, poll_timeout::Real=5.0)
    msg_id = nothing
    pl = payload
    if isa(payload, AbstractDict) && haskey(payload, "id")
        msg_id = string(payload["id"])
    elseif isa(payload, AbstractDict)
        msg_id = string(round(Int, time()*1e6)) * "-" * string(rand(UInt64))
        pl = deepcopy(payload)
        pl["id"] = msg_id
    else
        # not a dict: we won't be able to poll by id
        msg_id = nothing
    end

    last_err = nothing
    for attempt in 1:max(1, retries)
        try
            return request(pl; host=host, port=port, timeout=timeout)
        catch e
            last_err = e
            if attempt < retries
                sleep(backoff * 2^(attempt-1))
                continue
            end
        end
    end

    if allow_get_reply && msg_id !== nothing
        deadline = time() + poll_timeout
        while time() < deadline
            try
                r = poll_reply(string(msg_id); host=host, port=port, timeout=poll_interval)
                if isa(r, AbstractDict) && haskey(r, "error")
                    # continue polling
                    nothing
                else
                    return r
                end
            catch
                # ignore and retry until timeout
            end
            sleep(poll_interval)
        end
        if last_err !== nothing
            throw(last_err)
        end
    end

    return Dict("error"=>"request_with_retry failed")
end

 


"""Set the default bridge host used by `@ggblab` and helpers."""
function set_default_host(h::AbstractString)
    global DEFAULT_HOST = h
    return DEFAULT_HOST
end


"""Set the default bridge port used by `@ggblab` and helpers."""
function set_default_port(p::Integer)
    global DEFAULT_PORT = Int(p)
    return DEFAULT_PORT
end


"""Macro-based convenience wrapper.

Usage:
  @ggblab Circle((0,0), 1)
    -> sends a `command` payload with text "Circle((0,0), 1)"

  @ggblab api getXML(c)
    -> sends an `api` call for `getXML` with argument "c"

The macro expands to a call to `IJuliaBridgeClient.request_with_retry` and
returns the parsed reply.
"""
macro ggblab(args...)
    # Normalize invocation: drop possible LineNumberNode and Module metadata
    toks = args
    if length(toks) >= 2 && toks[1] isa LineNumberNode
        # form observed: (LineNumberNode, Module, rest...)
        toks = toks[3:end]
    end

    if length(toks) == 0
        error("@ggblab requires an expression")
    end

    # Reconstruct a single Expr representing the user's intent
    ex = nothing
    if length(toks) == 1
        ex = toks[1]
    else
        # If first token is :api, make an api call expression
        if toks[1] === :api
            if length(toks) < 2
                error("@ggblab api usage must be like `@ggblab api fn(args...)`")
            end
            # second token may already be a call expression
            ex = Expr(:call, :api, toks[2])
        else
            # Otherwise treat as a call: head followed by arguments
            head = toks[1]
            args_rest = toks[2:end]
            ex = Expr(:call, head, args_rest...)
        end
    end

    # Now handle the normalized expression `ex` similar to previous implementation
    # api form
    if ex isa Expr && ex.head == :call && ex.args !== nothing && length(ex.args) >= 1 && ex.args[1] == :api
        inner = ex.args[2]
        if inner isa Expr && inner.head == :call
            name = inner.args[1]
            arg_nodes = inner.args[2:end]
            # Call runtime helper so arguments are evaluated before sending
            args_tuple = Expr(:tuple, arg_nodes...)
            return esc(Expr(:call, Expr(:call, :getfield, :(IJuliaBridgeClient), QuoteNode(:send_function_eval)), QuoteNode(name), args_tuple))
        else
            error("@ggblab api usage must be like `@ggblab api fn(args...)`")
        end
    end

    # command call: @ggblab Circle((0,0),1) or literals like @ggblab (0,0)
    if ex isa Expr && ex.head == :call
        name = ex.args[1]
        arg_nodes = ex.args[2:end]
        # Use the runtime helper so arguments are evaluated
        args_tuple = Expr(:tuple, arg_nodes...)
        return esc(Expr(:call, Expr(:call, :getfield, :(IJuliaBridgeClient), QuoteNode(:send_command_eval)), QuoteNode(name), args_tuple))
    else
        # Fallback: evaluate the expression and send its string form as a command payload
        return esc(:(begin
            using IJuliaBridgeClient
            payload = Dict("type"=>"command", "payload"=>string($(QuoteNode(ex))))
            IJuliaBridgeClient.request(payload; host=IJuliaBridgeClient.DEFAULT_HOST, port=IJuliaBridgeClient.DEFAULT_PORT)
        end))
    end
end
