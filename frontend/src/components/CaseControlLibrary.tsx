import {
  AlertCircle,
  ChevronRight,
  Clipboard,
  Copy,
  FileText,
  Layers3,
  Loader2,
  Sparkles,
  X
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { CaseAiInfo, CaseControlGroup } from "../types";

type CopyText = (text: string, message: string) => Promise<void>;

function CaseAiInfoDialog({ info, close, copyText }: { info: CaseAiInfo; close: () => void; copyText: CopyText }) {
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
奖项: ${info.award}
适合标题: ${info.pageTitle}
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
            <span>{info.award}</span>
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

export function CaseControlLibrary({ copyText }: { copyText: CopyText }) {
  const [groups, setGroups] = useState<CaseControlGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [aiInfo, setAiInfo] = useState<CaseAiInfo | null>(null);
  const [selectedGroupCode, setSelectedGroupCode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
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
  }, []);

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
                      : <iframe loading="lazy" title={`${caseGroup.title}预览`} src={caseGroup.reportUrl} />}
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
                  {caseGroup.sourceDoc ? <button className="icon-btn" title="复制原始文档链接" aria-label="复制原始文档链接" type="button" onClick={() => void copyText(caseGroup.sourceDoc, "已复制飞书文档链接")}><Copy size={14} /></button> : null}
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
                {group.sourceDoc ? <button className="secondary" type="button" onClick={() => void copyText(group.sourceDoc, "已复制飞书文档链接")}><Copy size={15} />复制文档链接</button> : null}
                <a className="secondary" href={group.reportUrl} target="_blank" rel="noreferrer"><FileText size={15} />多页预览</a>
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
                          <div className="case-list-badges"><span>{item.award}</span><span>{item.scenario}</span><span>{item.code}</span></div>
                          <h3>{item.title}</h3>
                        </div>
                        <code>{item.id}</code>
                      </header>
                      <div className="case-detail-body">
                        <div className="case-detail-preview">
                          <iframe loading="lazy" title={`${item.title} 页面素材预览`} src={item.controlUrl} />
                        </div>
                        <div className="case-detail-info">
                          <section><strong>案例总结</strong><p>{item.summary}</p></section>
                          {attachments.length > 0 ? <section><strong>页面素材组成</strong><p>{attachments.join(" / ")}</p></section> : null}
                          <div className="case-row-actions">
                            {item.sourceUrl ? <button type="button" onClick={() => void copyText(item.sourceUrl, "已复制原始飞书链接")}><Copy size={14} />原始链接</button> : null}
                            <a href={item.controlUrl} target="_blank" rel="noreferrer"><Layers3 size={14} />页面素材</a>
                            <a href={item.reportPageUrl} target="_blank" rel="noreferrer"><FileText size={14} />预览页</a>
                            {item.ai ? <button type="button" onClick={() => setAiInfo(item.ai || null)}><Sparkles size={14} />AI 信息</button> : null}
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
    </>
  );
}
