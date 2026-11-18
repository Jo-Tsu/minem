import { FileText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { Asset } from "../types";
import { api } from "../api";

export function ReportDialog({ controls, close, createReport }: {
  controls: Asset[];
  close: () => void;
  createReport: (payload: { title: string; note: string; pageIds: string[]; coverTemplateId: string }) => Promise<void>;
}) {
  const [title, setTitle] = useState("新建汇报素材");
  const [note, setNote] = useState("");
  const [coverTemplateId, setCoverTemplateId] = useState("cover-1");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [available, setAvailable] = useState(controls);
  const [selected, setSelected] = useState(controls[0] ? [controls[0]] : []);
  const pageIds = selected.map((asset) => asset.id);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(controls.length >= 200);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const submitting = useRef(false);
  const load = async (number: number, reset = false) => {
    const request = ++sequence.current;
    setLoading(true);
    setError("");
    const data = await api.assets({ view: "list", type: "control", q: query || undefined, page: number, page_size: 200 });
    if (request !== sequence.current) return;
    setLoading(false);
    if (data.ok === false) { setError(data.error || "页面素材读取失败，请重试"); return; }
    setAvailable((current) => reset ? data.assets : [...current, ...data.assets.filter((asset) => !current.some((item) => item.id === asset.id))]);
    setPage(number);
    setHasNext(Boolean(data.pagination?.hasNext));
  };
  useEffect(() => {
    if (!query && page === 1 && available === controls) return () => { sequence.current++; };
    const timer = setTimeout(() => void load(1, true), 200);
    return () => { clearTimeout(timer); sequence.current++; };
  }, [query]);
  const toggle = (asset: Asset) => {
    setSelected((current) => current.some((item) => item.id === asset.id) ? current.filter((item) => item.id !== asset.id) : [...current, asset]);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current || !pageIds.length) return;
    submitting.current = true;
    setBusy(true);
    try {
      await createReport({ title: title.trim(), note: note.trim(), pageIds, coverTemplateId });
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  return (
    <div className="modal import-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <form className="import-panel report-create-panel" onSubmit={submit}>
        <header><div><span>REPORT</span><h2>新增汇报素材</h2><p>选择页面素材，生成独立汇报。</p></div><button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button></header>
        <label className="import-field"><span>汇报标题</span><input required value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <fieldset className="report-cover-picker" disabled={busy}><legend>封面模板</legend><div className="report-cover-options">
          {[1, 2, 3].map((number) => <label className="report-cover-option" key={number}>
            <img src={`/report-covers/cover-${number}.webp`} width={1920} height={1080} alt="" />
            <span><input type="radio" name="coverTemplateId" value={`cover-${number}`} checked={coverTemplateId === `cover-${number}`} onChange={(event) => setCoverTemplateId(event.target.value)} />封面 {number}</span>
          </label>)}
        </div></fieldset>
        <label className="import-field"><span>搜索页面素材</span><input value={query} disabled={busy} onChange={(event) => setQuery(event.target.value)} placeholder="按名称或编号搜索整个页面库" /></label>
        <div className="page-picker-grid report-page-picker" aria-label="选择页面素材">
          {available.map((asset) => <button key={asset.id} type="button" role="checkbox" aria-checked={pageIds.includes(asset.id)} aria-label={`${asset.title} · ${asset.asset_code}`} className={`page-picker-card${pageIds.includes(asset.id) ? " is-selected" : ""}`} disabled={busy} onClick={() => toggle(asset)}>
            {asset.thumbnail_url ? <img src={asset.thumbnail_url} alt="" loading="lazy" /> : <FileText size={24} />}
            <span>{asset.title}</span><small>{asset.asset_code}{pageIds.includes(asset.id) ? ` · 已选 #${pageIds.indexOf(asset.id) + 1}` : ""}</small>
          </button>)}
        </div>
        {loading ? <p role="status">正在读取页面素材…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {!loading && !available.length ? <p>{query ? "没有匹配的页面素材" : "请先导入页面素材"}</p> : null}
        {hasNext ? <button className="secondary" type="button" disabled={busy || loading} onClick={() => void load(page + 1)}>加载更多页面</button> : null}
        <div className="report-selected-pages"><span>已选择 {pageIds.length} 页，按选择顺序编排</span>{selected.map((asset, index) => <button key={asset.id} type="button" disabled={busy} onClick={() => toggle(asset)} title="取消选择">{index + 1}. {asset.title}<X size={12} /></button>)}</div>
        <label className="import-field"><span>备注</span><input value={note} onChange={(event) => setNote(event.target.value)} /></label>
        <footer><button className="primary" type="submit" disabled={busy || !pageIds.length}>{busy ? "正在创建" : "创建汇报素材"}</button><button className="secondary" type="button" onClick={close}>取消</button></footer>
      </form>
    </div>
  );
}
