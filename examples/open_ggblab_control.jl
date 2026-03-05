# open_ggblab_control.jl
# Helper to open a comm to the frontend target `jupyter.ggblab.control`
# with retries to avoid frontend-registration race conditions.

try
    using IJulia, JSON
    import IJulia: Comm
catch e
    @warn "IJulia/JSON not available: $e"
end

"""
open_ggblab_control(; target="jupyter.ggblab.control", retries=6, delay=0.5)

Attempt to create/open a comm to the frontend control target. Returns the
comm object on success or `nothing` on failure. This helper tries several
times with `sleep(delay)` between attempts to avoid the race where the
frontend hasn't registered the comm target yet.
"""
function open_ggblab_control(; target::AbstractString = "jupyter.ggblab.control", retries::Integer = 6, delay::Real = 0.5)
    for i in 1:retries
        try
            # Try a few ways to construct a Comm object
            c = nothing
            try
                c = IJulia.Comm(target)
            catch
                try
                    c = Comm(target)
                catch
                    c = nothing
                end
            end

            if c !== nothing
                # Optionally send a small ping to verify the comm is usable
                try
                    payload = JSON.json(Dict("type" => "ping", "id" => "jj_ping"))
                    # prefer IJulia.send if available
                    try
                        IJulia.send(c, payload)
                    catch
                        try
                            c.send(payload)
                        catch
                        end
                    end
                catch e
                    @warn "open_ggblab_control: ping send failed: $e"
                end
                return c
            end
        catch e
            @warn "open_ggblab_control attempt $i failed: $e"
        end
        sleep(delay)
    end
    @warn "open_ggblab_control: failed to open comm to $target after $retries attempts"
    return nothing
end

# Optional: auto-run when included for convenience (comment out if undesired)
# try
#     c = open_ggblab_control()
#     if c === nothing
#         @warn "open_ggblab_control: couldn't open control comm on include()"
#     else
#         println("Opened ggblab control comm: ", c)
#     end
# catch e
#     @warn "Auto-open failed: $e"
# end
