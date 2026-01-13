# ggblab

**English version first / 英語版が先で、その後日本語版が続きます**

---

## ggblab (English)

ggblab is a JupyterLab extension that opens a GeoGebra applet inside JupyterLab and lets you drive it from a Python kernel. You can launch the panel from the Command Palette or Launcher and call GeoGebra commands/functions asynchronously from Python via IPython Comm plus an optional Unix-socket/TCP WebSocket bridge.

### Features

- Open the GeoGebra panel from the Command Palette/Launcher, or programmatically via `GeoGebra().init()` (Command ID: `ggblab:create`, label: "React Widget")
- Call GeoGebra commands (`command`) and API functions (`function`) from Python through the `GeoGebra` helper
- Combined IPython Comm + Unix domain socket (POSIX) / TCP WebSocket channel for fast data exchange
- Frontend watches add/remove/rename/clear events and dialog messages and forwards them to the kernel
- Settings schema is wired up (no user options yet) for future configuration

### Requirements

- JupyterLab >= 4.0
- Python >= 3.10
- Browser access to https://cdn.geogebra.org/apps/deployggb.js
- For development: Node.js and `jlpm`

### Installation

```bash
pip install ggblab
jupyter labextension list | grep ggblab
```

Uninstall:

```bash
pip uninstall ggblab
```

### Quick Start (UI)

1. Open JupyterLab
2. Run "React Widget" from the Command Palette (category "Tutorial") or click the Launcher tile under "example"
3. A GeoGebra panel opens in the main area; layout restoration and launcher integration are enabled

### Quick Start (Notebook/Python)

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # init IPython Comm/socket and open the GeoGebra panel

await ggb.command("A=(0,0)")    # create a point
value = await ggb.function("getValue", ["A"])  # call GeoGebra API
print(value)
```

`init()` fetches the current kernel ID, starts the IPython Comm/WebSocket server, and triggers the frontend command `ggblab:create` to open the panel. `command` sends GeoGebra commands; `function` calls GeoGebra API names (single name or list) and returns the result asynchronously.

### Examples

- Sample notebook: [examples/example.ipynb](examples/example.ipynb)
- Demo video:

<video src="https://github.com/user/repo/assets/example.mov" controls width="100%">
  <source src="examples/example.mov" type="video/quicktime">
  Your browser does not support the video tag. Please <a href="examples/example.mov">download the video</a> directly.
</video>

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

### Saving construction

Save the current construction (archive when Base64 is set, otherwise plain XML):

```python
from ggblab import GeoGebra

ggb = await GeoGebra().init()
c = ggb.construction.load('/path/to/your.ggb')

# Save to XML (when no Base64 is set)
c.save('/tmp/construction.xml')

# Save to a .ggb file name; content depends on state:
# - if Base64 is set -> decoded archive (.ggb zip)
# - else -> plain XML bytes (extension does not enforce format)
c.save('/tmp/construction.ggb')
```

#### Saving behavior and defaults

- `c.save()` with no arguments writes to the next available filename derived from the originally loaded `source_file` (e.g., `name_1.ggb`, `name_2.ggb`, ...). Use `c.save(overwrite=True)` to overwrite the original `source_file`.
- If `construction.base64_buffer` is set (e.g., from `getBase64()` or `load()`), `save()` writes the decoded archive; otherwise it writes the in-memory `geogebra_xml` as plain XML.
- Target file extension does not enforce format: if Base64 is absent, saving to a `.ggb` path will still write plain XML bytes.
- Note: `getBase64()` from the applet may not include non-XML artifacts present in the original `.ggb` archive (e.g., thumbnails or other resources). Saving after API-driven changes can therefore produce a leaner archive.

### Use Cases (from examples/eg3_applet.ipynb)

#### 1) Algebraic commands and API functions

```python
# Algebraic command
r = await ggb.command("O = (0, 0)")

# API functions
r = await ggb.function("getAllObjectNames")
r = await ggb.function("newConstruction")
```

#### 2) Load .ggb and draw via Base64

```python
# Load a .ggb (base64-encoded zip)
c = ggb.construction.load('path/to/file.ggb')

# Render in applet
await ggb.function("setBase64", [ggb.construction.base64_buffer.decode('utf-8')])
```

#### 3) Layer visibility control

```python
from itertools import zip_longest

layers = range(10)
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=False)))
layers = [9, 0]
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=True)))
```

#### 4) XML attribute edit roundtrip

```python
# Pull XML for object 'A'
r = await ggb.function("getXML", ['A'])

# Decode to schema dict, modify, and encode back
o2 = c.ggb_schema.decode(r)
o2['show'][0]['@object'] = False
x = xmlschema.etree_tostring(c.ggb_schema.encode(o2, 'element'))

