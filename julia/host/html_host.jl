"""
GGBLabHost — the Julia twin of `ggblab/host/html_host.py` (stage 4, 2026-09-10; module name is a position marker, C7).

Same transport as the Python host (C0, ruling (i) 2026-09-09): the kernel is an HTTP client of its own jupyter_server —
`POST ggblab/call` parks until the browser's reply (`GET ggblab/await` continues in proxy-sized slices), events are
pulled with `GET ggblab/events`.  No comm, no comm target, no control socket, no WebSocket, no HTTP.jl: `Downloads`
(stdlib) + `JSON` + IJulia's display.  The mount is the SAME JavaScript as the Python host (`ggblab/host/mount.js`),
so the browser cannot tell which language is behind the mailbox.  Verbs = the closed subset of 8 (C1):
eval / new / delete / xml_in (writes), xml_out / value / kind (reads), listen (subscription, pull-first; no task).

    include("julia/host/html_host.jl"); using .GGBLabHost
    g = GeoGebra(appName="suite"); mount(g)
    command(g, "A = (1, 2)", "c = Circle(A, 1)")   # -> labels per command
    xml(g); value(g, "a"); events(g); wait_update(g, "A"; timeout=20.0)
"""
module GGBLabHost

using Downloads, JSON, UUIDs

const DEPLOY = Ref("https://www.geogebra.org/apps/deployggb.js")
const MOUNT_JS = read(joinpath(@__DIR__, "..", "..", "ggblab", "host", "mount.js"), String)
const SLICE = 25.0                     # one parked HTTP request per proxy-sized slice (same as the Python host)

export GeoGebra, mount, command, xml, set_xml, delete, value, new_construction, kind, listen, unlisten, events, errors, wait_update, request

# ── the 8 verbs as JSON requests (mirrors ggblab/host/base.py `to_json`; contract-checked by tests/test_julia_host_parity.py) ──
function request(kind::Symbol; req_id::AbstractString="", commands=String[], xml::AbstractString="", label::AbstractString="", enable::Bool=true)
    d = kind === :eval    ? Dict{String,Any}("kind" => "eval", "commands" => collect(String, commands)) :
        kind === :xml_in  ? Dict{String,Any}("kind" => "xml_in", "xml" => xml) :
        kind === :xml_out ? Dict{String,Any}("kind" => "xml_out") :
        kind === :listen  ? Dict{String,Any}("kind" => "listen", "enable" => enable) :
        kind === :delete  ? Dict{String,Any}("kind" => "delete", "label" => label) :
        kind === :value   ? Dict{String,Any}("kind" => "value", "label" => label) :
        kind === :kind    ? Dict{String,Any}("kind" => "kind", "label" => label) :
        kind === :new     ? Dict{String,Any}("kind" => "new") :
        error("unhandled request kind: $kind")          # C3: one clause per head, no guessing
    d["req_id"] = req_id
    d
end

# ── kernel identity and the server that owns it (find_server twin) ──
function kernel_id()
    cf = try
        Main.IJulia._default_kernel.connection_file
    catch
        return ""
    end
    f = basename(String(cf))
    startswith(f, "kernel-") && endswith(f, ".json") ? f[8:end-5] : ""
end

function runtime_dir()
    d = get(ENV, "JUPYTER_RUNTIME_DIR", "")
    isempty(d) || return d
    try
        d = strip(read(`jupyter --runtime-dir`, String)); isempty(d) || return d
    catch
    end
    Sys.isapple() ? joinpath(homedir(), "Library", "Jupyter", "runtime") : joinpath(homedir(), ".local", "share", "jupyter", "runtime")
end

function _status(url, headers; timeout=3.0)
    io = IOBuffer()
    r = Downloads.request(url; method="GET", headers=headers, output=io, timeout=timeout, throw=false)
    r isa Downloads.Response ? r.status : 0
end

function find_server(kid::AbstractString)
    cands = Tuple{String,Vector{Pair{String,String}}}[]
    hub_url, hub_tok = get(ENV, "JUPYTERHUB_SERVICE_URL", ""), get(ENV, "JUPYTERHUB_API_TOKEN", "")
    if !isempty(hub_url) && !isempty(hub_tok)
        push!(cands, (hub_url, ["Authorization" => "token $hub_tok"]))
    end
    rd = runtime_dir()
    if isdir(rd)
        for f in sort(readdir(rd; join=true); by=mtime, rev=true)
            (startswith(basename(f), "jpserver-") && endswith(f, ".json")) || continue
            d = try JSON.parsefile(f) catch; continue end
            tok = get(d, "token", "")
            push!(cands, (String(d["url"]), isempty(tok) ? Pair{String,String}[] : ["Authorization" => "token $tok"]))
        end
    end
    for (url, h) in cands
        u = rstrip(url, '/')
        _status("$u/api/kernels/$kid", h) == 200 && return (u, h)
    end
    error("no running jupyter_server owns kernel '$kid' (candidates: $(first.(cands)))")
end

# ── the façade ──
mutable struct GeoGebra
    kernel_id::String
    dom_id::String
    params::Dict{String,Any}
    url::String
    headers::Vector{Pair{String,String}}
    path::Union{Nothing,String}
    mount_id::String
    mounted::Bool
    event_seq::Int
    listeners::Vector{Tuple{Function,Union{Nothing,String}}}
end

_q(s::AbstractString) = join(('A' <= c <= 'Z' || 'a' <= c <= 'z' || '0' <= c <= '9' || c in "-_.~") ? string(c) :
                              join(string("%", uppercase(string(b, base=16, pad=2))) for b in codeunits(string(c))) for c in s)

