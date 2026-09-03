"""ggblab — replay lineage (stage 0: 鞭毛 = applet mount + control-channel comm + external ops).

Conventions (2026-09-03 draft): C0 origin A = control-channel comm_msg; C1 host adapters behind 5 verbs;
C2 never rely on the shell channel for applet replies; C3 Horn-clause style (heads = discriminated unions).
"""
from .host.control import ControlComm, kernel_id
from .host.anywidget_host import GeoGebraWidget, GeoGebra

__all__ = ["ControlComm", "kernel_id", "GeoGebraWidget", "GeoGebra"]
