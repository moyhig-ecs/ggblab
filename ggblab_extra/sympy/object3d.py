"""3D helpers moved into sympy subpackage (renamed object3d).

Provides `Object3D`, `Segment` and `attach_object3d` which attaches an
`object3d` column to a Polars DataFrame by resolving `Type`, `Command`,
and `Value` using the 3D parsers.
"""
from dataclasses import dataclass
from typing import Optional

try:
    from sympy.geometry import Point3D as SympyPoint3D
except Exception:
    SympyPoint3D = None
try:
    from sympy.geometry.line3d import Line3D as SympyLine3D
except ImportError:
    try:
        from sympy.geometry import Line3D as SympyLine3D
    except ImportError:
        SympyLine3D = None
from .line import SimpleLine3D, to_sympy_line, segment_from_command as _segment_from_command, SegmentCommand


# Note: segment commands are represented by `SegmentCommand` from `line.py`.


@dataclass
class Object3D:
    """Container describing a parsed 3D object and its origin metadata."""
    kind: str | None = None
    obj: object | None = None
    value: str | None = None
    command: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - formatting
        return (
            f"Object3D(kind={self.kind!r}, obj={self.obj!r}, "
            f"value={self.value!r}, command={self.command!r})"
        )

    @classmethod
    def from_value_command(cls, value: str | None = None, command: str | None = None, type_: str | None = None):
        """Construct an `Object3D` by heuristically parsing `value`/`command`.

        This method uses small module-level helpers to keep complexity low.
        """
        # Use declared `type_` as a hint when available. Normalize inputs.
        try:
            declared = type_.strip().lower() if isinstance(type_, str) else None
        except (AttributeError, TypeError):
            declared = None

        cmd_lower = command.strip().lower() if isinstance(command, str) else ""
        looks_parametric = False
        if isinstance(value, str):
            vl = value.lower()
            looks_parametric = (": x =" in vl) or ("cos(" in vl) or ("sin(" in vl)

        # Declared type takes precedence
        if declared == "line":
            seg = _try_segment_from_command(command) if command else None
            if seg is not None:
                return cls(kind="segment", obj=seg, value=value, command=command)
            inner = _try_line_from_value(value)
            if inner is not None:
                return cls(kind="line", obj=inner, value=value, command=command)

        if declared == "circle":
            inner = _try_circle_from_value(value)
            if inner is not None:
                return cls(kind="circle", obj=inner, value=value, command=command)

        if declared == "point":
            inner = _try_point_from_value(value)
            if inner is not None:
                return cls(kind="point", obj=inner, value=value, command=command)

        if declared == "surface":
            inner = _try_surface_from_value(value)
            if inner is not None:
                return cls(kind="surface", obj=inner, value=value, command=command)

        # Heuristics: prefer circle for explicit curve commands or parametric values
        if cmd_lower.startswith("cylinder") or cmd_lower.startswith("circle") or cmd_lower.startswith("intersectpath") or looks_parametric:
            inner = _try_circle_from_value(value)
            if inner is not None:
                return cls(kind="circle", obj=inner, value=value, command=command)

        # If value looks like a 2-parameter parametric surface try parsing
        if isinstance(value, str):
            vl = value.lower()
            # crude heuristic: contains both 'u' and 'v' and at least three comma-separated expressions
            if ("u" in vl and "v" in vl and ("cos(" in vl or "sin(" in vl or "tan(" in vl)):
                inner = _try_surface_from_value(value)
                if inner is not None:
                    return cls(kind="surface", obj=inner, value=value, command=command)

        # Command-based segment parse
        seg = _try_segment_from_command(command) if command else None
        if seg is not None:
            return cls(kind="segment", obj=seg, value=value, command=command)

        # Fallback value-based resolution
        if value:
            if looks_parametric:
                inner = _try_line_from_value(value)
                if inner is not None:
                    return cls(kind="line", obj=inner, value=value, command=command)
            inner = _try_point_from_value(value)
            if inner is not None:
                return cls(kind="point", obj=inner, value=value, command=command)
            inner = _try_circle_from_value(value)
            if inner is not None:
                return cls(kind="circle", obj=inner, value=value, command=command)
            inner = _try_line_from_value(value)
            if inner is not None:
                return cls(kind="line", obj=inner, value=value, command=command)

        return cls(kind=None, obj=None, value=value, command=command)


def _is_degenerate_circle(cand) -> bool:
    """Return True if `cand` is a circle-like object with zero radius.

    Safe to call on unknown objects; returns False if radius not available.
    """
    try:
        r = getattr(cand, "radius", None)
        if r is None:
            return False
        return float(r) == 0.0
    except (AttributeError, TypeError, ValueError):
        return False

def _try_segment_from_command(cmd: str):
    if not cmd:
        return None
    try:
        sc = _segment_from_command(cmd)
        if hasattr(sc, "p1") and hasattr(sc, "p2"):
            return sc
    except (AttributeError, TypeError, ValueError):
        return None
    return None

def _try_line_from_value(val: str):
    if not val:
        return None
    try:
        from .line import line_from_value

        l = line_from_value(val)
        inner = l.obj if hasattr(l, "obj") else l
        sym = getattr(inner, "sympy", None)
        return sym if sym is not None else inner
    except (ImportError, AttributeError, TypeError, ValueError):
        return None

def _try_circle_from_value(val: str):
    if not val:
        return None
    try:
        from .circle import circle_from_value

        c = circle_from_value(val)
        if not _is_degenerate_circle(c):
            return c
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    return None

def _try_surface_from_value(val: str):
    if not val:
        return None
    try:
        from .surface import surface_from_value

        s = surface_from_value(val)
        return s.sympy if getattr(s, "sympy", None) is not None else s
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    return None

def _try_point_from_value(val: str):
    if not val:
        return None
    try:
        from .point import point_from_value

        p = point_from_value(val)
        return p.obj if hasattr(p, "obj") else p
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
def segment_from_command(command_str: str) -> SegmentCommand:
    """Return the underlying `SegmentCommand` parsed from `command_str`."""
    sc = _segment_from_command(command_str)
    return sc


def attach_object3d(df, type_col: str = "Type", command_col: str = "Command", value_col: str = "Value", out_col: str = "object3d"):
    """Attach an `Object3D` for each row using `Type`, `Command`, and `Value`.

    Expects a Polars DataFrame and returns a new DataFrame with the
    additional `out_col` column containing `Object3D` instances (or `None`).
    """
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_object3d requires a polars DataFrame")

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    # Force re-detection of the applet mode before processing rows.
    try:
        from .utils import get_applet_3d

        try:
            _ = get_applet_3d(force=True)
        except (AttributeError, TypeError):
            # Best-effort: ignore detection errors and continue.
            pass
    except (ImportError, AttributeError):
        pass
    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            type_norm = t.strip().lower() if isinstance(t, str) else None
        except (AttributeError, TypeError):
            type_norm = None

        if type_norm in ("list", "numeric"):
            objs.append(None)
            continue

        try:
            o = Object3D.from_value_command(value=v if v is not None else None, command=c if c is not None else None, type_=type_norm)
        except (AttributeError, TypeError, ValueError):
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append(o)
    try:
        s = pl.Series(out_col, objs, dtype=getattr(pl, "Object"))
    except (TypeError, AttributeError):
        s = pl.Series(out_col, objs)
    return df.with_columns([s])


__all__ = [
    "SimpleLine3D",
    "SegmentCommand",
    "to_sympy_line",
    "segment_from_command",
    "Object3D",
    "attach_object3d",
]
