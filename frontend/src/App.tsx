import {
  AlertCircle,
  BookmarkPlus,
  Box,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Check,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileArchive,
  FileText,
  GitBranch,
  Grid2X2,
  GripVertical,
  Layers3,
  Plus,
  Link,
  Loader2,
  Maximize2,
  MoreHorizontal,
  PackagePlus,
  Pencil,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { absoluteUrl, api } from "./api";
import { CaseControlLibrary } from "./components/CaseControlLibrary";
import { ImportDialog, ImportTaskDock } from "./components/ImportWidgets";
import type { ImportMode } from "./components/ImportWidgets";
import { Workbench } from "./components/Workbench";
import type {
  Asset,
  AssetType,
  ImportTask,
  LineageItem,
  LineageResponse,
  LineageSection,
  Pagination,
  PresenterScriptStatus,
  ReportExportTask,
  ReportArrangement,
  PipelineSummary,
  StatsResponse,
  Storyline,
  ViewKey
} from "./types";

const ASSET_PAGE_SIZE = 30;
const RESOURCE_FILTERS = [
  ["all", "全部资源"],
  ["image", "图片"],
  ["logo", "Logo"],
  ["icon", "图标"],
  ["gif", "GIF"],
  ["video", "视频"]
] as const;
const CONTROL_ROLE_FILTERS = ["全部", "开场定位", "背景价值", "组织铺垫", "能力说明", "路径方法", "客户背书", "场景地图", "案例展开", "证据证明", "收束行动"];
const DISMISSED_IMPORT_TASKS_KEY = "minem.dismissedImportTaskIds";
const DISMISSED_IMPORT_TASKS_UNTIL_KEY = "minem.dismissedImportTasksUntil";
const SOURCE_TYPE_LABELS: Record<string, string> = {
  auto: "自动扫描导入",
  upload: "文件扫描导入",
  template: "模板包导入",
  "slide-control-import": "汇报单页导入",
  "control-resource-import": "资源素材抽取",
  "manual-version-import": "手动版本导入",
  "manual-generated-control": "人工生成页面",
  "single-page-reclassified": "单页纠正",
  "created-report-page": "汇报页面",
  "report-canvas-normalized": "汇报尺寸适配",
  "report-canvas-normalization": "汇报尺寸适配",
  "report-material-sync": "汇报材料同步",
  "report-material-candidate": "汇报候选页",
  "storyline-collection": "故事线收藏"
};
const VIEW_META = {
  workbench: ["工作台", "素材资产一处沉淀，按汇报、页面、资源和故事线连续复用。"],
  report: ["汇报素材", "完整生成的汇报材料，是页面素材和资源素材的根节点。"],
  control: ["页面素材", "一页一页的可拼接素材，可从汇报单页导入，也可导出为页面模板包。"],
  resource: ["资源素材", "图片、Logo、图标、GIF、视频和 SVG 等页面基础素材。"],
  caseControl: ["案例素材", "把同一文档生成的多个案例素材组织成组，统一管理原始链接、页面素材和多页预览。"],
  storyline: ["故事线", "可复用的汇报材料结构，也包含从汇报收藏生成的故事线记录。"]
} as const;

type Toast = { id: number; text: string };
type StorylineCollectMode = "new" | "version";
type StorylineReportMode = "chat" | "manual" | "copy";
type ManualMergeMode = "keep" | "version";
type PresenterScriptSource = "minutes" | "script";
type PresenterScriptDraft = { asset: Asset; status?: PresenterScriptStatus; editing: boolean };
type PresenterAction = { asset: Asset; status: PresenterScriptStatus };

function sourceTypeLabel(value = "") {
  return SOURCE_TYPE_LABELS[value] || value || "未记录";
}

function formatTime(value?: number | string) {
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

function isActiveImportTask(task: ImportTask) {
  return task.status === "queued" || task.status === "running";
}

function classNames(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
}

function timestampValue(value?: number | string) {
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

function sortAssetsByNewest(items: Asset[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.activity_at || left.updated_at, right.activity_at || right.updated_at)
    || compareNewestByTime(left.created_at, right.created_at)
    || right.asset_code.localeCompare(left.asset_code)
  );
}

function sortStorylinesByNewest(items: Storyline[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.updatedAt, right.updatedAt)
    || compareNewestByTime(left.createdAt, right.createdAt)
    || right.code.localeCompare(left.code)
  );
}

function sortImportTasksByNewest(items: ImportTask[]) {
  return [...items].sort((left, right) =>
    compareNewestByTime(left.updatedAt, right.updatedAt)
    || compareNewestByTime(left.createdAt, right.createdAt)
    || right.id.localeCompare(left.id)
  );
}

function loadDismissedImportTaskIds() {
  try {
    const raw = window.localStorage.getItem(DISMISSED_IMPORT_TASKS_KEY);
    const ids = JSON.parse(raw || "[]");
    return new Set(Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set<string>();
  }
}

function saveDismissedImportTaskIds(ids: Set<string>) {
  try {
    window.localStorage.setItem(DISMISSED_IMPORT_TASKS_KEY, JSON.stringify(Array.from(ids).slice(-80)));
  } catch {
    // Local storage can be unavailable in restricted browser modes; dismissal still works for this session.
  }
}

function loadDismissedImportTasksUntil() {
  try {
    const value = Number(window.localStorage.getItem(DISMISSED_IMPORT_TASKS_UNTIL_KEY) || 0);
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch {
    return 0;
  }
}

function saveDismissedImportTasksUntil(value: number) {
  try {
    window.localStorage.setItem(DISMISSED_IMPORT_TASKS_UNTIL_KEY, String(value));
  } catch {
    // A restricted browser can still keep the dismissal for the current session.
  }
}

function openExternalUrl(url: string) {
  const opened = window.open(url, "_blank", "noreferrer");
  if (!opened) window.location.href = url;
}

function defaultReportFormula(controls: Asset[], title: string) {
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

function controlCodesFromText(text: string) {
  const matches = text.match(/CTRL-[A-Z0-9-]+/gi) || [];
  return Array.from(new Set(matches.map((item) => item.toUpperCase())));
}

function titleFromFormula(text: string, fallback: string) {
  const match = text.match(/标题(?:是|为)\s*[「《“"]([^」》”"\n。]+)[」》”"]?/);
  return match?.[1]?.trim() || fallback;
}

function topTags(asset: Asset, limit = 4) {
  return (asset.tags || []).filter((tag) => tag && !tag.startsWith("RPT-")).slice(0, limit);
}

function reportPageCount(asset: Asset) {
  return Number(asset.displayPageCount ?? asset.sourceBatch?.pageCount ?? asset.trusted_viewer_page_count ?? asset.trusted_page_count ?? 0);
}

function scenarioForReport(asset: Asset) {
  const tags = asset.tags || [];
  return tags.find((tag) => ["制造业", "客户案例", "生产巡检", "质量管理", "安全巡检", "供应商管理"].includes(tag)) || tags.find((tag) => !tag.startsWith("RPT-")) || "汇报材料";
}

function roleForControl(asset: Asset) {
  const tags = asset.tags || [];
  return tags.find((tag) => CONTROL_ROLE_FILTERS.includes(tag)) || `第 ${String(pageNoFromAsset(asset) || "").padStart(2, "0")} 页`;
}

function pageNoFromAsset(asset: Asset) {
  const tags = asset.tags || [];
  const pageTag = tags.find((tag) => /^第\d+页$/.test(tag)) || tags.find((tag) => /^页码[:：]\d+$/i.test(tag));
  if (pageTag) return Number(pageTag.replace(/\D/g, ""));
  const controlCodeMatch = asset.asset_code.match(/^CTRL-.+-(\d{1,3})$/i);
  if (controlCodeMatch) return Number(controlCodeMatch[1]);
  const pathMatch = asset.source_path.match(/(?:page|slide)-?(\d{1,3})/i);
  return pathMatch ? Number(pathMatch[1]) : 0;
}

function isVisualAsset(asset?: Asset | LineageItem | null) {
  const path = ("preview_url" in (asset || {}) ? (asset as Asset)?.preview_url : (asset as LineageItem)?.previewUrl) || "";
  const kind = "media_kind" in (asset || {}) ? (asset as Asset)?.media_kind : "";
  return ["image", "gif", "svg", "video"].includes(kind || "") || /\.(png|jpe?g|gif|webp|svg|mp4|mov|webm)$/i.test(path);
}

function isImagePreview(url = "") {
  return /\.(png|jpe?g|gif|webp|svg)(?:[?#].*)?$/i.test(url);
}

function previewSource(asset: Asset, mode: "thumbnail" | "interactive") {
  if (mode === "thumbnail") {
    if (asset.thumbnail_url) return asset.thumbnail_url;
    if (["image", "gif", "svg", "video"].includes(asset.media_kind) || isImagePreview(asset.preview_url)) {
      return asset.preview_url;
    }
    return "";
  }
  return asset.preview_url;
}

const HTML_PREVIEW_SIZE = { width: 1920, height: 1080 };

function previewSizeForAsset(asset: Asset) {
  const width = Math.round(Number(asset.preview_meta?.width || 0));
  const height = Math.round(Number(asset.preview_meta?.height || 0));
  const valid = width >= 320 && height >= 240 && width <= 8000 && height <= 6000;
  return valid ? { width, height } : HTML_PREVIEW_SIZE;
}

function FramePreview({
  asset,
  src,
  interactive,
  canvasSize
}: {
  asset: Asset;
  src: string;
  interactive: boolean;
  canvasSize?: { width: number; height: number };
}) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const { width: frameWidth, height: frameHeight } = canvasSize || previewSizeForAsset(asset);
  const scale = viewport.width && viewport.height ? Math.min(viewport.width / frameWidth, viewport.height / frameHeight) : 0;
  const offsetX = scale ? (viewport.width - frameWidth * scale) / 2 : 0;
  const offsetY = scale ? (viewport.height - frameHeight * scale) / 2 : 0;
  const frameSrc = `${src}${src.includes("?") ? "&" : "?"}embed=1&v=${encodeURIComponent(String(asset.updated_at || 0))}`;

  useEffect(() => {
    const node = shellRef.current;
    if (!node) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      setViewport({ width: rect.width, height: rect.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className={classNames("frame-shell", asset.preview_meta?.longPage && "is-long-page")}
      ref={shellRef}
      style={{ aspectRatio: "16 / 9" }}
    >
      <div
        className="frame-stage"
        style={{
          width: frameWidth,
          height: frameHeight,
          opacity: scale ? 1 : 0,
          transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale || 1})`
        }}
      >
        <iframe className={classNames("page-frame", interactive && "is-interactive")} src={frameSrc} title={asset.title} loading="lazy" />
      </div>
    </div>
  );
}

function Preview({ asset, mode = "interactive", compact = false }: { asset: Asset; mode?: "thumbnail" | "interactive"; compact?: boolean }) {
  const src = previewSource(asset, mode);
  // Reports always enter the canonical report viewer. It owns page order,
  // hidden pages and navigation; the imported document remains page content.
  if (mode === "interactive" && asset.asset_type === "report") {
    return <FramePreview asset={asset} src={`/api/reports/${encodeURIComponent(asset.id)}/arrangement/viewer`} interactive canvasSize={HTML_PREVIEW_SIZE} />;
  }
  if (mode === "interactive" && asset.asset_type === "control") {
    return <FramePreview asset={asset} src={`/pages/${encodeURIComponent(asset.id)}/index.html`} interactive canvasSize={HTML_PREVIEW_SIZE} />;
  }
  if (!src && asset.preview_url && asset.media_kind === "html") {
    return <FramePreview asset={asset} src={asset.preview_url} interactive={mode === "interactive"} />;
  }
  if (!src) return <div className="preview-fallback">{asset.mediaLabel || asset.typeLabel}</div>;
  const isThumbnailImage = mode === "thumbnail";
  if (asset.media_kind === "video") {
    return <video className="media-preview" src={src} muted playsInline controls={!compact} />;
  }
  if (isThumbnailImage || ["image", "gif", "svg"].includes(asset.media_kind) || asset.asset_type === "resource") {
    return <img className="media-preview" src={src} alt={asset.title} loading="lazy" />;
  }
  return <FramePreview asset={asset} src={src} interactive={mode === "interactive"} />;
}

function LineagePreview({ item }: { item?: LineageItem }) {
  if (!item?.previewUrl) return <div className="preview-fallback">无预览</div>;
  if (isVisualAsset(item)) return <img src={item.previewUrl} alt={item.title || item.assetCode || ""} loading="lazy" />;
  return <iframe src={item.previewUrl} title={item.title || item.assetCode || ""} loading="lazy" />;
}

function App() {
  const [view, setView] = useState<ViewKey>("materials");
  const [assetType, setAssetType] = useState<AssetType>("report");
  const [resourceKind, setResourceKind] = useState("all");
  const [controlRole, setControlRole] = useState("全部");
  const [query, setQuery] = useState("");
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSummary | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, pageSize: ASSET_PAGE_SIZE, total: 0, totalPages: 1, hasPrev: false, hasNext: false });
  const [storylines, setStorylines] = useState<Storyline[]>([]);
  const [loading, setLoading] = useState("正在加载素材");
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [arrangementAsset, setArrangementAsset] = useState<Asset | null>(null);
  const [lineage, setLineage] = useState<{ section: LineageSection; items: LineageItem[]; selectedIndex: number } | null>(null);
  const [storylineAsset, setStorylineAsset] = useState<Asset | null>(null);
  const [selectedStoryline, setSelectedStoryline] = useState<Storyline | null>(null);
  const [storylineCandidates, setStorylineCandidates] = useState<Storyline[]>([]);
  const [createReportOpen, setCreateReportOpen] = useState(false);
  const [createReportControls, setCreateReportControls] = useState<Asset[]>([]);
  const [selectedControlIds, setSelectedControlIds] = useState<Set<string>>(() => new Set());
  const [selectedResourceIds, setSelectedResourceIds] = useState<Set<string>>(() => new Set());
  const [manualMergeAssets, setManualMergeAssets] = useState<Asset[] | null>(null);
  const [presenterAction, setPresenterAction] = useState<PresenterAction | null>(null);
  const [presenterScriptDraft, setPresenterScriptDraft] = useState<PresenterScriptDraft | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importMode, setImportMode] = useState<ImportMode>("general");
  const [importTasks, setImportTasks] = useState<ImportTask[]>([]);
  const [dismissedImportTaskIds, setDismissedImportTaskIds] = useState<Set<string>>(() => loadDismissedImportTaskIds());
  const [dismissedImportTasksUntil, setDismissedImportTasksUntil] = useState(() => loadDismissedImportTasksUntil());
  const [toast, setToast] = useState<Toast | null>(null);
  const [workbench, setWorkbench] = useState<{ reports: Asset[]; controls: Asset[]; resources: Asset[] }>({ reports: [], controls: [], resources: [] });
  const requestSeq = useRef(0);
  const importTaskSessionStartedAt = useRef(Date.now());

  const activeMetaKey = view === "materials" ? assetType : view;
  const [pageTitle, pageSubtitle] = VIEW_META[activeMetaKey];
  const visibleImportTasks = useMemo(
    () => sortImportTasksByNewest(importTasks.filter((task) => {
      if (isActiveImportTask(task)) return true;
      const completedAt = timestampValue(task.updatedAt || task.createdAt);
      return completedAt >= importTaskSessionStartedAt.current
        && completedAt > dismissedImportTasksUntil
        && !dismissedImportTaskIds.has(task.id);
    })),
    [dismissedImportTaskIds, dismissedImportTasksUntil, importTasks]
  );

  const showToast = useCallback((text: string) => {
    setToast({ id: Date.now(), text });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const loadStats = useCallback(async () => {
    const data = await api.stats();
    setStats(data);
    setPipeline(data.pipeline);
    return data;
  }, []);

  const loadAssets = useCallback(async (page = 1, append = false) => {
    const seq = ++requestSeq.current;
    setLoading(append ? "正在加载更多素材" : query ? "正在搜索素材" : "正在加载素材");
    const data = await api.assets({
      view: "list",
      type: assetType,
      category: "all",
      resource_kind: assetType === "resource" ? resourceKind : "all",
      control_role: assetType === "control" && controlRole !== "全部" ? controlRole : undefined,
      q: query || undefined,
      page,
      page_size: ASSET_PAGE_SIZE
    });
    if (seq !== requestSeq.current) return;
    const incoming = sortAssetsByNewest(data.assets || []);
    setAssets((current) => {
      if (!append) return incoming;
      const seen = new Set(current.map((asset) => asset.id));
      const nextItems = incoming.filter((asset) => !seen.has(asset.id));
      return [...current, ...nextItems];
    });
    setPagination(data.pagination);
    setPipeline(data.pipeline || null);
  }, [assetType, controlRole, query, resourceKind]);

  const loadStorylines = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(query ? "正在搜索故事线" : "正在加载故事线");
    const data = await api.storylines({ q: query || undefined });
    if (seq !== requestSeq.current) return;
    if (data.ok === false) {
      showToast(data.error || "故事线读取失败");
      return;
    }
    setStorylines(sortStorylinesByNewest(data.storylines || []));
  }, [query, showToast]);

  const loadWorkbench = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading("正在整理工作台");
    const [statsData, storylineData, reports, controls, resources] = await Promise.all([
      api.stats(),
      api.storylines(),
      api.assets({ view: "list", type: "report", category: "all", resource_kind: "all", page: 1, page_size: 8 }),
      api.assets({ view: "list", type: "control", category: "all", resource_kind: "all", page: 1, page_size: 8 }),
      api.assets({ view: "list", type: "resource", category: "all", resource_kind: "all", page: 1, page_size: 8 })
    ]);
    if (seq !== requestSeq.current) return;
    setStats(statsData);
    setPipeline(statsData.pipeline);
    setStorylines(sortStorylinesByNewest(storylineData.storylines || []));
    setWorkbench({
      reports: sortAssetsByNewest(reports.assets || []),
      controls: sortAssetsByNewest(controls.assets || []),
      resources: sortAssetsByNewest(resources.assets || [])
    });
  }, []);

  const refreshCurrent = useCallback(async (page = 1) => {
    const loader = view === "workbench"
      ? loadWorkbench()
      : view === "storyline"
        ? loadStorylines()
        : view === "caseControl"
          ? Promise.resolve()
          : loadAssets(page);
    await Promise.all([loader, loadStats()]);
  }, [loadAssets, loadStats, loadStorylines, loadWorkbench, view]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (view === "workbench") void loadWorkbench();
      else if (view === "caseControl") setLoading("案例素材已加载");
      else if (view === "storyline") void loadStorylines();
      else void loadAssets(1);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [assetType, controlRole, loadAssets, loadStorylines, loadWorkbench, query, resourceKind, view]);

  useEffect(() => {
    if (view !== "materials" || assetType !== "control") {
      setSelectedControlIds(new Set());
    }
    if (view !== "materials" || assetType !== "resource") {
      setSelectedResourceIds(new Set());
    }
  }, [assetType, view]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [assetType, view]);

  const refreshImportTasks = useCallback(async () => {
    const data = await api.importTasks();
    if (data.ok === false) return;
    setImportTasks(sortImportTasksByNewest(data.tasks || []));
    if ((data.tasks || []).some((task) => task.status === "queued" || task.status === "running")) {
      window.setTimeout(() => void refreshImportTasks(), 1200);
    }
  }, []);

  useEffect(() => {
    void refreshImportTasks();
  }, [refreshImportTasks]);

  const openAsset = useCallback(async (assetId: string) => {
    const data = await api.asset(assetId);
    if (data.ok === false || !data.asset) {
      showToast(data.error || "素材读取失败");
      return;
    }
    setSelectedAsset(data.asset);
    setLineage(null);
  }, [showToast]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const arrangementId = params.get("arrange");
    if (arrangementId) {
      void api.asset(arrangementId).then((data) => {
        if (data.ok === false || !data.asset) {
          showToast(data.error || "汇报编排读取失败");
          return;
        }
        setArrangementAsset(data.asset);
      });
      return;
    }
    const assetId = params.get("preview");
    if (assetId) void openAsset(assetId);
  }, [openAsset, showToast]);

  const toggleControlSelection = useCallback((assetId: string) => {
    setSelectedControlIds((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  }, []);

  const selectVisibleControls = useCallback((assetIds: string[]) => {
    setSelectedControlIds((current) => {
      const next = new Set(current);
      assetIds.forEach((assetId) => next.add(assetId));
      return next;
    });
  }, []);

  const selectVisibleResources = useCallback((assetIds: string[]) => {
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      assetIds.forEach((assetId) => next.add(assetId));
      return next;
    });
  }, []);

  const clearControlSelection = useCallback(() => {
    setSelectedControlIds(new Set());
  }, []);

  const toggleResourceSelection = useCallback((assetId: string) => {
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  }, []);

  const clearResourceSelection = useCallback(() => {
    setSelectedResourceIds(new Set());
  }, []);

  const openManualMergeDialog = useCallback((items: Asset[]) => {
    const selected = items.filter((asset) => asset.asset_type === assetType);
    if (selected.length < 2) {
      showToast("请至少选择两个同类型素材");
      return;
    }
    setManualMergeAssets(selected);
  }, [assetType, showToast]);

  const submitManualMerge = useCallback(async (payload: { assetIds: string[]; primaryAssetId: string; mode: ManualMergeMode }) => {
    const data = await api.manualMergeAssets(payload);
    if (data.ok === false || !data.primary) {
      showToast(data.error || "人工合并失败");
      return;
    }
    const label = payload.mode === "keep" ? "已保留主素材并合并重复项" : "已生成素材版本组";
    showToast(`${label}，共 ${data.versionCount || payload.assetIds.length} 个版本`);
    setManualMergeAssets(null);
    setSelectedControlIds(new Set());
    setSelectedResourceIds(new Set());
    setSelectedAsset((current) => current && payload.assetIds.includes(current.id) ? data.primary : current);
    await Promise.all([loadAssets(1), loadStats()]);
  }, [loadAssets, loadStats, showToast]);

  const openSelectedTempReport = useCallback(async () => {
    const controlIds = [...selectedControlIds];
    if (!controlIds.length) {
      showToast("请先勾选页面素材");
      return;
    }
    const data = await api.createTempReport(controlIds);
    if (data.ok === false || !data.url) {
      showToast(data.error || "临时预览创建失败");
      return;
    }
    const url = absoluteUrl(data.url);
    openExternalUrl(url);
    showToast(`已打开 ${data.pageCount || controlIds.length} 页临时预览`);
  }, [selectedControlIds, showToast]);

  const openLineage = useCallback(async (assetId: string, sectionKey: string, groupKey = "") => {
    showToast("正在读取链路数据...");
    const data: LineageResponse = await api.assetLineage(assetId);
    if (data.ok === false) {
      showToast(data.error || "链路数据读取失败");
      return;
    }
    const section = (data.sections || []).find((item) => item.key === sectionKey) || data.sections?.[0];
    if (!section) return;
    let items: LineageItem[] = [];
    if (section.groups?.length) {
      const groups = groupKey ? section.groups.filter((group) => group.key === groupKey) : section.groups;
      items = groups.flatMap((group) => group.items || []);
    } else {
      items = section.items || [];
    }
    setLineage({ section, items, selectedIndex: 0 });
    showToast("");
  }, [showToast]);

  const startTagAnalysis = useCallback(async (asset: Asset) => {
    const data = await api.createTagAnalysisTask(asset.id);
    if (data.ok === false || !data.task) {
      showToast(data.error || "标签分析任务创建失败");
      return;
    }
    showToast("已创建标签分析任务");
  }, [showToast]);

  const renameAsset = useCallback(async (asset: Asset) => {
    const title = window.prompt("素材名称", asset.title)?.trim();
    if (title === undefined || !title || title === asset.title) return;
    const data = await api.renameAsset(asset.id, title);
    if (data.ok === false || !data.asset) {
      showToast(data.error || "重命名失败");
      return;
    }
    showToast("名称已更新");
    setSelectedAsset((current) => current?.id === data.asset.id ? data.asset : current);
    setAssets((current) => current.map((item) => item.id === data.asset.id ? data.asset : item));
  }, [showToast]);

  const deleteAsset = useCallback(async (asset: Asset) => {
    const confirmed = window.confirm(`删除素材 ${asset.asset_code}？\n\n这会从素材库数据库移除记录，并删除库内复制的文件；不会删除原始来源文件。`);
    if (!confirmed) return;
    const data = await api.deleteAsset(asset.id);
    if (data.ok === false) {
      showToast(data.error || "删除失败");
      return;
    }
    showToast(`已删除 ${data.assetCode || asset.asset_code}`);
    setSelectedAsset(null);
    await refreshCurrent();
  }, [refreshCurrent, showToast]);

  const copyText = useCallback(async (text: string, message: string) => {
    await navigator.clipboard.writeText(text);
    showToast(message);
  }, [showToast]);

  const openStorylineDialog = useCallback(async (asset: Asset) => {
    if (asset.asset_type !== "report") return;
    setStorylineAsset(asset);
    const data = await api.storylines();
    setStorylineCandidates(sortStorylinesByNewest(data.storylines || []));
  }, []);

  const createStorylineCollection = useCallback(async (payload: { title: string; note?: string; mode: StorylineCollectMode; targetStorylineId?: string }) => {
    if (!storylineAsset) return;
    const data = await api.createStorylineCollection(storylineAsset.id, {
      title: payload.title,
      note: payload.note,
      mode: payload.mode,
      target_storyline_id: payload.targetStorylineId
    });
    if (data.ok === false || !data.storyline) {
      showToast(data.error || "收藏失败");
      return;
    }
    showToast(payload.mode === "version" ? `已更新 ${data.storyline.code} 到 ${data.storyline.versionLabel || "新版本"}` : `已新建故事线 ${data.storyline.code}`);
    setStorylineAsset(null);
    setSelectedAsset(null);
    setSelectedStoryline(data.storyline);
    setView("storyline");
    await Promise.all([
      loadStats(),
      loadStorylines(),
      assetType === "report" ? loadAssets(1) : Promise.resolve()
    ]);
  }, [assetType, loadAssets, loadStats, loadStorylines, showToast, storylineAsset]);

  const openCreateReportDialog = useCallback(async () => {
    setCreateReportOpen(true);
    const [controls, storylineData] = await Promise.all([
      api.assets({ view: "list", type: "control", category: "all", resource_kind: "all", page: 1, page_size: 200 }),
      api.storylines()
    ]);
    setCreateReportControls(sortAssetsByNewest(controls.assets || []));
    if (storylineData.ok !== false) setStorylines(sortStorylinesByNewest(storylineData.storylines || []));
  }, []);

  const createStorylineReport = useCallback(async (payload: { mode: StorylineReportMode; title: string; note?: string; firstControlId?: string; controlIds?: string[]; conversation?: string; storylineVersionId?: string }) => {
    const data = await api.createStorylineReport(payload);
    if (data.ok === false || !data.asset) {
      showToast(data.error || "新增汇报素材失败");
      return;
    }
    showToast(`已新增汇报素材 ${data.asset.asset_code}`);
    setCreateReportOpen(false);
    setAssetType("report");
    setView("materials");
    await Promise.all([loadAssets(1), loadStats(), loadStorylines()]);
    setSelectedAsset(data.asset);
  }, [loadAssets, loadStats, loadStorylines, showToast]);

  const openAiPresenter = useCallback(async (asset: Asset) => {
    if (asset.asset_type !== "report" || !asset.preview_url) return;
    showToast("正在检查演讲稿...");
    const data = await api.reportPresenterScript(asset.id);
    if (data.ok === false) {
      showToast(data.error || "AI 演讲台检查失败");
      return;
    }
    if (data.hasScript) {
      setPresenterAction({ asset, status: data });
      showToast("");
      return;
    }
    setPresenterScriptDraft({ asset, status: data, editing: false });
    showToast("请先导入演讲稿");
  }, [showToast]);

  const savePresenterScript = useCallback(async (payload: { sourceType: PresenterScriptSource; minutesUrl?: string; script: string }) => {
    if (!presenterScriptDraft) return;
    const data = await api.saveReportPresenterScript(presenterScriptDraft.asset.id, payload);
    if (data.ok === false) {
      showToast(data.error || "演讲稿导入失败");
      return;
    }
    setPresenterScriptDraft(null);
    setPresenterAction(null);
    showToast(`${presenterScriptDraft.editing ? "已保存" : "已导入"} ${data.scriptCount || 0} 页演讲稿`);
    if (data.presenterUrl) openExternalUrl(absoluteUrl(data.presenterUrl));
  }, [presenterScriptDraft, showToast]);

  const generatePresenterScriptDraft = useCallback(async (asset: Asset) => {
    showToast("正在生成演讲稿...");
    const data = await api.generateReportPresenterScript(asset.id);
    if (data.ok === false || !data.scriptText) {
      showToast(data.error || "生成演讲稿失败");
      return "";
    }
    showToast(`已生成 ${data.pageCount || 0} 页演讲稿草稿`);
    return data.scriptText;
  }, [showToast]);

  const extractPresenterScriptFile = useCallback(async (asset: Asset, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    showToast("正在解析文件...");
    const data = await api.extractReportPresenterScriptFile(asset.id, formData);
    if (data.ok === false || !data.scriptText) {
      showToast(data.error || "文件解析失败");
      return "";
    }
    showToast(`已解析 ${data.fileName || file.name}`);
    return data.scriptText;
  }, [showToast]);

  const startImport = useCallback(async (file: File, description: string) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("description", description.trim());
    const data = await api.createImportTask(formData);
    if (data.ok === false || !data.task) {
      showToast(data.error || "导入任务创建失败");
      return;
    }
    setImportTasks((current) => sortImportTasksByNewest([data.task, ...current.filter((task) => task.id !== data.task.id)]).slice(0, 8));
    setImportOpen(false);
    showToast("已创建导入任务");
    window.setTimeout(() => void refreshImportTasks(), 500);
  }, [refreshImportTasks, showToast]);

  const dismissImportTask = useCallback((taskId: string) => {
    const task = importTasks.find((item) => item.id === taskId);
    setImportTasks((current) => current.filter((task) => task.id !== taskId));
    setDismissedImportTaskIds((current) => {
      const next = new Set(current);
      next.add(taskId);
      saveDismissedImportTaskIds(next);
      return next;
    });
    if (task && !isActiveImportTask(task)) {
      setDismissedImportTasksUntil((current) => {
        const next = Math.max(current, timestampValue(task.updatedAt || task.createdAt));
        saveDismissedImportTasksUntil(next);
        return next;
      });
    }
  }, [importTasks]);

  const actionButtons = useMemo(() => (
    <div className="shell-actions">
      <button className="icon-btn" type="button" onClick={() => void refreshCurrent()} title="刷新">
        <RefreshCw size={16} />
      </button>
      <button className="primary" type="button" onClick={() => { setImportMode("general"); setImportOpen(true); }}>
        <Upload size={16} /> 导入
      </button>
    </div>
  ), [refreshCurrent]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-main">
          <button className="brand" type="button" onClick={() => { setAssetType("report"); setResourceKind("all"); setView("materials"); }}>
            <span className="brand-mark">M</span>
            <span><strong>MineM</strong><small>Material OS</small></span>
          </button>
          <nav className="pill-nav" aria-label="产品模块">
            <button className={classNames(view === "workbench" && "active")} type="button" onClick={() => setView("workbench")}><Grid2X2 size={15} />工作</button>
            <button className={classNames(view === "materials" && assetType === "report" && "active")} type="button" onClick={() => { setAssetType("report"); setView("materials"); }}><FileText size={15} />汇报</button>
            <button className={classNames(view === "materials" && assetType === "control" && "active")} type="button" onClick={() => { setAssetType("control"); setView("materials"); }}><Layers3 size={15} />页面</button>
            <button className={classNames(view === "caseControl" && "active")} type="button" onClick={() => setView("caseControl")}><BookmarkPlus size={15} />案例</button>
            <button className={classNames(view === "materials" && assetType === "resource" && "active")} type="button" onClick={() => { setAssetType("resource"); setView("materials"); }}><Box size={15} />资源</button>
            <button className={classNames(view === "storyline" && "active")} type="button" onClick={() => setView("storyline")}><GitBranch size={15} />故事</button>
          </nav>
          {view === "materials" || view === "storyline" ? (
            <label className="search-box">
              <Search size={15} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索编号 / 名称 / 链接 / 标签" />
            </label>
          ) : <span className="topbar-spacer" aria-hidden="true" />}
          {actionButtons}
        </div>
        <div className="topbar-sub">
          <div>
            <h1>{pageTitle}</h1>
            <p>{pageSubtitle}</p>
          </div>
          {view !== "workbench" ? <dl className="top-stats">
            <div><dt>素材</dt><dd>{stats?.assetCount ?? 0}</dd></div>
            <div><dt>汇报</dt><dd>{stats?.types?.report ?? 0}</dd></div>
            <div><dt>页面</dt><dd>{stats?.types?.control ?? 0}</dd></div>
            <div><dt>资源</dt><dd>{stats?.types?.resource ?? 0}</dd></div>
          </dl> : null}
        </div>
      </header>

      <section className="workspace">
        {view === "workbench" && <Workbench stats={stats} pipeline={pipeline} workbench={workbench} storylines={storylines} setAssetType={setAssetType} setView={setView} openAsset={openAsset} openStoryline={setSelectedStoryline} />}
        {view === "materials" && (
          <AssetLibrary
            assetType={assetType}
            assets={assets}
            loading={loading}
            pagination={pagination}
            resourceKind={resourceKind}
            setResourceKind={setResourceKind}
            controlRole={controlRole}
            setControlRole={setControlRole}
            openAsset={openAsset}
            renameAsset={renameAsset}
            onCollectStoryline={openStorylineDialog}
            selectedControlIds={selectedControlIds}
            selectedResourceIds={selectedResourceIds}
            onToggleControlSelection={toggleControlSelection}
            onToggleResourceSelection={toggleResourceSelection}
            onSelectVisibleControls={selectVisibleControls}
            onSelectVisibleResources={selectVisibleResources}
            onClearControlSelection={clearControlSelection}
            onClearResourceSelection={clearResourceSelection}
            onOpenTempReport={openSelectedTempReport}
            onOpenManualMerge={openManualMergeDialog}
            loadAssets={loadAssets}
            onOpenExternalImport={() => { setImportMode("external-report"); setImportOpen(true); }}
            onAutoImport={async () => {
              showToast("正在扫描历史素材...");
              const data = await api.autoImport();
              if (data.ok === false) showToast(data.error || "自动导入失败");
              else {
                showToast(`扫描 ${data.scanned} 个文件，新增 ${data.assetCount} 个素材`);
                await Promise.all([loadAssets(1), loadStats()]);
              }
            }}
            onAiTag={async () => {
              showToast("正在补充标签...");
              const data = await api.aiTag(assetType);
              if (data.ok === false) showToast(data.error || "AI 打标签失败");
              else {
                showToast(`已分析 ${data.scanned} 个素材，更新 ${data.updated} 个`);
                await Promise.all([loadAssets(1), loadStats()]);
              }
            }}
            onMergeSimilar={async () => {
              showToast("正在合并相似图片...");
              const data = await api.mergeSimilar();
              if (data.ok === false) showToast(data.error || "合并失败");
              else {
                showToast(`扫描 ${data.scanned} 个图片素材，合并 ${data.mergedAssets} 个为 ${data.groups} 组版本`);
                await Promise.all([loadAssets(1), loadStats()]);
              }
            }}
          />
        )}
        {view === "caseControl" && <CaseControlLibrary copyText={copyText} />}
        {view === "storyline" && <StorylineLibrary storylines={storylines} loading={loading} copyText={copyText} openStoryline={setSelectedStoryline} openCreateReport={openCreateReportDialog} />}
      </section>

      {manualMergeAssets ? (
        <ManualMergeDialog
          assets={manualMergeAssets}
          close={() => setManualMergeAssets(null)}
          mergeAssets={submitManualMerge}
        />
      ) : null}

      {selectedAsset && (
        <AssetModal
          asset={selectedAsset}
          lineage={lineage}
          setLineage={setLineage}
          close={() => { setSelectedAsset(null); setLineage(null); }}
          copyText={copyText}
          refreshAsset={openAsset}
          startTagAnalysis={startTagAnalysis}
          renameAsset={renameAsset}
          deleteAsset={deleteAsset}
          openLineage={openLineage}
          collectStoryline={openStorylineDialog}
          openAiPresenter={openAiPresenter}
          openArrangement={(asset) => { setSelectedAsset(null); setArrangementAsset(asset); window.history.pushState({}, "", `?arrange=${encodeURIComponent(asset.id)}`); }}
        />
      )}
      {arrangementAsset ? <ReportArrangementWorkspace asset={arrangementAsset} close={() => { setArrangementAsset(null); window.history.pushState({}, "", window.location.pathname); }} showToast={showToast} refreshAsset={openAsset} /> : null}
      {storylineAsset ? (
        <StorylineCollectionDialog
          asset={storylineAsset}
          storylines={storylineCandidates}
          close={() => setStorylineAsset(null)}
          createStoryline={createStorylineCollection}
        />
      ) : null}
      {selectedStoryline ? (
        <StorylineModal
          storyline={selectedStoryline}
          close={() => setSelectedStoryline(null)}
          copyText={copyText}
          openAsset={async (assetId) => {
            setSelectedStoryline(null);
            await openAsset(assetId);
          }}
        />
      ) : null}
      {createReportOpen ? (
        <StorylineReportDialog
          storylines={storylines}
          controls={createReportControls}
          close={() => setCreateReportOpen(false)}
          createReport={createStorylineReport}
          copyText={copyText}
        />
      ) : null}

      {presenterAction ? (
        <PresenterActionDialog
          asset={presenterAction.asset}
          status={presenterAction.status}
          close={() => setPresenterAction(null)}
          editScript={() => {
            setPresenterScriptDraft({ asset: presenterAction.asset, status: presenterAction.status, editing: true });
            setPresenterAction(null);
          }}
          enterPresenter={() => {
            setPresenterAction(null);
            if (presenterAction.status.presenterUrl) openExternalUrl(absoluteUrl(presenterAction.status.presenterUrl));
          }}
        />
      ) : null}

      {presenterScriptDraft ? (
        <PresenterScriptDialog
          asset={presenterScriptDraft.asset}
          status={presenterScriptDraft.status}
          editing={presenterScriptDraft.editing}
          close={() => setPresenterScriptDraft(null)}
          saveScript={savePresenterScript}
          generateScript={generatePresenterScriptDraft}
          extractScriptFile={extractPresenterScriptFile}
        />
      ) : null}

      {importOpen && <ImportDialog mode={importMode} close={() => setImportOpen(false)} startImport={startImport} />}
      <ImportTaskDock tasks={visibleImportTasks} dismissTask={dismissImportTask} />
      {toast?.text ? <div className="toast" role="status">{toast.text}</div> : null}
    </main>
  );
}

function AssetLibrary(props: {
  assetType: AssetType;
  assets: Asset[];
  loading: string;
  pagination: Pagination;
  resourceKind: string;
  setResourceKind: (kind: string) => void;
  controlRole: string;
  setControlRole: (role: string) => void;
  openAsset: (id: string) => Promise<void>;
  renameAsset: (asset: Asset) => Promise<void>;
  onCollectStoryline: (asset: Asset) => Promise<void>;
  selectedControlIds: Set<string>;
  selectedResourceIds: Set<string>;
  onToggleControlSelection: (assetId: string) => void;
  onToggleResourceSelection: (assetId: string) => void;
  onSelectVisibleControls: (assetIds: string[]) => void;
  onSelectVisibleResources: (assetIds: string[]) => void;
  onClearControlSelection: () => void;
  onClearResourceSelection: () => void;
  onOpenTempReport: () => Promise<void>;
  onOpenManualMerge: (assets: Asset[]) => void;
  loadAssets: (page?: number) => Promise<void>;
  onOpenExternalImport: () => void;
  onAutoImport: () => Promise<void>;
  onAiTag: () => Promise<void>;
  onMergeSimilar: () => Promise<void>;
}) {
  const { assetType, assets, loading, pagination, openAsset, renameAsset, loadAssets, onCollectStoryline, selectedControlIds, selectedResourceIds } = props;
  const visibleControlIds = useMemo(() => assets.filter((asset) => asset.asset_type === "control").map((asset) => asset.id), [assets]);
  const allVisibleControlsSelected = visibleControlIds.length > 0 && visibleControlIds.every((assetId) => selectedControlIds.has(assetId));
  const visibleResourceIds = useMemo(() => assets.filter((asset) => asset.asset_type === "resource").map((asset) => asset.id), [assets]);
  const allVisibleResourcesSelected = visibleResourceIds.length > 0 && visibleResourceIds.every((assetId) => selectedResourceIds.has(assetId));
  const selectedControls = useMemo(() => assets.filter((asset) => selectedControlIds.has(asset.id)), [assets, selectedControlIds]);
  const selectedResources = useMemo(() => assets.filter((asset) => selectedResourceIds.has(asset.id)), [assets, selectedResourceIds]);
  return (
    <>
      {assetType === "resource" ? (
        <section className="toolbar">
          <div>
            <strong>{pagination.total || assets.length} 个素材</strong>
            <span>已加载 {assets.length} / {pagination.total || assets.length}</span>
          </div>
          <div className="chip-row">
            {RESOURCE_FILTERS.map(([kind, label]) => (
              <button key={kind} className={classNames(props.resourceKind === kind && "active")} type="button" onClick={() => props.setResourceKind(kind)}>{label}</button>
            ))}
          </div>
          <div className="toolbar-actions">
            <button className="primary" type="button" onClick={props.onOpenExternalImport}><Upload size={15} />导入外部资源</button>
            <button className="secondary" type="button" onClick={() => props.onSelectVisibleResources(visibleResourceIds)} disabled={!visibleResourceIds.length || allVisibleResourcesSelected}><CheckCircle2 size={15} />全选当前页</button>
            {selectedResourceIds.size ? <button className="secondary" type="button" onClick={props.onClearResourceSelection}><X size={15} />清空</button> : null}
            {selectedResources.length >= 2 ? <button className="secondary" type="button" onClick={() => props.onOpenManualMerge(selectedResources)}><GitBranch size={15} />合并</button> : null}
            <details className="toolbar-more">
              <summary aria-label="更多资源操作"><MoreHorizontal size={16} />更多</summary>
              <div>
                <button type="button" onClick={props.onAutoImport}><PackagePlus size={15} />自动导入</button>
                <button type="button" onClick={props.onAiTag}><Sparkles size={15} />打标签</button>
                <button type="button" onClick={props.onMergeSimilar}><GitBranch size={15} />合并相似</button>
              </div>
            </details>
          </div>
        </section>
      ) : null}
      {assetType === "control" ? (
        <section className="selection-toolbar">
          <div className="selection-summary">
            <strong>{selectedControlIds.size ? `已选 ${selectedControlIds.size} 页` : "页面选择"}</strong>
            <span>{selectedControlIds.size ? "可临时预览或人工合并" : `${pagination.total || assets.length} 页 · 每次加载 30 页`}</span>
          </div>
          <div className="selection-actions">
            <button className="secondary" type="button" onClick={() => props.onSelectVisibleControls(visibleControlIds)} disabled={!visibleControlIds.length || allVisibleControlsSelected}>
              <CheckCircle2 size={14} />全选当前页
            </button>
            {selectedControlIds.size ? <button className="secondary" type="button" onClick={props.onClearControlSelection}>
              <X size={14} />清空
            </button> : null}
            {selectedControls.length >= 2 ? <button className="secondary" type="button" onClick={() => props.onOpenManualMerge(selectedControls)}>
              <GitBranch size={14} />人工合并
            </button> : null}
            {selectedControlIds.size ? <button className="primary" type="button" onClick={() => void props.onOpenTempReport()}>
              <Link size={14} />打开临时预览
            </button> : null}
          </div>
        </section>
      ) : null}
      {!assets.length ? <div className="empty-state"><Loader2 size={18} />{loading}</div> : (
        <section className={classNames("asset-grid", assetType === "resource" && "resource-grid")}>
          {assets.map((asset, index) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              index={index}
              openAsset={openAsset}
              onRename={renameAsset}
              onCollectStoryline={onCollectStoryline}
              selected={assetType === "control" ? selectedControlIds.has(asset.id) : selectedResourceIds.has(asset.id)}
              selectable={assetType === "control" || assetType === "resource"}
              onToggleSelect={assetType === "resource" ? props.onToggleResourceSelection : props.onToggleControlSelection}
            />
          ))}
        </section>
      )}
      <PaginationBar pagination={pagination} loadAssets={loadAssets} />
    </>
  );
}

function AssetCard({
  asset,
  index,
  openAsset,
  onRename,
  onCollectStoryline,
  selected = false,
  selectable = false,
  onToggleSelect
}: {
  asset: Asset;
  index: number;
  openAsset: (id: string) => Promise<void>;
  onRename: (asset: Asset) => Promise<void>;
  onCollectStoryline: (asset: Asset) => Promise<void>;
  selected?: boolean;
  selectable?: boolean;
  onToggleSelect?: (assetId: string) => void;
}) {
  if (asset.asset_type === "resource") {
    return (
      <article className={classNames("resource-card asset-card", selected && "is-selected")}>
        {selectable ? (
          <button
            className={classNames("select-toggle", selected && "is-selected")}
            type="button"
            aria-pressed={selected}
            aria-label={`${selected ? "取消选择" : "选择"} ${asset.title}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggleSelect?.(asset.id);
            }}
          >
            <CheckCircle2 size={15} />
          </button>
        ) : null}
        <button className="asset-card-hit" type="button" onClick={() => void openAsset(asset.id)}>
          <div className="resource-preview"><Preview asset={asset} mode="thumbnail" compact /></div>
          <div className="resource-copy">
            <span>{asset.resourceKindLabel || asset.mediaLabel}</span>
            <strong>{asset.title}</strong>
            <small><code>{asset.asset_code}</code>{asset.versionCount > 1 ? ` · ${asset.versionCount} 版` : null}</small>
          </div>
        </button>
      </article>
    );
  }
  return (
    <article className={classNames("report-card asset-card", selected && "is-selected")}>
      {selectable ? (
        <button
          className={classNames("select-toggle", selected && "is-selected")}
          type="button"
          aria-pressed={selected}
          aria-label={`${selected ? "取消选择" : "选择"} ${asset.title}`}
          onClick={(event) => {
            event.stopPropagation();
            onToggleSelect?.(asset.id);
          }}
        >
          <CheckCircle2 size={15} />
        </button>
      ) : null}
      <button className="asset-card-hit" type="button" onClick={() => void openAsset(asset.id)}>
        <div className="card-preview"><Preview asset={asset} mode="thumbnail" compact /></div>
        <div className="card-copy">
          <span>#{String(index + 1).padStart(3, "0")} · {asset.asset_type === "report" ? `${reportPageCount(asset)} 页` : roleForControl(asset)}</span>
          <strong>{asset.title}</strong>
          <small><code>{asset.asset_code}</code> · {asset.asset_type === "report" ? scenarioForReport(asset) : sourceTypeLabel(asset.source_type)}</small>
        </div>
      </button>
      <div className="card-footer">
        <div className="chips">
          {topTags(asset, 3).map((tag) => <em key={tag}>{tag}</em>)}
          {asset.asset_type === "report" && asset.storylineCount > 0 ? <em>故事线 {asset.storylineCount}</em> : null}
          {asset.versionCount > 1 ? <em>版本 {asset.versionCount}</em> : null}
        </div>
        <div className="card-actions">
          <button className="card-action is-muted" type="button" onClick={() => void onRename(asset)}>
            <Pencil size={13} />命名
          </button>
          {asset.asset_type === "report" ? (
            <button className="card-action" type="button" onClick={() => void onCollectStoryline(asset)}>
              <BookmarkPlus size={14} />收藏
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function ManualMergeDialog({ assets, close, mergeAssets }: {
  assets: Asset[];
  close: () => void;
  mergeAssets: (payload: { assetIds: string[]; primaryAssetId: string; mode: ManualMergeMode }) => Promise<void>;
}) {
  const [primaryAssetId, setPrimaryAssetId] = useState(assets[0]?.id || "");
  const [mode, setMode] = useState<ManualMergeMode>("version");
  const [busy, setBusy] = useState(false);
  const assetTypeLabel = assets[0]?.typeLabel || "素材";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!primaryAssetId || assets.length < 2) return;
    setBusy(true);
    try {
      await mergeAssets({
        assetIds: assets.map((asset) => asset.id),
        primaryAssetId,
        mode
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="modal-panel manual-merge-panel" onSubmit={(event) => void submit(event)}>
        <button className="icon-btn modal-close" type="button" onClick={close} aria-label="关闭"><X size={16} /></button>
        <header className="modal-head">
          <div>
            <code>{assetTypeLabel}</code>
            <h2>人工合并</h2>
            <p>选择一个主素材，其余素材会进入同一版本组。</p>
          </div>
        </header>
        <div className="manual-merge-body">
          <section className="manual-merge-list">
            {assets.map((asset) => (
              <button
                key={asset.id}
                className={classNames("manual-merge-item", primaryAssetId === asset.id && "active")}
                type="button"
                onClick={() => setPrimaryAssetId(asset.id)}
              >
                <span className="manual-merge-preview"><Preview asset={asset} mode="thumbnail" compact /></span>
                <span>
                  <strong>{asset.asset_code}</strong>
                  <small>{asset.title}</small>
                </span>
                <em>{primaryAssetId === asset.id ? "主" : `V${asset.version_no || 1}`}</em>
              </button>
            ))}
          </section>
          <section className="manual-merge-options">
            <h3>合并方式</h3>
            <button className={classNames(mode === "keep" && "active")} type="button" onClick={() => setMode("keep")}>
              <CheckCircle2 size={16} />
              <span><strong>保留一个</strong><small>主素材继续展示；页面引用会切到主素材。</small></span>
            </button>
            <button className={classNames(mode === "version" && "active")} type="button" onClick={() => setMode("version")}>
              <GitBranch size={16} />
              <span><strong>生成版本</strong><small>建立版本组；原有页面引用保持不变。</small></span>
            </button>
          </section>
        </div>
        <footer className="manual-merge-footer">
          <span>{assets.length} 个素材将合并为 1 个版本组</span>
          <button className="secondary" type="button" onClick={close}>取消</button>
          <button className="primary" type="submit" disabled={busy || !primaryAssetId}>{busy ? "合并中" : "确认合并"}</button>
        </footer>
      </form>
    </div>
  );
}

function PaginationBar({ pagination, loadAssets }: { pagination: Pagination; loadAssets: (page?: number, append?: boolean) => Promise<void> }) {
  if (!pagination.hasNext) return null;
  return (
    <div className="pagination">
      <button type="button" onClick={() => void loadAssets(pagination.page + 1, true)}>
        加载更多<ChevronRight size={15} />
      </button>
      <span>每次 {pagination.pageSize || ASSET_PAGE_SIZE} 条 · 第 {pagination.page} / {pagination.totalPages} 批</span>
    </div>
  );
}

function StorylineLibrary({ storylines, loading, copyText, openStoryline, openCreateReport }: { storylines: Storyline[]; loading: string; copyText: (text: string, message: string) => Promise<void>; openStoryline: (storyline: Storyline) => void; openCreateReport: () => Promise<void> }) {
  const body = !storylines.length ? <div className="empty-state">{loading}</div> : (
    <section className="storyline-grid">
      {storylines.map((item) => (
        <article className="storyline-card" key={item.id}>
          <button className="storyline-card-hit" type="button" onClick={() => openStoryline(item)}>
            <code>{item.code}</code>
            <h3>{item.title}</h3>
            <p>{item.scenario || item.tone}</p>
            <div className="chips">{(item.tags || []).slice(0, 4).map((tag) => <em key={tag}>{tag}</em>)}</div>
            {item.sourceReportCode ? <small>{item.sourceReportCode} · {item.versionLabel || "V1"} / 共 {item.versionCount || 1} 版</small> : null}
          </button>
          <footer>
            <button className="secondary" type="button" onClick={() => void copyText(item.code, "已复制故事线 ID")}><Copy size={14} />复制 ID</button>
          </footer>
        </article>
      ))}
    </section>
  );
  return (
    <>
      <section className="storyline-toolbar">
        <div><strong>{storylines.length} 条故事线</strong><span>新增汇报会生成独立素材和独立链接</span></div>
        <button className="primary" type="button" onClick={() => void openCreateReport()}><FileText size={15} />新增汇报素材</button>
      </section>
      {body}
    </>
  );
}

function StorylineReportDialog({
  storylines,
  controls,
  close,
  createReport,
  copyText
}: {
  storylines: Storyline[];
  controls: Asset[];
  close: () => void;
  createReport: (payload: { mode: StorylineReportMode; title: string; note?: string; firstControlId?: string; controlIds?: string[]; conversation?: string; storylineVersionId?: string }) => Promise<void>;
  copyText: (text: string, message: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<StorylineReportMode>("chat");
  const [title, setTitle] = useState(`新建汇报素材 ${new Date().toLocaleDateString("zh-CN")}`);
  const [note, setNote] = useState("");
  const [formulaText, setFormulaText] = useState("");
  const [firstControlId, setFirstControlId] = useState(controls[0]?.id || "");
  const storylineVersions = storylines.flatMap((item) => item.versions?.length ? item.versions : [item]).filter((item) => item.sourceReportId || item.outputReportId);
  const [storylineVersionId, setStorylineVersionId] = useState(storylineVersions[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const formulaTemplate = useMemo(() => defaultReportFormula(controls, title), [controls, title]);
  const controlCodes = useMemo(() => controlCodesFromText(formulaText || formulaTemplate), [formulaText, formulaTemplate]);
  const controlsByCode = useMemo(() => new Map(controls.map((asset) => [asset.asset_code.toUpperCase(), asset])), [controls]);
  const matchedControls = useMemo(() => controlCodes.map((code) => controlsByCode.get(code)).filter(Boolean) as Asset[], [controlCodes, controlsByCode]);
  const unknownControlCodes = controlCodes.filter((code) => !controlsByCode.has(code));
  useEffect(() => {
    if (!firstControlId && controls[0]) setFirstControlId(controls[0].id);
  }, [controls, firstControlId]);
  useEffect(() => {
    if (!formulaText && controls.length) setFormulaText(defaultReportFormula(controls, title));
  }, [controls, formulaText, title]);
  useEffect(() => {
    if (!storylineVersionId && storylineVersions[0]) setStorylineVersionId(storylineVersions[0].id);
  }, [storylineVersionId, storylineVersions]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (mode === "chat" && !matchedControls.length) return;
    if (mode === "manual" && !firstControlId) return;
    if (mode === "copy" && !storylineVersionId) return;
    setBusy(true);
    try {
      const conversation = formulaText.trim() || formulaTemplate;
      const typedTitle = title.trim();
      const parsedTitle = titleFromFormula(conversation, typedTitle);
      const finalTitle = mode === "chat" && (!typedTitle || typedTitle.startsWith("新建汇报素材")) ? parsedTitle : typedTitle;
      await createReport({
        mode,
        title: finalTitle,
        note,
        conversation: mode === "chat" ? conversation : undefined,
        controlIds: mode === "chat" ? matchedControls.map((asset) => asset.id) : undefined,
        firstControlId: mode === "manual" ? firstControlId : undefined,
        storylineVersionId: mode === "copy" ? storylineVersionId : undefined
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="import-panel storyline-report-panel" onSubmit={submit}>
        <header>
          <div>
            <span>REPORT</span>
            <h2>新增汇报素材</h2>
            <p>每次创建都会生成独立汇报素材、独立目录和独立链接。</p>
          </div>
          <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="storyline-mode">
          <button className={classNames(mode === "chat" && "active")} type="button" onClick={() => setMode("chat")}>对话公式生成</button>
          <button className={classNames(mode === "manual" && "active")} type="button" onClick={() => setMode("manual")}>人工新增首页</button>
          <button className={classNames(mode === "copy" && "active")} type="button" onClick={() => setMode("copy")}>复制故事线版本</button>
        </div>
        <label className="import-field">
          <span>汇报素材标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入汇报素材标题" />
        </label>
        {mode === "chat" ? (
          <DetailSection title="平台交互提示词">
            <textarea className="copy-prompt chat-formula" value={formulaText} onChange={(event) => setFormulaText(event.target.value)} />
            <div className="formula-actions">
              <button className="secondary" type="button" onClick={() => void copyText(formulaText || formulaTemplate, "已复制快捷公式")}><Copy size={14} />复制公式</button>
              <button className="secondary" type="button" onClick={() => setFormulaText(formulaTemplate)}><Sparkles size={14} />填入默认公式</button>
            </div>
            <div className="matched-controls">
              <strong>已识别页面素材</strong>
              {matchedControls.length ? (
                <div className="matched-list">
                  {matchedControls.map((asset, index) => <span key={asset.id}>{index + 1}. {asset.asset_code} · {asset.title}</span>)}
                </div>
              ) : <p>把页面素材编号粘贴到公式里，例如 CTRL-20260704-001-001。</p>}
              {unknownControlCodes.length ? <p className="formula-warning">未找到：{unknownControlCodes.join("、")}</p> : null}
            </div>
          </DetailSection>
        ) : mode === "manual" ? (
          <label className="import-field">
            <span>首页页面素材</span>
            <select value={firstControlId} onChange={(event) => setFirstControlId(event.target.value)}>
              {controls.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_code} · {asset.title}</option>)}
            </select>
          </label>
        ) : (
          <label className="import-field">
            <span>故事线版本</span>
            <select value={storylineVersionId} onChange={(event) => setStorylineVersionId(event.target.value)}>
              {storylineVersions.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.versionLabel || "V1"} · {item.title}</option>)}
            </select>
          </label>
        )}
        <label className="import-field">
          <span>备注</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="创建原因、受众、约束，可留空" />
        </label>
        <div className="import-note">
          <AlertCircle size={15} />
          <span>新增汇报不会覆盖故事线版本，也不会覆盖来源汇报；复制模式会复制文件到新的独立目录。</span>
        </div>
        <footer>
          <button className="primary" type="submit" disabled={busy || (mode === "chat" && !matchedControls.length) || (mode === "manual" && !firstControlId) || (mode === "copy" && !storylineVersionId)}>{busy ? "正在创建" : "创建汇报素材"}</button>
          <button className="secondary" type="button" onClick={close}>取消</button>
        </footer>
      </form>
    </div>
  );
}

function StorylineCollectionDialog({
  asset,
  storylines,
  close,
  createStoryline
}: {
  asset: Asset;
  storylines: Storyline[];
  close: () => void;
  createStoryline: (payload: { title: string; note?: string; mode: StorylineCollectMode; targetStorylineId?: string }) => Promise<void>;
}) {
  const [mode, setMode] = useState<StorylineCollectMode>("new");
  const [title, setTitle] = useState(asset.title.replace(/｜完整汇报材料$/, ""));
  const [targetStorylineId, setTargetStorylineId] = useState(storylines[0]?.id || "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedStoryline = storylines.find((item) => item.id === targetStorylineId);
  useEffect(() => {
    if (mode === "version" && !targetStorylineId && storylines[0]) {
      setTargetStorylineId(storylines[0].id);
    }
  }, [mode, storylines, targetStorylineId]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (mode === "version" && !targetStorylineId) return;
    setBusy(true);
    try {
      await createStoryline({
        title: title.trim() || selectedStoryline?.title || asset.title,
        note,
        mode,
        targetStorylineId: mode === "version" ? targetStorylineId : undefined
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="import-panel storyline-panel" onSubmit={submit}>
        <header>
          <div>
            <span>STORYLINE</span>
            <h2>收藏为故事线</h2>
            <p>当前汇报可以新建故事线，也可以作为已有故事线的新版本；不会新增汇报材料。</p>
          </div>
          <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="storyline-source">
          <code>{asset.asset_code}</code>
          <strong>{asset.title}</strong>
        </div>
        <label className="import-field">
          <span>故事线名称</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入故事线名称" />
        </label>
        <div className="storyline-mode">
          <button className={classNames(mode === "new" && "active")} type="button" onClick={() => setMode("new")}>新建故事线</button>
          <button className={classNames(mode === "version" && "active")} type="button" onClick={() => setMode("version")}>更新已有故事线版本</button>
        </div>
        {mode === "version" ? (
          <label className="import-field">
            <span>选择故事线</span>
            <select value={targetStorylineId} onChange={(event) => setTargetStorylineId(event.target.value)}>
              {storylines.map((item) => (
                <option key={item.id} value={item.id}>{item.code} · {item.title} · 当前 {item.versionLabel || "V1"}</option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="import-field">
          <span>备注</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="收藏原因、适用场景，可留空" />
        </label>
        <div className="import-note">
          <AlertCircle size={15} />
          <span>故事线版本只写 MineM 元数据；来源汇报和原始素材生成方式都不会被改写。</span>
        </div>
        <footer>
          <button className="primary" type="submit" disabled={busy || (mode === "version" && !targetStorylineId)}>{busy ? "正在收藏" : "确认收藏"}</button>
          <button className="secondary" type="button" onClick={close}>取消</button>
        </footer>
      </form>
    </div>
  );
}

function PresenterActionDialog({ asset, status, close, editScript, enterPresenter }: {
  asset: Asset;
  status: PresenterScriptStatus;
  close: () => void;
  editScript: () => void;
  enterPresenter: () => void;
}) {
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <section className="import-panel presenter-choice-panel">
        <header>
          <div>
            <span>AI SPEAKER</span>
            <h2>AI 演讲台</h2>
            <p>当前汇报已导入 {status.scriptCount || 0} 页演讲稿。</p>
          </div>
          <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="storyline-source">
          <code>{asset.asset_code}</code>
          <strong>{asset.title}</strong>
        </div>
        <div className="presenter-choice-actions">
          <button className="secondary" type="button" onClick={editScript}><FileText size={17} /><span>编辑演讲稿</span></button>
          <button className="primary" type="button" onClick={enterPresenter}><Sparkles size={17} /><span>进入演讲台</span></button>
        </div>
      </section>
    </div>
  );
}

function PresenterScriptDialog({ asset, status, editing, close, saveScript, generateScript, extractScriptFile }: {
  asset: Asset;
  status?: PresenterScriptStatus;
  editing?: boolean;
  close: () => void;
  saveScript: (payload: { sourceType: PresenterScriptSource; minutesUrl?: string; script: string }) => Promise<void>;
  generateScript: (asset: Asset) => Promise<string>;
  extractScriptFile: (asset: Asset, file: File) => Promise<string>;
}) {
  const [sourceType, setSourceType] = useState<PresenterScriptSource>(editing ? "script" : "minutes");
  const [minutesUrl, setMinutesUrl] = useState(status?.minutesUrl || "");
  const [script, setScript] = useState(status?.scriptText || "");
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState<"" | "generate" | "file">("");
  const [scriptFileName, setScriptFileName] = useState("");
  const canSubmit = script.trim().length > 0 && (sourceType === "script" || minutesUrl.trim().length > 0);
  const generateDraft = async () => {
    if (draftBusy) return;
    setDraftBusy("generate");
    try {
      const generated = await generateScript(asset);
      if (generated) {
        setSourceType("script");
        setScript(generated);
        setScriptFileName("");
      }
    } finally {
      setDraftBusy("");
    }
  };
  const importScriptFile = async (file?: File | null) => {
    if (!file || draftBusy) return;
    setDraftBusy("file");
    try {
      const extracted = await extractScriptFile(asset, file);
      if (extracted) {
        setSourceType("script");
        setScript(extracted);
        setScriptFileName(file.name);
      }
    } finally {
      setDraftBusy("");
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit || busy) return;
    setBusy(true);
    try {
      await saveScript({
        sourceType,
        minutesUrl: sourceType === "minutes" ? minutesUrl.trim() : "",
        script: script.trim()
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="import-panel presenter-script-panel" onSubmit={submit}>
        <header>
          <div>
            <span>AI SPEAKER</span>
            <h2>{editing ? "编辑演讲稿" : "导入演讲稿"}</h2>
            <p>{editing ? "修改后会覆盖 AI 演讲台里的讲稿，不改原汇报素材。" : "当前汇报还没有演讲稿。导入后会写入 AI 演讲台，不改原汇报素材。"}</p>
          </div>
          <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="storyline-source">
          <code>{asset.asset_code}</code>
          <strong>{asset.title}</strong>
        </div>
        <div className="storyline-mode presenter-source-mode">
          <button className={classNames(sourceType === "minutes" && "active")} type="button" onClick={() => setSourceType("minutes")}><Link size={14} />飞书妙记</button>
          <button className={classNames(sourceType === "script" && "active")} type="button" onClick={() => setSourceType("script")}><FileText size={14} />演讲稿</button>
        </div>
        <div className="presenter-draft-tools">
          <button className="secondary" type="button" disabled={!!draftBusy} onClick={() => void generateDraft()}>
            {draftBusy === "generate" ? <Loader2 size={14} /> : <Sparkles size={14} />}
            生成演讲稿
          </button>
          <label className={classNames("secondary", draftBusy && "disabled")}>
            {draftBusy === "file" ? <Loader2 size={14} /> : <Upload size={14} />}
            导入 PDF/MD
            <input
              type="file"
              accept=".pdf,.md,.markdown,.txt"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0] || null;
                event.currentTarget.value = "";
                void importScriptFile(file);
              }}
            />
          </label>
        </div>
        {scriptFileName ? <p className="presenter-file-name">已导入：{scriptFileName}</p> : null}
        {sourceType === "minutes" ? (
          <label className="import-field">
            <span>飞书妙记链接</span>
            <input value={minutesUrl} onChange={(event) => setMinutesUrl(event.target.value)} placeholder="粘贴飞书妙记链接或 token" />
          </label>
        ) : null}
        <label className="import-field">
          <span>{sourceType === "minutes" ? "妙记整理内容" : "演讲稿正文"}</span>
          <textarea
            className="script-textarea"
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder="支持 Page 01: ... / 第1页：...；没有页码标记时，AI 会结合每页标题、章节和页面内容自动分页。"
          />
        </label>
        <div className="import-note">
          <AlertCircle size={15} />
          <span>飞书妙记暂不自动拉取内容；粘贴带时间戳的转写稿即可，系统会清理时间戳、自动分页，并补足页间衔接。</span>
        </div>
        <footer>
          <button className="primary" type="submit" disabled={busy || !canSubmit}>{busy ? "正在保存" : editing ? "保存并打开" : "导入并打开"}</button>
          <button className="secondary" type="button" onClick={close}>取消</button>
        </footer>
      </form>
    </div>
  );
}

function StorylineSourcePreview({ source }: { source?: Storyline["sourceReport"] }) {
  if (!source?.preview_url) return <div className="preview-fallback">暂无来源材料预览</div>;
  if (source.media_kind === "video") return <video src={source.preview_url} controls muted playsInline />;
  if (["image", "gif", "svg"].includes(source.media_kind)) return <img src={source.preview_url} alt={source.title} loading="lazy" />;
  const src = source.asset_type === "report" && source.id
    ? `/api/reports/${encodeURIComponent(source.id)}/arrangement/viewer?embed=1`
    : `${source.preview_url}${source.preview_url.includes("?") ? "&" : "?"}embed=1`;
  return <iframe src={src} title={source.title} loading="lazy" />;
}

function StorylineModal({ storyline, close, copyText, openAsset }: {
  storyline: Storyline;
  close: () => void;
  copyText: (text: string, message: string) => Promise<void>;
  openAsset: (assetId: string) => Promise<void>;
}) {
  const versions = storyline.versions?.length ? storyline.versions : [storyline];
  const [activeVersionId, setActiveVersionId] = useState(storyline.id);
  useEffect(() => setActiveVersionId(storyline.id), [storyline.id]);
  const active = versions.find((item) => item.id === activeVersionId) || storyline;
  const fixedBlocks = active.fixedBlocks || [];
  const directory = active.directory || [];
  const source = active.sourceReport || storyline.sourceReport;
  return (
    <div className="modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <section className="modal-panel storyline-detail-panel">
        <button className="icon-btn modal-close" type="button" onClick={close} aria-label="关闭"><X size={16} /></button>
        <header className="modal-head">
          <div>
            <code>{storyline.code}</code>
            <h2>{storyline.title}</h2>
            <p>{active.versionLabel || "V1"} / 共 {storyline.versionCount || versions.length || 1} 版 · {active.scenario || active.tone || "故事线"}</p>
          </div>
          <div className="modal-actions">
            {active.sourceReportId ? <button className="secondary" type="button" onClick={() => void openAsset(active.sourceReportId!)}><FileText size={14} />查看来源汇报</button> : null}
            <button className="secondary" type="button" onClick={() => void copyText(storyline.code, "已复制故事线 ID")}><Copy size={14} />复制 ID</button>
          </div>
        </header>
        <div className="storyline-detail-body">
          <section className="storyline-material-panel">
            <header>
              <span>来源材料</span>
              <strong>{source?.asset_code || active.sourceReportCode || "未关联来源汇报"}</strong>
            </header>
            <div className="storyline-material-preview"><StorylineSourcePreview source={source} /></div>
            <p>{source?.title || active.sourceReportCode || "暂无来源材料标题"}</p>
          </section>
          <div className="storyline-detail-stack">
            <DetailSection title="版本">
              <div className="storyline-version-list">
                {versions.map((version) => (
                  <button key={version.id} className={classNames(active.id === version.id && "active")} type="button" onClick={() => setActiveVersionId(version.id)}>
                    <span>{version.versionLabel || `V${version.versionNo || 1}`}</span>
                    <strong>{version.sourceReportCode || "来源汇报"}</strong>
                    <small>{formatTime(version.createdAt)}</small>
                  </button>
                ))}
              </div>
            </DetailSection>
            <DetailSection title="基础信息">
              <div className="storyline-info-grid">
                <div><span>故事线 ID</span><strong>{active.code}</strong></div>
                <div><span>创建时间</span><strong>{formatTime(active.createdAt)}</strong></div>
              </div>
            </DetailSection>
            {active.note || active.scenario ? <DetailSection title="备注"><p>{active.note || active.scenario}</p></DetailSection> : null}
            {(active.tags || []).length ? <DetailSection title="标签"><div className="chips">{active.tags.map((tag) => <em key={tag}>{tag}</em>)}</div></DetailSection> : null}
            {fixedBlocks.length || directory.length ? (
              <details className="storyline-more-info">
                <summary>更多结构信息</summary>
                {fixedBlocks.length ? <div><h4>固定内容</h4><ul className="storyline-block-list">{fixedBlocks.map((block, index) => <li key={`${block}-${index}`}>{block}</li>)}</ul></div> : null}
                {directory.length ? <div><h4>目录结构</h4><div className="storyline-directory">{directory.map((section, index) => (
                  <section key={`${section.title}-${index}`}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{section.title}</strong>
                    <small>{section.role}</small>
                    {section.defaultContent?.length ? <p>{section.defaultContent.join(" / ")}</p> : null}
                  </section>
                ))}</div></div> : null}
              </details>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function AssetModal({ asset, lineage, setLineage, close, copyText, refreshAsset, startTagAnalysis, renameAsset, deleteAsset, openLineage, collectStoryline, openAiPresenter, openArrangement }: {
  asset: Asset;
  lineage: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null;
  setLineage: (value: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null) => void;
  close: () => void;
  copyText: (text: string, message: string) => Promise<void>;
  refreshAsset: (assetId: string) => Promise<void>;
  startTagAnalysis: (asset: Asset) => Promise<void>;
  renameAsset: (asset: Asset) => Promise<void>;
  deleteAsset: (asset: Asset) => Promise<void>;
  openLineage: (assetId: string, sectionKey: string, groupKey?: string) => Promise<void>;
  collectStoryline: (asset: Asset) => Promise<void>;
  openAiPresenter: (asset: Asset) => Promise<void>;
  openArrangement: (asset: Asset) => void;
}) {
  const [previewRefreshKey, setPreviewRefreshKey] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);
  const [versions, setVersions] = useState<Asset[]>([]);
  const [activeAsset, setActiveAsset] = useState(asset);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const previewContainerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let cancelled = false;
    setActiveAsset(asset);
    setVersionsLoading(true);
    void api.assetVersions(asset.id).then((data) => {
      if (cancelled) return;
      setVersions(data.ok === false ? [asset] : data.versions || [asset]);
      setVersionsLoading(false);
    }).catch(() => {
      if (!cancelled) {
        setVersions([asset]);
        setVersionsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [asset]);
  const refreshPreview = async () => {
    setPreviewRefreshKey((value) => value + 1);
    await refreshAsset(activeAsset.id);
  };
  const detailMeta = [activeAsset.typeLabel, activeAsset.mediaLabel].filter(Boolean).join(" · ");
  const chooseVersion = (version: Asset) => {
    setActiveAsset(version);
    setLineage(null);
    setPreviewRefreshKey((value) => value + 1);
  };
  return (
    <div className="modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <section className={classNames("modal-panel", `is-${asset.asset_type}`)}>
        <button className="icon-btn modal-close" type="button" onClick={close} aria-label="关闭"><X size={16} /></button>
        <header className="modal-head">
          <div>
            <code>{activeAsset.asset_code}</code>
            <h2>{activeAsset.title}</h2>
            <p>{detailMeta}</p>
          </div>
          <div className="modal-actions">
            {activeAsset.preview_url ? <button className="icon-btn" type="button" onClick={() => void copyText(absoluteUrl(activeAsset.preview_url), "已复制链接")} title="复制链接" aria-label="复制链接"><Link size={15} /></button> : null}
            <button className="icon-btn" type="button" onClick={() => void refreshPreview()} title="刷新页面" aria-label="刷新页面"><RefreshCw size={15} /></button>
            {activeAsset.preview_url ? <button className="icon-btn" type="button" onClick={() => void previewContainerRef.current?.requestFullscreen()} title="全屏预览" aria-label="全屏预览"><Maximize2 size={15} /></button> : null}
            <details className="modal-more-menu">
              <summary className="icon-btn" title="更多操作" aria-label="更多操作"><MoreHorizontal size={17} /></summary>
              <div>
                {activeAsset.asset_type === "report" ? <button type="button" onClick={() => void collectStoryline(activeAsset)}><BookmarkPlus size={14} />收藏</button> : null}
                {activeAsset.asset_type === "report" && activeAsset.preview_url ? <button type="button" onClick={() => void openAiPresenter(activeAsset)}><Sparkles size={14} />AI演讲台</button> : null}
                {activeAsset.asset_type === "report" ? <button type="button" onClick={() => openArrangement(activeAsset)}><Grid2X2 size={14} />编排</button> : null}
                {activeAsset.asset_type === "report" ? <button type="button" onClick={() => setExportOpen(true)}><Download size={14} />导出</button> : null}
                <button type="button" onClick={() => void startTagAnalysis(activeAsset)}><Sparkles size={14} />分析内容</button>
                <button type="button" onClick={() => void renameAsset(activeAsset)}><Pencil size={14} />命名</button>
                {activeAsset.preview_url ? <a href={absoluteUrl(activeAsset.preview_url)} target="_blank" rel="noreferrer"><Link size={14} />打开链接</a> : null}
                <button type="button" onClick={() => void copyText(activeAsset.asset_code, "已复制素材 ID")}><Clipboard size={14} />复制 ID</button>
                <button className="danger-item" type="button" onClick={() => void deleteAsset(activeAsset)}><Trash2 size={14} />删除</button>
              </div>
            </details>
          </div>
        </header>
        <div className="modal-body">
          <div className="modal-preview" ref={previewContainerRef}><Preview key={`${activeAsset.id}-${previewRefreshKey}`} asset={activeAsset} mode="interactive" /></div>
          <aside className="detail-stack detail-sidebar">
            <DetailSection title="概览"><p>{activeAsset.usage || "未填写适用场景"}</p>
              {(activeAsset.tags || []).length ? <div className="chips">{activeAsset.tags.map((tag) => <em key={tag}>{tag}</em>)}</div> : null}
            </DetailSection>
            <section className="detail-section version-panel">
              <div className="version-panel-head"><h3>版本</h3><span>{versions.length || activeAsset.versionCount || 1} 版</span></div>
              <div className="version-list">
                {versionsLoading ? <p className="version-loading">正在读取历史版本…</p> : versions.map((version) => <button key={version.id} type="button" className={classNames("version-item", version.id === activeAsset.id && "is-active")} onClick={() => chooseVersion(version)}>
                  <span className="version-thumb"><Preview asset={version} mode="thumbnail" compact /></span>
                  <span className="version-copy"><strong>{version.versionLabel || `V${version.version_no || 1}`}{version.id === activeAsset.id ? " · 当前预览" : ""}</strong><small>{formatTime(version.updated_at)} · {sourceTypeLabel(version.source_type)}</small></span>
                </button>)}</div>
              {!versionsLoading && versions.length <= 1 ? <p className="version-empty">当前素材暂无历史版本</p> : null}
            </section>
            <details className="detail-source">
              <summary>来源与关系</summary>
              <LineageSectionView asset={activeAsset} openLineage={openLineage} />
            </details>
          </aside>
        </div>
        {lineage ? <LineageDrawer lineage={lineage} setLineage={setLineage} /> : null}
      </section>
      {exportOpen ? <ReportExportDialog asset={activeAsset} close={() => setExportOpen(false)} /> : null}
    </div>
  );
}

function ReportExportDialog({ asset, close }: { asset: Asset; close: () => void }) {
  const [task, setTask] = useState<ReportExportTask | null>(null);
  const [starting, setStarting] = useState(false);
  const start = async (format: "html" | "pdf") => {
    setStarting(true);
    const data = await api.createReportExport(asset.id, format);
    setStarting(false);
    if (data.ok === false || !data.task) return;
    setTask(data.task);
  };
  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed") return;
    const timer = window.setInterval(() => {
      void api.reportExportTask(task.id).then((data) => {
        if (data.ok !== false && data.task) setTask(data.task);
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [task?.id, task?.status]);
  const pending = task && (task.status === "queued" || task.status === "running");
  return <div className="modal" role="dialog" aria-modal="true">
    <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
    <section className="modal-panel confirm-panel export-panel">
      <header><div><code>完整汇报</code><h2>导出汇报</h2><p>仅导出已确认编排中可见的页面。</p></div><button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={16} /></button></header>
      {!task ? <div className="export-format-grid">
        <button className="export-format-card" type="button" disabled={starting} onClick={() => void start("html")}><FileArchive size={22} /><strong>HTML</strong><span>离线压缩包，图片、视频、GIF 保持原始文件。</span></button>
        <button className="export-format-card" type="button" disabled={starting} onClick={() => void start("pdf")}><FileText size={22} /><strong>PDF</strong><span>逐页等待渲染完成后生成静态 PDF。</span></button>
      </div> : <div className="export-progress">
        <span>{task.format.toUpperCase()} · {task.pageCount} 页</span><strong>{task.status === "completed" ? "导出完成" : task.status === "failed" ? "导出失败" : task.message || "正在导出"}</strong>
        <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
        {task.error ? <p className="error-text">{task.error}</p> : null}
        {pending ? <small>后台处理中，可继续浏览素材库。</small> : null}
        {task.status === "completed" && task.downloadUrl ? <a className="primary" href={task.downloadUrl}><Download size={15} />下载文件</a> : null}
        {task.status === "failed" ? <button className="secondary" type="button" onClick={() => setTask(null)}>重新导出</button> : null}
      </div>}
    </section>
  </div>;
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function ReportArrangementWorkspace({ asset, close, showToast, refreshAsset }: { asset: Asset; close: () => void; showToast: (text: string) => void; refreshAsset: (assetId: string) => Promise<void> }) {
  const [arrangement, setArrangement] = useState<ReportArrangement | null>(null);
  const [draggedId, setDraggedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAssets, setPickerAssets] = useState<Asset[]>([]);
  const [pickerPage, setPickerPage] = useState(0);
  const [pickerHasNext, setPickerHasNext] = useState(true);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickedIds, setPickedIds] = useState<Set<string>>(() => new Set());
  const [insertedIds, setInsertedIds] = useState<string[]>([]);
  const [removedIds, setRemovedIds] = useState<string[]>([]);
  const [confirmClose, setConfirmClose] = useState(false);
  const original = useRef("");
  useEffect(() => {
    void api.reportArrangement(asset.id).then((data) => {
      if (data.ok === false) showToast(data.error || "无法加载页面编排");
      else { setArrangement(data); original.current = JSON.stringify(data.pages.map((page) => [page.id, page.hidden])); }
    });
  }, [asset.id, showToast]);
  const dirty = Boolean(arrangement && (insertedIds.length || removedIds.length || JSON.stringify(arrangement.pages.map((page) => [page.id, page.hidden])) !== original.current));
  const loadPicker = async (page: number, reset = false) => {
    if (pickerLoading || (!reset && !pickerHasNext)) return;
    setPickerLoading(true);
    const data = await api.assets({ view: "list", type: "control", page, page_size: 20, q: pickerQuery || undefined });
    setPickerAssets((current) => reset ? data.assets : [...current, ...data.assets.filter((item) => !current.some((existing) => existing.id === item.id))]);
    setPickerPage(page);
    setPickerHasNext(Boolean(data.pagination?.hasNext));
    setPickerLoading(false);
  };
  const openPicker = () => { setPickerOpen(true); setPickedIds(new Set()); setPickerAssets([]); setPickerPage(0); setPickerHasNext(true); void loadPicker(1, true); };
  const insertPicked = () => {
    if (!arrangement || !pickedIds.size) return;
    const inserted = pickerAssets.filter((item) => pickedIds.has(item.id)).map((item, index) => ({
      id: item.id, slotNumber: 0, order: arrangement.pages.length + index + 1, title: item.title, code: item.asset_code,
      previewUrl: item.preview_url, thumbnailUrl: item.thumbnail_url || item.preview_url, hidden: false
    }));
    setArrangement({ ...arrangement, pages: [...arrangement.pages, ...inserted] });
    setInsertedIds((current) => [...current, ...inserted.map((item) => item.id)]);
    setPickerOpen(false);
  };
  const confirm = async (): Promise<boolean> => {
    if (!arrangement) return false;
    setBusy(true);
    try {
      const requestedOrder = arrangement.pages.map((page) => page.id);
      const requestedHidden = arrangement.pages.filter((page) => page.hidden).map((page) => page.id);
      const data = await api.updateReportArrangement(asset.id, { pageOrder: requestedOrder, hiddenPageIds: requestedHidden, insertedControlIds: insertedIds, removedPageIds: removedIds });
      if (data.ok === false) { showToast(data.error || "编排更新失败"); return false; }
      const verified = await api.reportArrangement(asset.id);
      const verifiedOrder = verified.ok === false ? [] : verified.pages.map((page) => page.id);
      const verifiedHidden = verified.ok === false ? [] : verified.pages.filter((page) => page.hidden).map((page) => page.id);
      if (verified.ok === false || JSON.stringify(verifiedOrder) !== JSON.stringify(data.pages.map((page) => page.id)) || JSON.stringify(verifiedHidden) !== JSON.stringify(data.pages.filter((page) => page.hidden).map((page) => page.id))) {
        showToast("编排尚未完全生效，请稍后重试");
        return false;
      }
      const viewer = await fetch(`${data.previewUrl}${data.previewUrl.includes("?") ? "&" : "?"}v=${encodeURIComponent(String(data.updatedAt || Date.now()))}`, { cache: "no-store" });
      if (!viewer.ok) { showToast("编排已保存，但预览刷新失败"); return false; }
      setArrangement(verified);
      setInsertedIds([]);
      setRemovedIds([]);
      original.current = JSON.stringify(verified.pages.map((page) => [page.id, page.hidden]));
      await refreshAsset(asset.id);
      showToast("编排已确认并生效");
      return true;
    } catch {
      showToast("编排生效失败，请稍后重试");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const move = (targetId: string) => {
    if (!arrangement || !draggedId || draggedId === targetId) return;
    const pages = [...arrangement.pages];
    const from = pages.findIndex((page) => page.id === draggedId);
    const to = pages.findIndex((page) => page.id === targetId);
    if (from < 0 || to < 0) return;
    const [item] = pages.splice(from, 1);
    pages.splice(to, 0, item);
    setDraggedId("");
    setArrangement({ ...arrangement, pages });
  };
  const removePage = (pageId: string) => {
    if (!arrangement || arrangement.pages.length <= 1) {
      showToast("汇报至少需要保留一页");
      return;
    }
    setArrangement({ ...arrangement, pages: arrangement.pages.filter((page) => page.id !== pageId) });
    if (insertedIds.includes(pageId)) {
      setInsertedIds((current) => current.filter((id) => id !== pageId));
    } else {
      setRemovedIds((current) => current.includes(pageId) ? current : [...current, pageId]);
    }
  };
  const requestClose = () => dirty ? setConfirmClose(true) : close();
  return <section className="arrangement-workspace" aria-label="汇报页面编排">
    <header className="arrangement-toolbar"><div><button className="icon-btn" title="返回汇报" aria-label="返回汇报" type="button" onClick={requestClose}><ChevronRight className="back-icon" size={18} /></button><code>页面编排</code><h2>{asset.title}</h2></div><div className="modal-actions"><button className="secondary" type="button" disabled={busy} onClick={openPicker}><Plus size={16} />插入页面</button><button className="primary" type="button" disabled={!dirty || busy} onClick={() => void confirm()}>{busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{busy ? "正在生效" : "确认编排"}</button></div></header>
    <div className="arrangement-grid arrangement-workspace-grid">
      {!arrangement ? <div className="empty-state">正在加载页面…</div> : arrangement.pages.map((page, index) => <article key={`${page.id}-${index}`} className={classNames("arrangement-page", page.hidden && "is-hidden")} draggable={!busy} onDragStart={() => setDraggedId(page.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => move(page.id)}>
          <div className="arrangement-thumb"><img src={page.thumbnailUrl} alt={page.title} loading="lazy" /></div>
          <div><span>#{String(index + 1).padStart(2, "0")}</span><strong>{page.title}</strong><small>{page.code}</small></div>
          <div className="arrangement-actions"><GripVertical size={16} /><button className="icon-btn" type="button" title={page.hidden ? "恢复页面" : "隐藏页面"} aria-label={page.hidden ? "恢复页面" : "隐藏页面"} onClick={() => setArrangement({ ...arrangement, pages: arrangement.pages.map((item, itemIndex) => itemIndex === index ? { ...item, hidden: !item.hidden } : item) })}>{page.hidden ? <Eye size={15} /> : <EyeOff size={15} />}</button><button className="icon-btn danger-icon" type="button" title="从当前汇报移出" aria-label="从当前汇报移出" onClick={() => removePage(page.id)}><Trash2 size={15} /></button></div>
        </article>)}</div>
    {pickerOpen ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={() => setPickerOpen(false)} aria-label="关闭" /><section className="modal-panel page-picker-panel"><header className="modal-head"><div><code>页面素材</code><h2>批量插入页面</h2></div><div className="modal-actions"><input value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void loadPicker(1, true)} placeholder="搜索页面素材" /><button className="icon-btn" onClick={() => setPickerOpen(false)} aria-label="关闭"><X size={16} /></button></div></header><div className="page-picker-grid" onScroll={(event) => { const el = event.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 160) void loadPicker(pickerPage + 1); }}>{pickerAssets.map((item) => <button key={item.id} type="button" className={classNames("page-picker-card", pickedIds.has(item.id) && "is-selected")} onClick={() => setPickedIds((current) => { const next = new Set(current); next.has(item.id) ? next.delete(item.id) : next.add(item.id); return next; })}><img src={item.thumbnail_url || item.preview_url} alt="" loading="lazy" /><span>{item.title}</span><small>{item.asset_code}</small></button>)}{pickerLoading ? <div className="empty-state">正在加载…</div> : null}</div><footer className="modal-actions"><span>{pickedIds.size} 页已选择</span><button className="primary" disabled={!pickedIds.size} type="button" onClick={insertPicked}><Plus size={16} />插入所选页面</button></footer></section></div> : null}
    {confirmClose ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={() => setConfirmClose(false)} aria-label="继续编辑" /><section className="modal-panel confirm-panel"><h2>是否保存编排？</h2><p>当前顺序、隐藏、移出和插入页面尚未生效。</p><footer><button className="secondary" disabled={busy} onClick={() => close()}>放弃修改</button><button className="secondary" disabled={busy} onClick={() => setConfirmClose(false)}>继续编辑</button><button className="primary" disabled={busy} onClick={() => void confirm().then((saved) => { if (saved) close(); })}>{busy ? "正在生效" : "保存编排"}</button></footer></section></div> : null}
  </section>;
}

function LineageSectionView({ asset, openLineage }: { asset: Asset; openLineage: (assetId: string, sectionKey: string, groupKey?: string) => Promise<void> }) {
  const batch = asset.sourceBatch;
  const batchCounts = batch ? `汇报 ${batch.typeCounts?.report || 0} / 页面 ${batch.typeCounts?.control || 0} / 资源 ${batch.typeCounts?.resource || 0}` : "无批次";
  const resourceKinds = batch?.resourceCounts ? Object.entries(batch.resourceCounts).map(([key, count]) => `${key} ${count}`).join(" / ") : "无资源细分";
  const fields = [
    ["current-stage", "当前层级", asset.typeLabel],
    ["source-action", "生成动作", sourceTypeLabel(asset.source_type)],
    ["source-batch", "原数据批次", batch?.filename || asset.upload_id || "未记录"],
    ["batch-output", "批次产物", batchCounts],
    ["created-at", "入库时间", formatTime(batch?.createdAt || asset.created_at)],
    ["resource-breakdown", "资源细分", resourceKinds]
  ];
  return (
    <section className="detail-section lineage-section">
      <h3>原数据链路</h3>
      <div className="lineage-grid">
        {fields.map(([key, label, value]) => (
          <button key={key} type="button" onClick={() => void openLineage(asset.id, key)}>
            <span>{label}</span>
            <strong>{value}</strong>
          </button>
        ))}
      </div>
      <button className="lineage-path" type="button" onClick={() => void openLineage(asset.id, "source-path")}>{asset.source_path || "原始路径未记录"}</button>
    </section>
  );
}

function LineageDrawer({ lineage, setLineage }: { lineage: { section: LineageSection; items: LineageItem[]; selectedIndex: number }; setLineage: (value: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null) => void }) {
  const selected = lineage.items[lineage.selectedIndex];
  return (
    <div className="lineage-drawer-shell">
      <aside className="lineage-list">
        <header>
          <div><span>{lineage.section.label}</span><h3>{lineage.section.label}</h3></div>
          <button className="icon-btn" type="button" onClick={() => setLineage(null)}><X size={14} /></button>
        </header>
        <div>
          {lineage.items.length ? lineage.items.map((item, index) => (
            <button key={`${item.id || item.assetCode || index}`} className={classNames(index === lineage.selectedIndex && "active")} type="button" onClick={() => setLineage({ ...lineage, selectedIndex: index })}>
              <strong>{item.assetCode || item.title || item.id}</strong>
              <span>{item.title || "未命名素材"}</span>
              <small>{[item.typeLabel, item.resourceKindLabel, item.sourcePath].filter(Boolean).join(" / ")}</small>
            </button>
          )) : <p>该项是汇报入口统计值，没有独立素材记录。</p>}
        </div>
      </aside>
      <aside className="lineage-detail">
        {selected ? (
          <>
            <header>
              <span>{selected.typeLabel || "关联素材"}</span>
              <h3>{selected.assetCode || selected.title || selected.id}</h3>
              <p>{selected.title || "未命名素材"}</p>
            </header>
            <dl>
              <div><dt>类型</dt><dd>{[selected.typeLabel, selected.resourceKindLabel].filter(Boolean).join(" / ") || "未记录"}</dd></div>
              <div><dt>来源路径</dt><dd>{selected.sourcePath || "未记录"}</dd></div>
              <div><dt>生成动作</dt><dd>{sourceTypeLabel(selected.sourceType)}</dd></div>
              <div><dt>更新时间</dt><dd>{formatTime(selected.updatedAt || selected.createdAt)}</dd></div>
            </dl>
            <div className="lineage-preview"><LineagePreview item={selected} /></div>
            {selected.previewUrl ? <a className="primary" href={absoluteUrl(selected.previewUrl)} target="_blank" rel="noreferrer">打开链接</a> : null}
          </>
        ) : <div className="empty-state">暂无关联数据</div>}
      </aside>
    </div>
  );
}

export default App;
