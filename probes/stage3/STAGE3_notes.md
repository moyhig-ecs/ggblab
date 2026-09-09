# stage 3 (対話の界面) — 前段: Jupyter MCP Server 二経路の実測(2026-09-09)
- `mcp_client.py <url> list | call <tool> '<json>'` — streamable HTTP の最小 client(mcp SDK)。
- lab 構成: `probes/lab_config`(最小・JSD off・8899)/ `probes/.runtime_full`(フル・JSD on・8897・MCP 3005)/ `probes/lab_config_ydoc`(JSD off・jupyter_server_ydoc on・8896・MCP 3006 = datalayer 版の相手)。
- datalayer `jupyter-mcp-server` 2.1.10 は別 venv(scratchpad)で `start --transport streamable-http --port 4040 --document-provider jupyter --jupyter-url http://127.0.0.1:8896 --jupyter-token … --document-id examples/eg5_construction.ipynb --insecure-mcp-noauth --jupyterlab false`。
- 結果(詳細 = lancedb-rag `conversations/2026-09-09/RECORD_ggblab_replay_stage3_mcp_measurement_20260909.md`): 両経路とも cell_index 0 始まり・18 tool。A(frontend command 経由)の run_all は applet 170 object ⭕。B(server 側実行)は mount の HTML が browser に届かず `set_xml` timeout(docprovider-extension disabled = browser は RTC room 外)。
- 設計項目(段階 3): mount id を kernel(session)単位で安定させ、browser に生きている applet が新しい kernel object の request も受ける。実装は先生の GO の後。

## 09-09 pm — document-scoped mailbox (measured)
- relay: mount_key(doc:<path> | kernel:<id>), whoami, poll lease (40 s, `held`), reply_to per request. host: GeoGebra(mount=, doc=), page registry `window.__ggblabBoxes`, held backoff.
- A route (Restart & Run All) on 8899/8896: box doc:examples/eg5_construction.ipynb, EQUAL True, 170 objects, 1 mount.
- datalayer 2.1.10 `use_notebook(kernel_id=…)` ignores kernel_id and starts a new session-less kernel → box kernel:<id> → timeout. With `GeoGebra(doc="examples/eg5_construction.ipynb")` the request is served by the browser applet: reply ['D2'] in 6 ms, served XML 154 elements.
- Same kernel, second object: box doc, dedupe note shown, reply ['E'], XML 151 elements.
- jupyter_ai notebook tools need JSD (`yroom_manager`) → cannot share a lab with datalayer (ydoc). `window.ggbApplet` may point at a stale saved-output applet; observe via `el.__api`.
