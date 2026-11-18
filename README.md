<div align="center">

<img src="desktop/src-tauri/icons/icon.png" width="80" alt="MineM" />

# MineM

**把已有 HTML 整理成页面，再编排成可播放、可交付的汇报。**

A local-first workspace for HTML pages and presentations.

[![CI](https://img.shields.io/github/actions/workflow/status/Jo-Tsu/minem/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/Jo-Tsu/minem/actions/workflows/ci.yml)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/Jo-Tsu/minem/codeql.yml?branch=main&label=CodeQL&style=flat-square)](https://github.com/Jo-Tsu/minem/actions/workflows/codeql.yml)
[![License](https://img.shields.io/github/license/Jo-Tsu/minem?style=flat-square)](LICENSE)

[快速开始](#快速开始) · [使用流程](#使用流程) · [飞书链接导入](#飞书链接导入) · [文档](docs/README.md) · [English](#english)

</div>

MineM 是个人 HTML 管理与快速创作工具，以网页为主要入口。导入完整汇报或单页，
保留原来的文字、排版和媒体，再从页面库选择内容、调整顺序，生成新的汇报。
数据库和素材保存在本地，默认无需 MineM 账号。

## 核心能力

| 能力 | 当前行为 |
| --- | --- |
| 导入 | 支持 HTML、ZIP 和媒体文件；飞书文件夹链接通过本机下载服务异步处理 |
| 页面 | 一条页面素材对应一页，图片、字体、脚本、视频等依赖随页面封装 |
| 新建汇报 | 选择默认封面和已有页面，按选择顺序创建独立汇报 |
| 编排 | 插入、排序、隐藏和移出页面；保存成功后可查看最新结果，继续修改后可再次保存 |
| 播放 | 独立页面与完整汇报均可预览，支持等比适配、翻页和全屏 |
| 交付 | 导出含资源与清单的 HTML ZIP，或供静态阅读的 PDF |
| 自动化 | CLI 和 HTTP 接口可供脚本、Codex 等外部 Agent 调用 |

主流程是 **页面 → 编排 → 汇报**。每页拥有独立的资源封装，汇报保存页面的播放顺序。
插入到新汇报时复制对应页面内容和依赖，保留来源关系；不依赖跨汇报共享资源池。
资源在页面内部管理，不提供独立的资源模块入口。

## 快速开始

两种运行方式任选一种，默认访问 [http://127.0.0.1:8790/](http://127.0.0.1:8790/)。

### Docker

需要 Docker Engine 与 Compose，或 Docker Desktop。网页运行所需的 Python、
Chromium 和字体由镜像提供，主机无需安装 Node.js。

```bash
git clone https://github.com/Jo-Tsu/minem.git
cd minem
docker compose up -d --build
```

首次构建需要下载依赖；之后使用 `docker compose up -d` 启动已有镜像。
首次进入是空素材库，默认不会扫描本机材料目录。

```bash
# 查看状态与日志
docker compose ps
docker compose logs --tail=100 minem-platform

# 停止服务，保留本机数据
docker compose down
```

### 直接在本机运行

需要 Python 3.10+（推荐 3.12）、Node.js 20.19+（20.x）或 22.12+。
缩略图和 PDF 渲染还需要可被发现的 Chromium、Google Chrome 或 macOS Microsoft Edge。

```bash
git clone https://github.com/Jo-Tsu/minem.git
cd minem
./start.sh --data-dir ./runtime
```

启动器按需创建虚拟环境、安装依赖并构建前端，服务就绪后打开默认浏览器。
此命令将运行数据统一保存在项目的 `runtime/` 下；按 `Ctrl+C` 停止服务。

再次启动沿用同一命令。可加 `--no-browser` 禁止自动打开浏览器，
或用 `--port 8791` 改端口。`--skip-install --no-build` 仅适用于依赖与构建已准备好的环境。

### macOS 桌面快捷入口

完成 Docker 首次构建后，在项目目录执行：

```bash
./scripts/install_macos_launcher.sh
```

需要 Xcode Command Line Tools。脚本在桌面创建 `MineM.app`，双击后按需启动
Docker Desktop 和网页服务，再打开默认浏览器。启动时的提示可关闭，就绪后自动消失；
关闭提示不会取消后台启动。服务已运行时直接打开网页，项目移动后需重新安装入口。
这是网页快捷入口，使用它不需要构建 `desktop/` 中的完整客户端。

## 使用流程

1. **导入材料**：点击「导入」，上传 HTML 或 ZIP。后台任务成功后，打开素材检查封面、页数和媒体。
2. **新建汇报**：在汇报素材中点击「新增汇报素材」，填写名称、选择封面和正文页面。正文按选择顺序加入，封面模板自动生成为一页「封面」。
3. **确认编排**：插入、拖动排序、隐藏或移出页面后点击「确认编排」。成功弹窗可查看最新汇报，也可返回继续编辑。
4. **播放与交付**：检查实际播放效果，再导出 HTML ZIP 或 PDF。导出采用已经保存的编排，隐藏和移出的页不进入交付物。

封面模板本身不作为页面素材入库；创建汇报后生成的「封面」属于该汇报。
公开版提供三张原创几何背景。自定义封面可放在运行目录的
`config/report-covers/cover-1.webp` 至 `cover-3.webp`，推荐 1920×1080。
已有汇报保留创建时封装的封面。
Docker 部署使用自定义封面时，需将该目录挂载到容器实际运行目录的同名子目录。

### 导入格式与边界

| 来源 | 准备方式 |
| --- | --- |
| 单个 HTML | 使用自包含文件；引用本地图片、视频、CSS 等时改用 ZIP |
| HTML ZIP | 保留入口与依赖的相对路径；明确汇报页序时提供 Manifest |
| 多页 Deck | 识别受支持的页面结构后拆分，同时保留完整汇报入口 |
| 飞书云空间文件夹 | 需包含兼容的 HTML 汇报入口，且当前账号有文件和依赖的读取权限 |
| 图片与视频 | 可上传为底层资源记录；独立页面应使用包含媒体的 HTML |

单个 HTML、独立多 HTML 页面包与完整汇报不会一律归为同一种素材。
分类、Manifest 示例、默认体积限制和错误处理见[导入接口文档](docs/MineM_IMPORT_API.md)。

HTML ZIP 是保留视频、音频和交互的主要交付格式；PDF 是静态阅读副本。
缺失必需资源或仍依赖线上运行环境时，离线导出会返回具体错误。
飞书在线文档和在线幻灯片不能直接通过文件夹入口转成 HTML 汇报，需先准备兼容的导出文件。
已验证范围与剩余限制见 [HTML 文档交付标准](docs/MineM_EXPORT_STANDARD.md)。

## 飞书链接导入

在导入弹窗选择「飞书链接」，通过「添加链接」增加输入项，一次最多提交 8 个文件夹。
提交后在任务列表查看进度、原链接和失败原因；不要将提交成功当作导入完成。

此能力需要主机安装并登录有读取权限的 `lark-cli`，以及 Python 3.10+。
本机下载服务与网页服务通过同一份 `drive-imports/` 目录交换任务。

**使用上面的本机启动命令时**，运行目录已经是 `./runtime`，在另一个终端执行：

```bash
cd minem
source .venv/bin/activate
./scripts/start_drive_import_worker.sh
```

**使用仓库默认 Docker 配置时**，先在 `docker-compose.override.yml` 中增加队列挂载，
再运行 `docker compose up -d` 应用配置：

```yaml
services:
  minem-platform:
    volumes:
      - ./runtime/drive-imports:/app/drive-imports
```

随后在主机运行 `./scripts/start_drive_import_worker.sh`。已自定义 `MINEM_DATA_DIR`
的部署应把同一主机目录挂载到实际运行目录的 `drive-imports/` 下。
主机重启后需重新启动下载服务；不要把本机登录凭据复制进镜像或提交到仓库。
具体队列、重试和查询约定见[导入接口文档](docs/MineM_IMPORT_API.md)。

## 数据与维护

| 运行方式 | 数据位置 |
| --- | --- |
| `./start.sh --data-dir ./runtime` | 项目内 `runtime/` |
| 仓库默认 Docker Compose | 项目内各数据目录，分别挂载到容器 `/app/` 下 |
| 自定义部署 | 以实际 `MINEM_DATA_DIR` 和 Compose 挂载为准 |

运行目录中，`data/` 保存数据库，`uploads/` 保存上传文件，`extracted/` 保存页面与资源，
`thumbnails/` 保存预览图，`report-exports/` 保存导出结果。
维护验证放在 `maintenance/validation/`，历史归档放在 `maintenance/history/`。
这些内容均属于本地状态，不进入公开源码。

备份时先停止服务，再备份完整运行目录或全部数据挂载目录；只备份数据库不能恢复页面和视频。
测试数据按独立验证目录清理，避免直接删除正式库的资源目录。
默认服务仅面向本机；网络部署要求见[安全策略](SECURITY.md)，源码发布边界见[开源说明](docs/OPEN_SOURCE_RELEASE.md)。

## CLI 与 Agent

CLI 调用已经运行的 MineM 服务，可由人或外部 Agent 使用。
它负责素材操作与结果查询；HTML 内容可由你自己的工具或模型生成。
本机启动器会安装 CLI，使用前激活项目虚拟环境：

```bash
source .venv/bin/activate
minem --help

# 导入一页并等待任务结果
minem page import ./page.html --name "产品介绍" --wait --output json

# 用真实页面编号替换下方示例值
minem report create --name "产品汇报" \
  --page CTRL-PAGE-001 --page CTRL-PAGE-002 --output json
```

仅使用 Docker 时，可在容器中通过 `docker compose exec minem-platform minem --help`
调用 CLI。文件导入路径必须能被执行该命令的环境访问。
支持的命令、`--confirm` 和 JSON 协议见 [CLI 能力范围](docs/MineM_CLI_能力范围.md)，
HTTP 导入协议见[接口文档](docs/MineM_IMPORT_API.md)。

## 开发与文档

网页使用 React + TypeScript，服务使用 Python + SQLite；浏览器渲染由 Chromium 提供。

| 路径 | 用途 |
| --- | --- |
| `frontend/` | 网页交互与样式 |
| `minem/`、`server.py` | 素材、导入、编排、播放与导出 |
| `templates/` | 运行模板和默认封面 |
| `scripts/` | 启动、测试和维护工具 |
| `desktop/` | 可选完整桌面客户端源码 |
| `docs/` | 产品、接口、交付与开发文档 |

安装依赖后，基础检查为：

```bash
npm run check
python3 scripts/check_repository_docs.py
python3 scripts/check_public_boundary.py
python3 scripts/version_control.py check
```

CI 还会执行隔离数据回归、浏览器产品测试和 Docker 镜像内测试。
只修改文档时无需重启正在运行的服务。

[文档索引](docs/README.md) · [贡献指南](CONTRIBUTING.md) · [问题支持](SUPPORT.md) · [更新记录](CHANGELOG.md)

## English

MineM is a local-first tool for organizing HTML pages and composing presentations.
The web app is the main interface. Import HTML or ZIP material, keep page content and
media together, arrange pages into a report, then play or export the saved result.
Each page owns its dependencies; reports keep the ordered composition and source
relationships. Resources are managed inside pages rather than through a separate module.

### Run

With Docker and Compose installed:

```bash
git clone https://github.com/Jo-Tsu/minem.git
cd minem
docker compose up -d --build
```

Open [http://127.0.0.1:8790/](http://127.0.0.1:8790/). The image includes Python,
Chromium and fonts. It starts with an empty library and does not scan host folders.
Use `docker compose down` to stop it while keeping the bind-mounted data.

Alternatively, install Python 3.10+ (3.12 recommended), a supported Node.js version
(20.19+ on Node 20, or 22.12+), and Chromium or Chrome, then run
`./start.sh --data-dir ./runtime`. The launcher installs dependencies, builds the
frontend and opens the browser. Runtime data stays under `runtime/`.

### Use

Import material, create a report with a cover and selected pages, arrange it, and
save before playback or export. A successful save offers a link to the updated report;
further changes can be saved again. HTML ZIP preserves media and interaction, while
PDF is a static reading copy. Missing required dependencies block offline delivery.

Feishu folder import accepts up to eight links per submission. It requires a logged-in
host `lark-cli` worker and a shared queue directory. For default Docker deployments,
mount `./runtime/drive-imports` at `/app/drive-imports`; the host worker uses the former.
Online documents and slides must first be exported to a compatible HTML package.
See the [setup above](#飞书链接导入), [import API](docs/MineM_IMPORT_API.md) and
[delivery standard](docs/MineM_EXPORT_STANDARD.md) for requirements and limits.

The CLI is available to external agents as well as people; run `minem --help` or
`docker compose exec minem-platform minem --help`. Back up the database and material
directories together with the service stopped. User data, private covers and machine
configuration are excluded from the public source tree.

[Documentation](docs/README.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## License

源码依据 [Apache License 2.0](LICENSE) 发布，支持个人与商业使用、修改和再分发；
分发时保留许可证与相关声明。商标与第三方素材的权利以各自条款为准。

Source code is available under [Apache License 2.0](LICENSE) for personal and
commercial use, modification and redistribution, subject to its license and notice
requirements. Trademarks and third-party content retain their respective terms.
