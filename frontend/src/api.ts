import type {
  ApiOk,
  Asset,
  AssetsResponse,
  CaseControlGroup,
  ImportTask,
  LineageResponse,
  ReportExportTask,
  ReportArrangement,
  StatsResponse,
  TempReportResponse
} from "./types";

type Params = Record<string, string | number | boolean | undefined | null>;

function apiUrl(path: string, params?: Params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

async function readJson<T>(response: Response): Promise<T> {
  let data;
  try {
    data = await response.json();
  } catch {
    return { ok: false, error: `服务响应格式异常（HTTP ${response.status}），请稍后重试` } as T;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, error: "服务响应格式异常，请稍后重试" } as T;
  }
  if (!response.ok) {
    return { ...data, ok: false, error: data.error || response.statusText } as T;
  }
  return data as T;
}

async function requestJson<T>(path: string, options: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeoutMs);
  try {
    return await readJson<T>(await fetch(path, { ...options, signal: controller.signal }));
  } catch (error) {
    if (options.signal?.aborted) throw error;
    return { ok: false, error: controller.signal.aborted ? "请求超时，请重试" : "无法连接服务，请稍后重试" } as T;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

async function getJson<T>(path: string, params?: Params, signal?: AbortSignal) {
  return requestJson<T>(apiUrl(path, params), { signal });
}

async function postJson<T>(path: string, body: unknown = {}) {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

async function postForm<T>(path: string, formData: FormData) {
  return requestJson<T>(path, { method: "POST", body: formData }, 180000);
}

async function postEmpty<T>(path: string) {
  return requestJson<T>(path, { method: "POST" });
}

async function deleteJson<T>(path: string) {
  return requestJson<T>(path, { method: "DELETE" });
}

export const api = {
  stats: () => getJson<ApiOk<StatsResponse>>("/api/stats"),
  caseGroups: () => getJson<ApiOk<{ caseGroups: CaseControlGroup[]; total: number }>>("/api/case-groups"),
  assets: (params: Params) => getJson<ApiOk<AssetsResponse>>("/api/assets", params),
  asset: (assetId: string) => getJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}`),
  assetVersions: (assetId: string) => getJson<ApiOk<{ groupId: string; versions: Asset[] }>>(`/api/assets/${encodeURIComponent(assetId)}/versions`),
  assetLineage: (assetId: string) => getJson<LineageResponse>(`/api/assets/${encodeURIComponent(assetId)}/lineage`),
  createReport: (body: { title: string; pageIds: string[]; note?: string; coverTemplateId?: string }) =>
    postJson<ApiOk<{ asset: Asset; url: string }>>("/api/reports", body),
  reportArrangement: (reportId: string) =>
    getJson<ApiOk<ReportArrangement>>(`/api/reports/${encodeURIComponent(reportId)}/arrangement`),
  updateReportArrangement: (reportId: string, body: { pageOrder: string[]; hiddenPageIds: string[]; insertedControlIds?: string[]; removedPageIds?: string[]; expectedUpdatedAt?: number }) =>
    postJson<ApiOk<ReportArrangement>>(`/api/reports/${encodeURIComponent(reportId)}/arrangement`, body),
  createReportExport: (reportId: string, format: "html" | "pdf") =>
    postJson<ApiOk<{ task: ReportExportTask }>>(`/api/reports/${encodeURIComponent(reportId)}/exports`, { format }),
  reportExportTask: (taskId: string, signal?: AbortSignal) =>
    getJson<ApiOk<{ task: ReportExportTask }>>(`/api/report-exports/${encodeURIComponent(taskId)}`, undefined, signal),
  reportExportTasks: (reportId: string) =>
    getJson<ApiOk<{ tasks: ReportExportTask[] }>>(`/api/reports/${encodeURIComponent(reportId)}/exports`),
  importTasks: (signal?: AbortSignal) => getJson<ApiOk<{ tasks: ImportTask[] }>>("/api/import-tasks", undefined, signal),
  createImportTask: (formData: FormData) => postForm<ApiOk<{ task: ImportTask }>>("/api/import-tasks", formData),
  createDriveImportTasks: (links: string[], description: string) =>
    postJson<ApiOk<{ tasks: ImportTask[] }>>("/api/import-tasks/drive", { links, description }),
  autoImport: () => postEmpty<ApiOk<{ scanned: number; assetCount: number }>>("/api/auto-import"),
  mergeSimilar: () => postEmpty<ApiOk<{ scanned: number; mergedAssets: number; groups: number }>>("/api/merge-similar"),
  manualMergeAssets: (body: { assetIds: string[]; primaryAssetId: string; mode: "keep" | "version" }) =>
    postJson<ApiOk<{ primary: Asset; versions: Asset[]; versionCount: number; mergedCount: number; updatedReferences: number }>>("/api/assets/manual-merge", body),
  createTempReport: (controlIds: string[]) => postJson<ApiOk<TempReportResponse>>("/api/temp-reports", { controlIds }),
  renameAsset: (assetId: string, title: string) => postJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}/title`, { title }),
  deleteAsset: (assetId: string) => deleteJson<ApiOk<{ assetCode: string }>>(`/api/assets/${encodeURIComponent(assetId)}`),
};

export function absoluteUrl(url?: string) {
  if (!url) return window.location.href;
  return new URL(url, window.location.href).href;
}
