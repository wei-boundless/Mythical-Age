"use client";

import { useMemo } from "react";

import type { TaskGraphStandardEdgeSpec, TaskGraphStandardView } from "@/lib/api";

import { TaskSystemField, TaskSystemSelectField } from "./TaskSystemWorkbenchUi";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { describeTaskGraphStandardEdge } from "./taskGraphStandardView";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function edgeIdOf(edge: Record<string, unknown>, index = 0) {
  return stringValue(edge.edge_id ?? edge.id, `edge_${index + 1}`);
}

function edgeSource(edge: Record<string, unknown>) {
  return stringValue(edge.source_node_id ?? edge.from ?? edge.source);
}

function edgeTarget(edge: Record<string, unknown>) {
  return stringValue(edge.target_node_id ?? edge.to ?? edge.target);
}

function edgeLabel(edge: Record<string, unknown>, index = 0) {
  return `${edgeSource(edge)} -> ${edgeTarget(edge)} · ${stringValue(edge.edge_type ?? edge.mode, edgeIdOf(edge, index))}`;
}

function standardEdgeById(standardView: TaskGraphStandardView | null) {
  return new Map((standardView?.edges ?? []).map((edge) => [edge.edge_id, edge]));
}

function edgeIssueCount(standardView: TaskGraphStandardView | null, edgeId: string) {
  return (standardView?.issues ?? []).filter((issue) => issue.edge_id === edgeId).length;
}

