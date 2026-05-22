"use client";

import { Loader2, Network, Plus, Search, Trash2, Users } from "lucide-react";

import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

type AgentCategory = "main_agent" | "builtin_agent" | "custom_agent";
type CustomDirectoryMode = "grouped" | "ungrouped";
type AssemblySelectionKind = "agent" | "group" | "empty";

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
  activeCategory,
  categoryCounts,
  selectCategory,
  customDirectoryMode,
  selectCustomDirectoryMode,
  agentGroups,
  selectedGroupId,
  selectSubAgentGroup,
  selectedGroupAgents,
  ungroupedCustomAgents,
  selectedAgentId,
  selectAgent,
  activeGroupItems,
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
  activeCategory: AgentCategory;
  categoryCounts: Record<string, number>;
  selectCategory: (category: AgentCategory) => void;
  customDirectoryMode: CustomDirectoryMode;
  selectCustomDirectoryMode: (mode: CustomDirectoryMode) => void;
  agentGroups: Array<{ group_id: string; title: string; member_agent_ids: string[] }>;
  selectedGroupId: string;
  selectSubAgentGroup: (groupId: string) => void;
  selectedGroupAgents: Array<Record<string, unknown>>;
  ungroupedCustomAgents: Array<Record<string, unknown>>;
  selectedAgentId: string;
  selectAgent: (agentId: string) => void;
  activeGroupItems: Array<Record<string, unknown>>;
  selectionKind: AssemblySelectionKind;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
  startBlankAgentDraft: () => void | Promise<void>;
  startBlankGroupDraft: () => void;
  removeAgentById: (agentId: string, agentName: string) => void;
  removeSelectedGroup: () => void;
}) {
  const categoryLabels: Record<AgentCategory, string> = {
    main_agent: "主 Agent",
    builtin_agent: "内置 Agent",
    custom_agent: "子 Agent",
  };

  const categoryDescriptions: Record<AgentCategory, string> = {
    main_agent: "主会话入口与最终整合输出",
    builtin_agent: "系统管理与内置专业 Agent",
    custom_agent: "可分组、可委派的任务执行 Agent",
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

  const mainAgents = activeCategory === "main_agent" ? activeGroupItems : agents.filter((agent) => String(agent.agent_category || agent.profile_type || "") === "main_agent");
  const builtinAgents = activeCategory === "builtin_agent" ? activeGroupItems : agents.filter((agent) => String(agent.agent_category || agent.profile_type || "") === "builtin_agent");
  const groupingRows = [
    {
      id: "main_agent",
      title: "主 Agent",
      count: categoryCounts.main_agent ?? mainAgents.length,
      active: activeCategory === "main_agent",
      onClick: () => selectCategory("main_agent"),
    },
    {
      id: "builtin_agent",
      title: "内置 Agent",
      count: categoryCounts.builtin_agent ?? builtinAgents.length,
      active: activeCategory === "builtin_agent",
      onClick: () => selectCategory("builtin_agent"),
    },
    {
      id: "custom_grouped",
      title: "子 Agent 组",
      count: agentGroups.length,
      active: activeCategory === "custom_agent" && customDirectoryMode === "grouped",
      onClick: () => {
        selectCategory("custom_agent");
        selectCustomDirectoryMode("grouped");
      },
    },
    {
      id: "custom_ungrouped",
      title: "未分组",
      count: ungroupedCustomAgents.length,
      active: activeCategory === "custom_agent" && customDirectoryMode === "ungrouped",
      onClick: () => {
        selectCategory("custom_agent");
        selectCustomDirectoryMode("ungrouped");
      },
    },
  ];

  const directoryStatusLabel = activeCategory === "custom_agent" && customDirectoryMode === "grouped"
    ? `分组 ${agentGroups.length}`
    : activeCategory === "custom_agent"
      ? `未分组 ${ungroupedCustomAgents.length}`
      : `${activeGroupItems.length} 项`;

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
        <span>{activeCategory === "custom_agent" && customDirectoryMode === "grouped" ? "Agent 组" : categoryLabels[activeCategory]}</span>
        <small>{directoryStatusLabel} · {activeCategory === "custom_agent" ? "行进入配置" : categoryDescriptions[activeCategory]}</small>
      </div>
      <div className="boundary-list boundary-list--scroll orchestration-practical-list">
        {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
        {activeCategory === "custom_agent" && customDirectoryMode === "grouped" ? (
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
            {!loading && !agentGroups.length ? <div className="boundary-empty">暂无子 Agent 分组。</div> : null}
          </>
        ) : null}
        {activeCategory === "custom_agent" && customDirectoryMode === "ungrouped" ? (
          <>
            {ungroupedCustomAgents.map((agent) => <AgentRow agent={agent} compact key={String(agent.agent_id)} />)}
            <button className="orchestration-subagent-create-row" onClick={startBlankAgentDraft} type="button">
              <Plus size={16} />
              <span>新建子 Agent</span>
            </button>
            {!loading && !ungroupedCustomAgents.length ? <div className="boundary-empty">暂无未分组子 Agent。</div> : null}
          </>
        ) : null}
        {(activeCategory === "custom_agent" ? [] : activeGroupItems).map((agent) => <AgentRow agent={agent} key={String(agent.agent_id)} />)}
        {!loading && (
          activeCategory === "custom_agent"
            ? customDirectoryMode === "grouped"
              ? !agentGroups.length
              : !ungroupedCustomAgents.length
            : !activeGroupItems.length
        ) ? <div className="boundary-empty">当前层级暂无 Agent。</div> : null}
      </div>
      <div className="orchestration-directory-actions orchestration-directory-actions--practical">
        {activeCategory === "custom_agent" && customDirectoryMode === "grouped" ? (
          <>
          <OrchestrationToolbarButton onClick={startBlankGroupDraft} variant="ghost">
            <Network size={14} />
            新建组
          </OrchestrationToolbarButton>
          <OrchestrationToolbarButton
            disabled={!selectedGroupId || saving === "delete"}
            onClick={removeSelectedGroup}
            variant="danger"
          >
            <Trash2 size={14} />
            删除组
          </OrchestrationToolbarButton>
          </>
        ) : null}
        {activeCategory === "custom_agent" && customDirectoryMode !== "ungrouped" ? (
          <OrchestrationToolbarButton onClick={startBlankAgentDraft} variant="ghost">
            <Plus size={14} />
            新建 Agent
          </OrchestrationToolbarButton>
        ) : null}
      </div>
    </aside>
  );
}
