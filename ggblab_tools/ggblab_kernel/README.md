````markdown
ggblab_tools.ggblab_kernel — In-process Python kernel
=================================

This package provides a lightweight in-process Python kernel that executes code via IPython's InteractiveShell.

Quick start
-----------

1. Install the kernelspec for the current user:

```bash
python -m ggblab_tools.ggblab_kernel.install_kernelspec --user --name ggblab-local
```

2. Launch a console connected to the kernel:

```bash
python -m ggblab_tools.ggblab_kernel.console_frontend
# or directly:
jupyter console --kernel ggblab-local
```

3. To enable ggblab integration at kernel startup, launch via the provided launcher:

```bash
python -m ggblab_tools.ggblab_kernel.proxy_launcher --ggblab
```

When `--ggblab` is provided, the kernel will attempt to import `ggblab_core.applet`, create
an `AppletInjector` and call `open()`. It will also export `ggb`, `function_sync`, and
`command_sync` into the kernel user namespace so that cells can call them directly.

````
