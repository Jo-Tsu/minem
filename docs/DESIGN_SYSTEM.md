# MineM 设计规范

版本：0.4.0 · 2026-07-19
来源：基于项目设计规范沉淀，调整为当前 React + TypeScript + Vite 平台落地版。

## 1. 定位

MineM 是本地化 HTML 汇报素材工作台，视觉气质为：

- Editorial：克制留白、清晰标题、内容可读。
- Workbench：信息密度可扫描，控件稳定，不做营销页式装饰。
- Soft-Tech：浅蓝品牌记忆点，冷灰画布，轻微玻璃与极光。

后续新增前端页面、弹窗、抽屉和导入流程，必须先复用本规范中的 token、组件和交互规则。

## 2. 设计原则

1. 克制优先，渐变点睛：页面主体使用黑白灰和浅蓝，不使用紫色、粉色、荧光色作为主视觉。
2. 顶部导航优先：一级导航使用顶部胶囊导航，不引入左侧后台式菜单。
3. 卡片是内容最小单位：汇报、控件、资源、故事线都通过卡片进入详情。
4. 先广场，后详情：一级页面展示聚合、筛选和入口；细节进入弹窗或抽屉。
5. 数据可解释：批次、链路、版本和标签要能点击查看关联数据。
6. 动效轻：只使用 hover 抬升、焦点环、弹窗显隐，不做粒子、视差、整页动画。
7. 任务优先：先展示客户当前可执行的操作，再展示解释信息；同一数据不在顶部、Hero 和卡片中重复出现。
8. 渐进操作：低频动作进入“更多”，批量动作只在选择后出现，危险动作不与主操作并列。

## 3. 技术落地

当前平台使用 React + TypeScript + Vite，规范落在：

- `frontend/src/styles.css`：设计 token、布局、组件样式。
- `frontend/src/App.tsx`：当前 React 组件入口，后续按组件目录继续拆分。
- `frontend/src/api.ts`：统一 API 请求入口和预览 URL 处理。
- `frontend/src/types.ts`：前后端契约类型。
- `vite.config.ts`：构建到 `public/`，由 Python 后端静态托管。

新增页面不要在组件内硬编码主色、阴影、圆角和字体，应优先使用 CSS token。`public/` 是构建产物目录，不再手写平台源码。

## 4. Token

核心 token 已在 `frontend/src/styles.css` 的 `:root` 中定义。

色彩：
- `--background`：页面画布。
- `--surface`：卡片、弹窗右栏、按钮底。
- `--surface-2`：弹窗左栏、次级面板。
- `--ink`：主文字。
- `--ink-soft`：次级文字。
- `--ink-muted`：弱文字和 meta。
- `--line`：hairline 分隔。
- `--brand`：品牌浅蓝。
- `--brand-strong`：主按钮、选中态和重点数字。
- `--brand-soft`：选中底、chip 底、高亮底。
- `--destructive`：删除等危险动作。

渐变：
- `--gradient-brand`：主 CTA、品牌 mark、KPI 图标徽章。
- `--gradient-brand-soft`：选中卡片、hover 底。
- `--gradient-aurora`：AI 演讲台等沉浸式工具背景；不得用于工作台营销式 Hero。
- `--gradient-sheen`：卡片顶部微亮。

阴影：
- `--shadow-soft`：默认卡片。
- `--shadow-elev`：hover 抬升和弹窗。
- `--shadow-brand`：主 CTA、品牌徽章。

字体：
- `--font-display`：大标题、KPI 数字。
- `--font-sans`：正文、按钮、表单。
- `--font-serif`：只允许作为少量 editorial 点缀。
- `--font-mono`：素材编号、页码、时间戳、结构标签。

## 5. 页面骨架

新增一级页面按此 React 结构：

```tsx
<section class="workspace">
  <section class="compact-overview">...</section>
  <section class="library-toolbar is-sticky">...</section>
  <section class="asset-grid">...</section>
</section>
```

要求：
- 主容器沿用 `--page-max` 和 `--page-gutter`；宽屏通过增加稳定卡片列数提升密度，不把少量卡片无限拉宽。
- 不在一级页面铺满所有明细列表；长内容进入弹窗、抽屉或分页列表。
- 工具栏必须有清楚的筛选状态和数量反馈。
- 模块切换后滚动位置归零；列表工具栏吸附在两层顶部导航下方，不能覆盖导航或卡片。
- 素材列表页不展示“汇报素材 / 控件素材 / 资源素材”流程卡片，类型切换只保留在顶部导航和“更多”菜单中。
- “数量 + 导入/自动导入/打标签/合并相似”的工具栏只在资源素材页显示，汇报和控件列表不展示该模块。

## 6. 组件规则

