# Stage 2 probe (現行経路の文字列化): run the v1 `@ggb` macro VERBATIM (julia/GeoGebra.jl/src/ggb_macros.jl of the
# ggblab main checkout) with the transport stubbed to a recorder, so that every command string the current route would
# send to the applet is captured — without an applet, a kernel, or PythonCall.  Rules copied verbatim: the argument
# stringification of CommBridge.send_command_eval (label for GGBObject, `string(a)` otherwise, ", " join) and
# expr_to_cmd_string (extracted from ggb_sympy.jl).  Usage: julia current_route_render.jl <lines.json> <out.json> [<v1 src dir>]
using JSON
const V1SRC = length(ARGS) >= 3 ? ARGS[3] : "/Users/manabu/work/ggblab/julia/GeoGebra.jl/src"
module GeoGebra
    mutable struct GGBObject; label::String; data::Any; end
    const _CONSRUCTION_PROTOCOL = Ref{Vector{GGBObject}}(GGBObject[])
    construction_protocol() = _CONSRUCTION_PROTOCOL[]
    const SENT = String[]
    send_command(cmd_text::AbstractString; kw...) = (push!(SENT, String(cmd_text)); Any[])
    function send_command_eval(name, args_tuple; kw...)                 # = CommBridge.send_command_eval_tcp, verbatim rule
        args = Tuple((isa(a, GGBObject) ? a.label : a) for a in args_tuple)
        name_str = isa(name, Symbol) ? string(name) : string(name)
        arg_strs = [string(a) for a in args]
        cmd_text = string(name_str, "(", join(arg_strs, ", "), ")")
        push!(SENT, cmd_text); Any[]
    end
    send_function(name, args...; kw...) = (push!(SENT, "api:" * string(name) * "(" * join(string.(args), ", ") * ")"); nothing)
    send_function_eval(name, args_tuple) = send_function(name, args_tuple...)
    send_listen(label; enabled::Bool=true, kw...) = (push!(SENT, (enabled ? "listen:" : "unlisten:") * string(label)); nothing)
    get_object_observable(lbl) = nothing
    get_construction_object(args...) = nothing
    process_labels_response(resp) = resp
    _push_construction_result!(resp) = nothing
    new_construction!() = (push!(SENT, "api:newConstruction()"); empty!(_CONSRUCTION_PROTOCOL[]); _CONSRUCTION_PROTOCOL[])
    sympy_to_ggb(x) = nothing
    include(joinpath(@__DIR__, "expr_to_cmd_string_v1.jl"))
    include(joinpath(Main.V1SRC, "ggb_macros.jl"))                        # VERBATIM v1 macro file
end
const var"@ggb" = GeoGebra.var"@ggb"
lines = JSON.parsefile(ARGS[1])
out = Any[]
for (i, body) in enumerate(lines)
    empty!(GeoGebra.SENT); empty!(GeoGebra._CONSRUCTION_PROTOCOL[])
    rec = Dict("i" => i - 1, "body" => body, "sent" => String[], "status" => "ok", "error" => "")
    try
        ex = Meta.parse("@ggb " * body)
        Core.eval(Main, ex)
        rec["sent"] = copy(GeoGebra.SENT)
    catch e
        rec["status"] = e isa UndefVarError ? "dynamic" : "error"
        rec["error"] = sprint(showerror, e)[1:min(end, 160)]
        rec["sent"] = copy(GeoGebra.SENT)
    end
    push!(out, rec)
end
open(ARGS[2], "w") do io; JSON.print(io, Dict("n" => length(out), "macro_file" => joinpath(V1SRC, "ggb_macros.jl"), "rows" => out)); end
println("⭕ rendered ", length(out), " lines → ", ARGS[2])
