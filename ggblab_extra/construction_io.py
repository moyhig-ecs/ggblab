"""ggblab_extra.construction_io — data-in (teacher's ruling 2026-09-08: option I).

The DataFrame is built from construction XML only.  Communication is the host's business: a caller fetches the XML
with the host's `xml_out` verb (`GeoGebra.xml()` in v2) or reads a .ggb file, then hands the STRING to this module.
No juliacall, no `called_from_julia`, no monkeypatching, no `async`: the same code serves Python and (via PythonCall,
one-way) Julia.  `getValueString` is not used (ruling ii): the `Value` column is the expression / IR read from the XML,
exactly as v1's file path (`_build_df_from_ggb_file`) already did.  The decode-and-build logic is carried from v1 verbatim.
"""
from __future__ import annotations

import base64, io, json, re, zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import polars as pl
import polars.selectors as cs

from ggblab.schema import get_schema
from ggblab.xml_errata import apply_xml_errata, construction_xml, normalize_exponent


def _decode(xml: str) -> Dict[str, Any]:
    """Schema-decode a construction document; on failure retry after the errata pass (v1 behaviour)."""
    sch = get_schema()
    doc = construction_xml(xml)
    try:
        return sch.decode(normalize_exponent(doc))
    except Exception:
        return sch.decode(normalize_exponent(apply_xml_errata(doc)))


def read_ggb(path: Union[str, Path]) -> str:
    """Return the geogebra.xml text of a .ggb (zip / base64-zip / json archive / plain xml) — v1 `ggb_file.load`."""
    p = Path(path); raw = p.read_bytes()
    def unzip(b: bytes) -> str:
        with zipfile.ZipFile(io.BytesIO(b)) as zf:
            return zf.read("geogebra.xml").decode("utf-8")
    if raw[:4] == b"UEsD":
        return unzip(base64.b64decode(raw))
    if raw[:2] == b"PK":
        return unzip(raw)
    if raw[:1] in (b"{", b"["):
        arc = json.loads(raw.decode("utf-8"))
        for f in arc["archive"]:
            if f["fileName"] == "geogebra.xml":
                return f["fileContent"]
        raise ValueError("json archive without geogebra.xml")
    return raw.decode("utf-8")


