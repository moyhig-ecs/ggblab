# Offline tests of the Julia package (no browser, no jupyter_server). The byte-for-byte parity with the Python host
# (request JSON, mount JavaScript, the parser's output) is checked from Python by tests/test_julia_*_parity.py.
using Test
using GGBLab

@testset "GGBLab (offline)" begin
    @testset "host" begin
        @test GGBLab.GGBLabHost.kernel_id() == ""                       # outside an IJulia kernel
        r = request(:eval; commands=["A = (1, 2)"], req_id="r1")
        @test r["kind"] == "eval" && r["commands"] == ["A = (1, 2)"] && r["req_id"] == "r1"
        @test Set(request(k)["kind"] for k in (:eval, :new, :delete, :xml_in, :xml_out, :value, :kind, :listen)) ==
              Set(["eval", "new", "delete", "xml_in", "xml_out", "value", "kind", "listen"])   # the closed subset of 8
        @test_throws ErrorException request(:api)                         # not a verb
        @test GGBLab.GGBLabHost.without_gui("<geogebra>\n<gui>\n<window/>\n</gui>\n<euclidianView/>\n</geogebra>") ==
              "<geogebra>\n<euclidianView/>\n</geogebra>"
        @test GGBLab.GGBLabHost.without_gui("<geogebra><gui/><a/></geogebra>") == "<geogebra><a/></geogebra>"
        p = GGBLab.GGBLabHost.mount_js_path()                              # the one JavaScript, wherever the package lives
        @test isfile(p) && occursin("__CFG__", read(p, String)) && occursin("pollLoop", read(p, String))
    end

    @testset "macro (PythonCall + the ggblab Python package)" begin
        ok = try
            GGBLab.GGBLabMacro._parse_mod(); true
        catch
            # the source tree: make the repository root importable and try once more
            try
                GGBLab.GGBLabMacro.pyimport("sys").path.append(normpath(joinpath(@__DIR__, "..", "..")))
                GGBLab.GGBLabMacro._PARSE[] = nothing
                GGBLab.GGBLabMacro._parse_mod(); true
            catch
                false
            end
        end
        if ok
            c = ggb"""
            A = (0, 0)
            c = Circle(:A, 1)
            """
            @test to_ggb(c) == ["A = (0, 0)", "c = Circle(A, 1)"]
            @test labels(c) == ["A", "c"]
            @test_throws ClosedWorldError parse_ggb("Cylinder(A, B, 1)")   # outside the closed world (28 heads)
            @test flatten_labels([["t1,c", "a"], nothing]) == ["t1", "c", "a", nothing]
        else
            @test_skip "the Python package ggblab is not importable from PythonCall"
        end
    end
end
