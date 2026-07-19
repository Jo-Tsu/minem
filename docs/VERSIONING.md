# MineM 版本与发布管理

## 单一版本来源

`product-version.json` 是 MineM 的唯一产品版本来源。当前发布号始终从该文件读取，不在文档中写死；其版本会同步到：

- 根目录 `package.json`：网页端和统一构建入口。
- `desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/src-tauri/tauri.conf.json`：macOS 客户端和安装包。
- Docker 镜像构建参数与标签。
- 服务端 `GET /api/version`：便于网页端、客户端、运维和诊断读取。

用户数据、素材、SQLite、缩略图和导入历史不属于发布版本；升级应用包不得覆盖这些数据。

## 版本号规则

采用 `MAJOR.MINOR.PATCH`：

| 变更 | 升级 | 示例 |
| --- | --- | --- |
| 不兼容的数据、API、导入或素材语义调整 | `MAJOR` | 页面/汇报模型无法向后兼容 |
| 新增用户可见且兼容的功能 | `MINOR` | 新增桌面快捷浮窗、案例能力 |
| 缺陷修复、性能、样式、测试与文档调整 | `PATCH` | 修复预览、去重、链接、尺寸问题 |

预发布使用 `-alpha.N`、`-beta.N`、`-rc.N` 后缀；`channel` 必须标识 `internal`、`beta` 或 `stable`。

## 每次更新流程

1. 先更新 PRD、技术文档与测试计划，明确影响范围和兼容性。
2. 选择版本级别，并执行版本升级命令。
3. 在 `CHANGELOG.md` 写入用户可感知的新能力、修复与迁移说明。
4. 实现并运行前端检查、核心数据/点击测试、桌面端编译；涉及 Docker 或客户端时分别构建。
5. 执行版本一致性检查。检查不通过不得发布。
6. 提交代码后建立 Git 标签 `vX.Y.Z`；发布说明引用同版本的 CHANGELOG 段落。

## 命令

```bash
# 查看当前版本与发布信息
python3 scripts/version_control.py show

# 验证所有版本入口与 CHANGELOG 是否一致
python3 scripts/version_control.py check

# 只在确认发布级别后执行；会同步版本入口并生成 CHANGELOG 草稿
python3 scripts/version_control.py bump patch --headline "修复预览链接"
python3 scripts/version_control.py bump minor --headline "新增案例工作流"
python3 scripts/version_control.py bump major --headline "素材模型升级"
```

`bump` 只修改代码仓库内的版本元数据，不修改数据库、用户素材或运行数据。执行后仍需人工完善 CHANGELOG 内容并完成测试。

## 发布矩阵

| 交付物 | 版本来源 | 发布命令 |
| --- | --- | --- |
| 网页端 / 本机服务 | `product-version.json` | `python3 server.py` 或 Docker 构建 |
| Docker | `MINEM_VERSION` 构建参数 | `docker compose build` |
| macOS 客户端 | 同步后的 Tauri / package 元数据 | `npm run desktop:build` |

客户端或 Docker 更新仅替换程序和运行时；持久化目录保持原样。每次故障诊断先记录 `/api/version`、容器标签或 `.dmg` 文件名中的版本号。
