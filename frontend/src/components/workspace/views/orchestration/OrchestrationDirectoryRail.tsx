"use client";

import { Loader2, Network, Plus, Search, Trash2, Users } from "lucide-react";

import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

type AgentDirectorySection = "main_agent" | "builtin_system_agent" | "builtin_specialist_agent" | "custom_agent";
type AssemblySelectionKind = "agent" | "group" | "empty";
const DEFAULT_SUB_AGENT_GROUP_ID = "__default_sub_agent_group__";

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const labels: Record<string, string> = {
    main_agent: "主 Agent",
    builtin_agent: "内置 Agent",
    custom_agent: "子 Agent",
  };
  if (labels[raw]) return `${labels[raw]} · ${raw}`;
  return raw;
}

function displayName(agent: Record<string, unknown> | null | undefined) {
  return text(agent?.agent_name || agent?.display_name, displayId(agent?.agent_id, "未命名 Agent"));
}

export function OrchestrationDirectoryRail({
  agents,
  loading,
  query,
  setQuery,
  activeSection,
  sectionCounts,
  selectCategory,
  agentGroups,
  selectedGroupId,
  selectSubAgentGroup,
  selectedGroupAgents,
  ungroupedCustomAgents,
  selectedAgentId,
  selectAgent,
  activeSectionItems,
  selectionKind,
  saving,
  startBlankAgentDraft,
  startBlankGroupDraft,
  removeAgentById,
  removeSelectedGroup,
}: {
  agents: Array<Record<string, unknown>>;
  loading: boolean;
  query: string;
  setQuery: (value: string) => void;
  activeSection: AgentDirectorySection;
  sectionCounts: Record<string, number>;
  selectCategory: (section: AgentDirectorySection) => void;
  agentGroups: Array<{ group_id: string; title: string; member_agent_ids: string[] }>;
  selectedGroupId: string;
  selectSubAgentGroup: (groupId: string) => void;
  selectedGroupAgents: Array<Record<string, unknown>>;
  ungroupedCustomAgents: Array<Record<string, unknown>>;
  selectedAgentId: string;
  selectAgent: (agentId: string) => void;
  activeSectionItems: Array<Record<string, unknown>>;
  selectionKind: AssemblySelectionKind;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
  startBlankAgentDraft: () => void | Promise<void>;
  startBlankGroupDraft: () => void;
  removeAgentById: (agentId: string, agentName: string) => void;
  removeSelectedGroup: () => void;
}) {
  const sectionLabels: Record<AgentDirectorySection, string> = {
    main_agent: "主 Agent",
    builtin_system_agent: "系统 Agent",
    builtin_specialist_agent: "专业内置 Agent",
    custom_agent: "子 Agent",
  };

  const sectionDescriptions: Record<AgentDirectorySection, string> = {
    main_agent: "主会话入口与最终整合输出",
    builtin_system_agent: "系统管理与平台治理 Agent",
    builtin_specialist_agent: "知识、PDF、表格、网页等专业 Agent",
    custom_agent: "可分组、可作为子 Agent 的任务执行 Agent",
  };
  function AgentRow({
    agent,
    compact = false,
  }: {
    agent: Record<string, unknown>;
    compact?: boolean;
  }) {
    const agentId = String(agent.agent_id);
    const name = displayName(agent);
    const builtin = Boolean(agent.builtin);
    const category = String(agent.agent_category || agent.profile_type || "custom_agent");
    const profile = agent.runtime_profile && typeof agent.runtime_profile === "object" ? agent.runtime_profile as Record<string, unknown> : {};
    const profileId = String(profile.agent_profile_id || "");
    if (!compact) {
      return (
        <button
          className={agentId === selectedAgentId && selectionKind === "agent" ? "boundary-list-row boundary-list-row--active orchestration-agent-row" : "boundary-list-row orchestration-agent-row"}
          key={agentId}
          onClick={() => selectAgent(agentId)}
          type="button"
        >
          <div>
            <strong>{name}</strong>
            <span>{displayId(agent.agent_id)}</span>
          </div>
          <small>{profileId || displayId(category)}</small>
        </button>
      );
    }
    return (
      <div className={agentId === selectedAgentId && selectionKind === "agent" ? "orchestration-subagent-row orchestration-subagent-row--active" : "orchestration-subagent-row"}>
        <button className="orchestration-subagent-row__main" onClick={() => selectAgent(agentId)} type="button">
          <strong>{name}</strong>
          <span>{builtin ? "内置来源" : profileId || "子 Agent"}</span>
        </button>
        <button
          className="orchestration-subagent-row__delete"
          disabled={saving === "delete"}
          onClick={() => removeAgentById(agentId, name)}
          type="button"
        >
          <Trash2 size={14} />
        </button>
      </div>
    );
  }

  const customAgentCount = sectionCounts.custom_agent ?? (agentGroups.reduce((sum, group) => sum + group.member_agent_ids.length, 0) + ungroupedCustomAgents.length);
  const groupingRows = [
    {
      id: "main_agent",
      title: "主 Agent",
      count: sectionCounts.main_agent ?? 0,
      active: activeSection === "main_agent",
      onClick: () => selectCategory("main_agent"),
    },
    {
      id: "builtin_system_agent",
      title: "系统 Agent",
      count: sectionCounts.builtin_system_agent ?? 0,
      active: activeSection === "builtin_system_agent",
      onClick: () => selectCategory("builtin_system_agent"),
    },
    {
      id: "builtin_specialist_agent",
      title: "专业内置 Agent",
      count: sectionCounts.builtin_specialist_agent ?? 0,
      active: activeSection === "builtin_specialist_agent",
      onClick: () => selectCategory("builtin_specialist_agent"),
    },
    {
      id: "custom_agent",
      title: "子 Agent",
      count: customAgentCount,
      active: activeSection === "custom_agent",
      onClick: () => {
        selectCategory("custom_agent");
      },
    },
  ];

  const directoryStatusLabel = activeSection === "custom_agent"
    ? `${agentGroups.length + 1} 组 / ${customAgentCount} 个 Agent`
    : `${activeSectionItems.length} 项`;

  return (
    <aside className="boundary-rail orchestration-subagent-rail orchestration-practical-rail">
      <div className="boundary-rail__head orchestration-directory-head">
        <strong>Agent</strong>
        <span>{agents.length}</span>
      </div>
      <div className="boundary-search">
        <Search size={15} />
        <input onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称 / ID / 职责" value={query} />
      </div>
      <div className="orchestration-directory-switcher" aria-label="Agent 分组">
        {groupingRows.map((row) => (
          <button
            className={row.active ? "orchestration-directory-switcher__item orchestration-directory-switcher__item--active" : "orchestration-directory-switcher__item"}
            key={row.id}
            onClick={row.onClick}
            type="button"
          >
            <span>{row.title}</span>
            <strong>{row.count}</strong>
          </button>
        ))}
      </div>
      <div className="orchestration-section-title orchestration-section-title--compact">
        <span>{sectionLabels[activeSection]}</span>
        <small>{directoryStatusLabel} · {activeSection === "custom_agent" ? "行进入配置" : sectionDescriptions[activeSection]}</small>
      </div>
      <div className="boundary-list boundary-list--scroll orchestration-practical-list">
        {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
        {activeSection === "custom_agent" ? (
          <>
            {agentGroups.map((group) => (
              <div className={group.group_id === selectedGroupId && selectionKind === "group" ? "orchestration-practical-group orchestration-practical-group--active" : "orchestration-practical-group"} key={group.group_id}>
                <button className="orchestration-practical-group__head" onClick={() => selectSubAgentGroup(group.group_id)} type="button">
                  <Users size={15} />
                  <div>
                    <strong>{group.title}</strong>
                    <span>{group.member_agent_ids.length} 个成员</span>
                  </div>
                </button>
                {group.group_id === selectedGroupId ? (
                  <div className="orchestration-group-members">
                    {selectedGroupAgents.map((agent) => <AgentRow agent={agent} compact key={String(agent.agent_id)} />)}
                    {!selectedGroupAgents.length ? <div className="boundary-empty">当前组还没有成员。</div> : null}
                  </div>
                ) : null}
              </div>
            ))}
            <div className={selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID ? "orchestration-practical-group orchestration-practical-group--active" : "orchestration-practical-group"} key={DEFAULT_SUB_AGENT_GROUP_ID}>
              <button className="orchestration-practical-group__head" onClick={() => selectSubAgentGroup(DEFAULT_SUB_AGENT_GROUP_ID)} type="button">
                <Users size={15} />
                <div>
                  <strong>默认组</strong>
                  <span>{ungroupedCustomAgents.length} 个成员</span>
                </div>
              </button>
              {selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID ? (
                <div className="orchestration-group-members">
                  {ungroupedCustomAgents.map((agent) => <AgentRow agent={agent} compact key={String(agent.agent_id)} />)}
                  <button className="orchestration-subagent-create-row" onClick={startBlankAgentDraft} type="button">
                    <Plus size={16} />
                    <span>新建子 Agent</span>
                  </button>
                  {!ungroupedCustomAgents.length ? <div className="boundary-empty">当前默认组暂无子 Agent。</div> : null}
                </div>
              ) : null}
            </div>
          </>
        ) : null}
        {(activeSection === "custom_agent" ? [] : activeSectionItems).map((agent) => <AgentRow agent={agent} key={String(agent.agent_id)} />)}
        {!loading && (
          activeSection === "custom_agent"
            ? !agentGroups.length && !ungroupedCustomAgents.length
            : !activeSectionItems.length
        ) ? <div className="boundary-empty">当前层级暂无 Agent。</div> : null}
      </div>
      <div className="orchestration-directory-actions orchestration-directory-actions--practical">
        {activeSection === "custom_agent" ? (
          <>
          <OrchestrationToolbarButton onClick={startBlankGroupDraft} variant="ghost">
            <Network size={14} />
            新建组
          </OrchestrationToolbarButton>
          <OrchestrationToolbarButton
            disabled={!selectedGroupId || selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID || saving === "delete"}
            onClick={removeSelectedGroup}
            variant="danger"
          >
            <Trash2 size={14} />
            删除组
          </OrchestrationToolbarButton>
          </>
        ) : null}
        {activeSection === "custom_agent" ? (
          <OrchestrationToolbarButton onClick={startBlankAgentDraft} variant="ghost">
            <Plus size={14} />
            新建 Agent
          </OrchestrationToolbarButton>
        ) : null}
      </div>
    </aside>
  );
}
