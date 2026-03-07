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

    # Prefer psutil when available (more reliable)
    try:
        import psutil  # type: ignore

        pid = os.getppid()
        depth = 0
        while pid and pid != 0 and depth < max_depth:
            p = psutil.Process(pid)
            name = (p.name() or "").lower()
            cmd = " ".join(p.cmdline() or []).lower()
            if "julia" in name or "julia" in cmd:
                return True
            if not check_ancestors:
                break
            pid = p.ppid()
            depth += 1
        # also check current process cmdline
        try:
            if "julia" in " ".join(psutil.Process(os.getpid()).cmdline() or []).lower():
                return True
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
        break
        depth += 1

    for a in sys.argv:
        if isinstance(a, str) and "julia" in a.lower():
            return True

    return False
