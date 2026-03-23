"""Julia-specific utilities for use when Python is invoked from Julia/PythonCall.

This module provides `called_from_julia()` which prefers `psutil` when
available and falls back to platform checks. It's a lightweight copy
of `ggblab_core2.utils` tailored for environments that use the original
`ggblab` package (kernel1 / non-kernel2 setups).
"""

import os
import subprocess
import sys
from typing import Optional
import inspect


def _safe_check_output(cmd: list[str]) -> Optional[str]:
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return None


def _proc_info_windows(pid: int):
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None, None
        buf_len = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        QueryFullProcessImageName = kernel32.QueryFullProcessImageNameW
        if QueryFullProcessImageName(h, 0, buf, ctypes.byref(buf_len)):
            path = buf.value
        else:
            path = None
        kernel32.CloseHandle(h)
        name = os.path.basename(path) if path else None
        return name, path
    except Exception:
        return None, None


def _proc_info_unix(pid: int):
    try:
        if sys.platform.startswith("linux"):
            try:
                with open(f"/proc/{pid}/comm", "r", encoding="utf8") as f:
                    comm = f.read().strip()
                return comm, None
            except Exception:
                pass
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "args="], text=True
        ).strip()
        return out, None
    except Exception:
        return None, None


def called_from_julia(check_ancestors: bool = True, max_depth: int = 5) -> bool:
    """Detect whether this Python process was likely invoked from Julia/PythonCall.

    Returns True if heuristics suggest Julia; False otherwise.
    """
    julia_env_keys = (
        "JULIA_PROJECT",
        "JULIA_LOAD_PATH",
        "JULIA_BINDIR",
        "JULIA_DEPOT_PATH",
    )
    for k in julia_env_keys:
        if os.environ.get(k):
            return True

    # Fast-path: some embedder setups set an env var indicating Julia caller
    if os.environ.get("PYTHONCALL_JULIA"):
        return True

    # Prefer psutil when available (more reliable). Use Process.parents() to
    # inspect the full ancestor chain rather than manually walking ppid.
    try:
        import psutil  # type: ignore

        proc = psutil.Process()
        # check current process cmdline/name first
        try:
            name = (proc.name() or "").lower()
            cmd = " ".join(proc.cmdline() or []).lower()
            if "julia" in name or "julia" in cmd:
                return True
        except Exception:
            pass

        if check_ancestors:
            try:
                for depth, anc in enumerate(proc.parents()):
                    if depth >= max_depth:
                        break
                    try:
                        aname = (anc.name() or "").lower()
                        acmd = " ".join(anc.cmdline() or []).lower()
                        if "julia" in aname or "julia" in acmd:
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
    except Exception:
        # psutil not available: fall back to platform methods
        pass

    pid = os.getppid()
    depth = 0
    while pid and pid != 0 and depth < max_depth:
        if sys.platform == "win32":
            name, path = _proc_info_windows(pid)
            if name and "julia" in name.lower():
                return True
            if path and "julia" in path.lower():
                return True
        else:
            name, path = _proc_info_unix(pid)
            if name and "julia" in name.lower():
                return True
            out = _safe_check_output(["ps", "-p", str(pid), "-o", "args="])
            if out and "julia" in out.lower():
                return True
        if not check_ancestors:
            break
        # move up the parent chain
        try:
            # Use /proc when available; otherwise ask ps for the PPID
            if sys.platform.startswith("linux"):
                try:
                    with open(f"/proc/{pid}/status", "r", encoding="utf8") as f:
                        for line in f:
                            if line.startswith("PPid:"):
                                pid = int(line.split()[1])
                                break
                        else:
                            pid = 0
                except Exception:
                    pid = 0
            else:
                out = _safe_check_output(["ps", "-p", str(pid), "-o", "ppid="])
                if out:
                    try:
                        pid = int(out.strip())
                    except Exception:
                        pid = 0
                else:
                    pid = 0
        except Exception:
            pid = 0
        depth += 1

    for a in sys.argv:
        if isinstance(a, str) and "julia" in a.lower():
            return True

    return False


async def maybe_await(value):
    """Await *value* if it's awaitable unless running under Julia.

    When Python is embedded in Julia (detected by `called_from_julia()`),
    many juliacall-backed functions are synchronous and should not be
    awaited. This helper returns the awaited result in normal Python
    usage, but returns the original value when running under Julia so
    callers can treat both cases uniformly.
    """
    try:
        if called_from_julia():
            return value
        if inspect.isawaitable(value):
            return await value
        return value
    except Exception:
        # On error, propagate to caller
        raise


# juliacall proxy helpers
_jl = None
def _get_jl_main():
    """Return the juliacall Main proxy or None if unavailable."""
    global _jl
    if _jl is not None:
        return _jl
    try:
        from juliacall import Main as jl  # type: ignore
        _jl = jl
        return _jl
    except Exception:
        _jl = None
        return None

# Note: previous attempts to coerce julia sequence-like results to Python
# lists caused inconsistent behaviour across juliacall versions. We now
# return raw results and let callers handle conversion as needed.

def jl_function_sync(name_or_names, args=None):
    """Call `jl.GeoGebra.send_function` synchronously via juliacall.

    Raises RuntimeError if juliacall/Main is unavailable.
    """
    jl = _get_jl_main()
    if jl is None:
        raise RuntimeError("juliacall Main not available")
    if args is None:
        res = jl.GeoGebra.send_function(name_or_names)
    elif isinstance(args, (list, tuple)):
        res = jl.GeoGebra.send_function(name_or_names, *args)
    else:
        res = jl.GeoGebra.send_function(name_or_names, args)
    return res

def jl_command_sync(cmd_text):
    jl = _get_jl_main()
    if jl is None:
        raise RuntimeError("juliacall Main not available")
    return jl.GeoGebra.send_command(cmd_text)


def patch_ggb_for_julia(ggb):
    """Monkeypatch a `ggb` object so `ggb.function`/`ggb.command` call
    into Julia synchronously when running under juliacall.

    This sets `ggb._jl_patched = True` to avoid double-patching.
    """
    if ggb is None:
        return
    if not called_from_julia():
        return
    if getattr(ggb, "_jl_patched", False):
        return
    # bind methods that call into Julia
    import types as _types

    def _fn(self, name_or_names, args=None):
        return jl_function_sync(name_or_names, args)

    def _cmd(self, cmd_text):
        return jl_command_sync(cmd_text)

    ggb.function = _types.MethodType(_fn, ggb)
    ggb.command = _types.MethodType(_cmd, ggb)
    setattr(ggb, "_jl_patched", True)
