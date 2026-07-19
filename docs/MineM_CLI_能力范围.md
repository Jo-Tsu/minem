# MineM CLI v1 产品与技术规范

版本：CLI Schema v1 · 2026-07-19
状态：已批准实施

## 1. 产品定位

MineM CLI 是平台面向开发者、自动化脚本和 AI Agent 的正式操作入口。它不是 HTTP API
的薄包装，也不绑定任何一家模型。人可以在终端中使用，AI Agent 可以通过相同命令和
稳定 JSON 契约创建、查询、编排和交付素材。

能力分为两层：

1. **确定性素材操作**：导入、分类、命名、查询、版本、汇报编排、导出和预览，由
   MineM CLI 与平台负责，并且必须可重复验证。
2. **内容生成**：模型理解需求并生成 HTML、Markdown 或结构化页面描述。模型可以在
   MineM 外部运行，再把结果交给 CLI；只有真正配置模型提供方后，命令才能使用
   `generate` 名称。

因此，简单包装 Markdown 的行为只能叫 `case import`，不能宣传成 AI 提炼。

## 2. 设计原则

- 安装后直接使用 `minem`，不要求用户输入 `python3 scripts/minem_cli.py`。
- 命令采用 `minem <resource> <action>`，资源名和动作在全平台保持一致。
- 素材参数接受内部 ID、`RPT-*` / `CTRL-*` / `RES-*` 编号或 MineM 链接。
- 默认输出适合人阅读；`--output json` 提供稳定的机器输出。
- stdout 只输出最终结果；进度、提示和警告写入 stderr。
- 写操作支持 `--dry-run`；高影响操作必须使用 `--confirm` 或 `--yes`。
- 异步操作统一支持 `--wait/--no-wait` 和 `--timeout`。
- Agent 可传入稳定的 `--request-id`，用于日志关联和结果追踪；当前版本不虚构服务端
  幂等保证，重复写入仍由调用方在重试前查询任务或素材结果。
- 不依赖隐式工作区；服务地址来自显式参数、环境变量、配置或桌面运行时清单。
- 所有失败使用稳定错误码和非零退出码。

## 3. 正式命令树

```text
minem version
minem status
minem doctor
minem config get|set|list|unset
minem completion bash|zsh|fish

minem asset list|get|search|versions|lineage|open|rename|delete
minem import report|page <source>
minem page import
minem report create|get|pages|open|export
minem report page add|replace|move|hide|show|remove
minem case import
minem task list|get|wait
minem agent capabilities|schema
```

`page create`、`case create`、`report page --add/--replace` 和 `--json` 作为旧版兼容入口保留
一个大版本，并在 stderr 输出迁移提示。

## 4. 典型工作流

### 4.1 导入与查询

```bash
minem import report ./customer-report.zip --name "客户方案" --wait
minem page import ./case-page.html --name "客户案例：交付成果" --wait
minem asset list --type page --limit 30
minem asset search "客户案例" --output json
minem asset get CTRL-PAGE-001
minem asset open CTRL-PAGE-001
```

### 4.2 创建和修改汇报

```bash
minem report create --name "2026 制造业方案" \
  --page CTRL-PAGE-001 --page CTRL-PAGE-002

minem report page add RPT-20260719-001 \
  --page CTRL-PAGE-003 --after CTRL-PAGE-001 --dry-run

minem report page add RPT-20260719-001 \
  --page CTRL-PAGE-003 --after CTRL-PAGE-001 --confirm

minem report page replace RPT-20260719-001 \
  --page CTRL-PAGE-001 --with CTRL-PAGE-004 --confirm

minem report page hide RPT-20260719-001 --page CTRL-PAGE-003 --confirm
minem report page remove RPT-20260719-001 --page CTRL-PAGE-003 --confirm
```

隐藏和移出只改变当前汇报，不删除页面素材。替换页面也不删除旧页面或历史版本。

### 4.3 AI Agent 调用

