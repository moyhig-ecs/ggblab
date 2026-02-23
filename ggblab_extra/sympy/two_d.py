"""2D helpers moved into sympy subpackage."""
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
                from .line import segment_from_command

                seg = segment_from_command(command)
                return cls(kind="segment", obj=seg, value=value, command=command)
            except Exception:
                pass
        if value:
            try:
                if value.strip().lower().startswith("segment"):
                    try:
                        from .line import segment_from_command

                        seg = segment_from_command(value)
                        return cls(kind="segment", obj=seg, value=value, command=command)
                    except Exception:
                        pass
                if value.strip().startswith("(") or "=" in value:
                    return cls(kind=None, obj=None, value=value, command=command)
            except Exception:
                pass
        return cls(kind=None, obj=None, value=value, command=command)


__all__ = ["Object2D"]
