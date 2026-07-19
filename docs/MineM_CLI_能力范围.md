# MineM CLI 首版能力定义

## 产品目标

把 MineM 现有的“素材工作台 + 汇报生成流程”开放给 Agent 调用。首版只做以下四件事：

1. 导入外部材料；
2. 创建和修改汇报材料；
3. 创建页面素材；
4. 将外部文档转成案例素材。

素材检索、故事线、演讲台、资源治理等能力可以保留在产品内，但不作为 CLI 首版主能力。

CLI 是 MineM 面向 AI Agent 的正式产品接口，不绑定具体模型。Codex、Claude Code、
Gemini CLI 或其他能够执行 Shell 命令并解析 JSON 的 Agent，都可以使用同一套命令完成
素材创建和管理。模型负责理解意图、提炼内容和生成页面，MineM 负责素材分类、持久化、
编号、版本、编排、预览与来源追踪。

## 命令总览

```text
python3 scripts/minem_cli.py import ...  # 导入外部材料
python3 scripts/minem_cli.py report ...  # 创建、修改汇报材料
python3 scripts/minem_cli.py page ...    # 新增页面素材
python3 scripts/minem_cli.py case ...    # 外部文档转案例素材
python3 scripts/minem_cli.py task ...    # 查询异步任务和结果
```

所有命令支持 `--json`。任何会改写正式汇报的命令先支持 `--dry-run`；`apply`、`publish`、`delete` 等动作须加 `--yes`。

## 1. 导入外部材料

### 用户要做的事

将外部已有的汇报 HTML / 汇报 ZIP / 单页 HTML / 页面模板包导入 MineM，自动入库为汇报材料、页面素材及其关联资源，并得到可预览的 ID 和链接。

### CLI

```bash
# 导入一份完整汇报；MineM 识别页面并抽取资源
minem import report ./客户方案.zip \
  --title "某客户数字化方案" \
  --tags 制造业,客户方案 --wait --json

# 导入一个已有页面；直接作为页面素材入库
minem import page ./客户案例页.html \
  --title "客户案例：降本提效" \
  --tags 客户案例,案例页 --wait --json

# 导入多个混合材料，由 MineM 判别汇报、页面和资源
minem import files ./materials/ --description "Q3 汇报材料" --json

# 查看导入是否完成；完成的标准是返回真实可打开的预览链接
minem task get IMP-20260715-001 --json
```

### 系统要包装的现有能力

- 支持 HTML、ZIP，以及图片、SVG、GIF、视频等资源；
- ZIP 安全解压、扫描入口 HTML、抽取素材资源；
- 完整汇报入库为 `RPT-*`，单页入库为 `CTRL-*`；
- 保存来源批次、来源路径、标签、资源关系和真实预览地址；
- 导入为异步任务，返回成功/失败原因和可重试信息。

### 返回结果

默认异步返回任务；增加 `--wait` 后，CLI 会等待任务进入终态，并返回最终素材。此时
`--title` 必须作用于最终素材，而不是只写入任务描述。若平台复用了历史相同内容，CLI
不会擅自重命名已有素材。

```json
{
  "ok": true,
  "task_id": "IMP-20260715-001",
  "task": {"id": "task-20260715-001", "status": "queued"}
}
```

## 2. 创建、修改汇报材料

### 用户要做的事

创建一个新的汇报，或对已有汇报新增一页、替换某一页、修改某一页的内容，然后得到新的可预览汇报。

这里“修改某一页”分两种：

- **换页**：用已有或新建的页面素材替换汇报中的某页；
- **改页**：对该页页面素材的 HTML/结构化内容进行编辑，并将新版本挂回该汇报。

### CLI

```bash
# 创建空汇报，或以一个已有汇报作为起点
python3 scripts/minem_cli.py report create --title "2026 制造业解决方案" --controls <CTRL页面内部ID>,<CTRL页面内部ID> --json

# 查看当前汇报的页面和顺序
python3 scripts/minem_cli.py report pages <RPT内部ID> --json

# 在指定页后新增一页（引用一个已有页面素材）
python3 scripts/minem_cli.py report page <RPT内部ID> \
  --add <新CTRL内部ID>:<现有CTRL内部ID> --yes --json

# 用另一张页面素材替换第 4 页
python3 scripts/minem_cli.py report page <RPT内部ID> \
  --replace <旧CTRL内部ID>:<新CTRL内部ID> --yes --json

# “改页”的首版做法：先以新 HTML 创建一个新页面素材，再用 replace 替换旧页
python3 scripts/minem_cli.py page create --file ./revised-page-4.html --title "新版第 4 页" --json
python3 scripts/minem_cli.py report page <RPT内部ID> \
  --replace <旧CTRL内部ID>:<新CTRL内部ID> --yes --json
```

