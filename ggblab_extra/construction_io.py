"""ggblab_extra.construction_io.

Moved implementation of ConstructionIO into a separate optional package.

This file is a mostly verbatim copy of the original implementation with
imports adjusted for absolute package layout so it can live outside the
`ggblab` package tree.
"""

from __future__ import annotations

import json
import polars as pl
import polars.selectors as cs
from typing import Optional, Mapping, Sequence, Dict, Any, Union, TYPE_CHECKING
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
import uuid

if TYPE_CHECKING:
	from ggblab.ggbapplet import GeoGebra


class ConstructionIO:
	"""Helper class for building and persisting GeoGebra construction DataFrames.

	This module provides helpers for building a Polars DataFrame from a
	GeoGebra applet, saving the resulting DataFrame to disk and other
	convenience functions. Historically this module included a complex XML
	parser helper called ``_parse_construction_xml``; that helper has been
	removed because the preferred IR representation is now the JSON-like IR
	stored in DataFrame ``Value`` fields. The rest of the helpers remain.
	"""

	COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
	SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral"]

	@staticmethod
	async def _build_df_from_applet(ggb: "GeoGebra", columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
		if columns is None:
			columns = ConstructionIO.COLUMNS

		if ggb is None:
			raise ValueError("ggb runner is required for async construction building; ggb must not be None")

		construction: Dict[str, Any] = {}
		objs = await ggb.function("getAllObjectNames")
		for o in objs:
			r = await ggb.function(["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"], [o])
			r2 = await ggb.function("getXML", [o])
			try:
				o2 = ggb.file.ggb_schema.decode(r2)
			except Exception:
				try:
					from itertools import chain

					vr = ET.fromstringlist(chain(['<construction>'], r, ['</construction>']))
					o3 = ggb.file.ggb_schema.decode(ET.tostring(vr).decode('utf-8'))
					o2 = o3.get('element', [{}])[0]
				except Exception:
					o2 = {}

			construction[o] = r + [
				o2.get('show', [{}])[0].get('@object'),
				o2.get('show', [{}])[0].get('@label'),
				o2.get('auxiliary', [{}])[0].get('@val'),
			]

		return construction

	@staticmethod
	def _build_df_from_ggb_file(ggb: "GeoGebra", ggb_path: str, columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
		if ggb is None:
			raise ValueError("ggb runner is required for .ggb loading; ggb must not be None")
		if not ggb_path:
			raise ValueError("ggb_path must be provided when using ggb runner")

		c = ggb.file.load(ggb_path)
		o = c.ggb_schema.decode(c.geogebra_xml)

		construction: Dict[str, Any] = {}
		for e in o.get('element', []):
			_n = e.get('@label')
			cmd = None
			exp = None

			for _c in o.get('command', []):
				try:
					_ci = tuple(zip(*_c['input'].items()))[1]
				except Exception:
					_ci = tuple()
				try:
					_co = tuple(zip(*_c['output'].items()))[1]
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
					if _c.get('@name') == 'Polygon':
						try:
							match _ci:
								case (p0, p1, '4'):
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

					cmd = (
						f"{_c.get('@name')}({', '.join(_ci)})"
						.replace('OrthogonalLine', 'PerpendicularLine')
						.translate(str.maketrans('[]', '()'))
					)
					break

			for _e in o.get('expression', []):
				if _n == _e.get('@label'):
					exp = _e.get('@exp')

			construction[_n] = [
				e.get('@type'),
				cmd or exp,
				exp or None,
				e.get('caption', [{}])[0].get('@val'),
				e.get('layer', [{}])[0].get('@val'),
				e.get('show', [{}])[0].get('@object'),
				e.get('show', [{}])[0].get('@label'),
				e.get('auxiliary', [{}])[0].get('@val'),
			]

		return construction

	@staticmethod
	def _build_df_from_xml_file(xml_path: str, columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
		if columns is None:
			columns = ConstructionIO.COLUMNS
		raise NotImplementedError("_build_df_from_xml_file requires an XML parser which was removed")

	@staticmethod
	async def initialize_dataframe(ggb: Optional["GeoGebra"], parquet_file: Optional[Union[str, pl.DataFrame]] = None, file: Optional[str] = None, *, _columns=None, use_applet: bool = False) -> pl.DataFrame:
		"""Initialize and normalize a Polars DataFrame from applet/parquet/file.

		Returns a normalized `pl.DataFrame` ready for downstream parsing.
		"""
		if _columns is None:
			_columns = ConstructionIO.COLUMNS
		construction_map: Optional[Mapping[str, Sequence]] = None

		if ggb is not None:
			if use_applet:
				construction_map = await ConstructionIO._build_df_from_applet(ggb, columns=_columns)
			if file is not None and str(file).lower().endswith('.ggb'):
				construction_map = ConstructionIO._build_df_from_ggb_file(ggb, str(file), columns=_columns)

		if construction_map is None and file is not None and str(file).lower().endswith('.xml'):
			construction_map = ConstructionIO._build_df_from_xml_file(str(file), columns=_columns)

		if construction_map is not None:
			_df = pl.from_dict(construction_map, strict=False)
			norm_df = (
				_df.transpose(include_header=True, header_name="Name", column_names=_columns)
				.with_columns(pl.col("Layer").cast(pl.Int64).fill_null(0))
			)
		elif parquet_file is not None:
			if isinstance(parquet_file, pl.DataFrame):
				norm_df = parquet_file
			else:
				norm_df = pl.read_parquet(str(parquet_file))
		elif file is not None:
			norm_df = pl.read_parquet(file).with_columns(pl.col("Layer").cast(pl.Int64).fill_null(0))
		else:
			raise ValueError("Either parquet_file or file must be provided.")

		if not isinstance(norm_df, pl.DataFrame):
			raise TypeError("Normalized DataFrame expected at this point")

		for _bcol in ("ShowObject", "ShowLabel", "Auxiliary"):
			if _bcol in norm_df.columns:
				norm_df = norm_df.with_columns(
					cs.by_name(_bcol, require_all=False).replace_strict(
						{"false": False, "true": True},
						return_dtype=pl.Boolean
					).fill_null(False)
				)

		return norm_df

	@staticmethod
	def write_parquet(df: pl.DataFrame, file: Optional[str] = None) -> None:
		"""Write the provided DataFrame to a Parquet file if `file` is given."""
		if file is not None:
			df.write_parquet(file)

	@staticmethod
	def save_dataframe(df: pl.DataFrame, ggb=None, fmt: str = 'parquet', out_dir: Optional[str] = None, overwrite: bool = False) -> str:
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
		if fmt not in ('parquet', 'json'):
			raise ValueError("fmt must be 'parquet' or 'json'")

		if ggb is not None and hasattr(ggb, 'source_file') and ggb.source_file:
			base = Path(ggb.source_file).stem
		else:
			base = 'construction'

		out_dir = Path(out_dir) if out_dir is not None else Path('.')
		out_dir.mkdir(parents=True, exist_ok=True)

		ext = '.parquet' if fmt == 'parquet' else '.json'
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

		if fmt == 'parquet':
			df.write_parquet(str(target))
		else:
			# json: use Polars native writer when available
			try:
				df.write_json(str(target))
			except Exception:
				# fallback to explicit serialization
				rows = df.to_dicts()
				with open(target, 'w', encoding='utf-8') as f:
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
		raise NotImplementedError("XML->IR conversion was removed; provide JSON IR or reintroduce a parser")


# Backward/forward compatibility: prefer `ConstructionIO` as the canonical name
# but keep `DataFrameIO` for existing imports.
DataFrameIO = ConstructionIO
__all__ = ["ConstructionIO", "DataFrameIO"]
