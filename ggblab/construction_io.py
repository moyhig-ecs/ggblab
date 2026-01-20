"""ggblab.construction_io

Construction I/O helpers (canonical `ConstructionIO`).

This module provides `ConstructionIO` (preferred) and a backward-compatible
`DataFrameIO` alias. Typical usage (from `examples/eg6_construction.ipynb`):

        from ggblab import GeoGebra
        from ggblab.construction_io import ConstructionIO

        ggb = GeoGebra()
        await ggb.init()

        # Load from a .ggb file (requires a GeoGebra runner instance)
        df_from_file = await ConstructionIO.initialize_dataframe(
            ggb, file='example.ggb',
            _columns=ConstructionIO.COLUMNS + ["ShowObject", "ShowLabel", "Auxiliary"]
        )

        # Or build from a running applet
        df_from_applet = await ConstructionIO.initialize_dataframe(ggb, use_applet=True)

Utilities:
    - `ConstructionIO.COLUMNS`: canonical column list
    - `ConstructionIO.initialize_dataframe(...)`: build a Polars DataFrame
    - `ConstructionIO.save_temp_ir_from_file(...)`: emit IR JSON and validate

Notes:
    - `ConstructionIO` is the preferred public API; `DataFrameIO` remains as
        a compatibility alias exported by the module.
"""

import polars as pl
import polars.selectors as cs
from typing import Optional, Mapping, Sequence, Dict, Any, Union, TYPE_CHECKING
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
import uuid
if TYPE_CHECKING:
    from .ggbapplet import GeoGebra


