"""Simple CLI frontend that launches `jupyter console` connected to the ggblab-local kernel."""
import argparse
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description="Open jupyter console to ggblab-local kernel")
    p.add_argument("--kernel", default="ggblab-local", help="Kernel name to use")
    args, extra = p.parse_known_args()

    cmd = ["jupyter", "console", "--kernel", args.kernel]
    if extra:
        cmd += extra

    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        print("jupyter command not found. Ensure Jupyter is installed and on PATH.")
        sys.exit(2)


if __name__ == "__main__":
    main()
