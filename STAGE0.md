# replay / stage 0 — 鞭毛 (2026-09-03)
訂正 A: applet の返信は control channel の comm_msg で届く (kernel 内に WebSocket listener も bridge も置かない)。
- `ggblab/host/base.py`     C1 の五動詞 (Request 判別共用体 + Host Protocol)
- `ggblab/host/control.py`  kernel 側 Comm + 待ち行列 (handler は control thread で走る)
- `ggblab/host/relay.py`    jupyter_server extension: POST /ggblab/reply → control socket へ comm_msg
- `ggblab/host/anywidget_host.py`  host adapter #1 (anywidget: JupyterLab / marimo)。kernel→applet は trait 同期、applet→kernel は relay
- `examples/eg{1,2,3,9}_*.ipynb`  仕様 (C5・main から逐語コピー)
- `probes/stage0_control_roundtrip.py`  headless 検証 (browser 無し)

実行 (JupyterLab):
```
# jupyter_server_config.py に  c.ServerApp.jpserver_extensions = {"ggblab.host.relay": True}
PYTHONPATH=$PWD jupyter lab --config=jupyter_server_config.py
```

## browser 検証 (2026-09-03 午後・Playwright MCP で JupyterLab を駆動)
- 受入: `examples/stage0_browser_test.ipynb` を Restart Kernel and Run All → `LABELS ['A','B','c'] after 0.26 s` / `XML_LEN 4925 | has Circle: True`。
  同じ page で再度 Restart & Run All(2 回目の inject)→ `after 0.06 s` / `XML_LEN 4920`。返信は kernel の Control thread で受信(`g.ctl.thread_seen == ['Control']`)。JS 例外 0。
- 返信経路の最終形: applet(anywidget ESM)→ `fetch POST <base>/ggblab/reply`(X-XSRFToken)→ relay 拡張が **widget 自身の comm** に ipywidgets `custom` メッセージを control socket へ送る → ipykernel `control_handlers['comm_msg']`(`wire_control_handlers`)→ `Widget.on_msg` → `ControlBridge.dispatch`。
  (kernel 側で独自 comm target を開く版は JupyterLab が "Exception opening new comm" で閉じるため廃止。)
- 落とし穴 3 つ(いずれも実測で判明):
  1. **jupyter_server_documents 0.2.0**(@jupyter-ai-contrib/server-documents)が有効だと、kernel 発の comm_open が frontend で例外→ comm_close され、widget も Layout も kernel の comm_manager から消える(ipywidgets/anywidget が全滅)。試験 server では `jpserver_extensions` で無効化し、frontend 側は page_config `disabledExtensions` で切る(`probes/lab_config/`)。
  2. **deployggb `inject(id)` は `document.getElementById(id)` に失敗すると "possibly bug on ajax loading?" を log して黙って戻る**(appletOnLoad が来ない)。kernel 再起動 + Run All では出力 node が document 未接続の瞬間があるため、id ではなく **要素を渡す** `inject(div)`。
  3. applet 準備前に届いた request は JS 側で **queue** し、appletOnLoad で流す(TDZ を避けるため queue/serve は inject より前に宣言)。
- 試験 server の起動(worktree 直下):
```
PYTHONPATH=$PWD JUPYTER_CONFIG_DIR=$PWD/probes/lab_config jupyter lab --config=probes/lab_config/jupyter_server_config.py --ServerApp.port=8899 --IdentityProvider.token=stage0token
```

## Julia (IJulia 1.34.4 / Julia 1.12.5) headless 検証 (2026-09-03 夕)
- `probes/stage0_julia_control_roundtrip.py`: IJulia kernel を jupyter_client で起動し、cell 内で `Comm("ggblab_control", ...)` を開いて `take!(ch)` で待つ (shell は busy)。1.5 s 後に外部から comm_msg を送る。
  - control socket → `GOT|control|on_requests_task=false|after=1.59s`(cell が塞いでいる間に届く・requests task ではない task = control task で on_msg 実行)
  - shell socket(負の統制)→ `GOT|TIMEOUT|...|after=8.02s`(cell が終わるまで届かない)
- IJulia は control と requests の両 socket を同じ `handlers` 辞書で dispatch するので、ipykernel と違い `wire_control_handlers` 相当の細工は不要。
- 制約: Julia の task は協調型。cell 側の待ちは `take!` / `wait` / `sleep` のように yield するものに限る(busy loop は control task を飢えさせる)。
- 未解決(browser 側): kernel が開いた comm の target を JupyterLab が知らないと `Exception opening new comm` → comm_close される(Python でも同じ)。Python は ipywidgets の comm に相乗りして回避したが、Julia には相乗り先が無い → comm 設計を続けるなら target を登録する labextension が要る。comm 無し設計(server 拡張の郵便箱)ならこの問題自体が消える。
- browser フル構成 8898・同 page で再 Restart & Run All (2 回目の inject): `LABELS ['A', 'B', 'c'] after 0.09 s` / `XML_LEN 4925 | has Circle: True`。
