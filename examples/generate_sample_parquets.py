import polars as pl
from pathlib import Path

OUT_DIR = Path('examples/poc_parquets')
OUT_DIR.mkdir(parents=True, exist_ok=True)

COLUMNS = ["Type","Command","Value","Caption","Layer","ShowObject","ShowLabel","Auxiliary"]

# create 5 synthetic constructions
for i in range(5):
    # simple variations
    if i == 0:
        rows = {
            'A': ['point','Point(A)', None, 'A', 0, True, True, False],
            'B': ['point','Point(B)', None, 'B', 0, True, True, False],
            'Seg': ['segment', 'Segment(A, B)', None, 'Seg', 0, True, True, False]
        }
    elif i == 1:
        rows = {
            'P': ['point','Point(P)', None, 'P', 0, True, True, False],
            'Q': ['point','Point(Q)', None, 'Q', 0, True, True, False],
            'Mid': ['point','Midpoint(P, Q)', None, 'Mid', 0, True, True, False]
        }
    elif i == 2:
        rows = {
            'X': ['point','Point(X)', None, 'X', 0, True, True, False],
            'Y': ['point','Point(Y)', None, 'Y', 0, True, True, False],
            'C': ['circle','Circle(X, Y)', None, 'C', 0, True, True, False]
        }
    elif i == 3:
        rows = {
            'U': ['point','Point(U)', None, 'U', 0, True, True, False],
            'V': ['point','Point(V)', None, 'V', 0, True, True, False],
            'Line': ['line','Line(U, V)', None, 'Line', 0, True, True, False]
        }
    else:
        rows = {
            'M': ['point','Point(M)', None, 'M', 0, True, True, False],
            'N': ['point','Point(N)', None, 'N', 0, True, True, False],
            'O': ['point','Point(O)', None, 'O', 0, True, True, False],
            'Seg2': ['segment','Segment(M, N)', None, 'Seg2', 0, True, True, False]
        }

    names = list(rows.keys())
    # build list of row dicts for Polars
    row_list = []
    for idx, name in enumerate(names):
        vals = rows[name]
        row = { 'Name': name }
        for j, col in enumerate(COLUMNS):
            row[col] = vals[j] if j < len(vals) else None
        row['Sequence'] = idx
        row_list.append(row)

    df = pl.DataFrame(row_list)
    out_path = OUT_DIR / f'ch1_sample_{i}.parquet'
    df.write_parquet(str(out_path))
    print('Wrote', out_path)

print('Done.')
