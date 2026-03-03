# ijulia_comm_forward.jl
# Register a comm target in IJulia and forward incoming messages to
# Python via PyCall (uses examples/py_ijulia_forward.py::handle_payload).

try
    using IJulia, JSON, PyCall
    import IJulia: Comm, comm_target
catch e
    @warn "Required packages (IJulia, JSON, PyCall) not available: $e"
end

const TARGET_NAME = "jupyter.ggblab"
# Exposed Python manager instance (set when available)
global PY_FORWARD_MANAGER = nothing

function _ensure_py_forward_module()
    # Insert examples/ to sys.path so Python can import py_ijulia_forward
    try
        pysys = pyimport("sys")
        pyos = pyimport("os")
        examples_path = abspath(joinpath(@__DIR__, "."))
        # Prepend so local examples/ is found first
        if !(examples_path in pysys.path)
            pysys.path.insert(0, examples_path)
        end
        # also ensure py_comm_manager is available and create manager
        try
            # include julia helper that defines create_pycommmanager()
            include(joinpath(@__DIR__, "py_comm_manager.jl"))
            mgr = create_pycommmanager()
            global PY_FORWARD_MANAGER
            PY_FORWARD_MANAGER = mgr
            # set send callback so Python can ask Julia to send replies
            try
                cb = pyfunction((comm_id, msg_json) -> begin
                            send_reply_to_comm(string(comm_id), string(msg_json))
                        end, Any, Any)
                mgr.set_send_callback(cb)
            catch e
                @warn "Failed to set pymgr send callback: $e"
            end
            return (pyimport("py_ijulia_forward"), mgr)
        catch e
            @warn "Failed to create PyCommManager: $e"
            return (pyimport("py_ijulia_forward"), nothing)
        end
    catch e
        @warn "Failed to import py_ijulia_forward: $e"
        return nothing
    end
end

const _ACTIVE_COMMS = Dict{String,Any}()

# Manual on_open handler you can register interactively from IJulia
const MANUAL_ACTIVE_COMMS = Dict{String,Any}()

function manual_on_open(comm, msg)
    println("manual_on_open called")
    cid = nothing
    try
        cid = getproperty(comm, :id)
    catch
    end
    if cid === nothing || cid == ""
        try
            cid = getproperty(comm, :comm_id)
        catch
        end
    end
    if cid === nothing || cid == ""
        try
            mc = try msg["content"]["comm_id"] catch; try msg["content"]["commId"] catch; nothing end end
            if mc !== nothing
                cid = mc
            end
        catch
        end
    end
    if cid === nothing || cid == ""
        cid = string(comm)
    end
    cid = string(cid)
    println("manual: registering comm id=", cid)
    MANUAL_ACTIVE_COMMS[cid] = comm

    try
        comm.on_msg(function(m)
            try
                data = m["content"]["data"]
                payload = isa(data, String) ? JSON.parse(data) : data
                println("manual received payload: ", payload)
                resp = Dict("type" => "value", "id" => get(payload, "id", nothing),
                            "payload" => Dict("value" => "ok"))
                comm.send(JSON.json(resp))
            catch e
                @warn "manual on_msg handler error: $e"
            end
        end)
    catch e
        @warn "Failed to attach manual on_msg: $e"
    end
end

function register_manual_forwarder()
    if hasproperty(IJulia, :register_comm)
        IJulia.register_comm(TARGET_NAME, manual_on_open)
        println("Registered manual_on_open via IJulia.register_comm")
        return true
    elseif hasproperty(IJulia, :install_comm)
        IJulia.install_comm(TARGET_NAME, manual_on_open)
        println("Registered manual_on_open via IJulia.install_comm")
        return true
    else
        println("No register_comm API available in this IJulia build")
        return false
    end
end

function send_reply_comm(comm_obj, reply_json::AbstractString)
    try
        comm_obj.send(reply_json)
        return true
    catch e
        @warn "send_reply_comm failed: $e"
        return false
    end
end

function send_reply_to_comm(comm_id::AbstractString, reply_json::AbstractString)
    comm = get(_ACTIVE_COMMS, comm_id, nothing)
    if comm === nothing
        @warn "No active comm with id: $comm_id"
        return false
    end
    return send_reply_comm(comm, reply_json)
