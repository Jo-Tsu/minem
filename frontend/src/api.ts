import type {
  ApiOk,
  Asset,
  AssetsResponse,
  CaseControlGroup,
  ImportTask,
  LineageResponse,
  PresenterScriptStatus,
  ReportExportTask,
  ReportArrangement,
  StatsResponse,
  Storyline,
  TempReportResponse
} from "./types";

type Params = Record<string, string | number | boolean | undefined | null>;

function sessionToken() {
  return document.querySelector<HTMLMetaElement>('meta[name="minem-session-token"]')?.content?.trim() || "";
}

function apiHeaders(existing?: HeadersInit) {
  const headers = new Headers(existing);
  const token = sessionToken();
  if (token) headers.set("X-MineM-Session-Token", token);
  return headers;
}

function apiUrl(path: string, params?: Params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

// Bounded default so a hung/dead backend can never leave the UI spinning
// forever. File uploads opt out (they can legitimately take minutes).
const DEFAULT_TIMEOUT_MS = 20000;
const LONG_OPERATION_TIMEOUT_MS = 10 * 60 * 1000;
const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;

async function requestJson<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    let response: Response;
    try {
      const secured = path.startsWith("/api/")
        ? { ...init, headers: apiHeaders(init?.headers) }
        : init;
      response = await fetch(path, controller ? { ...secured, signal: controller.signal } : secured);
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === "AbortError";
      return { ok: false, error: aborted ? "请求超时，请重试" : "网络连接失败，请确认本机服务是否运行" } as T;
    }
    let data: unknown = null;
    try {
      const text = await response.text();
      data = text ? JSON.parse(text) : null;
    } catch {
      if (controller?.signal.aborted) {
        return { ok: false, error: "请求超时，请重试" } as T;
      }
      return { ok: false, error: `服务返回内容异常（${response.status} ${response.statusText || "无响应"}）` } as T;
    }
    if (data && typeof data === "object") {
      if (!response.ok) {
        const detail = (data as { error?: string }).error || response.statusText;
        return { ok: false, error: detail, ...(data as object) } as T;
      }
      return data as T;
    }
    if (!response.ok) {
      return { ok: false, error: `请求失败（${response.status}）` } as T;
    }
    return data as T;
  } finally {
    if (timer !== null) window.clearTimeout(timer);
  }
}

async function getJson<T>(path: string, params?: Params) {
  return requestJson<T>(apiUrl(path, params));
}

async function postJson<T>(path: string, body: unknown = {}, timeoutMs?: number) {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }, timeoutMs);
}

function postForm<T>(
  path: string,
  formData: FormData,
  onProgress?: (progress: number) => void,
  signal?: AbortSignal
): Promise<T> {
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    const abortRequest = () => request.abort();
    request.open("POST", path);
    request.timeout = UPLOAD_TIMEOUT_MS;
    const token = sessionToken();
    if (token) request.setRequestHeader("X-MineM-Session-Token", token);
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      onProgress?.(Math.max(1, Math.min(100, Math.round((event.loaded / event.total) * 100))));
    });
    request.addEventListener("load", () => {
      let data: unknown = null;
      try {
        data = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        resolve({
          ok: false,
          error: `服务返回内容异常（${request.status || 0} ${request.statusText || "无响应"}）`
        } as T);
        return;
      }
      if (data && typeof data === "object") {
        if (request.status < 200 || request.status >= 300) {
          const detail = (data as { error?: string }).error || request.statusText || "上传失败";
          resolve({ ok: false, error: detail, ...(data as object) } as T);
          return;
        }
        onProgress?.(100);
        resolve(data as T);
        return;
      }
      resolve({ ok: false, error: `上传失败（${request.status || 0}）` } as T);
    });
    request.addEventListener("error", () => {
      resolve({ ok: false, error: "上传连接失败，请确认本机服务是否运行" } as T);
    });
    request.addEventListener("timeout", () => {
      resolve({ ok: false, error: "文件上传超时，请检查文件大小后重试" } as T);
    });
    request.addEventListener("abort", () => {
      resolve({ ok: false, error: "文件上传已取消" } as T);
    });
    if (signal?.aborted) {
      resolve({ ok: false, error: "文件上传已取消" } as T);
      return;
    }
    signal?.addEventListener("abort", abortRequest, { once: true });
    request.addEventListener("loadend", () => signal?.removeEventListener("abort", abortRequest));
    request.send(formData);
  });
}

async function postEmpty<T>(path: string, timeoutMs?: number) {
  return requestJson<T>(path, { method: "POST" }, timeoutMs);
}

async function deleteJson<T>(path: string) {
  return requestJson<T>(path, { method: "DELETE" });
}

