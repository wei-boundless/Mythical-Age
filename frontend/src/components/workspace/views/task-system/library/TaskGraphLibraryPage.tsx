"use client";

import { AlertTriangle, Network, Save } from "lucide-react";

import type { TaskGraphRecord } from "@/lib/api";

import type { TaskGraphDraftV2 } from "../taskGraphDraftV2";
import {
  isRecommendedTaskGraph,
  sortTaskGraphsForWorkbench,
  taskGraphFeatureBadges,
} from "../taskGraphSelection";
import { TaskGraphManagementPage } from "../TaskSystemPages";
import { TaskSystemToolbarButton as ToolbarButton } from "../TaskSystemWorkbenchUi";

type TaskGraphLibraryDomain = {
  domain_id?: string;
  title?: string;
};

function readinessCard({ label, ready, value }: { label: string; ready: boolean; value: string }) {
  return (
    <div className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function TaskGraphLibraryPage({
  activeGraphEdges,
  activeGraphNodes,
  editorIssueCount,
  editorPublished,
  editorValid,
  onCreateGraph,
  onDuplicateGraph,
  onOpenWorkbench,
  onSaveGraph,
  onSelectGraph,
  saving,
  selectedDomain,
  selectedTaskGraph,
  selectedTaskGraphId,
  standardViewError,
  taskGraphDraft,
  taskGraphs,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  editorIssueCount: number;
  editorPublished: boolean;
  editorValid: boolean;
  onCreateGraph: () => void;
  onDuplicateGraph: () => void;
  onOpenWorkbench: (graphId?: string) => void;
  onSaveGraph: () => void;
  onSelectGraph: (graphId: string) => void;
  saving: string;
  selectedDomain: TaskGraphLibraryDomain | null;
  selectedTaskGraph: TaskGraphRecord | null;
  selectedTaskGraphId: string;
  standardViewError?: string;
  taskGraphDraft: TaskGraphDraftV2;
  taskGraphs: TaskGraphRecord[];
}) {
  const orderedTaskGraphs = sortTaskGraphsForWorkbench(taskGraphs);

  return (
    <TaskGraphManagementPage>
      <aside className="task-management-directory">
        <div className="task-management-directory__head">
          <span>{selectedDomain?.title || "任务域"}</span>
          <strong>任务图库</strong>
          <ToolbarButton disabled={saving === "task-graph-create" || !selectedDomain} onClick={onCreateGraph}>
            <Network size={15} />新图草稿
          </ToolbarButton>
        </div>
        <div className="boundary-list">
          {orderedTaskGraphs.map((graph) => {
            const badges = taskGraphFeatureBadges(graph);
            const recommended = isRecommendedTaskGraph(graph, orderedTaskGraphs);
            return (
            <button
              className={graph.graph_id === selectedTaskGraphId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"}
              key={graph.graph_id}
              onClick={() => onSelectGraph(graph.graph_id)}
              type="button"
            >
              <strong>{graph.title}</strong>
              <span>{graph.publish_state || "draft"} / {(graph.node_count ?? graph.nodes?.length ?? 0)} 节点 / {(graph.edge_count ?? graph.edges?.length ?? 0)} 边</span>
              {badges.length ? (
                <small className="task-graph-library-badges">
                  {recommended ? <em>默认入口</em> : null}
                  {badges.slice(0, 4).map((badge) => <em key={badge}>{badge}</em>)}
                </small>
              ) : null}
            </button>
            );
          })}
          {!taskGraphs.length ? <div className="boundary-empty">当前任务域暂无任务图草稿。</div> : null}
        </div>
      </aside>

      <main className="task-management-workbench">
        <header className="task-management-titlebar">
          <div>
            <span>任务图库</span>
            <h3>{selectedTaskGraph?.title || "未选择任务图"}</h3>
            <p>这里只管理任务域下的一等任务图资产。节点、边、资源流、契约绑定和发布运行统一进入图工作台。</p>
          </div>
          <div className="boundary-actions">
            <ToolbarButton disabled={!selectedTaskGraph} onClick={() => onOpenWorkbench(selectedTaskGraph?.graph_id)}>进入图工作台</ToolbarButton>
            <ToolbarButton disabled={saving === "task-graph-duplicate" || !selectedTaskGraph} onClick={onDuplicateGraph}>复制图</ToolbarButton>
            <ToolbarButton disabled={saving === "task-graph" || !selectedTaskGraph} onClick={onSaveGraph} variant="primary">
              <Save size={15} />保存图
            </ToolbarButton>
          </div>
        </header>

        {selectedTaskGraph ? (
          <section className="boundary-layer-stack">
            <div className="task-management-status-row">
              {readinessCard({ label: "节点", value: `${activeGraphNodes.length}`, ready: Boolean(activeGraphNodes.length) })}
              {readinessCard({ label: "边", value: `${activeGraphEdges.length}`, ready: Boolean(activeGraphEdges.length) })}
              {readinessCard({ label: "预检", value: editorValid ? "通过" : `${editorIssueCount} 个问题`, ready: editorValid })}
              {readinessCard({ label: "发布状态", value: String(taskGraphDraft.publish_state || selectedTaskGraph.publish_state || "draft"), ready: editorPublished })}
            </div>
            <section className="task-system-task-cover">
              <article className="boundary-card">
                <header><strong>图目录信息</strong><span>{selectedTaskGraph.graph_id}</span></header>
                <div className="boundary-kv">
                  <p><span>任务域</span><strong>{selectedDomain?.title || selectedTaskGraph.domain_id || "-"}</strong></p>
                  <p><span>图类型</span><strong>{String(selectedTaskGraph.graph_kind || "coordination")}</strong></p>
                  <p><span>入口节点</span><strong>{String(selectedTaskGraph.entry_node_id || taskGraphDraft.entry_node_id || "未设置")}</strong></p>
                  <p><span>出口节点</span><strong>{String(selectedTaskGraph.output_node_id || taskGraphDraft.output_node_id || "未设置")}</strong></p>
                  <p><span>默认协议</span><strong>{String(selectedTaskGraph.default_protocol_id || taskGraphDraft.default_protocol_id || "未设置")}</strong></p>
                  <p><span>启用状态</span><strong>{selectedTaskGraph.enabled ? "启用" : "草稿"}</strong></p>
                </div>
              </article>
              <article className="boundary-card">
                <header><strong>工作台职责</strong><span>深编辑入口</span></header>
                <div className="boundary-kv">
                  <p><span>节点配置</span><strong>图工作台 / 对象编辑台</strong></p>
                  <p><span>边交接</span><strong>图工作台 / 交接边</strong></p>
                  <p><span>契约绑定</span><strong>图工作台 / contract_bindings</strong></p>
                  <p><span>时序分层</span><strong>图工作台 / 拓扑时序</strong></p>
                  <p><span>资源流</span><strong>图工作台 / 资源流</strong></p>
                  <p><span>发布运行</span><strong>图工作台 / 执行包</strong></p>
                </div>
                <div className="boundary-actions">
                  <ToolbarButton onClick={() => onOpenWorkbench(selectedTaskGraph.graph_id)}>打开图工作台</ToolbarButton>
                </div>
              </article>
            </section>
            {standardViewError ? (
              <div className="boundary-notice boundary-notice--error">
                <AlertTriangle size={16} />
                图标准视图加载失败：{standardViewError}
              </div>
            ) : null}
          </section>
        ) : <div className="boundary-empty">请先创建或选择一张任务图。</div>}
      </main>
    </TaskGraphManagementPage>
  );
}
