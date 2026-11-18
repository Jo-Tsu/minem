import { AlertCircle, Box, CheckCircle2, Clock3, FileArchive, FileText, Loader2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
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

export function ImportDialog({ mode, close, startImport, startDriveImport }: {
  mode: ImportMode;
  close: () => void;
  startImport: (file: File, description: string) => Promise<boolean>;
  startDriveImport: (links: string[], description: string) => Promise<boolean>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<"file" | "drive">("file");
  const [linksText, setLinksText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const externalMode = mode === "external-report";
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current || (source === "file" && !file)) return;
    const links = linksText.split(/\r?\n/).map((link) => link.trim()).filter(Boolean);
    if (source === "drive" && (!links.length || links.length > 8)) {
      setError("请输入 1 至 8 个飞书文件夹链接，每行一个。");
      return;
    }
    const prefix = externalMode ? "外部资源导入" : "平台导入";
    submitting.current = true;
    setPending(true);
    setError("");
    try {
      const note = [prefix, description.trim()].filter(Boolean).join("：");
      const success = source === "drive" ? await startDriveImport(links, note) : await startImport(file!, note);
      if (!success) setError("导入提交失败，请检查提示后重试。");
    } catch {
      setError("导入提交失败，请稍后重试。");
    } finally {
      submitting.current = false;
      setPending(false);
    }
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
        <div className="chip-row">
          <button type="button" disabled={pending} className={source === "file" ? "active" : ""} onClick={() => { setSource("file"); setError(""); }}>文件上传</button>
          <button type="button" disabled={pending} className={source === "drive" ? "active" : ""} onClick={() => { setSource("drive"); setError(""); }}>飞书链接</button>
        </div>
        {source === "file" ? <><div className="import-hints">
          <div><FileText size={15} /><span>HTML 汇报</span></div>
          <div><FileArchive size={15} /><span>ZIP 素材包</span></div>
          <div><Box size={15} /><span>资源文件</span></div>
        </div>
        <label className="file-drop">
          <input type="file" disabled={pending} accept={IMPORT_ACCEPT} onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <Upload size={22} />
          <strong>{file?.name || "选择 HTML 或 ZIP"}</strong>
          <span>{file ? `${file.type || "本地文件"} · ${formatFileSize(file.size)}` : "支持 HTML / ZIP / 图片 / SVG / GIF / 视频"}</span>
        </label></> : <label className="import-field"><span>飞书云空间文件夹链接</span><textarea rows={4} disabled={pending} value={linksText} onChange={(event) => setLinksText(event.target.value)} placeholder="每行一个飞书云空间文件夹链接，最多 8 个" /></label>}
        <label className="import-field"><span>导入说明</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="行业、用途、页面特点，可留空" /></label>
        <div className="import-note"><AlertCircle size={15} /><span>平台只复制入库文件并建立素材记录，不改变原始素材目录和生成方式。</span></div>
        {error ? <p className="error-text" role="alert">{error}</p> : null}
        <footer>
          <button className="primary" type="submit" disabled={pending || (source === "file" ? !file : !linksText.trim())}>{pending ? "正在提交" : "开始导入"}</button>
          <button className="secondary" type="button" onClick={close}>取消</button>
        </footer>
      </form>
    </div>
  );
}

export function ImportTaskDock({ tasks, dismissTask, retryTask }: { tasks: ImportTask[]; dismissTask?: (taskId: string) => void; retryTask?: (task: ImportTask) => Promise<boolean> }) {
  const [retrying, setRetrying] = useState<string | null>(null);
  if (!tasks.length) return null;
  return (
    <aside className="import-task-dock">
      <header><strong>导入任务</strong><span>{tasks.filter(isActiveImportTask).length} 个进行中</span></header>
      {tasks.map((task) => (
        <article key={task.id} className={`task-card is-${task.status}`}>
          <header>
            {(() => {
              const meta = importStatusMeta(task.status);
              const Icon = meta.icon;
              return <span><Icon size={13} />{meta.label}</span>;
            })()}
            <strong>{task.fileName || "导入文件"}</strong>
            {!isActiveImportTask(task) && dismissTask ? <button className="task-dismiss" type="button" onClick={() => dismissTask(task.id)} title="关闭导入任务" aria-label="关闭导入任务"><X size={13} /></button> : null}
          </header>
          <small>{task.message || task.error || "等待处理"}</small>
          {task.sourceUrl ? <div className="task-source"><a href={task.sourceUrl} target="_blank" rel="noreferrer">原飞书链接</a>
            {task.status === "failed" && retryTask ? <button type="button" className="secondary" disabled={retrying !== null} onClick={async () => {
              setRetrying(task.id);
              try { await retryTask(task); } finally { setRetrying(null); }
            }}>{retrying === task.id ? "正在提交" : "重试导入"}</button> : null}
          </div> : null}
          <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
          <footer><span>{task.status === "success" ? "已入库" : task.status === "failed" ? task.error || "失败" : `${task.progress || 0}%`}</span>{task.previewUrl ? <a href={task.previewUrl} target="_blank" rel="noreferrer">预览</a> : null}</footer>

        </article>
      ))}
    </aside>
  );
}

export function ImportHistoryDialog({ tasks, close, retryTask }: {
  tasks: ImportTask[]; close: () => void; retryTask: (task: ImportTask) => Promise<boolean>;
}) {
  return <div className="modal" role="dialog" aria-modal="true" aria-label="导入记录">
    <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
    <section className="modal-panel import-history"><header><h2>导入记录</h2><button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={16} /></button></header>
      {tasks.length ? <ImportTaskDock tasks={tasks} retryTask={retryTask} /> : <p>暂无导入记录</p>}
    </section>
  </div>;
}