# Apply to applet
await ggb.function("evalXML", [x])
```

#### 5) Roundtrip save from applet state

```python
# Fetch current applet state as base64 and save
r = await ggb.function("getBase64")
ggb.construction.base64_buffer = r.encode('ascii')
c.save()              # next available filename based on source_file
# c.save(overwrite=True)  # to overwrite the original
```

### Object Dependency Analysis (Parser)

ggblab includes a **dependency parser** (`ggblab.parser.ggb_parser`) that analyzes object relationships in GeoGebra constructions using **NetworkX graphs**. This enables:

- **Dependency tracking**: Build a directed graph of which objects depend on which others
- **Root/leaf identification**: Find independent starting objects and final dependent objects
- **Subgraph analysis**: Identify minimal construction sequences needed to derive specific objects

#### Basic Usage

```python
from ggblab import GeoGebra
from ggblab.parser import ggb_parser
import networkx as nx

ggb = GeoGebra()
await ggb.init()

# Fetch construction protocol from applet
construction = {}
for obj_name in await ggb.function("getAllObjectNames"):
    obj_info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj_name]
    )
    construction[obj_name] = obj_info

# Parse into Polars DataFrame
parser = ggb_parser()
parser.initialize_dataframe(df=pl.DataFrame(construction, strict=False))
parser.parse()  # Build dependency graph

# Access the NetworkX DiGraph
G = parser.G
print(f"Root objects: {parser.roots}")      # Objects with no dependencies
print(f"Leaf objects: {parser.leaves}")      # Objects that nothing depends on

# Traverse dependencies
for obj in parser.roots:
    descendants = nx.descendants(G, obj)  # All objects that depend on this one
    print(f"{obj} -> {descendants}")
```

#### Advanced: Subgraph Extraction

Extract minimal construction sequences needed for specific output objects:

```python
# Analyze subgraph for focused construction steps
parser.parse_subgraph()  # Builds G2 with simplified dependencies
G2 = parser.G2

# Reconstruct only necessary steps
nx.write_network_text(G2)  # View simplified dependency tree
```

#### Parser Components

- **`df`**: Polars DataFrame with columns `Type`, `Command`, `Value`, `Caption`, `Layer` (transposed from construction protocol)
- **`G` (NetworkX DiGraph)**: Full dependency graph; edges point from dependencies to dependents
- **`G2` (NetworkX DiGraph)**: Simplified subgraph with redundant dependencies removed
- **`ft` (dict)**: Tokenized command strings; maps object name → list of tokens (parsed by `tokenize_with_commas()`)
- **`roots` (list)**: Objects with `in_degree == 0` (no incoming dependencies)
- **`leaves` (list)**: Objects with `out_degree == 0` (nothing depends on them)

#### Example Notebook

See [examples/eg4_parse.ipynb](examples/eg4_parse.ipynb) for a complete example of loading a `.ggb`, building dependency graphs, and analyzing construction structure.

### Architecture

- **Frontend** ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx)): Registers the plugin `ggblab:plugin` and command `ggblab:create`. Creates a `GeoGebraWidget` ReactWidget that loads GeoGebra from the CDN, opens an IPython Comm target (default `test3`), executes commands/functions, and mirrors add/remove/rename/clear events plus dialog notices back to the kernel. Results can also be forwarded over the external socket when provided.
- **Backend** ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/construction.py](ggblab/construction.py), [ggblab/parser.py](ggblab/parser.py)): Initializes a singleton `GeoGebra`, spins up a Unix-socket/TCP WebSocket server, registers the IPython Comm target, and drives the frontend command via ipylab. `ggb_comm.send_recv` waits for responses; `ggb_construction` loads multiple file formats (`.ggb`, zip, JSON, XML) and provides `geogebra_xml` + `ggb_schema` for converting construction XML to schema objects. `ggb_parser` analyzes object dependencies using NetworkX directed graphs.
- **Styles** ([style/index.css](style/index.css), [style/base.css](style/base.css)): Ensure the embedded applet fills the available area.

#### Communication Architecture

**Dual-channel design**: ggblab uses two communication channels between the frontend and backend:

1. **Primary channel (IPython Comm over WebSocket)**:
   - Handles command/function calls and event notifications
   - Managed by Jupyter/JupyterHub infrastructure with reverse proxy support
   - Connection health guaranteed by Jupyter/JupyterHub
   - **Limitation**: IPython Comm cannot receive messages while a notebook cell is executing

2. **Out-of-band channel (Unix Domain Socket on POSIX / TCP WebSocket on Windows)**:
   - Addresses the Comm limitation by enabling message reception during cell execution
   - Allows GeoGebra applet responses to be received even when Python is busy executing code
   - Connection is opened/closed per transaction (no persistent connection)
   - No auto-reconnection needed due to transient nature

This dual-channel approach ensures that interactive operations (e.g., retrieving object values, updating constructions) remain responsive even during long-running cell execution.

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design rationale and implementation notes.

#### Error Handling and Limitations

**Primary channel (IPython Comm)**: Error handling is managed automatically by Jupyter/JupyterHub infrastructure. Connection failures are detected and handled transparently; kernel status is visible in the JupyterLab UI.

**Out-of-band channel**: The secondary channel has a **3-second timeout** for receiving responses. If no response arrives within this window, a `TimeoutError` is raised in Python:

```python
try:
    result = await ggb.function("getValue", ["a"])