class ConstructionIO:
    """Construction XML → Polars DataFrame (8 columns + Name + Sequence) and pure helpers on that DataFrame."""

    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral", "curvecartesian"]

    # ---- the one builder (v1 `_build_df_from_ggb_file`, decode step replaced by `_decode`) ----
    @staticmethod
    def _construction_map(o: Dict[str, Any]) -> Dict[str, Any]:
        construction: Dict[str, Any] = {}
        for e in o.get("element", []):
            _n = e.get("@label")
            cmd = None
            exp = None

            for _c in o.get("command", []):
                try:
                    _ci = tuple(zip(*_c["input"].items()))[1]
                except Exception:
                    _ci = tuple()
                try:
                    _co = tuple(zip(*_c["output"].items()))[1]
                except Exception:
                    _co = tuple()

                def build_command_string(edges, vertices):
                    try:
                        i = edges.index(_n)
                        ci_loc = (vertices[i:] + vertices[:i])[:2] + (_co[0],)
                        co_loc = _co[0]
                        return f"Segment({', '.join(ci_loc)})", ci_loc, co_loc
                    except Exception:
                        return None, None, None

                if _n in _co:
                    if _c.get("@name") == "Polygon":
                        try:
                            match _ci:
                                case (p0, p1, "4"):
                                    _, e0, e1, e2, e4, p2, p3 = _co
                                    edges = (e0, e1, e2, e4)
                                    vertices = (p0, p1, p2, p3)
                                    res, ci_loc, co_loc = build_command_string(edges, vertices)
                                    if res:
                                        cmd = res
                                        break
                                case _:
                                    edges = _co[1:]
                                    vertices = _ci
                                    res, ci_loc, co_loc = build_command_string(edges, vertices)
                                    if res:
                                        cmd = res
                                        break
                        except Exception:
                            edges = _co[1:]
                            vertices = _ci
                            res, ci_loc, co_loc = build_command_string(edges, vertices)
                            if res:
                                cmd = res
                                break

                    cmd = f"{_c.get('@name')}({', '.join(_ci)})".replace("OrthogonalLine", "PerpendicularLine").translate(str.maketrans("[]", "()"))
                    break

            for _e in o.get("expression", []):
                if _n == _e.get("@label"):
                    exp = _e.get("@exp")

            construction[_n] = [
                e.get("@type"),
                cmd or exp,
                exp or None,
                e.get("caption", [{}])[0].get("@val"),
                e.get("layer", [{}])[0].get("@val"),
                e.get("show", [{}])[0].get("@object"),
                e.get("show", [{}])[0].get("@label"),
                e.get("auxiliary", [{}])[0].get("@val"),
            ]
        return construction

    @staticmethod
    def _normalize(construction_map: Mapping[str, Sequence], columns: Sequence[str]) -> pl.DataFrame:
        _df = pl.from_dict(dict(construction_map), strict=False)
        norm_df = _df.transpose(include_header=True, header_name="Name", column_names=list(columns)).with_columns(
            pl.col("Layer").cast(pl.UInt32).fill_null(0))
        if "Sequence" not in norm_df.columns:
            norm_df = norm_df.with_row_index("Sequence", offset=1)
        for _bcol in ("ShowObject", "ShowLabel", "Auxiliary"):
            if _bcol in norm_df.columns:
                norm_df = norm_df.with_columns(
                    cs.by_name(_bcol, require_all=False).replace_strict({"false": False, "true": True}, return_dtype=pl.Boolean).fill_null(False))
        return norm_df

    # ---- data-in entry points ----
    @staticmethod
    def from_xml(xml: str, columns: Optional[Sequence[str]] = None) -> pl.DataFrame:
        """Construction XML (getXML() document, <construction> element, or element fragment) → DataFrame."""
        cols = list(columns) if columns is not None else ConstructionIO.COLUMNS
        return ConstructionIO._normalize(ConstructionIO._construction_map(_decode(xml)), cols)

    @staticmethod
    def from_ggb_file(path: Union[str, Path], columns: Optional[Sequence[str]] = None) -> pl.DataFrame:
        return ConstructionIO.from_xml(read_ggb(path), columns)

    @staticmethod
    def from_parquet(path: Union[str, Path]) -> pl.DataFrame:
        df = pl.read_parquet(str(path)).with_columns(pl.col("Layer").cast(pl.UInt32).fill_null(0))
        return df if "Sequence" in df.columns else df.with_row_index("Sequence", offset=1)

    # ---- pure helpers on the DataFrame (v1 verbatim) ----
    @staticmethod
    def commands_for_ggb(df: pl.DataFrame) -> Sequence[str]:
        """Produce a list of GeoGebra command strings ready for `%%ggb` input.

        The returned commands have object `Name` references replaced with the
        underscore-number notation (e.g. `_3`) that the IPython magic understands.

        Args:
            df: Normalized DataFrame returned by `initialize_dataframe`.

        Returns:
            Sequence[str]: list of transformed command strings ordered by `Sequence`.
        """
        if not isinstance(df, pl.DataFrame):
            raise TypeError("df must be a polars DataFrame")
        if "Sequence" not in df.columns or "Name" not in df.columns:
            raise ValueError("DataFrame must contain 'Name' and 'Sequence' columns")

        # Build a mapping from object name -> 1-based sequence index
        try:
            rows = (
                df.select(["Name", "Sequence", "Command", "Type", "Value"])
                .sort("Sequence")
                .to_dicts()
            )
        except Exception:
            # Fallback for older polars versions
            rows = sorted(
                [
                    {
                        k: r.get(k)
                        for k in ("Name", "Sequence", "Command", "Type", "Value")
                    }
                    for r in df.to_dicts()
                ],
                key=lambda x: x.get("Sequence") or 0,
            )

        name_to_seq = {}
        for r in rows:
            n = r.get("Name")
            seq = r.get("Sequence")
            try:
                if n is not None and seq is not None:
                    name_to_seq[str(n)] = int(seq)
            except Exception:
                continue

        import re

        # sort by length so longer names are replaced first to avoid partial
        # replacements (e.g. 'A' inside 'A1')
        names_sorted = sorted(name_to_seq.keys(), key=len, reverse=True)

        def _transform_command(cmd: Optional[str]) -> str:
            if not cmd or not isinstance(cmd, str):
                return ""
            s = cmd
            for name in names_sorted:
                seq = name_to_seq.get(name)
                if seq is None:
                    continue
                # replace whole-name occurrences only
                s = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", f"_{seq}", s)
            return s

        out: list[str] = []
        for r in rows:
            cmd = r.get("Command")
            t = ""
            if cmd:
                t = _transform_command(cmd)
            else:
                # If Command is empty and the object is numeric, try using Value
                typ = r.get("Type")
                val = r.get("Value")
                name = r.get("Name")
                if (typ is not None and str(typ).lower() == "numeric") and val and name:
                    # If Value is already an assignment like "r = 1.5", use it;
                    # otherwise construct "Name = Value".
                    sval = str(val)
                    if "=" in sval:
                        candidate = sval
                    else:
                        candidate = f"{name} = {sval}"
                    t = _transform_command(candidate)
            if t:
                out.append(t)
        return out

    @staticmethod
    def commands_for_magic(
        df: pl.DataFrame, as_string: bool = True, *, use_name_equals: bool = False
    ):
        """Return commands ready for `%%ggb` usage.

        Behavior:
        - By default returns the existing "register" representation where
          object `Name` references are replaced with underscore-number
          notation (e.g. `_3`). This is the historical behavior.
        - If `use_name_equals` is True, returns lines of the form
          "Name = Command" which can be more human-readable or useful for
          frontends that prefer explicit name-to-command mapping.

        Args:
            df: Normalized DataFrame returned by `initialize_dataframe`.
            as_string: If True (default) return a single newline-separated
                string. If False, return a sequence of strings.
            use_name_equals: When True, emit `Name = Command` lines instead
                of the register-style transformed commands.
        """
        if use_name_equals:
            # Build rows ordered by Sequence and emit "Name = Command" for
            # rows that have a non-empty Command value.
            try:
                rows = (
                    df.select(["Name", "Sequence", "Command", "Type", "Value"])
                    .sort("Sequence")
                    .to_dicts()
                )
            except Exception:
                rows = sorted(
                    [
                        {
                            k: r.get(k)
                            for k in ("Name", "Sequence", "Command", "Type", "Value")
                        }
                        for r in df.to_dicts()
                    ],
                    key=lambda x: x.get("Sequence") or 0,
                )

            out = []
            for r in rows:
                name = r.get("Name")
                cmd = r.get("Command")
                if name is None:
                    continue
                if cmd:
                    out.append(f"{name} = {cmd}")
                    continue
                # fallback: if numeric and Value is present, use Value
                typ = r.get("Type")
                val = r.get("Value")
                if typ is not None and str(typ).lower() == "numeric" and val:
                    sval = str(val)
                    if "=" in sval:
                        out.append(sval)
                    else:
                        out.append(f"{name} = {sval}")
                    continue
            if as_string:
                return "\n".join(out)
            return out

        # Default (backwards-compatible): register-style transformation
        cmds = ConstructionIO.commands_for_ggb(df)
        if as_string:
            return "\n".join(cmds)
        return cmds

    @staticmethod
    def write_parquet(df: pl.DataFrame, file: Optional[str] = None) -> None:
        """Write the provided DataFrame to a Parquet file if `file` is given."""
        if file is not None:
            df.write_parquet(file)

    @staticmethod
    def save_dataframe(
        df: pl.DataFrame,
        ggb=None,
        fmt: str = "parquet",
        out_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> str:
        """Save a polars DataFrame to parquet or json.

        Args:
            df: polars DataFrame to save.
            ggb: optional ggb_file-like object; used to derive filename base from `ggb.source_file`.
            fmt: 'parquet' or 'json'.
            out_dir: directory to write the file (defaults to current directory).
            overwrite: if False and file exists, append _1, _2.. to base name.

        Returns:
            str: path to written file.
        """
        if fmt not in ("parquet", "json"):
            raise ValueError("fmt must be 'parquet' or 'json'")

        if (
            ggb is not None
            and hasattr(ggb.file, "source_file")
            and ggb.file.source_file
        ):
            base = Path(ggb.file.source_file).stem
        else:
            base = "construction"

        out_dir = Path(out_dir) if out_dir is not None else Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)

        ext = ".parquet" if fmt == "parquet" else ".json"
        target = out_dir / f"{base}{ext}"

        def _next_available(p: Path) -> Path:
            if overwrite or not p.exists():
                return p
            root = p.stem
            suffix = p.suffix
            i = 1
            while True:
                candidate = p.with_name(f"{root}_{i}{suffix}")
                if not candidate.exists():
                    return candidate
                i += 1

        target = _next_available(target)

        if fmt == "parquet":
            df.write_parquet(str(target))
        else:
            # json: use Polars native writer when available
            try:
                df.write_json(str(target))
            except Exception:
                # fallback to explicit serialization
                rows = df.to_dicts()
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)

        return str(target)

    # The `save_temp_ir_from_file` helper was removed: prefer producing
    # JSON IR via `initialize_dataframe` or use `save_dataframe` to persist
    # DataFrame results. XML->IR conversion is intentionally not included.


DataFrameIO = ConstructionIO
__all__ = ["ConstructionIO", "DataFrameIO", "read_ggb"]
