"""ggblab — replay lineage (stage 0 v2 → RPC 09-09: 鞭毛 = applet mount from a trusted HTML output + HTTP polling; the
kernel is an HTTP client of its own server — no comm, no comm target, no control socket). No ipywidgets. Conventions: C0
transport = mailbox (RPC); C1 host verbs = a closed subset of the GeoGebra Apps API (7 on 2026-09-07: writes eval/new/delete/xml_in, reads xml_out/value, subscription listen); C2 never rely
on the shell channel for replies, queue until the applet is ready; C3 Horn-clause style.
The anywidget adapter (host/anywidget_host.py) is kept as adapter #1 for marimo; import it explicitly."""
from .host.control import ControlBridge, kernel_id
from .host.html_host import GeoGebra, find_server

__all__ = ["ControlBridge", "kernel_id", "GeoGebra", "find_server"]
