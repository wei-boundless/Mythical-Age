"use client";

import { Save } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

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
  groupDraft,
  setGroupDraft,
  groupMembersChanged,
  saving,
  saveAgentGroup,
  groupDraftAvailableAgents,
  groupDraftMemberAgents,
  includeAllVisibleWorkers,
  clearGroupMembers,
  toggleGroupMember,
}: {
  groupDraft: AgentGroupDraftLike;
  setGroupDraft: Dispatch<SetStateAction<AgentGroupDraftLike>>;
  groupMembersChanged: boolean;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
  saveAgentGroup: () => Promise<void>;
  groupDraftAvailableAgents: Array<Record<string, unknown>>;
  groupDraftMemberAgents: Array<Record<string, unknown>>;
  includeAllVisibleWorkers: () => void;
  clearGroupMembers: () => void;
  toggleGroupMember: (agentId: string) => void;
}) {
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
        <Field label="组名">
          <input value={groupDraft.title} onChange={(event) => setGroupDraft((value) => ({ ...value, title: event.target.value }))} />
        </Field>
        <Field label="说明" wide>
          <textarea value={groupDraft.description} onChange={(event) => setGroupDraft((value) => ({ ...value, description: event.target.value }))} />
        </Field>
      </div>
      <div className="orchestration-member-toolbar">
        <button disabled={!groupDraftAvailableAgents.length} onClick={includeAllVisibleWorkers} type="button">
          全部加入
        </button>
        <button disabled={!groupDraftMemberAgents.length} onClick={clearGroupMembers} type="button">
          清空成员
        </button>
      </div>
      <div className="orchestration-member-workbench">
        <section className="orchestration-member-column">
          <header className="boundary-panel-head">
            <strong>已进组</strong>
            <span>{groupDraftMemberAgents.length}</span>
          </header>
          <div className="orchestration-member-picker">
            {groupDraftMemberAgents.map((agent) => (
              <button
                className="orchestration-member-card orchestration-member-card--selected"
                key={String(agent.agent_id)}
                onClick={() => toggleGroupMember(String(agent.agent_id))}
                type="button"
              >
                <strong>{displayName(agent)}</strong>
                <span>点击移出</span>
              </button>
            ))}
            {!groupDraftMemberAgents.length ? <div className="boundary-empty">当前还没有子 Agent 进入这个组。</div> : null}
          </div>
        </section>
        <section className="orchestration-member-column">
          <header className="boundary-panel-head">
            <strong>未进组</strong>
            <span>{groupDraftAvailableAgents.length}</span>
          </header>
          <div className="orchestration-member-picker">
            {groupDraftAvailableAgents.map((agent) => (
              <button
                className="orchestration-member-card"
                key={String(agent.agent_id)}
                onClick={() => toggleGroupMember(String(agent.agent_id))}
                type="button"
              >
                <strong>{displayName(agent)}</strong>
                <span>点击加入</span>
              </button>
            ))}
            {!groupDraftAvailableAgents.length ? <div className="boundary-empty">当前没有可加入的子 Agent。</div> : null}
          </div>
        </section>
      </div>
    </section>
  );
}
