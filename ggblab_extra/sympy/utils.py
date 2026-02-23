"""Lightweight facade utilities (moved into sympy subpackage).

This module keeps a small set of convenience helpers that previously
lived in `ggblab_extra/sympy_utils.py`. It intentionally only exposes a
few functions and delegates heavy work to sibling modules.
"""
# Lightweight facade utilities (moved into sympy subpackage).

# This module keeps a small set of convenience helpers that previously
# lived in `ggblab_extra/sympy_utils.py`. It intentionally only exposes a
from typing import Optional

# Module-level applet dimensionality flag. Use `set_applet_3d` / `get_applet_3d`
_is_applet_3d: Optional[bool] = None


def set_applet_3d(value: Optional[bool]) -> None:
    """Set module-level `_is_applet_3d` flag (True/False/None)."""
    global _is_applet_3d
    _is_applet_3d = True if value else (False if value is False else None)


def get_applet_3d(force: bool = False) -> Optional[bool]:
    """Return the module-level `_is_applet_3d` flag.

    If `force` is True, re-run the detector even if a cached value exists.
    """
    # If we already know the mode and caller didn't request a forced
    # re-detection, return it.
    if _is_applet_3d is not None and not force:
        return _is_applet_3d

    # Otherwise, attempt to discover it by calling the async detector.
    try:
        import asyncio

        # If an event loop is already running (e.g. IPython), schedule a
        # background task to detect and set the value and return None
        # immediately (caller can read the updated value later).
        loop = asyncio.get_event_loop()
        if loop.is_running():
            try:
                # If caller requested a forced synchronous detection while an
                # event loop is running (e.g. in Jupyter), attempt to apply
                # `nest_asyncio` so we can run the detector synchronously.
                if force:
                    try:
                        import nest_asyncio

                        nest_asyncio.apply()
                        val = asyncio.run(is_applet_3d_from_ggblab())
                        set_applet_3d(val)
                        return val
                    except (ImportError, AttributeError, RuntimeError, TypeError):
                        # Fall back to scheduling a background task if nest_asyncio
                        # isn't available or running synchronously fails.
                        pass
                coro = is_applet_3d_from_ggblab()
                task = loop.create_task(coro)

                def _cb(fut):
                    try:
                        res = fut.result()
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        res = None
                    try:
                        set_applet_3d(res)
                    except (AttributeError, TypeError):
                        pass

                task.add_done_callback(_cb)
                return None
            except (AttributeError, RuntimeError, TypeError):
                return None
        # No running loop: run detector synchronously.
        val = asyncio.run(is_applet_3d_from_ggblab())
        set_applet_3d(val)
        return val
    except (ImportError, RuntimeError, AttributeError, TypeError):
        return None
# Note: `set_applet_3d` / `get_applet_3d` live in `ggblab_extra.sympy.point`.
# Callers should import them from `ggblab_extra.sympy.point` directly.


async def is_applet_3d_from_ggblab(ggb=None) -> Optional[bool]:
    """Return True/False if the running GeoGebra applet is 3D, else None.

    If `ggb` is provided, use it. If not, attempt to discover an
    implicit GeoGebra instance created by the IPython magics: prefer
    `GeoGebra._instance` if present, otherwise look for `ggb` in the
    IPython `user_ns` (the `ipymagic` helpers store a singleton there).
    """
    # If caller didn't pass an instance, try to find an implicit one.
    if ggb is None:
        try:
            from ggblab.ipymagic import GeoGebra

            inst = getattr(GeoGebra, '_instance', None)
            if inst is not None:
                ggb = inst
            else:
                # fallback: check IPython user_ns for a 'ggb' binding
                try:
                    from IPython import get_ipython

                    ip = get_ipython()
                    user_ns = getattr(ip, 'user_ns', None) if ip is not None else None
                except (ImportError, AttributeError, RuntimeError):
                    user_ns = None
                if isinstance(user_ns, dict) and 'ggb' in user_ns:
                    ggb = user_ns.get('ggb')
        except (ImportError, AttributeError):
            # If ipymagic or IPython aren't available, continue with ggb=None
            ggb = None

    if ggb is None:
        return None

    try:
        xml = await ggb.function("getXML")
    except (AttributeError, TypeError, RuntimeError, ValueError):
        return None
    if not xml:
        return None
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
    except (ImportError, ET.ParseError, ValueError):
        return None
    app_attr = (root.get("app") or "").lower()
    sub_attr = (root.get("subApp") or "").lower()
    return ("3d" in app_attr) or ("3d" in sub_attr)


__all__ = [
    "is_applet_3d_from_ggblab",
    # removed: set_applet_3d, get_applet_3d — import from ggblab_extra.sympy.point
    "set_applet_3d",
    "get_applet_3d",
]


def is_pointlike(obj: object) -> bool:
    """Return True if `obj` looks like a point (has `x` and `y`)."""
    try:
        return hasattr(obj, "x") and hasattr(obj, "y")
    except (AttributeError, TypeError):
        return False


def resolve_label_to_point(label: str, df, name_col: str, value_col: str, obj_col: str):
    """Resolve a point-like object for `label` using `df` (polars/pandas).

    Mirrors the resolution logic used by parsers: prefer an attached `obj`
    value that is point-like, otherwise try to parse the `Value` cell.
    Returns the resolved point-like object or None.
    """
    import importlib
    try:
        point_mod = importlib.import_module("ggblab_extra.sympy.point")
        sympy_point_from_coords = getattr(point_mod, "sympy_point_from_coords")
        point_from_value = getattr(point_mod, "point_from_value")
    except (ImportError, AttributeError):
        sympy_point_from_coords = None
        point_from_value = None
    from sympy.parsing.sympy_parser import parse_expr
    from sympy.parsing.sympy_parser import standard_transformations
    from sympy.parsing.sympy_parser import implicit_multiplication_application

    _transformations = standard_transformations + (implicit_multiplication_application,)

    if is_pointlike(label):
        return label
    if not isinstance(label, str):
        return None
    if df is None:
        return None
    try:
        matches = df.filter(df[name_col] == label)
        if len(matches) == 0:
            return None
        try:
            obj = matches[obj_col][0]
            resolved = getattr(obj, "obj", obj) if obj is not None else None
            if is_pointlike(resolved):
                return resolved
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        try:
            raw = matches[value_col][0]
            # Normalize the stored value and strip any leading label/equals/parentheses
            s = str(raw).strip()
            s = s.lstrip(label).strip()
            s = s.lstrip("=").strip().strip("()")
            comps = [v.strip() for v in s.split(",")]
            # Parse with sympy if available, otherwise return a tuple of parsed exprs
            parsed = [parse_expr(v, transformations=_transformations) for v in comps]
            if sympy_point_from_coords is not None:
                return sympy_point_from_coords(*parsed)
            return tuple(parsed)
        except (IndexError, TypeError, ValueError, AttributeError):
            return None
    except (AttributeError, TypeError):
        try:
            sel = df[df[name_col] == label]
            if len(sel) == 0:
                return None
            row = sel.iloc[0]
            try:
                obj = row[obj_col]
                resolved = getattr(obj, "obj", obj) if obj is not None else None
                if is_pointlike(resolved):
                    return resolved
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
            try:
                if point_from_value is not None:
                    return point_from_value(row[value_col])
                return None
            except (TypeError, ValueError, AttributeError):
                return None
        except (TypeError, AttributeError, IndexError):
            return None
