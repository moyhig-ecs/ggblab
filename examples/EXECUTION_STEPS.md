簡潔メモ — 実行手順と生成物

目的

- PoC のパーサ堅牢化、SCC 集約導入、FT 異常検出レポート作成、サンプル Parquet に対する類似度比較

主要変更点

- `ggblab_extra/construction_parser.py`
  - 追加: `_validate_ft(out_path=None)` — self-ref / unknown-ref / cycles を検出してログ出力、JSON 保存
  - `parse()` から `_validate_ft(out_path=...)` を呼び出すよう変更（出力先はインスタンス属性または env で制御可能、**デフォルトでは出力しません**。出力するには `GGBLAB_FT_REPORT_DIR` 環境変数を設定するか、パーサーインスタンスの `ft_report_dir` を指定してください）
- `examples/run_poc_ged.py`
  - 追加: `collapse_scc()` — 強連結成分をスーパー・ノードに集約
  - `hungarian_similarity(..., collapse_cycles=True)` — SCC 集約オプションとレポートを追加
- `examples/run_poc_on_parquets.py`
  - 各サンプル実行時に `parser._validate_ft(out_path=...)` を呼び、サンプル毎の JSON レポートを生成（出力はデフォルト無効。環境変数またはインスタンス属性で有効化してください）

実行コマンド（リポジトリルート）

```bash
python examples/run_poc_ged.py
python examples/run_poc_on_parquets.py
```

生成ファイル（examples/ 相対）

- `ft_anomalies_<digest>.json`（`ft` の内容に対して決定論的に生成されるが、**デフォルトでは生成しません**。生成するには `GGBLAB_FT_REPORT_DIR` を設定するか、パーサーの `ft_report_dir` を指定してください）
- `ft_anomalies_ch1_sample_0.json` ... `ft_anomalies_ch1_sample_4.json`（各サンプルごとのレポート。出力はデフォルト無効）
- PoC ノートブック: `poc_ged_grader.ipynb` と実行済み `poc_ged_grader_executed.ipynb`
- サンプル Parquet: `poc_parquets/ch1_sample_0..4.parquet`

観察と次案

- 多くのサンプルで単一ノードの自己参照（self-ref）と未知トークン（例: 'Point', 'Segment'）が見つかる
- 改善案: トークン正規化、自己参照を取り除く簡易ヒューリスティック、レポート CSV 集約

参照ファイル

- `ggblab_extra/construction_parser.py`
- `examples/run_poc_ged.py`
- `examples/run_poc_on_parquets.py`

簡単な使い方（例: 環境変数で出力先を指定）

```bash
export GGBLAB_FT_REPORT_DIR=examples
python examples/run_poc_on_parquets.py
```

補足: 環境変数の代わりにパーサーインスタンスに直接 `ft_report_dir` を設定することもできます。例えば:

```python
parser = ConstructionTreeParser(df=df)
parser.ft_report_dir = 'examples'
parser.parse()
```
