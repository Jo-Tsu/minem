import { AlertCircle, Box, CheckCircle2, ChevronDown, Clock3, Copy, ExternalLink, FileArchive, FileText, Loader2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useModalBehavior } from "../modal";
import type { ImportTask } from "../types";

const IMPORT_ACCEPT = ".zip,.html,.htm,.svg,.png,.jpg,.jpeg,.gif,.webp,.mp4,.mov,.m4v,.webm";
const IMPORT_SUFFIXES = new Set(IMPORT_ACCEPT.split(","));

export type ImportMode = "general" | "external-report";
type ImportStartResult = { ok: boolean; error?: string };

function formatFileSize(value?: number) {
  if (!value) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function isActiveImportTask(task: ImportTask) {
  return task.status === "queued" || task.status === "running";
}

function importStatusMeta(status: ImportTask["status"]) {
  if (status === "success") return { label: "成功", icon: CheckCircle2 };
  if (status === "failed") return { label: "失败", icon: AlertCircle };
  if (status === "running") return { label: "处理中", icon: Loader2 };
  return { label: "排队中", icon: Clock3 };
}

function acceptsImportFile(file: File) {
  const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  return IMPORT_SUFFIXES.has(suffix);
}

export function ImportDialog({ mode, close, startImport }: {
  mode: ImportMode;
  close: () => void;
  startImport: (file: File, description: string, onProgress: (progress: number) => void, signal: AbortSignal) => Promise<ImportStartResult>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const uploadController = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const externalMode = mode === "external-report";
  useModalBehavior(() => {
    if (submitting) uploadController.current?.abort();
    else close();
  });
  const chooseFile = (nextFile: File | null) => {
    setError("");
    if (!nextFile) {
      setFile(null);
      return;
    }
    if (!acceptsImportFile(nextFile)) {
      setFile(null);
      setError("该文件类型暂不支持，请选择 HTML、ZIP、图片、SVG、GIF 或视频");
      return;
    }
    setFile(nextFile);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || submitting) return;
    const prefix = externalMode ? "外部资源导入" : "平台导入";
    setSubmitting(true);
    setUploadProgress(1);
    setError("");
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const result = await startImport(
        file,
        [prefix, description.trim()].filter(Boolean).join("："),
        setUploadProgress,
        controller.signal
      );
      if (result.ok) return;
      if (result.error === "文件上传已取消") {
        setError("已取消上传，可以重新选择文件");
      } else {
        setError(result.error || "导入任务创建失败，请重试");
      }
    } catch {
      setError("导入请求异常，请确认本机服务运行后重试");
    } finally {
      uploadController.current = null;
      setUploadProgress(0);
      setSubmitting(false);
    }
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={() => { if (!submitting) close(); }} aria-label="关闭" />
      <form className="import-panel" onSubmit={(event) => void submit(event)} aria-busy={submitting}>
        <header>
          <div>
            <span>{externalMode ? "EXTERNAL" : "IMPORT"}</span>
            <h2>{externalMode ? "导入外部资源" : "添加导入"}</h2>
            <p>{externalMode ? "支持外部 HTML、ZIP、图片、SVG、GIF 和视频，入库后解析为 MineM 可复用素材。" : "上传完整 HTML、ZIP 或资源文件。导入进入后台任务，成功后素材卡片可以直接预览。"}</p>
          </div>
          <button className="icon-btn" type="button" disabled={submitting} onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="import-hints">
          <div><FileText size={15} /><span>HTML 汇报</span></div>
          <div><FileArchive size={15} /><span>ZIP 素材包</span></div>
          <div><Box size={15} /><span>资源文件</span></div>
        </div>
        <label
          data-modal-initial-focus
          tabIndex={submitting ? -1 : 0}
          role="button"
          aria-label={file ? `重新选择文件，当前为 ${file.name}` : "选择或拖入导入文件"}
          className={`file-drop${dragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
          onKeyDown={(event) => {
            if (submitting || (event.key !== "Enter" && event.key !== " ")) return;
            event.preventDefault();
            fileInput.current?.click();
          }}
          onDragEnter={(event) => { event.preventDefault(); if (!submitting) setDragging(true); }}
          onDragOver={(event) => { event.preventDefault(); }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            if (!submitting) chooseFile(event.dataTransfer.files?.[0] || null);
          }}
        >
          <input
            ref={fileInput}
            type="file"
            accept={IMPORT_ACCEPT}
            disabled={submitting}
            onChange={(event) => chooseFile(event.target.files?.[0] || null)}
          />
          {submitting ? <Loader2 className="spin" size={22} /> : file ? <CheckCircle2 size={22} /> : <Upload size={22} />}
          <strong>{submitting ? "正在上传到本机服务" : file?.name || (dragging ? "松开即可选择文件" : "点击选择或拖入文件")}</strong>
          <span>{file ? `${file.type || "本地文件"} · ${formatFileSize(file.size)}` : "支持 HTML / ZIP / 图片 / SVG / GIF / 视频"}</span>
        </label>
        {submitting ? (
          <div className="upload-progress" role="status" aria-live="polite">
            <div><i style={{ width: `${Math.max(2, uploadProgress)}%` }} /></div>
            <span>{uploadProgress >= 100 ? "文件已上传，正在创建导入任务…" : `正在上传 ${uploadProgress}%`}</span>
          </div>
        ) : null}
        <label className="import-field"><span>导入说明</span><input disabled={submitting} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="行业、用途、页面特点，可留空" /></label>
        <div className="import-note"><AlertCircle size={15} /><span>平台只复制入库文件并建立素材记录，不改变原始素材目录和生成方式。</span></div>
        {error ? <div className="import-error" role="alert"><AlertCircle size={15} /><span>{error}</span></div> : null}
        <footer>
          <button className="primary" type="submit" disabled={!file || submitting}>
            {submitting ? <Loader2 className="spin" size={15} /> : <Upload size={15} />}
            {submitting ? "正在上传" : "开始导入"}
          </button>
          <button className="secondary" type="button" onClick={() => {
            if (submitting) uploadController.current?.abort();
            else close();
          }}>{submitting ? "取消上传" : "取消"}</button>
        </footer>
      </form>
    </div>
  );
}

export function ImportTaskDock({ tasks, dismissTask, retryTask, openAsset, copyError, retryingTaskIds, connectionLost = false }: {
  tasks: ImportTask[];
  dismissTask: (taskId: string) => void;
  retryTask: (taskId: string) => void;
  openAsset: (assetId: string) => void;
  copyError: (text: string) => void;
  retryingTaskIds: Set<string>;
  connectionLost?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  if (!tasks.length) return null;
  return (
    <aside className={`import-task-dock${collapsed ? " is-collapsed" : ""}`}>
      <header>
        <div><strong>导入任务</strong><span>{connectionLost ? "连接中断" : `${tasks.filter(isActiveImportTask).length} 个进行中 · 共 ${tasks.length} 个`}</span></div>
        <button type="button" aria-expanded={!collapsed} aria-label={collapsed ? "展开导入任务" : "收起导入任务"} onClick={() => setCollapsed((value) => !value)}>
          <ChevronDown size={15} />
        </button>
      </header>
      {!collapsed ? tasks.slice(0, 6).map((task) => (
        <article key={task.id} className={`task-card is-${task.status}`}>
          <header>
            {(() => {
              if (connectionLost && isActiveImportTask(task)) {
                return <span><AlertCircle size={13} />连接中断</span>;
              }
              const meta = importStatusMeta(task.status);
              const Icon = meta.icon;
              return <span><Icon size={13} />{meta.label}</span>;
            })()}
            <strong>{task.fileName || "导入文件"}</strong>
            {(!isActiveImportTask(task) || connectionLost) ? <button className="task-dismiss" type="button" onClick={() => dismissTask(task.id)} title="关闭导入任务" aria-label="关闭导入任务"><X size={13} /></button> : null}
          </header>
          <small>{connectionLost && isActiveImportTask(task) ? "正在重新连接本机服务" : task.message || task.error || "等待处理"}</small>
          <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
          <footer>
            <span>{connectionLost && isActiveImportTask(task) ? "等待恢复" : task.status === "success" ? `成功 ${task.assetCount || 0} 个` : task.status === "failed" ? task.error || "失败" : `${task.progress || 0}%`}</span>
            {task.status === "failed" && task.error ? <button type="button" onClick={() => copyError(task.error)}><Copy size={12} />错误</button> : null}
            {task.status === "failed" && !connectionLost ? (
              <button type="button" disabled={retryingTaskIds.has(task.id)} onClick={() => retryTask(task.id)}>
                {retryingTaskIds.has(task.id) ? <Loader2 className="spin" size={12} /> : null}
                {retryingTaskIds.has(task.id) ? "重试中" : "重试"}
              </button>
            ) : null}
            {task.status === "success" && task.assetId ? <button type="button" onClick={() => openAsset(task.assetId!)}><ExternalLink size={12} />查看素材</button> : null}
            {task.previewUrl ? <a href={task.previewUrl} target="_blank" rel="noreferrer"><ExternalLink size={12} />预览</a> : null}
          </footer>
        </article>
      )) : null}
    </aside>
  );
}
