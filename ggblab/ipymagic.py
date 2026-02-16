"""IPython magic for executing GeoGebra commands via `ggb.command`.

Provides `%ggb` (line) and `%%ggb` (cell) magics that schedule execution
of GeoGebra commands. In a running IPython event loop the commands are
scheduled as background tasks; when IPython is not running inside an
async loop the commands are executed synchronously.
"""
from typing import Optional, Tuple, List
import asyncio
import sys

from IPython import get_ipython

from .ggbapplet import GeoGebra
from .errors import GeoGebraAppletError


async def _run_commands_async(cmds: List[str], ggb_instance: Optional[GeoGebra] = None):
    ggb = ggb_instance or GeoGebra()
    if not getattr(ggb, 'initialized', False):
        try:
            await ggb.init()
        except Exception:
            # If init fails, continue and let command raise later
            pass
    import re

    results: List[str] = []

    def _stringify(v) -> str:
        try:
            if isinstance(v, str):
                # If GeoGebra returns a comma-separated multi-value string
                # (e.g. Polygon returns like "t1,e,a,d") and it's not a
                # function-like expression, use only the first token.
                if ',' in v and '(' not in v and ')' not in v:
                    try:
                        return v.split(',', 1)[0].strip()
                    except Exception:
                        return v
                return v
            # If GeoGebra returns a dict like {'label': 'A'}, prefer label
            if isinstance(v, dict):
                if 'label' in v:
                    return str(v['label'])
                # fall back to 'result' or full repr
                if 'result' in v:
                    return str(v['result'])
            # lists/tuples: join or take first
            if isinstance(v, (list, tuple)):
                # Prefer the first element for multi-valued results.
                try:
                    if len(v) >= 1:
                        return _stringify(v[0])
                except Exception:
                    pass
                return ''
            return str(v)
        except Exception:
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
    def _strip_comment(s: str) -> str:
        s2 = s.split('#', 1)[0]
        return s2.rstrip()

    instance = None
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
            # If the token is quoted (e.g. "'{cmds}'"), strip outer quotes
            if (raw_tok.startswith("'") and raw_tok.endswith("'")) or (raw_tok.startswith('"') and raw_tok.endswith('"')):
                raw_tok_str = raw_tok[1:-1].strip()
            else:
                raw_tok_str = raw_tok
            # allow both `{name}` and `name`
            var_match = None
            try:
                var_match = __import__('re').match(r'^\{\s*([A-Za-z_]\w*)\s*\}$', raw_tok)
            except Exception:
                var_match = None
            # Expand when token is either a bare identifier `name` or the
            # brace form `{name}` so both `%ggb name` and `%ggb {name}` work.
            if var_match:
                varname = var_match.group(1)
            elif raw_tok_str.isidentifier():
                varname = raw_tok_str
            else:
                varname = None

            # Debug: show token parsing result (temporary)
            # debug prints removed

            # If we couldn't detect a {name} form (because a frontend already
            # expanded it), try to find a variable in the user namespace whose
            # string contents match the token. This lets frontends that expand
            # `{var}` before our magic run still behave like `%ggb var`.
            if varname is None:
                try:
                    tgt = raw_tok_str.strip()
                    if isinstance(user_ns, dict):
                        for k, v in user_ns.items():
                            # skip obvious internals
                            if k.startswith('__'):
                                continue
                            # string variables: compare stripped content
                            if isinstance(v, str):
                                vv = v.strip()
                                if (vv.startswith("'") and vv.endswith("'")) or (vv.startswith('"') and vv.endswith('"')):
                                    vv = vv[1:-1].strip()
                                if vv == tgt:
                                    varname = k
                                    # debug prints removed
                                    break
                            # list/tuple: join by newlines and compare
                            if isinstance(v, (list, tuple)):
                                joined = '\n'.join(str(x) for x in v).strip()
                                if joined == tgt:
                                    varname = k
                                    # debug prints removed
                                    break
                except Exception:
                    pass

            if varname and varname in user_ns:
                val = user_ns[varname]
                if isinstance(val, str):
                    v2 = val.strip()
                    if (v2.startswith("'") and v2.endswith("'")) or (v2.startswith('"') and v2.endswith('"')):
                        v2 = v2[1:-1]
                    new_cmds = []
                    for ln in v2.splitlines():
                        ln2 = ln.strip()
                        if not ln2:
                            continue
                        if ln2.startswith('#'):
                            continue
                        ln3 = ln2.split('#', 1)[0].rstrip()
                        if ln3.startswith('{') and ln3.endswith('}'):
                            ln3 = ln3[1:-1].strip()
                        if ln3.startswith("'"):
                            ln3 = ln3[1:]
                        if ln3.endswith("'"):
                            ln3 = ln3[:-1]
                        if ln3.startswith('"'):
                            ln3 = ln3[1:]
                        if ln3.endswith('"'):
                            ln3 = ln3[:-1]
                        if ln3:
                            new_cmds.append(ln3)
                    if new_cmds:
                        inst_name = None
                        cmds = new_cmds
                elif isinstance(val, (list, tuple)):
                    try:
                        cmds = [str(x) for x in val if x is not None]
                        inst_name = None
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
        # Ensure a readily discoverable name in the user namespace: if we will
        # create or use the singleton, store it as `ggb` in user_ns for later discovery.
        try:
            if ggb_instance is None and ip is not None and isinstance(user_ns, dict):
                inst = getattr(GeoGebra, '_instance', None)
                if inst is None:
                    inst = GeoGebra()
                if 'ggb' not in user_ns:
                    user_ns['ggb'] = inst
                ggb_instance = inst
        except Exception:
            pass
        # debug prints removed
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
                        ggb_instance = getattr(GeoGebra, '_instance', None) or GeoGebra()
                    except Exception:
                        ggb_instance = GeoGebra()

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
                                        ns['_'] = res
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
                            ns['_'] = res
                        except Exception:
                            # Best-effort; ignore failures
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