except TimeoutError:
    print("GeoGebra did not respond within 3 seconds")
```

**GeoGebra API constraint**: The GeoGebra API does **not** provide explicit error response codes. Instead, errors are communicated through **dialog popups** displayed in the browser. The frontend monitors these dialog events and forwards error information via the primary Comm channel. For errors that do not trigger dialogs (e.g., malformed responses), the timeout is the primary error signal.

See [ARCHITECTURE.md § Error Handling](ARCHITECTURE.md#error-handling) for details on error detection and recovery strategies.

### Settings

The current settings schema ([schema/plugin.json](schema/plugin.json)) exposes no user options yet but is ready for future configuration.

### Development Workflow

```bash
pip install -e ".[dev]"
jupyter labextension develop . --overwrite
jlpm build           # or `jlpm watch` during development
jupyter lab          # run in another terminal
```

To remove the dev link, uninstall and delete the `ggblab` symlink listed by `jupyter labextension list`.

### Testing

- Frontend: `jlpm install && jlpm test`
- Integration (Playwright/Galata): see [ui-tests/README.md](ui-tests/README.md); build with `jlpm build:prod`, then `cd ui-tests && jlpm install && jlpm playwright test`

### Release

See [RELEASE.md](RELEASE.md) for publishing to PyPI/NPM or using Jupyter Releaser; bump versions with `hatch version`.

### Known Issues and Gaps

#### Frontend Limitations

- **No explicit error handling UI**: Communication failures between frontend and backend are logged to console but not displayed to users. Currently relies on browser console for debugging.
- **Limited event notification**: Only monitors basic GeoGebra events (add/remove/rename/clear objects, dialogs). Advanced events like slider changes, conditional visibility toggles, or script execution results are not automatically propagated.
- **Hardcoded Comm target**: The Comm target name is hardcoded as `'test3'` with no option for customization without code changes.
- **TypeScript strict checks disabled**: Some type assertions use `any` type, reducing type safety. Widget props lack full interface documentation.
- **No input validation**: Commands and function arguments are not validated before sending to GeoGebra; invalid requests may cause silent failures.

#### Backend Limitations

- **Singleton pattern constraint**: Only one active GeoGebra instance per kernel session. Attempting to create multiple instances will reuse the same connection.
- **Out-of-band communication timeout**: The out-of-band socket channel has a 3-second timeout. If the frontend does not respond within this window, the backend raises a timeout exception.
- **Limited error handling on out-of-band channel**: GeoGebra API does not provide explicit error responses, so errors are communicated indirectly:
  - GeoGebra displays error dialogs (native popups) when operations fail (e.g., invalid syntax in algebraic commands)
  - The frontend monitors dialog events and forwards error messages via the primary Comm channel
  - Errors without a dialog (e.g., malformed JSON responses) result in timeout exceptions or silent failures

#### General Limitations

- **No unit tests**: Backend Python code lacks comprehensive unit tests.
- **Incomplete integration tests**: No Playwright tests yet for critical workflows (command execution, file loading, event handling).
- **No CI/CD pipeline**: No automated testing on pull requests or releases.
- **Minimal documentation**: No dedicated developer guide beyond code comments; architecture rationale is not documented.

### Future Enhancements and Roadmap

#### Short Term (v0.8.x)

1. **Error Handling & User Feedback**
   - Add user-facing error notifications for Comm/WebSocket failures
   - Improve out-of-band error reporting: detect timeout conditions and propagate as Python exceptions with context
   - Support for custom timeout configuration in `GeoGebra()` initialization
   - Enhanced error message recovery from GeoGebra dialog content
   - Provide more descriptive error messages in the UI when operations fail

2. **Event System Expansion**
   - Subscribe to additional GeoGebra events (slider value changes, object property changes, script execution)
   - Expose event system to Python API via `ggb.on_event()` pattern
   - Log all events with timestamps for debugging

3. **Configuration & Customization**
   - Add settings UI to choose Comm target name and socket configuration
   - Allow custom GeoGebra CDN URL (for offline or private CDN scenarios)
   - Implement widget position/size preferences (split-right, split-left, tab, etc.)

#### Medium Term (v1.0)

1. **Type Safety & Code Quality**
   - Enable TypeScript strict mode and eliminate `any` types
   - Add JSDoc for all public TypeScript/Python APIs
   - Increase test coverage to >80% for both frontend and backend

2. **Advanced Features**
   - **Multi-panel support**: Allow multiple GeoGebra instances in different notebook cells
   - **State persistence**: Save/restore GeoGebra construction state to notebook or file
   - **Real-time collaboration**: Support multiple users viewing/editing the same construction
   - **Animation API**: Programmatic animation of objects with timeline control
   - **Custom tool definitions**: Allow users to define and persist custom GeoGebra tools

3. **Integration Improvements**
   - **Jupyter Widgets (ipywidgets) support**: Make GeoGebra embeddable in `ipywidgets` environments
   - **Matplotlib/Plotly integration**: Export construction data to visualization libraries
   - **NumPy/Pandas integration**: Bidirectional data sync with DataFrames

#### Long Term (v1.5+)

1. **Performance & Scalability**
   - WebSocket batching for high-frequency updates (e.g., animations)
   - Caching layer for repeated function calls
   - Support for serverless/container environments without persistent sockets

2. **ML/Data Science Features**
   - Built-in geometry solvers with numerical optimization (scipy integration)
   - Constraint solving interface
   - Interactive visualization of mathematical models

3. **Ecosystem & Standards**
   - JupyterHub compatibility testing and official support
   - Jupyter Notebook (classic) extension variant
   - Conda-forge packaging
   - Official plugin for popular JupyterLab distributions (JupyterHub, Google Colab, etc.)

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/xyz`)
3. Commit with clear messages
4. Run tests and linting: `jlpm lint && jlpm test`
5. Submit a pull request

