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
from typing import Optional, Tuple, List
import asyncio
import sys
import os
import re

from IPython import get_ipython

from .ggbapplet import GeoGebra
from .errors import GeoGebraAppletError


# Runtime debug toggle: enable with env `GGBLAB_IPYMAGIC_DEBUG=1`
# or by setting `_ggb_debug=True` in IPython's `user_ns`.
_DEBUG = os.environ.get('GGBLAB_IPYMAGIC_DEBUG', '') not in ('', '0', 'False', 'false')


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
                    msg = ' '.join(str(x) for x in a)
        else:
            msg = ' '.join(str(x) for x in a)

        if _DEBUG:
            print(msg, **kw)
            return
        ip_ = get_ipython()
        if ip_ is None:
            return
        ns_ = getattr(ip_, 'user_ns', None)
        if isinstance(ns_, dict) and ns_.get('_ggb_debug'):
            print(msg, **kw)
    except Exception:
        pass


def _strip_outer_quotes(s: str) -> str:
    try:
        s2 = s.strip()
        if (s2.startswith("'") and s2.endswith("'")) or (s2.startswith('"') and s2.endswith('"')):
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
        if not ln2 or ln2.startswith('#'):
            return ''
        ln3 = ln2.split('#', 1)[0].strip()
        # Preserve lines wrapped in braces `{...}` verbatim.
        # ConstructionIO.commands_for_magic may emit brace-wrapped lines
        # that are intended to be passed directly to GeoGebra rather than
        # treated as variable expansion markers. Do not unwrap them here.
        ln3 = _strip_outer_quotes(ln3)
        return ln3.strip()
    except Exception:
        return ''


