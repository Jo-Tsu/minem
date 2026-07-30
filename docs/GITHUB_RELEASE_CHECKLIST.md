# GitHub 发布检查清单 / GitHub Release Checklist

本清单用于每次公开推送和正式版本发布。源代码提交与二进制 Release 分开检查。

Use this checklist for every public push and tagged release. Source commits and
binary release artifacts are checked separately.

## 1. 源码范围 / Source boundary

- [ ] `public-release.json` 包含 `frontend`、`minem`、`desktop`、`skills`、
      `templates`、`scripts` 和 `docs`。
- [ ] Web、服务端、CLI、Agent Skills、macOS 客户端和创作助手源码完整。
- [ ] `data/`、`uploads/`、`extracted/`、`thumbnails/`、`report-exports/`、
      `artifacts/` 和生成的 `public/` 未提交。
- [ ] SQLite、客户素材、会议转写、演讲稿、模型、音频和日志未提交。
- [ ] `.app`、DMG、sidecar、`node_modules`、Rust target 和构建缓存未提交。
- [ ] `.env`、令牌、凭据、本机绝对路径和私有覆盖配置未提交。
- [ ] `python3 scripts/check_public_boundary.py` 通过。

- [ ] The Web app, backend, CLI, Agent Skills, macOS client, and Creator
      Assistant sources are complete.
- [ ] Runtime data, customer material, credentials, models, installers,
      sidecars, and build caches are absent.
- [ ] The public-boundary checker passes.

## 2. 文档与许可 / Documentation and licensing

- [ ] `README.md` 中英文介绍当前能力、启动方式、客户端构建和 AI 调用方式。
- [ ] `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 完整。
- [ ] `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md` 和 `SUPPORT.md`
      可从 README 或文档索引访问。
- [ ] `docs/USER_GUIDE.md` 从用户角度说明客户端、创作助手、汇报和页面工作流。
- [ ] PRD、技术文档、设计规范和测试计划与当前产品一致。
- [ ] `python3 scripts/check_repository_docs.py` 通过。

- [ ] The bilingual README explains current capabilities, startup, desktop
      builds, and AI integration.
- [ ] Legal, contribution, security, support, user, product, technical, and
      testing documents are current and linked.

## 3. 版本与测试 / Version and tests

- [ ] `product-version.json`、`package.json`、`pyproject.toml`、
      `desktop/package.json`、Tauri 和 Cargo 版本一致。
- [ ] `CHANGELOG.md` 顶部版本准确、日期正确且没有重复版本标题。
- [ ] `python3 scripts/version_control.py check` 通过。
- [ ] `npm run check` 通过。
- [ ] `python3 -m compileall -q minem scripts server.py` 通过。
- [ ] `python3 scripts/run_core_tests.py` 通过。
- [ ] `npm --prefix desktop run test:release` 通过。
- [ ] `git diff --check` 通过。

- [ ] Product, Node, Python, Tauri, and Cargo versions agree.
- [ ] Frontend, Python, core workflow, desktop runtime, and formatting checks
      pass.

## 4. GitHub 仓库 / GitHub repository

- [ ] 仓库为 Public，描述、Topics、主页和社交预览不含内部或客户信息。
- [ ] 默认分支为 `main`，日常改动通过功能分支和 Pull Request 合并。
- [ ] CI 与 CodeQL 工作流启用并通过。
- [ ] Dependabot、secret scanning、push protection 和 private vulnerability
      reporting 已启用。
- [ ] Issue Forms 与 Pull Request 模板可被 GitHub 识别。
- [ ] 提交说明能够概括产品行为变化，未提交无关本机文件。

- [ ] The repository is public and its metadata contains no private context.
- [ ] CI, CodeQL, dependency, secret, vulnerability, issue, and pull-request
      settings are enabled as appropriate.

## 5. macOS 二进制发布 / macOS binary release

仅在发布预构建客户端时执行本节。Skip this section for source-only pushes.

- [ ] 安装包由准备发布的同一 Git commit 构建。
- [ ] 构建前客户端源码测试与 Rust 运行时测试通过。
- [ ] `.app` 已签名；对外分发时完成 notarization。
- [ ] DMG 在干净 macOS 用户环境中能够安装、启动并连接本地平台。
- [ ] 创作助手可拖动、复制指令、唤起平台并打开真实链接。
- [ ] Release 附带版本说明、SHA-256 校验值和已知限制。
- [ ] 安装包不含用户数据库、导入素材、演讲稿、模型或开发机路径。

- [ ] The installer is built from the tagged commit, tested, signed, and
      notarized when distributed publicly.
- [ ] The release includes checksums and contains no user data, imported
      material, presenter content, models, or developer-machine paths.
