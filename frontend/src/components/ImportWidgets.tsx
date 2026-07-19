import { AlertCircle, Box, CheckCircle2, Clock3, FileArchive, FileText, Loader2, Upload, X } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import type { ImportTask } from "../types";

const IMPORT_ACCEPT = ".zip,.html,.htm,.svg,.png,.jpg,.jpeg,.gif,.webp,.mp4,.mov,.m4v,.webm";

export type ImportMode = "general" | "external-report";

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

export function ImportDialog({ mode, close, startImport }: {
  mode: ImportMode;
  close: () => void;
  startImport: (file: File, description: string) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const externalMode = mode === "external-report";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const prefix = externalMode ? "外部资源导入" : "平台导入";
    void startImport(file, [prefix, description.trim()].filter(Boolean).join("："));
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="import-panel" onSubmit={submit}>
        <header>
          <div>
            <span>{externalMode ? "EXTERNAL" : "IMPORT"}</span>
            <h2>{externalMode ? "导入外部资源" : "添加导入"}</h2>
            <p>{externalMode ? "支持外部 HTML、ZIP、图片、SVG、GIF 和视频，入库后解析为 MineM 可复用素材。" : "上传完整 HTML、ZIP 或资源文件。导入进入后台任务，成功后素材卡片可以直接预览。"}</p>
          </div>
          <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="import-hints">
          <div><FileText size={15} /><span>HTML 汇报</span></div>
          <div><FileArchive size={15} /><span>ZIP 素材包</span></div>
          <div><Box size={15} /><span>资源文件</span></div>
        </div>
        <label className="file-drop">
          <input type="file" accept={IMPORT_ACCEPT} onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <Upload size={22} />
          <strong>{file?.name || "选择 HTML 或 ZIP"}</strong>
          <span>{file ? `${file.type || "本地文件"} · ${formatFileSize(file.size)}` : "支持 HTML / ZIP / 图片 / SVG / GIF / 视频"}</span>
        </label>
        <label className="import-field"><span>导入说明</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="行业、用途、页面特点，可留空" /></label>
        <div className="import-note"><AlertCircle size={15} /><span>平台只复制入库文件并建立素材记录，不改变原始素材目录和生成方式。</span></div>
        <footer>
          <button className="primary" type="submit" disabled={!file}>开始导入</button>
          <button className="secondary" type="button" onClick={close}>取消</button>
        </footer>
      </form>
    </div>
  );
}

export function ImportTaskDock({ tasks, dismissTask }: { tasks: ImportTask[]; dismissTask: (taskId: string) => void }) {
  if (!tasks.length) return null;
  return (
    <aside className="import-task-dock">
      <header><strong>导入任务</strong><span>{tasks.filter(isActiveImportTask).length} 个进行中</span></header>
      {tasks.slice(0, 6).map((task) => (
        <article key={task.id} className={`task-card is-${task.status}`}>
          <header>
            {(() => {
              const meta = importStatusMeta(task.status);
              const Icon = meta.icon;
              return <span><Icon size={13} />{meta.label}</span>;
            })()}
            <strong>{task.fileName || "导入文件"}</strong>
            {!isActiveImportTask(task) ? <button className="task-dismiss" type="button" onClick={() => dismissTask(task.id)} title="关闭导入任务" aria-label="关闭导入任务"><X size={13} /></button> : null}
          </header>
          <small>{task.message || task.error || "等待处理"}</small>
          <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
          <footer><span>{task.status === "success" ? `成功 ${task.assetCount || 0} 个` : task.status === "failed" ? task.error || "失败" : `${task.progress || 0}%`}</span>{task.previewUrl ? <a href={task.previewUrl} target="_blank" rel="noreferrer">预览</a> : null}</footer>
        </article>
      ))}
    </aside>
  );
}
