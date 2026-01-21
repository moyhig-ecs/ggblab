"""ggblab_extra.construction_io

Moved implementation of ConstructionIO into a separate optional package.

This file is a mostly verbatim copy of the original implementation with
imports adjusted for absolute package layout so it can live outside the
`ggblab` package tree.
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
    from ggblab.ggbapplet import GeoGebra


class ConstructionIO:
    """Helper class for building and persisting GeoGebra construction DataFrames.

    Provides canonical `COLUMNS` and `SHAPES` used across the project and
    staticmethods to initialize/write DataFrames from multiple sources.
    """

    COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
    SHAPES = ["point", "segment", "vector", "ray", "line", "circle", "conic", "polygon", "triangle", "quadrilateral"]

    @staticmethod
    async def _build_df_from_applet(ggb: 'GeoGebra', columns: Optional[Sequence[str]] = None) -> Mapping[str, Sequence]:
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
                import xml.etree.ElementTree as ET
                from itertools import chain

                try:
                    o2 = ggb.file.ggb_schema.decode(r2)
                except ET.ParseError:
                    vr = ET.fromstringlist(chain(['<construction>'], r, ['</construction>']))
                    o3 = ggb.file.ggb_schema.decode(ET.tostring(vr).decode('utf-8'))
                    o2 = o3.get('element', [{}])[0]
            except Exception:
                o2 = {}
            
            construction[o] = r + [o2.get('show', [{}])[0].get('@object'),
                                   o2.get('show', [{}])[0].get('@label'),
                                   o2.get('auxiliary', [{}])[0].get('@val')]

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
        if columns is None:
            columns = ConstructionIO.COLUMNS
        expressions, commands, elements = ConstructionIO._parse_construction_xml(xml_path)

        construction: Dict[str, Any] = {}
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
            norm_df = (_df
                .transpose(include_header=True, header_name="Name", column_names=_columns)
                .with_columns(pl.col("Layer").cast(pl.Int64).fill_null(0)))
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
        if file is not None:
            df.write_parquet(file)

    @staticmethod
    async def save_temp_ir_from_file(file_path: str, schema_path: str = 'docs/ir_schema.json', out_dir: Optional[str] = None) -> str:
        import json as _json
        if str(file_path).lower().endswith('.xml'):
            ir = ConstructionIO._ir_from_xml_file(file_path)
        else:
            try:
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

        td = out_dir or tempfile.gettempdir()
        fname = f'ggb_ir_{uuid.uuid4().hex}.json'
        out_path = Path(td) / fname
        out_path.write_text(_json.dumps(ir, ensure_ascii=False, indent=2), encoding='utf-8')

        try:
            from jsonschema import Draft7Validator
        except Exception as e:
            raise RuntimeError('jsonschema is required for validation') from e

        schema = _json.load(open(schema_path, 'r', encoding='utf-8'))
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(ir))
        if errors:
            msgs = []
            for e in errors[:50]:
                path = '/'.join([str(p) for p in e.path]) or '(root)'
                msgs.append(f'{path}: {e.message}')
            raise RuntimeError('IR validation failed:\n' + '\n'.join(msgs))

        return str(out_path)

    @staticmethod
    def _ir_from_xml_file(xml_path: str) -> Dict[str, Any]:
        expressions, commands, elements_raw = ConstructionIO._parse_construction_xml(xml_path)

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
        p = Path(xml_path)
        txt = p.read_text(encoding='utf-8')
        idx = txt.find('<construction')
        if idx > 0:
            txt = txt[idx:]
        end_tag = '</construction>'
        end_idx = txt.rfind(end_tag)
        if end_idx != -1:
            txt = txt[: end_idx + len(end_tag)]

        try:
            root = ET.fromstring(txt)

            expressions = {}
            commands = []
            elements_raw = []

            for child in list(root):
                tag = child.tag.lower()
                if tag == 'expression':
                    lbl = child.attrib.get('label')
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
            pass

        try:
            from ggblab.schema import ggb_schema
            import io as _io

            schema = ggb_schema().schema
            data = schema.to_dict(_io.StringIO(txt))
            o = data.get('construction') if isinstance(data, dict) and 'construction' in data else data

            def _ensure_list(v):
                if v is None:
                    return []
                if isinstance(v, list):
                    return v
                return [v]

            expressions = {}
            for ex in _ensure_list(o.get('expression')):
                lbl = ex.get('@label') or ex.get('label')
                exp_text = None
                if isinstance(ex, dict):
                    exp_text = ex.get('@exp') or ex.get('exp') or ex.get('#text')
                expressions[lbl] = exp_text

            commands = []
            for c in _ensure_list(o.get('command')):
                name = c.get('@name') or c.get('name')

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
                if raw is None:
                    try:
                        raw = f"{name}({', '.join(inputs)})"
                    except Exception:
                        raw = None

                commands.append({'name': name, 'inputs': inputs, 'outputs': outputs, 'raw': raw})

            elements_raw = []
            for e in _ensure_list(o.get('element')):
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
            try:
                raise _et_err
            except NameError:
                raise


# Backward/forward compatibility: prefer `ConstructionIO` as the canonical name
# but keep `DataFrameIO` for existing imports.
DataFrameIO = ConstructionIO
__all__ = ["ConstructionIO", "DataFrameIO"]
