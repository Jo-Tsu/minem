import { Box, FileText, Layers3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Asset, AssetType, PipelineSummary, StatsResponse, Storyline, ViewKey } from "../types";

type WorkbenchCard = {
  key: AssetType;
  label: string;
  value: number | string;
  icon: LucideIcon;
};

type WorkbenchProps = {
  stats: StatsResponse | null;
  pipeline: PipelineSummary | null;
  workbench: { reports: Asset[]; controls: Asset[]; resources: Asset[] };
  storylines: Storyline[];
  setAssetType: (type: AssetType) => void;
  setView: (view: ViewKey) => void;
  openAsset: (id: string) => Promise<void>;
  openStoryline: (storyline: Storyline) => void;
};

function MiniList({ title, code, items = [], storylines = [], openAsset, openStoryline }: {
  title: string;
  code: string;
  items?: Asset[];
  storylines?: Storyline[];
  openAsset?: (id: string) => Promise<void>;
  openStoryline?: (storyline: Storyline) => void;
}) {
  return (
    <section className="workbench-panel">
      <header><span>{code}</span><strong>{title}</strong></header>
      <div className="mini-list">
        {items.map((asset) => (
          <button key={asset.id} type="button" onClick={() => openAsset?.(asset.id)}>
            <code>{asset.asset_code}</code>
            <span>{asset.title}</span>
          </button>
        ))}
        {storylines.slice(0, 6).map((item) => (
          <button key={item.id} type="button" onClick={() => openStoryline?.(item)}>
            <code>{item.code}</code>
            <span>{item.title}</span>
          </button>
        ))}
        {!items.length && !storylines.length ? <p>暂无数据</p> : null}
      </div>
    </section>
  );
}

export function Workbench({ stats, pipeline, workbench, storylines, setAssetType, setView, openAsset, openStoryline }: WorkbenchProps) {
  const cards: WorkbenchCard[] = [
    { key: "report", label: "汇报", value: stats?.types.report || 0, icon: FileText },
    { key: "control", label: "页面", value: stats?.types.control || 0, icon: Layers3 },
    { key: "resource", label: "资源", value: stats?.types.resource || 0, icon: Box }
  ];
  const latestBatch = pipeline?.latestBatches?.[0];
  return (
    <div className="workbench-view">
      <section className="workbench-overview">
        <div className="workbench-intro">
          <span>素材总览</span>
          <strong>{stats?.assetCount || 0}</strong>
          <small>{latestBatch ? `最近批次 ${latestBatch.filename || latestBatch.id}` : "暂无导入批次"}</small>
        </div>
        <div className="workbench-kpis">
          {cards.map((card) => {
            const Icon = card.icon;
            return (
              <button key={card.key} type="button" onClick={() => {
                setAssetType(card.key);
                setView("materials");
              }}>
                <span className="icon-badge"><Icon size={16} /></span>
                <strong>{card.value}</strong>
                <small>{card.label}</small>
              </button>
            );
          })}
        </div>
      </section>
      <section className="panel-grid">
        <MiniList title="最近汇报" code="RPT" items={workbench.reports} openAsset={openAsset} />
        <MiniList title="最近页面" code="PAGE" items={workbench.controls} openAsset={openAsset} />
        <MiniList title="故事线" code="STL" storylines={storylines} openStoryline={openStoryline} />
      </section>
    </div>
  );
}
