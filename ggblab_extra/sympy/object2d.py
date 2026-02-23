"""2D helpers moved into sympy subpackage (renamed object2d).

Provides `Object2D` and `attach_object2d` which attaches an `object2d`
column to a Polars DataFrame by resolving `Type`, `Command`, and `Value`.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Object2D:
    kind: Optional[str] = None
    obj: object | None = None
    value: str | None = None
    command: str | None = None

    @classmethod
    def from_value_command(cls, value: str | None = None, command: str | None = None):
        if command:
            try:
                # defer to sympy.line's segment parser for simple commands
                from .line import segment_from_command

                seg = segment_from_command(command)
                return cls(kind="segment", obj=seg, value=value, command=command)
            except Exception:
                pass
        if value:
            try:
                # best-effort: attempt to detect simple 2D constructs
                if value.strip().lower().startswith("segment"):
                    try:
                        from .line import segment_from_command

                        seg = segment_from_command(value)
                        return cls(kind="segment", obj=seg, value=value, command=command)
                    except Exception:
                        pass
                if value.strip().startswith("(") or "=" in value:
                    # could be a point or simple 2D value; leave for callers to parse
                    return cls(kind=None, obj=None, value=value, command=command)
            except Exception:
                pass
        return cls(kind=None, obj=None, value=value, command=command)


def attach_object2d(df, type_col: str = "Type", command_col: str = "Command", value_col: str = "Value", out_col: str = "object2d"):
    """Attach an `Object2D` for each row using `Type`, `Command`, and `Value`.

    - Expects a Polars DataFrame and returns a new DataFrame with the
      additional `out_col` column containing `Object2D` instances.
    """
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        raise TypeError("attach_object2d requires a polars DataFrame")

    types = df[type_col].to_list()
    cmds = df[command_col].to_list()
    vals = df[value_col].to_list()
    objs = []
    for t, c, v in zip(types, cmds, vals):
        try:
            o = Object2D.from_value_command(value=v if v is not None else None, command=c if c is not None else None)
        except Exception:
            o = Object2D(kind=None, obj=None, value=v, command=c)
        objs.append(o)
    try:
        s = pl.Series(out_col, objs, dtype=getattr(pl, "Object"))
    except Exception:
        s = pl.Series(out_col, objs)
    return df.with_columns([s])


__all__ = ["Object2D", "attach_object2d"]
