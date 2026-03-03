using JSON

"""
py_exec_sync(code; timeout=5.0)

Execute `code` by asking the proxy kernel to run it in Python and return the parsed JSON reply.
The proxy recognizes a request of the form:
  println("__GGB_PY__<reply_path>__<code>")
and will write a JSON reply to `<reply_path>` when available.
"""
function py_exec_sync(code::AbstractString; timeout::Float64=5.0)
    reply = tempname()
    # send request with reply path
    println("__GGB_PY__" * reply * "__" * code)
    deadline = time() + timeout
    while time() < deadline
        if isfile(reply)
            s = read(reply, String)
            try
                rm(reply; force=true)
            catch
            end
            try
                return JSON.parse(s)
            catch
                return s
            end
        end
        sleep(0.02)
    end
    error("timeout waiting for python reply")
end

"""
Convenience wrapper for calling common ggblab functions implemented in the Python side.
Example:
  res = py_exec_sync("1+1")
"""
function py_eval(code::AbstractString; timeout::Float64=5.0)
    return py_exec_sync(code; timeout=timeout)
end
