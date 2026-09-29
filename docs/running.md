# Where it runs, and known limitations

## Where it runs

```{include} ../README.md
:start-after: "## Where it runs\n"
:end-before: "## Known limitations"
```

On JupyterHub the kernel finds its server from `JUPYTERHUB_SERVICE_URL` and `JUPYTERHUB_API_TOKEN`. The requests of
the applet pass the proxy of the hub as plain HTTP long polls; no WebSocket is needed.

## Known limitations

```{include} ../README.md
:start-after: "## Known limitations\n"
:end-before: "## Tests"
```
