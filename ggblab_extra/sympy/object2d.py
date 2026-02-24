"""2D helpers moved into sympy subpackage (renamed object2d).

Provides `Object2D` and `attach_object2d` which attaches an `object2d`
column to a Polars DataFrame by resolving `Type`, `Command`, and `Value`.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Object2D:
    """Container describing a parsed 2D object and its metadata."""
    kind: Optional[str] = None
    obj: object | None = None
    value: str | None = None
    command: str | None = None

    @classmethod
    def from_value_command(
        cls,
        value: str | None = None,
        command: str | None = None,
        type_: Optional[str] = None,
        df=None,
        name_col: str = "Name",
        value_col: str = "Value",
        obj_col: str = "object2d",
    ):
        # Prefer using declared `type_` when available to pick parsers.
        # Defer to specialized parsers to construct SymPy-backed objects.
        try:
            if type_ is not None:
                t = type_.strip().lower()
            else:
                t = None
        except (AttributeError, TypeError):
            t = None

        # Try command-based resolution first for constructs like Segment(...)/Ray(...)
        if command:
            cmd = command.strip()
            try:
                if cmd.lower().startswith("segment"):
                    from .line import segment_from_command

                    seg = segment_from_command(command, df, name_col, value_col, obj_col)
                    return cls(kind="segment", obj=seg, value=value, command=command)
                if cmd.lower().startswith("ray"):
                    from .line import ray_from_command

                    r = ray_from_command(command, df, name_col, value_col, obj_col)
                    return cls(kind="ray", obj=r, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                # Best-effort: if parsing fails, continue to other heuristics.
                pass

        # Type-driven or value-driven parsing
        if t == "point":
            try:
                from .point import point_from_value

                pwrap = point_from_value(value)
                return cls(kind="point", obj=getattr(pwrap, "obj", pwrap), value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                return cls(kind="point", obj=None, value=value, command=command)

        if t == "circle":
            try:
                from .circle import circle_from_value

                c = circle_from_value(value)
                return cls(kind="circle", obj=c, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                return cls(kind="circle", obj=None, value=value, command=command)

        if t in ("curvecartesian", "curve"):
            try:
                from .curve import curve_from_value

                cv = curve_from_value(command or value)
                obj_val = cv.sympy if getattr(cv, "sympy", None) is not None else cv
                return cls(kind="curvecartesian", obj=obj_val, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                return cls(kind="curvecartesian", obj=None, value=value, command=command)

        if t == "line":
            try:
                from .line import line_from_value

                l = line_from_value(value)
                return cls(kind="line", obj=getattr(l, "obj", l), value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                return cls(kind="line", obj=None, value=value, command=command)

        if t == "segment":
            try:
                from .line import segment_from_command

                seg = segment_from_command(command or value)
                return cls(kind="segment", obj=seg, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                return cls(kind="segment", obj=None, value=value, command=command)

        if t == "list":
            return cls(kind="list", obj=None, value=value, command=command)

        # Heuristic fallback: try point -> circle -> line
        if value:
            v = value.strip()
            # Prefer treating explicit Curve(...) commands or parametric values as curves
            try:
                if isinstance(v, str) and (v.lower().startswith("curve(") or (":" in v and ("cos(" in v or "sin(" in v))):
                    from .curve import curve_from_value

                    cv = curve_from_value(command or value)
                    obj_val = cv.sympy if getattr(cv, "sympy", None) is not None else cv
                    return cls(kind="curvecartesian", obj=obj_val, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                pass
            try:
                from .point import point_from_value

                pwrap = point_from_value(value)
                return cls(kind="point", obj=getattr(pwrap, "obj", pwrap), value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                pass
            try:
                from .circle import circle_from_value

                c = circle_from_value(value)
                return cls(kind="circle", obj=c, value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                pass
            try:
                from .line import line_from_value

                l = line_from_value(value)
                return cls(kind="line", obj=getattr(l, "obj", l), value=value, command=command)
            except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError):
                pass

        # Unknown/unsupported
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
    # Force re-detection of the applet mode before processing rows.
    try:
        from .utils import get_applet_3d
    except ImportError:
        # utils may be absent in minimal environments; continue gracefully.
        get_applet_3d = None  # type: ignore
    else:
        try:
            _ = get_applet_3d(force=True)
        except (RuntimeError, TypeError, ValueError):
            # Best-effort: ignore detection errors and continue.
            pass

    objs = []
    for t, c, v in zip(types, cmds, vals):
        # If the declared type is an unsupported container like 'list', do not attach.
        try:
            type_norm = t.strip().lower() if isinstance(t, str) else None
        except (AttributeError, TypeError):
            type_norm = None

        if type_norm in ("list", "numeric"):
            objs.append(None)
            continue

        try:
            o = Object2D.from_value_command(
                value=v if v is not None else None,
                command=c if c is not None else None,
                type_=t,
                df=df,
                name_col=type_col if False else "Name",
                value_col=value_col,
                obj_col=out_col,
            )
        except (ImportError, AttributeError, TypeError, ValueError, IndexError, KeyError, RuntimeError):
            o = Object2D(kind=None, obj=None, value=v, command=c)
        objs.append(o)
    try:
        s = pl.Series(out_col, objs, dtype=getattr(pl, "Object"))
    except (AttributeError, TypeError):
        s = pl.Series(out_col, objs)
    return df.with_columns([s])


__all__ = ["Object2D", "attach_object2d"]
