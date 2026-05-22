"use client";

import { Loader2, Network, Plus, Search, Trash2 } from "lucide-react";

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
  const builtinCount = agents.filter((agent) => Boolean(agent.builtin)).length;
  const builtinCountByCategory = agents.reduce<Record<string, number>>((acc, agent) => {
    if (!agent.builtin) return acc;
    const category = String(agent.agent_category || agent.profile_type || "custom_agent");
    acc[category] = (acc[category] ?? 0) + 1;
    return acc;
  }, {});

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
      <article className={agentId === selectedAgentId && selectionKind === "agent" ? "orchestration-subagent-card orchestration-subagent-card--active" : "orchestration-subagent-card"}>
        <button className="orchestration-subagent-card__main" onClick={() => selectAgent(agentId)} type="button">
          <strong>{name}</strong>
          <span>{builtin ? "内置来源" : profileId || "子 Agent"}</span>
        </button>
        <button
          className="orchestration-subagent-card__delete"
          disabled={saving === "delete"}
          onClick={() => removeAgentById(agentId, name)}
          type="button"
        >
          <Trash2 size={14} />
        </button>
      </article>
    );
  }

  return (
    <aside className="boundary-rail orchestration-subagent-rail">
      <div className="boundary-rail__head">
        <strong>Agent 装配目录</strong>
        <span>{agents.length} 个 / 内置 {builtinCount}</span>
      </div>
      <div className="boundary-search">
        <Search size={15} />
        <input onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Agent / 职责 / 能力" value={query} />
      </div>
      <div className="orchestration-agent-type-strip" aria-label="Agent 类型快速入口">
        {(Object.keys(categoryLabels) as AgentCategory[]).map((category) => (
          <button className={activeCategory === category ? "active" : ""} key={category} onClick={() => selectCategory(category)} type="button">
            <span>{categoryLabels[category]}</span>
            <b>{categoryCounts[category] ?? 0}</b>
            <small>{categoryDescriptions[category]} · 内置 {builtinCountByCategory[category] ?? 0}</small>
          </button>
        ))}
      </div>
      {activeCategory === "custom_agent" ? (
        <div className="orchestration-subagent-mode-strip" aria-label="子 Agent 目录切换">
          <button className={customDirectoryMode === "grouped" ? "active" : ""} onClick={() => selectCustomDirectoryMode("grouped")} type="button">
            Agent 分组
          </button>
          <button className={customDirectoryMode === "ungrouped" ? "active" : ""} onClick={() => selectCustomDirectoryMode("ungrouped")} type="button">
            未分组
          </button>
        </div>
      ) : null}
      <div className="boundary-list boundary-list--scroll">
        {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
        {activeCategory === "custom_agent" && customDirectoryMode === "grouped" ? (
          <>
            <div className="orchestration-list-label">子 Agent 组</div>
            {agentGroups.map((group) => (
              <div className={group.group_id === selectedGroupId && selectionKind === "group" ? "orchestration-group-tree orchestration-group-tree--active" : "orchestration-group-tree"} key={group.group_id}>
                <button className="boundary-list-row" onClick={() => selectSubAgentGroup(group.group_id)} type="button">
                  <strong>{group.title}</strong>
                  <span>{group.member_agent_ids.length} 个成员</span>
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
            <div className="orchestration-list-label">未分组子 Agent</div>
            {ungroupedCustomAgents.map((agent) => <AgentRow agent={agent} compact key={String(agent.agent_id)} />)}
            <button className="orchestration-subagent-create-card" onClick={startBlankAgentDraft} type="button">
              <Plus size={16} />
              <span>新增子 Agent</span>
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
      {activeCategory === "custom_agent" && customDirectoryMode === "grouped" ? (
        <div className="orchestration-directory-actions">
          <OrchestrationToolbarButton onClick={startBlankGroupDraft} variant="ghost">
            <Network size={14} />
            新建子 Agent 组
          </OrchestrationToolbarButton>
          <OrchestrationToolbarButton
            disabled={!selectedGroupId || saving === "delete"}
            onClick={removeSelectedGroup}
            variant="danger"
          >
            <Trash2 size={14} />
            删除当前组
          </OrchestrationToolbarButton>
        </div>
      ) : null}
    </aside>
  );
}
