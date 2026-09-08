"""Stage 1 acceptance — DataFrame parity of the data-in ConstructionIO (v2) against v1 (teacher's ruling 2026-09-08).

Inputs (all actual outputs, R4):
  A. v1 file path      : examples/2025_13_01.json in the ggblab-extra checkout = v1 `initialize_dataframe(ggb, file=…)` written 2026-01-20
  B. v1 applet path    : <capture>/df_applet.json + <capture>/applet.xml written by probes/stage1/stage1_capture_v1.ipynb in the v1 lab
  C. v2 data-in        : ConstructionIO.from_ggb_file(examples/2025_13_01.ggb) and from_xml(<capture>/applet.xml)
Comparisons (rows aligned by Name; Sequence and Value handled separately):
  C-file vs A          : both XML-derived → expected equal on the 8 columns (Value included)
  C-xml  vs C-file     : same construction via applet XML vs .ggb → expected equal
  C-xml  vs B          : XML path vs applet path → 7 columns expected equal; `Value` differs by design (getValueString discarded, ruling ii) → counted, not judged
Controls: positive = the Polygon errata path is exercised (Segment(…, poly1) reconstructed); negative = one label changed → mismatch.
usage: python probes/stage1_dataframe_parity.py [--capture DIR] [--out report.json]
"""
import argparse, json, sys
from pathlib import Path
import polars as pl
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ggblab_extra import ConstructionIO, read_ggb

GGB = ROOT / "examples/2025_13_01.ggb"
V1_FILE_JSON = Path("/Users/manabu/work/ggblab-extra/examples/2025_13_01.json")
COLS7 = ["Type", "Command", "Caption", "Layer", "ShowObject", "ShowLabel", "Auxiliary"]


def load_v1_json(p: Path) -> pl.DataFrame:
    rows = json.loads(p.read_text(encoding="utf-8"))
    df = pl.DataFrame(rows)
    if "Layer" in df.columns: df = df.with_columns(pl.col("Layer").cast(pl.UInt32).fill_null(0))
    for b in ("ShowObject", "ShowLabel", "Auxiliary"):
        if b in df.columns: df = df.with_columns(pl.col(b).cast(pl.Boolean).fill_null(False))
    return df


def diff(a: pl.DataFrame, b: pl.DataFrame, cols):
    """Row-aligned by Name. Returns {col: n_mismatch} plus names only in one side."""
    a = a.select(["Name"] + cols); b = b.select(["Name"] + [c for c in cols])
    j = a.join(b, on="Name", how="full", suffix="_b", coalesce=True)
    only_a = j.filter(pl.col(cols[0] + "_b").is_null() & pl.col(cols[0]).is_not_null()).height
    only_b = j.filter(pl.col(cols[0]).is_null() & pl.col(cols[0] + "_b").is_not_null()).height
    both = j.filter(pl.col(cols[0]).is_not_null() & pl.col(cols[0] + "_b").is_not_null())
    out = {}
    for c in cols:
        ne = both.filter(~(pl.col(c).eq_missing(pl.col(c + "_b"))))
        out[c] = {"mismatch": ne.height, "examples": ne.select(["Name", c, c + "_b"]).head(3).rows()}
    return {"rows_a": a.height, "rows_b": b.height, "common": both.height, "only_a": only_a, "only_b": only_b, "columns": out}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--capture", default=None); ap.add_argument("--out", default=str(ROOT / "probes/stage1_dataframe_parity_report.json"))
    a = ap.parse_args(); R = {"ggb": str(GGB)}
    c_file = ConstructionIO.from_ggb_file(GGB); R["v2_file_rows"] = c_file.height
    # positive control: errata path
    seg = c_file.filter(pl.col("Name") == "f")["Command"].item(); R["positive_control"] = {"Segment_from_Polygon_edge": seg, "ok": seg == "Segment(C, A, poly1)"}
    # negative control
    bad = ConstructionIO.from_xml(read_ggb(GGB).replace('label="poly1"', 'label="polyX"', 1))
    R["negative_control"] = {"mismatch_detected": diff(c_file, bad, COLS7)["only_a"] == 1}
    if V1_FILE_JSON.exists():
        v1f = load_v1_json(V1_FILE_JSON); R["v1_file_json"] = str(V1_FILE_JSON)
        R["C_file_vs_A"] = diff(c_file, v1f, COLS7 + ["Value"])
    if a.capture:
        cap = Path(a.capture)
        xml = (cap / "applet.xml").read_text(encoding="utf-8"); c_xml = ConstructionIO.from_xml(xml)
        R["C_xml_vs_C_file"] = diff(c_xml, c_file, COLS7 + ["Value"])
        if (cap / "df_applet.json").exists():
            v1a = load_v1_json(cap / "df_applet.json"); R["v1_applet_rows"] = v1a.height
            d = diff(c_xml, v1a, COLS7 + ["Value"]); R["C_xml_vs_B"] = d
            R["C_xml_vs_B"]["value_note"] = "Value differs by design (v1 applet path = getValueString; v2 = XML expression/IR; ruling 2026-09-08 ii)"
    Path(a.out).write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    def summ(k):
        d = R.get(k); 
        if not d: return f"{k}: (no input)"
        mm = {c: v["mismatch"] for c, v in d["columns"].items()}
        return f"{k}: rows {d['rows_a']}/{d['rows_b']} common {d['common']} only_a {d['only_a']} only_b {d['only_b']} mismatch {mm}"
    print("⭕ positive control", R["positive_control"]["ok"], "| negative control", R["negative_control"]["mismatch_detected"])
    for k in ("C_file_vs_A", "C_xml_vs_C_file", "C_xml_vs_B"): print(" ", summ(k))
    print("  report", a.out)


if __name__ == "__main__":
    main()
