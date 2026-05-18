"use client";

import { useMemo } from "react";

import { EdgeHandoffCard } from "./EdgeHandoffCard";
import { NodeResponsibilityCard } from "./NodeResponsibilityCard";
import { TaskGraphNodeStandardPage } from "./TaskGraphNodeStandardPage";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { buildTaskGraphCognitionModel, type TaskGraphCognitionPackage } from "./taskGraphCognitionView";
import type { TaskGraphStandardView } from "@/lib/api";

function CognitionPackagePanel({
  nodePackage,
}: {
  nodePackage: TaskGraphCognitionPackage | null;
}) {
  if (!nodePackage) {
    return (
      <article className="boundary-card">
        <header><strong>节点执行认知包</strong></header>
        <div className="task-graph-note">
          <strong>未选择节点</strong>
          <span>认知包会把节点身份、运行时位置、输入包、输出契约和下游交接合成一个模型可理解的执行视图。</span>
        </div>
      </article>
    );
  }

  return (
    <article className="boundary-card task-graph-cognition-panel">
      <header>
        <div className="boundary-identity-stack">
          <span>节点执行认知包</span>
          <strong>{nodePackage.title}</strong>
        </div>
        <small>{nodePackage.nodeId}</small>
      </header>

      <div className="task-graph-mini-kv">
        <p><span>Agent</span><strong>{nodePackage.agentId || "未绑定"}</strong></p>
        <p><span>Projection</span><strong>{nodePackage.projectionId || "未绑定"}</strong></p>
        <p><span>Clock Scope</span><strong>{nodePackage.timelineScope}</strong></p>
        <p><span>输入包</span><strong>{nodePackage.inputPackets.length}</strong></p>
        <p><span>输出/交接</span><strong>{nodePackage.outputs.length}</strong></p>
        <p><span>风险</span><strong>{nodePackage.issues.length}</strong></p>
      </div>

      <section className="task-graph-cognition-section">
        <header><strong>输入包</strong><span>Packet 与 Prompt 使用方式必须配套</span></header>
        <div className="task-graph-cognition-list">
          {nodePackage.inputPackets.map((packet) => (
            <article className={packet.issues.length ? "task-graph-cognition-item task-graph-cognition-item--warn" : "task-graph-cognition-item"} key={packet.packetId}>
              <div>
                <strong>{packet.modelVisibleLabel || packet.title}</strong>
                <span>{packet.kind}{packet.edgeId ? ` · ${packet.edgeId}` : ""}</span>
              </div>
              <p>{packet.usageInstruction || "缺少使用说明：节点不知道这份输入应该如何约束本轮任务。"}</p>
              <em>{packet.required ? "required" : "optional"}</em>
            </article>
          ))}
        </div>
      </section>

      <section className="task-graph-cognition-section">
        <header><strong>输出与生效</strong><span>下游只应接收契约化输出、引用、提交确认或交接包</span></header>
        <div className="task-graph-cognition-list">
          {nodePackage.outputs.length ? nodePackage.outputs.map((output) => (
            <article className="task-graph-cognition-item" key={output.outputId}>
              <div>
                <strong>{output.title}</strong>
                <span>{output.kind} · {output.targetId}</span>
              </div>
              <p>{output.contractId ? `契约 ${output.contractId}` : "未绑定契约"}</p>
              <em>{output.visibility}</em>
            </article>
          )) : (
            <div className="task-graph-note task-graph-note--danger">
              <strong>没有明确输出</strong>
              <span>节点需要至少有产物、下游交接、记忆候选或提交确认中的一种。</span>
            </div>
          )}
        </div>
      </section>

      <section className="task-graph-cognition-section">
        <header><strong>Prompt 预览</strong><span>面向 Agent 的任务语言，不暴露开发实现细节</span></header>
        <pre className="task-graph-prompt-preview">{nodePackage.promptPreview}</pre>
      </section>
    </article>
  );
}

