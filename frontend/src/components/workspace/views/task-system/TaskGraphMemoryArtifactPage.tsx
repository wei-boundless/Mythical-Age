"use client";

import { ArtifactPolicyEditor } from "./ArtifactPolicyEditor";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { WorkingMemoryPolicyEditor, WORKING_MEMORY_KIND_OPTIONS, WORKING_MEMORY_SCOPE_OPTIONS } from "./WorkingMemoryPolicyEditor";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function edgeSource(edge: Record<string, unknown>) {
  return String(edge.source_node_id ?? edge.from ?? edge.source ?? "");
}

function edgeTarget(edge: Record<string, unknown>) {
  return String(edge.target_node_id ?? edge.to ?? edge.target ?? "");
}

export function TaskGraphMemoryArtifactPage({
  activeGraphNodes,
  activeGraphEdges,
  taskGraphDraft,
  updateContextPolicy,
  updateTaskGraphMetadata,
  updateWorkingMemoryPolicy,
  updateTaskGraphEdge,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  updateContextPolicy: (patch: Partial<TaskGraphDraftV2["context_policy"]>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateWorkingMemoryPolicy: (patch: Partial<TaskGraphDraftV2["working_memory_policy"]>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const metadata = asRecord(taskGraphDraft.metadata);
  const workingMemoryPolicy = asRecord(taskGraphDraft.working_memory_policy);
  const artifactPolicy = asRecord(metadata.artifact_policy);

  const updateArtifactPolicy = (patch: Record<string, unknown>) => {
    updateTaskGraphMetadata({
      artifact_policy: {
        ...artifactPolicy,
        ...patch,
      },
    });
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>记忆与产物</strong>
        <small>定义 Agent 读什么、写什么、交接什么，以及产物如何落盘。</small>
      </header>

      <section className="task-graph-form-grid">
        <WorkingMemoryPolicyEditor
          memorySharingPolicy={taskGraphDraft.context_policy.memory_sharing_policy}
          policy={workingMemoryPolicy}
          sharedContextPolicy={taskGraphDraft.context_policy.shared_context_policy}
          onMemorySharingPolicyChange={(value) => updateContextPolicy({ memory_sharing_policy: value })}
          onPolicyChange={updateWorkingMemoryPolicy}
          onSharedContextPolicyChange={(value) => updateContextPolicy({ shared_context_policy: value })}
        />

        <ArtifactPolicyEditor
          policy={artifactPolicy}
          onPolicyChange={updateArtifactPolicy}
        />
      </section>

      <section className="boundary-card">
        <header><strong>节点记忆与产物边界</strong></header>
        <div className="task-graph-node-policy-list">
          {activeGraphNodes.map((node, index) => {
            const nodeId = String(node.node_id ?? "");
            const readPolicy = asRecord(node.memory_read_policy);
            const writePolicy = asRecord(node.memory_writeback_policy);
            const nodeArtifactPolicy = asRecord(node.artifact_policy);
            return (
              <article className="task-graph-node-policy-row" key={nodeId || `node_${index}`}>
                <div className="task-graph-node-policy-row__identity">
                  <strong>{nodeTitle(node)}</strong>
                  <span>{nodeId}</span>
                </div>
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="读取范围"
                  onChange={(value) => updateTaskGraphNode(nodeId, { memory_read_policy: { ...readPolicy, scope: value } })}
                  options={WORKING_MEMORY_SCOPE_OPTIONS}
                  value={String(readPolicy.scope ?? "node_scope")}
                />
                <TaskSystemField label="可读 Kind">
                  <textarea
                    onChange={(event) => updateTaskGraphNode(nodeId, { memory_read_policy: { ...readPolicy, readable_kinds: splitList(event.target.value) } })}
                    value={listText(readPolicy.readable_kinds)}
                  />
                </TaskSystemField>
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="写回策略"
                  onChange={(value) => updateTaskGraphNode(nodeId, { memory_writeback_policy: { ...writePolicy, writeback_policy: value } })}
                  options={["task_default", "task_summary_only", "session_and_durable"]}
                  value={String(writePolicy.writeback_policy ?? "task_default")}
                />
                <TaskSystemField label="可写 Kind">
                  <textarea
                    onChange={(event) => updateTaskGraphNode(nodeId, { memory_writeback_policy: { ...writePolicy, writable_kinds: splitList(event.target.value) } })}
                    value={listText(writePolicy.writable_kinds)}
                  />
                </TaskSystemField>
                <TaskSystemField label="产物目标">
                  <input
                    onChange={(event) => updateTaskGraphNode(nodeId, { artifact_target: event.target.value, output_path: event.target.value })}
                    placeholder="artifacts/result.md"
                    value={String(node.artifact_target ?? node.output_path ?? "")}
                  />
                </TaskSystemField>
                <label className="boundary-check">
                  <input
                    checked={nodeArtifactPolicy.required === true}
                    onChange={(event) => updateTaskGraphNode(nodeId, { artifact_policy: { ...nodeArtifactPolicy, required: event.target.checked } })}
                    type="checkbox"
                  />
                  阶段必需产物
                </label>
              </article>
            );
          })}
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>边级记忆交接</strong><span>只描述交接携带什么，不替节点扩大权限</span></header>
        <div className="task-graph-node-policy-list">
          {activeGraphEdges.map((edge, index) => {
            const edgeId = String(edge.edge_id ?? edge.id ?? `edge_${index + 1}`);
            const handoffPolicy = asRecord(edge.working_memory_handoff_policy);
            return (
              <article className="task-graph-node-policy-row" key={edgeId}>
                <div className="task-graph-node-policy-row__identity">
                  <strong>{edgeSource(edge)} {"->"} {edgeTarget(edge)}</strong>
                  <span>{edgeId}</span>
                </div>
                <TaskSystemField label="携带 Kind">
                  <textarea
                    onChange={(event) => updateTaskGraphEdge(edgeId, {
                      working_memory_handoff_policy: {
                        ...handoffPolicy,
                        carry_kinds: splitList(event.target.value),
                      },
                    })}
                    placeholder={WORKING_MEMORY_KIND_OPTIONS.slice(0, 3).join("\n")}
                    value={listText(handoffPolicy.carry_kinds)}
                  />
                </TaskSystemField>
                <TaskSystemField label="携带 Scope">
                  <textarea
                    onChange={(event) => updateTaskGraphEdge(edgeId, {
                      working_memory_handoff_policy: {
                        ...handoffPolicy,
                        carry_scopes: splitList(event.target.value),
                      },
                    })}
                    placeholder={"edge_scope\nartifact_scope"}
                    value={listText(handoffPolicy.carry_scopes)}
                  />
                </TaskSystemField>
                <label className="boundary-check">
                  <input
                    checked={handoffPolicy.summary_only === true}
                    onChange={(event) => updateTaskGraphEdge(edgeId, {
                      working_memory_handoff_policy: {
                        ...handoffPolicy,
                        summary_only: event.target.checked,
                      },
                    })}
                    type="checkbox"
                  />
                  只传摘要或引用
                </label>
              </article>
            );
          })}
          {!activeGraphEdges.length ? (
            <div className="task-graph-note">
              <strong>暂无通信边</strong>
              <span>创建边后可以在这里定义工作记忆交接携带的 Kind、Scope 和摘要策略。</span>
            </div>
          ) : null}
        </div>
      </section>
    </section>
  );
}
