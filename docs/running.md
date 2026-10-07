# Where it runs, and known limitations

## Where it runs

```{include} ../README.md
:start-after: "## Where it runs\n"
:end-before: "## Known limitations"
```

On JupyterHub the kernel finds its server from `JUPYTERHUB_SERVICE_URL` and `JUPYTERHUB_API_TOKEN`. The requests of
the applet pass the proxy of the hub as plain HTTP long polls; no WebSocket is needed.

## Known limitations

- **A call needs a holder.** A box nobody polls answers `NoHolderError` within `holder_grace` s (default 2.0): open the notebook's applet, or the holder page `ggblab/holder?mount=…`, before calling. Pass `fail_fast=False` to wait out `timeout` instead.

```{include} ../README.md
:start-after: "## Known limitations\n"
:end-before: "## Tests"
```
