import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import asyncio
import re

from ggblab.ipymagic import _parse_commands, _run_commands_async

# sample value with multiple lines
val = "'(0, 0)\nCircle(_1, 1)\nPoint(_2)\nLine(_1, _3)\nPoint(_4)\nPerpendicularLine(_5, _4)\n{Intersect(_2, _6)}\n_7(1)\n_7(2)\nPolygon(_1, _8, _9)\nSegment(_1, _8, _10)\nSegment(_8, _9, _10)\nSegment(_9, _1, _10)'"
user_ns = {"cmds": val}

line = "{cmds}"
inst_name, cmds = _parse_commands(line, None)
print("Initial parse ->", cmds)

# expansion (same as in ipymagic)
new_cmds = cmds
if isinstance(cmds, list) and len(cmds) == 1:
    raw_tok = cmds[0].strip() if cmds[0] is not None else ""
    if (raw_tok.startswith("'") and raw_tok.endswith("'")) or (
        raw_tok.startswith('"') and raw_tok.endswith('"')
    ):
        raw_tok_str = raw_tok[1:-1].strip()
    else:
        raw_tok_str = raw_tok
    var_match = re.match(r"^\{\s*([A-Za-z_]\w*)\s*\}$", raw_tok_str)
    if var_match:
        varname = var_match.group(1)
    elif raw_tok_str.isidentifier():
        varname = raw_tok_str
    else:
        varname = None
    print("varname detected:", varname)
    if varname and varname in user_ns:
        val = user_ns[varname]
        if isinstance(val, str):
            v2 = val.strip()
            if (v2.startswith("'") and v2.endswith("'")) or (
                v2.startswith('"') and v2.endswith('"')
            ):
                v2 = v2[1:-1]
            new_cmds = []
            for ln in v2.splitlines():
                ln2 = ln.strip()
                if not ln2:
                    continue
                if ln2.startswith("#"):
                    continue
                ln3 = ln2.split("#", 1)[0].rstrip()
                if ln3.startswith("{") and ln3.endswith("}"):
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
        elif isinstance(val, (list, tuple)):
            try:
                new_cmds = [str(x) for x in val if x is not None]
            except Exception:
                pass

print("Expanded count:", len(new_cmds))
for i, c in enumerate(new_cmds, 1):
    print(i, repr(c))


# fake GeoGebra
class FakeGG:
    async def init(self):
        return None

    async def command(self, cmd):
        print("FakeGG executing:", cmd)
        return f"OK:{cmd}"


async def run_all():
    g = FakeGG()
    res = await _run_commands_async(new_cmds, g)
    print("Run results count:", len(res))
    print(res)


asyncio.run(run_all())
