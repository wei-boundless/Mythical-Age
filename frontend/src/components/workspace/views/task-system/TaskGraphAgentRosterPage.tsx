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

function legacyFieldNames(value: unknown): string[] {
  const record = asRecord(value);
  const next = record.legacy_field_names;
  return Array.isArray(next) ? next.map((item) => String(item)).filter(Boolean) : [];
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
    const operations = Array.isArray(profile.allowed_operations) ? profile.allowed_operations.length : 0;
    if (!profileId) return "未绑定运行档案";
    return `${profileId} / ${operations} 个操作`;
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>任务图工作台</span>
        <strong>节点装配</strong>
        <small>为当前图模块绑定执行者、Agent 与运行档案；执行者主数据由注册表维护，本页只写入节点装配关系。</small>
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
          <header><strong>提示词主数据</strong></header>
          <div className="task-graph-note">
            <strong>归属已切换到任务图节点</strong>
            <span>图级和节点级提示词由节点角色 Prompt、输入契约和输出契约共同表达；请在职责与交接页收口旧职责字段。</span>
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
            const rolePrompt = String(node.role_prompt ?? nodeMetadata.role_prompt ?? "").trim();
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
                    <span>运行档案</span>
                    <strong>{formatProfileSummary(effectivePolicyDisplayValue(agentPolicy.value))}</strong>
                    <em>编排系统</em>
                  </p>
                  <p>
                    <span>角色 Prompt</span>
                    <strong>{rolePrompt ? "已配置" : "未配置"}</strong>
                    <em>任务图节点</em>
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
                <TaskSystemField label="节点角色 Prompt">
                  <input readOnly value={rolePrompt || "未配置"} />
                </TaskSystemField>
                {legacyFieldNames(nodeMetadata.legacy_prompt_migration).length > 0 ? (
                  <div className="task-graph-note">
                    <strong>旧提示词待收口</strong>
                    <span>该节点仍有旧职责字段，请到职责与交接页合并为角色 Prompt。</span>
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