App Shell：
- 顶部胶囊导航为一级导航。
- 搜索在支持素材检索的模块固定于顶部右侧；没有检索结果页的工作台和案例模块不显示占位搜索框。
- 上传/导入是主 CTA，使用 `--gradient-brand`。

卡片：
- 内容卡片圆角不超过 8px；14px 只用于主弹窗外壳。
- hover 使用 `translateY(-2px)`、边框转品牌色、`--shadow-elev`。
- 预览区必须有稳定 aspect-ratio，避免图片/iframe 加载后撑开布局。
- 汇报/页面卡片优先 `minmax(340px, 1fr)`；资源素材是高密度浏览区，优先 `minmax(176px, 1fr)`，常规桌面约 6 列。
- 资源卡片使用 4:3 小预览、短标题和弱化素材编号，不使用大面积 1:1 图片卡。
- 列表优先使用缩略图，HTML iframe 仅作 `loading="lazy"` 的缺图兜底；案例列表不得直接加载整份多页汇报作为每张卡片预览。

弹窗：
- 高频操作放顶部右侧，按钮高度保持 30-32px。
- 弹窗圆角优先 14px，详情 section 圆角优先 8px，不在弹窗里继续堆叠大卡片。
- 详情内容按 section 分组，预览区和信息区分栏；资源素材弹窗可以缩小预览占比。
- 故事线详情只保留一份来源、版本和基础字段；低频目录/固定内容使用折叠区，不展示“暂无内容”占位卡片。
- 链路详情使用双抽屉：左侧关联列表，右侧选中项详情/预览。

导入：
- 导入弹窗必须展示支持类型、所选文件名、文件大小、后台任务说明和“不改变生成链路”的边界提醒。
- 导入任务 Dock 使用紧凑状态卡，展示状态、文件名、进度、结果数量和预览入口。
- 导入任务列表最多展示最近少量任务，不能遮挡主工作区。
- 资源素材页工具栏必须提供“导入外部资源”入口；支持 HTML、ZIP、图片、SVG、GIF 和视频，不只支持汇报包。

筛选 Chip：
- 未选：白底/浅灰底 + hairline。
- 选中：`--brand-soft` + `--brand-strong`。
- 文案短，不用长句。

操作层级：
- 每个工具条最多一个主按钮；资源页主按钮固定为导入。
- 全选属于次级操作，清空、合并、临时预览只在已有选择时出现。
- 自动导入、自动标签和相似合并属于低频批处理，统一收进“更多”菜单。
- 图标按钮必须提供 `title` 和 `aria-label`；复制、刷新、全屏、关闭优先只用图标。

预览画布：
- 平台汇报查看器和页面查看器的外层逻辑画布固定为 `1920×1080`，容器使用 `contain` 等比缩放。
- 来源页面尺寸只用于内容适配与版本记录；不得用来源尺寸再次缩放统一查看器。
- 公开页显示一套复制、刷新、全屏工具；嵌入卡片或弹窗时隐藏查看器内部工具，避免重复。

## 7. 禁止清单

- 不新增左侧后台风一级菜单。
- 不使用紫色、粉色、荧光渐变作为主色。
- 不用 emoji 作为图标。
- 不在组件中新增散落的 `fetch()`，统一走 `frontend/src/api.ts`。
- 不无净化地使用 `dangerouslySetInnerHTML`；用户/接口文本默认用 JSX 文本节点渲染。
- 不新增大面积圆角和多层卡片嵌套。
- 不新增 2px 以上粗边框或强烈阴影。

## 8. 前端新增流程

新增页面或组件前先确认：

1. 是否已有 token 可用；没有则先补 `frontend/src/styles.css`。
2. 是否已有 API wrapper；没有则先补 `frontend/src/api.ts`。
3. 是否已有类型；没有则先补 `frontend/src/types.ts`。
4. 是否已有 lucide 图标；没有则从 `lucide-react` 选择最贴近语义的图标。
5. 是否需要跨组件状态；优先放在上层 React state，避免新增全局变量。
6. 文本默认用 JSX 渲染；禁止无净化地使用 `dangerouslySetInnerHTML`。
7. 完成后至少运行：

```bash
npm run check
python3 scripts/check_api_contract.py --base-url http://127.0.0.1:8790
```

## 9. 目标组件架构（尚未完成）

- `frontend/src/components/AssetGrid.tsx`：汇报、控件、资源、故事线列表。
- `frontend/src/components/AssetModal.tsx`：素材详情弹窗、标签编辑、历史版本。
- `frontend/src/components/LineageDrawer.tsx`：原数据链路和双抽屉。
- `frontend/src/components/ImportDialog.tsx`：导入弹窗和导入任务 dock。

上述文件当前尚未全部存在。拆分原则：每次只迁一个功能面，保留现有视觉、API 口径和素材生成边界，完成后用浏览器验证对应主路径。
