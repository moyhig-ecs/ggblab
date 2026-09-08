# replay / stage 1 — Construction 型と型付き構成器 (2026-09-04)
訂正 B: 起点 = Construction(自由対象 + 命令 28 頭 + 依存辺)。鞭毛 = parser を「28 命令の判別共用体を返す型付き構成器」に。
- `ggblab/construction.py`  頭 = `CommandHead`(Literal 28・先生確定 09-04)/ `Command` / `FreePoint` / `FreeNumber` / `Definition` / `Directive`・引数 = `Ref(:A)` / `Ident(A)` / `Num` / `Tup` / `Str` / `Raw` / 入れ子 `Command`。`render`(→ GeoGebra 命令文字列)・`signature`(頭ごとに一節・`match` + `assert_never`)・`references` / `dependencies`(依存 DAG)。純粋関数のみ(C3)。
- `ggblab/parse.py`  `parse_cell(text, dialect="julia"|"python") → Construction`。閉世界: 28 頭の外は `UnknownHead`。コメント・文字列・入れ子括弧を扱う分割器。
- `probes/stage1_closed_world.py`  gate(C5/R5/R6): textbook-2026 L04–L13 の `@ggb` 805 行 → Unknown 0・parse error 0・arity 違反 0・観測頭集合 == 28・陽性統制(`Locus` を外すと Unknown = 2)。報告 = `probes/stage1_closed_world_report.json`。
- `tests/test_construction.py`  9 tests(parser test を 0 → 9 に)。
- `examples/eg6_parse.ipynb`  受入(C5): L04 cell → Construction → 命令列 → DAG → gate。headless 実行済(nbconvert・error 0)。

## 実測(2026-09-04)
- fixture 805 行 = directive 54 / free_point 125 / command 568(頭の出現 570・入れ子 1 行 = L05 `Intersect(Segment(A, M_a), Segment(B, M_b))`)/ definition 58(`G="(A+B+C)/3"`・`S={{1,k},{0,1}}`・`T_1=l_t(1)` 等)。
- 28 頭の出現: Intersect 90 / Distance 58 / Circle 50 / Line 44 / Midpoint 43 / PerpendicularLine 39 / AngleBisector 35 / Polygon 33 / Point 32 / Segment 23 / TriangleCenter 20 / ApplyMatrix 14 / PerpendicularPlane 11 / PerpendicularBisector 10 / Vector 9 / IntersectConic 8 / Sphere 8 / Cone 7 / Angle 6 / Ellipse 6 / Length 6 / Slider 4 / ClosestPoint 4 / Reflect 4 / Polar 2 / Locus 2 / Determinant 1 / Plane 1。
- 引数: シンボル参照 `:A` が主(≈1,050)・数 ≈100・組 29・文字列 21・裸識別子 15(L05 の SymPy 記法)。arity は全頭で signature の範囲内(観測 min..max は報告 JSON)。

## 残す判断(先生)
- 入れ子 1 行(L05)は「ネスト禁止」の教材規律に反する: 教材側を直すか、parser が入れ子を許し続けるか(現状 = 許して報告)。
- 裸識別子(`Midpoint(B, C)`)の扱い: Ident のまま host に渡す(現状)か、`:B` に正規化するか。
- 網羅検査の道具(裁定枠 ③): pyright / mypy は未導入。`assert_never` は書いてある。
- 次 = 段階 2: applet adapter(Construction → `Eval` 五動詞)・現行経路と getXML の byte 一致。

## 受入(2026-09-08・先生「柱 2 段階 1 へ進みます」・裁定 09-08 = ggblab_extra は data-in / getValueString を捨てる / 互換層なし)
- 新設: `ggblab/schema.py`(v1 verbatim・XSD は package 同梱 `ggblab/xsd/common.xsd`)/ `ggblab/xml_errata.py`(v1 `file.py` の正規化・errata + `construction_xml` = getXML() 文書 / `<construction>` / 断片 のいずれも受ける)/ `ggblab_extra/construction_io.py`(**data-in**: `from_xml(xml)` / `from_ggb_file(path)` / `from_parquet`・decode 以降は v1 `_build_df_from_ggb_file` verbatim・pure helper `commands_for_ggb` / `commands_for_magic` / `save_dataframe` verbatim・juliacall / `called_from_julia` / monkeypatch / `maybe_await` / `async` は無し)。host 側 glue は notebook の一行 `ConstructionIO.from_xml(g.xml())`。
- 試験 `tests/test_construction_io.py` 5(計 20 pass): 170 行 × 10 列・Polygon errata = 陽性統制(`f` = `Segment(C, A, poly1)`)・文書 / 要素 / 断片の三形・.ggb と getXML の一致・陰性統制(label 一つ変更 → 不一致)。
- **受入 probe** `probes/stage1_dataframe_parity.py`(報告 `probes/stage1_dataframe_parity_report.json`・内訳 `probes/stage1/parity_breakdown.json`):
  - v2 `from_ggb_file` vs **v1 file 経路の実出力**(2026-01-20 `2025_13_01.json` = `probes/stage1/v1_file_path_20260120.json`): **170/170・8 列すべて mismatch 0(Value 含む)**。
  - v2 `from_xml(applet getXML)` vs v2 `from_ggb_file`: 170/170・mismatch 0。
  - v2 `from_xml` vs **v1 applet 経路**: v1 の Comm は v1 lab で今日も開かず(274 s・version None = 09-07 と同じ race)。そこで v1 `_build_df_from_applet` と**同じ API 呼び出し**(getAllObjectNames → object ごとに getObjectType / getCommandString / getValueString / getCaption / getLayer + getXML(label))を Playwright から v2 の applet(5.4.920.0)に掛け(`probes/stage1/applet_api_capture.json`)、v1 の後処理を逐語で当てた(`probes/stage1/v1_applet_path_replica.py` → `df_applet.json`)。結果: ShowObject / ShowLabel / Auxiliary = 0 / Caption 154 は全て null vs ''(実差 0)/ Command: null vs '' 2 + 実差 19(式の印字 `((w * u)) / ((u * u))` vs `(w u) / (u u)` 等 8・free text は getCommandString が '' で XML は本文を持つ 8・`Translate(Vector(…))` の印字 3)/ Type 12(XML の class vs API の特殊化: conic→circle 3・polygon→triangle 8・polygon→quadrilateral 1)/ Layer 10(XML に `<layer>` が無い object = 0 vs getLayer 8)/ Value 170(設計どおり: getValueString を捨てた)。**v2 に帰する差は無く、差はすべて XML と API という二つの源の違い**(v1 の file 経路も同じ差を持つ)。
- notebook(C5): `examples/eg5_construction.ipynb` v2(file 経路 → host `xml_in` + `xml_out` 各一回 0.71 s → 170 行・EQUAL True・helper)/ `examples/eg4_errors.ipynb` v2(閉世界 `UnknownHead` / `ParseError` / arity を送信前に・host の誤りは reply `[None]`)。いずれも v2 試験 lab(8899)で Restart & Run All → DONE。
- 残す判断(先生): (a) `parse.py` は `Circle(A, ` を `Definition` として受ける(括弧不整合を拒まない・v1 tokenizer は syntax error)→ 段階 1 の 4 点に追加。(b) Type の特殊化(circle / triangle / quadrilateral)を `from_xml` で命令頭から導くか(XML の class のまま = v1 file 経路と同じ)。(c) XML に `<layer>` の無い 10 object(GeoGebra の直列化)は 0 のまま。(d) applet の誤りは modal dialog を出す(`setErrorDialogsActive(false)` を host の mount に入れるか = 段階 3 の listener と併せて)。