end

function _on_comm_msg(comm, m, pymod_tuple)
    try
        data = m["content"]["data"]
        payload = isa(data, String) ? JSON.parse(data) : data
        # Call Python handler
        (pymod, pymgr) = pymod_tuple
        if pymod !== nothing
            try
                js = pymod.handle_payload(payload)
                js_str = String(js)
            catch e
                @warn "Python handler raised: $e"
                js_str = JSON.json(Dict("type"=>"error","id"=>get(payload,"id",nothing),"payload"=>Dict("message"=>string(e))))
            end
            # send immediate reply
            comm.send(js_str)
            # also notify Python manager of the open/msg (so Python can send later)
            try
                # pass simple comm descriptor and raw message
                if pymgr !== nothing
                    # call pymgr.comm_msg(comm_descriptor, payload)
                    pymgr.comm_msg("", payload)
                end
            catch e
                @warn "pymgr.comm_msg failed: $e"
            end
        else
            js_str = JSON.json(Dict("type"=>"error","id"=>get(payload,"id",nothing),"payload"=>Dict("message"=>"no python handler")))
            comm.send(js_str)
        end
    catch e
        @warn "Failed to handle comm message: $e"
    end
end

function on_open(comm, msg)
    println("ggblab comm opened (forwarding to Python)")
    (pymod, pymgr) = _ensure_py_forward_module()
    try
        # Attempt to determine a stable comm id from various places.
        # 1) common comm objects may expose `id`; 2) open message may include comm_id; 
        # 3) fallback to string(comm).
        cid = nothing
        # try common properties
        try
            cid = getproperty(comm, :id)
        catch
        end
        if cid === nothing || cid == ""
            try
                cid = getproperty(comm, :comm_id)
            catch
            end
        end
        if cid === nothing || cid == ""
            # try reading the open message (Jupyter comm_open uses content.comm_id)
            try
                # msg may be a Julia Dict-like or PyObject mapping
                mc = try msg["content"]["comm_id"] catch; try msg["content"]["commId"] catch; nothing end end
                if mc !== nothing
                    cid = mc
                end
            catch
            end
        end
        # final fallback: string representation of comm object
        if cid === nothing || cid == ""
            cid = string(comm)
        end
        cid_str = string(cid)
        println("Registering active comm id=", cid_str)
        _ACTIVE_COMMS[cid_str] = comm
        # if pymgr present, instruct it about the open
        try
            if pymgr !== nothing
                # create a minimal comm descriptor for Python side
                pd = Dict("id"=>cid_str, "target_name"=>TARGET_NAME)
                pymgr.comm_open(TARGET_NAME, pd, Dict("content"=>Dict("data"=>Dict("type"=>"open","id"=>cid_str))))
            end
        catch e
            @warn "pymgr.comm_open failed: $e"
        end
        comm.on_msg(m -> _on_comm_msg(comm, m, (pymod, pymgr)))
    catch e
        @warn "Failed to attach comm.on_msg: $e"
    end
end

function register_forwarder()
    try
        if hasproperty(IJulia, :register_comm)
            IJulia.register_comm(TARGET_NAME, on_open)
            println("Registered comm forwarder via IJulia.register_comm(\"$TARGET_NAME\")")
            return true
        elseif hasproperty(IJulia, :install_comm)
            IJulia.install_comm(TARGET_NAME, on_open)
            println("Registered comm forwarder via IJulia.install_comm(\"$TARGET_NAME\")")
            return true
        else
            println("No automatic registration API detected. To register manually, run the following in your IJulia session:")
            println("using IJulia, JSON, PyCall")
            println("# define on_open(...) as in this file then call: IJulia.register_comm(\"$TARGET_NAME\", on_open)")
            return false
        end
    catch e
        @warn "Failed to register comm forwarder: $e"
        return false
    end
end

# Autoregister when included
try
    register_forwarder()
catch e
    @warn "Auto-register failed: $e"
end

export register_forwarder, send_reply_to_comm, send_reply_comm
