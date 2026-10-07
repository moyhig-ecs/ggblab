"""Check that a built wheel carries the four kinds of data besides the Python modules (used by the CI; not a pytest test).

    python tests/check_wheel.py dist/ggblab-2.0.0rc3-py3-none-any.whl
"""
import sys
import zipfile

NEED = [
    "ggblab/host/mount.js",
    "ggblab/xsd/common.xsd",
    "ggblab/julia/host/html_host.jl",
    "ggblab/julia/host/ggb_macro.jl",
    "data/etc/jupyter/jupyter_server_config.d/ggblab.json",
]
MUST_NOT = ("tests/", "probes/", "examples/")


def main(path: str) -> int:
    names = zipfile.ZipFile(path).namelist()
    missing = [n for n in NEED if not any(x == n or x.endswith("/" + n) or x.endswith(n) for x in names)]
    extra = [x for x in names if x.startswith(MUST_NOT)]
    print(f"{path}: {len(names)} files")
    for n in NEED:
        print("  ", "missing" if n in missing else "ok     ", n)
    if extra:
        print("   not expected in the wheel:", extra[:5])
    return 1 if missing or extra else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
