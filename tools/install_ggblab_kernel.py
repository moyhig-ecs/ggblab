#!/usr/bin/env python3
"""
Install/uninstall a Jupyter kernelspec for the ggblab kernel launcher.

This script creates a temporary kernelspec directory containing a
`kernel.json` that points to `tools/ggblab_kernel_launch.py` using the
current Python executable. Then it calls `jupyter kernelspec install` to
register the kernel for the current user.

Usage:
  python tools/install_ggblab_kernel.py --install   # install into --user
  python tools/install_ggblab_kernel.py --remove    # uninstall the kernel
"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

KERNEL_NAME = "ggblab"


def make_kernelspec_dir(launch_py_path):
    td = tempfile.mkdtemp(prefix="ggblab-kernelspec-")
    ks = {
        "argv": [sys.executable, launch_py_path, "-f", "{connection_file}"],
        "display_name": "ggblab (local)",
        "language": "python",
    }
    os.makedirs(os.path.join(td, "resources"), exist_ok=True)
    with open(os.path.join(td, "kernel.json"), "w", encoding="utf-8") as f:
        json.dump(ks, f, indent=2)
    return td


def install_kernelspec(kernelspec_dir, user=True, replace=True):
    cmd = ["jupyter", "kernelspec", "install"]
    if user:
        cmd.append("--user")
    if replace:
        cmd.append("--replace")
    cmd.append(kernelspec_dir)
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def uninstall_kernelspec(name=KERNEL_NAME):
    cmd = ["jupyter", "kernelspec", "uninstall", name, "-f"]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Install/uninstall ggblab Jupyter kernel"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--install", action="store_true", help="Install the kernelspec (user scope)"
    )
    group.add_argument("--remove", action="store_true", help="Uninstall the kernelspec")
    parser.add_argument(
        "--launch-path",
        help="Path to ggblab_kernel_launch.py (defaults to tools/ggblab_kernel_launch.py in repo)",
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    default_launch = os.path.join(repo_root, "tools", "ggblab_kernel_launch.py")
    launch = os.path.abspath(args.launch_path) if args.launch_path else default_launch

    if args.install:
        if not os.path.exists(launch):
            print("Launch script not found:", launch, file=sys.stderr)
            sys.exit(2)
        ksdir = make_kernelspec_dir(launch)
        try:
            install_kernelspec(ksdir, user=True, replace=True)
            print("Installed kernelspec as", KERNEL_NAME)
        finally:
            shutil.rmtree(ksdir)
    elif args.remove:
        uninstall_kernelspec(KERNEL_NAME)


if __name__ == "__main__":
    main()
