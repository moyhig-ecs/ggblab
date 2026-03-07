"""IPython magics for executing GeoGebra commands via ``ggb.command``.

This module provides two magics:

- ``%ggb``: line magic variant
- ``%%ggb``: cell magic variant

Behavior highlights:
- When running inside an active asyncio event loop the commands are
    scheduled as background tasks; otherwise they are executed
    synchronously.
- Variable/token expansion and frontend-side `{var}` expansion are
    performed by the IPython frontend; this module does not attempt to
    emulate or re-run those expansions.
- Quoted multiline tokens passed on the line (for example
    ``%ggb '(0,0)\nCircle(_1,1)\n'``) are detected and moved to the
    cell body so they are parsed as multi-line GeoGebra commands.
- When async tasks complete, results are published through IPython's
    `displayhook` so they appear in the notebook output and are stored
    in the `Out` mapping; a best-effort fallback also assigns ``_``.
"""

import ast
import asyncio
import os
import re
from typing import List, Optional, Tuple

from IPython import get_ipython

from .errors import GeoGebraAppletError
from .ggbapplet import GeoGebra

# Build a mapping of ascii names -> unicode Greek symbol names from sympy.abc._clash2
_GREEK_MAP = None
_GREEK_RE = None


def _build_greek_map():
    global _GREEK_MAP, _GREEK_RE
    # print("Building Greek symbol mapping from sympy...")
    if _GREEK_MAP is not None:
        return
    _GREEK_MAP = {}
    try:
        # Import lazily to avoid hard dependency if sympy is not installed
        import sympy

        core = getattr(sympy, "core", None)
        alphabets = getattr(core, "alphabets", None)
        greeks = getattr(alphabets, "greeks", None)
        # print(f"Found {len(greeks) if greeks else 0} sympy greek symbols for mapping")
        if greeks:
            import unicodedata as _ud

            for name in greeks:
                # print("sympy greek symbol:", s)
                # name = str(s)
                # small letter: map 'alpha' -> 'α'
                try:
                    small = _ud.lookup(f"GREEK SMALL LETTER {name.upper()}")
                    # print(f"Mapping {name} -> {small}")
                    _GREEK_MAP[name] = small
                except Exception:
                    pass
                # capital forms: map 'Alpha' and 'ALPHA' -> 'Α'
                try:
                    cap = _ud.lookup(f"GREEK CAPITAL LETTER {name.upper()}")
                    # print(f"Mapping {name.capitalize()} and {name.upper()} -> {cap}")
                    _GREEK_MAP[name.capitalize()] = cap
                    _GREEK_MAP[name.upper()] = cap
                except Exception:
                    pass
    except Exception:
        _GREEK_MAP = {}
    # print(f"Built Greek symbol mapping with {len(_GREEK_MAP)} entries")
    # compile regex for whole-word substitution if any mappings exist
    try:
        if _GREEK_MAP:
            import re as _re

            pattern = (
                r"\b(?:" + "|".join(_re.escape(k) for k in _GREEK_MAP.keys()) + r")\b"
            )
            _GREEK_RE = _re.compile(pattern)
    except Exception:
        _GREEK_RE = None


# Runtime debug toggle: enable with env `GGBLAB_IPYMAGIC_DEBUG=1`
# or by setting `_ggb_debug=True` in IPython's `user_ns`.
_DEBUG = os.environ.get("GGBLAB_IPYMAGIC_DEBUG", "") not in ("", "0", "False", "false")


def _dbg(*a, **kw):
    try:
        if not a:
            return
        # If caller passed a format string plus args, format it like printf
        if isinstance(a[0], str) and len(a) > 1:
            try:
                msg = a[0] % tuple(a[1:])
            except Exception:
                try:
                    msg = a[0].format(*a[1:])
                except Exception:
                    msg = " ".join(str(x) for x in a)
        else:
            msg = " ".join(str(x) for x in a)

        if _DEBUG:
            print(msg, **kw)
            return
        ip_ = get_ipython()
        if ip_ is None:
            return
        ns_ = getattr(ip_, "user_ns", None)
        if isinstance(ns_, dict) and ns_.get("_ggb_debug"):
            print(msg, **kw)
    except Exception:
        pass


