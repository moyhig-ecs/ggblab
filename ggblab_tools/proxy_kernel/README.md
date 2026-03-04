````markdown
ggblab_tools.proxy_kernel — Proxy Jupyter kernel
=================================

This package provides a simple proxy kernel that forwards execution to a child kernel (Python or Julia) and returns outputs back to the frontend.

Quick start
-----------

1. Install the package's kernelspec for the current user:

```bash
python -m ggblab_tools.proxy_kernel.install_kernelspec --user
```

2. (Optional) Choose the child kernel by setting the environment variable `GGBLAB_PROXY_CHILD_KERNEL` before launching the proxy kernel. Example to use julia (if installed):

```bash
export GGBLAB_PROXY_CHILD_KERNEL=julia-1.10
```

3. Open a console connected to the proxy kernel:

```bash
python -m ggblab_tools.proxy_kernel.console_frontend
# or directly:
jupyter console --kernel ggblab-proxy
```

Notes
-----
- The proxy kernel is implemented in `ggblab_tools/proxy_kernel/__init__.py` and started via `python -m ggblab_tools.proxy_kernel.proxy_launcher`.
- The kernelspec is installed from `ggblab_tools/kernelspec/kernel.json`.
- The proxy forwards basic iopub message types: `stream`, `execute_result`, `display_data`, and `error`.

````
