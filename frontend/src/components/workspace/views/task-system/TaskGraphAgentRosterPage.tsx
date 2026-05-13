"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { effectivePolicyDisplayValue, resolveTaskGraphEffectivePolicy } from "./taskGraphEffectivePolicy";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function parseList(text: string) {
  return text
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function TaskGraphAgentRosterPage({
  activeGraphNodes,
  a2aCatalog,
  taskGraphDraft,
  updateRuntimePolicy,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  a2aCatalog: TaskGraphWorkbenchAgentCatalog | null;
  taskGraphDraft: TaskGraphDraftV2;
  updateRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const coordinatorAgentId = String(taskGraphDraft.runtime_policy.coordinator_agent_id ?? "agent:0");
  const participantAgentIds = taskGraphDraft.runtime_policy.participant_agent_ids ?? [];
  const knownAgentIds = uniqueStrings([
    coordinatorAgentId,
    ...participantAgentIds,
    ...activeGraphNodes.map((node) => String(node.agent_id ?? "")),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => String(card.agent_id ?? ""))),
  ]);

  const formatAgent = (agentId: string) => {
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    if (!agentId) return "不绑定";
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>Agent 编组</strong>
        <small>定义协调者、参与者与节点职责边界，减少上下文污染。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>协调与参与</strong></header>
          <div className="boundary-form">
            <TaskSystemSelectField
              formatOption={formatAgent}
              label="协调者 Agent"
              onChange={(value) => updateRuntimePolicy({ coordinator_agent_id: value })}
              options={knownAgentIds}
              value={coordinatorAgentId}
            />
            <TaskSystemField label="参与者列表">
              <textarea
                onChange={(event) => updateRuntimePolicy({ participant_agent_ids: parseList(event.target.value) })}
                placeholder="agent:writer_01&#10;agent:review_01"
                value={participantAgentIds.join("\n")}
              />
            </TaskSystemField>
            <TaskSystemField label="Agent 组 ID">
              <input
                onChange={(event) => updateRuntimePolicy({ agent_group_id: event.target.value })}
                value={taskGraphDraft.runtime_policy.agent_group_id}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="协作模式"
              onChange={(value) => updateRuntimePolicy({ coordination_mode: value })}
              options={["review_merge", "pipeline", "parallel_review"]}
              value={taskGraphDraft.runtime_policy.coordination_mode}
            />
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>角色职责提示</strong></header>
          <div className="task-graph-note">
            <strong>Prompt 原则</strong>
            <span>请写角色职责语言，不要写开发字段说明。示例：你是一名审核员，你只负责裁决是否通过，不负责扩写内容。</span>
          </div>
          <div className="boundary-form">
            <TaskSystemField label="图级协作说明">
              <textarea
                onChange={(event) => updateTaskGraphMetadata({ role_prompt: event.target.value })}
                placeholder="你是协调者，负责推进阶段、整合子结论、对冲突做裁决。"
                value={String(asRecord(taskGraphDraft.metadata).role_prompt ?? "")}
              />
            </TaskSystemField>
          </div>
        </article>
      </section>

      <section className="boundary-card">
        <header><strong>节点绑定</strong></header>
        <div className="task-graph-agent-node-grid">
          {activeGraphNodes.map((node, index) => {
            const nodeId = String(node.node_id ?? "");
            const nodeMetadata = asRecord(node.metadata);
            const role = String(node.work_posture ?? node.role ?? "participant");
            const agentPolicy = resolveTaskGraphEffectivePolicy({
              key: "agent_id",
              node,
              graph: { agent_id: coordinatorAgentId },
              agentRolePreset: role === "coordinator" ? { agent_id: coordinatorAgentId } : null,
              systemDefault: "agent:0",
            });
            const promptPolicy = resolveTaskGraphEffectivePolicy({
              key: "role_prompt",
              node,
              graph: asRecord(taskGraphDraft.metadata),
              agentRolePreset: {
                role_prompt: role === "reviewer"
                  ? "你是一名审核员。你只负责裁决当前结果是否允许进入下一阶段。"
                  : "",
              },
            });
            return (
              <article className="task-graph-agent-node-card" key={nodeId || `node_${index}`}>
                <div className="task-graph-agent-node-card__title">
                  <strong>{nodeTitle(node)}</strong>
                  <span>{nodeId}</span>
                </div>
                <div className="task-graph-effective-policy-strip">
                  <p>
                    <span>有效 Agent</span>
                    <strong>{formatAgent(effectivePolicyDisplayValue(agentPolicy.value))}</strong>
                    <em>{agentPolicy.source_label}</em>
                  </p>
                  <p>
                    <span>Prompt 来源</span>
                    <strong>{promptPolicy.configured ? "已配置" : "未配置"}</strong>
                    <em>{promptPolicy.source_label}</em>
                  </p>
                </div>
                <TaskSystemSelectField
                  formatOption={formatAgent}
                  label="执行 Agent"
                  onChange={(value) => updateTaskGraphNode(nodeId, { agent_id: value })}
                  options={knownAgentIds}
                  value={String(node.agent_id ?? "")}
                />
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="工作姿态"
                  onChange={(value) => updateTaskGraphNode(nodeId, { role: value, work_posture: value })}
                  options={["coordinator", "planner", "executor", "reviewer", "verifier", "summarizer", "merge", "acceptance", "participant"]}
                  value={String(node.work_posture ?? node.role ?? "participant")}
                />
                <TaskSystemField label="节点职责 Prompt">
                  <textarea
                    onChange={(event) => updateTaskGraphNode(nodeId, {
                      metadata: {
                        ...nodeMetadata,
                        role_prompt: event.target.value,
                      },
                    })}
                    placeholder="你是一名资料分析员。你只负责提炼证据并标注来源，不负责最终裁决。"
                    value={String(nodeMetadata.role_prompt ?? "")}
                  />
                </TaskSystemField>
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}
