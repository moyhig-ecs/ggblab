# ggblab — ipympl/ipywidgets 比較と対処メモ

日付: 2026-01-28

目的: `ggblab` を初期化した後に `ipywidgets` の Comm が使えなくなる問題を回避するための調査結論と推奨アクションをまとめる。

要点
- ipympl の実装は `DOMWidget` ベースで front-end の `on_msg`/`send` を用いる典型的な ipywidgets パターンを踏襲している。
- ipympl はセル実行ライフサイクルの制約（セル実行中に Comm や描画処理が停滞する）を補うために `post_execute` フックや専用の flush 処理を導入している。

ggblab 側の現状（該当ファイル）
- `ggblab/comm.py`:
  - 二重チャネル設計: IPython Comm（コマンド） + アウトオブバンド（Unix domain socket / WebSocket）でレスポンスを受ける。
  - `pending_futures`, `recv_events` キューを使い、OOB ソケットからの応答で future を満たす実装がある。
  - `_ensure_widget_bridge()` による最小ウィジェット作成フォールバックがある。
- `src/widget.tsx`:
  - フロントエンド側で WidgetManager が存在する場合は生の `jupyter.widget` ターゲット登録を避ける変更を既に加えている（Comm ハンドシェイクを“盗まない”ようにするため）。

問題の本質
- IPython kernel の Comm はセル実行中にメッセージ受信が滞るケースがあり、これが ipywidgets と同居した際に「Comm が見つからない」や「プロトコルバージョンが空になる」等の競合を招く。
- フロントエンドがウィジェット用の Comm を不適切に“取り出す（steal）”と、正しい widget-manager のハンドシェイクが完了せず ipywidgets 側が壊れる。

実施済みの対処（このリポジトリに適用済み）
- `ggblab/comm.py` に `post_execute` 用ハンドラを追加して `recv_events` をセル終了時にフラッシュするようにした。
- `send()` において可能なときはカーネル I/O ループ経由で `tc.send()` を行い、スレッド安全に送信する分岐を追加した。
- フロントエンド側では WidgetManager がいる場合に生の target 登録を避ける変更を行っている（`src/index.ts` / `src/widget.tsx` の変更）。

推奨追加対策（優先度順）
1. 維持: 現状の OOB ソケット方針を維持する（セル実行中でも応答を受けられるため有利）。
2. `post_execute` の活用を拡張: 現在のフラッシュは診断向けだが、`recv_events` の処理（エラーバブルアップ、ユーザー向け通知）を `post_execute` で明示的に行うと UX が向上する。
3. Frontend 側の WidgetManager 協調: フロントエンドが本当に WidgetManager を持つ場合は、`model_id` に対して `manager.get_model(model_id)` → `create_view` の正規 API を使って接続する設計に移行し、“comm を奪う”ような raw ターゲット登録は避ける。
4. 送信経路の強化: バックグラウンドスレッドや OOB ハンドラから IPython Comm を呼ぶときは常にカーネル I/O ループ経由で実行するよう統一する（現在は best-effort で `io_loop.add_callback` を使う分岐を追加済み）。
5. ロギングと可視化: ブラウザコンソールとカーネル側ログ（`ggblab/comm.py` の `logs`）を緊密に連携させ、発生したタイミングでの `clients`/`target_comm` 状態を簡単に取得できるデバッグコマンドを追加する。

短い実施計画（次 2 手）
- 即時（短期）: ユーザに Jupyter を再起動して `GeoGebra().init()` → ipywidgets（例: `ipywidgets.IntSlider()`）を順に実行し、ブラウザコンソールとカーネルログを提供してもらう（再現確認）。
- 中期: フロントエンドで正規の `WidgetManager` を渡してフロントエンド側で `model_id` を attach するパスを実装する（この変更でプロトコル競合は根本解決できる）。

参照ファイル
- `ggblab/comm.py` (通信レイヤー) — 既に `post_execute` ハンドラと `io_loop` 経由 send を追加済み。
- `src/widget.tsx`, `src/index.ts` (フロントエンド) — WidgetManager の有無で raw target 登録を回避する変更を確認。

メモ作成者: 変更を適用した自動エージェント（作業ログはコミット履歴またはこの会話ログを参照してください）

---
追加でこのファイルに記載して欲しい項目（例: 実行ログの抜粋、追加の行番号参照）があれば教えてください。対応してファイルを更新します。