def _strip_outer_quotes(s: str) -> str:
    try:
        s2 = s.strip()
        if (s2.startswith("'") and s2.endswith("'")) or (
            s2.startswith('"') and s2.endswith('"')
        ):
            return s2[1:-1].strip()
        return s2
    except Exception:
        return s


def _clean_cmd_line(ln: str) -> str:
    """Normalize a single command line extracted from a multi-line variable.

    Normalization performed:
    - strip surrounding whitespace
    - remove full-line or inline comments (``#``)
    - preserve brace-wrapped lines (``{...}``) verbatim — do not unwrap
      them here because some producers emit brace-wrapped GeoGebra
      commands that should be passed unchanged to the applet.
    - remove surrounding quotes if present
    - return empty string for comments/blank
    """
    try:
        ln2 = ln.strip()
        if not ln2 or ln2.startswith("#"):
            return ""
        ln3 = ln2.split("#", 1)[0].strip()
        # Preserve lines wrapped in braces `{...}` verbatim.
        # ConstructionIO.commands_for_magic may emit brace-wrapped lines
        # that are intended to be passed directly to GeoGebra rather than
        # treated as variable expansion markers. Do not unwrap them here.
        ln3 = _strip_outer_quotes(ln3)
        return ln3.strip()
    except Exception:
        return ""


def _serialize_for_ggb(obj):
    """Recursively convert Python lists/tuples (including objects
    exposing `tolist()`, e.g. sympy.Matrix or numpy arrays) to
    GeoGebra-style brace notation. Strings are returned as-is.
    """
    try:
        # If object has a `.shape` like (n, 1) treat it as a column vector
        # and serialize as GeoGebra Vector((...)) before any tolist() conversion.
        try:
            shape = getattr(obj, "shape", None)
            if isinstance(shape, (tuple, list)) and len(shape) >= 2 and shape[1] == 1:
                # Attempt to obtain Python list representation
                lst = None
                if (
                    not isinstance(obj, str)
                    and hasattr(obj, "tolist")
                    and callable(getattr(obj, "tolist"))
                ):
                    try:
                        lst = obj.tolist()
                    except Exception:
                        lst = None
                else:
                    try:
                        lst = list(obj)
                    except Exception:
                        lst = None

                if lst is not None:
                    try:
                        # Flatten column vector rows like [x], (x,) -> x
                        vals = [
                            (
                                row[0]
                                if (isinstance(row, (list, tuple)) and len(row) > 0)
                                else row
                            )
                            for row in lst
                        ]
                    except Exception:
                        vals = lst
                    parts = [_serialize_for_ggb(x) for x in vals]
                    return "Vector((" + ",".join(parts) + "))"
        except Exception:
            pass

        # If the object exposes `tolist()`, prefer converting it to
        # Python lists first so nested matrices/arrays serialize correctly.
        if (
            not isinstance(obj, str)
            and hasattr(obj, "tolist")
            and callable(getattr(obj, "tolist"))
        ):
            try:
                obj = obj.tolist()
            except Exception:
                pass

        if isinstance(obj, (list, tuple)):
            # Detect NaN-like elements before serializing parts so we can
            # normalize ['nan'] or [nan] -> {}. Use a robust check that
            # handles float('nan'), numpy.nan, sympy.nan, or the string 'nan'.
            def _is_nan_val(v):
                try:
                    import math

                    if isinstance(v, float) and math.isnan(v):
                        return True
                except Exception:
                    pass
                try:
                    # numpy floats
                    import numpy as _np

                    if isinstance(v, (_np.floating,)) and _np.isnan(v):
                        return True
                except Exception:
                    pass
                try:
                    # sympy.nan comparison
                    from sympy import nan as _s_nan

                    if v is _s_nan or v == _s_nan:
                        return True
                except Exception:
                    pass
                try:
                    if isinstance(v, str) and v.lower() == "nan":
                        return True
                except Exception:
                    pass
                return False

            # If the python-level list contains only NaN-like values, render as '{}'
            try:
                if len(obj) == 1 and _is_nan_val(obj[0]):
                    return "{}"
                if obj and all(_is_nan_val(x) for x in obj):
                    return "{}"
            except Exception:
                pass

            parts = [_serialize_for_ggb(x) for x in obj]
            return "{" + ",".join(parts) + "}"
        if isinstance(obj, str):
            # Treat GeoGebra brace placeholders like '{?}' or '{nan}' as empty
            # sets so we don't emit '{nan}' back to the applet. Match either
            # '?' or 'nan' (case-insensitive) possibly repeated like '{?,?}'.
            try:
                if re.match(
                    r"^\{\s*(?:\?|nan)(?:\s*,\s*(?:\?|nan))*\s*\}$",
                    obj,
                    flags=re.IGNORECASE,
                ):
                    return "{}"
            except Exception:
                pass
            # encode ascii greek names to unicode greek if mapping available
            try:
                _build_greek_map()
                if _GREEK_RE and _GREEK_MAP:

                    def _enc(m):
                        return _GREEK_MAP.get(m.group(0), m.group(0))

                    return _GREEK_RE.sub(_enc, obj)
            except Exception:
                pass
            return obj
        # Fallback: convert to string and run mapping as well
        s = str(obj)
        try:
            _build_greek_map()
            if _GREEK_RE and _GREEK_MAP:

                def _enc2(m):
                    return _GREEK_MAP.get(m.group(0), m.group(0))

                return _GREEK_RE.sub(_enc2, s)
        except Exception:
            pass
        return s
    except Exception:
        try:
            return str(obj)
        except Exception:
            return ""


