# テスト実装と実施ガイド（ggblab）

このドキュメントでは、ggblab のユニットテスト/統合テストの構成、ローカルおよび CI 上での実行方法、カバレッジ目標、拡張方法について説明します。

## テスト構成

- ディレクトリ構成（抜粋）
  - `tests/`（ユニットテスト）
    - `test_construction.py`: 形式別ロード/セーブ (.ggb Base64, ZIP, JSON, XML)、ラウンドトリップ、エッジケース
    - `test_parser.py`: 依存グラフ構築、ルート/リーフ同定、トポロジカルソート、世代分析
    - `__init__.py`, `conftest.py`: Pytest 設定・共通フィクスチャ
  - ルート
    - `pytest.ini`: カバレッジ/マーカー/出力設定
    - `.github/workflows/tests.yml`: GitHub Actions 上での自動テスト

## ローカル実行

前提: 仮想環境を有効化（Conda/venv）

```bash
pip install -e ".[dev]"
pip install pytest pytest-cov

# すべてのテストを実行
pytest

# 詳細出力 + カバレッジ
pytest -v --cov=ggblab --cov-report=term-missing

# 特定ファイルのみ
pytest tests/test_construction.py -v
pytest tests/test_parser.py -v

# 失敗したテストのみ再実行
pytest --lf
```

生成物:
- `htmlcov/`（HTML カバレッジレポート）
- `coverage.xml`（CI 用カバレッジレポート）

## CI（GitHub Actions）

- ワークフロー: `.github/workflows/tests.yml`
- 対象: `ubuntu-latest`, `macos-latest`, `windows-latest` / Python `3.10`〜`3.12`
- 実行内容:
  - 依存関係のインストール (`pip install -e ".[dev]"`)
  - `pytest` によるテスト実行 + カバレッジ生成
  - Codecov へのアップロード（オプション）

## カバレッジ目標

- v0.8.0: 50% 以上（`construction`, `parser` を中心に達成）
- v0.9.0: 70% 以上（`comm`, `ggbapplet` のテスト追加）
- v1.0.0: 80% 以上（統合テスト/残りのエッジケース）

## テスト作成の指針

- 単一責務のテスト関数（1テスト = 1挙動）
- フィクスチャ（`conftest.py`）でテストデータ生成・使い回し
- エッジケースを優先（空ファイル、破損データ、非存在パス）
- 失敗時はユーザーに意味のあるメッセージ（例外種別・文言）
- 可能ならラウンドトリップ（load→save→load）で整合性検証

## 代表的なテスト内容（概要）

- `test_construction.py`
  - Base64 .ggb / ZIP .ggb / JSON / XML のロード
  - `<construction>` への XML ストリップと科学的記法の正規化（`e-1 → E-1`）
  - Base64 有無によるセーブ挙動（ZIP/プレーン XML）
  - 自動ファイル名生成（`name_1.ggb`, `name_2.ggb`）
  - ラウンドトリップ一致検証
- `test_parser.py`
  - ノード/エッジ生成（依存関係）
  - ルート/リーフの同定
  - トポロジカルソート/世代分析（スコープレベル）
  - 推移的依存（A→AB→L→C→triangle など）

## 拡張計画（提案）

- `tests/test_comm.py`: 通信レイヤ（IPython Comm + OOB ソケット）のモックテスト
- `tests/test_ggbapplet.py`: `GeoGebra` API の統合テスト（起動→関数呼び出し）
- Playwright/Galata による UI テスト（別レポジトリ/ディレクトリ）

## トラブルシューティング

- `ImportError: ggblab.* が見つからない`
  - `conftest.py` が `sys.path` にプロジェクトルートを追加済みか確認
  - `pip install -e ".[dev]"` を実行
- Windows で ZIP ファイル関連の失敗
  - パス/改行コード差異に注意、`zipfile.is_zipfile()` で事前チェック
- カバレッジが低い
  - エッジケース追加、分岐を通すテストを増やす

## 参考

- `pytest.ini`: カバレッジ設定・マーカー
- `.github/workflows/tests.yml`: CI 実行条件/環境
- `docs/ai_assessment.md`: 技術評価とテスト優先順位の背景
