## 修改说明 / Summary

<!-- 说明改了什么以及为什么。Describe what changed and why. -->

## 关联问题 / Related issue

<!-- 例如 / Example: Closes #123 -->

## 验证方式 / Verification

<!-- 列出实际运行的命令和人工检查。List commands and manual checks performed. -->

## 界面变化 / UI changes

<!-- 有界面变化时提供脱敏截图；否则填写 N/A。Attach sanitized screenshots or write N/A. -->

## 检查清单 / Checklist

- [ ] 修改范围聚焦，没有无关重构。The change is focused and contains no unrelated refactor.
- [ ] 已新增或更新相关测试。Relevant tests were added or updated.
- [ ] 用户可见行为已同步到 PRD 和技术文档。User-visible behavior is reflected in the PRD and technical documentation.
- [ ] 已考虑现有数据兼容或提供迁移方案。Existing data remains compatible or a migration is included.
- [ ] 未提交用户数据、客户材料、模型、凭据、构建物或私人路径。No user data, customer material, models, credentials, build output, or private paths are included.
- [ ] `python3 scripts/check_public_boundary.py` 通过。The public-boundary check passes.
- [ ] `python3 scripts/check_repository_docs.py` 通过。The repository documentation check passes.
