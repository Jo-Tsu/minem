import {
  BookmarkPlus,
  Box,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Check,
  Download,
  Eye,
  EyeOff,
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
  Trash2,
  Upload,
  X
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { absoluteUrl, api } from "./api";
import { startImportTaskPolling } from "./import-task-polling";
import { CaseControlLibrary } from "./components/CaseControlLibrary";
import { ImportDialog, ImportTaskDock, ImportHistoryDialog } from "./components/ImportWidgets";
import type { ImportMode } from "./components/ImportWidgets";
import { Workbench } from "./components/Workbench";
import { ReportDialog } from "./components/ReportDialog";
import { ReportExportDialog } from "./components/ReportExportDialog";
import type {
  Asset,
  AssetType,
  ImportTask,
  LineageItem,
  LineageResponse,
  LineageSection,
  Pagination,
  ReportArrangement,
  PipelineSummary,
  StatsResponse,
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
  "created-report": "新建汇报"
};
const VIEW_META = {
  workbench: ["工作台", "管理独立封装的页面素材，按顺序编排并播放汇报。"],
  report: ["汇报素材", "按已确认顺序播放独立封装的页面素材。"],
  control: ["页面素材", "一页一页的可拼接素材，可从汇报单页导入，也可导出为页面模板包。"],
  resource: ["资源素材", "图片、Logo、图标、GIF、视频和 SVG 等页面基础素材。"],
  caseControl: ["案例素材", "把同一文档生成的多个案例素材组织成组，统一管理原始链接、页面素材和多页预览。"],
} as const;

type Toast = { id: number; text: string };
type ManualMergeMode = "keep" | "version";

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

function PageThumbnail({ url, title }: { url?: string; title: string }) {
  const usable = Boolean(url && !/\.html?(?:[?#]|$)/i.test(url));
  const [loadedUrl, setLoadedUrl] = useState("");
  const [failedUrl, setFailedUrl] = useState("");
  const loaded = usable && loadedUrl === url;
  const failed = usable && failedUrl === url;
  return <>
    {usable ? <img src={url} alt={title} loading="lazy" decoding="async" draggable={false} className={loaded ? "is-loaded" : ""}
      onLoad={(event) => { void event.currentTarget.decode().then(() => setLoadedUrl(url || "")).catch(() => setFailedUrl(url || "")); }}
      onError={() => setFailedUrl(url || "")} /> : null}
    {!loaded ? <span className="page-thumbnail-status">{failed ? <FileText size={20} /> : <Loader2 className="spin" size={20} />}<span>{failed ? "预览暂不可用" : "预览生成中"}</span></span> : null}
  </>;
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
  const [sort, setSort] = useState("updated");
  const [days, setDays] = useState("");
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [statsExpanded, setStatsExpanded] = useState(false);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSummary | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, pageSize: ASSET_PAGE_SIZE, total: 0, totalPages: 1, hasPrev: false, hasNext: false });
  const [loading, setLoading] = useState("正在加载素材");
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [arrangementAsset, setArrangementAsset] = useState<Asset | null>(null);
  const [lineage, setLineage] = useState<{ section: LineageSection; items: LineageItem[]; selectedIndex: number } | null>(null);
  const [createReportOpen, setCreateReportOpen] = useState(false);
  const [createReportControls, setCreateReportControls] = useState<Asset[]>([]);
  const [selectedControlIds, setSelectedControlIds] = useState<Set<string>>(() => new Set());
  const [selectedResourceIds, setSelectedResourceIds] = useState<Set<string>>(() => new Set());
  const [manualMergeAssets, setManualMergeAssets] = useState<Asset[] | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importHistoryOpen, setImportHistoryOpen] = useState(false);
  const [importMode, setImportMode] = useState<ImportMode>("general");
  const [importTasks, setImportTasks] = useState<ImportTask[]>([]);
  const [dismissedImportTaskIds, setDismissedImportTaskIds] = useState<Set<string>>(() => loadDismissedImportTaskIds());
  const [dismissedImportTasksUntil, setDismissedImportTasksUntil] = useState(() => loadDismissedImportTasksUntil());
  const [toast, setToast] = useState<Toast | null>(null);
  const [workbench, setWorkbench] = useState<{ reports: Asset[]; controls: Asset[]; resources: Asset[] }>({ reports: [], controls: [], resources: [] });
  const requestSeq = useRef(0);
  const knownImportStatuses = useRef(new Map<string, string>());
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
    if (data.ok === false) {
      showToast(data.error || "统计读取失败");
      return null;
    }
    setStats(data);
    setPipeline(data.pipeline);
    return data;
  }, [showToast]);

  const loadAssets = useCallback(async (page = 1, append = false) => {
    const seq = ++requestSeq.current;
    setLoading(append ? "正在加载更多素材" : query ? "正在搜索素材" : "正在加载素材");
    const data = await api.assets({
      view: "list",
      type: assetType,
      category: "all",
      resource_kind: assetType === "resource" ? resourceKind : "all",
      control_role: assetType === "control" && controlRole !== "全部" ? controlRole : undefined,
      sort, days: days || undefined,
      q: query || undefined,
      page,
      page_size: ASSET_PAGE_SIZE
    });
    if (seq !== requestSeq.current) return;
    if (data.ok === false) {
      setLoading(data.error || "素材读取失败，请重试");
      showToast(data.error || "素材读取失败，请重试");
      return;
    }
    const incoming = data.assets || [];
    setAssets((current) => {
      if (!append) return incoming;
      const seen = new Set(current.map((asset) => asset.id));
      const nextItems = incoming.filter((asset) => !seen.has(asset.id));
      return [...current, ...nextItems];
    });
    setPagination(data.pagination);
    setPipeline(data.pipeline || null);
    setLoading("");
  }, [assetType, controlRole, query, resourceKind, showToast, sort, days]);

  const loadWorkbench = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading("正在整理工作台");
    const [statsData, reports, controls] = await Promise.all([
      api.stats(),
      api.assets({ view: "list", type: "report", category: "all", resource_kind: "all", page: 1, page_size: 8 }),
      api.assets({ view: "list", type: "control", category: "all", resource_kind: "all", page: 1, page_size: 8 })
    ]);
    if (seq !== requestSeq.current) return;
    const failure = [statsData, reports, controls].find((data) => data.ok === false);
    if (failure) {
      showToast(failure.error || "工作台读取失败");
      return;
    }
    setStats(statsData);
    setPipeline(statsData.pipeline);
    setWorkbench({
      reports: sortAssetsByNewest(reports.assets || []),
      controls: sortAssetsByNewest(controls.assets || []),
      resources: []
    });
  }, [showToast]);

  const refreshCurrent = useCallback(async (page = 1) => {
    if (view === "workbench") await loadWorkbench();
    else if (view === "caseControl") await loadStats();
    else await Promise.all([loadAssets(page), loadStats()]);
  }, [loadAssets, loadStats, loadWorkbench, view]);

  useEffect(() => {
    const completed = importTasks.some((task) => task.status === "success"
      && knownImportStatuses.current.get(task.id) !== "success"
      && timestampValue(task.updatedAt || task.createdAt) >= importTaskSessionStartedAt.current);
    knownImportStatuses.current = new Map(importTasks.map((task) => [task.id, task.status]));
    if (completed) void refreshCurrent();
  }, [importTasks, refreshCurrent]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (view === "workbench") void loadWorkbench();
      else if (view === "caseControl") setLoading("案例素材已加载");
      else void loadAssets(1);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [assetType, controlRole, loadAssets, loadWorkbench, query, resourceKind, view]);

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
  }, []);

  useEffect(() => {
    return startImportTaskPolling(async (signal) => {
      const data = await api.importTasks(signal);
      if (data.ok === false) throw new Error(data.error || "导入任务读取失败");
      return data.tasks || [];
    }, (tasks) => setImportTasks(sortImportTasksByNewest(tasks)), (error) => {
      showToast(error instanceof Error ? error.message : "导入任务读取失败");
    });
  }, [showToast]);

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

  const openCreateReportDialog = useCallback(async () => {
    const data = await api.assets({ view: "list", type: "control", page: 1, page_size: 200 });
    if (data.ok === false) {
      showToast(data.error || "页面素材读取失败");
      return;
    }
    setCreateReportControls(sortAssetsByNewest(data.assets || []));
    setCreateReportOpen(true);
  }, [showToast]);

  const createReport = useCallback(async (payload: { title: string; note?: string; pageIds: string[]; coverTemplateId: string }) => {
    const data = await api.createReport(payload);
    if (data.ok === false || !data.asset) {
      showToast(data.error || "新增汇报素材失败");
      return;
    }
    showToast(`已新增汇报素材 ${data.asset.asset_code}`);
    setCreateReportOpen(false);
    setAssetType("report");
    setView("materials");
    await Promise.all([loadStats(), loadAssets(1)]);
    setSelectedAsset(data.asset);
  }, [loadAssets, loadStats, showToast]);

  const startImport = useCallback(async (file: File, description: string) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("description", description.trim());
    const data = await api.createImportTask(formData);
    if (data.ok === false || !data.task) {
      showToast(data.error || "导入任务创建失败");
      return false;
    }
    setImportTasks((current) => sortImportTasksByNewest([data.task, ...current.filter((task) => task.id !== data.task.id)]).slice(0, 8));
    setImportOpen(false);
    showToast("已创建导入任务");
    window.setTimeout(() => void refreshImportTasks(), 500);
    return true;
  }, [refreshImportTasks, showToast]);

  const startDriveImport = useCallback(async (links: string[], description: string) => {
    const data = await api.createDriveImportTasks(links, description);
    if (data.ok === false || !data.tasks) {
      showToast(data.error || "飞书导入任务创建失败");
      return false;
    }
    setImportTasks((current) => sortImportTasksByNewest([...data.tasks, ...current.filter((task) => !data.tasks.some((created) => created.id === task.id))]));
    setImportOpen(false);
    showToast(`已创建 ${data.tasks.length} 个飞书导入任务`);
    return true;
  }, [showToast]);

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
    <div className={classNames("shell-menu", menuOpen && "is-open")} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setMenuOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") setMenuOpen(false); }}><button className="mobile-menu icon-btn" type="button" aria-label="更多操作" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}><MoreHorizontal size={20} /></button>
    <div className="shell-actions" onClick={() => setMenuOpen(false)}>
      {view === "materials" && assetType === "report" ? <button className="secondary" type="button" onClick={() => void openCreateReportDialog()}><Plus size={16} />新建汇报</button> : null}
      <button className="icon-btn" type="button" onClick={() => void refreshCurrent()} title="刷新" aria-label="刷新">
        <RefreshCw size={16} />
      </button>
      <button className="secondary" type="button" onClick={() => { void refreshImportTasks(); setImportHistoryOpen(true); }}>导入记录</button>
      <button className="primary" type="button" onClick={() => { setImportMode("general"); setImportOpen(true); }}>
        <Upload size={16} /> 导入
      </button>
    </div></div>
  ), [menuOpen, assetType, openCreateReportDialog, refreshCurrent, refreshImportTasks, view]);

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
          </nav>
          {view === "materials" ? (
            <label className={classNames("search-box", searchExpanded && "is-expanded")}>
              <Search size={15} />
              <input aria-label="搜索素材" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索编号 / 名称 / 链接" />
            </label>
          ) : <span className="topbar-spacer" aria-hidden="true" />}
          {view === "materials" ? <button className="mobile-search icon-btn" type="button" aria-label="展开搜索" aria-expanded={searchExpanded} onClick={() => setSearchExpanded((value) => !value)}><Search size={20} /></button> : null}
          {actionButtons}
        </div>
        <div className="topbar-sub">
          <div>
            <h1>{pageTitle}</h1>
            <p>{pageSubtitle}</p>
          </div>
          {view !== "workbench" ? <div className={classNames("stats-group", statsExpanded && "is-expanded")}>
            <dl className="top-stats"><div className="stat-total"><dt>素材</dt><dd>{(stats?.types?.report ?? 0) + (stats?.types?.control ?? 0)}</dd></div>
            <div className="stat-part"><dt>其中 · 汇报</dt><dd>{stats?.types?.report ?? 0}</dd></div>
            <div className="stat-part"><dt>页面</dt><dd>{stats?.types?.control ?? 0}</dd></div></dl>
            <button className="stats-toggle" type="button" aria-expanded={statsExpanded} onClick={() => setStatsExpanded((value) => !value)}>{statsExpanded ? "收起统计" : "展开全部"}</button>
          </div> : null}
        </div>
      </header>

      <section className="workspace">
        {view === "workbench" && <Workbench stats={stats} pipeline={pipeline} workbench={workbench} setAssetType={setAssetType} setView={setView} openAsset={openAsset} />}
        {view === "materials" && (
          <AssetLibrary
            assetType={assetType}
            sort={sort} setSort={setSort} days={days} setDays={setDays}
            assets={assets}
            loading={loading}
            pagination={pagination}
            resourceKind={resourceKind}
            setResourceKind={setResourceKind}
            controlRole={controlRole}
            setControlRole={setControlRole}
            openAsset={openAsset}
            renameAsset={renameAsset}

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

          renameAsset={renameAsset}
          deleteAsset={deleteAsset}
          openLineage={openLineage}


          openArrangement={(asset) => { setSelectedAsset(null); setArrangementAsset(asset); window.history.pushState({}, "", `?arrange=${encodeURIComponent(asset.id)}`); }}
        />
      )}
      {arrangementAsset ? <ReportArrangementWorkspace asset={arrangementAsset} close={() => { setArrangementAsset(null); window.history.pushState({}, "", window.location.pathname); }} showToast={showToast} refreshAsset={() => refreshCurrent()} /> : null}
      {createReportOpen ? (
        <ReportDialog controls={createReportControls} close={() => setCreateReportOpen(false)} createReport={createReport} />
      ) : null}

      {importOpen && <ImportDialog mode={importMode} close={() => setImportOpen(false)} startImport={startImport} startDriveImport={startDriveImport} />}
      <ImportTaskDock tasks={visibleImportTasks.slice(0, 6)} dismissTask={dismissImportTask} retryTask={(task) => startDriveImport([task.sourceUrl || ""], "")} />
      {importHistoryOpen ? <ImportHistoryDialog tasks={importTasks} close={() => setImportHistoryOpen(false)} retryTask={(task) => startDriveImport([task.sourceUrl || ""], "")} /> : null}
      {toast?.text ? <div className="toast" role="status">{toast.text}</div> : null}
    </main>
  );
}