function _http(g::GeoGebra, method::AbstractString, path::AbstractString; body=nothing, timeout=5.0)
    io = IOBuffer()
    hdr = vcat(g.headers, ["Content-Type" => "application/json"])
    r = body === nothing ?
        Downloads.request(g.url * path; method=method, headers=hdr, output=io, timeout=timeout, throw=false) :
        Downloads.request(g.url * path; method=method, headers=hdr, input=IOBuffer(body), output=io, timeout=timeout, throw=false)
    r isa Downloads.Response || error("HTTP failed: $path ($r)")
    s = String(take!(io))
    r.status == 200 || error("HTTP $(r.status) $path: $s")
    isempty(s) ? Dict{String,Any}() : JSON.parse(s)
end

mount_key(path, kid, name) = (isempty(something(path, "")) ? "kernel:$kid" : "doc:$path") * (isempty(something(name, "")) ? "" : ":$name")

function GeoGebra(; mount=nothing, doc=nothing, params...)
    kid = kernel_id()
    url, headers = find_server(kid)
    g = GeoGebra(kid, string(uuid4())[1:12], Dict{String,Any}(string(k) => v for (k, v) in params), url, headers, nothing, "", false, 0, Tuple{Function,Union{Nothing,String}}[])
    if doc !== nothing
        g.path, g.mount_id = String(doc), mount_key(String(doc), kid, mount)
    else
        try
            d = _http(g, "GET", "/ggblab/whoami?kernel_id=$kid" * (mount === nothing ? "" : "&name=$(_q(mount))"); timeout=3.0)
            if get(d, "path", nothing) !== nothing
                g.path, g.mount_id = String(d["path"]), String(d["mount"])
            end
        catch
        end
        if isempty(g.mount_id)
            p = get(ENV, "JPY_SESSION_NAME", "")
            g.path = isempty(p) ? nothing : p
            g.mount_id = mount_key(g.path, kid, mount)
        end
    end
    try                                                    # events start from now, not from the box's birth
        d = _http(g, "GET", "/ggblab/events?mount=$(_q(g.mount_id))&since=latest&wait=0")
        g.event_seq = Int(d["next"])
    catch
        g.event_seq = 0
    end
    g
end

function mount(g::GeoGebra)
    cfg = Dict("mount" => g.mount_id, "dom" => g.dom_id, "params" => g.params, "deploy" => DEPLOY[])
    html = "<div id=\"ggb-$(g.dom_id)\" style=\"min-height:600px\"></div><script>" * replace(MOUNT_JS, "__CFG__" => JSON.json(cfg)) * "</script>"
    display(HTML(html))
    g.mounted = true
    nothing
end
Base.show(io::IO, ::MIME"text/html", g::GeoGebra) = (mount(g); print(io, ""))   # `g` at the end of a cell mounts, like the Python façade

function _rpc(g::GeoGebra, req::Dict{String,Any}; timeout=10.0)
    g.mounted || mount(g)
    rid = string(uuid4())[1:12]
    req["req_id"] = rid
    t0 = time(); w = min(timeout, SLICE)
    d = _http(g, "POST", "/ggblab/call"; body=JSON.json(Dict("mount" => g.mount_id, "request" => req, "wait" => w)), timeout=w + 10)
    while get(d, "status", "") == "pending"
        left = timeout - (time() - t0)
        left <= 0 && error("no reply for $rid within $(timeout)s (box $(g.mount_id): is its applet open in a browser?)")
        w = min(left, SLICE)
        d = _http(g, "GET", "/ggblab/await?req_id=$rid&wait=$w"; timeout=w + 10)
    end
    get(d, "data", nothing)
end

command(g::GeoGebra, cmds::AbstractString...; timeout=10.0) = _rpc(g, request(:eval; commands=collect(String, cmds)); timeout)
xml(g::GeoGebra; timeout=10.0) = _rpc(g, request(:xml_out); timeout)
set_xml(g::GeoGebra, x::AbstractString; timeout=10.0) = _rpc(g, request(:xml_in; xml=x); timeout)
delete(g::GeoGebra, label::AbstractString; timeout=10.0) = _rpc(g, request(:delete; label=label); timeout)
value(g::GeoGebra, label::AbstractString; timeout=10.0) = _rpc(g, request(:value; label=label); timeout)
new_construction(g::GeoGebra; timeout=10.0) = _rpc(g, request(:new); timeout)
kind(g::GeoGebra, label::AbstractString; timeout=10.0) = _rpc(g, request(:kind; label=label); timeout)

listen(g::GeoGebra, cb::Function; label=nothing) = (push!(g.listeners, (cb, label === nothing ? nothing : String(label))); nothing)
unlisten(g::GeoGebra, cb=nothing) = (g.listeners = cb === nothing ? Tuple{Function,Union{Nothing,String}}[] : filter(t -> t[1] !== cb, g.listeners); nothing)

function events(g::GeoGebra; wait=0.0)
    d = _http(g, "GET", "/ggblab/events?mount=$(_q(g.mount_id))&since=$(g.event_seq)&wait=$wait"; timeout=wait + 10)
    evs = [e["data"] for e in get(d, "events", Any[])]
    g.event_seq = Int(get(d, "next", g.event_seq))
    for e in evs, (cb, label) in g.listeners
        (label === nothing || get(e, "label", nothing) == label) && (try cb(e) catch end)
    end
    evs
end
errors(g::GeoGebra; wait=0.0) = filter(e -> get(e, "type", "") == "error", events(g; wait))

function wait_update(g::GeoGebra, label::AbstractString; timeout=30.0)
    t0 = time()
    while true
        left = timeout - (time() - t0)
        left <= 0 && return nothing
        for e in events(g; wait=min(left, SLICE))
            get(e, "label", nothing) == label && get(e, "type", "") in ("update", "add") && return e
        end
    end
end

end # module
