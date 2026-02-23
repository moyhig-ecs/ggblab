"""Lightweight facade utilities (moved into sympy subpackage).

This module keeps a small set of convenience helpers that previously
lived in `ggblab_extra/sympy_utils.py`. It intentionally only exposes a
few functions and delegates heavy work to sibling modules.
"""
from typing import Optional

from .point import set_applet_3d, get_applet_3d
from .three_d import Object3D
from .two_d import Object2D


def make_object_from_value_command(value: str | None = None, command: str | None = None, is_3d: Optional[bool] = None):
    if is_3d is None:
        flag = get_applet_3d()
    else:
        flag = is_3d
    is3d_flag = bool(flag) if flag is not None else False
    if is3d_flag:
        return Object3D.from_value_command(value=value, command=command)
    return Object2D.from_value_command(value=value, command=command)


async def is_applet_3d_from_ggblab(ggb) -> Optional[bool]:
    if ggb is None:
        return None
    try:
        xml = await ggb.function("getXML")
    except Exception:
        return None
    if not xml:
        return None
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
    except Exception:
        return None
    app_attr = (root.get("app") or "").lower()
    sub_attr = (root.get("subApp") or "").lower()
    return ("3d" in app_attr) or ("3d" in sub_attr)


__all__ = [
    "make_object_from_value_command",
    "is_applet_3d_from_ggblab",
    "set_applet_3d",
    "get_applet_3d",
]