export function TaskGraphEdgeStandardPage({
  activeGraphEdges,
  selectedGraphEdge,
  selectedGraphEdgeId,
  standardView,
  editorFocus,
  onEditorFocus,
  updateTaskGraphEdge,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  selectedGraphEdge: Record<string, unknown> | null;
  selectedGraphEdgeId: string;
  standardView: TaskGraphStandardView | null;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  const standardEdges = useMemo(() => standardEdgeById(standardView), [standardView]);
  const focusEdgeId = selectedGraphEdgeId || activeGraphEdges[0]?.edge_id || "";
  const currentEdge = selectedGraphEdge ?? activeGraphEdges.find((edge, index) => edgeIdOf(edge, index) === focusEdgeId) ?? null;
  const currentEdgeId = currentEdge ? edgeIdOf(currentEdge) : "";
  const standardEdge = currentEdgeId ? standardEdges.get(currentEdgeId) ?? null : null;
  const memory = asRecord(standardEdge?.memory);
  const handoff = asRecord(standardEdge?.handoff);
  const artifactContext = asRecord(standardEdge?.artifact_context);
  const revision = asRecord(standardEdge?.revision);
  const temporal = asRecord(standardEdge?.temporal);

  return (
    <section className="task-graph-cognition-workbench">
      <aside className="task-graph-cognition-workbench__nav boundary-card">
        <header><strong>边对象</strong><span>{activeGraphEdges.length} edges</span></header>
        <div className="task-graph-cognition-phase-list">
          {activeGraphEdges.map((edge, index) => {
            const edgeId = edgeIdOf(edge, index);
            const active = edgeId === currentEdgeId;
            return (
              <button
                className={active ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                key={edgeId}
                onClick={() => onEditorFocus?.({ layer: "contracts", facet: "edge_standard", edge_id: edgeId })}
                type="button"
              >
                <strong>{edgeLabel(edge, index)}</strong>
                <span>{edgeId}</span>
                <em>{edgeIssueCount(standardView, edgeId)} issues</em>
              </button>
            );
          })}
        </div>
      </aside>

      <div className="task-graph-cognition-workbench__main">
        <article className="boundary-card">
          <header><strong>边标准对象</strong><span>{currentEdgeId || "未选择边"}</span></header>
          {currentEdge && currentEdgeId ? (
            <div className="boundary-form">
              <TaskSystemField label="边 ID">
                <input disabled value={currentEdgeId} />
              </TaskSystemField>
              <TaskSystemField label="源节点">
                <input disabled value={edgeSource(currentEdge)} />
              </TaskSystemField>
              <TaskSystemField label="目标节点">
                <input disabled value={edgeTarget(currentEdge)} />
              </TaskSystemField>
              <TaskSystemSelectField
                label="边类型"
                onChange={(value) => updateTaskGraphEdge(currentEdgeId, { edge_type: value })}
                options={["structured_handoff", "control_flow", "memory_read", "memory_write_candidate", "memory_commit", "artifact_context", "revision_request", "temporal_dependency"]}
                value={stringValue(currentEdge.edge_type ?? currentEdge.mode, "structured_handoff")}
              />
              <TaskSystemField label="载荷契约">
                <input
                  onChange={(event) => updateTaskGraphEdge(currentEdgeId, { payload_contract_id: event.target.value, contract_id: event.target.value })}
                  value={stringValue(currentEdge.payload_contract_id ?? currentEdge.contract_id)}
                />
              </TaskSystemField>
              <TaskSystemField label="模型可见标签">
                <input
                  onChange={(event) => updateTaskGraphEdge(currentEdgeId, {
                    metadata: {
                      ...asRecord(currentEdge.metadata),
                      model_visible_label: event.target.value,
                    },
                  })}
                  value={stringValue(asRecord(currentEdge.metadata).model_visible_label)}
                />
              </TaskSystemField>
              <TaskSystemField label="Prompt 使用说明" wide>
                <textarea
                  onChange={(event) => updateTaskGraphEdge(currentEdgeId, {
                    metadata: {
                      ...asRecord(currentEdge.metadata),
                      usage_instruction: event.target.value,
                    },
                  })}
                  value={stringValue(asRecord(currentEdge.metadata).usage_instruction)}
                />
              </TaskSystemField>
            </div>
          ) : (
            <div className="task-graph-note">
              <strong>未选择边</strong>
              <span>这里查看当前边的载荷契约、交接语义和标准对象投影。</span>
            </div>
          )}
        </article>
      </div>

      <aside className="task-graph-cognition-workbench__aside">
        <article className="boundary-card">
          <header><strong>标准对象投影</strong><span>{standardEdge?.edge_id || "未加载"}</span></header>
          {standardEdge ? (
            <>
              <div className="task-graph-note">
                <strong>{describeTaskGraphStandardEdge(standardEdge)}</strong>
                <span>{String(standardEdge.source_node_id || "") + " -> " + String(standardEdge.target_node_id || "")}</span>
              </div>
              <div className="task-graph-mini-kv">
                <p><span>载荷契约</span><strong>{stringValue(standardEdge.payload_contract_id, "未绑定")}</strong></p>
                <p><span>交接模式</span><strong>{stringValue(handoff.ack_policy || handoff.wait_policy, "default")}</strong></p>
                <p><span>Memory</span><strong>{stringValue(memory.repository_id || memory.repository, "-")}</strong></p>
                <p><span>Artifact</span><strong>{stringValue(artifactContext.context_mode, "-")}</strong></p>
                <p><span>Revision</span><strong>{stringValue(revision.original_artifact_key || revision.review_result_key, "-")}</strong></p>
                <p><span>Temporal</span><strong>{stringValue(temporal.dependency_role || temporal.phase_id, "-")}</strong></p>
              </div>
            </>
          ) : (
            <div className="task-graph-note">
              <strong>标准视图尚未对齐到该边</strong>
              <span>保存或刷新标准对象视图后，这里会显示后端编译出来的边标准对象投影。</span>
            </div>
          )}
        </article>
        {editorFocus?.issue_id ? (
          <article className="boundary-card">
            <header><strong>当前诊断焦点</strong></header>
            <div className="task-graph-note">
              <strong>{editorFocus.issue_id}</strong>
              <span>当前边对象页已经按焦点边打开，优先核对载荷契约、usage instruction 和 edge type 语义是否一致。</span>
            </div>
          </article>
        ) : null}
      </aside>
    </section>
  );
}