class ConstructionIO:
    """Helper class for building and persisting GeoGebra construction DataFrames.

    Provides canonical `COLUMNS` and `SHAPES` used across the project and
    staticmethods to initialize/write DataFrames from multiple sources.
    """

    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer"]
    # COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral"]

    # mapping-to-DataFrame helper inlined at call sites (kept removed for clarity)

    @staticmethod
    async def _build_df_from_applet(ggb: 'GeoGebra', columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
        """Async constructor: given a GeoGebra `ggb` runner, query the applet
        API to build and return the construction mapping (object -> attributes).
        """
        if columns is None:
            columns = ConstructionIO.COLUMNS

        if ggb is None:
            raise ValueError("ggb runner is required for async construction building; ggb must not be None")

        construction: Dict[str, Any] = {}
        objs = await ggb.function("getAllObjectNames")
        for o in objs:
            r = await ggb.function(["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"], [o])
            # print(r)
            construction[o] = r

        return construction

    @staticmethod
    def _build_df_from_ggb_file(ggb: 'GeoGebra', ggb_path: str, columns=None) -> Mapping[str, Sequence]:
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

                    cmd = (f"{_c.get('@name')}({', '.join(_ci)})"
                           .replace('OrthogonalLine', 'PerpendicularLine')
                           .translate(str.maketrans('[]', '()')))
                    break

            for _e in o.get('expression', []):
                if _n == _e.get('@label'):
                    exp = _e.get('@exp')

            # COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
            construction[_n] = [e.get('@type'), cmd or exp, exp or None, 
                                e.get('caption', [{}])[0].get('@val'),
                                e.get('layer', [{}])[0].get('@val'),
                                e.get('show', [{}])[0].get('@object'),
                                e.get('show', [{}])[0].get('@label'),
                                e.get('auxiliary', [{}])[0].get('@val'),
                        ]

        return construction

    @staticmethod
    def _build_df_from_xml_file(xml_path: str, columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
        """Parse a GeoGebra construction XML file and return a construction mapping.

        Mapping format: { name: [Type, Command|Value, Value, Caption, Layer] }
        """
        if columns is None:
            columns = ConstructionIO.COLUMNS
        # Reuse shared XML parsing logic
        expressions, commands, elements = ConstructionIO._parse_construction_xml(xml_path)

        # map outputs from commands to element command info
        construction: Dict[str, Any] = {}
        # build lookup for outputs
        out_map = {}
        for c in commands:
            for o in c.get('outputs', []):
                out_map.setdefault(o, []).append(c)

        for e in elements:
            name = e.get('name')
            typ = e.get('type')
            layer = e.get('layer')
            caption = e.get('caption')
            val = expressions.get(name)
            cmd = None
            # if a command produced this element, take its representative raw form
            cs = out_map.get(name)
            if cs:
                c0 = cs[0]
                cmd = f"{c0.get('name')}({', '.join(c0.get('inputs', []))})"

            construction[name] = [typ, cmd or val, val or None, caption, layer]

        return construction

    @staticmethod
    async def initialize_dataframe(ggb: 'GeoGebra', parquet_file: Optional[Union[str, pl.DataFrame]] = None, file: Optional[str] = None, *, _columns=None, use_applet: bool = False) -> pl.DataFrame:
        if _columns is None:
            _columns = ConstructionIO.COLUMNS
        # build construction_map only from .ggb files (applet or file); we no longer accept
        # an external `construction` argument — callers should call the builders themselves.
        construction_map: Optional[Mapping[str, Sequence]] = None

        if ggb is not None:
            if use_applet:
                construction_map = await ConstructionIO._build_df_from_applet(ggb, columns=_columns)
            if file is not None and str(file).lower().endswith('.ggb'):
                construction_map = ConstructionIO._build_df_from_ggb_file(ggb, str(file), columns=_columns)

        # if no ggb runner available but an XML file is provided, try XML loader
        if construction_map is None and file is not None and str(file).lower().endswith('.xml'):
            construction_map = ConstructionIO._build_df_from_xml_file(str(file), columns=_columns)

        # now create/normalize the DataFrame from whichever source we have
        if construction_map is not None:
            # print(construction_map)
            _df = pl.from_dict(construction_map, strict=False)
            norm_df = (_df
                .transpose(include_header=True, header_name="Name", column_names=_columns)
                .with_columns(pl.col("Layer").cast(pl.Int64).fill_null(0)))
        elif parquet_file is not None:
            # `parquet_file` is expected to be a path to a parquet file written by `write_parquet`.
            # Load and return it without additional normalization.
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

        # Coerce boolean-like string columns consistently across sources
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
        if file is not None:
            df.write_parquet(file)

    @staticmethod
    async def save_temp_ir_from_file(file_path: str, schema_path: str = 'docs/ir_schema.json', out_dir: Optional[str] = None) -> str:
        """Generate an IR JSON from `file_path`, validate against `schema_path`, and save to a temp file.

        This is async so callers running inside an event loop (e.g., Jupyter)
        can `await` it; command-line scripts may call it via `asyncio.run()`.

        Returns the path to the written IR JSON file. Raises RuntimeError on validation failure.
        """
        import json as _json
        # if input is XML, build a richer IR directly from XML (coords, structured commands)
        if str(file_path).lower().endswith('.xml'):
            ir = ConstructionIO._ir_from_xml_file(file_path)
        else:
            try:
                # build dataframe asynchronously using the static initialize API
                df = await ConstructionIO.initialize_dataframe(None, file=file_path)
            except Exception:
                raise

            rows = df.to_dicts()

            elements = []
            for i, r in enumerate(rows):
                elem = {
                    'id': i,
                    'name': r.get('Name'),
                    'type': r.get('Type'),
                    'coords': None,
                    'command': None,
                    'command_raw': r.get('Command'),
                    'value': r.get('Value'),
                    'caption': r.get('Caption'),
                    'layer': int(r.get('Layer')) if r.get('Layer') is not None else None,
                    'show_object': r.get('ShowObject') if 'ShowObject' in r else None,
                    'show_label': r.get('ShowLabel') if 'ShowLabel' in r else None,
                    'auxiliary': r.get('Auxiliary') if 'Auxiliary' in r else None,
                    'metadata': {}
                }
                elements.append(elem)

            ir = {'schema_version': 1, 'elements': elements, 'commands': []}

        # prepare output path
        td = out_dir or tempfile.gettempdir()
        fname = f'ggb_ir_{uuid.uuid4().hex}.json'
        out_path = Path(td) / fname
        out_path.write_text(_json.dumps(ir, ensure_ascii=False, indent=2), encoding='utf-8')

        # validate
        try:
            from jsonschema import Draft7Validator
        except Exception as e:
            raise RuntimeError('jsonschema is required for validation') from e

        schema = _json.load(open(schema_path, 'r', encoding='utf-8'))
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(ir))
        if errors:
            # write a human readable error summary
            msgs = []
            for e in errors[:50]:
                path = '/'.join([str(p) for p in e.path]) or '(root)'
                msgs.append(f'{path}: {e.message}')
            raise RuntimeError('IR validation failed:\n' + '\n'.join(msgs))

        return str(out_path)

    @staticmethod
    def _ir_from_xml_file(xml_path: str) -> Dict[str, Any]:
        """Produce a rich IR dict from a GeoGebra XML file (elements + commands).

        This returns the same top-level shape as `{'schema_version':1,'elements':..., 'commands':...}`
        with `coords`, structured `command` objects, `command_raw`, and other metadata filled when available.
        """
        # Reuse shared XML parsing logic
        expressions, commands, elements_raw = ConstructionIO._parse_construction_xml(xml_path)

        # build quick lookup for commands producing outputs
        out_map = {}
        for c in commands:
            for o in c.get('outputs', []):
                out_map.setdefault(o, []).append(c)

        elements = []
        for i, e in enumerate(elements_raw):
            name = e.get('name')
            typ = e.get('type')
            cmd_obj = None
            cmd_raw = None
            cs = out_map.get(name)
            if cs:
                c0 = cs[0]
                cmd_obj = {'name': c0.get('name'), 'inputs': c0.get('inputs', []), 'outputs': c0.get('outputs', []), 'raw': c0.get('raw')}
                cmd_raw = c0.get('raw')

            elem = {
                'id': i,
                'name': name,
                'type': typ,
                'coords': e.get('coords'),
                'command': cmd_obj,
                'command_raw': cmd_raw,
                'value': expressions.get(name),
                'caption': e.get('caption'),
                'layer': e.get('layer'),
                'show_object': True if e.get('show_object') in (None, 'true', 'True') else False if e.get('show_object') in ('false', 'False') else None,
                'show_label': True if e.get('show_label') in (None, 'true', 'True') else False if e.get('show_label') in ('false', 'False') else None,
                'auxiliary': True if e.get('auxiliary') in (None, 'true', 'True') else False if e.get('auxiliary') in ('false', 'False') else None,
                'metadata': {}
            }
            elements.append(elem)

        ir = {'schema_version': 1, 'elements': elements, 'commands': commands}
        return ir

    @staticmethod
    def _parse_construction_xml(xml_path: str):
        """Shared helper: parse a GeoGebra construction XML file and return
        (expressions, commands, elements_raw) used by callers.

        Prefer using the project's XML Schema (`ggb_schema`) via `xmlschema` to
        convert XML → dict. If schema-based decoding fails for any reason, fall
        back to a robust ElementTree-based parser (legacy behavior).

        Returns:
            expressions (dict): mapping label -> expression text
            commands (list[dict]): list of {'name','inputs','outputs','raw'}
            elements_raw (list[dict]): list of element dicts with keys
                'name','type','coords','layer','show_object','show_label','auxiliary','caption'
        """
        p = Path(xml_path)
        txt = p.read_text(encoding='utf-8')
        idx = txt.find('<construction')
        if idx > 0:
            txt = txt[idx:]
        end_tag = '</construction>'
        end_idx = txt.rfind(end_tag)
        if end_idx != -1:
            txt = txt[: end_idx + len(end_tag)]

        # First attempt: Legacy ElementTree-based parsing (preferred/faster)
        try:
            root = ET.fromstring(txt)

            expressions = {}
            commands = []
            elements_raw = []

            for child in list(root):
                tag = child.tag.lower()
                if tag == 'expression':
                    lbl = child.attrib.get('label')
                    # Prefer the `exp` attribute (common in GeoGebra XML),
                    # then a nested <exp> element, then element text.
                    exp_text = child.attrib.get('exp')
                    if exp_text is None:
                        for sub in child:
                            if sub.tag.lower().endswith('exp'):
                                exp_text = sub.text
                                break
                    if exp_text is None:
                        exp_text = child.text
                    expressions[lbl] = exp_text
                elif tag == 'command':
                    name = child.attrib.get('name')
                    inp = []
                    out = []
                    raw = None
                    for sub in child:
                        st = sub.tag.lower()
                        if st == 'input':
                            # inputs may be listed as attributes like a0="A" a1="B"
                            try:
                                items = sorted(sub.attrib.items(), key=lambda x: x[0])
                                inp = [v for k, v in items]
                            except Exception:
                                pass
                        elif st == 'output':
                            try:
                                items = sorted(sub.attrib.items(), key=lambda x: x[0])
                                out = [v for k, v in items]
                            except Exception:
                                pass
                        elif st == 'raw':
                            raw = sub.text
                    # derive raw if missing
                    if raw is None:
                        try:
                            raw = f"{name}({', '.join(inp)})"
                        except Exception:
                            raw = None
                    commands.append({'name': name, 'inputs': inp, 'outputs': out, 'raw': raw})
                elif tag == 'element':
                    lbl = child.attrib.get('label')
                    typ = child.attrib.get('type')
                    coords = None
                    layer = None
                    caption = None
                    show_object = None
                    show_label = None
                    auxiliary = None
                    for sub in child:
                        st = sub.tag.lower()
                        if st == 'coords':
                            try:
                                coords = {k: float(sub.attrib.get(k)) for k in ('x', 'y', 'z') if k in sub.attrib}
                            except Exception:
                                coords = None
                        elif st == 'layer':
                            layer = sub.attrib.get('val') or sub.attrib.get('value')
                            try:
                                layer = int(layer)
                            except Exception:
                                pass
                        elif st == 'show':
                            show_object = sub.attrib.get('object')
                            show_label = sub.attrib.get('label')
                        elif st == 'auxiliary':
                            auxiliary = sub.attrib.get('val')
                        elif st == 'caption':
                            caption = sub.attrib.get('val')

                    elements_raw.append({'name': lbl, 'type': typ, 'coords': coords, 'layer': layer,
                                         'show_object': show_object, 'show_label': show_label,
                                         'auxiliary': auxiliary, 'caption': caption})

            return expressions, commands, elements_raw

        except Exception as _et_err:
            # If legacy parsing fails, try schema-driven conversion as a fallback
            pass

        # Second attempt: schema-driven conversion via ggb_schema
        try:
            from .schema import ggb_schema
            import io as _io

            schema = ggb_schema().schema
            # xmlschema accepts file-like objects
            data = schema.to_dict(_io.StringIO(txt))
            # normalize to the construction object if present
            o = data.get('construction') if isinstance(data, dict) and 'construction' in data else data

            # helper to coerce singletons to lists
            def _ensure_list(v):
                if v is None:
                    return []
                if isinstance(v, list):
                    return v
                return [v]

            expressions = {}
            for ex in _ensure_list(o.get('expression')):
                lbl = ex.get('@label') or ex.get('label')
                # expression text may appear under 'exp' or as text
                exp_text = None
                if isinstance(ex, dict):
                    exp_text = ex.get('@exp') or ex.get('exp') or ex.get('#text')
                expressions[lbl] = exp_text

            commands = []
            for c in _ensure_list(o.get('command')):
                name = c.get('@name') or c.get('name')

                # inputs/outputs can be represented as dicts of a0/a1 attrs or lists
                inputs = []
                inp_raw = c.get('input') or c.get('@input')
                if isinstance(inp_raw, dict):
                    try:
                        items = sorted(inp_raw.items(), key=lambda x: x[0])
                        inputs = [v for k, v in items]
                    except Exception:
                        inputs = []
                elif isinstance(inp_raw, list):
                    for it in inp_raw:
                        if isinstance(it, dict):
                            v = it.get('@val') or it.get('value') or next(iter(it.values()), None)
                            if v is not None:
                                inputs.append(v)
                        else:
                            inputs.append(it)

                outputs = []
                out_raw = c.get('output') or c.get('@output')
                if isinstance(out_raw, dict):
                    try:
                        items = sorted(out_raw.items(), key=lambda x: x[0])
                        outputs = [v for k, v in items]
                    except Exception:
                        outputs = []
                elif isinstance(out_raw, list):
                    for it in out_raw:
                        if isinstance(it, dict):
                            v = it.get('@val') or it.get('value') or next(iter(it.values()), None)
                            if v is not None:
                                outputs.append(v)
                        else:
                            outputs.append(it)

                raw = c.get('raw') or c.get('@raw') or None
                # derive raw if missing
                if raw is None:
                    try:
                        raw = f"{name}({', '.join(inputs)})"
                    except Exception:
                        raw = None

                commands.append({'name': name, 'inputs': inputs, 'outputs': outputs, 'raw': raw})

            elements_raw = []
            for e in _ensure_list(o.get('element')):
                # attributes may be under '@label'/'@type' or 'label'/'type'
                name = e.get('@label') or e.get('label') or e.get('name')
                typ = e.get('@type') or e.get('type')

                coords = None
                coords_raw = e.get('coords')
                if isinstance(coords_raw, dict):
                    try:
                        coords = {k: float(coords_raw.get(k)) for k in ('x', 'y', 'z') if coords_raw.get(k) is not None}
                    except Exception:
                        coords = None

                layer = None
                layer_raw = e.get('layer')
                if isinstance(layer_raw, dict):
                    layer = layer_raw.get('@val') or layer_raw.get('val') or layer_raw.get('value')
                else:
                    layer = layer_raw
                try:
                    if layer is not None:
                        layer = int(layer)
                except Exception:
                    pass

                caption = None
                cap_raw = e.get('caption')
                if isinstance(cap_raw, dict):
                    caption = cap_raw.get('@val') or cap_raw.get('val') or cap_raw.get('value')
                else:
                    caption = cap_raw

                show_object = None
                show_label = None
                show_raw = e.get('show')
                if isinstance(show_raw, dict):
                    show_object = show_raw.get('@object') or show_raw.get('object')
                    show_label = show_raw.get('@label') or show_raw.get('label')

                auxiliary = None
                aux_raw = e.get('auxiliary')
                if isinstance(aux_raw, dict):
                    auxiliary = aux_raw.get('@val') or aux_raw.get('val')

                elements_raw.append({'name': name, 'type': typ, 'coords': coords, 'layer': layer,
                                     'show_object': show_object, 'show_label': show_label,
                                     'auxiliary': auxiliary, 'caption': caption})

            return expressions, commands, elements_raw

        except Exception:
            # Both parsers failed; re-raise the original ET error if available
            try:
                raise _et_err
            except NameError:
                raise


    # Backward/forward compatibility: prefer `ConstructionIO` as the canonical name
    # but keep `DataFrameIO` for existing imports.
DataFrameIO = ConstructionIO
__all__ = ["ConstructionIO", "DataFrameIO"]
