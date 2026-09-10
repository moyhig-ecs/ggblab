# replay / stage 3 (`%%ggb` magic) + stage 4 (Julia host) — 2026-09-10

## `%%ggb <host>` (ggblab/ipymagic.py)
- `%load_ext ggblab.ipymagic` → `%%ggb g [--plan] [--timeout S]`. Body → `parse_cell(dialect="python")` (28 heads, `:label` refs, unknown head = error) → `adapter.plan` (ONE `Eval` per batch, `:const :new` → `new`) → `adapter.apply(g, …)`. Result `_` = flat label list (`"t1,c,a,b"` from one Polygon is split). Host is an explicit argument — no `GeoGebra._instance` / `user_ns["ggb"]` lookup (the same coupling stage 2 removed from sympy).
- Acceptance (`examples/stage3_magic.ipynb`, gate #2 group g1 = lesson 04, 10 statements): `--plan` strings == gate #1 `v2` strings; after `:const :new` + resend the applet's `<construction>` is byte-identical to `probes/stage2/gate2/v2_g1.xml` (md5 14bab5f7).
- Shared JS fix (M0, `ggblab/host/mount.js`): `eval` now try/catches per command — entry = labels | null (GeoGebra refused) | `{error}` (Apps API threw, e.g. TriangleCenter's lazy "Discrete commands not loaded yet"); before, one exception lost the whole batch's labels.

## Julia host (julia/host/html_host.jl, module `GGBLabHost` = position marker; the name is the teacher's)
- Same mailbox (C0 RPC), same JavaScript (`ggblab/host/mount.js` read by both hosts), same 8 verbs; `Downloads` (stdlib) + `JSON`; `kernel_id` from IJulia's `connection_file`; `find_server` = JUPYTERHUB env or `jupyter --runtime-dir`'s `jpserver-*.json` probed with `/api/kernels/<id>`. `listen` / `events` / `wait_update` are pull-only (no task). No comm, no HTTP.jl.
- Contract: `tests/test_julia_host_parity.py` runs julia and asserts the request JSON of all 8 verbs equals Python's `to_json`, `mount_key` three forms, `_q` percent-encoding, one JS file.
- Acceptance (`examples/julia_host.ipynb`, kernel julia-1.12): 6-command `command` 0.29 s, `value("a") = 2`, `xml` 5839 chars, 6 add events, `listen` callback fires on pull, `wait_update("A")` woke after 13.04 s on a browser-side drag, `kind("c1") = circle`.
- Not done: `@ggb` macro → Construction (brace question is the teacher's), a Julia Construction parser, JupyterHub crossing.

Record = lancedb-rag `conversations/2026-09-10/RECORD_ggblab_replay_stage3_magic_stage4_julia_20260910.md`.
