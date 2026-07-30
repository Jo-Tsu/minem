# MineM 开源说明 / Open-Source Guide

当前版本 / Current version：`0.5.0-alpha.28`

许可证 / License：[Apache License 2.0](../LICENSE)

公开仓库 / Public repository：[github.com/Jo-Tsu/minem](https://github.com/Jo-Tsu/minem)

MineM 的 Web 平台、Python 服务、CLI、Agent Skills、macOS 客户端和创作助手均以
源码形式公开。个人、团队和企业可以免费使用、修改、私有部署、商业使用和再发布，
不需要 MineM 账号、许可证密钥、付费订阅或额外授权。

MineM publishes the Web platform, Python service, CLI, Agent Skills, macOS
client, and Creator Assistant as source code. Individuals, teams, and
companies may use, modify, self-host, commercialize, and redistribute the
software without a MineM account, license key, subscription, or separate
permission.

## 1. 开放的能力 / What is open

| 范围 / Area | 源码位置 / Source | 说明 / Description |
| --- | --- | --- |
| Web 管理平台 | `frontend/` | React + TypeScript 素材库、预览、搜索、编排、导入与导出界面 |
| 本地服务 | `server.py`, `minem/` | Python HTTP API、SQLite 数据模型、导入、预览、版本与数据治理 |
| CLI | `minem/cli/` | 面向人和 AI Agent 的稳定命令与 `minem.cli/v1` JSON 输出 |
| Agent Skills | `skills/` | 页面生成、汇报工作流和案例素材的可复用执行说明 |
| macOS 客户端 | `desktop/` | Tauri + Rust 客户端、浏览窗口、创作助手、快捷浮窗和打包脚本 |
| 页面运行时 | `templates/` | 汇报与页面的统一画布、翻页、全屏、刷新和链接能力 |
| 工程工具 | `scripts/` | 测试、版本校验、公开边界检查和数据治理脚本 |
| 文档 | `docs/` | PRD、技术设计、设计规范、测试计划和用户指南 |

The public repository contains the complete source needed to run the platform,
invoke it through the CLI, use it from an AI coding agent, and build the macOS
client. The desktop application is not a closed wrapper around a private
service: its Rust host, WebView UI, native bridge, navigation, clipboard
integration, local runtime launcher, quick-command window, tests, icons, and
packaging scripts are included.

## 2. 许可证授予的自由 / License freedoms

Apache-2.0 允许：

- 个人与商业使用。Personal and commercial use.
- 修改源码并创建衍生产品。Modification and derivative works.
- 私有部署，无需公开自己的业务数据或私有改动。Private deployment without
  publishing business data or private modifications.
- 复制和再发布源码或二进制版本。Source and binary redistribution.
- 在许可证范围内使用贡献者授予的专利许可。Use of the patent grant provided
  by contributors under the license.

再发布时需要保留适用的许可证、版权和 NOTICE 声明，并标注自己做出的重大修改。
软件按“现状”提供，不附带担保。完整法律条款以 [LICENSE](../LICENSE) 和
[NOTICE](../NOTICE) 为准。

When redistributing MineM, retain the applicable license, copyright, and NOTICE
text, and identify significant changes you made. The software is provided
without warranty. [LICENSE](../LICENSE) and [NOTICE](../NOTICE) are the
authoritative legal terms.

## 3. 三种运行方式 / Three ways to run

### 轻量本地启动 / Lightweight local startup

```bash
git clone https://github.com/Jo-Tsu/minem.git
cd minem
./start.sh
```

该方式使用本机 Python 与 Node.js，不要求 Docker。启动器会创建隔离环境、安装依赖、
构建前端并启动 `http://127.0.0.1:8790/`。

This mode uses the local Python and Node.js runtimes and does not require
Docker. The launcher creates an isolated environment, installs dependencies,
builds the frontend, and starts `http://127.0.0.1:8790/`.

### Docker

```bash
docker compose up -d --build
```

默认容器从空素材库启动，不扫描主机目录。外部来源必须通过本地
`docker-compose.override.yml` 显式只读挂载。

The default container starts with an empty library and scans no host
directory. External sources must be mounted explicitly and read-only through a
local `docker-compose.override.yml`.

### macOS 客户端源码构建 / Build the macOS client from source

要求 / Requirements:

- macOS 13 或更新版本。macOS 13 or later.
- Apple Silicon Mac。Apple Silicon Mac.
- Xcode Command Line Tools 与已接受的 Xcode 许可。Xcode Command Line
  Tools with the Xcode license accepted.
- Python 3.12、Node.js `^20.19.0` 或 `>=22.12.0`、Rust stable。

```bash
npm ci
npm --prefix desktop ci
npm run desktop:build
```

构建过程会先生成当前平台的本地服务 sidecar，再运行客户端测试并打包应用。
生成的 `.app`、DMG、sidecar 和构建缓存位于忽略目录，不提交到源码仓库。GitHub
Release 可以单独发布经过同一提交构建和签名的安装包。

The build creates the local service sidecar for the current platform, runs the
desktop tests, and packages the application. Generated app bundles, DMGs,
sidecars, and build caches are intentionally ignored. A GitHub Release may
publish signed installers built from the same source commit.

## 4. AI 与 CLI 集成 / AI and CLI integration

MineM 不绑定模型供应商。能够执行 Shell 命令的 Codex、Claude Code、Gemini CLI
或其他 Agent，可以调用同一套 CLI：

```bash
python3 -m pip install --no-deps -e .
minem page build --spec ./page.json --file ./page.html \
  --publish --wait --output json
minem report create --name "Customer review" \
  --page CTRL-PAGE-001 --page CTRL-PAGE-002 --output json
```

`skills/` 提供固定的业务规则和执行流程，macOS 创作助手提供可直接粘贴到 AI 对话
中的短模板。模型负责理解和生成内容，MineM 负责可验证的导入、分类、编号、版本、
预览、编排与结果链接。

MineM is model-agnostic. Any agent that can run shell commands can use the same
CLI. The `skills/` directory carries stable workflow rules, while the macOS
Creator Assistant provides short prompts that can be pasted into an AI
conversation. The model interprets and generates content; MineM performs the
verifiable import, classification, ID, version, preview, arrangement, and
result-link operations.

## 5. 不进入 Git 的内容 / What is not committed

开源客户端不等于公开使用者的数据。以下内容不会进入源码仓库：

- `data/`、SQLite 数据库、服务锁和数据库备份。
- `uploads/`、`extracted/`、`thumbnails/`、`report-exports/`、`artifacts/`
  和生成的 `public/`。
- 客户汇报、页面、案例、图片、Logo、视频、GIF、会议转写和演讲稿。
- `.env`、令牌、凭据、本机绝对路径和私有 Docker 覆盖配置。
- 模型权重、生成音频、日志和可选 TTS 运行数据。
- Node、Python、Rust 构建缓存，以及 macOS `.app`、DMG 和 sidecar 二进制。

The repository excludes runtime databases, imported or generated material,
customer content, credentials, machine-local configuration, model weights,
audio, logs, installers, sidecars, and build caches. These exclusions protect
user data and keep the source repository reproducible; they do not hide product
functionality.

具体纳入与排除路径由 [public-release.json](../public-release.json) 管理，并由
`scripts/check_public_boundary.py` 自动检查。

The exact include and exclude paths are defined in
[public-release.json](../public-release.json) and validated by
`scripts/check_public_boundary.py`.

## 6. 发布与质量门禁 / Release and quality gates

每个公开提交至少执行：

```bash
npm run check
python3 -m compileall -q minem scripts server.py
python3 scripts/run_core_tests.py
npm --prefix desktop run test:release
python3 scripts/check_public_boundary.py
python3 scripts/check_repository_docs.py
python3 scripts/version_control.py check
git diff --check
```

CI 还会验证真实 CLI 工作流，包括创建页面、生成案例、组装汇报、插入或替换页面，
以及正式预览链接。发布前同时检查：

- 版本号、变更记录、Python、Node、Tauri 与 Rust 包清单一致。
- 默认启动使用空素材库，不隐式读取本机目录。
- 无用户主目录绝对路径、明显密钥、数据库或客户素材。
- macOS 客户端源码可构建，创作助手与原生运行时测试通过。
- README、用户指南、PRD、技术文档和测试计划与当前行为一致。

CI also exercises real CLI workflows: page creation, case generation, report
assembly, page insertion or replacement, and final preview URLs. Version
manifests, source boundaries, privacy defaults, desktop buildability, and
documentation consistency are release gates.

## 7. 参与项目 / Participate

- 使用问题和建议：提交 [Issue](https://github.com/Jo-Tsu/minem/issues)。
- 代码贡献：阅读 [CONTRIBUTING.md](../CONTRIBUTING.md) 后提交 Pull Request。
- 安全问题：按 [SECURITY.md](../SECURITY.md) 私下报告。
- 使用方法：阅读 [USER_GUIDE.md](USER_GUIDE.md)。

- Questions and proposals: open an
  [Issue](https://github.com/Jo-Tsu/minem/issues).
- Code contributions: follow [CONTRIBUTING.md](../CONTRIBUTING.md) and open a
  pull request.
- Security reports: use the private process in [SECURITY.md](../SECURITY.md).
- Product usage: start with [USER_GUIDE.md](USER_GUIDE.md).
