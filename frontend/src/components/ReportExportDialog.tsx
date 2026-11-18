import { Download, FileArchive, FileText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Asset, ReportExportTask } from "../types";

export function ReportExportDialog({ asset, close }: { asset: Asset; close: () => void }) {
  const [task, setTask] = useState<ReportExportTask | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<ReportExportTask[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const submitting = useRef(false);
  useEffect(() => {
    let cancelled = false;
    void api.reportExportTasks(asset.id).then((data) => {
      if (cancelled) return;
      setLoadingHistory(false);
      if (data.ok === false) { setError(data.error || "导出记录读取失败"); return; }
      const tasks = data.tasks || [];
      setHistory(tasks);
      setTask(tasks.find((item) => item.status === "queued" || item.status === "running") || null);
    });
    return () => { cancelled = true; };
  }, [asset.id]);
  const start = async (format: "html" | "pdf") => {
    if (submitting.current || loadingHistory) return;
    submitting.current = true;
    setStarting(true);
    setError("");
    try {
      const data = await api.createReportExport(asset.id, format);
      if (data.ok === false || !data.task) setError(data.error || "导出任务创建失败，请重试");
      else {
        setTask(data.task);
        setHistory((current) => [data.task, ...current]);
      }
    } finally {
      submitting.current = false;
      setStarting(false);
    }
  };
  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const taskId = task.id;
    const poll = async () => {
      const data = await api.reportExportTask(taskId, controller.signal).catch(() => null);
      if (controller.signal.aborted) return;
      if (!data || data.ok === false || !data.task) {
        setError(data?.error || "导出状态读取失败，正在重试");
        timer = setTimeout(() => void poll(), 5000);
        return;
      }
      setError("");
      setTask(data.task);
      setHistory((current) => current.map((item) => item.id === data.task.id ? data.task : item));
      if (data.task.status === "queued" || data.task.status === "running") timer = setTimeout(() => void poll(), 1000);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [task?.id, task?.status]);
  const pending = task && (task.status === "queued" || task.status === "running");
  return <div className="modal" role="dialog" aria-modal="true">
    <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
    <section className="modal-panel confirm-panel export-panel">
      <header><div><code>完整汇报</code><h2>导出汇报</h2><p>仅导出已确认编排中可见的页面。</p></div><button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={16} /></button></header>
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      {loadingHistory ? <p role="status">正在恢复导出记录…</p> : null}
      {!task && !loadingHistory ? <div className="export-format-grid">
        <button className="export-format-card" type="button" disabled={starting} onClick={() => void start("html")}><FileArchive size={22} /><strong>HTML</strong><span>离线压缩包，图片、视频、GIF 保持原始文件。</span></button>
        <button className="export-format-card" type="button" disabled={starting} onClick={() => void start("pdf")}><FileText size={22} /><strong>PDF</strong><span>逐页等待渲染完成后生成静态 PDF。</span></button>
      </div> : task ? <div className="export-progress">
        <span>{task.format.toUpperCase()} · {task.pageCount} 页</span><strong>{task.status === "completed" ? "导出完成" : task.status === "failed" ? "导出失败" : task.message || "正在导出"}</strong>
        <div><i style={{ width: `${Math.max(4, Math.min(100, Number(task.progress || 0)))}%` }} /></div>
        {task.error ? <p className="error-text">{task.error}</p> : null}
        {pending ? <small>后台处理中，可继续浏览素材库。</small> : null}
        {task.status === "completed" && task.downloadUrl ? <a className="primary" href={task.downloadUrl}><Download size={15} />下载文件</a> : null}
        {!pending ? <button className="secondary" type="button" onClick={() => setTask(null)}>{task.status === "failed" ? "重新导出" : "再次导出"}</button> : null}
      </div> : null}
      {history.length ? <div className="export-history" aria-label="历史导出记录"><h3>导出记录</h3>{history.map((item) => <div key={item.id}>
        <span>{item.format.toUpperCase()} · {item.pageCount} 页 · {new Date(item.createdAt).toLocaleString("zh-CN")}</span>
        {item.status === "completed" && item.downloadUrl ? <a href={item.downloadUrl}>下载 {item.filename}</a> : <span>{item.status === "failed" ? item.error : item.message}</span>}
      </div>)}</div> : null}
    </section>
  </div>;
}
