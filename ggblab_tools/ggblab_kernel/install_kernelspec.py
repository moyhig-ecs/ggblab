"""Install the ggblab-local kernelspec into the Jupyter kernels directory.

Usage:
  python -m ggblab_tools.ggblab_kernel.install_kernelspec --user
"""
import os
import argparse
from jupyter_client.kernelspec import KernelSpecManager


def install(user=True, replace=True, kernel_name="ggblab-local"):
    here = os.path.dirname(__file__)
    # kernelspec lives at ggblab_tools/kernelspec
    spec_dir = os.path.normpath(os.path.join(here, "..", "kernelspec"))
    ksm = KernelSpecManager()
    ksm.install_kernel_spec(spec_dir, kernel_name=kernel_name, user=user, replace=replace)
    print(f"Installed {kernel_name} kernelspec (user={user})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", action="store_true", default=True, help="Install for current user")
    p.add_argument("--system", action="store_true", help="Install system-wide (requires permissions)")
    p.add_argument("--name", default="ggblab-local", help="Kernel name to install")
    args = p.parse_args()
    user = not args.system
    install(user=user, kernel_name=args.name)


if __name__ == "__main__":
    main()