def _safe_eval(expr: str, user_ns: dict):
    """Evaluate simple expressions (names, attribute access, indexing,
    and simple literals) against `user_ns`. Uses AST validation to
    prevent execution of calls or complex constructs.
    Returns the evaluated value or raises an exception on failure.
    """
    node = ast.parse(expr, mode="eval")

    def _is_safe(n):
        # Expression wrapper
        if isinstance(n, ast.Expression):
            return _is_safe(n.body)
        # Names and literals
        if isinstance(n, ast.Name):
            return True
        if isinstance(n, ast.Constant):
            return True
        # older py versions
        if hasattr(ast, "Num") and isinstance(n, ast.Num):
            return True
        if hasattr(ast, "Str") and isinstance(n, ast.Str):
            return True
        # Attribute access and subscripts
        if isinstance(n, ast.Attribute):
            return _is_safe(n.value)
        if isinstance(n, ast.Subscript):
            return _is_safe(n.value) and _is_safe(n.slice)
        if isinstance(n, ast.Index):
            return _is_safe(n.value)
        if isinstance(n, ast.Slice):
            ok = True
            for a in (n.lower, n.upper, n.step):
                if a is not None and not _is_safe(a):
                    ok = False
                    break
            return ok
        if isinstance(n, (ast.Tuple, ast.List)):
            return all(_is_safe(e) for e in n.elts)
        # Allow simple unary/binary numeric ops
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return _is_safe(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(
            n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
        ):
            return _is_safe(n.left) and _is_safe(n.right)
        return False

    if not _is_safe(node):
        raise ValueError("unsafe expression")
    # Evaluate with user_ns as locals to resolve names
    return eval(compile(node, "<ipymagic>", "eval"), {}, user_ns)


async def _run_commands_async(cmds: List[str], ggb_instance: Optional[GeoGebra] = None):
    # Prefer an explicitly-supplied instance. If none provided, ensure the
    # module behaves like the magic registration helper and create/store a
    # GeoGebra singleton in the IPython user namespace so callers have a
    # consistent `ggb` binding and a single shared instance per kernel.
    if ggb_instance is not None:
        ggb = ggb_instance
    else:
        prev_inst = getattr(GeoGebra, "_instance", None)
        try:
            ip = get_ipython()
            user_ns = getattr(ip, "user_ns", None) if ip is not None else None
        except Exception:
            user_ns = None
        try:
            ggb = GeoGebra()
            # If the user namespace is available and doesn't already have
            # a `ggb` binding, store the created singleton there and print
            # a notification (best-effort).
            try:
                if isinstance(user_ns, dict) and "ggb" not in user_ns:
                    user_ns["ggb"] = ggb
                    # After creating and storing the singleton, eagerly
                    # initialize it so callers (including `ggb.function`) can
                    # use the applet immediately without waiting for later
                    # initialization steps.
                    try:
                        if not getattr(ggb, "initialized", False):
                            try:
                                await ggb.init()
                            except Exception:
                                # initialization is best-effort here
                                pass
                    except Exception:
                        pass
                    if prev_inst is None:
                        try:
                            print(
                                "[ggblab] created GeoGebra singleton and stored as 'ggb' in user namespace"
                            )
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            # Fallback: attempt a plain construction; GeoGebra.__new__ enforces singleton
            ggb = GeoGebra()
    if not getattr(ggb, "initialized", False):
        try:
            await ggb.init()
        except Exception:
            # If init fails, continue and let command raise later
            pass
    results: List[str] = []

    def _stringify(v) -> str:
        if isinstance(v, str):
            # If GeoGebra returns a comma-separated multi-value string
            # (e.g. Polygon returns like "t1,e,a,d") and it's not a
            # function-like expression, prefer the first token.
            if "," in v and "(" not in v and ")" not in v:
                return v.split(",", 1)[0].strip()
            return v
        if isinstance(v, dict):
            if "label" in v:
                return str(v["label"])
            if "result" in v:
                return str(v["result"])
            return str(v)
        if isinstance(v, (list, tuple)):
            return _stringify(v[0]) if v else ""
        return str(v)

    # Pattern matches either a numeric form like '_2' (group 1) or a run
    # of underscores like '__' (group 2, includes all underscores). Numeric form takes precedence.
    # Do not match underscores that are immediately preceded by a word
    # character or an apostrophe (to exclude primed names like F'_2).
    token_re = re.compile(r"(?<![\w'])(?:_(\d+)|(_+))(?!\w)")

    for c in cmds:
        if not c or not c.strip():
            continue

        # Replace tokens with previous results when available
        def _repl(m):
            # If numeric form is present (e.g. '_3'), treat as the N-th result (1-based).
            # If underscore run (e.g. '__') is present, treat as N previous (as before).
            digits = m.group(1)
            underscores = m.group(2)
            if digits:
                try:
                    n = int(digits)
                except Exception:
                    return m.group(0)
                # n is 1-based index into results
                if 1 <= n <= len(results):
                    return _stringify(results[n - 1])
                return m.group(0)
            elif underscores:
                k = len(underscores)
                if len(results) >= k:
                    return _stringify(results[-k])
                return m.group(0)
            else:
                # single '_' -> last
                if len(results) >= 1:
                    return _stringify(results[-1])
                return m.group(0)

        try:
            c_to_send = token_re.sub(_repl, c)
        except Exception:
            c_to_send = c

        try:
            r = await ggb.command(c_to_send)
            # print(f"ggb.command({c_to_send!r}) -> {r!r}")
            # If the applet returned None, do not record it in the results list
            if r is None:
                continue
            # If GeoGebra returned multiple values packed in a string
            # (comma-separated) or as a list/tuple, push each item into
            # the results "register" so tokens like _1, _2 can access
            # subsequent values. Otherwise append the single result.
            try:
                if isinstance(r, str) and "," in r and "(" not in r and ")" not in r:
                    parts = [p.strip() for p in r.split(",")]
                    for p in parts:
                        results.append(p)
                elif isinstance(r, (list, tuple)):
                    for item in r:
                        # skip explicit None entries
                        if item is None:
                            continue
                        results.append(item)
                else:
                    results.append(r)
            except Exception:
                results.append(r)
        except Exception as e:
            # If the applet raised a GeoGebraAppletError, stop executing any
            # further commands and report only this first error back to the
            # caller (suppress subsequent errors).
            is_applet_error = (
                isinstance(e, GeoGebraAppletError)
                or type(e).__name__ == "GeoGebraAppletError"
            )
            print(f"ggb.command failed for: {c_to_send!r} -> {type(e).__name__}: {e}")
            if is_applet_error:
                # Replace results with a single error entry and stop processing
                results = [{"error": str(e)}]
                break
            else:
                # Non-applet errors: record and continue
                results.append({"error": str(e)})

    # Convert results to strings as the user expects a list of strings
    try:
        str_results = [_stringify(x) for x in results]
    except Exception:
        str_results = [str(x) for x in results]
    return str_results


def _parse_commands(line: str, cell: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Parse magic arguments.

    Returns tuple (instance_name_or_None, list_of_commands).

    Behavior changes:
    - For cell magics, ignore lines that start with `#` and strip trailing
      inline comments after `#`.
    - For line magics, strip trailing inline comments and allow an optional
      instance name as the first token.
    """
    # Note: this parser also accepts a quoted token on the line that
    # contains embedded newlines (real or escaped) and promotes that
    # quoted content to the `cell` argument so callers can pass a
    # multi-line command block as a single-line token. Frontends that
    # perform `{var}` expansion will already have expanded braces; the
    # magic does not attempt to re-run content-matching logic.

    def _strip_comment(s: str) -> str:
        s2 = s.split("#", 1)[0]
        return s2.rstrip()

    instance = None
    # If the caller provided a line that contains a quoted string with
    # literal `\n` sequences (e.g. "%ggb '(0,0)\nCircle(_1,1)\n'"),
    # treat that quoted string as the cell contents and remove it from
    # the line. IPython frontends may pass such quoted literals and we
    # should convert them into real newlines for cell parsing.
    if cell is None and line:
        try:
            s = line
            i = 0
            found = False
            while i < len(s):
                if s[i] in ("'", '"'):
                    quote = s[i]
                    j = i + 1
                    while j < len(s):
                        if s[j] == quote and s[j - 1] != "\\":
                            # candidate quoted segment
                            inner = s[i + 1 : j]
                            # Detect either real newlines or escaped '\\n' sequences
                            if "\\n" in inner or "\n" in inner:
                                # Normalize escaped sequences into real newlines
                                inner2 = (
                                    inner.replace("\\r\\n", "\r\n")
                                    .replace("\\n", "\n")
                                    .replace("\\r", "\r")
                                )
                                cell = inner2
                                # remove the quoted portion from the line
                                line = (s[:i] + s[j + 1 :]).strip()
                                found = True
                            break
                        j += 1
                    if found:
                        break
                    i = j
                else:
                    i += 1
        except Exception:
            # If anything goes wrong, leave `cell` unchanged
            pass

    _dbg("[ggb-magic-debug] parsing line=%r cell=%r", line, cell)

    if cell is not None:
        # cell magic: first token on the line may be an instance name
        parts = line.split(None, 1)
        if parts:
            instance = parts[0]
        cmds = []
        try:
            ip = get_ipython()
            user_ns = getattr(ip, "user_ns", {}) if ip is not None else {}
        except Exception:
            user_ns = {}
        for ln in cell.splitlines():
            ln2 = ln.strip()
            if not ln2:
                continue
            if ln2.startswith("#"):
                # ignore full-line comments
                continue
            # strip inline comments
            cmd = _strip_comment(ln2)
            if not cmd:
                continue

            # # Preserve verbatim brace-wrapped lines (e.g. `{...}`), do not expand them
            # cmd_stripped = cmd.strip()
            # if re.match(r'^\{\s*.*\s*\}$', cmd_stripped):
            #     print(f"Preserving verbatim brace-wrapped line: {cmd_stripped!r}")
            #     cmds.append(cmd_stripped)
            #     continue

            # Expand {var} occurrences using IPython user namespace when available.
            # Use module-level `_serialize_for_ggb` for serializing Python
            # lists/tuples (and objects exposing `tolist()`) into GeoGebra
            # brace notation.
            def _expand_var(m):
                expr = m.group(1).strip()
                try:
                    # Try to evaluate complex expressions (indexing/attr access)
                    val = (
                        _safe_eval(expr, user_ns)
                        if isinstance(user_ns, dict)
                        else _safe_eval(expr, {})
                    )
                except Exception:
                    # Fallback: if it's a simple identifier, look it up
                    if (
                        re.match(r"^[A-Za-z_]\w*$", expr)
                        and isinstance(user_ns, dict)
                        and expr in user_ns
                    ):
                        val = user_ns[expr]
                    else:
                        return m.group(0)
                try:
                    return _serialize_for_ggb(val)
                except Exception:
                    try:
                        return str(val)
                    except Exception:
                        return m.group(0)

            try:
                # Match any expression inside braces (non-greedy) and expand
                # using the safe evaluator which supports indexing/attribute access.
                # Do not expand brace groups that are immediately preceded by an
                # underscore (subscript syntax like `O_{4}`), to preserve those
                # grouping braces for GeoGebra identifiers.
                cmd = re.sub(r"(?<!_)\{\s*([^}]+?)\s*\}", _expand_var, cmd)
            except Exception:
                pass
            if cmd:
                cmds.append(cmd)
        # print(f"Parsed instance={instance!r} cmds={cmds!r}")
        return instance, cmds

    # line magic: allow "instance command..." or just "command"
    raw = line or ""
    raw = raw.strip()
    if not raw:
        return None, []
    # remove inline comment
    raw_nocom = _strip_comment(raw)
    parts = raw_nocom.split(None, 1)
    if not parts:
        return None, []
    if len(parts) == 1:
        # single token - treat as command
        return None, [parts[0]]
    inst_candidate, rest = parts[0], parts[1]
    if inst_candidate.isidentifier():
        return inst_candidate, [rest]
    return None, [raw_nocom]


def register_ggb_magic(ipython=None):
    """Register `%ggb` and `%%ggb` magics with the provided IPython instance.

    The magics schedule execution of commands and return an asyncio.Task
    when used inside an async event loop, otherwise they block and return
    the results list.
    """
    if ipython is None:
        ipython = get_ipython()
    if ipython is None:
        return

    def _get_or_create_ggb(user_ns, ip, *, for_api: bool = False):
        """Return an existing GeoGebra instance or create a singleton.

        If a new instance is created, store it in `user_ns['ggb']` when
        appropriate and print a single user notification. The `for_api`
        flag adjusts the notification message for the api-call path.
        """
        try:
            inst = getattr(GeoGebra, "_instance", None)
        except Exception:
            inst = None
        created = False
        if inst is None:
            try:
                inst = GeoGebra()
                created = True
            except Exception:
                try:
                    inst = getattr(GeoGebra, "_instance", None)
                except Exception:
                    inst = None
                if inst is None:
                    inst = GeoGebra()
                    created = True
        try:
            if isinstance(user_ns, dict) and "ggb" not in user_ns:
                user_ns["ggb"] = inst
        except Exception:
            pass
        if created:
            try:
                if for_api:
                    print("[ggblab] created GeoGebra singleton for api call")
                else:
                    print(
                        "[ggblab] created GeoGebra singleton and stored as 'ggb' in user namespace"
                    )
            except Exception:
                pass
        return inst

    def _ggb_magic(line, cell=None):
        inst_name, cmds = _parse_commands(line, cell)
        # If the magic was invoked with a single token (identifier or {identifier}),
        # treat that token as a variable name whose value contains the commands
        # (string with newlines) or a list of command strings.
        try:
            ip = get_ipython()
            user_ns = getattr(ip, "user_ns", {}) if ip is not None else {}
        except Exception:
            user_ns = {}

        if cell is None and isinstance(cmds, list) and len(cmds) == 1:
            raw_tok = cmds[0].strip() if cmds[0] is not None else ""
            # normalize token by removing outer quotes if present
            raw_tok_str = _strip_outer_quotes(raw_tok)
            # allow both `{name}` and `name`
            var_match = None
            try:
                var_match = __import__("re").match(
                    r"^\{\s*([A-Za-z_]\w*)\s*\}$", raw_tok
                )
            except Exception:
                var_match = None
            # Only expand the brace form `{name}`. Do NOT expand a bare
            # identifier like `%ggb name`.
            if var_match:
                varname = var_match.group(1)
            else:
                varname = None

            # Debug: show token parsing result (compact preview + metrics)
            try:
                ns_info = f"{len(user_ns)} names" if isinstance(user_ns, dict) else None
                tok_preview = (
                    (raw_tok.replace("\n", "\\n")[:120])
                    if isinstance(raw_tok, str)
                    else repr(raw_tok)[:120]
                )
                raw_preview = (
                    (raw_tok_str.replace("\n", "\\n")[:120])
                    if isinstance(raw_tok_str, str)
                    else repr(raw_tok_str)[:120]
                )
                tok_len = len(raw_tok) if hasattr(raw_tok, "__len__") else 0
                tok_lines = raw_tok.count("\n") + 1 if isinstance(raw_tok, str) else 0
                _dbg(
                    "[ggb-magic-debug] token_preview=%r len=%d lines=%d raw_preview=%r varname=%r user_ns=%r",
                    tok_preview,
                    tok_len,
                    tok_lines,
                    raw_preview,
                    varname,
                    ns_info,
                )
            except Exception:
                pass

            # Note: IPython performs `{var}` expansion in frontends; do not
            # attempt to emulate expansion here by matching token contents
            # against `user_ns`. Only accept explicit `{name}` brace form.

            if varname and varname in user_ns:
                val = user_ns[varname]
                if isinstance(val, str):
                    v2 = _strip_outer_quotes(val.strip())
                    # Prepare debug raw preview (convert literal \n to escaped form)
                    try:
                        raw_preview = v2.replace("\\n", "\n")
                    except Exception:
                        raw_preview = v2
                    new_cmds = []
                    for ln in v2.splitlines():
                        cleaned = _clean_cmd_line(ln)
                        if cleaned:
                            new_cmds.append(cleaned)
                    # Compact debug: show line/command counts and short preview
                    try:
                        lines = raw_preview.splitlines()
                        preview = raw_preview.replace("\n", "\\n")[:120]
                        sample = new_cmds[:5]
                        _dbg(
                            "[ggb-magic-debug] expanded %r: %d lines, %d cmds, preview=%r, sample=%r",
                            varname,
                            len(lines),
                            len(new_cmds),
                            preview,
                            sample,
                        )
                        if len(new_cmds) > 5:
                            _dbg(
                                "[ggb-magic-debug] expanded %r: showing first %d of %d cmds",
                                varname,
                                5,
                                len(new_cmds),
                            )
                    except Exception:
                        pass
                    if new_cmds:
                        inst_name = None
                        cmds = new_cmds
                elif isinstance(val, (list, tuple)):
                    try:
                        cmds = [str(x) for x in val if x is not None]
                        inst_name = None
                        # already logged a compact summary above
                    except Exception:
                        pass
        ggb_instance = None
        ip = get_ipython()
        user_ns = getattr(ip, "user_ns", {}) if ip is not None else {}
        if inst_name:
            if inst_name in user_ns:
                maybe = user_ns[inst_name]
                if isinstance(maybe, GeoGebra):
                    ggb_instance = maybe
            else:
                # If the user provided an instance name but it's not present
                # in the user namespace, check whether a class-level singleton
                # exists and use it (treat the provided name as an alias
                # referring to the singleton). This handles cases like
                # "%ggb ggb '(...)'" where `ggb` is the well-known
                # singleton rather than an explicit variable in `user_ns`.
                try:
                    inst = getattr(GeoGebra, "_instance", None)
                    if isinstance(inst, GeoGebra):
                        ggb_instance = inst
                except Exception:
                    pass
        else:
            # No explicit name provided: try to find any GeoGebra instance in user namespace
            try:
                for v in user_ns.values():
                    if isinstance(v, GeoGebra):
                        ggb_instance = v
                        break
            except Exception:
                ggb_instance = None
            # If still not found, prefer class-level singleton if available
            if ggb_instance is None:
                try:
                    inst = getattr(GeoGebra, "_instance", None)
                    if isinstance(inst, GeoGebra):
                        ggb_instance = inst
                except Exception:
                    pass
        # Ensure 'ggb' exists in `user_ns` when we create or reuse the singleton.
        try:
            if ggb_instance is None and ip is not None and isinstance(user_ns, dict):
                ggb_instance = _get_or_create_ggb(user_ns, ip, for_api=False)
        except Exception:
            pass
        # Debug: show resolved instance
        try:
            _dbg(
                "[ggb-magic-debug] resolved ggb_instance_source=%r ggb_instance=%r",
                getattr(ggb_instance, "__class__", None),
                ggb_instance,
            )
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        # Special-case API invocation using syntax: `%ggb api getValue(A)`
        # or `%ggb api getValue [A,B]` where 'api' is the first token (inst_name).
        if inst_name == "api" and cmds:
            expr = cmds[0].strip()
            # parse function name and args
            m = __import__("re").match(
                r"^\s*([A-Za-z_]\w*)(?:\s*(?:\((.*)\)|\[(.*)\]))?\s*$", expr
            )
            if m:
                fname = m.group(1)
                args_text = m.group(2) if m.group(2) is not None else (m.group(3) or "")
                if args_text.strip() == "":
                    args_list = []
                else:
                    args_list = [a.strip() for a in args_text.split(",") if a.strip()]

                # Ensure we have a GeoGebra instance
                if ggb_instance is None:
                    try:
                        ggb_instance = _get_or_create_ggb(user_ns, ip, for_api=True)
                    except Exception:
                        # Fallback: create without notification
                        try:
                            ggb_instance = GeoGebra()
                        except Exception:
                            ggb_instance = None

                if loop is None:
                    # synchronous call: ensure instance is initialized first
                    try:
                        if not getattr(ggb_instance, "initialized", False):
                            try:
                                asyncio.run(ggb_instance.init())
                            except Exception:
                                # best-effort initialization
                                pass
                        return asyncio.run(ggb_instance.function(fname, args_list))
                    except Exception as e:
                        print("ggb api call failed:", e)
                        return None
                else:
                    # schedule and store task; ensure init runs before function
                    async def _init_then_call():
                        try:
                            if not getattr(ggb_instance, "initialized", False):
                                try:
                                    await ggb_instance.init()
                                except Exception:
                                    pass
                            return await ggb_instance.function(fname, args_list)
                        except Exception:
                            # propagate to task result handling
                            raise

                    task = loop.create_task(_init_then_call())
                    try:
                        ip = get_ipython()
                        if ip is not None:
                            ns = getattr(ip, "user_ns", None)
                            if isinstance(ns, dict):
                                ns["_ggb_last_task"] = task

                                def _done_cb(t):
                                    try:
                                        res = t.result()
                                    except Exception:
                                        res = None
                                    try:
                                        ip2 = get_ipython()
                                    except Exception:
                                        ip2 = None
                                    try:
                                        if ip2 is not None:
                                            ip2.displayhook(res)
                                            return
                                    except Exception:
                                        pass
                                    try:
                                        ns["_"] = res
                                    except Exception:
                                        pass
                                    try:
                                        if ip2 is not None:
                                            ns2 = getattr(ip2, "user_ns", None)
                                            if isinstance(ns2, dict):
                                                out = ns2.get("Out")
                                                if isinstance(out, dict):
                                                    count = getattr(
                                                        ip2, "execution_count", None
                                                    )
                                                    if isinstance(count, int):
                                                        out[count] = res
                                    except Exception:
                                        pass

                                try:
                                    task.add_done_callback(_done_cb)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    return None

        # Default: run regular command sequence via coroutine
        coro = _run_commands_async(cmds, ggb_instance=ggb_instance)
        if loop is None:
            # No running loop: run synchronously
            try:
                return asyncio.run(coro)
            except Exception as e:
                print("ggb magic execution failed:", e)
                return None
        else:
            # Running loop available: schedule task and do not echo it in the cell.
            # Save the Task in the IPython user namespace under `_ggb_last_task`
            task = loop.create_task(coro)
            try:
                ip = get_ipython()
                if ip is not None:
                    ns = getattr(ip, "user_ns", None)
                    if isinstance(ns, dict):
                        ns["_ggb_last_task"] = task

                    # When the task finishes, capture its result into IPython's
                    # underscore (`_`) variable so users can reference it.
                    def _done_cb(t):
                        try:
                            res = t.result()
                        except Exception:
                            res = None
                        try:
                            ip2 = get_ipython()
                        except Exception:
                            ip2 = None
                        try:
                            if ip2 is not None:
                                ip2.displayhook(res)
                                return
                        except Exception:
                            pass
                        try:
                            ns["_"] = res
                        except Exception:
                            pass
                        try:
                            if ip2 is not None:
                                ns2 = getattr(ip2, "user_ns", None)
                                if isinstance(ns2, dict):
                                    out = ns2.get("Out")
                                    if isinstance(out, dict):
                                        count = getattr(ip2, "execution_count", None)
                                        if isinstance(count, int):
                                            out[count] = res
                        except Exception:
                            pass

                    try:
                        task.add_done_callback(_done_cb)
                    except Exception:
                        # Some event loops/tasks may not support add_done_callback
                        pass
            except Exception:
                pass
            # Return None so IPython does not echo the Task object in the cell output
            return None

    # Register both line and cell variants and an alias `ggblab`
    ipython.register_magic_function(_ggb_magic, "line", "ggb")
    ipython.register_magic_function(_ggb_magic, "cell", "ggb")
    try:
        ipython.register_magic_function(_ggb_magic, "line", "ggblab")
        ipython.register_magic_function(_ggb_magic, "cell", "ggblab")
    except Exception:
        # ignore if registration of alias fails
        pass


def unregister_ggb_magic(ipython=None):
    if ipython is None:
        ipython = get_ipython()
    if ipython is None:
        return
    try:
        ipython.magics_manager.registry.pop("ggb", None)
    except Exception:
        pass


__all__ = ["register_ggb_magic", "unregister_ggb_magic"]
