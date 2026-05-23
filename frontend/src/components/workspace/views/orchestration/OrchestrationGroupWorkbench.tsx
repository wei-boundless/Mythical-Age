"use client";

import { Plus, Save, Trash2 } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import type { OrchestrationAgentGroup } from "@/lib/api";

type AgentGroupDraftLike = OrchestrationAgentGroup & {
  member_agent_ids_text: string;
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const prefixLabels: Array<[string, string]> = [
    ["agent:", "Agent"],
    ["group.", "Agent 组"],
  ];
  const labels: Record<string, string> = {
    coordination_team: "协调任务组",
    worker_pool: "执行池",
    review_team: "审查组",
    enabled: "启用",
    disabled: "停用",
    draft: "草稿",
  };
  if (labels[raw]) return `${labels[raw]} · ${raw}`;
  const matched = prefixLabels.find(([prefix]) => raw.startsWith(prefix));
  return matched ? `${matched[1]} · ${raw}` : raw;
}

function displayName(agent: Record<string, unknown> | null | undefined) {
  return text(agent?.agent_name || agent?.display_name, displayId(agent?.agent_id, "未命名 Agent"));
}

function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "danger" }) {
  return <span className={`boundary-badge boundary-badge--${tone}`}>{children}</span>;
}

function ToolbarButton({
  children,
  disabled,
  onClick,
  variant = "ghost",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  variant?: "ghost" | "primary" | "danger";
}) {
  return (
    <button className={`boundary-button boundary-button--${variant}`} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={wide ? "boundary-field boundary-field--wide" : "boundary-field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function OrchestrationGroupWorkbench({
  agents,
  groupDraft,
  setGroupDraft,
  groupMembersChanged,
  saving,
  saveAgentGroup,
  groupDraftAvailableAgents,
  groupDraftMemberAgents,
  toggleGroupMember,
}: {
  agents: Array<Record<string, unknown>>;
  groupDraft: AgentGroupDraftLike;
  setGroupDraft: Dispatch<SetStateAction<AgentGroupDraftLike>>;
  groupMembersChanged: boolean;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
  saveAgentGroup: () => Promise<void>;
  groupDraftAvailableAgents: Array<Record<string, unknown>>;
  groupDraftMemberAgents: Array<Record<string, unknown>>;
  toggleGroupMember: (agentId: string) => void;
}) {
  const confirm = useConfirmDialog();
  const memberCount = groupDraftMemberAgents.length;
  const availableCount = groupDraftAvailableAgents.length;
  const agentOptions = Array.from(new Set([
    "",
    groupDraft.coordinator_agent_id,
    ...agents.map((agent) => String(agent.agent_id ?? "")).filter(Boolean),
  ]));
  const groupKinds = Array.from(new Set([groupDraft.group_kind || "coordination_team", "coordination_team", "worker_pool", "review_team"]));
  const lifecycleStates = Array.from(new Set([groupDraft.lifecycle_state || "enabled", "enabled", "disabled", "draft"]));

  async function confirmRemoveMember(agentId: string, name: string) {
    if (await confirm({
      title: `移出 Agent「${name || agentId}」`,
      body: "该 Agent 会从当前组成员中移除，保存后生效。",
      confirmLabel: "移出成员",
      tone: "warning",
    })) {
      toggleGroupMember(agentId);
    }
  }

  return (
    <section className="boundary-card orchestration-group-main">
      <header>
        <strong>{groupDraft.title || "子 Agent 组草稿"}</strong>
        <div className="boundary-inline-actions">
          {groupMembersChanged ? <Badge tone="warn">未保存</Badge> : <Badge tone="ok">已同步</Badge>}
          <ToolbarButton disabled={saving === "group"} onClick={() => void saveAgentGroup()} variant="primary">
            <Save size={15} />
            保存组
          </ToolbarButton>
        </div>
      </header>
      <div className="boundary-form">
        <Field label="组标识">
          <input value={groupDraft.group_id} onChange={(event) => setGroupDraft((value) => ({ ...value, group_id: event.target.value }))} />
        </Field>
        <Field label="组名">
          <input value={groupDraft.title} onChange={(event) => setGroupDraft((value) => ({ ...value, title: event.target.value }))} />
        </Field>
        <Field label="组类型">
          <select value={groupDraft.group_kind} onChange={(event) => setGroupDraft((value) => ({ ...value, group_kind: event.target.value }))}>
            {groupKinds.map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
          </select>
        </Field>
        <Field label="协调者">
          <select value={groupDraft.coordinator_agent_id || ""} onChange={(event) => setGroupDraft((value) => ({ ...value, coordinator_agent_id: event.target.value }))}>
            {agentOptions.map((item) => <option key={item || "none"} value={item}>{item ? displayName(agents.find((agent) => String(agent.agent_id ?? "") === item)) : "不指定协调者"}</option>)}
          </select>
        </Field>
        <Field label="生命周期">
          <select value={groupDraft.lifecycle_state} onChange={(event) => setGroupDraft((value) => ({ ...value, lifecycle_state: event.target.value }))}>
            {lifecycleStates.map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
          </select>
        </Field>
        <Field label="说明" wide>
          <textarea value={groupDraft.description} onChange={(event) => setGroupDraft((value) => ({ ...value, description: event.target.value }))} />
        </Field>
      </div>
      <div className="orchestration-group-summary" aria-label="组摘要">
        <article className="orchestration-group-summary-row">
          <span>组内成员</span>
          <strong>{memberCount}</strong>
          <small>{memberCount ? "已进入当前组" : "还没有成员"}</small>
        </article>
        <article className="orchestration-group-summary-row">
          <span>可加入成员</span>
          <strong>{availableCount}</strong>
          <small>{availableCount ? "可在下方行列表直接加入" : "没有可加入成员"}</small>
        </article>
        <article className="orchestration-group-summary-row">
          <span>协调者</span>
          <strong>{groupDraft.coordinator_agent_id ? displayName(agents.find((agent) => String(agent.agent_id ?? "") === groupDraft.coordinator_agent_id)) : "未指定"}</strong>
          <small>{displayId(groupDraft.group_kind || "coordination_team")}</small>
        </article>
      </div>
      <div className="orchestration-member-workbench">
        <section className="orchestration-member-column">
          <header className="boundary-panel-head">
            <strong>已进组</strong>
            <span>{memberCount}</span>
          </header>
          <div className="orchestration-member-list">
            {groupDraftMemberAgents.map((agent) => (
              <article className="orchestration-member-row orchestration-member-row--selected" key={String(agent.agent_id)}>
                <div className="orchestration-member-row__body">
                  <strong>{displayName(agent)}</strong>
                  <span>{displayId(agent.agent_id)}</span>
                </div>
                <button
                  className="orchestration-member-row__action orchestration-member-row__action--danger"
                  onClick={() => confirmRemoveMember(String(agent.agent_id), displayName(agent))}
                  type="button"
                >
                  <Trash2 size={14} />
                  <span>移出</span>
                </button>
              </article>
            ))}
            {!groupDraftMemberAgents.length ? <div className="boundary-empty">当前还没有子 Agent 进入这个组。</div> : null}
          </div>
        </section>
        <section className="orchestration-member-column">
          <header className="boundary-panel-head">
            <strong>未进组</strong>
            <span>{availableCount}</span>
          </header>
          <div className="orchestration-member-list">
            {groupDraftAvailableAgents.map((agent) => (
              <article className="orchestration-member-row" key={String(agent.agent_id)}>
                <div className="orchestration-member-row__body">
                  <strong>{displayName(agent)}</strong>
                  <span>{displayId(agent.agent_id)}</span>
                </div>
                <button
                  className="orchestration-member-row__action"
                  onClick={() => toggleGroupMember(String(agent.agent_id))}
                  type="button"
                >
                  <Plus size={14} />
                  <span>加入</span>
                </button>
              </article>
            ))}
            {!groupDraftAvailableAgents.length ? <div className="boundary-empty">当前没有可加入的子 Agent。</div> : null}
          </div>
        </section>
      </div>
    </section>
  );
}
