# 参与 MineM / Contributing to MineM

感谢你帮助改进 MineM。Thank you for helping improve MineM.

## 提交修改前 / Before opening a change

1. 先搜索已有 Issue 和 Pull Request。Search existing issues and pull requests.
2. 行为、数据模型或大型 UI 修改应先创建 Issue。Open an issue before
   behavior, data-model, or large UI changes.
3. 不得附带客户汇报、导入素材、数据库、缩略图、模型权重、凭据或私有源码
   路径。Never attach customer reports, imported assets, databases,
   thumbnails, model weights, credentials, or private source paths.

## 开发检查 / Development checks

运行与修改相关的检查。Run the checks relevant to your change:

```bash
npm ci
npm run check
python3 -m pip install -r requirements.txt
python3 -m compileall -q minem scripts server.py
python3 scripts/test_html_dependencies.py
python3 scripts/test_report_canvas_normalization.py
python3 scripts/version_control.py check
python3 scripts/check_public_boundary.py
python3 scripts/check_repository_docs.py
```

需要样例数据的测试必须在临时目录中创建数据。不得提交 `data/`、`uploads/`、
`extracted/`、`thumbnails/` 或 `artifacts/` 中的任何内容。

Tests that need sample data must create it in a temporary directory. Do not
commit anything from `data/`, `uploads/`, `extracted/`, `thumbnails/`, or
`artifacts/`.

## Pull Request 要求 / Pull requests

- 修改应保持聚焦，并记录用户可见的行为。Keep changes focused and document
  user-visible behavior.
- 修复缺陷或修改共享行为时，应新增或更新测试。Add or update tests for bug
  fixes and shared behavior.
- 实现新的产品能力前，先更新 PRD 和技术文档。Update the PRD and technical
  documentation before implementing a new product capability.
- 除非提案包含迁移方案，否则应保持现有用户数据兼容。Preserve compatibility
  with existing user data unless a migration is part of the proposal.
- 提交贡献即表示同意依据 Apache License, Version 2.0 授权该贡献。By
  submitting a contribution, you agree that it is licensed under the Apache
  License, Version 2.0.

提交前还应阅读 [社区行为准则](CODE_OF_CONDUCT.md)、[支持说明](SUPPORT.md)和
[安全策略](SECURITY.md)。Before contributing, also read the
[Code of Conduct](CODE_OF_CONDUCT.md), [Support policy](SUPPORT.md), and
[Security policy](SECURITY.md).
