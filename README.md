# ggblab

JupyterLab 上で GeoGebra アプレットを開き、Jupyter カーネルと双方向にやり取りするためのJupyterLab機能拡張とPythonライブラリです。
~~コマンドパレット/ランチャーから起動する方法に加え、~~Python の初期化 (`GeoGebra().init()`) でGeoGebraビューを開きます。
その際、Jupyter/JupyterHub APIによって、自動的にJupyterカーネルとGeeGebra Applet間のセキュアな通信を開始します
 (コマンドパレット/ランチャーから起動してもJupyterカーネルとの通信経路は開きません)。
Python 側から図形生成や値取得を非同期に呼び出せます。
フロントエンドは React/Lumino ウィジェット、バックエンドは ipylab とカスタム Comm/WebSocket で連携します。

下部に英語版を併記しています (English version is provided below).

## 特徴

- Command Palette/Launcher から、または Python の `GeoGebra().init()` から GeoGebra パネルを起動 (コマンド ID: `ggblab:create`, ラベル: "React Widget")
- Python から `GeoGebra` クラスを介してコマンド実行 (`command`) と API 呼び出し (`function`) が可能
- Comm メッセージと OS の Unix ドメインソケット (POSIX) / TCP WebSocket を併用した高速なデータ転送
- 図形の追加・削除・リネーム・クリアやダイアログ検出をフロント側で監視し、カーネルへ通知
- 設定スキーマあり (現状オプションなし) で JupyterLab の Settings と統合

## 前提条件

- JupyterLab 4.0 以降
- Python 3.10 以降
- ブラウザから https://cdn.geogebra.org/apps/deployggb.js へアクセスできるネットワーク環境
- 開発者向け: Node.js と `jlpm` (JupyterLab 同梱の yarn) が必要

## インストール (利用者向け)

```bash
pip install ggblab
# 反映確認
jupyter labextension list | grep ggblab
```

アンインストール:

```bash
pip uninstall ggblab
```

## すぐ試す (UI)

1. JupyterLab を開く
2. Command Palette で "React Widget" を実行 (カテゴリ "Tutorial") するか、Launcher の "example" セクションにあるタイルをクリック
3. GeoGebra パネルがメインエリアに開きます。レイアウト復元とランチャー登録に対応しています。

## すぐ試す (Notebook/Python API)

以下は Notebook での最小例です (セル内で `await` 実行可能な環境を想定)。

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # Comm とソケットを初期化し、UI パネルを開く

# 点を作成
await ggb.command("A=(0,0)")

# GeoGebra API を呼び出して値を取得
value = await ggb.function("getValue", ["A"])
print(value)
```

`init()` はカーネル ID を取得し、フロントエンドのコマンド `ggblab:create` を叩いて GeoGebra パネルを右分割で開きます。以降 `command` は GeoGebra コマンド、`function` は GeoGebra API 名 (配列で複数指定可) を実行します。戻り値は非同期で返されます。

## 例 (Examples)

- サンプルノートブック: [examples/example.ipynb](examples/example.ipynb)
- デモ動画:

<video src="https://github.com/user/repo/assets/example.mov" controls width="100%">
  <source src="examples/example.mov" type="video/quicktime">
  お使いのブラウザは動画タグに対応していません。<a href="examples/example.mov">動画を直接ダウンロード</a>してください。
</video>

- 例ではオートリロードを有効化し、`GeoGebra().init()` で左側にウィジェットを開いた後、`.ggb` ファイルからコンストラクションを読み込み、XML をデコードしてスキーマに変換する流れを示しています。

実行手順:

```python
%load_ext autoreload
%autoreload 2

from ggblab import GeoGebra
import io

# 左側に GeoGebra ウィジェットを開く
ggb = await GeoGebra().init()

# コンストラクションを読み込む (自分の .ggb ファイルパスに置き換えてください)
c = ggb.construction.load('/path/to/your.ggb')

