"""ggblab_extra.construction_io.

Moved implementation of ConstructionIO into a separate optional package.

This file is a mostly verbatim copy of the original implementation with
imports adjusted for absolute package layout so it can live outside the
`ggblab` package tree.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence, Union
import re

import polars as pl
import polars.selectors as cs
import asyncio
import types

# Optional juliacall integration: if running inside a Julia-embedded Python
# (or juliacall is available), provide async wrappers that call into
# `jl.GeoGebra.send_function` / `jl.GeoGebra.send_command` so existing
# `ggb.function(...)` usage can be redirected to Julia implementations.
HAVE_JL = False
_jl = None
try:
    # Prefer using the project's `called_from_julia()` probe to detect
    # whether Python is running embedded inside Julia. Import helpers
    # from `ggblab.utils_julia` to route calls to Julia when appropriate.
    try:
        from ggblab.utils_julia import called_from_julia, maybe_await, jl_function_sync, jl_command_sync, patch_ggb_for_julia
    except Exception:
        called_from_julia = lambda: False
        maybe_await = lambda x: x
        jl_function_sync = None
        jl_command_sync = None
        patch_ggb_for_julia = None
except Exception:
    called_from_julia = lambda: False
    maybe_await = lambda x: x
    jl_function_sync = None
    jl_command_sync = None
    patch_ggb_for_julia = None


if TYPE_CHECKING:
    from ggblab.ggbapplet import GeoGebra


def _normalize_exponent(xml: str) -> str:
    """Convert lowercase scientific 'e' to uppercase 'E' in numeric literals.

    GeoGebra sometimes emits numbers like '3.67e-16'. XML schema validation
    used elsewhere expects 'E' (pattern includes 'E') so normalize here.
    """
    if not isinstance(xml, str):
        return xml
    return re.sub(r'(?<=\d)e(?=[+-]?\d+)', 'E', xml)


class ConstructionIO:
    """Helper class for building and persisting GeoGebra construction DataFrames.

    This module provides helpers for building a Polars DataFrame from a
    GeoGebra applet, saving the resulting DataFrame to disk and other
    convenience functions. Historically this module included a complex XML
    parser helper called ``_parse_construction_xml``; that helper has been
    removed because the preferred IR representation is now the JSON-like IR
    stored in DataFrame ``Value`` fields. The rest of the helpers remain.
    """

    COLUMNS = [
        "Type",
        "Command",
        "Value",
        "Caption",
        "Layer",
        "ShowObject",
        "ShowLabel",
        "Auxiliary",
    ]
    SHAPES = [
        "point",
        "segment",
        "vector",
        "ray",
        "line",
        "circle",
        "conic",
        "polygon",
        "triangle",
        "quadrilateral",
        "curvecartesian",
    ]

    # Common GeoGebra function names used when querying object properties
    FUNCTION_FIELDS = [
        "getObjectType",
        "getCommandString",
        "getValueString",
        "getCaption",
        "getLayer",
    ]

    # NOTE: XML errata handling has been moved to the ggb_file helper in
    # `ggblab.file`. ConstructionIO will call the file-level errata helpers
    # when attempting to decode legacy XML formats.

    @staticmethod
    async def _build_df_from_applet(
        ggb: "GeoGebra", columns: Optional[Sequence[str]] = None
    ) -> Mapping[str, Sequence]:
        if columns is None:
            columns = ConstructionIO.COLUMNS

        if ggb is None:
            raise ValueError(
                "ggb runner is required for async construction building; ggb must not be None"
            )

        construction: Dict[str, Any] = {}
        # Call ggb.function and await only if necessary. `maybe_await`
        # ensures that when Python is embedded in Julia we don't await
        # synchronous juliacall results.
        # If available, patch the ggb instance to call into Julia
        # synchronously; this mirrors the previous local behavior.
        if patch_ggb_for_julia is not None:
            patch_ggb_for_julia(ggb)

        res = ggb.function("getAllObjectNames")
        objs = await maybe_await(res)

        for o in objs:
            r_res = ggb.function(ConstructionIO.FUNCTION_FIELDS, [o])
            r = await maybe_await(r_res)
            r2_res = ggb.function("getXML", [o])
            r2 = await maybe_await(r2_res)
            # Normalize scientific exponent notation: GeoGebra sometimes
            # emits lowercase 'e' (e.g. 3.67e-16) which fails XML schema
            # validators that expect 'E'. Convert to 'E' before decoding.
            if isinstance(r2, str):
                r2 = _normalize_exponent(r2)
            try:
                o2 = ggb.file.ggb_schema.decode(r2)
            except Exception:
                try:
                    from itertools import chain

                    vr = ET.fromstringlist(
                        chain(["<construction>"], r, ["</construction>"])
                    )
                    xml_vr = ET.tostring(vr).decode("utf-8")
                    xml_vr = _normalize_exponent(xml_vr)
                    o3 = ggb.file.ggb_schema.decode(xml_vr)
                    o2 = o3.get("element", [{}])[0]
                except Exception:
                    o2 = {}

            # Ensure `r` is a list-like sequence before concatenation. When
            # the frontend returns a null/None payload `r` may be None which
            # would raise TypeError on addition. Normalize to a list of
            # placeholders matching the expected fields.
            if isinstance(r, (list, tuple)):
                r_list = list(r)
            elif r is None:
                r_list = [None] * len(ConstructionIO.FUNCTION_FIELDS)
            else:
                r_list = [r]

            construction[o] = r_list + [
                o2.get("show", [{}])[0].get("@object"),
                o2.get("show", [{}])[0].get("@label"),
                o2.get("auxiliary", [{}])[0].get("@val"),
            ]

        return construction

    @staticmethod
    def _build_df_from_ggb_file(
        ggb: "GeoGebra", ggb_path: str, columns: Optional[Sequence[str]] = None
    ) -> Mapping[str, Sequence]:
        if ggb is None:
            raise ValueError(
                "ggb runner is required for .ggb loading; ggb must not be None"
            )
        if not ggb_path:
            raise ValueError("ggb_path must be provided when using ggb runner")

        c = ggb.file.load(ggb_path)
        # Try decoding with the provided schema. If decoding fails due to
        # legacy XML formatting that the schema does not accept (for
        # example older label formats like `O_{1}`), run errata handlers
        # to conservatively transform the XML and retry decoding.
        try:
            o = c.ggb_schema.decode(_normalize_exponent(c.geogebra_xml))
        except Exception:
            try:
                # Apply file-level errata handlers available on the loaded
                # ggb_file instance and retry decoding.
                xml_fixed = getattr(c, "_apply_xml_errata", lambda x: x)(c.geogebra_xml)
                o = c.ggb_schema.decode(_normalize_exponent(xml_fixed))
            except Exception:
                # If decoding still fails, attempt original decode so the
                # original exception propagates as before.
                o = c.ggb_schema.decode(c.geogebra_xml)

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
                                    res, ci_loc, co_loc = build_command_string(
                                        edges, vertices
                                    )
                                    if res:
                                        cmd = res
                                        break
                                case _:
                                    edges = _co[1:]
                                    vertices = _ci
                                    res, ci_loc, co_loc = build_command_string(
                                        edges, vertices
                                    )
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

                    cmd = f"{_c.get('@name')}({', '.join(_ci)})".replace(
                        "OrthogonalLine", "PerpendicularLine"
                    ).translate(str.maketrans("[]", "()"))
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
    def _build_df_from_xml_file(
        xml_path: str, columns: Optional[Sequence[str]] = None
    ) -> Mapping[str, Sequence]:
        if columns is None:
            columns = ConstructionIO.COLUMNS
        raise NotImplementedError(
            "_build_df_from_xml_file requires an XML parser which was removed"
        )

    @staticmethod
    async def initialize_dataframe(
        ggb: Optional["GeoGebra"],
        parquet_file: Optional[Union[str, pl.DataFrame]] = None,
        file: Optional[str] = None,
        *,
        _columns=None,
        use_applet: bool = False,
    ) -> pl.DataFrame:
        """Initialize and normalize a Polars DataFrame from applet/parquet/file.

        Returns a normalized `pl.DataFrame` ready for downstream parsing.
        """
        if _columns is None:
            _columns = ConstructionIO.COLUMNS
        construction_map: Optional[Mapping[str, Sequence]] = None

        if ggb is not None:
            if use_applet:
                construction_map = await ConstructionIO._build_df_from_applet(
                    ggb, columns=_columns
                )
            if file is not None and str(file).lower().endswith(".ggb"):
                construction_map = ConstructionIO._build_df_from_ggb_file(
                    ggb, str(file), columns=_columns
                )

        if (
            construction_map is None
            and file is not None
            and str(file).lower().endswith(".xml")
        ):
            construction_map = ConstructionIO._build_df_from_xml_file(
                str(file), columns=_columns
            )

        if construction_map is not None:
            _df = pl.from_dict(construction_map, strict=False)
            norm_df = _df.transpose(
                include_header=True, header_name="Name", column_names=_columns
            ).with_columns(pl.col("Layer").cast(pl.UInt32).fill_null(0))
        elif parquet_file is not None:
            if isinstance(parquet_file, pl.DataFrame):
                norm_df = parquet_file
            else:
                norm_df = pl.read_parquet(str(parquet_file))
        elif file is not None:
            norm_df = pl.read_parquet(file).with_columns(
                pl.col("Layer").cast(pl.UInt32).fill_null(0)
            )
        else:
            raise ValueError("Either parquet_file or file must be provided.")

        if not isinstance(norm_df, pl.DataFrame):
            raise TypeError("Normalized DataFrame expected at this point")

        # add a stable construction sequence index (1-based) to preserve
        # the original construction protocol ordering for downstream tools
        # (change from 0-origin to 1-origin as requested)
        if "Sequence" not in norm_df.columns:
            norm_df = norm_df.with_row_index("Sequence", offset=1)

        for _bcol in ("ShowObject", "ShowLabel", "Auxiliary"):
            if _bcol in norm_df.columns:
                norm_df = norm_df.with_columns(
                    cs.by_name(_bcol, require_all=False)
                    .replace_strict(
                        {"false": False, "true": True}, return_dtype=pl.Boolean
                    )
                    .fill_null(False)
                )

        return norm_df

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
                df.select(["Name", "Sequence", "Command"]).sort("Sequence").to_dicts()
            )
        except Exception:
            # Fallback for older polars versions
            rows = sorted(
                [
                    {k: r.get(k) for k in ("Name", "Sequence", "Command")}
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
            t = _transform_command(cmd)
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
                    df.select(["Name", "Sequence", "Command"])
                    .sort("Sequence")
                    .to_dicts()
                )
            except Exception:
                rows = sorted(
                    [
                        {k: r.get(k) for k in ("Name", "Sequence", "Command")}
                        for r in df.to_dicts()
                    ],
                    key=lambda x: x.get("Sequence") or 0,
                )

            out = []
            for r in rows:
                name = r.get("Name")
                cmd = r.get("Command")
                if name is None or not cmd:
                    continue
                out.append(f"{name} = {cmd}")
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

    @staticmethod
    def _ir_from_xml_file(xml_path: str) -> Dict[str, Any]:
        # If a legacy XML parser is required, implement here. The previous
        # comprehensive XML helper was intentionally removed to reduce
        # duplication; this method remains as a placeholder for projects
        # that wish to provide a focused XML->IR converter.
        raise NotImplementedError(
            "XML->IR conversion was removed; provide JSON IR or reintroduce a parser"
        )


# Backward/forward compatibility: prefer `ConstructionIO` as the canonical name
# but keep `DataFrameIO` for existing imports.
DataFrameIO = ConstructionIO
__all__ = ["ConstructionIO", "DataFrameIO"]
