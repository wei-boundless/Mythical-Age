"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getAgentSystemAgents } from "@/lib/api/agentSystem";
import type { AgentSystemAgentRuntimeCatalog } from "@/lib/api/types";
import { useAppStore } from "@/lib/store";
import type { ActiveMainAgentSelection } from "@/lib/store/types";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

type CatalogAgent = AgentSystemAgentRuntimeCatalog["agents"][number];

const FALLBACK_MAIN_AGENTS: ActiveMainAgentSelection[] = [
  {
    agent_id: "agent:0",
    agent_profile_id: "main_interactive_agent",
    agent_name: "通用主 Agent",
    main_agent_kind: "general",
    default_task_environment_id: "env.general.workspace",
    default_task_environment_label: "通用工作区",
    source: "system_fallback",
  },
  {
    agent_id: "agent:main_coding",
    agent_profile_id: "main_coding_agent",
    agent_name: "编码主 Agent",
    main_agent_kind: "coding",
    default_task_environment_id: "env.coding.vibe_workspace",
    default_task_environment_label: "Vibe 编码工作区",
    source: "system_fallback",
  },
  {
    agent_id: "agent:main_office",
    agent_profile_id: "main_office_agent",
    agent_name: "办公主 Agent",
    main_agent_kind: "office",
    default_task_environment_id: "env.office.file_search",
    default_task_environment_label: "轻量办公文件检索",
    source: "system_fallback",
  },
];

function text(value: unknown) {
  return String(value || "").trim();
}

function metadataOf(value: unknown) {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function mainAgentOption(agent: CatalogAgent): ActiveMainAgentSelection | null {
  const metadata = metadataOf(agent.metadata);
  const runtimeProfile = metadataOf(agent.runtime_profile);
  const profileMetadata = metadataOf(runtimeProfile.metadata);
  const agentCategory = text(agent.agent_category || agent.profile_type);
  const mainAgentKind = text(metadata.main_agent_kind || profileMetadata.main_agent_kind);
  if (agentCategory !== "main_agent" && !mainAgentKind) {
    return null;
  }
  const agentId = text(agent.agent_id);
  const profileId = text(runtimeProfile.agent_profile_id);
  if (!agentId || !profileId) {
    return null;
  }
  const environmentId = text(
    metadata.default_task_environment_id
    || profileMetadata.default_task_environment_id
    || metadata.task_environment_id
    || profileMetadata.task_environment_id
  );
  const agentName = text(agent.agent_name || agent.display_name || agentId);
  return {
    agent_id: agentId,
    agent_profile_id: profileId,
    agent_name: agentName,
    main_agent_kind: mainAgentKind || "main",
    default_task_environment_id: environmentId || "env.general.workspace",
    default_task_environment_label: taskEnvironmentDisplayName(environmentId),
    source: "agent_system_agent_catalog",
  };
}

function uniqueOptions(options: ActiveMainAgentSelection[]) {
  const seen = new Set<string>();
  const result: ActiveMainAgentSelection[] = [];
  for (const option of options) {
    const key = text(option.agent_id);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(option);
  }
  return result;
}

function optionSortKey(option: ActiveMainAgentSelection) {
  switch (option.main_agent_kind) {
    case "general":
      return 0;
    case "coding":
      return 1;
    case "office":
      return 2;
    default:
      return 10;
  }
}

export function WorkspaceModeSwitcher({
  ariaLabel = "切换当前主 Agent",
  className = "",
}: {
  ariaLabel?: string;
  className?: string;
}) {
  const {
    activeMainAgent,
    setActiveMainAgent,
  } = useAppStore();
  const [catalog, setCatalog] = useState<AgentSystemAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getAgentSystemAgents({ includeOptions: false })
      .then((payload) => {
        if (!cancelled) {
          setCatalog(payload);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "主 Agent 目录读取失败。");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const options = useMemo(() => {
    const catalogOptions = uniqueOptions(
      (catalog?.agents || [])
        .map(mainAgentOption)
        .filter((item): item is ActiveMainAgentSelection => Boolean(item))
    ).sort((left, right) => optionSortKey(left) - optionSortKey(right));
    return catalogOptions.length ? catalogOptions : FALLBACK_MAIN_AGENTS;
  }, [catalog]);

  const activeAgentId = text(activeMainAgent.agent_id) || "agent:0";
  const selectedValue = options.some((option) => option.agent_id === activeAgentId)
    ? activeAgentId
    : options[0]?.agent_id || activeAgentId;
  const selected = options.find((option) => option.agent_id === selectedValue) || activeMainAgent;
  const title = error
    ? `${error}；正在使用内置主 Agent 列表`
    : `${selected.agent_name} · 默认环境 ${taskEnvironmentDisplayName(selected.default_task_environment_id, selected.default_task_environment_label)}`;

  return (
    <label
      className={["workbench-mode-select", className].filter(Boolean).join(" ")}
      aria-label={ariaLabel}
      title={title}
    >
      <select
        disabled={loading && !options.length}
        value={selectedValue}
        onChange={(event) => {
          const option = options.find((item) => item.agent_id === event.target.value);
          if (option) void setActiveMainAgent(option);
        }}
      >
        {options.map((option) => (
          <option key={option.agent_id} value={option.agent_id}>
            {option.agent_name}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={14} />
    </label>
  );
}

