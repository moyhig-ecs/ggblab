"""
GGBLabMacro — the v2 Julia entry for constructions (ruling 2026-09-11: option A, the parser delegated to Python).

    ggb"…"      →  a Construction (parsed by `ggblab.parse.parse_cell`, dialect "python", via PythonCall)
    ggb"…"g     →  the same, applied to the host `g` (a `GGBLabHost.GeoGebra`): returns the labels per statement

The body is a NON-STANDARD STRING LITERAL: Julia's parser never sees it (the v1 `@ggb` Expr macro let Julia parse the
GeoGebra text first — juxtaposition `u v`, prime labels `C'`, `²`, numeric literals and operator printing were rewritten
or rejected before the macro ran; see lancedb-rag conversations/2026-09-11/SURVEY_julia_ggb_macro_v1_20260911.md).
The closed world (28 heads, `:label` refs, `RelativeReference`) is the Python parser's — one parser for both kernels (C6:
ggblab_extra / the parser are not reimplemented in Julia). No `\$` interpolation (a string macro receives raw text).

    include("julia/host/html_host.jl"); include("julia/host/ggb_macro.jl"); using .GGBLabHost, .GGBLabMacro
    c = ggb\"\"\"
    :const :new
    A = (0, 0)
    c = Circle(:A, 1)
    C' = l1(1)
    \"\"\"
    to_ggb(c)        # the command strings, byte for byte
    apply(g, c)      # or  ggb"…"g
"""
module GGBLabMacro

using PythonCall
import ..GGBLabHost: GeoGebra, command, new_construction, delete

export @ggb_str, parse_ggb, apply, plan, to_ggb, labels, flatten_labels, ClosedWorldError

struct ClosedWorldError <: Exception
    msg::String
end
Base.showerror(io::IO, e::ClosedWorldError) = print(io, "ClosedWorldError: ", e.msg)

const _PARSE = Ref{Any}(nothing)
const _ADAPTER = Ref{Any}(nothing)
_parse_mod() = (_PARSE[] === nothing && (_PARSE[] = pyimport("ggblab.parse")); _PARSE[])
_adapter_mod() = (_ADAPTER[] === nothing && (_ADAPTER[] = pyimport("ggblab.adapter")); _ADAPTER[])

"""Python `Construction` from raw text (dialect "python": every non-empty line is a statement). Parse errors of the closed
world (UnknownHead, RelativeReference, ParseError) surface as `ClosedWorldError` with the Python message."""
function parse_ggb(s::AbstractString)
    try
        return _parse_mod().parse_cell(String(s); dialect="python")
    catch e
        e isa PyException || rethrow()
        throw(ClosedWorldError(sprint(showerror, e)))
    end
end

to_ggb(c) = pyconvert(Vector{String}, c.to_ggb())
labels(c) = pyconvert(Vector{String}, c.labels())
plan(c) = collect(_adapter_mod().plan(c))

"""`flatten_labels` (ggblab/ipymagic.py): one entry per statement — a label string, `nothing` (GeoGebra refused / redefinition),
or a Dict (the Apps API threw); GeoGebra's comma-joined labels (`t1,c,a,b`) are split."""
function flatten_labels(replies)
    out = Any[]
    for r in replies
        r isa AbstractVector || (push!(out, r); continue)
        for x in r
            if x isa AbstractString
                append!(out, split(x, ','))
            else
                push!(out, x)
            end
        end
    end
    out
end

"""Send the plan to a host (one `Eval` per batch; `:const :new` → `new_construction`; `:const :undo` → `delete` of the last
label; `:api …` is not a construction statement → `ClosedWorldError`). Mirrors `ggblab.adapter.apply`."""
function apply(g::GeoGebra, c; timeout::Real=10.0)
    replies = Any[]
    for st in plan(c)
        k = pyconvert(String, pytype(st).__name__)
        if k == "Eval"
            push!(replies, command(g, pyconvert(Vector{String}, st.commands)...; timeout=Float64(timeout)))
        elseif k == "HostWord"
            a = pyconvert(String, st.action)
            if a == "newConstruction"
                push!(replies, new_construction(g; timeout=Float64(timeout)))
            elseif a == "undo"
                ls = labels(c)
                isempty(ls) && throw(ClosedWorldError(":const :undo with no labelled statement before it"))
                push!(replies, delete(g, ls[end]; timeout=Float64(timeout)))
            else
                throw(ClosedWorldError("directive $a $(pyconvert(String, st.detail)): not a construction statement (no Verb)"))
            end
        else
            throw(ClosedWorldError("unknown plan step $k"))
        end
    end
    flatten_labels(replies)
end

macro ggb_str(s, flags...)
    if isempty(flags)
        return :(parse_ggb($s))
    else
        host = Symbol(flags[1])
        return :(apply($(esc(host)), parse_ggb($s)))
    end
end

end # module
