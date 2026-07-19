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
  const data = await response.json();
  if (!response.ok && data && typeof data === "object") {
    return { ok: false, error: data.error || response.statusText, ...data } as T;
  }
  return data as T;
}

async function getJson<T>(path: string, params?: Params) {
  return readJson<T>(await fetch(apiUrl(path, params)));
}

async function postJson<T>(path: string, body: unknown = {}) {
  return readJson<T>(await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }));
}

async function postForm<T>(path: string, formData: FormData) {
  return readJson<T>(await fetch(path, { method: "POST", body: formData }));
}

async function postEmpty<T>(path: string) {
  return readJson<T>(await fetch(path, { method: "POST" }));
}

async function deleteJson<T>(path: string) {
  return readJson<T>(await fetch(path, { method: "DELETE" }));
}

export const api = {
  stats: () => getJson<StatsResponse>("/api/stats"),
  caseGroups: () => getJson<ApiOk<{ caseGroups: CaseControlGroup[]; total: number }>>("/api/case-groups"),
  assets: (params: Params) => getJson<AssetsResponse>("/api/assets", params),
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
  updateReportArrangement: (reportId: string, body: { pageOrder: string[]; hiddenPageIds: string[]; insertedControlIds?: string[]; removedPageIds?: string[] }) =>
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
  createImportTask: (formData: FormData) => postForm<ApiOk<{ task: ImportTask }>>("/api/import-tasks", formData),
  autoImport: () => postEmpty<ApiOk<{ scanned: number; assetCount: number }>>("/api/auto-import"),
  aiTag: (assetType: string) => postJson<ApiOk<{ scanned: number; updated: number }>>("/api/ai-tag", { asset_type: assetType }),
  createTagAnalysisTask: (assetId: string) => postJson<ApiOk<{ task: { id: string; status: string } }>>("/api/tag-analysis/tasks", { assetIds: [assetId] }),
  mergeSimilar: () => postEmpty<ApiOk<{ scanned: number; mergedAssets: number; groups: number }>>("/api/merge-similar"),
  manualMergeAssets: (body: { assetIds: string[]; primaryAssetId: string; mode: "keep" | "version" }) =>
    postJson<ApiOk<{ primary: Asset; versions: Asset[]; versionCount: number; mergedCount: number; updatedReferences: number }>>("/api/assets/manual-merge", body),
  createTempReport: (controlIds: string[]) => postJson<ApiOk<TempReportResponse>>("/api/temp-reports", { controlIds }),
  saveAssetTags: (assetId: string, tags: string[]) => postJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}/tags`, { tags }),
  renameAsset: (assetId: string, title: string) => postJson<ApiOk<{ asset: Asset }>>(`/api/assets/${encodeURIComponent(assetId)}/title`, { title }),
  deleteAsset: (assetId: string) => deleteJson<ApiOk<{ assetCode: string }>>(`/api/assets/${encodeURIComponent(assetId)}`),
  adoptCandidate: (candidateId: string) => postJson<ApiOk>(`/api/report-page-candidates/${encodeURIComponent(candidateId)}/adopt`, {})
};

export function absoluteUrl(url?: string) {
  if (!url) return window.location.href;
  return new URL(url, window.location.href).href;
}
