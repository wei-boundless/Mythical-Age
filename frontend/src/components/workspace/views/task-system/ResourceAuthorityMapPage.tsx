"use client";

import { CheckCircle2, Compass, ShieldCheck, TriangleAlert } from "lucide-react";

import type { RuntimeResourceInventory } from "@/lib/api";

import { TaskOrchestrationResourcePage } from "./TaskSystemPages";
import { TaskSystemToolbarButton as ToolbarButton } from "./TaskSystemWorkbenchUi";

function layerTone(layer: string) {
  if (layer.includes("L0") || layer.includes("L1")) return "task-resource-authority-row--hard";
  if (layer.includes("L6") || layer.includes("L7")) return "task-resource-authority-row--soft";
  return "task-resource-authority-row--directory";
}

function countWritable(inventory: RuntimeResourceInventory | null) {
  return (inventory?.items ?? []).filter((item) => item.can_authorize_side_effects).length;
}

export function ResourceAuthorityMapPage({
  inventory,
  loading,
  onRefresh,
  selectedTaskGraphId,
}: {
  inventory: RuntimeResourceInventory | null;
  loading: boolean;
  onRefresh: () => void;
  selectedTaskGraphId?: string;
}) {
  const items = inventory?.items ?? [];
  return (
    <TaskOrchestrationResourcePage>
      <header className="task-management-titlebar">
        <div>
          <span>资源权威地图</span>
          <h3>运行资源分层</h3>
          <p>这里只展示资源在运行时的权威层级。目录、图、投影和 checkpoint 都可以参与上下文，但只有当前指令和执行义务能授权副作用。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={loading} onClick={onRefresh}>
            <Compass size={15} />{loading ? "刷新中" : "刷新资源地图"}
          </ToolbarButton>
        </div>
      </header>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong>权威边界</strong><span>{inventory?.inventory_id || "未载入"}</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>资源</span><strong>{items.length}</strong></div>
            <div className="boundary-readiness"><span>可授权副作用</span><strong>{countWritable(inventory)}</strong></div>
            <div className="boundary-readiness"><span>当前图</span><strong>{selectedTaskGraphId || "-"}</strong></div>
            <div className="boundary-readiness"><span>Authority</span><strong>{inventory?.authority || "-"}</strong></div>
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>执行原则</strong><span>professional mother runtime</span></header>
          <div className="task-graph-note">
            <strong>目录资源不做意图裁决</strong>
            <span>TaskDomain 和 Projection 只能提供筛选、表达和组织信息，不能取消当前回合的读写验证义务。</span>
          </div>
          <div className="task-graph-note">
            <strong>状态恢复要重新绑定当前义务</strong>
            <span>Checkpoint 只恢复证据和进度，继续运行前仍以当前用户指令重新计算 ExecutionObligation。</span>
          </div>
        </article>
      </section>
      <section className="boundary-card">
        <header><strong>资源清单</strong><span>{items.length} items</span></header>
        <div className="task-resource-authority-list">
          {items.map((item) => (
            <article className={`task-resource-authority-row ${layerTone(item.authority_layer)}`} key={item.resource_id}>
              <div className="task-resource-authority-row__icon">
                {item.can_authorize_side_effects ? <ShieldCheck size={16} /> : <CheckCircle2 size={16} />}
              </div>
              <div>
                <strong>{item.title}</strong>
                <span>{item.resource_id}</span>
                <small>{item.notes}</small>
              </div>
              <div className="task-resource-authority-row__meta">
                <span>{item.authority_layer}</span>
                <strong>{item.can_authorize_side_effects ? "授权源" : "上下文源"}</strong>
                <small>{item.runtime_consumer}</small>
              </div>
              <code>{item.path}</code>
            </article>
          ))}
          {!items.length ? (
            <div className="boundary-empty">
              <TriangleAlert size={16} />资源清单尚未载入。
            </div>
          ) : null}
        </div>
      </section>
    </TaskOrchestrationResourcePage>
  );
}
