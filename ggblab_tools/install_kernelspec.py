"""Install the ggblab-proxy kernelspec into the Jupyter kernels directory.

Usage:
  python -m ggblab_tools.install_kernelspec --user
"""
import os
import argparse
from jupyter_client.kernelspec import KernelSpecManager


def install(user=True, replace=True):
    here = os.path.dirname(__file__)
    spec_dir = os.path.join(here, "kernelspec")
    ksm = KernelSpecManager()
    ksm.install_kernel_spec(spec_dir, kernel_name="ggblab-proxy", user=user, replace=replace)
    print("Installed ggblab-proxy kernelspec (user=%s)" % user)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", action="store_true", default=True, help="Install for current user")
    p.add_argument("--system", action="store_true", help="Install system-wide (requires permissions)")
    args = p.parse_args()
    user = not args.system
    install(user=user)


if __name__ == "__main__":
    main()
