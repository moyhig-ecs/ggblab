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
PYTHONPATH=$PWD jupyter lab --ServerApp.jpserver_extensions='{"ggblab.host.relay": true}'
```
