import {
  AlertCircle,
  ChevronRight,
  Clipboard,
  Copy,
  FileText,
  Layers3,
  Loader2,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useModalBehavior } from "../modal";
import { previewSandbox } from "../previewSecurity";
import type { CaseAiInfo, CaseControlGroup } from "../types";
import { safeAbsoluteUrl } from "../urlSafety";

type CopyText = (text: string, message: string) => Promise<void>;

// Mount the (heavy) iframe only when it nears the viewport so a large case
// library / long detail page does not spin up many live iframes at once.
function LazyFrame({ src, title }: { src: string; title: string }) {
  const safeSrc = safeAbsoluteUrl(src);
  const holderRef = useRef<HTMLDivElement | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const node = holderRef.current;
    if (!node || loaded) return;
    if (typeof IntersectionObserver === "undefined") {
      setLoaded(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => { for (const entry of entries) if (entry.isIntersecting) { setLoaded(true); observer.disconnect(); } },
      { rootMargin: "600px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [loaded]);
  return (
    <div ref={holderRef} className="lazy-frame-holder">
      {loaded && !failed && safeSrc ? <iframe loading="lazy" title={title} src={safeSrc} sandbox={previewSandbox(safeSrc)} referrerPolicy="no-referrer" onError={() => setFailed(true)} /> : <div className="lazy-frame-pending" aria-hidden="true" />}
      {failed || !safeSrc ? <div className="lazy-frame-error"><AlertCircle size={16} /><span>预览不可用</span></div> : null}
    </div>
  );
}

function CaseAiInfoDialog({ info, close, copyText }: { info: CaseAiInfo; close: () => void; copyText: CopyText }) {
  useModalBehavior(close);
  const award = info.award === "案例页面" ? "" : info.award;
  const assetStructure = [
    info.pageStructure.keyAsset ? `  - 主视觉/重点素材: ${info.pageStructure.keyAsset}` : "",
    info.pageStructure.modalAssets ? `  - 可弹窗查看素材: ${info.pageStructure.modalAssets}` : ""
  ].filter(Boolean).join("\n");
  const structureParts = [
    info.pageStructure.style,
    info.pageStructure.order,
    info.pageStructure.keyAsset ? `主素材：${info.pageStructure.keyAsset}` : "",
    info.pageStructure.modalAssets ? `弹窗：${info.pageStructure.modalAssets}` : ""
  ].filter(Boolean);
  const raw = `案例名称: ${info.caseName}
${award ? `奖项: ${award}\n` : ""}适合标题: ${info.pageTitle}
业务背景:
  - 内容: ${info.background.content}
  - 附件材料: ${info.background.attachments.join("；")}
核心痛点:
  - 内容: ${info.pain.content}
  - 附件材料: ${info.pain.attachments.join("；")}
解决方案:
  - 内容: ${info.solution.content}
  - 附件材料: ${info.solution.attachments.join("；")}
关键成果:
  - 内容: ${info.result.content}
  - 附件材料: ${info.result.attachments.join("；")}
材料主线: ${info.storyline}
一页材料结构:
  - 视觉风格: ${info.pageStructure.style}
  - 模块顺序: ${info.pageStructure.order}${assetStructure ? `\n${assetStructure}` : ""}
原始链接: ${info.sourceUrl}`;
  const sections = [
    ["业务背景", info.background],
    ["核心痛点", info.pain],
    ["解决方案", info.solution],
    ["关键成果", info.result]
  ] as const;

  return (
    <div className="modal case-ai-modal" role="dialog" aria-modal="true">
      <button className="modal-mask" type="button" onClick={close} aria-label="关闭" />
      <section className="case-ai-panel">
        <header>
          <div>
            {award ? <span>{award}</span> : null}
            <h2>{info.caseName}</h2>
            <p>{info.pageTitle}</p>
          </div>
          <div className="case-ai-actions">
            <button className="secondary" type="button" onClick={() => void copyText(raw, "已复制 AI 生成信息")}><Copy size={14} />复制信息</button>
            <button className="icon-btn" type="button" onClick={close} aria-label="关闭"><X size={15} /></button>
          </div>
        </header>
        <div className="case-ai-grid">
          {sections.map(([title, section]) => (
            <article key={title}>
              <strong>{title}</strong>
              <p>{section.content}</p>
              {section.attachments.length > 0 ? <small>{section.attachments.join(" / ")}</small> : null}
            </article>
          ))}
        </div>
        <footer>
          <div><b>材料主线</b><span>{info.storyline}</span></div>
          <div><b>一页材料结构</b><span>{structureParts.join(" · ")}</span></div>
        </footer>
      </section>
    </div>
  );
}

export function CaseControlLibrary({ copyText, reloadToken = 0 }: { copyText: CopyText; reloadToken?: number }) {
  const [groups, setGroups] = useState<CaseControlGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [aiInfo, setAiInfo] = useState<CaseAiInfo | null>(null);
  const [selectedGroupCode, setSelectedGroupCode] = useState<string | null>(null);
  const [failedPreviewIds, setFailedPreviewIds] = useState<Set<string>>(() => new Set());
  const [pendingDelete, setPendingDelete] = useState<{ id: string; code: string; title: string; kind: "group" | "page" } | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void api.caseGroups().then((response) => {
      if (cancelled) return;
      if (response.ok === false) {
        setError(response.error || "案例素材加载失败");
        setGroups([]);
      } else {
        setGroups(response.caseGroups || []);
      }
      setLoading(false);
    }).catch(() => {
      if (cancelled) return;
      setError("案例素材加载失败");
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [reloadToken]);

  const confirmDelete = async () => {
    if (!pendingDelete || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      if (pendingDelete.kind === "group") {
        const data = await api.deleteCaseGroup(pendingDelete.code);
        if (data.ok === false) {
          const references = data.referenceCodes?.length ? `（引用汇报：${data.referenceCodes.join("、")}）` : "";
          setDeleteError(`${data.error || "删除失败"}${references}`);
          return;
        }
        setPendingDelete(null);
        setGroups((current) => current.filter((item) => item.code !== pendingDelete.code));
        setSelectedGroupCode(null);
      } else {
        const data = await api.deleteAsset(pendingDelete.id);
        if (data.ok === false) {
          setDeleteError(data.error || "删除失败");
          return;
        }
        setPendingDelete(null);
        setGroups((current) => current.flatMap((item) => {
          if (item.code !== selectedGroupCode) return item;
          const controls = item.controls.filter((control) => control.code !== pendingDelete.code);
          return controls.length > 0
            ? [{ ...item, controls, controlCount: controls.length, caseCount: controls.length }]
            : [];
        }));
        if (group?.controls.length === 1) setSelectedGroupCode(null);
      }
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败，请稍后重试");
    } finally {
      setDeleteBusy(false);
    }
  };

  const selectedGroup = groups.find((item) => item.code === selectedGroupCode) || null;
  const group = selectedGroup || groups[0] || null;

  if (loading) {
    return <section className="empty-state"><Loader2 className="spin" size={20} /><strong>正在读取案例素材</strong></section>;
  }
  if (error || !group) {
    return <section className="empty-state"><AlertCircle size={20} /><strong>{error || "暂无已入库的案例素材"}</strong><span>案例组只有在关联页面素材可访问后才会显示。</span></section>;
  }

  return (
    <>
      <section className={`case-manager-view${selectedGroup ? " is-detail" : ""}`}>
        {selectedGroup ? (
          <header className="case-manager-toolbar compact">
            <div>
              <strong>案例组详情</strong>
              <span>页面均来自素材库真实记录，案例清单不再由前端硬编码维护。</span>
            </div>
            <div className="case-manager-actions">
              <button className="secondary" type="button" onClick={() => setSelectedGroupCode(null)}><ChevronRight size={15} />返回列表</button>
            </div>
          </header>
        ) : null}
        {!selectedGroup ? (
          <section className="case-card-grid" aria-label="案例素材列表">
            {groups.map((caseGroup) => (
              <article className="case-list-card" key={caseGroup.code}>
                <button className="case-list-hit" type="button" onClick={() => setSelectedGroupCode(caseGroup.code)}>
                  <div className="case-list-preview" aria-hidden="true">
                    {caseGroup.controls[0]?.thumbnailUrl
                      ? <img loading="lazy" alt="" src={caseGroup.controls[0].thumbnailUrl} />
                      : <LazyFrame title={`${caseGroup.title}预览`} src={caseGroup.reportUrl} />}
                  </div>
                  <div className="case-list-main">
                    <div className="case-list-badges">
                      <span>{caseGroup.brand || "案例素材"}</span>
                      <span>优秀案例</span>
                      <span>{caseGroup.controlCount} 个页面素材</span>
                    </div>
                    <h2>{caseGroup.title}</h2>
                    <div className="case-group-metrics">
                      <div><strong>{caseGroup.caseCount}</strong><span>案例</span></div>
                      <div><strong>{caseGroup.controlCount}</strong><span>页面素材</span></div>
                      <div><strong>{caseGroup.attachmentCount}</strong><span>资源素材</span></div>
                    </div>
                  </div>
                  <div className="case-list-side">
                    <ChevronRight size={22} />
                  </div>
                </button>
                <footer>
                  <code>{caseGroup.code}</code>
                  <button className="icon-btn" title="复制案例编号" aria-label="复制案例编号" type="button" onClick={() => void copyText(caseGroup.code, "已复制案例素材编号")}><Clipboard size={14} /></button>
                  {safeAbsoluteUrl(caseGroup.sourceDoc) ? <button className="icon-btn" title="复制原始文档链接" aria-label="复制原始文档链接" type="button" onClick={() => void copyText(safeAbsoluteUrl(caseGroup.sourceDoc), "已复制飞书文档链接")}><Copy size={14} /></button> : null}
                  <button className="case-delete-btn" title="删除案例组" aria-label="删除案例组" type="button" onClick={() => setPendingDelete({ id: caseGroup.code, code: caseGroup.code, title: caseGroup.title, kind: "group" })}><Trash2 size={14} />删除</button>
                </footer>
              </article>
            ))}
          </section>
        ) : (
          <>
            <section className="case-group-card">
              <div className="case-group-main">
                <span className="case-code">{group.code}</span>
                <h2>{group.title}</h2>
                <p>只展示已完成入库且页面链接可访问的案例页面；附件数量来自已入库资源和案例清单。</p>
                <div className="case-group-metrics">
                  <div><strong>{group.caseCount}</strong><span>案例</span></div>
                  <div><strong>{group.controlCount}</strong><span>页面素材</span></div>
                  <div><strong>{group.attachmentCount}</strong><span>附件素材</span></div>
                  <div><strong>{group.updatedAt}</strong><span>更新时间</span></div>
                </div>
              </div>
              <div className="case-group-side">
                {safeAbsoluteUrl(group.sourceDoc) ? <button className="secondary" type="button" onClick={() => void copyText(safeAbsoluteUrl(group.sourceDoc), "已复制飞书文档链接")}><Copy size={15} />复制文档链接</button> : null}
                {safeAbsoluteUrl(group.reportUrl) ? <a className="secondary" href={safeAbsoluteUrl(group.reportUrl)} target="_blank" rel="noreferrer"><FileText size={15} />多页预览</a> : null}
                <button className="danger" type="button" onClick={() => setPendingDelete({ id: group.code, code: group.code, title: group.title, kind: "group" })}><Trash2 size={15} />删除案例组</button>
              </div>
            </section>
            <section className="case-detail-layout" aria-label="案例详情">
              <aside className="case-detail-nav">
                <strong>案例目录</strong>
                {group.controls.map((item, index) => (
                  <a key={item.id} href={`#${item.id}`}>
                    <b>{String(index + 1).padStart(2, "0")} {(item.ai?.caseName || item.title).split("：")[0]}</b>
                    <span>{item.scenario}</span>
                  </a>
                ))}
              </aside>
              <div className="case-detail-stack">
                {group.controls.map((item) => {
                  const attachments = item.ai
                    ? item.ai.background.attachments.concat(item.ai.pain.attachments, item.ai.solution.attachments, item.ai.result.attachments).slice(0, 5)
                    : [];
                  return (
                    <article className="case-detail-card" id={item.id} key={item.id}>
                      <header>
                        <div>
                          <div className="case-list-badges">{item.award && item.award !== "案例页面" ? <span>{item.award}</span> : null}<span>{item.scenario}</span><span>{item.code}</span></div>
                          <h3>{item.title}</h3>
                        </div>
                        <code>{item.id}</code>
                      </header>
                      <div className="case-detail-body">
                        <div className="case-detail-preview">
                          {!failedPreviewIds.has(item.id) && safeAbsoluteUrl(item.controlUrl)
                            ? <iframe loading="lazy" title={`${item.title} 页面素材预览`} src={safeAbsoluteUrl(item.controlUrl)} sandbox={previewSandbox(item.controlUrl)} referrerPolicy="no-referrer" onError={() => setFailedPreviewIds((current) => new Set(current).add(item.id))} />
                            : <div className="case-preview-error"><AlertCircle size={18} /><strong>页面预览不可用</strong><span>可尝试打开页面素材链接查看详情。</span></div>}
                        </div>
                        <div className="case-detail-info">
                          <section><strong>案例总结</strong><p>{item.summary}</p></section>
                          {attachments.length > 0 ? <section><strong>页面素材组成</strong><p>{attachments.join(" / ")}</p></section> : null}
                          <div className="case-row-actions">
                            {safeAbsoluteUrl(item.sourceUrl) ? <button type="button" onClick={() => void copyText(safeAbsoluteUrl(item.sourceUrl), "已复制原始飞书链接")}><Copy size={14} />原始链接</button> : null}
                            {safeAbsoluteUrl(item.controlUrl) ? <a href={safeAbsoluteUrl(item.controlUrl)} target="_blank" rel="noreferrer"><Layers3 size={14} />页面素材</a> : null}
                            {safeAbsoluteUrl(item.reportPageUrl) ? <a href={safeAbsoluteUrl(item.reportPageUrl)} target="_blank" rel="noreferrer"><FileText size={14} />预览页</a> : null}
                            {item.ai ? <button type="button" onClick={() => setAiInfo(item.ai || null)}><Sparkles size={14} />AI 信息</button> : null}
                            <button className="danger-item" type="button" onClick={() => setPendingDelete({ id: item.id, code: item.code, title: item.title, kind: "page" })}><Trash2 size={14} />删除页面</button>
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          </>
        )}
      </section>
      {aiInfo ? <CaseAiInfoDialog info={aiInfo} close={() => setAiInfo(null)} copyText={copyText} /> : null}
      {pendingDelete ? (
        <div className="modal" role="dialog" aria-modal="true">
          <button className="modal-mask" type="button" onClick={() => { if (!deleteBusy) { setPendingDelete(null); setDeleteError(""); } }} aria-label="取消" />
          <section className="modal-panel confirm-panel">
            <h2>删除{pendingDelete.kind === "group" ? "案例组" : "页面素材"}？</h2>
            <p><code>{pendingDelete.code}</code> · {pendingDelete.title}</p>
            {pendingDelete.kind === "page"
              ? <p>仍被汇报引用的页面会被保护，请先在对应汇报中移出。</p>
              : <p>将删除案例组及组内全部页面素材和历史版本。原始文档及资源素材保留；任一页面仍被汇报引用时，本次删除不会执行。</p>}
            {deleteError ? <p className="error-text">{deleteError}</p> : null}
            <footer>
              <button className="secondary" type="button" disabled={deleteBusy} onClick={() => { setPendingDelete(null); setDeleteError(""); }}>取消</button>
              <button className="danger" type="button" disabled={deleteBusy} onClick={() => void confirmDelete()}>
                {deleteBusy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
                {deleteBusy ? "正在删除" : "确认删除"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