# geogebra_xml は自動的に construction 要素に絞られているため、直接スキーマにデコード可能
o = c.ggb_schema.decode(io.StringIO(c.geogebra_xml))
o
```

注: 
- `.ggb` ファイルに加え、zip、JSON、XML 形式にも対応しています。
- `geogebra_xml` は自動的に `construction` 要素に絞られ、科学記法が正規化されます。
- スキーマ/デコード API は変更される可能性があります。

## アーキテクチャ概要

- フロントエンド ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx))
	- プラグイン ID は `ggblab:plugin`。起動時にコマンド `ggblab:create` を登録し、メインエリアに ReactWidget (`GeoGebraWidget`) を開く。
	- Widget は CDN から GeoGebra を読み込み、Comm (`commTarget` デフォルト `test3`) を開いてカーネルと通信。追加/削除/リネーム/クリアやダイアログを監視して通知。
	- 受信コマンド `type: command` で GeoGebra コマンドを実行、`type: function` で GeoGebra API を呼び出し結果を返送。結果は Comm に加えて外部ソケットにも送信可能。

- バックエンド ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/construction.py](ggblab/construction.py))
	- `GeoGebra` クラスがシングルトンとして Comm と WebSocket サーバーを初期化し、ipylab 経由でフロントコマンドを実行。
	- `ggb_comm` は Unix ドメインソケット (POSIX) / TCP WebSocket を起動し、Comm で受けたレスポンスを待ち受ける `send_recv` を提供。
	- `ggb_construction` は `.ggb` (base64 zip)、zip、JSON、XML などの複数形式をサポートしてファイルを読み込み、構文解析して `geogebra_xml` を提供。`ggb_schema` でコンストラクション XML をスキーマに変換可能。

- スタイル ([style/index.css](style/index.css), [style/base.css](style/base.css))
	- GeoGebra 埋め込み領域を画面全体にフィットさせる基本スタイルを提供。

## 設定

設定スキーマ ([schema/plugin.json](schema/plugin.json)) は現状プロパティなしです。将来的な設定拡張のため Settings メニューに表示されます。

## 開発手順

```bash
# 1) 仮想環境を有効化したうえで依存をインストール
pip install -e ".[dev]"

# 2) フロントエンドを JupyterLab にリンク
jupyter labextension develop . --overwrite

# 3) ビルド (変更ごとに実行。自動ビルドは watch を使用)
jlpm build

# 開発中は並行で
jlpm watch   # TS の自動ビルド
jupyter lab  # 別ターミナルでサーバー起動
```

アンインストール (開発環境): `pip uninstall ggblab` 後、`jupyter labextension list` で場所を確認しシンボリックリンクを手動削除します。

## テスト

- フロントエンド: `jlpm install && jlpm test`
- 統合テスト (Playwright/Galata): [ui-tests/README.md](ui-tests/README.md) を参照。実行前に `jlpm build:prod` でビルドし、`ui-tests` ディレクトリで `jlpm install && jlpm playwright test`。

## リリース

手動/自動の配布手順は [RELEASE.md](RELEASE.md) を参照してください。バージョンは `hatch version` で管理します。

## ライセンス

BSD-3-Clause

---

# ggblab (English)

ggblab is a JupyterLab extension that opens a GeoGebra applet inside JupyterLab and lets you drive it from a Python kernel. You can launch the panel from the Command Palette or Launcher and call GeoGebra commands/functions asynchronously from Python via Comm plus an optional Unix-socket/TCP WebSocket bridge.

## Features

- Open the GeoGebra panel from the Command Palette/Launcher, or programmatically via `GeoGebra().init()` (Command ID: `ggblab:create`, label: "React Widget")
- Call GeoGebra commands (`command`) and API functions (`function`) from Python through the `GeoGebra` helper
- Combined Comm + Unix domain socket (POSIX) / TCP WebSocket channel for fast data exchange
- Frontend watches add/remove/rename/clear events and dialog messages and forwards them to the kernel
- Settings schema is wired up (no user options yet) for future configuration

## Requirements

- JupyterLab >= 4.0
- Python >= 3.10
- Browser access to https://cdn.geogebra.org/apps/deployggb.js
- For development: Node.js and `jlpm`

## Installation

```bash
pip install ggblab
jupyter labextension list | grep ggblab
```

Uninstall:

```bash
pip uninstall ggblab
```

## Quick Start (UI)

1. Open JupyterLab
2. Run "React Widget" from the Command Palette (category "Tutorial") or click the Launcher tile under "example"
3. A GeoGebra panel opens in the main area; layout restoration and launcher integration are enabled

## Quick Start (Notebook/Python)

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # init Comm/socket and open the GeoGebra panel

await ggb.command("A=(0,0)")    # create a point
value = await ggb.function("getValue", ["A"])  # call GeoGebra API
print(value)
```

