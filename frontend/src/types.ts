export type AssetType = "report" | "control" | "resource";
export type ViewKey = "workbench" | "materials" | "caseControl" | "storyline";

export type Pagination = {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  hasPrev: boolean;
  hasNext: boolean;
};

export type SourceBatch = {
  id: string;
  filename: string;
  storedPath: string;
  extractPath: string;
  fileCount: number;
  assetCount: number;
  createdAt: number;
  pageCount: number;
  typeCounts: Record<string, number>;
  resourceCounts: Record<string, number>;
  entryAsset?: {
    assetId: string;
    assetCode: string;
    title: string;
    pageCount: number;
    url: string;
  };
};

export type Asset = {
  id: string;
  title: string;
  category: string;
  usage: string;
  tags: string[];
  snippet: string;
  source_type: string;
  source_path: string;
  preview_url: string;
  upload_id: string;
  created_at: number;
  updated_at: number;
  activity_at?: number;
  trusted_page_count?: number;
  trusted_viewer_page_count?: number;
  displayPageCount?: number;
  asset_type: AssetType;
  asset_code: string;
  media_kind: string;
  source_hash: string;
  version_group: string;
  version_no: number;
  version_parent_id: string;
  similarity_score: number;
  similarity_method: string;
  resource_kind: string;
  tag_seeded: number;
  categoryLabel: string;
  typeLabel: string;
  mediaLabel: string;
  resourceKindLabel: string;
  thumbnail_url: string;
  preview_meta?: {
    width?: number;
    height?: number;
    aspectRatio?: number;
    longPage?: boolean;
  };
  versionCount: number;
  storylineCount: number;
  isPrimaryVersion: boolean;
  versionLabel: string;
  sourceBatch?: SourceBatch;
  trustedEntry?: Record<string, unknown>;
};

export type AssetsResponse = {
  assets: Asset[];
  pagination: Pagination;
  categories: Record<string, string>;
  types: Record<string, string>;
  resourceKinds: Record<string, string>;
  tagTaxonomy: Record<string, string[]>;
  pipeline: PipelineSummary | null;
};

export type PipelineStage = {
  key: AssetType;
  label: string;
  codePrefix: string;
  description: string;
  index: number;
  count: number;
};

export type PipelineSummary = {
  stages: PipelineStage[];
  resourceCounts: Record<string, number>;
  latestBatches: SourceBatch[];
};

export type StatsResponse = {
  assetCount: number;
  visibleAssetCount: number;
  rawAssetCount: number;
  versionedAssetCount: number;
  uploadCount: number;
  categories: Record<string, number>;
  types: Record<string, number>;
  pipeline: PipelineSummary;
};

export type CaseAiSection = {
  content: string;
  attachments: string[];
};

export type CaseAiInfo = {
  caseName: string;
  award: string;
  pageTitle: string;
  background: CaseAiSection;
  pain: CaseAiSection;
  solution: CaseAiSection;
  result: CaseAiSection;
  storyline: string;
  pageStructure: {
    style: string;
    order: string;
    keyAsset: string;
    modalAssets: string;
  };
  sourceUrl: string;
};

export type CaseControlItem = {
  id: string;
  code: string;
  award: string;
  title: string;
  scenario: string;
  sourceUrl: string;
  controlUrl: string;
  thumbnailUrl: string;
  reportPageUrl: string;
  summary: string;
  ai?: CaseAiInfo | null;
};

export type CaseControlGroup = {
  code: string;
  title: string;
  sourceDoc: string;
  detailUrl: string;
  reportUrl: string;
  caseCount: number;
  controlCount: number;
  attachmentCount: number;
  updatedAt: string;
  updatedAtMs: number;
  brand: string;
  controls: CaseControlItem[];
};

export type ApiOk<T = unknown> = T & { ok?: boolean; error?: string };

export type TempReportResponse = {
  id: string;
  url: string;
  pageCount: number;
  expiresAt: number;
};

export type ReportExportTask = {
  id: string;
  reportId: string;
  format: "html" | "pdf";
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  pageCount: number;
  filename: string;
  downloadUrl: string;
  error: string;
  createdAt: number;
  updatedAt: number;
};

export type ReportArrangementPage = {
  id: string;
  slotNumber: number;
  order: number;
  title: string;
  code: string;
  previewUrl: string;
  thumbnailUrl: string;
  hidden: boolean;
};

export type ReportArrangement = {
  reportId: string;
  pages: ReportArrangementPage[];
  updatedAt: number;
  previewUrl: string;
};

export type PresenterScriptStatus = {
  hasScript: boolean;
  scriptCount: number;
  pageCount: number;
  missingPresenter: boolean;
  presenterUrl: string;
  scriptText?: string;
  sourceType?: string;
  minutesUrl?: string;
};

export type ImportTask = {
  id: string;
  status: "queued" | "running" | "success" | "failed";
  fileName: string;
  message: string;
  error: string;
  progress: number;
  assetCount: number;
  previewUrl?: string;
  createdAt?: number;
  updatedAt?: number;
};

export type Storyline = {
  id: string;
  code: string;
  title: string;
  scenario: string;
  tone: string;
  tags: string[];
  fixedBlocks: string[];
  directory: Array<{
    title: string;
    role: string;
    defaultContent: string[];
  }>;
  sourceReportId?: string;
  sourceReportCode?: string;
  sourceReport?: {
    id: string;
    asset_code: string;
    title: string;
    asset_type: string;
    media_kind: string;
    preview_url: string;
    thumbnail_url: string;
    tags: string[];
    created_at?: number | string;
    updated_at?: number | string;
  } | null;
  outputReportId?: string;
  outputReportCode?: string;
  targetReportId?: string;
  mode?: "collection" | "new" | "version";
  note?: string;
  versionGroup?: string;
  versionNo?: number;
  versionParentId?: string;
  versionLabel?: string;
  versionCount?: number;
  versions?: Storyline[];
  createdAt?: number | string;
  updatedAt?: number | string;
};

export type LineageItem = {
  id?: string;
  assetId?: string;
  assetCode?: string;
  title?: string;
  typeLabel?: string;
  resourceKindLabel?: string;
  sourcePath?: string;
  sourceType?: string;
  previewUrl?: string;
  createdAt?: number;
  updatedAt?: number;
};

export type LineageSection = {
  key: string;
  label: string;
  value?: string | number;
  summary?: string;
  items?: LineageItem[];
  groups?: Array<{ key: string; label: string; items: LineageItem[] }>;
};

export type LineageResponse = ApiOk<{
  asset: LineageItem;
  sourceBatch?: SourceBatch;
  trustedEntry?: Record<string, unknown>;
  sections: LineageSection[];
}>;