For major changes, please open an issue first to discuss.

### License

BSD-3-Clause

---

---

## ggblab (日本語)

JupyterLab 上で GeoGebra アプレットを開き、Jupyter カーネルから非同期で駆動するための JupyterLab 機能拡張と Python ライブラリです。
コマンドパレット/ランチャーから起動するか、Python の `GeoGebra().init()` から GeoGebra パネルを開くことができます。
IPython Comm と Unix ドメインソケット (POSIX) / TCP WebSocket の併用により、高速なデータ転送が実現します。

### 特徴

- コマンドパレット/ランチャーから、または Python の `GeoGebra().init()` から GeoGebra パネルを起動 (コマンド ID: `ggblab:create`, ラベル: "React Widget")
- Python から `GeoGebra` クラスを介してコマンド実行 (`command`) と API 呼び出し (`function`) が可能
- IPython Comm メッセージと OS の Unix ドメインソケット (POSIX) / TCP WebSocket を併用した高速なデータ転送
- 図形の追加・削除・リネーム・クリアやダイアログ検出をフロント側で監視し、カーネルへ通知
- 設定スキーマあり (現状オプションなし) で JupyterLab の Settings と統合

### 前提条件

- JupyterLab 4.0 以降
- Python 3.10 以降
- ブラウザから https://cdn.geogebra.org/apps/deployggb.js へアクセスできるネットワーク環境
- 開発者向け: Node.js と `jlpm` (JupyterLab 同梱の yarn) が必要

### インストール (利用者向け)

```bash
pip install ggblab
# 反映確認
jupyter labextension list | grep ggblab
```

アンインストール:

```bash
pip uninstall ggblab
```

### すぐ試す (UI)

1. JupyterLab を開く
2. コマンドパレット (Cmd+Shift+P) で "React Widget" を実行 (カテゴリ "Tutorial") するか、ランチャーの "example" セクションにあるタイルをクリック
3. GeoGebra パネルがメインエリアに開きます。レイアウト復元とランチャー登録に対応しています。

### すぐ試す (Notebook/Python API)

以下は Notebook での最小例です (セル内で `await` 実行可能な環境を想定)。

```python
from ggblab.ggbapplet import GeoGebra

ggb = GeoGebra()
await ggb.init()                 # IPython Comm とソケットを初期化し、UI パネルを開く

# 点を作成
await ggb.command("A=(0,0)")

# GeoGebra API を呼び出して値を取得
value = await ggb.function("getValue", ["A"])
print(value)
```

`init()` はカーネル ID を取得し、IPython Comm と WebSocket サーバーを開始し、フロントエンドのコマンド `ggblab:create` を叩いて GeoGebra パネルを右分割で開きます。以降 `command` は GeoGebra コマンド、`function` は GeoGebra API 名 (配列で複数指定可) を実行します。戻り値は非同期で返されます。

