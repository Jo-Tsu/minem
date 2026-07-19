# MineM 公开版本边界 / Open-Source Release Boundary

状态 / Status：已公开发布 / Published
许可证 / License：Apache-2.0
版权 / Copyright：MineM contributors
首个公开版本目标 / First public release target：v0.4.0

## 1. 目标 / Goal

发布一个可复现的 MineM 源码仓库，任何人都可以检查、运行、修改和再分发，同时
不暴露用户数据、客户材料、私有路径、模型权重或生成的二进制文件。

Publish a reproducible MineM source repository that anyone can inspect, run,
modify, and redistribute without exposing user data, customer materials,
private paths, model weights, or generated binaries.

公开仓库采用干净的源码快照，不继承当前内部 Git 历史，确保已删除的实验代码和
下线模块无法通过公开历史恢复。

The public repository is a clean source snapshot. It does not inherit the
current internal Git history, so removed experiments and retired modules do
not remain accessible through public history.

## 2. 纳入的源码 / Included source

- `frontend/` 下的 React 与 TypeScript 源码。React and TypeScript source
  under `frontend/`.
- `server.py` 与 `minem/` 下的 Python 服务及领域模块。Python service and
  domain modules under `server.py` and `minem/`.
- `scripts/` 下安全的维护、校验、版本和 CLI 脚本。Safe maintenance,
  validation, version, and CLI scripts under `scripts/`.
- `desktop/` 下的 macOS 客户端源码与打包脚本。macOS client source and
  packaging scripts under `desktop/`.
- `local-tts/` 下的可选本地语音服务源码。Optional local speech service
  source under `local-tts/`.
- `templates/` 下的运行时 HTML 模板。Runtime HTML templates under
  `templates/`.
- 产品、技术、设计、测试、安全和贡献文档。Product, technical, design,
  testing, security, and contribution documents.
- 可复现的包清单、锁文件、Docker 文件和示例配置。Reproducible package
  manifests, lockfiles, Docker files, and example configuration.

## 3. 排除的内容 / Excluded content

以下内容不得进入公开源码仓库 / The following never enter the public source
repository:

- `data/`、SQLite 文件、服务锁和数据库备份。`data/`, SQLite files, server
  locks, and database backups.
- `uploads/`、`extracted/`、`thumbnails/`、`report-exports/` 和 `artifacts/`。
- `import-sources.json`、本地 Docker 覆盖配置、凭据、令牌和机器专属环境文件。
  `import-sources.json`, local Docker overrides, credentials, tokens, and
  machine-specific environment files.
- 客户汇报、案例材料、Logo、导入资源、会议转写、演讲稿和生成的预览。
  Customer reports, case materials, logos, imported resources, meeting
  transcripts, presenter scripts, and generated previews.
- `local-tts/models/`、AI 或语音模型权重、生成的音频和日志。AI or speech
  model weights, generated audio, and logs.
- macOS sidecar 二进制、`.app`、DMG、构建缓存及 Rust 或 Node 构建产物。
  macOS sidecar binaries, app bundles, DMG files, build caches, and Rust or
  Node build output.
- `public/` 下生成的 Vite 生产文件；发行构建必须从 `frontend/` 重新生成。
  Generated Vite production files under `public/`; release builds recreate
  them from `frontend/`.
- 披露本地路径或非公开运行环境的内部日期审计报告。Internal dated audit
  reports that disclose local paths or non-public operating context.

## 4. 商标与示例 / Trademark and examples

Apache-2.0 授权代码，但不授予 MineM 名称、产品标识或 Logo 的使用权。公开示例
必须使用合成内容、自有素材或许可兼容的素材，不得将客户或雇主材料作为示例包。

Apache-2.0 licenses the code but does not grant rights to the MineM name,
product identity, or logos. Public examples must use synthetic content and
self-owned or permissively licensed assets. Customer or employer material
must not be used as a demonstration package.

## 5. 依赖与模型策略 / Dependency and model policy

- 直接依赖许可证记录在 `THIRD_PARTY_NOTICES.md`。Direct dependency
  licenses are recorded in `THIRD_PARTY_NOTICES.md`.
- CI 和二进制发布任务必须为传递依赖生成完整的软件物料清单。CI and binary
  release jobs must generate a complete software bill of materials.
- 模型权重必须单独下载，不得镜像到 MineM 仓库或源码发行包。Model weights
  are downloaded separately and are never mirrored in the MineM repository.
- 二进制与容器发行必须满足实际捆绑依赖的许可证，包括可选的 LGPL-3.0
  `edge-tts`。Binary and container releases must satisfy the licenses of all
  bundled dependencies, including the optional LGPL-3.0 `edge-tts` package.

## 6. 发布方式 / Publication model

1. 准备并测试内部工作目录。Prepare and test the internal working tree.
2. 仅将批准范围内的源码导出到新目录。Export only the approved source boundary
   into a new directory.
3. 对导出目录运行 `scripts/check_public_boundary.py`。Run the public boundary
   checker against the export.
4. 初始化新的 Git 仓库并创建单个干净的初始提交。Initialize a new Git
   repository with one clean initial commit.
5. 使用 GitHub Desktop 添加并发布为公开仓库。Add it to GitHub Desktop and
   publish it as a public repository.
6. CI 通过后将测试提交标记为 `v0.4.0`。Tag the tested commit as `v0.4.0`
   after CI succeeds.

## 7. 必须通过的门禁 / Required gates

- Apache `LICENSE`、`NOTICE`、安全和贡献文档齐全。Required legal, security,
  and contribution documents exist.
- GitHub Issue Forms、Pull Request 模板和 `SUPPORT.md` 齐全。GitHub issue
  forms, the pull request template, and `SUPPORT.md` exist.
- 不包含禁止的运行目录或私有配置。No forbidden runtime path or private
  configuration is present.
- 不包含用户主目录绝对路径或明显密钥特征。No absolute user-home path or
  obvious secret marker is present.
- 前端、Python、版本、公开边界和 Docker 检查通过。Frontend, Python,
  version, boundary, and Docker checks pass.
- 默认安装以空素材库启动，不挂载私有来源。The default install starts with an
  empty library and no private source mount.
- 公开 README 同时说明轻量本地启动和可选 Docker 启动。The public README
  explains both lightweight local startup and optional Docker.