export const api = {
  openCreatorAssistant: () => postEmpty<ApiOk>("/api/desktop/creator-assistant"),
  stats: () => getJson<ApiOk<StatsResponse>>("/api/stats"),
  caseGroups: () => getJson<ApiOk<{ caseGroups: CaseControlGroup[]; total: number }>>("/api/case-groups"),
  assets: (params: Params) => getJson<ApiOk<AssetsResponse>>("/api/assets", params),
  asset: (assetId: string) => getJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}`),
  assetVersions: (assetId: string) => getJson<ApiOk<{ groupId: string; versions: Asset[] }>>(`/api/assets/${encodeURIComponent(assetId)}/versions`),
  assetLineage: (assetId: string) => getJson<LineageResponse>(`/api/assets/${encodeURIComponent(assetId)}/lineage`),
  storylines: (params?: Params) => getJson<ApiOk<{ storylines: Storyline[] }>>("/api/storylines", params),
  createStorylineCollection: (reportId: string, body: { title: string; note?: string; mode?: "new" | "version"; target_storyline_id?: string }) =>
    postJson<ApiOk<{ storyline: Storyline }>>(`/api/reports/${encodeURIComponent(reportId)}/storyline-collections`, body),
  createStorylineReport: (body: { mode: "chat" | "manual" | "copy"; title: string; note?: string; firstControlId?: string; controlIds?: string[]; conversation?: string; storylineVersionId?: string }) =>
    postJson<ApiOk<{ asset: Asset; url: string }>>("/api/storyline-reports", body),
  reportPresenterScript: (reportId: string) =>
    getJson<ApiOk<PresenterScriptStatus>>(`/api/reports/${encodeURIComponent(reportId)}/presenter-script`),
  reportArrangement: (reportId: string) =>
    getJson<ApiOk<ReportArrangement>>(`/api/reports/${encodeURIComponent(reportId)}/arrangement`),
  updateReportArrangement: (reportId: string, body: { pageOrder: string[]; hiddenPageIds: string[]; insertedControlIds?: string[]; removedPageIds?: string[]; expectedUpdatedAt?: number }) =>
    postJson<ApiOk<ReportArrangement>>(`/api/reports/${encodeURIComponent(reportId)}/arrangement`, body),
  createReportExport: (reportId: string, format: "html" | "pdf") =>
    postJson<ApiOk<{ task: ReportExportTask }>>(`/api/reports/${encodeURIComponent(reportId)}/exports`, { format }),
  reportExportTask: (taskId: string) =>
    getJson<ApiOk<{ task: ReportExportTask }>>(`/api/report-exports/${encodeURIComponent(taskId)}`),
  generateReportPresenterScript: (reportId: string) =>
    postJson<ApiOk<{ scriptText: string; pageCount: number; sourceType: string }>>(`/api/reports/${encodeURIComponent(reportId)}/presenter-script/generate`, {}),
  extractReportPresenterScriptFile: (reportId: string, formData: FormData) =>
    postForm<ApiOk<{ scriptText: string; sourceType: string; fileName: string }>>(`/api/reports/${encodeURIComponent(reportId)}/presenter-script/extract`, formData),
  saveReportPresenterScript: (reportId: string, body: { sourceType: "minutes" | "script"; minutesUrl?: string; script: string }) =>
    postJson<ApiOk<PresenterScriptStatus>>(`/api/reports/${encodeURIComponent(reportId)}/presenter-script`, body),
  importTasks: () => getJson<ApiOk<{ tasks: ImportTask[] }>>("/api/import-tasks"),
  createImportTask: (formData: FormData, onProgress?: (progress: number) => void, signal?: AbortSignal) =>
    postForm<ApiOk<{ task: ImportTask }>>("/api/import-tasks", formData, onProgress, signal),
  retryImportTask: (taskId: string) =>
    postEmpty<ApiOk<{ task: ImportTask }>>(`/api/import-tasks/${encodeURIComponent(taskId)}/retry`),
  autoImport: () => postEmpty<ApiOk<{ scanned: number; assetCount: number }>>("/api/auto-import", LONG_OPERATION_TIMEOUT_MS),
  aiTag: (assetType: string) => postJson<ApiOk<{ scanned: number; updated: number }>>("/api/ai-tag", { asset_type: assetType }, LONG_OPERATION_TIMEOUT_MS),
  createTagAnalysisTask: (assetId: string) => postJson<ApiOk<{ task: { id: string; status: string } }>>("/api/tag-analysis/tasks", { assetIds: [assetId] }),
  mergeSimilar: () => postEmpty<ApiOk<{ scanned: number; mergedAssets: number; groups: number }>>("/api/merge-similar", LONG_OPERATION_TIMEOUT_MS),
  manualMergeAssets: (body: { assetIds: string[]; primaryAssetId: string; mode: "keep" | "version" }) =>
    postJson<ApiOk<{ primary: Asset; versions: Asset[]; versionCount: number; mergedCount: number; updatedReferences: number }>>("/api/assets/manual-merge", body),
  createTempReport: (controlIds: string[]) => postJson<ApiOk<TempReportResponse>>("/api/temp-reports", { controlIds }),
  saveAssetTags: (assetId: string, tags: string[]) => postJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}/tags`, { tags }),
  renameAsset: (assetId: string, title: string) => postJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}/title`, { title }),
  deleteAsset: (assetId: string) => deleteJson<ApiOk<{ assetCode: string }>>(`/api/assets/${encodeURIComponent(assetId)}`),
  deleteCaseGroup: (code: string) => deleteJson<ApiOk<{ deletedCount: number; skipped: string[] }>>(`/api/case-groups/${encodeURIComponent(code)}`),
  adoptCandidate: (candidateId: string) => postJson<ApiOk>(`/api/report-page-candidates/${encodeURIComponent(candidateId)}/adopt`, {})
};

export function absoluteUrl(url?: string) {
  if (!url) return "";
  try {
    return new URL(url, window.location.href).href;
  } catch {
    return "";
  }
}