### 例

- サンプルノートブック: [examples/example.ipynb](examples/example.ipynb)
- デモ動画:

<video src="https://github.com/user/repo/assets/example.mov" controls width="100%">
  <source src="examples/example.mov" type="video/quicktime">
  お使いのブラウザは動画タグに対応していません。<a href="examples/example.mov">動画を直接ダウンロード</a>してください。
</video>

実行手順:

```python
%load_ext autoreload
%autoreload 2

from ggblab import GeoGebra
import io

# GeoGebra ウィジェットを開く
ggb = await GeoGebra().init()

# コンストラクションを読み込む (自分の .ggb ファイルパスに置き換えてください)
c = ggb.construction.load('/path/to/your.ggb')

# geogebra_xml は自動的に construction 要素に絞られているため、直接スキーマにデコード可能
o = c.ggb_schema.decode(io.StringIO(c.geogebra_xml))
o
```

注: 
- `.ggb` (base64 エンコードされた zip)、通常の zip、JSON、XML 形式に対応しています。
- `geogebra_xml` は自動的に `construction` 要素に絞られ、科学記法が正規化されます。
- スキーマ/デコード API は将来変更される可能性があります。

#### コンストラクションの保存

ロード済みコンストラクションを保存します（Base64 が設定されていればアーカイブ、未設定ならプレーン XML）:

```python
from ggblab import GeoGebra

ggb = await GeoGebra().init()
c = ggb.construction.load('/path/to/your.ggb')

# XML へ保存（Base64 未設定時）
c.save('/tmp/construction.xml')

# .ggb というファイル名へ保存（内容は状態に依存）:
# - Base64 設定時: デコードしたアーカイブ（.ggb zip）
# - 未設定時: プレーン XML バイト列（拡張子は形式を強制しません）
c.save('/tmp/construction.ggb')
```

##### 保存の挙動とデフォルト

- 引数なしの `c.save()` は、読み込んだ `source_file` を基に次の未使用ファイル名（例: `name_1.ggb`, `name_2.ggb`, ...）へ保存します。元の `source_file` を上書きするには `c.save(overwrite=True)` を使います。
- `construction.base64_buffer` が設定されている場合（例: `getBase64()` や `load()` の結果）、`save()` はそのデータをデコードしてアーカイブを書き出します。未設定の場合はメモリ上の `geogebra_xml` をプレーン XML として保存します。
- 拡張子は形式を強制しません。Base64 未設定時に `.ggb` のパスへ保存しても内容はプレーン XML になります。
- 注意: アプレットの `getBase64()` は、元の `.ggb` アーカイブに含まれる非XMLの付帯ファイル（例: サムネイルやリソース）を含まない場合があります。API 経由で編集後に保存すると、元アーカイブに比べて軽量なアーカイブになることがあります。

### 利用ケース（examples/eg3_applet.ipynb より）

#### 1) 代数コマンドと API 関数

```python
# 代数コマンド
r = await ggb.command("O = (0, 0)")

# API 関数
r = await ggb.function("getAllObjectNames")
r = await ggb.function("newConstruction")
```

#### 2) .ggb を読み込み Base64 で描画

```python
# .ggb（base64 エンコードされた zip）を読み込み
c = ggb.construction.load('path/to/file.ggb')

# アプレットへ反映
await ggb.function("setBase64", [ggb.construction.base64_buffer.decode('utf-8')])
```

#### 3) レイヤー可視性の制御

```python
from itertools import zip_longest

layers = range(10)
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=False)))
layers = [9, 0]
await ggb.function("setLayerVisible", list(zip_longest(list(layers), [], fillvalue=True)))
```

#### 4) XML 属性編集のラウンドトリップ

```python
# オブジェクト 'A' の XML を取得
r = await ggb.function("getXML", ['A'])

# スキーマ dict にデコードし、編集してエンコード
o2 = c.ggb_schema.decode(r)
o2['show'][0]['@object'] = False
x = xmlschema.etree_tostring(c.ggb_schema.encode(o2, 'element'))

# アプレットへ適用
await ggb.function("evalXML", [x])
```

#### 5) アプレット状態からの保存ラウンドトリップ

```python
# 現在のアプレット状態を base64 で取得して保存
r = await ggb.function("getBase64")
ggb.construction.base64_buffer = r.encode('ascii')
c.save()               # source_file を基準に次の未使用ファイル名へ保存
# c.save(overwrite=True)  # 元のファイルを上書きする場合
```

### オブジェクト依存関係の解析（パーサー）