export function TaskGraphResponsibilityPage({
  activeGraphEdges,
  activeGraphNodes,
  onCreateProjectionFromPrompt,
  projectionCards,
  selectedGraphNode,
  selectedGraphNodeId,
  selectedGraphEdge,
  selectedGraphEdgeId,
  standardView,
  editorFocus,
  onEditorFocus,
  updateTaskGraphNode,
  updateTaskGraphEdge,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  onCreateProjectionFromPrompt?: (input: { node: Record<string, unknown>; nodeId: string; prompt: string }) => Promise<string>;
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphNodeId: string;
  selectedGraphEdge: Record<string, unknown> | null;
  selectedGraphEdgeId: string;
  standardView: TaskGraphStandardView | null;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  const cognitionModel = useMemo(
    () => buildTaskGraphCognitionModel({ nodes: activeGraphNodes, edges: activeGraphEdges }),
    [activeGraphNodes, activeGraphEdges],
  );
  const nodePackage = selectedGraphNodeId ? cognitionModel.packageByNodeId.get(selectedGraphNodeId) ?? null : null;
  const packagesByPhase = useMemo(
    () => Array.from(
      cognitionModel.packages.reduce((groups, item) => {
        const phase = item.phaseId || "phase.unassigned";
        groups.set(phase, [...(groups.get(phase) ?? []), item]);
        return groups;
      }, new Map<string, TaskGraphCognitionPackage[]>()),
    ),
    [cognitionModel.packages],
  );

  if (editorFocus?.facet === "node_standard") {
    return (
      <section className="task-graph-studio-page">
        <header className="task-graph-studio-page__head">
          <span>TaskGraph Studio</span>
          <strong>节点标准对象</strong>
          <small>节点页负责身份、执行者、运行与产物目标；认知包仍然作为节点最终收到什么的语义预览。</small>
        </header>
        <TaskGraphNodeStandardPage
          activeGraphNodes={activeGraphNodes}
          editorFocus={editorFocus}
          onEditorFocus={onEditorFocus}
          selectedGraphNode={selectedGraphNode}
          selectedGraphNodeId={selectedGraphNodeId}
          standardView={standardView}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      </section>
    );
  }

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>节点执行认知包</strong>
        <small>把节点身份、时序位置、输入包、输出契约和交接关系合成 Agent 能理解的执行配置。</small>
      </header>

      <section className="task-graph-cognition-workbench">
        <aside className="task-graph-cognition-workbench__nav boundary-card">
          <header><strong>节点列表</strong><span>{cognitionModel.packages.length} 个执行节点</span></header>
          <div className="task-graph-cognition-phase-list">
            {packagesByPhase.map(([phaseId, packages]) => (
              <section className="task-graph-cognition-phase-group" key={phaseId}>
                <strong>{phaseId}</strong>
                <div className="task-graph-cognition-list">
                  {packages.map((item) => (
                    <button
                      className={item.nodeId === selectedGraphNodeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                      key={item.nodeId}
                      onClick={() => onEditorFocus?.({ layer: "responsibility", facet: "cognition", node_id: item.nodeId })}
                      type="button"
                    >
                      <strong>{item.title}</strong>
                      <span>{item.role} / {item.agentId || "未绑定 Agent"}</span>
                      <em>{item.inputPackets.length} 输入 / {item.outputs.length} 输出 / {item.issues.length} 风险</em>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
          <div className="boundary-actions">
            <button
              className="boundary-chip"
              disabled={!selectedGraphNodeId}
              onClick={() => selectedGraphNodeId && onEditorFocus?.({ layer: "responsibility", facet: "node_standard", node_id: selectedGraphNodeId })}
              type="button"
            >
              <span>打开节点对象页</span>
            </button>
          </div>
        </aside>
        <div className="task-graph-cognition-workbench__main">
          <NodeResponsibilityCard
            onCreateProjectionFromPrompt={onCreateProjectionFromPrompt}
            projectionCards={projectionCards}
            selectedGraphNode={selectedGraphNode}
            selectedGraphNodeId={selectedGraphNodeId}
            updateTaskGraphNode={updateTaskGraphNode}
          />
          <CognitionPackagePanel nodePackage={nodePackage} />
          {editorFocus?.issue_id ? (
            <div className="task-graph-note">
              <strong>来自发布诊断：{editorFocus.issue_id}</strong>
              <span>当前页面已经按诊断焦点定位到节点或交接对象，请检查输入包使用说明、输出契约和 Prompt 预览是否配套。</span>
            </div>
          ) : null}
        </div>
        <aside className="task-graph-cognition-workbench__aside">
          <EdgeHandoffCard
            selectedGraphEdge={selectedGraphEdge}
            selectedGraphEdgeId={selectedGraphEdgeId}
            updateTaskGraphEdge={updateTaskGraphEdge}
          />
          <article className="boundary-card">
            <header><strong>交接设计原则</strong></header>
            <div className="task-graph-note">
              <strong>边负责可交付载荷，不负责让下游猜上下文</strong>
              <span>需要进入模型上下文的信息应配置成 packet、artifact ref、memory selector 或 revision packet，并在 Prompt 预览里出现明确用途。</span>
            </div>
          </article>
        </aside>
      </section>
    </section>
  );
}
