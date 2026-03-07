#!/usr/bin/env python3
"""Install/uninstall a kernelspec for the julia adapter kernel.

Usage examples:
  python tools/install_julia_kernel.py --install --user
  python tools/install_julia_kernel.py --uninstall --name ggblab-julia-adapter

This writes a minimal `kernel.json` that launches the adapter script
with the `-f {connection_file}` argument so Jupyter Server can start it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from jupyter_client.kernelspec import KernelSpecManager
except Exception:
    KernelSpecManager = None  # type: ignore


def make_kernel_json(
    adapter_path: str, display_name: str = "Julia (ggblab adapter)"
) -> dict:
    return {
        "argv": [sys.executable, adapter_path, "-f", "{connection_file}"],
        "display_name": display_name,
        "language": "julia",
    }


def install_kernel(
    name: str, adapter_path: str, user: bool = True, display_name: str | None = None
) -> int:
    if KernelSpecManager is None:
        print(
            "jupyter_client not available in this environment; cannot install kernelspec",
            file=sys.stderr,
        )
        return 2

    ksm = KernelSpecManager()
    display = display_name or "Julia (ggblab adapter)"
    kernel_json = make_kernel_json(adapter_path, display)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "kernel.json").write_text(json.dumps(kernel_json, indent=2))
        try:
            # Use positional second argument for the kernel name for broader
            # compatibility across jupyter_client versions.
            ksm.install_kernel_spec(str(td_path), name, user=user, replace=True)
            print(f"Installed kernelspec '{name}' (user={user})")
            return 0
        except Exception as e:
            print("Failed to install kernelspec:", e, file=sys.stderr)
            return 1


def uninstall_kernel(name: str) -> int:
    if KernelSpecManager is None:
        print(
            "jupyter_client not available in this environment; cannot uninstall kernelspec",
            file=sys.stderr,
        )
        return 2
    ksm = KernelSpecManager()
    try:
        ksm.remove_kernel_spec(name)
        print(f"Removed kernelspec '{name}'")
        return 0
    except Exception as e:
        print("Failed to remove kernelspec:", e, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(
        description="Install/uninstall julia adapter kernelspec"
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install the kernelspec")
    group.add_argument(
        "--uninstall", action="store_true", help="Uninstall the kernelspec"
    )
    p.add_argument(
        "--name", default="ggblab-julia-adapter", help="Kernelspec name (id)"
    )
    p.add_argument(
        "--user", action="store_true", help="Install for current user (default)"
    )
    p.add_argument("--display-name", default=None, help="Display name shown in UIs")
    args = p.parse_args(argv)

    adapter_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "julia_adapter_kernel.py")
    )
    if not os.path.exists(adapter_path):
        print(f"Adapter script not found at {adapter_path}", file=sys.stderr)
        return 2

    if args.install:
        return install_kernel(
            args.name,
            adapter_path,
            user=args.user or True,
            display_name=args.display_name,
        )
    else:
        return uninstall_kernel(args.name)


if __name__ == "__main__":
    raise SystemExit(main())
