function expr_to_cmd_string(ex)
    if ex isa QuoteNode
        v = ex.value
        if isa(v, Symbol)
            return string(v)
        elseif isa(v, String)
            return v
        else
            return string(v)
        end
    elseif ex isa Symbol
        return string(ex)
    elseif ex isa Expr
        # call expression
        if ex.head == :call && length(ex.args) >= 1
            fn_raw = ex.args[1]
            # Handle common infix/binary operators using conventional notation
            op = isa(fn_raw, Symbol) ? string(fn_raw) : ""
            if op in ("+", "-", "*", "/", "^", "==", "<", ">", "<=", ">=", "!=", "&", "|", "%")
                nargs = length(ex.args) - 1
                # unary minus
                if op == "-" && nargs == 1
                    return "-" * expr_to_cmd_string(ex.args[2])
                end
                parts = [expr_to_cmd_string(a) for a in ex.args[2:end]]
                if nargs == 2
                return "(" * join(parts[1:2], " " * op * " ") * ")"
                else
                    # chain multiple operands: a + b + c
                    return join(parts, " " * op * " ")
                end
            else
                # regular function-style call: name(arg1, arg2, ...)
                fname = expr_to_cmd_string(fn_raw)
                parts = [expr_to_cmd_string(a) for a in ex.args[2:end]]
                return fname * "(" * join(parts, ", ") * ")"
            end
        elseif ex.head == :vect
            parts = [expr_to_cmd_string(a) for a in ex.args]
            return "{" * join(parts, ", ") * "}"
        else
            try
                return string(ex)
            catch
                return string(ex)
            end
        end
    else
        return string(ex)
    end
end
