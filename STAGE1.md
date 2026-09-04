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
