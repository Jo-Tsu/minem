# GitHub 发布检查清单 / GitHub Release Checklist

## 1. 仓库文件 / Repository files

- [ ] 根目录包含 `README.md`、`LICENSE`、`CONTRIBUTING.md`、
      `CODE_OF_CONDUCT.md`、`SECURITY.md` 和 `SUPPORT.md`。
- [ ] `.github/ISSUE_TEMPLATE/` 中的 Issue Forms 可被 GitHub 识别。
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` 存在并位于默认分支。
- [ ] `python3 scripts/check_repository_docs.py` 通过。
- [ ] `python3 scripts/check_public_boundary.py --strict-tree` 在干净公开快照中通过。

- [ ] The repository root contains `README.md`, `LICENSE`, `CONTRIBUTING.md`,
      `CODE_OF_CONDUCT.md`, `SECURITY.md`, and `SUPPORT.md`.
- [ ] GitHub recognizes the issue forms in `.github/ISSUE_TEMPLATE/`.
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` exists on the default branch.
- [ ] Both repository documentation and strict public-boundary checks pass.

## 2. GitHub 设置 / GitHub settings

- [ ] 仓库描述、主页、Topics 和社交预览不包含内部或客户信息。
- [ ] 默认分支为 `main`，并启用 Pull Request 与分支保护。
- [ ] 启用 Dependabot alerts、secret scanning、push protection 和 code scanning。
- [ ] 启用 Private Vulnerability Reporting。
- [ ] Actions 日志、缓存和构建产物不包含运行数据库或导入材料。

- [ ] Repository description, homepage, topics, and social preview contain no
      internal or customer information.
- [ ] `main` is the default branch and pull-request protection is enabled.
- [ ] Dependabot alerts, secret scanning, push protection, and code scanning
      are enabled.
- [ ] Private Vulnerability Reporting is enabled.
- [ ] Actions logs, caches, and artifacts contain no runtime databases or
      imported materials.

## 3. 发布内容 / Release contents

- [ ] 从批准的边界生成新的干净源码快照，不公开内部 Git 历史。
- [ ] 默认安装使用空素材库，不挂载任何本机私有素材源。
- [ ] 发布版本、变更记录、包清单和 Git tag 一致。
- [ ] 二进制或容器发行包含与实际依赖一致的 SBOM 和第三方许可证。
- [ ] 发布页面不附带模型权重、演讲内容、客户素材或测试数据库。

- [ ] Create a clean source snapshot from the approved boundary without
      publishing the internal Git history.
- [ ] The default installation starts with an empty library and no private
      source mount.
- [ ] Release version, changelog, package manifests, and Git tag agree.
- [ ] Binary or container releases include an accurate SBOM and third-party
      license set.
- [ ] Releases contain no model weights, presenter content, customer materials,
      or test databases.

## 4. 官方参考 / Official references

- [GitHub community profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
- [Issue and pull request templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates)
- [Repository security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)
