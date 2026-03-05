Simple ggblab Jupyter kernel

Files:

- `launch.py`: simplified kernel launcher. Use this as the `argv` in a kernelspec.
- `generate_kernelspec.py`: writes a `kernel.json` that points to `launch.py`.

Usage:

1. Generate a kernelspec directory (and optionally install it):

```
python tools/ggblab_kernel/generate_kernelspec.py --dest ./build/kernels/ggblab --display-name "ggblab (dev)"
```

To generate and install in one step (user install):

```
python tools/ggblab_kernel/generate_kernelspec.py --dest ./build/kernels/ggblab --install --user
```

To replace an existing installed kernelspec:

```
python tools/ggblab_kernel/generate_kernelspec.py --dest ./build/kernels/ggblab --install --user --replace
```

The generator prefers `python -m jupyter kernelspec install` to avoid PATH
issues; it falls back to a `jupyter` executable when necessary. The
generated `kernel.json` uses the same Python interpreter that runs the
generator (via `sys.executable`) and points the `argv` at `launch.py`.

Auto-install (write directly into detected kernels directories):

```
python tools/ggblab_kernel/generate_kernelspec.py --dest ./build/kernels/ggblab --auto-install --user --replace
```

This will detect Jupyter data directories (via `jupyter --paths --json`) and
write `kernel.json` into the first suitable `.../kernels/<name>/kernel.json`.
By default the kernelspec subdirectory name is `ggblab`; override with
`--name`.