ggblab には**依存関係パーサー** (`ggblab.parser.ggb_parser`) が含まれており、**NetworkX グラフ** を使用して GeoGebra コンストラクション内のオブジェクト間の関係を解析します。これにより以下が実現できます：

- **依存関係の追跡**: どのオブジェクトがどのオブジェクトに依存しているかの有向グラフを構築
- **ルート/リーフの特定**: 独立したスタートオブジェクトと最終的な依存オブジェクトを検出
- **部分グラフ解析**: 特定のオブジェクトを導出するために必要な最小限のコンストラクション手順を特定

#### 基本的な使用方法

```python
from ggblab import GeoGebra
from ggblab.parser import ggb_parser
import networkx as nx
import polars as pl

ggb = GeoGebra()
await ggb.init()

# アプレットからコンストラクションプロトコルを取得
construction = {}
for obj_name in await ggb.function("getAllObjectNames"):
    obj_info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj_name]
    )
    construction[obj_name] = obj_info

# Polars DataFrame にパース
parser = ggb_parser()
parser.initialize_dataframe(df=pl.DataFrame(construction, strict=False))
parser.parse()  # 依存関係グラフを構築

# NetworkX DiGraph にアクセス
G = parser.G
print(f"ルートオブジェクト: {parser.roots}")      # 依存関係のないオブジェクト
print(f"リーフオブジェクト: {parser.leaves}")      # 他に依存されていないオブジェクト

# 依存関係をトラバース
for obj in parser.roots:
    descendants = nx.descendants(G, obj)  # このオブジェクトに依存するすべてのオブジェクト
    print(f"{obj} -> {descendants}")
```

#### 高度な機能：部分グラフの抽出

特定の出力オブジェクトに必要な最小限のコンストラクション手順を抽出します：

```python
# 構築手順を特定するため部分グラフを解析
parser.parse_subgraph()  # 冗長な依存関係を削除したG2を構築
G2 = parser.G2

# 必要な手順のみを再構築
nx.write_network_text(G2)  # 単純化された依存関係ツリーを表示
```

#### パーサーのコンポーネント

- **`df`**: 列 `Type`, `Command`, `Value`, `Caption`, `Layer` を持つ Polars DataFrame（コンストラクションプロトコルから転置）
- **`G` (NetworkX DiGraph)**: 完全な依存グラフ。エッジは依存元から依存先へ指す
- **`G2` (NetworkX DiGraph)**: 冗長な依存関係を削除した単純化部分グラフ
- **`ft` (dict)**: トークン化されたコマンド文字列。オブジェクト名 → トークンのリスト（`tokenize_with_commas()` でパース）にマップ
- **`roots` (list)**: `in_degree == 0` のオブジェクト（入次数が 0、依存関係なし）
- **`leaves` (list)**: `out_degree == 0` のオブジェクト（出次数が 0、何も依存していない）

#### サンプルノートブック

[examples/eg4_parse.ipynb](examples/eg4_parse.ipynb) で完全な例を参照してください。.ggb ファイルの読み込み、依存グラフの構築、コンストラクション構造の解析例が含まれています。

### アーキテクチャ概要

- **フロントエンド** ([src/index.ts](src/index.ts), [src/widget.tsx](src/widget.tsx))
  - プラグイン ID は `ggblab:plugin`。起動時にコマンド `ggblab:create` を登録し、メインエリアに ReactWidget (`GeoGebraWidget`) を開く。
  - Widget は CDN から GeoGebra を読み込み、IPython Comm (`commTarget` デフォルト `test3`) を開いてカーネルと通信。追加/削除/リネーム/クリアやダイアログを監視して通知。
  - 受信コマンド `type: command` で GeoGebra コマンドを実行、`type: function` で GeoGebra API を呼び出し結果を返送。結果は IPython Comm に加えて外部ソケットにも送信可能。

- **バックエンド** ([ggblab/ggbapplet.py](ggblab/ggbapplet.py), [ggblab/comm.py](ggblab/comm.py), [ggblab/construction.py](ggblab/construction.py), [ggblab/parser.py](ggblab/parser.py))
  - `GeoGebra` クラスがシングルトンとして IPython Comm と WebSocket サーバーを初期化し、ipylab 経由でフロントコマンドを実行。
  - `ggb_comm` は Unix ドメインソケット (POSIX) / TCP WebSocket を起動し、IPython Comm で受けたレスポンスを待ち受ける `send_recv` を提供。
  - `ggb_construction` は `.ggb` (base64 zip)、zip、JSON、XML などの複数形式をサポートしてファイルを読み込み、構文解析して `geogebra_xml` を提供。`ggb_schema` でコンストラクション XML をスキーマに変換可能。
  - `ggb_parser` は NetworkX を使用してオブジェクト間の依存関係を解析します。