### 必须遵守的 MineM 规则

- 新增、替换或编辑页面只改变当前汇报的页面槽位和编排元数据；
- 不改写原始来源汇报 HTML；
- “改页”产生页面素材新版本，旧版本可追溯；
- 不复制无关资源；页面引用关系必须可查询；
- 编排提交成功后，公开汇报链接必须实际展示最新结果，而非仅 CLI 返回成功；
- 不允许删除或编排为空汇报。

## 3. 新增页面素材

### 用户要做的事

从零创建一页可复用的页面素材，或基于已有页面复制后修改；页面可独立预览，也能插入任何汇报。

### CLI

```bash
# 从模板创建空白页面素材
python3 scripts/minem_cli.py page create \
  --file ./customer-case-page.html \
  --title "客户案例：交付成果" --wait --json
```

### 页面输入契约（首版）

首版以“预先生成单页 HTML 或标准页面模板 ZIP 后导入”为边界。页面渲染 schema 是下一阶段能力；建议届时使用 JSON，避免 Agent 直接拼接不受控 HTML：

```json
{
  "layout": "case-study",
  "title": "某制造客户：产线协同提效",
  "sections": [
    {"heading": "客户挑战", "body": "跨部门协同成本高"},
    {"heading": "解决方案", "body": "通过统一协作平台串联流程"},
    {"heading": "成果", "body": "审批周期缩短 40%"}
  ],
  "asset_ids": ["RES-20260701-018"]
}
```

MineM 将其渲染为独立 HTML 页面、生成缩略图和预览链接，并保留输入 spec 与页面版本关系。

## 4. 外部文档转案例素材

### 用户要做的事

输入一篇外部文档（Markdown、TXT、PDF；后续可接飞书文档内容），MineM 提取案例信息，形成一个案例组与若干可复用案例页面素材，而不是只保存原文。

### CLI

```bash
# 从本地文档提炼案例素材
python3 scripts/minem_cli.py case create --file ./客户访谈纪要.md \
  --title "某制造客户协同提效案例" \
  --industry 制造业 --wait --json

# 从已取回的文档文本创建；适合 Agent 已获得文档内容的场景
python3 scripts/minem_cli.py case create --file ./customer-case.txt \
  --title "某制造客户协同提效案例" --wait --json

# 查询案例页面导入任务
python3 scripts/minem_cli.py task get <task-id> --json

# 选择一个生成的案例页面，插入目标汇报
python3 scripts/minem_cli.py report page <RPT内部ID> \
  --add <案例CTRL内部ID>:<现有CTRL内部ID> --yes --json
```

### 文档转化链路

```text
外部文档
→ 提取客户、行业、背景、挑战、方案、关键动作、成果/数据、引用素材
→ 生成首张 CTRL 案例页面素材
→ 预览通过后可插入 RPT 汇报
```

案例结构化 JSON 至少包含：客户名称、行业、案例标题、背景、挑战、解决方案、成果指标、可引用的原文片段及素材来源。若文档缺少数据，必须标记“待补充”，不得编造指标或客户事实。

首版默认生成“案例概览”页。后续升级为由结构化 JSON 驱动的三类页面：

1. 案例概览：客户背景、行业、核心成果；
2. 挑战与方案：问题、关键动作、产品/服务能力；
3. 价值成果：量化成果、客户引语、可复用结论。

## 首版验收闭环

```text
导入一份外部汇报
→ 找到其页面或新建一张案例页
→ 将该页插入/替换到目标汇报
→ 得到更新后的正式预览链接
```

以及：

```text
导入外部案例文档
→ 生成案例组和案例页面
→ 人工/Agent 校验事实与预览
→ 插入目标汇报
```

本文定义的是 MineM 对外 CLI 产品范围。实现应复用现有 SQLite、上传目录、`extracted/`、缩略图和预览链路，不建立第二套素材库。

### AI / CLI 可执行性验收

发布前必须在隔离数据目录运行 `python3 scripts/test_cli_workflow.py`，真实完成以下动作：

1. 创建并命名三张页面素材和一张案例页面，取得 `CTRL-*` 编号与可访问预览链接；
2. 使用页面素材创建一份 `RPT-*` 汇报；
3. 将案例页面插入汇报，再以新页面替换旧页面；
4. 查询最终编排并确认页数、顺序与引用正确；
5. 访问每张页面和正式汇报链接，确认不是 404、空白响应或仅有任务成功状态；
6. 确认插入、替换不会删除原页面素材和历史版本。

该测试使用临时数据库和临时素材，不写入用户素材库。GitHub CI 对每次提交执行同一条
链路，保证 README 中展示的 AI 能力是可运行的产品能力。