function AssetLibrary(props: {
  assetType: AssetType;
  sort: string; setSort: (value: string) => void;
  days: string; setDays: (value: string) => void;
  assets: Asset[];
  loading: string;
  pagination: Pagination;
  resourceKind: string;
  setResourceKind: (kind: string) => void;
  controlRole: string;
  setControlRole: (role: string) => void;
  openAsset: (id: string) => Promise<void>;
  renameAsset: (asset: Asset) => Promise<void>;
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
  onMergeSimilar: () => Promise<void>;
}) {
  const { assetType, assets, loading, pagination, openAsset, renameAsset, loadAssets, selectedControlIds, selectedResourceIds } = props;
  const [layout, setLayout] = useState("grid");
  const visibleControlIds = useMemo(() => assets.filter((asset) => asset.asset_type === "control").map((asset) => asset.id), [assets]);
  const allVisibleControlsSelected = visibleControlIds.length > 0 && visibleControlIds.every((assetId) => selectedControlIds.has(assetId));
  const visibleResourceIds = useMemo(() => assets.filter((asset) => asset.asset_type === "resource").map((asset) => asset.id), [assets]);
  const allVisibleResourcesSelected = visibleResourceIds.length > 0 && visibleResourceIds.every((assetId) => selectedResourceIds.has(assetId));
  const selectedControls = useMemo(() => assets.filter((asset) => selectedControlIds.has(asset.id)), [assets, selectedControlIds]);
  const selectedResources = useMemo(() => assets.filter((asset) => selectedResourceIds.has(asset.id)), [assets, selectedResourceIds]);
  return (
    <>
      {assetType !== "resource" ? <section className="library-toolbar" aria-label="素材筛选与视图">
        <span>{pagination.total} 个{assetType === "report" ? "汇报" : "页面"} · 当前 {assets.length} 个</span>
        <div className="library-options">
          {assetType === "control" ? <label>用途<select aria-label="页面用途" value={props.controlRole} onChange={(event) => props.setControlRole(event.target.value)}>{CONTROL_ROLE_FILTERS.map((value) => <option key={value}>{value}</option>)}</select></label> : null}
          <label>时间<select aria-label="时间范围" value={props.days} onChange={(event) => props.setDays(event.target.value)}><option value="">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select></label>
          <label>排序<select aria-label="排序方式" value={props.sort} onChange={(event) => props.setSort(event.target.value)}><option value="updated">最近更新</option><option value="code">编号升序</option><option value="title">名称</option></select></label>
          <div className="layout-switch" role="group" aria-label="视图方式"><button type="button" aria-pressed={layout === "grid"} onClick={() => setLayout("grid")}>网格</button><button type="button" aria-pressed={layout === "list"} onClick={() => setLayout("list")}>列表</button></div>
        </div>
      </section> : null}
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
      {!assets.length ? <div className="empty-state">{loading ? <><Loader2 size={18} />{loading}</> : "没有匹配的素材，可导入文件或调整搜索条件。"}</div> : (
        <section className={classNames("asset-grid", layout === "list" && "is-list", assetType === "resource" && "resource-grid")}>
          {assets.map((asset, index) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              index={index}
              openAsset={openAsset}
              onRename={renameAsset}

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
  selected = false,
  selectable = false,
  onToggleSelect
}: {
  asset: Asset;
  index: number;
  openAsset: (id: string) => Promise<void>;
  onRename: (asset: Asset) => Promise<void>;
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
          {asset.versionCount > 1 ? <em>版本 {asset.versionCount}</em> : null}
        </div>
        <div className="card-actions">
          <button className="card-action is-muted rename-action" type="button" title={`重命名：${asset.title}`} aria-label={`重命名：${asset.title}`} onClick={() => void onRename(asset)}>
            <Pencil size={16} />
          </button>
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

function AssetModal({ asset, lineage, setLineage, close, copyText, refreshAsset, renameAsset, deleteAsset, openLineage, openArrangement }: {
  asset: Asset;
  lineage: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null;
  setLineage: (value: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null) => void;
  close: () => void;
  copyText: (text: string, message: string) => Promise<void>;
  refreshAsset: (assetId: string) => Promise<void>;
  renameAsset: (asset: Asset) => Promise<void>;
  deleteAsset: (asset: Asset) => Promise<void>;
  openLineage: (assetId: string, sectionKey: string, groupKey?: string) => Promise<void>;
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
                {activeAsset.asset_type === "report" ? <button type="button" onClick={() => openArrangement(activeAsset)}><Grid2X2 size={14} />编排</button> : null}
                {activeAsset.asset_type === "report" ? <button type="button" onClick={() => setExportOpen(true)}><Download size={14} />导出</button> : null}
                <button type="button" onClick={() => void renameAsset(activeAsset)}><Pencil size={14} />重命名</button>
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
  const [saveResult, setSaveResult] = useState<{ url: string; warning: string } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [pickerError, setPickerError] = useState("");
  const saving = useRef(false);
  const pickerRequest = useRef(0);
  const pickerPending = useRef(false);
  const original = useRef("");
  useEffect(() => {
    void api.reportArrangement(asset.id).then((data) => {
      if (data.ok === false) showToast(data.error || "无法加载页面编排");
      else { setArrangement(data); original.current = JSON.stringify(data.pages.map((page) => [page.id, page.hidden])); }
    });
  }, [asset.id, showToast]);
  const dirty = Boolean(arrangement && (insertedIds.length || removedIds.length || JSON.stringify(arrangement.pages.map((page) => [page.id, page.hidden])) !== original.current));
  const pendingThumbnailIds = arrangement?.pages.filter((page) => !page.thumbnailUrl).map((page) => page.id).join("\n") || "";
  useEffect(() => {
    if (!pendingThumbnailIds || busy) return;
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const ids = pendingThumbnailIds.split("\n");
    const refresh = async () => {
      const batch = ids.slice((attempts * 3) % ids.length).slice(0, 3);
      attempts += 1;
      const results = await Promise.all(batch.map((id) => api.asset(id)));
      if (cancelled) return;
      const thumbnails = new Map(results.filter((result) => result.ok !== false && result.asset?.thumbnail_url).map((result) => [result.asset.id, result.asset.thumbnail_url]));
      if (thumbnails.size) setArrangement((current) => current ? { ...current, pages: current.pages.map((page) => thumbnails.has(page.id) ? { ...page, thumbnailUrl: thumbnails.get(page.id)! } : page) } : current);
      if (attempts < 15 && !cancelled) timer = setTimeout(() => void refresh(), 2000);
    };
    timer = setTimeout(() => void refresh(), 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pendingThumbnailIds, busy]);
  const loadPicker = async (page: number, reset = false) => {
    if (!reset && (pickerPending.current || !pickerHasNext)) return;
    const request = ++pickerRequest.current;
    pickerPending.current = true;
    setPickerLoading(true);
    setPickerError("");
    try {
      const data = await api.assets({ view: "list", type: "control", page, page_size: 20, q: pickerQuery || undefined });
      if (request !== pickerRequest.current) return;
      if (data.ok === false) { setPickerError(data.error || "页面读取失败，请重试"); return; }
      const incoming = data.assets || [];
      setPickerAssets((current) => reset ? incoming : [...current, ...incoming.filter((item) => !current.some((existing) => existing.id === item.id))]);
      setPickerPage(page);
      setPickerHasNext(Boolean(data.pagination?.hasNext));
    } finally {
      if (request === pickerRequest.current) { pickerPending.current = false; setPickerLoading(false); }
    }
  };
  const closePicker = () => { ++pickerRequest.current; pickerPending.current = false; setPickerLoading(false); setPickerOpen(false); };
  const openPicker = () => { setPickerOpen(true); setPickedIds(new Set()); setPickerAssets([]); setPickerPage(0); setPickerHasNext(true); void loadPicker(1, true); };
  const insertPicked = () => {
    if (!arrangement || !pickedIds.size) return;
    const inserted = pickerAssets.filter((item) => pickedIds.has(item.id) && item.preview_url && !arrangement.pages.some((page) => page.id === item.id)).map((item, index) => ({
      id: item.id, slotNumber: 0, order: arrangement.pages.length + index + 1, title: item.title, code: item.asset_code,
      previewUrl: item.preview_url, thumbnailUrl: item.thumbnail_url || "", canvas: item.preview_meta, hidden: false
    }));
    setArrangement({ ...arrangement, pages: [...arrangement.pages, ...inserted] });
    setInsertedIds((current) => [...current, ...inserted.map((item) => item.id)]);
    closePicker();
  };
  const confirm = async (showSuccess = true): Promise<boolean> => {
    if (!arrangement || saving.current) return false;
    saving.current = true;
    setBusy(true);
    setSaveError("");
    try {
      const requestedOrder = arrangement.pages.map((page) => page.id);
      const requestedHidden = arrangement.pages.filter((page) => page.hidden).map((page) => page.id);
      const data = await api.updateReportArrangement(asset.id, { pageOrder: requestedOrder, hiddenPageIds: requestedHidden, insertedControlIds: insertedIds, removedPageIds: removedIds, expectedUpdatedAt: arrangement.updatedAt });
      if (data.ok === false) { setSaveError(data.error || "编排更新失败，请重试"); return false; }
      // The successful POST is already committed. Keep its version even when
      // a later preview check fails, so another edit can be saved safely.
      setArrangement(data);
      setInsertedIds([]);
      setRemovedIds([]);
      original.current = JSON.stringify(data.pages.map((page) => [page.id, page.hidden]));
      let warning = "";
      const verified = await api.reportArrangement(asset.id);
      if (verified.ok === false) warning = "编排已保存，暂时无法重新读取预览状态，可稍后查看最新汇报。";
      else {
        const latestOrder = JSON.stringify(verified.pages.map((page) => [page.id, page.hidden]));
        if (latestOrder !== original.current) warning = "编排已保存，检测到另一处更新，已载入最新页序。";
        setArrangement(verified);
        original.current = latestOrder;
      }
      const latestUrl = `${data.previewUrl}${data.previewUrl.includes("?") ? "&" : "?"}v=${encodeURIComponent(String(data.updatedAt || Date.now()))}`;
      try {
        const viewer = await fetch(latestUrl, { cache: "no-store" });
        if (!viewer.ok) warning = "编排已保存，汇报预览暂时不可用，请稍后查看。";
      } catch { warning = "编排已保存，暂时无法连接预览，请稍后查看。"; }
      if (showSuccess) setSaveResult({ url: latestUrl, warning });
      void refreshAsset(asset.id).catch(() => showToast("编排已保存，素材列表稍后刷新"));
      showToast("编排已确认并生效");
      return true;
    } catch {
      setSaveError("暂时无法确认保存结果，请重试；当前修改已保留。");
      return false;
    } finally {
      saving.current = false;
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
    <header className="arrangement-toolbar"><div><button className="icon-btn" title="返回汇报" aria-label="返回汇报" type="button" disabled={busy} onClick={requestClose}><ChevronRight className="back-icon" size={18} /></button><code>页面编排</code><h2>{asset.title}</h2></div><div className="modal-actions"><button className="secondary" type="button" disabled={busy} onClick={openPicker}><Plus size={16} />插入页面</button><button className="primary" type="button" disabled={!dirty || busy} onClick={() => void confirm()}>{busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{busy ? "正在生效" : "确认编排"}</button></div></header>
    <div className="arrangement-content">
      <div className="arrangement-save-status" role="status">{busy ? "正在保存，请稍候…" : dirty ? "有未保存的修改" : "当前编排已保存，可继续修改"}</div>
      {saveError ? <p className="arrangement-save-error error-text" role="alert">{saveError}</p> : null}
      <div className="arrangement-grid arrangement-workspace-grid">
      {!arrangement ? <div className="empty-state">正在加载页面…</div> : arrangement.pages.map((page, index) => <article key={`${page.id}-${index}`} className={classNames("arrangement-page", page.hidden && "is-hidden")} draggable={!busy} onDragStart={() => setDraggedId(page.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => move(page.id)}>
          <div className="arrangement-thumb"><PageThumbnail url={page.thumbnailUrl} title={page.title} /></div>
          <div className="arrangement-copy"><span>#{String(index + 1).padStart(2, "0")}</span><strong>{page.title}</strong><small>{page.code}</small></div>
          <div className="arrangement-actions"><GripVertical size={16} /><button className="icon-btn" type="button" title={page.hidden ? "恢复页面" : "隐藏页面"} aria-label={page.hidden ? "恢复页面" : "隐藏页面"} disabled={busy} onClick={() => setArrangement({ ...arrangement, pages: arrangement.pages.map((item, itemIndex) => itemIndex === index ? { ...item, hidden: !item.hidden } : item) })}>{page.hidden ? <Eye size={15} /> : <EyeOff size={15} />}</button><button className="icon-btn danger-icon" type="button" title="从当前汇报移出" aria-label="从当前汇报移出" disabled={busy} onClick={() => removePage(page.id)}><Trash2 size={15} /></button></div>
        </article>)}</div></div>
    {saveResult ? <div className="modal arrangement-saved-modal" role="dialog" aria-modal="true" aria-labelledby="arrangement-saved-title" onKeyDown={(event) => { if (event.key === "Escape") setSaveResult(null); }}>
      <button className="modal-mask" type="button" onClick={() => setSaveResult(null)} aria-label="关闭保存提示" />
      <section className="modal-panel confirm-panel"><CheckCircle2 className="saved-icon" size={32} /><h2 id="arrangement-saved-title">保存成功</h2><p>{saveResult.warning || "最新编排已生效。可立即查看汇报，或继续调整页面。"}</p><footer>
        <button className="secondary" type="button" autoFocus onClick={() => setSaveResult(null)}>继续编排</button>
        <a className="primary" href={saveResult.url} target="_blank" rel="noreferrer" onClick={() => setSaveResult(null)}><Eye size={15} />查看最新汇报</a>
      </footer></section>
    </div> : null}
    {pickerOpen ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={closePicker} aria-label="关闭" /><section className={classNames("modal-panel page-picker-panel", pickerError && "has-error")}><header className="modal-head"><div><code>页面素材</code><h2>批量插入页面</h2></div><div className="modal-actions"><input value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void loadPicker(1, true)} placeholder="搜索页面素材" /><button className="icon-btn" onClick={closePicker} aria-label="关闭"><X size={16} /></button></div></header>{pickerError ? <p className="error-text picker-error" role="alert">{pickerError}<button className="secondary" type="button" onClick={() => void loadPicker(pickerPage || 1, !pickerPage)}>重试</button></p> : null}<div className="page-picker-grid" onScroll={(event) => { const el = event.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 160) void loadPicker(pickerPage + 1); }}>{pickerAssets.map((item) => <button key={item.id} type="button" className={classNames("page-picker-card", pickedIds.has(item.id) && "is-selected")} disabled={!item.preview_url || arrangement?.pages.some((page) => page.id === item.id)} onClick={() => setPickedIds((current) => { const next = new Set(current); next.has(item.id) ? next.delete(item.id) : next.add(item.id); return next; })}><div className="page-picker-thumb"><PageThumbnail url={item.thumbnail_url} title={item.title} /></div><span>{item.title}</span><small>{item.asset_code}{arrangement?.pages.some((page) => page.id === item.id) ? " · 已在汇报中" : ""}</small></button>)}{pickerLoading ? <div className="empty-state">正在加载…</div> : null}</div><footer className="modal-actions"><span>{pickedIds.size} 页已选择</span><button className="primary" disabled={!pickedIds.size} type="button" onClick={insertPicked}><Plus size={16} />插入所选页面</button></footer></section></div> : null}
    {confirmClose ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={() => setConfirmClose(false)} aria-label="继续编辑" /><section className="modal-panel confirm-panel"><h2>是否保存编排？</h2><p>当前顺序、隐藏、移出和插入页面尚未生效。</p><footer><button className="secondary" disabled={busy} onClick={() => close()}>放弃修改</button><button className="secondary" disabled={busy} onClick={() => setConfirmClose(false)}>继续编辑</button><button className="primary" disabled={busy} onClick={() => void confirm(false).then((saved) => { if (saved) close(); })}>{busy ? "正在生效" : "保存编排"}</button></footer></section></div> : null}
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
