# Sweep every construction line (fixture + eg11/eg12) through Julia's own parser, as any `@ggb` Expr-macro must:
#   parse error?  Expr head?  and the round trip string(expr) vs the original text (what Julia would hand the macro).
using JSON
bodies = JSON.parsefile(ARGS[1])
probes = ["x^2", "2x", "y = 2x + 1", "y = 2 x + 1", "u v", "sqrt(u u)", "C'", "A' = l1(1)", "O'' = Intersect(f, g)", "A + B", "G = (A + B + C) / 3",
          "a(b)", "l1(1)", "x(A)", "f(x) = x^2", "n = Translate((u v) / (v v) v, P)", "n = Translate(Vector((((u * v)) / ((v * v)) * v)), P_{h})",
          "{Intersect(c, p)}", "l1 = {Intersect(c, p)}", "_7(1)", "Polygon(_1, _, __)", "G_{s} = \"(A_s + B_s + C_s) / 3\"", "s_{cw} = Segment(P_{c}, P_{w})",
          "α = Angle(A, B, C)", "sph1 = Sphere((0, 0, 1.8257), 0.6260)", "B = (cos(2π/5), sin(2π/5))", "C = (cos(-2π/5), sin(-2π/5))", "π/3", "A ≟ B", "x²", "3°",
          "a ≤ b", "Slider(0, 9, 1)", "SetValue(n, 0)", "Circle(:O, :A)", "Circle(O, A)", "k = Distance(a, F)", "Curve(x, x^2, x, -10, 10)", "Element(l, 1)",
          "h_1 = PerpendicularLine(P, yAxis, space)", "Circle(_1, 1)", "u = Vector(P_{h}, P)", "P'' = l7(1)", "1.0", "1", "-1", "(0, -1)", "\"text\"", "x = 2^3^2", "a/b*c"]
function classify(src, s)
    src == s && return "exact"
    replace(src, r"\s+" => "") == replace(s, r"\s+" => "") && return "ws"
    replace(src, r"[\s()]+" => "") == replace(s, r"[\s()]+" => "") && return "paren"
    return "other"
end
function one(src)
    ex = nothing
    try
        ex = Meta.parse(src)
    catch e
        return Dict("src" => src, "parse" => "ERROR", "msg" => first(sprint(showerror, e), 120))
    end
    if ex isa Expr && ex.head == :incomplete
        return Dict("src" => src, "parse" => "INCOMPLETE", "msg" => string(ex.args[1])[1:min(end, 120)])
    end
    s = string(ex)
    heads = String[]
    walk(x) = (x isa Expr && (push!(heads, string(x.head)); foreach(walk, x.args)); nothing)
    walk(ex)
    Dict("src" => src, "parse" => "OK", "head" => ex isa Expr ? string(ex.head) : string(typeof(ex)), "heads" => unique(heads), "unparse" => s, "class" => classify(src, s))
end
out = Dict("bodies" => [merge(one(b[2]), Dict("source" => b[1])) for b in bodies], "probes" => [one(p) for p in probes])
open(ARGS[2], "w") do io; JSON.print(io, out, 1); end
n = length(out["bodies"]); cnt = Dict{String,Int}()
for r in out["bodies"]; k = r["parse"] == "OK" ? r["class"] : r["parse"]; cnt[k] = get(cnt, k, 0) + 1; end
println("bodies ", n, " -> ", cnt)
for r in out["probes"]; println(rpad(r["src"], 62), " | ", r["parse"], " | ", get(r, "class", ""), " | ", get(r, "unparse", get(r, "msg", ""))); end