async def _run_commands_async(cmds: List[str], ggb_instance: Optional[GeoGebra] = None):
    ggb = ggb_instance or GeoGebra()
    if not getattr(ggb, 'initialized', False):
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
            if ',' in v and '(' not in v and ')' not in v:
                return v.split(',', 1)[0].strip()
            return v
        if isinstance(v, dict):
            if 'label' in v:
                return str(v['label'])
            if 'result' in v:
                return str(v['result'])
            return str(v)
        if isinstance(v, (list, tuple)):
            return _stringify(v[0]) if v else ''
        return str(v)

    # Pattern matches either a numeric form like '_2' (group 1) or a run
    # of underscores like '__' (group 2, includes all underscores). Numeric form takes precedence.
    token_re = re.compile(r'(?<!\w)(?:_(\d+)|(_+))(?!\w)')

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
                    return _stringify(results[n-1])
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
            # If the applet returned None, do not record it in the results list
            if r is None:
                continue
            # If GeoGebra returned multiple values packed in a string
            # (comma-separated) or as a list/tuple, push each item into
            # the results "register" so tokens like _1, _2 can access
            # subsequent values. Otherwise append the single result.
            try:
                if isinstance(r, str) and ',' in r and '(' not in r and ')' not in r:
                    parts = [p.strip() for p in r.split(',')]
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
            is_applet_error = isinstance(e, GeoGebraAppletError) or type(e).__name__ == 'GeoGebraAppletError'
            print(f"ggb.command failed for: {c_to_send!r} -> {type(e).__name__}: {e}")
            if is_applet_error:
                # Replace results with a single error entry and stop processing
                results = [{'error': str(e)}]
                break
            else:
                # Non-applet errors: record and continue
                results.append({'error': str(e)})

    # Convert results to strings as the user expects a list of strings
    try:
        str_results = [ _stringify(x) for x in results ]
    except Exception:
        str_results = [ str(x) for x in results ]
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
        s2 = s.split('#', 1)[0]
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
                        if s[j] == quote and s[j-1] != '\\':
                            # candidate quoted segment
                            inner = s[i+1:j]
                            # Detect either real newlines or escaped '\\n' sequences
                            if '\\n' in inner or '\n' in inner:
                                # Normalize escaped sequences into real newlines
                                inner2 = inner.replace('\\r\\n', '\r\n').replace('\\n', '\n').replace('\\r', '\r')
                                cell = inner2
                                # remove the quoted portion from the line
                                line = (s[:i] + s[j+1:]).strip()
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
        for ln in cell.splitlines():
            ln2 = ln.strip()
            if not ln2:
                continue
            if ln2.startswith('#'):
                # ignore full-line comments
                continue
            # strip inline comments
            cmd = _strip_comment(ln2)
            if cmd:
                cmds.append(cmd)
        return instance, cmds

    # line magic: allow "instance command..." or just "command"
    raw = line or ''
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
            inst = getattr(GeoGebra, '_instance', None)
        except Exception:
            inst = None
        created = False
        if inst is None:
            try:
                inst = GeoGebra()
                created = True
            except Exception:
                try:
                    inst = getattr(GeoGebra, '_instance', None)
                except Exception:
                    inst = None
                if inst is None:
                    inst = GeoGebra()
                    created = True
        try:
            if isinstance(user_ns, dict) and 'ggb' not in user_ns:
                user_ns['ggb'] = inst
        except Exception:
            pass
        if created:
            try:
                if for_api:
                    print("[ggb] created GeoGebra singleton for api call")
                else:
                    print("[ggb] created GeoGebra singleton and stored as 'ggb' in user namespace")
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
            user_ns = getattr(ip, 'user_ns', {}) if ip is not None else {}
        except Exception:
            user_ns = {}

        if cell is None and isinstance(cmds, list) and len(cmds) == 1:
            raw_tok = cmds[0].strip() if cmds[0] is not None else ''
            # normalize token by removing outer quotes if present
            raw_tok_str = _strip_outer_quotes(raw_tok)
            # allow both `{name}` and `name`
            var_match = None
            try:
                var_match = __import__('re').match(r'^\{\s*([A-Za-z_]\w*)\s*\}$', raw_tok)
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
                tok_preview = (raw_tok.replace('\n', '\\n')[:120]) if isinstance(raw_tok, str) else repr(raw_tok)[:120]
                raw_preview = (raw_tok_str.replace('\n', '\\n')[:120]) if isinstance(raw_tok_str, str) else repr(raw_tok_str)[:120]
                tok_len = len(raw_tok) if hasattr(raw_tok, '__len__') else 0
                tok_lines = raw_tok.count('\n') + 1 if isinstance(raw_tok, str) else 0
                _dbg("[ggb-magic-debug] token_preview=%r len=%d lines=%d raw_preview=%r varname=%r user_ns=%r",
                     tok_preview, tok_len, tok_lines, raw_preview, varname, ns_info)
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
                        raw_preview = v2.replace('\\n', '\n')
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
                        preview = raw_preview.replace('\n', '\\n')[:120]
                        sample = new_cmds[:5]
                        _dbg("[ggb-magic-debug] expanded %r: %d lines, %d cmds, preview=%r, sample=%r",
                             varname, len(lines), len(new_cmds), preview, sample)
                        if len(new_cmds) > 5:
                            _dbg("[ggb-magic-debug] expanded %r: showing first %d of %d cmds",
                                 varname, 5, len(new_cmds))
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
        user_ns = getattr(ip, 'user_ns', {}) if ip is not None else {}
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
                    inst = getattr(GeoGebra, '_instance', None)
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
                    inst = getattr(GeoGebra, '_instance', None)
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
            _dbg("[ggb-magic-debug] resolved ggb_instance_source=%r ggb_instance=%r",
                 getattr(ggb_instance, '__class__', None), ggb_instance)
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        # Special-case API invocation using syntax: `%ggb api getValue(A)`
        # or `%ggb api getValue [A,B]` where 'api' is the first token (inst_name).
        if inst_name == 'api' and cmds:
            expr = cmds[0].strip()
            # parse function name and args
            m = __import__('re').match(r"^\s*([A-Za-z_]\w*)(?:\s*(?:\((.*)\)|\[(.*)\]))?\s*$", expr)
            if m:
                fname = m.group(1)
                args_text = m.group(2) if m.group(2) is not None else (m.group(3) or "")
                if args_text.strip() == "":
                    args_list = []
                else:
                    args_list = [a.strip() for a in args_text.split(',') if a.strip()]

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
                    # synchronous call
                    try:
                        return asyncio.run(ggb_instance.function(fname, args_list))
                    except Exception as e:
                        print('ggb api call failed:', e)
                        return None
                else:
                    # schedule and store task
                    task = loop.create_task(ggb_instance.function(fname, args_list))
                    try:
                        ip = get_ipython()
                        if ip is not None:
                            ns = getattr(ip, 'user_ns', None)
                            if isinstance(ns, dict):
                                ns['_ggb_last_task'] = task

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
                                        ns['_'] = res
                                    except Exception:
                                        pass
                                    try:
                                        if ip2 is not None:
                                            ns2 = getattr(ip2, 'user_ns', None)
                                            if isinstance(ns2, dict):
                                                out = ns2.get('Out')
                                                if isinstance(out, dict):
                                                    count = getattr(ip2, 'execution_count', None)
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
                print('ggb magic execution failed:', e)
                return None
        else:
            # Running loop available: schedule task and do not echo it in the cell.
            # Save the Task in the IPython user namespace under `_ggb_last_task`
            task = loop.create_task(coro)
            try:
                ip = get_ipython()
                if ip is not None:
                    ns = getattr(ip, 'user_ns', None)
                    if isinstance(ns, dict):
                        ns['_ggb_last_task'] = task

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
                            ns['_'] = res
                        except Exception:
                            pass
                        try:
                            if ip2 is not None:
                                ns2 = getattr(ip2, 'user_ns', None)
                                if isinstance(ns2, dict):
                                    out = ns2.get('Out')
                                    if isinstance(out, dict):
                                        count = getattr(ip2, 'execution_count', None)
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
    ipython.register_magic_function(_ggb_magic, 'line', 'ggb')
    ipython.register_magic_function(_ggb_magic, 'cell', 'ggb')
    try:
        ipython.register_magic_function(_ggb_magic, 'line', 'ggblab')
        ipython.register_magic_function(_ggb_magic, 'cell', 'ggblab')
    except Exception:
        # ignore if registration of alias fails
        pass


def unregister_ggb_magic(ipython=None):
    if ipython is None:
        ipython = get_ipython()
    if ipython is None:
        return
    try:
        ipython.magics_manager.registry.pop('ggb', None)
    except Exception:
        pass


__all__ = ['register_ggb_magic', 'unregister_ggb_magic']
