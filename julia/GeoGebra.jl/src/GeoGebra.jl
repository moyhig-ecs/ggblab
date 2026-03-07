module GeoGebra

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
using PythonCall

# Defaults are mutable so users can change the bridge host/port at runtime
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

"""Internal helper: send a JSON line to the bridge and return the parsed reply.

Arguments:
- `msg::String`: JSON string to send (a newline is appended automatically).
- `host`, `port`, `timeout`: connection parameters.

Returns:
- Parsed JSON (Dict/Array/primitive). Network or parse errors raise exceptions.
"""
function _send_and_recv(msg::String; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=10.0)
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
        line = readline(sock)
        return JSON.parse(String(line))
    finally
        close(sock)
    end
end

"""Normalize bridge replies.

If the bridge returns a `{ "reply": ... }` wrapper, return the inner value;
otherwise return the response unchanged.
"""
function _unwrap_reply(resp)
    if resp isa AbstractDict && haskey(resp, "reply")
        return resp["reply"]
    else
        return resp
    end
end

"""Send `payload` to the bridge and return the parsed reply.

`payload` may be a `Dict`/`Array`/`String`; non-string values are converted to JSON.

Example:
```julia
resp = GeoGebra.request(Dict("type"=>"function", "payload"=>Dict("name"=>"getVersion", "args"=>[])))
```
"""
function request(payload; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=10.0)
    data = isa(payload, String) ? payload : JSON.json(payload)
    return _unwrap_reply(_send_and_recv(data; host=host, port=port, timeout=timeout))
end

"""Send a named command using runtime-evaluated arguments.

`name` may be a Symbol or String. Arguments are converted to strings and
sent as a textual command like `Name(arg1, arg2, ...)`.

Example:
```julia
GeoGebra.send_command(:Circle, (0,0), 1)
```
"""
function send_command(name, args...; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT)
    name_str = isa(name, Symbol) ? string(name) : string(name)
    arg_strs = [string(a) for a in args]
    cmd_text = string(name_str, "(", join(arg_strs, ", "), ")")
    payload = Dict("type"=>"command", "payload"=>cmd_text)
    return request(payload; host=host, port=port)
end

"""Send a function call payload to the bridge.

`name` is the function name (Symbol or String); `args` are converted to
strings and sent inside the `payload` object:
`{"type":"function","payload":{"name":...,"args":[...]}}`.
"""
function send_function(name, args...; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT)
    name_str = isa(name, Symbol) ? string(name) : string(name)
    arg_strs = [string(a) for a in args]
    args_field = length(arg_strs) == 0 ? nothing : arg_strs
    payload = Dict("type"=>"function", "payload"=>Dict("name"=>name_str, "args"=>args_field))
    resp = request(payload; host=host, port=port)
    try
        if resp isa AbstractDict && haskey(resp, "value")
            return resp["value"]
        elseif resp isa AbstractDict && haskey(resp, "payload")
            p = resp["payload"]
            if p isa AbstractDict && haskey(p, "value")
                return p["value"]
            end
        end
    catch
        # fall through and return original response on any error
    end
    return resp
end

"""Helper called by the macro: evaluate an argument tuple and call `send_command`."""
function send_command_eval(name, args_tuple)
    return send_command(name, args_tuple...; host=DEFAULT_HOST, port=DEFAULT_PORT)
end

"""Helper called by the macro: evaluate an argument tuple and call `send_function`."""
function send_function_eval(name, args_tuple)
    return send_function(name, args_tuple...; host=DEFAULT_HOST, port=DEFAULT_PORT)
end

"""Poll the bridge for a previously stored reply by `reply_id`.

`reply_id` is typically an ID injected by `request_with_retry`.
"""
function poll_reply(reply_id::AbstractString; host::String=DEFAULT_HOST, port::Int=DEFAULT_PORT, timeout::Real=5.0)
    payload = Dict("op"=>"get_reply", "id"=>reply_id)
    return request(payload; host=host, port=port, timeout=timeout)
