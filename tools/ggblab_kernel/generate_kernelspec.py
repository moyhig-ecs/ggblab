#!/usr/bin/env python3
"""
Generate a kernelspec `kernel.json` that points to the simplified ggblab
launcher. This script writes a kernelspec directory you can install with
`jupyter kernelspec install <dir>` or copy into a Jupyter kernels directory.

Example:
  python tools/ggblab_kernel/generate_kernelspec.py --dest ./build/kernels/ggblab --display-name "ggblab (dev)"
"""
from __future__ import annotations

import argparse
import json
import json as _json
import os
import shutil
import subprocess
import sys


def find_launcher():
    # Prefer repo-local launcher
    here = os.path.abspath(os.path.dirname(__file__))
    launcher = os.path.join(here, "launch.py")
    if os.path.exists(launcher):
        return launcher
    # Fallback: try the top-level tools script
    alt = os.path.abspath(os.path.join(here, "..", "ggblab_kernel_launch.py"))
    if os.path.exists(alt):
        return alt
    return None


def make_kernelspec(
    dest_dir: str, display_name: str = "ggblab (dev)", language: str = "python"
):
    launcher = find_launcher()
    if launcher is None:
        raise SystemExit("Could not find a launcher script to point kernelspec at")

    # Use sys.executable to ensure the same Python interpreter
    argv = [sys.executable, launcher, "-f", "{connection_file}"]

    spec = {
        "argv": argv,
        "display_name": display_name,
        "language": language,
        "env": {},
    }

    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, "kernel.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    print("Wrote kernelspec to", path)
    return path


def install_kernelspec(dest_dir: str, user: bool = True, replace: bool = False) -> int:
    # Prefer using `python -m jupyter` to avoid PATH issues
    cmd = [sys.executable, "-m", "jupyter", "kernelspec", "install", dest_dir]
    if user:
        cmd.append("--user")
    if replace:
        cmd.append("--replace")

    print("Running:", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        # Fallback to `jupyter` executable if python -m jupyter isn't available
        jupyter = shutil.which("jupyter")
        if not jupyter:
            print(
                "Could not find `jupyter` command to install kernelspec",
                file=sys.stderr,
            )
            return 2
        cmd = [jupyter, "kernelspec", "install", dest_dir]
        if user:
            cmd.append("--user")
        if replace:
            cmd.append("--replace")
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)

    if proc.returncode != 0:
        print(
            "kernelspec install failed (exit {}):".format(proc.returncode),
            file=sys.stderr,
        )
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
    else:
        print("kernelspec installed successfully")
    return proc.returncode


def find_jupyter_data_paths() -> list:
    """Return the list of Jupyter data directories from `jupyter --paths --json`.

    Falls back to common defaults when the command is unavailable.
    """
    cmd = [sys.executable, "-m", "jupyter", "--paths", "--json"]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = _json.loads(proc.stdout)
        return data.get("data", [])
    except Exception:
        # Fallback: common locations per jupyter spec
        paths = []
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            paths.append(xdg)
        home = os.path.expanduser("~")
        paths.append(os.path.join(home, ".local", "share"))
        paths.append("/usr/local/share")
        paths.append("/usr/share")
        return paths


def auto_install_kernelspec(
    kernel_dirname: str,
    kernel_json_path: str,
    prefer_user: bool = True,
    replace: bool = False,
) -> int:
    """Write kernel.json into a detected kernelspec directory.

    kernel_dirname is the subdirectory name for the kernelspec (e.g. 'ggblab').
    kernel_json_path is the path to the generated kernel.json file.
    """
    data_paths = find_jupyter_data_paths()
    candidates = [os.path.join(p, "kernels") for p in data_paths]

    # Prefer user-local location when requested
    home = os.path.expanduser("~")
    chosen = None
    if prefer_user:
        for c in candidates:
            try:
                if os.path.commonpath([os.path.abspath(c), home]) == os.path.abspath(
                    home
                ):
                    chosen = c
                    break
            except Exception:
                continue
    if chosen is None:
        # pick first writable candidate or createable
        for c in candidates:
            try:
                os.makedirs(c, exist_ok=True)
                # test write
                test = os.path.join(c, ".write_test")
                with open(test, "w"):
                    pass
                os.remove(test)
                chosen = c
                break
            except Exception:
                continue

    if chosen is None:
        print(
            "No suitable kernels directory found to install kernelspec", file=sys.stderr
        )
        return 2

    dest = os.path.join(chosen, kernel_dirname)
    if os.path.exists(dest):
        if not replace:
            print(
                f"Kernelspec directory already exists: {dest} (use --replace to overwrite)",
                file=sys.stderr,
            )
            return 3
        # remove and recreate
        try:
            shutil.rmtree(dest)
        except Exception as e:
            print("Failed to remove existing kernelspec dir:", e, file=sys.stderr)
            return 4

    os.makedirs(dest, exist_ok=True)
    try:
        shutil.copy(kernel_json_path, os.path.join(dest, "kernel.json"))
    except Exception as e:
        print("Failed to copy kernel.json into kernelspec dir:", e, file=sys.stderr)
        return 5

    print("Installed kernelspec into", dest)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Write a ggblab kernelspec directory")
    parser.add_argument(
        "--dest",
        required=True,
        help="Destination directory to write the kernelspec (will be created)",
    )
    parser.add_argument(
        "--display-name", default="ggblab (dev)", help="Display name for the kernelspec"
    )
    parser.add_argument("--language", default="python", help="Language name")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install the kernelspec after generating (uses python -m jupyter)",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="Pass --user to `jupyter kernelspec install`",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Pass --replace to `jupyter kernelspec install`",
    )
    parser.add_argument(
        "--auto-install",
        action="store_true",
        help="Detect Jupyter kernels directories and write the kernelspec directly",
    )
    parser.add_argument(
        "--name",
        help="Kernelspec directory name to install as when using --auto-install (default: ggblab)",
    )
    args = parser.parse_args()
    kernel_json = make_kernelspec(args.dest, args.display_name, args.language)
    if args.install:
        rc = install_kernelspec(args.dest, user=args.user, replace=args.replace)
        if rc != 0:
            raise SystemExit(rc)
    if args.auto_install:
        # kernel name (dir) defaults to "ggblab"
        name = args.name or "ggblab"
        rc = auto_install_kernelspec(
            name, kernel_json, prefer_user=args.user, replace=args.replace
        )
        if rc != 0:
            raise SystemExit(rc)


if __name__ == "__main__":
    main()
