"""Lightweight facade utilities (moved into sympy subpackage).

This module keeps a small set of convenience helpers that previously
lived in `ggblab_extra/sympy_utils.py`. It intentionally only exposes a
few functions and delegates heavy work to sibling modules.
"""
from typing import Optional

from .point import set_applet_3d, get_applet_3d


# `make_object_from_value_command` was removed; use `attach_object2d`/`attach_object3d`
# or call `Object2D.from_value_command` / `Object3D.from_value_command` directly.


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
    "is_applet_3d_from_ggblab",
    "set_applet_3d",
    "get_applet_3d",
]