end

"""Send `payload` with retry/backoff and optional stored-reply polling.

Parameters:
- `retries`: max send attempts
- `backoff`: initial delay in seconds
- `allow_get_reply`: if true, poll the bridge for a stored reply by `id` when all attempts fail
- `poll_interval`, `poll_timeout`: polling interval and timeout

Returns the reply on success; raises on network errors or returns
`Dict("error"=>...)` if polling/timeout occurs.
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
                    nothing
                else
                    return r
                end
            catch
            end
            sleep(poll_interval)
        end
        if last_err !== nothing
            throw(last_err)
        end
    end

    return Dict("error"=>"request_with_retry failed")
end

"""Set the module default `host`. Returns the new value."""
function set_default_host(h::AbstractString)
    global DEFAULT_HOST = h
    return DEFAULT_HOST
end

"""Set the module default `port`. Returns the new value."""
function set_default_port(p::Integer)
    global DEFAULT_PORT = Int(p)
    return DEFAULT_PORT
end

"""Macro helper: send commands/functions concisely with `@ggblab expr`.

Examples:
- `@ggblab Circle(0, 0, 1)` — send as a command
- `@ggblab api getVersion()` — send as a function call

The macro builds an argument tuple at expansion time and calls
`send_command_eval` / `send_function_eval` at runtime so arguments are
evaluated in the caller's scope.
"""
macro ggblab(args...)
    toks = args
    if length(toks) >= 2 && toks[1] isa LineNumberNode
        toks = toks[3:end]
    end
    if length(toks) == 0
        error("@ggblab requires an expression")
    end
    ex = nothing
    if length(toks) == 1
        ex = toks[1]
    else
        if toks[1] === :api
            if length(toks) < 2
                error("@ggblab api usage must be like `@ggblab api fn(args...)`")
            end
            ex = Expr(:call, :api, toks[2])
        else
            head = toks[1]
            args_rest = toks[2:end]
            ex = Expr(:call, head, args_rest...)
        end
    end
    if ex isa Expr && ex.head == :call && ex.args !== nothing && length(ex.args) >= 1 && ex.args[1] == :api
        inner = ex.args[2]
        if inner isa Expr && inner.head == :call
            name = inner.args[1]
            arg_nodes = inner.args[2:end]
            args_tuple = Expr(:tuple, arg_nodes...)
            return esc(Expr(:call, Expr(:call, :getfield, :(GeoGebra), QuoteNode(:send_function_eval)), QuoteNode(name), args_tuple))
        else
            error("@ggblab api usage must be like `@ggblab api fn(args...)`")
        end
    end
    if ex isa Expr && ex.head == :call
        name = ex.args[1]
        arg_nodes = ex.args[2:end]
        args_tuple = Expr(:tuple, arg_nodes...)
        return esc(Expr(:call, Expr(:call, :getfield, :(GeoGebra), QuoteNode(:send_command_eval)), QuoteNode(name), args_tuple))
    else
        return esc(:(begin
            using GeoGebra
            payload = Dict("type"=>"command", "payload"=>string($(QuoteNode(ex))))
            GeoGebra.request(payload; host=GeoGebra.DEFAULT_HOST, port=GeoGebra.DEFAULT_PORT)
        end))
    end
end

macro ggb(args...)
    return Expr(:macrocall, Symbol("@ggblab"), args...)
end

"""Run a Python coroutine (PythonCall.PyObject) with asyncio.run.

Usage:
```
# obtain a coroutine object, e.g. via `py"coro()"` or `pyeval("coro()")`
# coro = py"coro()"
result = @await coro
```
"""
macro await(expr)
    return :(let _asyncio = PythonCall.pyimport("asyncio")
                _coro = $(esc(expr))
                _asyncio.run(_coro)
             end)
end

export request, poll_reply, request_with_retry, set_default_host, set_default_port, send_command, send_function, send_command_eval, send_function_eval, @ggblab, @ggb, @await

end # module