`init()` fetches the current kernel ID, starts the Comm/WebSocket server, and triggers the frontend command `ggblab:create` to open the panel. `command` sends GeoGebra commands; `function` calls GeoGebra API names (single name or list) and returns the result asynchronously.

## Examples

- Sample notebook: [examples/example.ipynb](examples/example.ipynb)
- Demo video:

<video src="https://github.com/user/repo/assets/example.mov" controls width="100%">
  <source src="examples/example.mov" type="video/quicktime">
  Your browser does not support the video tag. Please <a href="examples/example.mov">download the video</a> directly.
</video>

- It demonstrates enabling autoreload, opening the widget on the left via `GeoGebra().init()`, loading a construction from a `.ggb` file, decoding the `construction` XML and converting it to a schema.

Run steps:

```python
%load_ext autoreload
%autoreload 2

from ggblab import GeoGebra
import io

ggb = await GeoGebra().init()  # open GeoGebra widget on the left

c = ggb.construction.load('/path/to/your.ggb')  # supports .ggb, zip, JSON, XML
o = c.ggb_schema.decode(io.StringIO(c.geogebra_xml))  # geogebra_xml is auto-stripped to construction
o
```

Note: Supports `.ggb` (base64-encoded zip), plain zip, JSON, and XML formats. The `geogebra_xml` is automatically narrowed to the `construction` element and scientific notation is normalized. Schema/decoding APIs may evolve.

## Architecture

- Frontend ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx)) registers the plugin `ggblab:plugin`, command `ggblab:create`, and a `GeoGebraWidget` ReactWidget. It loads GeoGebra from the CDN, opens a Comm target (default `test3`), executes commands/functions, and mirrors add/remove/rename/clear events plus dialog notices back to the kernel. Results can also be forwarded over the external socket when provided.
- Backend ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/construction.py](ggblab/construction.py)) initializes a singleton `GeoGebra`, spins up a Unix-socket/TCP WebSocket server, registers the Comm target, and drives the frontend command via ipylab. `ggb_comm.send_recv` waits for responses; `ggb_construction` loads multiple file formats (`.ggb`, zip, JSON, XML) and provides `geogebra_xml` + `ggb_schema` for converting construction XML to schema objects.
- Styles ([style/index.css](style/index.css), [style/base.css](style/base.css)) ensure the embedded applet fills the available area.

## Settings

The current settings schema ([schema/plugin.json](schema/plugin.json)) exposes no user options yet but is ready for future configuration.

## Development Workflow

```bash
pip install -e ".[dev]"
jupyter labextension develop . --overwrite
jlpm build           # or `jlpm watch` during development
jupyter lab          # run in another terminal
```

To remove the dev link, uninstall and delete the `ggblab` symlink listed by `jupyter labextension list`.

## Testing

- Frontend: `jlpm install && jlpm test`
- Integration (Playwright/Galata): see [ui-tests/README.md](ui-tests/README.md); build with `jlpm build:prod`, then `cd ui-tests && jlpm install && jlpm playwright test`

## Release

See [RELEASE.md](RELEASE.md) for publishing to PyPI/NPM or using Jupyter Releaser; bump versions with `hatch version`.

## License

BSD-3-Clause
