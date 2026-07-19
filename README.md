# MineM

[中文](#中文) | [English](#english)

MineM 是一个本地优先的汇报素材管理平台，用于导入、整理、预览、编排和导出
汇报、页面、案例与资源素材。

MineM is a local-first presentation material platform for importing,
organizing, previewing, arranging, and exporting reports, pages, cases, and
media resources.

> **公开准备状态 / Publication status:** 源码公开边界已经确认，当前仓库仍处于
> 发布准备阶段。公开前必须通过
> [`docs/OPEN_SOURCE_RELEASE.md`](docs/OPEN_SOURCE_RELEASE.md) 中的全部门禁。
> The source boundary is approved, while the repository is still being prepared
> for publication. All gates in the release boundary document must pass first.

## 中文

### 核心能力

- 管理汇报、单页、案例、资源和故事线素材。
- 导入 HTML 或 ZIP 汇报包，将多页汇报拆分为独立页面素材。
- 统一页面预览、翻页、全屏和尺寸适配逻辑。
- 对汇报页面进行排序、插入和隐藏编排，并保留来源关系。
- 导出可独立打开的 HTML 汇报包或 PDF。
- 使用 SQLite 在本机保存数据，不要求云端账号。
- 提供可选的 macOS 桌面客户端与本地语音服务源码。

### 环境要求

- Python 3.12（推荐）
- Node.js `^20.19.0` 或 `>=22.12.0`
- npm

### 一条命令启动

macOS 或 Linux 在仓库根目录执行：

```bash
./start.sh
```

启动器会按需创建 `.venv`、安装依赖、在前端源码变化后重新构建，并打开浏览器。
手工安装时可执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
npm ci
npm run build
python3 server.py
```

浏览器访问：<http://127.0.0.1:8790/>

首次启动会创建本地运行目录。`data/`、`uploads/`、`extracted/`、
`thumbnails/`、`report-exports/` 和 `artifacts/` 不属于源码，不得提交。

### Docker

Docker 默认以空素材库启动，不扫描任何本机目录：

```bash
docker compose up -d --build
```

需要自动扫描外部素材时，复制 `docker-compose.override.example.yml` 为
`docker-compose.override.yml`，并显式设置 `MINEM_IMPORT_ROOT`。外部来源始终以
只读方式挂载。可选语音服务使用 `docker compose --profile speech up`，模型权重
需要单独获取。

### 开发检查

```bash
npm run check
python3 -m compileall -q minem scripts server.py
python3 scripts/check_public_boundary.py
python3 scripts/check_repository_docs.py
python3 scripts/version_control.py check
```

涉及真实数据治理的脚本必须先以只读模式运行，只有明确确认后才使用 `--apply`。

### 项目结构

| 路径 | 作用 |
| --- | --- |
| `frontend/` | React + TypeScript 前端源码 |
| `minem/` | Python 领域模块与数据访问 |
| `server.py` | 本地 HTTP 服务入口和兼容路由 |
| `desktop/` | macOS 桌面客户端源码 |
| `templates/` | 平台运行时 HTML 模板 |
| `scripts/` | 测试、校验、治理、版本和 CLI 工具 |
| `docs/` | 产品、技术、设计、测试与发布文档 |

### 数据与隐私

公开仓库不包含用户数据库、客户材料、导入汇报、预览图、模型权重、音频、
桌面安装包或本机路径配置。提交 Issue 或 Pull Request 时也不得上传这些内容。
完整边界见[公开版本边界](docs/OPEN_SOURCE_RELEASE.md)。

### 文档与社区

- [文档索引](docs/README.md)
- [贡献指南](CONTRIBUTING.md)
- [支持说明](SUPPORT.md)
- [安全策略](SECURITY.md)
- [社区行为准则](CODE_OF_CONDUCT.md)
- [第三方软件声明](THIRD_PARTY_NOTICES.md)

## English

### Core capabilities

- Manage report, page, case, resource, and storyline materials.
- Import HTML or ZIP report packages and split multi-page reports into
  independent page materials.
- Use one preview, navigation, fullscreen, and canvas-fitting model.
- Reorder, insert, or hide report pages while preserving source lineage.
- Export standalone HTML report packages or PDF files.
- Store local data in SQLite without requiring a cloud account.
- Build the optional macOS client and local speech service from source.

### Requirements

- Python 3.12 recommended
- Node.js `^20.19.0` or `>=22.12.0`
- npm

### One-command startup

On macOS or Linux, run from the repository root:

```bash
./start.sh
```

The launcher creates `.venv` when needed, installs dependencies, rebuilds the
frontend only after source changes, starts MineM, and opens a browser. For a
manual setup, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
npm ci
npm run build
python3 server.py
```

Open <http://127.0.0.1:8790/>.

The first run creates local runtime directories. `data/`, `uploads/`,
`extracted/`, `thumbnails/`, `report-exports/`, and `artifacts/` are local
state and must never be committed.

### Docker

Docker starts with an empty library and scans no host directory by default:

```bash
docker compose up -d --build
```

To scan an external source, copy `docker-compose.override.example.yml` to
`docker-compose.override.yml` and set `MINEM_IMPORT_ROOT` explicitly. The
source is always mounted read-only. The optional speech service uses
`docker compose --profile speech up`; obtain model weights separately.

### Development checks

```bash
npm run check
python3 -m compileall -q minem scripts server.py
python3 scripts/check_public_boundary.py
python3 scripts/check_repository_docs.py
python3 scripts/version_control.py check
```

Run data-governance tools in read-only mode first. Use `--apply` only after
reviewing the proposed changes.

### Repository layout

| Path | Purpose |
| --- | --- |
| `frontend/` | React and TypeScript frontend source |
| `minem/` | Python domain modules and data access |
| `server.py` | Local HTTP service and compatibility routes |
| `desktop/` | macOS desktop client source |
| `templates/` | Runtime HTML templates |
| `scripts/` | Tests, validation, governance, versioning, and CLI tools |
| `docs/` | Product, technical, design, testing, and release documents |

### Data and privacy

The public repository excludes user databases, customer materials, imported
reports, previews, model weights, audio, desktop installers, and machine-local
path configuration. Do not attach this content to issues or pull requests.
See the [open-source release boundary](docs/OPEN_SOURCE_RELEASE.md).

### Documentation and community

- [Documentation index](docs/README.md)
- [Contributing guide](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Security policy](SECURITY.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## 许可证 / License

MineM 源码依据 [Apache License 2.0](LICENSE) 发布。MineM source code is
licensed under the [Apache License 2.0](LICENSE). MineM 名称、产品标识和 Logo
不随代码授权。The MineM name, product identity, and logos are not licensed
with the source code.
