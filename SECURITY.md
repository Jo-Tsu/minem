# 安全策略 / Security Policy

## 支持版本 / Supported versions

安全修复面向最新发布的次版本。旧开发快照可能需要先升级，之后再获得修复。

Security fixes are provided for the latest published minor release. Older
development snapshots may be asked to upgrade before a fix is prepared.

## 报告漏洞 / Reporting a vulnerability

怀疑存在漏洞或密钥泄露时，请勿创建公开 Issue。请使用仓库 Security 页面中的
GitHub Private Vulnerability Reporting，并提供受影响版本、复现步骤、影响和建议
缓解方式。不得附带真实客户材料或凭据。

Do not open a public issue for a suspected vulnerability or leaked secret.
Use GitHub Private Vulnerability Reporting in the repository's Security tab.
Include affected versions, reproduction steps, impact, and any proposed
mitigation. Do not include real customer materials or credentials.

维护者会尽快确认完整报告，以私密方式协调验证与修复，并在用户需要采取行动时
发布安全公告。

The maintainers will acknowledge a complete report as soon as practical,
coordinate validation and remediation privately, and publish an advisory when
users need to take action.

## 部署边界 / Deployment boundary

MineM 默认仅将开发服务绑定到 localhost。将其暴露到网络的运营者负责配置身份
认证、TLS、访问控制、备份和数据保留策略。内部 Agent API 只有在明确配置后才
会启用。

MineM binds its development services to localhost by default. Operators who
expose it to a network are responsible for authentication, TLS, access
control, backups, and data-retention policy. The internal Agent API remains
disabled unless explicitly configured.
