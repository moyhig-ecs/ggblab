# Cloud Deployment Guide

This document provides detailed deployment and troubleshooting guidance for operating ggblab in cloud environments (JupyterHub, Kubernetes, generic VMs).

## Environment Sanity Checks

Before deploying ggblab in a cloud environment, verify that `pip`, `python`, and `jupyter lab` all target the same environment:

```bash
# Confirm Jupyter binary path
which jupyter

# Confirm Python executable used in the session
python -c 'import sys; print(sys.executable)'

# Inspect Python environment paths
python -m site

# Verify ggblab is registered as a federated extension
jupyter labextension list | grep ggblab

# Verify ggblab is installed in the current environment
pip show ggblab
```

## Common Pitfalls

- **Mixed environments**: `pip` installs into a different environment than `jupyter lab` uses. Use the sanity checks above to verify all paths target the same environment.

- **Missing restart**: After runtime install, restart the single-user server; a browser refresh alone won't load new extensions.

- **CDN egress blocked**: Cluster/network policies must allow `cdn.geogebra.org`.

- **Proxy/WebSocket interference**: Corporate or custom proxies can disrupt Comm/WebSocket. Inspect Hub and single-user server logs for detailed error messages.

- **JupyterLab version mismatch**: ggblab targets JupyterLab 4; older versions won't load federated extensions reliably.

- **Unnecessary Node build**: Cloud installs don't require `jlpm build`; ggblab ships prebuilt.

- **Extension not listed**: If `jupyter labextension list` doesn't show ggblab, you likely installed into the wrong environment or need a server restart.

## Post-Deployment Verification

Run the following in a JupyterLab notebook to confirm the extension loads, opens the panel, and kernel↔widget communication works:

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # open panel and initialize comm/socket

# Create a point and read its value
await ggb.command("A = (0, 0)")
val = await ggb.function("getValue", ["A"])  # should return 0 or a numeric value
print(val)
```

If you encounter a timeout:
- Restart the single-user server from the JupyterLab Control Panel
- Verify that your cluster allows egress to `cdn.geogebra.org`
- Check proxy/firewall logs for WebSocket or HTTP connection errors
