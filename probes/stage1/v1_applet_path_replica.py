"""Rebuild the v1 *applet-path* DataFrame from an applet-API capture (stage 1 acceptance, reference side).

v1 `ConstructionIO._build_df_from_applet` asked the applet, per object, for
    [getObjectType, getCommandString, getValueString, getCaption, getLayer]  and  getXML(label)
and then decoded the per-object XML for show/auxiliary.  v1's own Comm did not come up in the v1 lab today (the race of
2026-09-07 again: 274 s, version None), so the SAME API calls were issued to the v2 applet through Playwright
(`window.ggbApplet`) and saved as JSON; this script applies v1's post-processing verbatim (copied from v1 1.8.1
`ggblab_extra/construction_io.py` L149–L196 and `initialize_dataframe`) to that capture.
usage: python v1_applet_path_replica.py <capture.json> <out_dir>   → out_dir/df_applet.json, out_dir/applet.xml
"""
import json, sys, re
import xml.etree.ElementTree as ET
from itertools import chain
from pathlib import Path
import polars as pl
import polars.selectors as cs
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ggblab.schema import get_schema

COLUMNS = ["Type", "Command", "Value", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]
FUNCTION_FIELDS = ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"]


def _normalize_exponent(xml):
    return re.sub(r'(?<=\d)e(?=[+-]?\d+)', 'E', xml) if isinstance(xml, str) else xml


def main(capture, out_dir):
    cap = json.loads(Path(capture).read_text(encoding="utf-8"))
    assert cap["fields"] == FUNCTION_FIELDS
    schema = get_schema()
    construction = {}
    for row in cap["rows"]:                                   # ---- v1 L149–L196, comm calls replaced by the capture
        o, r, r2 = row["name"], row["fields"], row["xml"]
        if isinstance(r2, str):
            r2 = _normalize_exponent(r2)
        try:
            o2 = schema.decode(r2)
        except Exception:
            try:
                vr = ET.fromstringlist(chain(["<construction>"], r2, ["</construction>"]))
                xml_vr = _normalize_exponent(ET.tostring(vr).decode("utf-8"))
                o3 = schema.decode(xml_vr)
                o2 = o3.get("element", [{}])[0]
            except Exception:
                o2 = {}
        if isinstance(r, (list, tuple)):
            r_list = list(r)
        elif r is None:
            r_list = [None] * len(FUNCTION_FIELDS)
        else:
            r_list = [r]
        construction[o] = r_list + [
            o2.get("show", [{}])[0].get("@object"),
            o2.get("show", [{}])[0].get("@label"),
            o2.get("auxiliary", [{}])[0].get("@val"),
        ]
    # ---- v1 initialize_dataframe normalisation
    _df = pl.from_dict(construction, strict=False)
    norm_df = _df.transpose(include_header=True, header_name="Name", column_names=COLUMNS).with_columns(
        pl.col("Layer").cast(pl.UInt32).fill_null(0))
    norm_df = norm_df.with_row_index("Sequence", offset=1)
    for _bcol in ("ShowObject", "ShowLabel", "Auxiliary"):
        norm_df = norm_df.with_columns(
            cs.by_name(_bcol, require_all=False).replace_strict({"false": False, "true": True}, return_dtype=pl.Boolean).fill_null(False))
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    norm_df.write_json(str(out / "df_applet.json"))
    (out / "applet.xml").write_text(cap["full_xml"], encoding="utf-8")
    print("applet-path replica:", norm_df.shape, "| applet", cap.get("version"), "| wrote df_applet.json, applet.xml")
    print(norm_df.head(5))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
