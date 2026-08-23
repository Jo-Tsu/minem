import type { Asset, ImportTask, Storyline } from "./types";

export const ASSET_PAGE_SIZE = 30;

export const RESOURCE_FILTERS = [
  ["all", "全部资源"],
  ["image", "图片"],
  ["logo", "Logo"],
  ["icon", "图标"],
  ["gif", "GIF"],
  ["video", "视频"]
] as const;

export const PAGE_ROLE_FILTERS = [
  ["all", "全部页面"],
  ["cover", "封面"],
  ["title", "标题页"],
  ["content", "内容"],
  ["toc", "目录"],
] as const;

export const CONTROL_ROLE_FILTERS = [
  "全部",
  "开场定位",
  "背景价值",
  "组织铺垫",
  "能力说明",
  "路径方法",
  "客户背书",
  "场景地图",
  "案例展开",
  "证据证明",
  "收束行动"
];

export const VIEW_META = {
  workbench: ["工作台", "素材资产一处沉淀，按汇报、页面、资源和故事线连续复用。"],
  report: ["汇报素材", "完整生成的汇报材料，是页面素材和资源素材的根节点。"],
  control: ["页面素材", "一页一页的可拼接素材，可从汇报单页导入，也可导出为页面模板包。"],
  resource: ["资源素材", "图片、Logo、图标、GIF、视频和 SVG 等页面基础素材。"],
  caseControl: ["案例素材", "把同一文档生成的多个案例素材组织成组，统一管理原始链接、页面素材和多页预览。"],
  storyline: ["故事线", "可复用的汇报材料结构，也包含从汇报收藏生成的故事线记录。"]
} as const;

const SOURCE_TYPE_LABELS: Record<string, string> = {
  auto: "自动扫描导入",
  upload: "文件扫描导入",
  template: "模板包导入",
  "slide-control-import": "汇报单页导入",
  "control-resource-import": "资源素材抽取",
  "manual-version-import": "手动版本导入",
  "version-upload": "手动上传新版本",
  "manual-generated-control": "人工生成页面",
  "single-page-reclassified": "单页纠正",
  "created-report-page": "汇报页面",
  "report-canvas-normalized": "汇报尺寸适配",
  "report-canvas-normalization": "汇报尺寸适配",
  "report-material-sync": "汇报材料同步",
  "report-material-candidate": "汇报候选页",
  "storyline-collection": "故事线收藏"
};

export function sourceTypeLabel(value = "") {
  return SOURCE_TYPE_LABELS[value] || value || "未记录";
}

export function formatTime(value?: number | string) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未记录";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

export function isActiveImportTask(task: ImportTask) {
  return task.status === "queued" || task.status === "running";
}

export function timestampValue(value?: number | string) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (!value) return 0;
  const numeric = Number(value);
  if (Number.isFinite(numeric)) return numeric;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function compareNewestByTime(left: number | string | undefined, right: number | string | undefined) {
  return timestampValue(right) - timestampValue(left);
}

export function sortAssetsByNewest(items: Asset[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.activity_at || left.updated_at, right.activity_at || right.updated_at)
    || compareNewestByTime(left.created_at, right.created_at)
    || right.asset_code.localeCompare(left.asset_code)
  );
}

export function sortStorylinesByNewest(items: Storyline[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.updatedAt, right.updatedAt)
    || compareNewestByTime(left.createdAt, right.createdAt)
    || right.code.localeCompare(left.code)
  );
}

export function sortImportTasksByNewest(items: ImportTask[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.updatedAt, right.updatedAt)
    || compareNewestByTime(left.createdAt, right.createdAt)
    || right.id.localeCompare(left.id)
  );
}

export function defaultReportFormula(controls: Asset[], title: string) {
  const sampleCodes = controls.slice(0, 3).map((asset) => asset.asset_code).join("\n");
  return `你是 MineM 汇报素材平台里的 AI 创建助手，正在帮助用户通过“故事线 > 新增汇报素材 > 对话公式生成”功能创建一个新的汇报素材。

平台交互方式：
1. 用户会告诉你要生成的汇报素材标题、用途，以及要使用的页面素材编号。
2. 页面素材编号当前通常沿用“CTRL-日期-批次-序号”。这里只说明格式，不要把格式说明当成真实素材。
3. 平台会从你的回复中识别这些页面素材编号，并按出现顺序把对应页面复制成汇报页面。
4. 每次创建都会生成独立且唯一的汇报素材、独立目录和独立链接；不要覆盖已有故事线、来源汇报或页面素材。
5. 你的回复不要输出接口参数，也不要要求用户调用接口，只需要整理成平台能识别的创建指令。

请按下面格式回复给平台：
我现在准备生成一个汇报素材，标题是「${title || "新建汇报素材"}」。
请使用这些页面素材作为页面，按下面顺序直接生成：
${sampleCodes || "CTRL-这里替换成页面素材编号"}
要求：每个新增汇报素材都是独立且唯一的，不覆盖已有故事线或来源汇报。`;
}

export function controlCodesFromText(text: string) {
  const matches = text.match(/CTRL-[A-Z0-9-]+/gi) || [];
  return Array.from(new Set(matches.map((item) => item.toUpperCase())));
}

export function titleFromFormula(text: string, fallback: string) {
  const match = text.match(/标题(?:是|为)\s*[「《“"]([^」》”"\n。]+)[」》”"]?/);
  return match?.[1]?.trim() || fallback;
}

export function topTags(asset: Asset, limit = 4) {
  return (asset.tags || []).filter((tag) => tag && !tag.startsWith("RPT-")).slice(0, limit);
}

export function reportPageCount(asset: Asset) {
  return Number(asset.displayPageCount ?? asset.sourceBatch?.pageCount ?? asset.trusted_viewer_page_count ?? asset.trusted_page_count ?? 0);
}

export function scenarioForReport(asset: Asset) {
  const tags = asset.tags || [];
  return tags.find((tag) => ["制造业", "客户案例", "生产巡检", "质量管理", "安全巡检", "供应商管理"].includes(tag))
    || tags.find((tag) => !tag.startsWith("RPT-"))
    || "汇报材料";
}

export function pageNoFromAsset(asset: Asset) {
  const tags = asset.tags || [];
  const pageTag = tags.find((tag) => /^第\d+页$/.test(tag)) || tags.find((tag) => /^页码[:：]\d+$/i.test(tag));
  if (pageTag) return Number(pageTag.replace(/\D/g, ""));
  const controlCodeMatch = asset.asset_code.match(/^CTRL-.+-(\d{1,3})$/i);
  if (controlCodeMatch) return Number(controlCodeMatch[1]);
  const pathMatch = asset.source_path.match(/(?:page|slide)-?(\d{1,3})/i);
  return pathMatch ? Number(pathMatch[1]) : 0;
}

export function roleForControl(asset: Asset) {
  const tags = asset.tags || [];
  const pageNo = pageNoFromAsset(asset);
  return tags.find((tag) => CONTROL_ROLE_FILTERS.includes(tag))
    || (pageNo ? `第 ${String(pageNo).padStart(2, "0")} 页` : "未编号");
}
