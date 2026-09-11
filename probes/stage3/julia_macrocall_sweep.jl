# The v1 entry path: `@ggb <body>` — Julia splits the macro's arguments at top-level whitespace BEFORE the macro runs.
# For every body: does `@ggb <body>` parse? how many macro arguments does it become? which heads?
using JSON
bodies = JSON.parsefile(ARGS[1])
extra = ["u v", "y = 2 x + 1", "Circle(A, 1) Circle(B, 1)", ":api getVersion()", ":const :new", "C' = l1(1)", "x²", "m_1 = Distance(O, P)² + 1", "A = (0, 0) # comment", "P = If(x(l2(1)) < x(M), l2(1), l2(2))"]
function one(src)
    ex = try Meta.parse("@ggb " * src) catch e; return Dict("src" => src, "parse" => "ERROR", "msg" => first(sprint(showerror, e), 100)) end
    if ex isa Expr && ex.head == :incomplete; return Dict("src" => src, "parse" => "INCOMPLETE"); end
    args = ex.args[3:end]   # (macroname, LineNumberNode, args...)
    Dict("src" => src, "parse" => "OK", "nargs" => length(args), "args" => [string(a) for a in args],
         "kinds" => [a isa Expr ? string(a.head) : string(typeof(a)) for a in args])
end
out = Dict("bodies" => [merge(one(b[2]), Dict("source" => b[1])) for b in bodies], "probes" => [one(p) for p in extra])
open(ARGS[2], "w") do io; JSON.print(io, out, 1); end
cnt = Dict{String,Int}()
for r in out["bodies"]; k = r["parse"] == "OK" ? "nargs=" * string(r["nargs"]) : r["parse"]; cnt[k] = get(cnt, k, 0) + 1; end
println("bodies -> ", cnt)
for r in out["probes"]; println(rpad(r["src"], 44), " | ", r["parse"], " | ", get(r, "nargs", ""), " | ", join(get(r, "args", [get(r, "msg", "")]), " ‖ ")); end