- **スタイル** ([style/index.css](style/index.css), [style/base.css](style/base.css))
  - GeoGebra 埋め込み領域を画面全体にフィットさせる基本スタイルを提供。

#### 通信アーキテクチャ

**2チャネル設計**: ggblab はフロントエンドとバックエンド間で 2 つの通信チャネルを使用します：

1. **主回線 (IPython Comm over WebSocket)**:
   - コマンド/関数呼び出しとイベント通知を処理
   - Jupyter/JupyterHub インフラストラクチャがリバースプロキシ対応で管理
   - 接続の健全性は Jupyter/JupyterHub が保証
   - **制約**: IPython Comm はノートブックセル実行中にメッセージを受信できない

2. **帯域外チャネル (POSIX では Unix Domain Socket / Windows では TCP WebSocket)**:
   - Comm の制約を回避し、セル実行中でもメッセージ受信を可能にする
   - Python がコード実行中でも GeoGebra アプレットからの応答を受信できる
   - トランザクションごとに接続を開閉（永続接続なし）
   - 一時的な性質のため自動再接続は不要

この 2 チャネルアプローチにより、長時間実行されるセル中でも対話的操作（例: オブジェクト値の取得、コンストラクションの更新）が応答性を保ちます。

設計の根拠と実装ノートの詳細は [ARCHITECTURE.md](ARCHITECTURE.md) を参照してください。

#### エラーハンドリングと制限事項

**主回線 (IPython Comm)**: エラーハンドリングは Jupyter/JupyterHub インフラストラクチャが自動的に管理します。接続障害は透過的に検出・処理され、カーネル状態は JupyterLab UI で確認できます。

**帯域外チャネル**: セカンダリチャネルは応答受信に **3 秒のタイムアウト** を設定しています。この期間内に応答がない場合、Python で `TimeoutError` が発生します：

```python
try:
    result = await ggb.function("getValue", ["a"])
except TimeoutError:
    print("GeoGebra は 3 秒以内に応答しませんでした")
```

**GeoGebra API の制約**: GeoGebra API は **明示的なエラー応答コードを提供しません**。代わりに、ブラウザに表示される **ダイアログポップアップ** を通じてエラーが通知されます。フロントエンドはこれらのダイアログイベントを監視して、主回線 Comm 経由でエラー情報を転送します。ダイアログを伴わないエラー（例: 不正な JSON 応答）の場合、タイムアウトがエラー信号となります。

