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
import { FormEvent, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { absoluteUrl, api } from "./api";
import { LineagePreview, Preview } from "./components/AssetPreview";
import { CaseControlLibrary } from "./components/CaseControlLibrary";
import { ImportDialog, ImportTaskDock } from "./components/ImportWidgets";
import type { ImportMode } from "./components/ImportWidgets";
import { useModalBehavior } from "./modal";
import { previewSandbox } from "./previewSecurity";
import { Workbench } from "./components/Workbench";
import {
  ASSET_PAGE_SIZE,
  RESOURCE_FILTERS,
  VIEW_META,
  controlCodesFromText,
  defaultReportFormula,
  formatTime,
  isActiveImportTask,
  pageNoFromAsset,
  reportPageCount,
  roleForControl,
  scenarioForReport,
  sortAssetsByNewest,
  sortImportTasksByNewest,
  sortStorylinesByNewest,
  sourceTypeLabel,
  timestampValue,
  titleFromFormula,
  topTags
} from "./productLogic";
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

const DISMISSED_IMPORT_TASKS_KEY = "minem.dismissedImportTaskIds";
const DISMISSED_IMPORT_TASKS_UNTIL_KEY = "minem.dismissedImportTasksUntil";

type Toast = { id: number; text: string; tone?: "info" | "error"; duration?: number; actionLabel?: string; onAction?: () => void };
type StorylineCollectMode = "new" | "version";
type StorylineReportMode = "chat" | "manual" | "copy";
type ManualMergeMode = "keep" | "version";
type PresenterScriptSource = "minutes" | "script";
type PresenterScriptDraft = { asset: Asset; status?: PresenterScriptStatus; editing: boolean };
type PresenterAction = { asset: Asset; status: PresenterScriptStatus };
type BatchAction = "autoImport" | "aiTag" | "mergeSimilar" | null;

function classNames(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
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

const useEscapeClose = useModalBehavior;

function App() {
  const [view, setView] = useState<ViewKey>("materials");
  const [assetType, setAssetType] = useState<AssetType>("report");
  const [resourceKind, setResourceKind] = useState("all");
  const [caseReloadToken, setCaseReloadToken] = useState(0);
  const [query, setQuery] = useState("");
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSummary | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ page: 1, pageSize: ASSET_PAGE_SIZE, total: 0, totalPages: 1, hasPrev: false, hasNext: false });
  const [storylines, setStorylines] = useState<Storyline[]>([]);
  const [loading, setLoading] = useState("正在加载素材");
  const [isLoading, setIsLoading] = useState(true);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [openingAssetId, setOpeningAssetId] = useState("");
  const [pendingDeleteAsset, setPendingDeleteAsset] = useState<Asset | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Asset | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
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
  const [importTasksConnectionLost, setImportTasksConnectionLost] = useState(false);
  const [retryingImportTaskIds, setRetryingImportTaskIds] = useState<Set<string>>(() => new Set());
  const [dismissedImportTaskIds, setDismissedImportTaskIds] = useState<Set<string>>(() => loadDismissedImportTaskIds());
  const [dismissedImportTasksUntil, setDismissedImportTasksUntil] = useState(() => loadDismissedImportTasksUntil());
  const [batchAction, setBatchAction] = useState<BatchAction>(null);
  const [topActionBusy, setTopActionBusy] = useState<"creator" | "refresh" | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [workbench, setWorkbench] = useState<{ reports: Asset[]; controls: Asset[]; resources: Asset[] }>({ reports: [], controls: [], resources: [] });
  const requestSeq = useRef(0);
  const importTaskSessionStartedAt = useRef(Date.now());
  const importPollTimer = useRef<number | null>(null);
  const importPollAlive = useRef(true);
  const importTaskStatuses = useRef<Map<string, ImportTask["status"]>>(new Map());

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

  const showToast = useCallback((text: string, duration = 2600) => {
    setToast({ id: Date.now(), text, duration });
  }, []);

  // Errors deserve a longer dwell and an optional retry affordance so a failure
  // is recoverable instead of a 2.6s flash the user may miss.
  const showError = useCallback((text: string, onRetry?: () => void) => {
    setToast({
      id: Date.now(),
      text,
      tone: "error",
      duration: onRetry ? 8000 : 4200,
      actionLabel: onRetry ? "重试" : undefined,
      onAction: onRetry
    });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.duration || 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Escape closes the App-level confirm dialogs (unless a write is in flight).
  useEscapeClose(() => { if (!deleteBusy) setPendingDeleteAsset(null); }, Boolean(pendingDeleteAsset));
  useEscapeClose(() => { if (!renameBusy) setRenameTarget(null); }, Boolean(renameTarget));

  const loadStats = useCallback(async () => {
    const data = await api.stats();
    if (data.ok === false) return data;
    setStats(data);
    setPipeline(data.pipeline);
    return data;
  }, []);

  const loadAssets = useCallback(async (page = 1, append = false) => {
    const seq = ++requestSeq.current;
    setIsLoading(true);
    setLoading(append ? "正在加载更多素材" : query ? "正在搜索素材" : "正在加载素材");
    if (!append) setAssets([]);
    try {
      const data = await api.assets({
        view: "list",
        type: assetType,
        category: "all",
        resource_kind: assetType === "resource" ? resourceKind : "all",
        q: query || undefined,
        page,
        page_size: ASSET_PAGE_SIZE
      });
      if (seq !== requestSeq.current) return;
      if (data.ok === false) {
        setLoading(data.error || "素材读取失败，请刷新重试");
        return;
      }
      const incoming = sortAssetsByNewest(data.assets || []);
      setAssets((current) => {
        if (!append) return incoming;
        const seen = new Set(current.map((asset) => asset.id));
        const nextItems = incoming.filter((asset) => !seen.has(asset.id));
        return [...current, ...nextItems];
      });
      if (data.pagination) setPagination(data.pagination);
      setPipeline(data.pipeline || null);
      setLoading(incoming.length || append ? "" : query ? "没有匹配的素材" : "暂无素材");
    } catch {
      if (seq === requestSeq.current) setLoading("素材读取失败，请刷新重试");
    } finally {
      if (seq === requestSeq.current) setIsLoading(false);
    }
  }, [assetType, query, resourceKind]);

  const loadStorylines = useCallback(async () => {
    const seq = ++requestSeq.current;
    setIsLoading(true);
    setLoading(query ? "正在搜索故事线" : "正在加载故事线");
    setStorylines([]);
    try {
      const data = await api.storylines({ q: query || undefined });
      if (seq !== requestSeq.current) return;
      if (data.ok === false) {
        setLoading(data.error || "故事线读取失败");
        return;
      }
      const incoming = sortStorylinesByNewest(data.storylines || []);
      setStorylines(incoming);
      setLoading(incoming.length ? "" : query ? "没有匹配的故事线" : "暂无故事线");
    } catch {
      if (seq === requestSeq.current) setLoading("故事线读取失败，请刷新重试");
    } finally {
      if (seq === requestSeq.current) setIsLoading(false);
    }
  }, [query]);

  const loadWorkbench = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading("正在整理工作台");
    try {
      const [statsData, storylineData, reports, controls, resources] = await Promise.all([
        api.stats(),
        api.storylines(),
        api.assets({ view: "list", type: "report", category: "all", resource_kind: "all", page: 1, page_size: 8 }),
        api.assets({ view: "list", type: "control", category: "all", resource_kind: "all", page: 1, page_size: 8 }),
        api.assets({ view: "list", type: "resource", category: "all", resource_kind: "all", page: 1, page_size: 8 })
      ]);
      if (seq !== requestSeq.current) return;
      if (statsData.ok === false) {
        setLoading(statsData.error || "工作台读取失败，请刷新重试");
        return;
      }
      setStats(statsData);
      setPipeline(statsData.pipeline);
      setStorylines(sortStorylinesByNewest(storylineData.storylines || []));
      setWorkbench({
        reports: sortAssetsByNewest(reports.assets || []),
        controls: sortAssetsByNewest(controls.assets || []),
        resources: sortAssetsByNewest(resources.assets || [])
      });
      setLoading("");
      // Stats loaded, but a sub-panel may have failed; render what we have and
      // warn instead of silently showing empty "最近..." panels.
      if ([storylineData, reports, controls, resources].some((part) => part.ok === false)) {
        showError("部分工作台数据加载失败，请刷新重试", () => void loadWorkbench());
      }
    } catch {
      if (seq === requestSeq.current) setLoading("工作台读取失败，请刷新重试");
    }
  }, [showError]);

  const refreshCurrent = useCallback(async (page = 1) => {
    if (view === "caseControl") {
      setCaseReloadToken((token) => token + 1);
      return;
    }
    const loader = view === "workbench"
      ? loadWorkbench()
      : view === "storyline"
        ? loadStorylines()
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
  }, [assetType, loadAssets, loadStorylines, loadWorkbench, query, resourceKind, view]);

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
    if (importPollTimer.current !== null) {
      window.clearTimeout(importPollTimer.current);
      importPollTimer.current = null;
    }
    const scheduleNext = (delay: number) => {
      if (!importPollAlive.current) return;
      importPollTimer.current = window.setTimeout(() => void refreshImportTasks(), delay);
    };
    try {
      const data = await api.importTasks();
      if (!importPollAlive.current) return;
      if (data.ok === false) throw new Error(data.error || "任务读取失败");
      setImportTasksConnectionLost(false);
      setImportTasks(sortImportTasksByNewest(data.tasks || []));
      if ((data.tasks || []).some((task) => task.status === "queued" || task.status === "running")) {
        scheduleNext(1200);
      }
    } catch {
      if (!importPollAlive.current) return;
      setImportTasksConnectionLost(true);
      scheduleNext(2500);
    }
  }, []);

  useEffect(() => {
    importPollAlive.current = true;
    void refreshImportTasks();
    return () => {
      importPollAlive.current = false;
      if (importPollTimer.current !== null) {
        window.clearTimeout(importPollTimer.current);
        importPollTimer.current = null;
      }
    };
  }, [refreshImportTasks]);

  useEffect(() => {
    const completed: ImportTask[] = [];
    const failed: ImportTask[] = [];
    importTasks.forEach((task) => {
      const previous = importTaskStatuses.current.get(task.id);
      if (previous && isActiveImportTask({ ...task, status: previous }) && task.status === "success") {
        completed.push(task);
      }
      if (previous && isActiveImportTask({ ...task, status: previous }) && task.status === "failed") {
        failed.push(task);
      }
      importTaskStatuses.current.set(task.id, task.status);
    });
    if (completed.length) {
      const assetCount = completed.reduce((total, task) => total + Number(task.assetCount || 0), 0);
      showToast(`导入完成，新增或关联 ${assetCount} 个素材`);
      void refreshCurrent();
    }
    if (failed.length) {
      showError(failed.length === 1 ? failed[0].error || "导入失败，请查看任务详情" : `${failed.length} 个导入任务失败，请查看任务详情`);
    }
  }, [importTasks, refreshCurrent, showError, showToast]);

  const openAsset = useCallback(async (assetId: string) => {
    setOpeningAssetId(assetId);
    try {
      const data = await api.asset(assetId);
      if (data.ok === false || !data.asset) {
        showError(data.error || "素材读取失败", () => void openAsset(assetId));
        return;
      }
      setSelectedAsset(data.asset);
      setLineage(null);
    } finally {
      setOpeningAssetId((current) => current === assetId ? "" : current);
    }
  }, [showError]);

  const syncLocation = useCallback(() => {
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
    setArrangementAsset(null);
    const assetId = params.get("preview");
    if (assetId) void openAsset(assetId);
  }, [openAsset, showToast]);

  useEffect(() => {
    syncLocation();
    window.addEventListener("popstate", syncLocation);
    return () => window.removeEventListener("popstate", syncLocation);
  }, [syncLocation]);

  const closeArrangement = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("arrange")) {
      if (window.history.state?.minemArrangement) {
        window.history.back();
      } else {
        window.history.replaceState({}, "", window.location.pathname);
        setArrangementAsset(null);
      }
      return;
    }
    setArrangementAsset(null);
  }, []);

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
    setRenameTarget(asset);
    setRenameDraft(asset.title || "");
  }, []);

  const submitRename = useCallback(async () => {
    const asset = renameTarget;
    if (!asset || renameBusy) return;
    const title = renameDraft.trim();
    if (!title || title === asset.title) {
      setRenameTarget(null);
      return;
    }
    setRenameBusy(true);
    try {
      const data = await api.renameAsset(asset.id, title);
      if (data.ok === false || !data.asset) {
        showToast(data.error || "重命名失败");
        return;
      }
      showToast("名称已更新");
      setSelectedAsset((current) => current?.id === data.asset.id ? data.asset : current);
      setAssets((current) => current.map((item) => item.id === data.asset.id ? data.asset : item));
      setRenameTarget(null);
    } finally {
      setRenameBusy(false);
    }
  }, [renameBusy, renameDraft, renameTarget, showToast]);

  const deleteAsset = useCallback(async (asset: Asset) => {
    setPendingDeleteAsset(asset);
  }, []);

  const confirmDeleteAsset = useCallback(async () => {
    const asset = pendingDeleteAsset;
    if (!asset || deleteBusy) return;
    setDeleteBusy(true);
    try {
      const data = await api.deleteAsset(asset.id);
      if (data.ok === false) {
        showToast(data.error || "删除失败", 3600);
        return;
      }
      showToast(`已删除 ${data.assetCode || asset.asset_code}`);
      setPendingDeleteAsset(null);
      setSelectedAsset(null);
      await refreshCurrent();
    } catch (error) {
      showToast(error instanceof Error ? `删除失败：${error.message}` : "删除失败，请稍后重试", 3600);
    } finally {
      setDeleteBusy(false);
    }
  }, [deleteBusy, pendingDeleteAsset, refreshCurrent, showToast]);

  const copyText = useCallback(async (text: string, message: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // navigator.clipboard is unavailable in non-secure contexts (e.g. a LAN
        // IP instead of 127.0.0.1); fall back to a hidden textarea + execCommand.
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.focus();
        area.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(area);
        if (!ok) throw new Error("execCommand copy failed");
      }
      showToast(message || "复制成功", 1000);
    } catch {
      showError("复制失败，请手动选择内容复制");
    }
  }, [showError, showToast]);

  const openStorylineDialog = useCallback(async (asset: Asset) => {
    if (asset.asset_type !== "report") return;
    setStorylineAsset(asset);
    const data = await api.storylines();
    if (data.ok === false) {
      setStorylineCandidates([]);
      showError(data.error || "故事线读取失败，暂时只能新建故事线");
      return;
    }
    setStorylineCandidates(sortStorylinesByNewest(data.storylines || []));
  }, [showError]);

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
    showToast("正在准备汇报素材...");
    const [controls, storylineData] = await Promise.all([
      api.assets({ view: "list", type: "control", category: "all", resource_kind: "all", page: 1, page_size: 200 }),
      api.storylines()
    ]);
    if (controls.ok === false) {
      showError(controls.error || "页面素材读取失败，无法创建汇报", () => void openCreateReportDialog());
      return;
    }
    setCreateReportControls(sortAssetsByNewest(controls.assets || []));
    if (storylineData.ok === false) {
      setStorylines([]);
      showError(storylineData.error || "故事线读取失败，复制模式暂不可用");
    } else {
      setStorylines(sortStorylinesByNewest(storylineData.storylines || []));
      showToast("");
    }
    setCreateReportOpen(true);
  }, [showError, showToast]);

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

  const startImport = useCallback(async (file: File, description: string, onProgress: (progress: number) => void, signal: AbortSignal) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("description", description.trim());
    const data = await api.createImportTask(formData, onProgress, signal);
    if (data.ok === false || !data.task) {
      return { ok: false, error: data.error || "导入任务创建失败" };
    }
    setImportTasks((current) => sortImportTasksByNewest([data.task, ...current.filter((task) => task.id !== data.task.id)]).slice(0, 8));
    setImportOpen(false);
    if (data.task.status === "success") {
      showToast(data.task.message || "相同素材已存在，已复用历史批次");
      await refreshCurrent();
    } else {
      showToast("文件已上传，正在后台解析素材");
    }
    window.setTimeout(() => void refreshImportTasks(), 500);
    return { ok: true };
  }, [refreshCurrent, refreshImportTasks, showToast]);

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

  const retryImportTask = useCallback(async (taskId: string) => {
    if (retryingImportTaskIds.has(taskId)) return;
    setRetryingImportTaskIds((current) => new Set(current).add(taskId));
    try {
      const data = await api.retryImportTask(taskId);
      if (data.ok === false || !data.task) {
        showError(data.error || "任务重试失败");
        return;
      }
      setImportTasks((current) => sortImportTasksByNewest([
        data.task!,
        ...current.filter((task) => task.id !== taskId)
      ]));
      showToast("已重新开始导入");
      window.setTimeout(() => void refreshImportTasks(), 500);
    } finally {
      setRetryingImportTaskIds((current) => {
        const next = new Set(current);
        next.delete(taskId);
        return next;
      });
    }
  }, [refreshImportTasks, retryingImportTaskIds, showError, showToast]);

  const actionButtons = useMemo(() => (
    <div className="shell-actions">
      <button
        className="secondary creator-assistant-entry"
        type="button"
        disabled={topActionBusy !== null}
        onClick={() => {
          setTopActionBusy("creator");
          void api.openCreatorAssistant().then((data) => {
            if (data.ok === false) showError(data.error || "无法打开创作助手");
            else showToast("创作助手已打开");
          }).finally(() => setTopActionBusy(null));
        }}
        title="打开创作助手"
      >
        {topActionBusy === "creator" ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />} 创作
      </button>
      <button
        className="icon-btn"
        type="button"
        disabled={topActionBusy !== null}
        onClick={() => {
          setTopActionBusy("refresh");
          void refreshCurrent().then(() => showToast("已刷新当前内容")).finally(() => setTopActionBusy(null));
        }}
        title="刷新"
      >
        <RefreshCw className={topActionBusy === "refresh" ? "spin" : ""} size={16} />
      </button>
      <button className="primary" type="button" onClick={() => { setImportMode("general"); setImportOpen(true); }}>
        <Upload size={16} /> 导入
      </button>
    </div>
  ), [refreshCurrent, showError, showToast, topActionBusy]);

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
            isLoading={isLoading}
            pagination={pagination}
            resourceKind={resourceKind}
            setResourceKind={setResourceKind}
            openAsset={openAsset}
            openingAssetId={openingAssetId}
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
            batchAction={batchAction}
            onOpenExternalImport={() => { setImportMode("external-report"); setImportOpen(true); }}
            onAutoImport={async () => {
              if (batchAction) return;
              setBatchAction("autoImport");
              showToast("正在扫描历史素材...");
              try {
                const data = await api.autoImport();
                if (data.ok === false) showError(data.error || "自动导入失败");
                else {
                  showToast(`扫描 ${data.scanned} 个文件，新增 ${data.assetCount} 个素材`);
                  await Promise.all([loadAssets(1), loadStats()]);
                }
              } finally {
                setBatchAction(null);
              }
            }}
            onAiTag={async () => {
              if (batchAction) return;
              setBatchAction("aiTag");
              showToast("正在创建标签任务...");
              try {
                const data = await api.aiTag(assetType);
                if (data.ok === false) showError(data.error || "AI 打标签失败");
                else {
                  showToast(`已创建 ${data.scanned} 个素材的标签任务，完成后刷新列表即可查看`);
                }
              } finally {
                setBatchAction(null);
              }
            }}
            onMergeSimilar={async () => {
              if (batchAction) return;
              setBatchAction("mergeSimilar");
              showToast("正在合并相似图片...");
              try {
                const data = await api.mergeSimilar();
                if (data.ok === false) showError(data.error || "合并失败");
                else {
                  showToast(`扫描 ${data.scanned} 个图片素材，合并 ${data.mergedAssets} 个为 ${data.groups} 组版本`);
                  await Promise.all([loadAssets(1), loadStats()]);
                }
              } finally {
                setBatchAction(null);
              }
            }}
          />
        )}
        {view === "caseControl" && <CaseControlLibrary copyText={copyText} reloadToken={caseReloadToken} />}
        {view === "storyline" && <StorylineLibrary storylines={storylines} loading={loading} isLoading={isLoading} copyText={copyText} openStoryline={setSelectedStoryline} openCreateReport={openCreateReportDialog} />}
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
          showError={showError}
          refreshAsset={openAsset}
          startTagAnalysis={startTagAnalysis}
          renameAsset={renameAsset}
          deleteAsset={deleteAsset}
          openLineage={openLineage}
          collectStoryline={openStorylineDialog}
          openAiPresenter={openAiPresenter}
          openArrangement={(asset) => {
            setSelectedAsset(null);
            setArrangementAsset(asset);
            window.history.pushState({ minemArrangement: asset.id }, "", `?arrange=${encodeURIComponent(asset.id)}`);
          }}
        />
      )}
      {pendingDeleteAsset ? (
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-asset-title">
          <button
            className="modal-mask"
            type="button"
            onClick={() => { if (!deleteBusy) setPendingDeleteAsset(null); }}
            aria-label="取消删除"
          />
          <section className="modal-panel confirm-panel">
            <h2 id="delete-asset-title">删除{pendingDeleteAsset.typeLabel || "素材"}？</h2>
            <p><code>{pendingDeleteAsset.asset_code}</code> · {pendingDeleteAsset.title}</p>
            {(pendingDeleteAsset.versionCount || 1) > 1 && !pendingDeleteAsset.version_parent_id
              ? <p>该素材包含 {pendingDeleteAsset.versionCount} 个版本，将一并删除。</p>
              : null}
            <p>
              {pendingDeleteAsset.asset_type === "control"
                ? "仍被汇报引用的页面会被保护，请先在对应汇报中移出。"
                : "汇报引用的页面和资源会继续保留，原始导入文件也不会被删除。"}
            </p>
            <footer>
              <button className="secondary" type="button" disabled={deleteBusy} onClick={() => setPendingDeleteAsset(null)}>取消</button>
              <button className="danger" type="button" disabled={deleteBusy} onClick={() => void confirmDeleteAsset()}>
                {deleteBusy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
                {deleteBusy ? "正在删除" : "确认删除"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {renameTarget ? (
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="rename-asset-title">
          <button
            className="modal-mask"
            type="button"
            onClick={() => { if (!renameBusy) setRenameTarget(null); }}
            aria-label="取消命名"
          />
          <form
            className="modal-panel confirm-panel"
            onSubmit={(event) => { event.preventDefault(); void submitRename(); }}
          >
            <h2 id="rename-asset-title">重命名{renameTarget.typeLabel || "素材"}</h2>
            <p><code>{renameTarget.asset_code}</code></p>
            <input
              className="rename-input"
              type="text"
              value={renameDraft}
              autoFocus
              disabled={renameBusy}
              placeholder="素材名称"
              onChange={(event) => setRenameDraft(event.target.value)}
            />
            <footer>
              <button className="secondary" type="button" disabled={renameBusy} onClick={() => setRenameTarget(null)}>取消</button>
              <button className="primary" type="submit" disabled={renameBusy || !renameDraft.trim()}>
                {renameBusy ? <Loader2 className="spin" size={16} /> : <Pencil size={16} />}
                {renameBusy ? "正在保存" : "保存"}
              </button>
            </footer>
          </form>
        </div>
      ) : null}
      {arrangementAsset ? <ReportArrangementWorkspace asset={arrangementAsset} close={closeArrangement} showToast={showToast} refreshAsset={openAsset} /> : null}
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
      <ImportTaskDock
        tasks={visibleImportTasks}
        dismissTask={dismissImportTask}
        retryTask={(taskId) => void retryImportTask(taskId)}
        openAsset={(assetId) => void openAsset(assetId)}
        copyError={(text) => void copyText(text, "已复制错误信息")}
        retryingTaskIds={retryingImportTaskIds}
        connectionLost={importTasksConnectionLost}
      />
      {toast?.text ? (
        <div className={classNames("toast", toast.tone === "error" && "is-error", visibleImportTasks.length > 0 && "has-task-dock")} role={toast.tone === "error" ? "alert" : "status"}>
          {toast.tone === "error" ? <AlertCircle size={16} /> : null}
          <span>{toast.text}</span>
          {toast.actionLabel && toast.onAction ? (
            <button
              type="button"
              className="toast-action"
              onClick={() => { const action = toast.onAction; setToast(null); action?.(); }}
            >
              {toast.actionLabel}
            </button>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function AssetLibrary(props: {
  assetType: AssetType;
  assets: Asset[];
  loading: string;
  isLoading: boolean;
  pagination: Pagination;
  resourceKind: string;
  setResourceKind: (kind: string) => void;
  openAsset: (id: string) => Promise<void>;
  openingAssetId: string;
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
  batchAction: BatchAction;
  onOpenExternalImport: () => void;
  onAutoImport: () => Promise<void>;
  onAiTag: () => Promise<void>;
  onMergeSimilar: () => Promise<void>;
}) {
  const { assetType, assets, loading, isLoading, pagination, openAsset, openingAssetId, renameAsset, loadAssets, onCollectStoryline, selectedControlIds, selectedResourceIds } = props;
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
                <button type="button" disabled={Boolean(props.batchAction)} onClick={props.onAutoImport}>
                  {props.batchAction === "autoImport" ? <Loader2 className="spin" size={15} /> : <PackagePlus size={15} />}
                  {props.batchAction === "autoImport" ? "扫描中" : "自动导入"}
                </button>
                <button type="button" disabled={Boolean(props.batchAction)} onClick={props.onAiTag}>
                  {props.batchAction === "aiTag" ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
                  {props.batchAction === "aiTag" ? "处理中" : "打标签"}
                </button>
                <button type="button" disabled={Boolean(props.batchAction)} onClick={props.onMergeSimilar}>
                  {props.batchAction === "mergeSimilar" ? <Loader2 className="spin" size={15} /> : <GitBranch size={15} />}
                  {props.batchAction === "mergeSimilar" ? "合并中" : "合并相似"}
                </button>
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
      {!assets.length ? (
        <div className={classNames("empty-state", /失败|连接/.test(loading) && "is-error")}>
          {isLoading ? <Loader2 className="spin" size={18} /> : /失败|连接/.test(loading) ? <AlertCircle size={18} /> : null}
          <strong>{loading || "暂无素材"}</strong>
          {!isLoading && /失败|连接/.test(loading) ? <button className="secondary" type="button" onClick={() => void loadAssets(1)}>重新加载</button> : null}
        </div>
      ) : (
        <section className={classNames("asset-grid", assetType === "resource" && "resource-grid")}>
          {assets.map((asset, index) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              index={index}
              openAsset={openAsset}
              opening={openingAssetId === asset.id}
              onRename={renameAsset}
              onCollectStoryline={onCollectStoryline}
              selected={assetType === "control" ? selectedControlIds.has(asset.id) : selectedResourceIds.has(asset.id)}
              selectable={assetType === "control" || assetType === "resource"}
              onToggleSelect={assetType === "resource" ? props.onToggleResourceSelection : props.onToggleControlSelection}
            />
          ))}
        </section>
      )}
      <PaginationBar pagination={pagination} loadAssets={loadAssets} loading={isLoading} />
    </>
  );
}

const AssetCard = memo(function AssetCard({
  asset,
  index,
  openAsset,
  opening,
  onRename,
  onCollectStoryline,
  selected = false,
  selectable = false,
  onToggleSelect
}: {
  asset: Asset;
  index: number;
  openAsset: (id: string) => Promise<void>;
  opening: boolean;
  onRename: (asset: Asset) => Promise<void>;
  onCollectStoryline: (asset: Asset) => Promise<void>;
  selected?: boolean;
  selectable?: boolean;
  onToggleSelect?: (assetId: string) => void;
}) {
  const isReport = asset.asset_type === "report";
  const supportsInteractivePreview = asset.media_kind === "html" || Boolean(asset.preview_url);
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
        <button className="asset-card-hit" type="button" disabled={opening} aria-busy={opening} onClick={() => void openAsset(asset.id)}>
          <div className="resource-preview"><Preview asset={asset} mode="thumbnail" compact /></div>
          <div className="resource-copy">
            <span>{asset.resourceKindLabel || asset.mediaLabel}</span>
            <strong>{asset.title}</strong>
            <small><code>{asset.asset_code}</code>{asset.versionCount > 1 ? ` · ${asset.versionCount} 版` : null}</small>
          </div>
        </button>
        {opening ? <span className="card-opening" role="status"><Loader2 className="spin" size={15} />正在打开</span> : null}
      </article>
    );
  }
  return (
    <article className={classNames("report-card", isReport ? "report-material-card" : "page-material-card", "asset-card", selected && "is-selected")}>
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
      <button className="asset-card-hit" type="button" disabled={opening} aria-busy={opening} onClick={() => void openAsset(asset.id)}>
        <div className="card-preview">
          <Preview asset={asset} mode="thumbnail" compact />
          <div className="material-preview-chrome" aria-hidden="true">
            <span className="material-kind">{isReport ? "汇报材料" : "页面材料"}</span>
            <span className="material-canvas">1920 × 1080</span>
          </div>
          {supportsInteractivePreview ? <span className="interactive-badge"><span />可交互</span> : null}
        </div>
        <div className="card-copy">
          <span>#{String(index + 1).padStart(3, "0")} · {isReport ? `${reportPageCount(asset)} 页` : roleForControl(asset)}</span>
          <strong>{asset.title}</strong>
          <small><code>{asset.asset_code}</code> · {isReport ? scenarioForReport(asset) : sourceTypeLabel(asset.source_type)}</small>
        </div>
      </button>
      {opening ? <span className="card-opening" role="status"><Loader2 className="spin" size={15} />正在打开</span> : null}
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
});

function ManualMergeDialog({ assets, close, mergeAssets }: {
  assets: Asset[];
  close: () => void;
  mergeAssets: (payload: { assetIds: string[]; primaryAssetId: string; mode: ManualMergeMode }) => Promise<void>;
}) {
  const [primaryAssetId, setPrimaryAssetId] = useState(assets[0]?.id || "");
  const [mode, setMode] = useState<ManualMergeMode>("version");
  const [busy, setBusy] = useState(false);
  useEscapeClose(() => { if (!busy) close(); });
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

function PaginationBar({ pagination, loadAssets, loading }: { pagination: Pagination; loadAssets: (page?: number, append?: boolean) => Promise<void>; loading: boolean }) {
  if (!pagination.hasNext) return null;
  return (
    <div className="pagination">
      <button type="button" disabled={loading} aria-busy={loading} onClick={() => void loadAssets(pagination.page + 1, true)}>
        {loading ? <Loader2 className="spin" size={15} /> : null}
        {loading ? "正在加载" : "加载更多"}{!loading ? <ChevronRight size={15} /> : null}
      </button>
      <span>每次 {pagination.pageSize || ASSET_PAGE_SIZE} 条 · 第 {pagination.page} / {pagination.totalPages} 批</span>
    </div>
  );
}

function StorylineLibrary({ storylines, loading, isLoading, copyText, openStoryline, openCreateReport }: { storylines: Storyline[]; loading: string; isLoading: boolean; copyText: (text: string, message: string) => Promise<void>; openStoryline: (storyline: Storyline) => void; openCreateReport: () => Promise<void> }) {
  const body = !storylines.length ? <div className={classNames("empty-state", /失败|连接/.test(loading) && "is-error")}>{isLoading ? <Loader2 className="spin" size={18} /> : /失败|连接/.test(loading) ? <AlertCircle size={18} /> : null}<strong>{loading || "暂无故事线"}</strong></div> : (
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
  useEscapeClose(close);
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
          <button className={classNames(mode === "copy" && "active")} type="button" disabled={!storylineVersions.length} onClick={() => setMode("copy")}>复制故事线版本</button>
        </div>
        <label className="import-field">
          <span>汇报素材标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入汇报素材标题" />
        </label>
        {mode === "chat" ? (
          <DetailSection title="平台交互提示词">
            <textarea className="copy-prompt chat-formula" value={formulaText} placeholder={`留空则使用默认公式：\n${formulaTemplate}`} onChange={(event) => setFormulaText(event.target.value)} />
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
  useEscapeClose(close);
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
          <button className={classNames(mode === "version" && "active")} type="button" disabled={!storylines.length} onClick={() => setMode("version")}>更新已有故事线版本</button>
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
  useEscapeClose(close);
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
  useEscapeClose(() => { if (!busy) close(); });
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
  return <iframe src={src} title={source.title} loading="lazy" sandbox={previewSandbox(src)} referrerPolicy="no-referrer" />;
}

function StorylineModal({ storyline, close, copyText, openAsset }: {
  storyline: Storyline;
  close: () => void;
  copyText: (text: string, message: string) => Promise<void>;
  openAsset: (assetId: string) => Promise<void>;
}) {
  const versions = storyline.versions?.length ? storyline.versions : [storyline];
  const [activeVersionId, setActiveVersionId] = useState(storyline.id);
  useEscapeClose(close);
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

function AssetModal({ asset, lineage, setLineage, close, copyText, showError, refreshAsset, startTagAnalysis, renameAsset, deleteAsset, openLineage, collectStoryline, openAiPresenter, openArrangement }: {
  asset: Asset;
  lineage: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null;
  setLineage: (value: { section: LineageSection; items: LineageItem[]; selectedIndex: number } | null) => void;
  close: () => void;
  copyText: (text: string, message: string) => Promise<void>;
  showError: (text: string, onRetry?: () => void) => void;
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
  // Escape closes the export sub-dialog first, otherwise the asset modal.
  useEscapeClose(() => { if (exportOpen) setExportOpen(false); else close(); });
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
            {activeAsset.preview_url ? <button className="icon-btn" type="button" onClick={() => { previewContainerRef.current?.requestFullscreen().catch(() => showError("浏览器阻止了全屏预览")); }} title="全屏预览" aria-label="全屏预览"><Maximize2 size={15} /></button> : null}
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
  const [startError, setStartError] = useState("");
  const [pollError, setPollError] = useState("");
  useEscapeClose(close);
  const start = async (format: "html" | "pdf") => {
    setStarting(true);
    setStartError("");
    const data = await api.createReportExport(asset.id, format);
    setStarting(false);
    if (data.ok === false || !data.task) {
      setStartError(data.error || "导出启动失败，请重试");
      return;
    }
    setTask(data.task);
  };
  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed") return;
    let failures = 0;
    const timer = window.setInterval(() => {
      void api.reportExportTask(task.id).then((data) => {
        if (data.ok !== false && data.task) {
          failures = 0;
          setPollError("");
          setTask(data.task);
          return;
        }
        // Stop polling after repeated failures so the dialog surfaces the
        // problem instead of spinning on a stale "正在导出" forever.
        failures += 1;
        if (failures >= 3) {
          setPollError(data.error || "导出状态获取失败，请稍后重试");
          window.clearInterval(timer);
        }
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
        <span>{task.format.toUpperCase()} · {task.pageCount} 页</span><strong>{task.status === "completed" ? "导出完成" : task.status === "failed" ? "导出失败" : pollError ? "导出中断" : task.message || "正在导出"}</strong>
        <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
        {task.error ? <p className="error-text">{task.error}</p> : null}
        {pollError ? <p className="error-text">{pollError}</p> : null}
        {pending && !pollError ? <small>后台处理中，可继续浏览素材库。</small> : null}
        {task.status === "completed" && task.downloadUrl ? <a className="primary" href={task.downloadUrl}><Download size={15} />下载文件</a> : null}
        {task.status === "failed" || pollError ? <button className="secondary" type="button" onClick={() => { setTask(null); setPollError(""); }}>重新导出</button> : null}
      </div>}
      {!task && startError ? <p className="error-text">{startError}</p> : null}
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
  const [arrangementError, setArrangementError] = useState("");
  const [draggedId, setDraggedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAssets, setPickerAssets] = useState<Asset[]>([]);
  const [pickerPage, setPickerPage] = useState(0);
  const [pickerHasNext, setPickerHasNext] = useState(true);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickedIds, setPickedIds] = useState<Set<string>>(() => new Set());
  const [pickedOrder, setPickedOrder] = useState<string[]>([]);
  const [insertAfterId, setInsertAfterId] = useState("");
  const [insertedIds, setInsertedIds] = useState<string[]>([]);
  const [removedIds, setRemovedIds] = useState<string[]>([]);
  const [confirmClose, setConfirmClose] = useState(false);
  const original = useRef("");
  const loadArrangement = useCallback(async () => {
    setArrangementError("");
    const data = await api.reportArrangement(asset.id);
    if (data.ok === false) {
      const message = data.error || "无法加载页面编排";
      setArrangement(null);
      setArrangementError(message);
      showToast(message);
      return;
    }
    setArrangement(data);
    original.current = JSON.stringify(data.pages.map((page) => [page.id, page.hidden]));
  }, [asset.id, showToast]);
  useEffect(() => {
    void loadArrangement();
  }, [loadArrangement]);
  const dirty = Boolean(arrangement && (insertedIds.length || removedIds.length || JSON.stringify(arrangement.pages.map((page) => [page.id, page.hidden])) !== original.current));
  useEffect(() => {
    if (!dirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);
  useEscapeClose(() => { if (!busy) requestClose(); }, !busy && !pickerOpen && !confirmClose);
  useEscapeClose(() => setPickerOpen(false), pickerOpen && !busy);
  useEscapeClose(() => setConfirmClose(false), confirmClose && !busy);
  const loadPicker = async (page: number, reset = false) => {
    if (pickerLoading || (!reset && !pickerHasNext)) return;
    setPickerLoading(true);
    const data = await api.assets({ view: "list", type: "control", page, page_size: 20, q: pickerQuery || undefined });
    if (data.ok === false) {
      showToast(data.error || "页面列表读取失败，请重试");
      setPickerLoading(false);
      return;
    }
    const items = data.assets || [];
    setPickerAssets((current) => reset ? items : [...current, ...items.filter((item) => !current.some((existing) => existing.id === item.id))]);
    setPickerPage(page);
    setPickerHasNext(Boolean(data.pagination?.hasNext));
    setPickerLoading(false);
  };
  const openPicker = () => {
    setPickerOpen(true);
    setPickedIds(new Set());
    setPickedOrder([]);
    setInsertAfterId(arrangement?.pages.at(-1)?.id || "");
    setPickerAssets([]);
    setPickerPage(0);
    setPickerHasNext(true);
    void loadPicker(1, true);
  };
  const insertPicked = () => {
    if (!arrangement || !pickedIds.size) return;
    const assetsById = new Map(pickerAssets.map((item) => [item.id, item]));
    const inserted = pickedOrder.flatMap((id, index) => {
      const selectedAsset = assetsById.get(id);
      if (!selectedAsset) return [];
      return [{
        id: selectedAsset.id,
        slotNumber: 0,
        order: arrangement.pages.length + index + 1,
        title: selectedAsset.title,
        code: selectedAsset.asset_code,
        previewUrl: selectedAsset.preview_url,
        thumbnailUrl: selectedAsset.thumbnail_url || selectedAsset.preview_url,
        hidden: false
      }];
    });
    const insertIndex = insertAfterId
      ? Math.max(0, arrangement.pages.findIndex((page) => page.id === insertAfterId) + 1)
      : 0;
    const pages = [...arrangement.pages];
    pages.splice(insertIndex, 0, ...inserted);
    setArrangement({ ...arrangement, pages });
    setInsertedIds((current) => [...current, ...inserted.map((item) => item.id)]);
    setPickerOpen(false);
  };
  const movePageBy = (pageId: string, delta: number) => {
    if (!arrangement || busy) return;
    const index = arrangement.pages.findIndex((page) => page.id === pageId);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= arrangement.pages.length) return;
    const pages = [...arrangement.pages];
    const [item] = pages.splice(index, 1);
    pages.splice(target, 0, item);
    setArrangement({ ...arrangement, pages });
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(`[data-arrangement-page="${CSS.escape(pageId)}"]`)?.focus();
    });
  };
  const confirm = async (): Promise<boolean> => {
    if (!arrangement) return false;
    setBusy(true);
    try {
      const requestedOrder = arrangement.pages.map((page) => page.id);
      const requestedHidden = arrangement.pages.filter((page) => page.hidden).map((page) => page.id);
      const data = await api.updateReportArrangement(asset.id, {
        pageOrder: requestedOrder,
        hiddenPageIds: requestedHidden,
        insertedControlIds: insertedIds,
        removedPageIds: removedIds,
        expectedUpdatedAt: arrangement.updatedAt
      });
      if (data.ok === false) {
        if ((data as { conflict?: boolean }).conflict) {
          showToast("该汇报已在其他窗口更新，请重新加载后再编辑");
          setArrangementError("检测到其他窗口的编排更新");
        } else {
          showToast(data.error || "编排更新失败");
        }
        return false;
      }
      const verified = await api.reportArrangement(asset.id);
      const verifiedOrder = verified.ok === false ? [] : verified.pages.map((page) => page.id);
      const verifiedHidden = verified.ok === false ? [] : verified.pages.filter((page) => page.hidden).map((page) => page.id);
      if (verified.ok === false || JSON.stringify(verifiedOrder) !== JSON.stringify(data.pages.map((page) => page.id)) || JSON.stringify(verifiedHidden) !== JSON.stringify(data.pages.filter((page) => page.hidden).map((page) => page.id))) {
        showToast("编排尚未完全生效，请稍后重试");
        return false;
      }
      let previewReady = false;
      const previewController = new AbortController();
      const previewTimer = window.setTimeout(() => previewController.abort(), 20000);
      try {
        const viewer = await fetch(
          `${data.previewUrl}${data.previewUrl.includes("?") ? "&" : "?"}v=${encodeURIComponent(String(data.updatedAt || Date.now()))}`,
          { cache: "no-store", signal: previewController.signal }
        );
        previewReady = viewer.ok;
      } catch {
        previewReady = false;
      } finally {
        window.clearTimeout(previewTimer);
      }
      setArrangement(verified);
      setInsertedIds([]);
      setRemovedIds([]);
      original.current = JSON.stringify(verified.pages.map((page) => [page.id, page.hidden]));
      await refreshAsset(asset.id);
      showToast(previewReady ? "编排已确认并生效" : "编排已保存，预览暂时无法刷新");
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
  function requestClose() {
    if (dirty) setConfirmClose(true);
    else close();
  }
  return <section className="arrangement-workspace" aria-label="汇报页面编排">
    <header className="arrangement-toolbar"><div><button className="icon-btn" title="返回汇报" aria-label="返回汇报" type="button" onClick={requestClose}><ChevronRight className="back-icon" size={18} /></button><code>页面编排</code><h2>{asset.title}</h2></div><div className="modal-actions"><button className="secondary" type="button" disabled={busy} onClick={openPicker}><Plus size={16} />插入页面</button><button className="primary" type="button" disabled={!dirty || busy} onClick={() => void confirm()}>{busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{busy ? "正在生效" : "确认编排"}</button></div></header>
    <div className="arrangement-grid arrangement-workspace-grid">
      {!arrangement ? (
        <div className="empty-state">
          {arrangementError ? <AlertCircle size={18} /> : <Loader2 className="spin" size={18} />}
          <strong>{arrangementError || "正在加载页面…"}</strong>
          {arrangementError ? <button className="secondary" type="button" onClick={() => void loadArrangement()}>重新加载</button> : null}
        </div>
      ) : arrangement.pages.map((page, index) => <article key={`${page.id}-${index}`} className={classNames("arrangement-page", page.hidden && "is-hidden")} data-arrangement-page={page.id} tabIndex={0} draggable={!busy} onDragStart={() => setDraggedId(page.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => move(page.id)} onKeyDown={(event) => {
          if (!(event.altKey || event.metaKey)) return;
          if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
            event.preventDefault();
            movePageBy(page.id, -1);
          }
          if (event.key === "ArrowDown" || event.key === "ArrowRight") {
            event.preventDefault();
            movePageBy(page.id, 1);
          }
        }}>
          <div className="arrangement-thumb"><img src={page.thumbnailUrl} alt={page.title} loading="lazy" /></div>
          <div><span>#{String(index + 1).padStart(2, "0")}</span><strong>{page.title}</strong><small>{page.code}</small></div>
          <div className="arrangement-actions"><GripVertical size={16} /><button className="icon-btn" type="button" disabled={index === 0 || busy} title="向前移动" aria-label="向前移动" onClick={() => movePageBy(page.id, -1)}>↑</button><button className="icon-btn" type="button" disabled={index === arrangement.pages.length - 1 || busy} title="向后移动" aria-label="向后移动" onClick={() => movePageBy(page.id, 1)}>↓</button><button className="icon-btn" type="button" title={page.hidden ? "恢复页面" : "隐藏页面"} aria-label={page.hidden ? "恢复页面" : "隐藏页面"} onClick={() => setArrangement({ ...arrangement, pages: arrangement.pages.map((item, itemIndex) => itemIndex === index ? { ...item, hidden: !item.hidden } : item) })}>{page.hidden ? <Eye size={15} /> : <EyeOff size={15} />}</button><button className="icon-btn danger-icon" type="button" title="从当前汇报移出" aria-label="从当前汇报移出" onClick={() => removePage(page.id)}><Trash2 size={15} /></button></div>
        </article>)}</div>
    {pickerOpen ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={() => setPickerOpen(false)} aria-label="关闭" /><section className="modal-panel page-picker-panel"><header className="modal-head"><div><code>页面素材</code><h2>批量插入页面</h2></div><div className="modal-actions"><input data-modal-initial-focus value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void loadPicker(1, true)} placeholder="搜索页面素材" /><button className="icon-btn" onClick={() => setPickerOpen(false)} aria-label="关闭"><X size={16} /></button></div></header><div className="page-picker-grid" onScroll={(event) => { const el = event.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 160) void loadPicker(pickerPage + 1); }}>{pickerAssets.map((item) => <button key={item.id} type="button" className={classNames("page-picker-card", pickedIds.has(item.id) && "is-selected")} onClick={() => {
      setPickedIds((current) => {
        const next = new Set(current);
        if (next.has(item.id)) next.delete(item.id);
        else next.add(item.id);
        return next;
      });
      setPickedOrder((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id]);
    }}><img src={item.thumbnail_url || item.preview_url} alt="" loading="lazy" /><span>{item.title}</span><small>{item.asset_code}</small></button>)}{pickerLoading ? <div className="empty-state">正在加载…</div> : null}</div><footer className="page-picker-footer"><label><span>插入位置</span><select value={insertAfterId} onChange={(event) => setInsertAfterId(event.target.value)}><option value="">汇报最前面</option>{arrangement?.pages.map((page, index) => <option key={page.id} value={page.id}>第 {index + 1} 页之后 · {page.title}</option>)}</select></label><span>{pickedIds.size} 页已选择 · 按选择顺序插入</span><button className="primary" disabled={!pickedIds.size} type="button" onClick={insertPicked}><Plus size={16} />插入所选页面</button></footer></section></div> : null}
    {confirmClose ? <div className="modal" role="dialog" aria-modal="true"><button className="modal-mask" onClick={() => setConfirmClose(false)} aria-label="继续编辑" /><section className="modal-panel confirm-panel"><h2>是否保存编排？</h2><p>当前顺序、隐藏、移出和插入页面尚未生效。</p><footer><button className="secondary" disabled={busy} onClick={() => close()}>放弃修改</button><button className="secondary" data-modal-initial-focus disabled={busy} onClick={() => setConfirmClose(false)}>继续编辑</button><button className="primary" disabled={busy} onClick={() => void confirm().then((saved) => { if (saved) close(); })}>{busy ? "正在生效" : "保存编排"}</button></footer></section></div> : null}
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
