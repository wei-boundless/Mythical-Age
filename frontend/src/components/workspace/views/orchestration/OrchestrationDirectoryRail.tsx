"use client";

import { Loader2, Search } from "lucide-react";

type AgentCategory = "main_agent" | "system_management_agent" | "worker_sub_agent";
type WorkerDirectoryMode = "grouped" | "ungrouped";

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
    system_management_agent: "系统管理 Agent",
    worker_sub_agent: "子 Agent",
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
  workerDirectoryMode,
  selectWorkerDirectoryMode,
  agentGroups,
  selectedGroupId,
  selectSubAgentGroup,
  ungroupedWorkerAgents,
  selectedAgentId,
  selectAgent,
  activeGroupItems,
}: {
  agents: Array<Record<string, unknown>>;
  loading: boolean;
  query: string;
  setQuery: (value: string) => void;
  activeCategory: AgentCategory;
  categoryCounts: Record<string, number>;
  selectCategory: (category: AgentCategory) => void;
  workerDirectoryMode: WorkerDirectoryMode;
  selectWorkerDirectoryMode: (mode: WorkerDirectoryMode) => void;
  agentGroups: Array<{ group_id: string; title: string; member_agent_ids: string[] }>;
  selectedGroupId: string;
  selectSubAgentGroup: (groupId: string) => void;
  ungroupedWorkerAgents: Array<Record<string, unknown>>;
  selectedAgentId: string;
  selectAgent: (agentId: string) => void;
  activeGroupItems: Array<Record<string, unknown>>;
}) {
  const categoryLabels: Record<AgentCategory, string> = {
    main_agent: "主 Agent",
    system_management_agent: "系统管理 Agent",
    worker_sub_agent: "子 Agent",
  };

  return (
    <aside className="boundary-rail orchestration-subagent-rail">
      <div className="boundary-rail__head">
        <strong>Agent 分类</strong>
        <span>{agents.length}</span>
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
          </button>
        ))}
      </div>
      {activeCategory === "worker_sub_agent" ? (
        <div className="orchestration-subagent-mode-strip" aria-label="子 Agent 目录切换">
          <button className={workerDirectoryMode === "grouped" ? "active" : ""} onClick={() => selectWorkerDirectoryMode("grouped")} type="button">
            有组
          </button>
          <button className={workerDirectoryMode === "ungrouped" ? "active" : ""} onClick={() => selectWorkerDirectoryMode("ungrouped")} type="button">
            无组
          </button>
        </div>
      ) : null}
      <div className="boundary-list boundary-list--scroll">
        {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
        {activeCategory === "worker_sub_agent" && workerDirectoryMode === "grouped" ? (
          <>
            <div className="orchestration-list-label">有组子 Agent</div>
            {agentGroups.map((group) => (
              <div className={group.group_id === selectedGroupId ? "orchestration-group-tree orchestration-group-tree--active" : "orchestration-group-tree"} key={group.group_id}>
                <button className="boundary-list-row" onClick={() => selectSubAgentGroup(group.group_id)} type="button">
                  <strong>{group.title}</strong>
                  <span>{group.member_agent_ids.length} 个成员</span>
                </button>
              </div>
            ))}
            {!loading && !agentGroups.length ? <div className="boundary-empty">暂无子 Agent 组。</div> : null}
          </>
        ) : null}
        {activeCategory === "worker_sub_agent" && workerDirectoryMode === "ungrouped" ? (
          <>
            <div className="orchestration-list-label">无组子 Agent</div>
            {ungroupedWorkerAgents.map((agent) => (
              <button
                className={String(agent.agent_id) === selectedAgentId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
                key={String(agent.agent_id)}
                onClick={() => selectAgent(String(agent.agent_id))}
                type="button"
              >
                <strong>{displayName(agent)}</strong>
              </button>
            ))}
            {!loading && !ungroupedWorkerAgents.length ? <div className="boundary-empty">暂无无组子 Agent。</div> : null}
          </>
        ) : null}
        {(activeCategory === "worker_sub_agent" ? [] : activeGroupItems).map((agent) => (
          <button
            className={String(agent.agent_id) === selectedAgentId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
            key={String(agent.agent_id)}
            onClick={() => selectAgent(String(agent.agent_id))}
            type="button"
          >
            <strong>{displayName(agent)}</strong>
          </button>
        ))}
        {!loading && (
          activeCategory === "worker_sub_agent"
            ? workerDirectoryMode === "grouped"
              ? !agentGroups.length
              : !ungroupedWorkerAgents.length
            : !activeGroupItems.length
        ) ? <div className="boundary-empty">当前层级暂无 Agent。</div> : null}
      </div>
    </aside>
  );
}