詳細なエラー検出と復旧戦略については [ARCHITECTURE.md のエラーハンドリング](ARCHITECTURE.md#error-handling) を参照してください。

### 設定

設定スキーマ ([schema/plugin.json](schema/plugin.json)) は現状プロパティなしです。将来的な設定拡張のため Settings メニューに表示されます。

### 開発手順

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

### テスト

- フロントエンド: `jlpm install && jlpm test`
- 統合テスト (Playwright/Galata): [ui-tests/README.md](ui-tests/README.md) を参照。実行前に `jlpm build:prod` でビルドし、`ui-tests` ディレクトリで `jlpm install && jlpm playwright test`。

### リリース

手動/自動の配布手順は [RELEASE.md](RELEASE.md) を参照してください。バージョンは `hatch version` で管理します。

### 既知の課題と欠落機能

#### フロントエンドの制限事項

- **明確なエラーハンドリング UI がない**: フロントエンドとバックエンド間の通信障害はコンソールにログされますが、ユーザーには表示されません。デバッグはブラウザのコンソールに依存しています。
- **イベント通知が限定的**: GeoGebra の基本的なイベント (オブジェクトの追加/削除/リネーム/クリア、ダイアログ) のみを監視。スライダーの値変更、条件付き表示の切り替え、スクリプト実行結果などの高度なイベントは自動的には伝播されません。
- **Comm ターゲットがハードコードされている**: Comm ターゲット名は `'test3'` にハードコードされており、コード変更なしにカスタマイズできません。
- **TypeScript の厳密なチェックが無効**: 一部の型アサーションが `any` 型を使用しており、型安全性が低下しています。ウィジェットプロパティのインターフェース文書化が不完全。
- **入力検証がない**: コマンドと関数の引数は GeoGebra に送信前に検証されません。無効なリクエストはサイレント失敗する可能性があります。

#### バックエンドの制限事項

- **シングルトンパターンの制約**: カーネルセッションごとに 1 つのアクティブな GeoGebra インスタンスのみ。複数インスタンスの作成を試みると同じ接続が再利用されます。
- **帯域外通信のタイムアウト**: 帯域外ソケットチャネルは 3 秒のタイムアウト設定を有しています。この窓内にフロントエンドから応答がない場合、バックエンドはタイムアウト例外を発生します。
- **GeoGebra API の制約に伴うエラー処理**: GeoGebra API は明示的なエラー遠格を提供しないため、エラーは間接的に伝通されます：
  - GeoGebra は操作失敗時（例: 代数コマンド文法エラー）、エラーダイアログ（ネイティブポップアップ）を表示します
  - フロントエンドはダイアログイベントを監視して、主回線 Comm 経由でエラーメッセージを伝送
  - ダイアログなしのエラー（例: 不正な JSON 応答）を上流で尽くす実装は不可能

#### 一般的な制限事項

- **ユニットテストがない**: バックエンド Python コードは包括的なユニットテストがありません。
- **統合テストが不完全**: 重要なワークフロー (コマンド実行、ファイル読み込み、イベント処理) の Playwright テストがまだありません。
- **CI/CD パイプラインがない**: プルリクエストやリリース時の自動テストがありません。
- **ドキュメントが最小限**: コードコメント以外の専用開発ガイドがなく、アーキテクチャの設計思想が文書化されていません。

### 将来の拡張と工程表

#### 短期 (v0.8.x)

1. **エラーハンドリングとユーザーフィードバック**
   - Comm/WebSocket 障害時のユーザー向け通知を追加
   - 帯域外エラー報告改善: タイムアウト検出を Python 例外として伝播させ、コンテキスト情報を付加
   - `GeoGebra()` 初期化時のカスタムタイムアウト設定対応
   - GeoGebra ダイアログコンテンツからのエラーメッセージ抽出改善
   - 操作失敗時の UI エラーメッセージ詳細化

2. **イベントシステムの拡張**
   - スライダー値の変更、オブジェクトプロパティの変更、スクリプト実行など、追加の GeoGebra イベントへの購読
   - Python API を `ggb.on_event()` パターンで公開
   - すべてのイベントをタイムスタンプ付きでログ

3. **設定とカスタマイズ**
   - Comm ターゲット名とソケット設定を選択する設定 UI
   - カスタム GeoGebra CDN URL (オフラインまたはプライベート CDN シナリオ向け)
   - ウィジェットの位置/サイズの設定 (split-right、split-left、タブなど)

#### 中期 (v1.0)

1. **型安全性とコード品質**
   - TypeScript 厳密モードを有効にし、`any` 型を排除
   - すべてのパブリック TypeScript/Python API に JSDoc を追加
   - フロントエンドとバックエンド両方のテストカバレッジを 80% 以上に

2. **高度な機能**
   - **マルチパネルサポート**: 異なるノートブックセルで複数の GeoGebra インスタンスを許可
   - **状態永続化**: GeoGebra コンストラクション状態をノートブックまたはファイルに保存/復元
   - **リアルタイムコラボレーション**: 複数ユーザーが同じコンストラクションを表示/編集をサポート
   - **アニメーション API**: タイムラインコントロール付きオブジェクトのプログラマティックアニメーション
   - **カスタムツール定義**: ユーザーによるカスタム GeoGebra ツールの定義と永続化

3. **統合の改善**
   - **Jupyter Widgets (ipywidgets) サポート**: `ipywidgets` 環境に GeoGebra を埋め込み可能にする
   - **Matplotlib/Plotly 統合**: コンストラクション データを可視化ライブラリにエクスポート
   - **NumPy/Pandas 統合**: DataFrame との双方向データ同期

#### 長期 (v1.5+)

1. **パフォーマンスとスケーラビリティ**
   - 高頻度更新向け WebSocket バッチング (例: アニメーション)
   - 繰り返し関数呼び出しのキャッシングレイヤー
   - サーバーレス/コンテナ環境での永続ソケットなしサポート

2. **ML/データサイエンス機能**
   - 数値最適化 (scipy 統合) を備えた組み込み幾何ソルバー
   - 制約充足インターフェース
   - 数学モデルのインタラクティブな可視化

3. **エコシステムと標準化**
   - JupyterHub 互換性テストと公式サポート
   - Jupyter Notebook (クラシック) 拡張バリアント
   - Conda-forge パッケージング
   - 一般的な JupyterLab ディストリビューション (JupyterHub、Google Colab など) の公式プラグイン

### 貢献方法

貢献は大歓迎です。以下の手順に従ってください：

1. リポジトリをフォーク
2. フィーチャーブランチを作成 (`git checkout -b feature/xyz`)
3. わかりやすいメッセージでコミット
4. テストと linting を実行: `jlpm lint && jlpm test`
5. プルリクエストを提出

大きな変更の場合は、まず issue を開いて相談してください。

### ライセンス

BSD-3-Clause