```bash
minem agent capabilities --output json
minem agent schema report.page.add --output json

# 模型先生成单页 HTML，再调用确定性素材能力
minem page import ./generated-page.html \
  --name "客户价值" --wait --output json --no-input

minem report page add RPT-20260719-001 \
  --page CTRL-PAGE-009 --after CTRL-PAGE-004 \
  --confirm --output json --no-input
```

Agent 不应解析人类表格输出，也不能依赖标题匹配唯一素材。写操作应保存返回的
`requestId`、素材 `id` 和 `code`；发生网络中断时，应先按任务或素材查询结果，再决定
是否重试，避免重复创建。

## 5. 机器输出契约

```json
{
  "schemaVersion": "minem.cli/v1",
  "ok": true,
  "command": "report.page.add",
  "requestId": "req_01J...",
  "resource": {
    "id": "created-report-...",
    "code": "RPT-20260719-001",
    "type": "report",
    "title": "2026 制造业方案"
  },
  "data": {},
  "links": {
    "preview": "http://127.0.0.1:8790/reports/.../index.html"
  },
  "warnings": [],
  "meta": {
    "durationMs": 84,
    "serverUrl": "http://127.0.0.1:8790"
  },
  "error": null
}
```

错误时 `ok=false`，`error` 至少包含 `code`、`message` 和可选 `details`。稳定错误码包括：

- `CONNECTION_FAILED`
- `INVALID_ARGUMENT`
- `NOT_FOUND`
- `AMBIGUOUS_REFERENCE`
- `TYPE_MISMATCH`
- `CONFIRMATION_REQUIRED`
- `IMPORT_FAILED`
- `TASK_TIMEOUT`
- `SERVER_ERROR`
- `AI_PROVIDER_NOT_CONFIGURED`

退出码：成功 `0`、一般失败 `1`、参数错误 `2`、连接失败 `3`、需要确认 `4`。

## 6. 输出、配置与安全

所有叶子命令支持：

```text
--output table|json|jsonl|yaml
--json                         # --output json 的兼容别名
--quiet
--base-url URL
--timeout SECONDS
--no-input
```

配置优先级：命令参数 > `MINEM_BASE_URL` > 用户配置 > macOS 客户端运行时清单 >
`http://127.0.0.1:8790`。配置文件不存储模型密钥；密钥只能来自系统钥匙串或环境变量。

`doctor` 必须检查 CLI 版本、服务连接、服务版本、数据目录可用性和 API 兼容性，但不能
修改数据。`delete`、合并、正式编排等动作必须支持预演和显式确认。

## 7. 实现结构

```text
minem/cli/
  client.py       HTTP、上传、下载、超时和错误映射
  config.py       配置与桌面运行时发现
  contracts.py    输出 Schema、错误码和退出码
  resolver.py     ID、编号和链接解析
  commands.py     领域命令
  parser.py       命令树和兼容参数
  main.py         执行入口与输出
scripts/minem_cli.py  旧入口兼容层
```

CLI 调用现有 MineM HTTP API，不建立第二套数据库或素材目录。复杂业务逻辑属于后端领域
服务，CLI 只负责参数解析、引用解析、用户确认和稳定协议转换。

## 8. 验收要求

隔离环境测试必须真实验证：

1. `minem` 安装入口、`--help`、`version`、`status` 和 `doctor`；
2. 人类表格与 JSON 输出互不污染；全局输出参数放在命令前后都可解析；
3. 使用编号、内部 ID 和链接能解析到同一素材；
4. 页面与案例导入返回最终编号、标题和有效预览；
5. 汇报创建、插入、替换、移动、隐藏、显示和移出正确；
6. `--dry-run` 不写数据，缺少确认不会写数据；
7. 正式汇报链接展示已确认编排，原页面仍然存在；
8. 错误 JSON、错误码和进程退出码稳定；
9. README 展示的每条命令均由自动化测试覆盖。

GitHub CI 使用临时数据目录执行完整链路，不写入用户素材库。
