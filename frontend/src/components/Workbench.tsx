import { Box, FileText, Layers3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Asset, AssetType, PipelineSummary, StatsResponse, ViewKey } from "../types";

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
  setAssetType: (type: AssetType) => void;
  setView: (view: ViewKey) => void;
  openAsset: (id: string) => Promise<void>;
};

function MiniList({ title, code, items = [], openAsset }: {
  title: string;
  code: string;
  items?: Asset[];
  openAsset?: (id: string) => Promise<void>;
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
        {!items.length ? <p>暂无数据</p> : null}
      </div>
    </section>
  );
}

export function Workbench({ stats, pipeline, workbench, setAssetType, setView, openAsset }: WorkbenchProps) {
  const cards: WorkbenchCard[] = [
    { key: "report", label: "汇报", value: stats?.types.report || 0, icon: FileText },
    { key: "control", label: "页面", value: stats?.types.control || 0, icon: Layers3 }
  ];
  const latestBatch = pipeline?.latestBatches?.[0];
  return (
    <div className="workbench-view">
      <section className="workbench-overview">
        <div className="workbench-intro">
          <span>素材总览</span>
          <strong>{(stats?.types.report || 0) + (stats?.types.control || 0)}</strong>
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
      </section>
    </div>
  );
}
