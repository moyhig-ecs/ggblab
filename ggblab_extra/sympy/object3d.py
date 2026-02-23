"""3D helpers moved into sympy subpackage (renamed object3d).

Provides `Object3D`, `Segment` and `attach_object3d` which attaches an
`object3d` column to a Polars DataFrame by resolving `Type`, `Command`,
and `Value` using the 3D parsers.
"""
import math
import re
from dataclasses import dataclass
from typing import Optional
import xml.etree.ElementTree as ET

from sympy import Matrix, cos, sin, sqrt, symbols
from sympy.geometry import Point3D as SympyPoint3D
try:
    from sympy.geometry.line3d import Line3D as SympyLine3D
except Exception:
    try:
        from sympy.geometry import Line3D as SympyLine3D
    except Exception:
        SympyLine3D = None
from .line import SimpleLine3D, to_sympy_line, segment_from_command as _segment_from_command


@dataclass
class Segment:
    p1: SympyPoint3D | str | None = None
    p2: SympyPoint3D | str | None = None
    length: Optional[float] = None
    parent: Optional[str] = None

    def __repr__(self) -> str:  # pragma: no cover - simple formatting
        if self.p1 is not None and self.p2 is not None:
            return f"Segment(p1={self.p1}, p2={self.p2})"
        return f"Segment(length={self.length})"


@dataclass
class Object3D:
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
    def from_value_command(cls, value: str | None = None, command: str | None = None):
        if command:
            try:
                sc = _segment_from_command(command)
                if hasattr(sc, "p1") and hasattr(sc, "p2"):
                    return cls(kind="segment", obj=sc, value=value, command=command)
            except Exception:
                pass

        if value:
            try:
                from .point import point_from_value

                p = point_from_value(value)
                return cls(kind="point", obj=p.obj, value=value, command=command)
            except Exception:
                pass
            try:
                from .circle import circle_from_value

                c = circle_from_value(value)
                return cls(kind="circle", obj=c, value=value, command=command)
            except Exception:
                pass
            try:
                from .line import line_from_value

                l = line_from_value(value)
                return cls(kind="line", obj=l.obj if hasattr(l, "obj") else l, value=value, command=command)
            except Exception:
                pass

        return cls(kind=None, obj=None, value=value, command=command)


def segment_from_command(command_str: str) -> Segment:
    sc = _segment_from_command(command_str)
    if hasattr(sc, "p1") and hasattr(sc, "p2"):
        return Segment(p1=getattr(sc, "p1", None), p2=getattr(sc, "p2", None), parent=getattr(sc, "parent", None))
    return Segment(p1=None, p2=None)


def attach_object3d(df, type_col: str = "Type", command_col: str = "Command", value_col: str = "Value", out_col: str = "object3d"):
    """Attach an `Object3D` for each row using `Type`, `Command`, and `Value`.

    - Expects a Polars DataFrame and returns a new DataFrame with the
      additional `out_col` column containing `Object3D` instances (or `None` for
      unsupported declared types like `list`).
    """
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_object3d requires a polars DataFrame")

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            type_norm = t.strip().lower() if isinstance(t, str) else None
        except Exception:
            type_norm = None

        if type_norm == "list":
            objs.append(None)
            continue

        try:
            o = Object3D.from_value_command(value=v if v is not None else None, command=c if c is not None else None)
        except Exception:
            o = Object3D(kind=None, obj=None, value=v, command=c)
        objs.append(o)
    try:
        s = pl.Series(out_col, objs, dtype=getattr(pl, "Object"))
    except Exception:
        s = pl.Series(out_col, objs)
    return df.with_columns([s])


__all__ = [
    "SimpleLine3D",
    "Segment",
    "to_sympy_line",
    "segment_from_command",
    "Object3D",
    "attach_object3d",
]
