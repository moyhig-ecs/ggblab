# replay / stage 2 — applet adapter と二段 gate (2026-09-07)
起点(段階 1 の Construction 型)を現行経路に接続する段。受入 = **現行経路と同じものが applet に届く**こと。二段 gate:
gate #1(headless)= 命令文字列の同型実行検定、gate #2(browser)= getXML の byte 一致(未実施・下記)。

## gate #1 — 現行経路の文字列化 vs v2 `render`(headless・`probes/stage2_render_equivalence.py`)
- 現行経路 = v1 の `@ggb` macro **そのもの**(`julia/GeoGebra.jl/src/ggb_macros.jl` を逐語 include・md5 `6d9c9ceb…`)を、送信だけ記録に差し替えた stub(`probes/stage2/current_route_render.jl`・引数の文字列化規則は `CommBridge.send_command_eval` を逐語複写・`expr_to_cmd_string` は `ggb_sympy.jl` から切り出し)で走らせ、applet に届くはずの文字列を得る。applet も kernel も PythonCall も不要(805 行 6 s)。
- 判定は級(述語)で: exact / ws(空白差)/ paren(Julia の Expr 印字 `2π/5` → `(2π) / 5`)/ num(`0.6260` → `0.626`)/ quote / mismatch / dynamic(実行時の値が要る = 除外)/ directive。陽性統制 = v2 の引数順を反転 → 多引数命令 512 行が全て落ちる(512/512 ⭕)。
- **結果(textbook-2026 L04–L13・805 行)**: directive 54 / 静的 731 = **exact 718 / ws 4 / paren 4 / num 4 / quote 1 / mismatch 0** / dynamic 20 → **⭕ PASS**。報告 = `probes/stage2_render_equivalence_report.json`。
- 一走目で見つかった v2 の欠陥(直した): 引用符付き定義 `G = "(A+B+C)/3"` と文字列引数を v2 は引用符ごと送っていた(55 行)。現行経路は Julia 側で剥がす(`"…"` は 28 頭の外の式を通す escape hatch であって GeoGebra の text 構文ではない)→ `construction.py` の `render` を修正(= **既存段階の編集 1 件**・INSTR の言う「起点の訂正が足りていない印」として記録)。
- 現行経路の欠陥(v2 は再現しない): `G_{s} = "(A_s + B_s + C_s) / 3"` だけは v1 が引用符を残して送る(Julia が `G_{s}` を `Expr(:curly)` に読み `string(ex)` へ落ちる)= text object になる。quote 級 1 行はこれ。
- directive の現行動作(逐語): `:const :new` → `newConstruction()`、`:api getVersion()` → API 呼び出し。
- dynamic 20 行 = 裸識別子(`Midpoint(B, C)`・`s = d1 + d2` 等)。現行経路は Julia 変数の値を文字列化して送る(GGBObject なら label)。v2 は `Ident` をそのまま渡す = 先生判断 2(裸識別子の扱い)がここに効く。

## adapter(`ggblab/adapter.py`)
- `plan(Construction) → (Eval | HostWord)*`: directive 間の命令を一つの `Eval` に束ね(JS host は順に evalCommandGetLabels)、directive は `HostWord`(newConstruction / undo / api)。
- `apply(host, c)`: `Eval` は `host.command(*cmds)`、undo は `host.delete(最後の label)`、**newConstruction と api は動詞が無いので `UnsupportedHostWord`**(推測で送らない)。tests 4 本(計 13 本)。

## 計器 C3(`probes/stage_codegraph_v2.py`・INSTR v0.2 追記 3 / Step 8)
- v2 branch の全 commit で code graph を再構築し M1 単調(追加のみ)/ M2 界面不変(HEADS 28・Verb 集合)/ M3 生えた順(host が construction より先)/ M0 既存 module の内容変更(記録)を読む。陽性統制 = import 1 本と頭 1 個を落とした合成状態で M1・M2 が落ちる。
- **読み(9 commit 時点)**: M2 ⭕(HEADS 28・状態 1 / Verb 6 = DELETE, EVAL, LISTEN, VALUE, XML_IN, XML_OUT・状態 1)/ M3 ⭕(host ≤ step 5 < construction = step 8)/ **M1 ⛔ at fa861a4**(段階 0 v2 = 先生裁定「ipywidgets 不使用」で `__init__ → host/anywidget_host` の辺が外れた = 段階 0 の起点を段階内で訂正した痕跡。計器が正しく読んだ・記録)/ 陽性統制 ⭕。

## 残す判断(先生)
1. `:const :new` の動詞: C1 に `new` を足す(JS は `api.newConstruction()`・一節)か、`XmlIn(空の construction)` で表すか。
2. 裸識別子 20 行: `Ident` のまま host へ(GeoGebra が label で解決 = Julia 変数が同名 GGBObject のときと同値)か、`:B` に正規化するか(段階 1 の判断 2 と同じ)。
3. C1 の「五動詞」と base.py の Verb 6 個(VALUE 込み)の食い違い: 文書を 6 に直すか VALUE を外すか。
4. 現行経路の `G_{s}` 欠陥: 教材側を直す(`G_s` に)か放置か。

## gate #2(browser・未実施)
- v2 経路: 試験 server 8899(STAGE0.md 末尾の一行)+ `examples/eg6_parse.ipynb` 系の cell(`apply(g, parse_cell(L04 cell))` → `g.xml()`)。
- 現行経路: v1 1.8.1(py314 に install 済・labextension 有効)の通常 JupyterLab で同じ命令列(gate #1 の v1 側の文字列)を `%%ggb` で送り `getXML`。
- 述語: `<construction>` 要素の byte 一致(view 設定は applet param 依存なので全文一致は求めない)。ws / paren / num の 12 行は両経路に各自の文字列を与えて XML が一致することを確かめる(意味的同値の実証)。applet param は v1 = `appName suite, showToolBar, showZoomButtons, showAlgebraInput, showMenuBar, autoHeight, allowUpscale false, scaleContainerClass lm-Panel, algebraInputPosition top`(`src/shared/createApplet.ts` / `components/widget.tsx`)。deployggb は v1 = cdn.geogebra.org・v2 = www.geogebra.org(同一 file か要確認)。
