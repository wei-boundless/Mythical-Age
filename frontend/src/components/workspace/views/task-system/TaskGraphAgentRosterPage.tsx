"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { effectivePolicyDisplayValue, resolveTaskGraphEffectivePolicy } from "./taskGraphEffectivePolicy";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";
import type { OrchestrationAgentRuntimeCatalog } from "@/lib/api";

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
  orchestrationAgentCatalog,
  taskGraphDraft,
  updateRuntimePolicy,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  a2aCatalog: TaskGraphWorkbenchAgentCatalog | null;
  orchestrationAgentCatalog: OrchestrationAgentRuntimeCatalog | null;
  taskGraphDraft: TaskGraphDraftV2;
  updateRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const coordinatorAgentId = String(taskGraphDraft.runtime_policy.coordinator_agent_id ?? "agent:0");
  const participantAgentIds = taskGraphDraft.runtime_policy.participant_agent_ids ?? [];
  const knownAgentIds = uniqueStrings([
    coordinatorAgentId,
    ...participantAgentIds,
    ...activeGraphNodes.map((node) => String(node.agent_id ?? "")),
    ...((orchestrationAgentCatalog?.agents ?? []).map((agent) => String(agent.agent_id ?? ""))),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => String(card.agent_id ?? ""))),
  ]);
  const agentGroupOptions = uniqueStrings([
    String(taskGraphDraft.runtime_policy.agent_group_id ?? ""),
    ...((orchestrationAgentCatalog?.agent_groups ?? []).map((group) => String(group.group_id ?? ""))),
  ]);

  const formatAgent = (agentId: string) => {
    const agent = (orchestrationAgentCatalog?.agents ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    if (!agentId) return "不绑定";
    const agentName = String(agent?.display_name ?? agent?.agent_name ?? "").trim();
    if (agentName) return `${agentName} · ${agentId}`;
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };
  const formatAgentGroup = (groupId: string) => {
    const group = (orchestrationAgentCatalog?.agent_groups ?? []).find((item) => String(item.group_id ?? "") === groupId);
    if (!groupId) return "不绑定 Agent 组";
    return group?.title ? `${String(group.title)} · ${groupId}` : groupId;
  };
  const runtimeProfileForAgent = (agentId: string) => {
    const agent = (orchestrationAgentCatalog?.agents ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    const inlineProfile = asRecord(agent?.runtime_profile);
    if (Object.keys(inlineProfile).length) return inlineProfile;
    return asRecord((orchestrationAgentCatalog?.profiles ?? []).find((profile) => String(profile.agent_id ?? "") === agentId));
  };
  const formatProfileSummary = (agentId: string) => {
    const profile = runtimeProfileForAgent(agentId);
    const profileId = String(profile.agent_profile_id ?? "").trim();
    const lanes = Array.isArray(profile.allowed_runtime_lanes) ? profile.allowed_runtime_lanes.length : 0;
    const operations = Array.isArray(profile.allowed_operations) ? profile.allowed_operations.length : 0;
    if (!profileId) return "未绑定 Runtime Profile";
    return `${profileId} / ${lanes} lanes / ${operations} ops`;
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
            <TaskSystemSelectField
              formatOption={formatAgentGroup}
              label="Agent 组"
              onChange={(value) => updateRuntimePolicy({ agent_group_id: value })}
              options={agentGroupOptions}
              value={taskGraphDraft.runtime_policy.agent_group_id}
            />
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
          <header><strong>Prompt 主数据</strong></header>
          <div className="task-graph-note">
            <strong>归属已切换到投影系统</strong>
            <span>图级和节点级 Prompt 不再在 TaskGraph 内直接编辑；请在职责与交接页生成并绑定 Projection。</span>
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
            const projectionPolicy = resolveTaskGraphEffectivePolicy({
              key: "projection_id",
              node,
              graph: asRecord(taskGraphDraft.metadata),
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
                    <span>Runtime Profile</span>
                    <strong>{formatProfileSummary(effectivePolicyDisplayValue(agentPolicy.value))}</strong>
                    <em>编排系统</em>
                  </p>
                  <p>
                    <span>Projection 来源</span>
                    <strong>{projectionPolicy.configured ? effectivePolicyDisplayValue(projectionPolicy.value) : "未绑定"}</strong>
                    <em>{projectionPolicy.source_label}</em>
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
                <TaskSystemField label="节点职责 Projection">
                  <input readOnly value={String(node.projection_id ?? node.projection_overlay_id ?? "未绑定")} />
                </TaskSystemField>
                {String(nodeMetadata.role_prompt ?? "").trim() ? (
                  <div className="task-graph-note">
                    <strong>Legacy Prompt 待迁移</strong>
                    <span>该节点仍有旧 Prompt 文本，请到职责与交接页生成并绑定投影。</span>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}
