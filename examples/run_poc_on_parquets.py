import polars as pl
from ggblab_extra.construction_parser import ConstructionTreeParser
from ggblab_extra.construction_parser import build_graph_from_df
import networkx as nx
import logging
from run_poc_ged import hungarian_similarity, build_graph_from_tuples
from pathlib import Path

P = Path('examples/poc_parquets')
files = sorted(P.glob('ch1_sample_*.parquet'))
if not files:
    print('No parquet files found in', P)
    raise SystemExit(1)

# Use first as reference
ref_path = files[0]
print('Reference:', ref_path)
ref_df = pl.read_parquet(str(ref_path))
parser_ref = ConstructionTreeParser(df=ref_df)
try:
    G_ref = parser_ref.parse()
except Exception as e:
    print('Parser.parse failed for reference; falling back to build_graph_from_df:', e)
    # fallback: build graph from DependsOn column if present
    G_ref = build_graph_from_df(ref_df)
print('Reference graph nodes:', len(G_ref.nodes), 'edges:', len(G_ref.edges))
# write per-sample anomaly report for reference
try:
    parser_ref._validate_ft(out_path=f'examples/ft_anomalies_{ref_path.stem}.json')
except Exception:
    logging.getLogger(__name__).exception("_validate_ft failed for reference")

for f in files[1:]:
    print('\nComparing to', f)
    df = pl.read_parquet(str(f))
    parser = ConstructionTreeParser(df=df)
    try:
        G_sub = parser.parse()
    except Exception as e:
        print('Parser.parse failed for sample; falling back to build_graph_from_df:', e)
        G_sub = build_graph_from_df(df)
    print('Sub graph nodes:', len(G_sub.nodes), 'edges:', len(G_sub.edges))
    # write per-sample anomaly report
    try:
        parser._validate_ft(out_path=f'examples/ft_anomalies_{f.stem}.json')
    except Exception:
        logging.getLogger(__name__).exception("_validate_ft failed for sample %s", f)
    sim, rpt = hungarian_similarity(G_ref, G_sub)
    print('Similarity:', sim)
    print('Report:')
    print(' matched_pairs:', rpt.get('matched_pairs'))
    print(' unmatched_ref:', rpt.get('unmatched_ref'))
    print(' unmatched_sub:', rpt.get('unmatched_sub'))
