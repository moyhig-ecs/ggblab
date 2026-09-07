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

## gate #2 — browser: getXML の `<construction>` byte 一致(`probes/stage2_xml_gate.py`・2026-09-07 夕)
- 現行経路 = v1 1.8.1(py314 に install 済・labextension)を **通常の JupyterLab**(port 8890・config = `probes/stage2/gate2/v1lab_config/`)で: `GeoGebra().init()` → comm が立つまで待つ(`getVersion` を 1 s 毎に再試行)→ 群ごとに `newConstruction` → `command(v1 側の文字列)` → `function('getXML')`(driver = `probes/stage2/gate2/stage2_xml_gate_v1.ipynb`)。
- v2 経路 = 試験 server 8899 + `examples/stage2_xml_gate_v2.ipynb`: 群ごとに新しい applet(`GeoGebra(**v1 と同じ param)`)→ `command(*v2 側の文字列)` → `xml()`。deployggb は両者 cdn.geogebra.org(applet 5.4.920.0・app suite/graphing)。
- 対象 = lesson 04 の 4 群 50 行(gate #1 の級: exact 42 / ws 4 / paren 4・dynamic なし)。各経路に**各自の文字列**を与える(exact 行は輸送の検定、ws/paren 行は意味的同値の検定)。Playwright MCP で両 lab を駆動。
- **結果**: g1・g3(10 行ずつ・exact のみ)= `<construction>` **byte 一致**(md5 33ab8903 / 3c4267ab・要素 12 / 13)。g0・g2(15 行・ws 2 + paren 2 を含む)= 要素 15/15、差分は paren 級 2 点 B・C の `<expression exp="…">` の括弧だけ(`cos(((2 * pi)) / 5)` vs `cos((2 * pi / 5))` = 入力の括弧が applet の式文字列に残る・ws 級 B2/C2 は applet が正規化して一致)。→ **PASS**(述語: 文字列が同じ行は byte 一致・paren 行は `exp=` の文字だけ)。報告 = `probes/stage2/gate2/gate2_report.json`・XML 8 本同梱。
- 副産物 2(両経路で同一に再現 = applet の性質): ① **`TriangleCenter(A, B, C, 3)` は新しい page での初回呼び出しが失敗**(v2: `Discrete commands not loaded yet`・v1: `Handler execution failed`)→ 同じ page の 2 回目(g3)は成功。lesson 04 の該当 cell は初回に落ちうる。② v1 の `init()` は applet と comm が立つ前に返る(今回 ~17 s)→ 直後の `function()` は `No active Comm`。待ちが要る。server-documents 有効の初回も同じ症状だったが待ち無しなので切り分け未了。

## 先生裁定(09-07 夜)の実装と実測
1. **`:const :new` → 動詞 `new` = `newConstruction()`**(裁定: Julia macro / Python magic は別枠、現段階では GeoGebra API を尊重)。`host/base.py` に `New`、両 host の JS に一節、adapter は `host.new_construction()` を送る。実機(`examples/stage2_new_verb.ipynb`・試験 server): reply True・直前の `Z` を含む construction が空になる(LABELS_AFTER = [])。`:api f()` は動詞にしない(閉じた部分集合を破る)= 別枠へ。
2. **裸識別子 = label 参照に正規化**(`Ident` を `Ref` に畳む)+ **label 文法の実測**(applet 5.4.920 に API で直接): `exists('l_CA') == exists('l_{CA}') == true`・`exists('l_{C}A') == false`・`A_12 ≡ A_{12}`・`G_{s} ≡ G_s`(同一性は括弧を無視)。しかし **algebra view の表示は `l_CA` → l_C A、`A_12` → A_1 2**(添字 1 文字・`probes/stage2/gate2/ggb_label_grammar_algebra_view.png`)= 先生の観察。→ `wire_label`: 括弧なし 2 文字以上の添字だけ `l_{CA}` にして送る(1 文字・既に括弧付きはそのまま = 現行経路からの最小の逸脱)。`canonical_label`(常に括弧)= DAG の同一性。表示は `l_{CA}` で l_CA に直る(`ggb_label_braced_algebra_view.png`)。gate #1 に級 `label`(83 行・送る label 24 種)。
3. **五動詞 vs Verb**: 材料と 3 案 = lancedb-rag `conversations/2026-09-07/MEMO_ggblab_v2_host_verbs_c1_20260907.md`(推し = C1 を「GeoGebra Apps API の閉じた部分集合・現在 7 = 書 4 / 読 2 / 購読 1」に書き換え、変更は C3 の allow-list に登記 — 計器は実装済: Verb 6 → 7 を「allow-list 上の変化」と読む)。
4. **v1 の `G_{s}` 欠陥** = 2 と同じ label 文法の家族だが欠陥は Julia parser 側(Expr(:curly))→ 1 の別枠へ。v2 では `G_{s}` は label として通る。

### gate #2 再走(括弧付き label を送る版・09-07 夜)
v2 route を新 kernel で再走(`groups.json` の v2 文字列を現 render で再生成: 4 群とも 4 行が `s_{BC}` / `l_{BC}` 等に変化)。XML の label は `l_{BC}` / `l_{CA}` / `l_{AB}` / `s_{BC}` / `s_{BC2}` で保存。現行経路との比較は **canonical label を法として**(gate script を canon 後の diff + 同じ命令列の v1 相手との照合に更新): g1・g3 = v1_g3 と法一致(要素 13/13)、g0・g2 = paren 級 2 点の `exp=` だけ → **PASS**。TriangleCenter の初回失敗は今回 v2 で出ず(browser が module を cache 済)= 非決定的な applet 側の性質として記録。
