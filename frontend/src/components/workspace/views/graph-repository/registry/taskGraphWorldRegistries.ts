import type { OrchestrationAgentRuntimeCatalog, TaskGraphNodeRecord } from "@/lib/api";

export type AgentWorldRegistration = {
  agent_id: string;
  displayName: string;
  description?: string;
  category: "writer" | "reviewer" | "planner" | "tool_operator" | "custom";
  runtimeProfileRef?: string;
  toolPolicyRef?: string;
  resourceRefs?: string[];
  defaultNodePatch: Partial<TaskGraphNodeRecord>;
  visual: {
    icon: string;
    tone: "agent" | "reviewer" | "planner" | "operator" | "custom";
  };
};

export type ResourceWorldRegistration = {
  resource_id: string;
  displayName: string;
  kind: "file_space" | "memory_repository" | "artifact_repository" | "mcp_resource" | "tool_provider";
  description?: string;
  defaultNodePatch?: Partial<TaskGraphNodeRecord>;
  allowedFileRoles?: string[];
  visual: {
    icon: string;
    tone: "file" | "memory" | "artifact" | "external" | "tool";
  };
};

export function agentWorldRegistrationsFromCatalog(catalog: OrchestrationAgentRuntimeCatalog | null | undefined): AgentWorldRegistration[] {
  const agents = catalog?.agents ?? [];
  if (!agents.length) return defaultAgentWorldRegistrations;
  return agents.map((agent, index) => {
    const agentId = String(agent.agent_id ?? agent.id ?? `agent.catalog.${index + 1}`).trim();
    const title = String(agent.title ?? agent.display_name ?? agent.name ?? agentId).trim();
    const role = String(agent.role ?? agent.category ?? "custom").trim();
    const profileId = String(agent.runtime_profile?.agent_profile_id ?? "").trim();
    const category = agentCategory(role);
    return {
      agent_id: agentId,
      displayName: title || agentId,
      description: String(agent.description ?? agent.summary ?? "").trim(),
      category,
      runtimeProfileRef: profileId || undefined,
      defaultNodePatch: {
        node_type: "agent",
        title: title || "Agent",
        agent_id: agentId,
        node_config_id: profileId || undefined,
        role: category,
        execution_mode: "sync",
      },
      visual: {
        icon: category === "reviewer" ? "badge-check" : category === "planner" ? "list-tree" : category === "tool_operator" ? "wrench" : "bot",
        tone: category === "reviewer" ? "reviewer" : category === "planner" ? "planner" : category === "tool_operator" ? "operator" : "agent",
      },
    };
  });
}

export const defaultAgentWorldRegistrations: AgentWorldRegistration[] = [
  {
    agent_id: "agent.custom.main",
    displayName: "自由主 agent",
    description: "默认可放到 (0,0) 的主 agent，只是 home 坐标锚点，不拥有隐式调度权。",
    category: "custom",
    defaultNodePatch: {
      node_type: "agent",
      title: "自由主 agent",
      agent_id: "agent.custom.main",
      role: "custom",
      execution_mode: "sync",
    },
    visual: { icon: "bot", tone: "agent" },
  },
  {
    agent_id: "agent.custom.reviewer",
    displayName: "审核 agent",
    description: "用于质量裁决、问题指出和阶段放行。",
    category: "reviewer",
    defaultNodePatch: {
      node_type: "agent",
      title: "审核 agent",
      agent_id: "agent.custom.reviewer",
      role: "reviewer",
      execution_mode: "sync",
    },
    visual: { icon: "badge-check", tone: "reviewer" },
  },
  {
    agent_id: "agent.custom.planner",
    displayName: "规划 agent",
    description: "用于任务拆解、流程规划和结构化交接。",
    category: "planner",
    defaultNodePatch: {
      node_type: "agent",
      title: "规划 agent",
      agent_id: "agent.custom.planner",
      role: "planner",
      execution_mode: "sync",
    },
    visual: { icon: "list-tree", tone: "planner" },
  },
];

export const defaultResourceWorldRegistrations: ResourceWorldRegistration[] = [
  {
    resource_id: "resource.file_space",
    displayName: "实例文件空间",
    kind: "file_space",
    description: "图实例拥有的通用文件空间，由模板文件角色决定结构。",
    defaultNodePatch: {
      node_type: "artifact",
      title: "实例文件空间",
      role: "file_space",
      execution_mode: "sync",
    },
    visual: { icon: "folder-tree", tone: "file" },
  },
  {
    resource_id: "resource.memory_repository",
    displayName: "记忆仓库",
    kind: "memory_repository",
    description: "显式连接后才能向 agent 提供上下文。",
    defaultNodePatch: {
      node_type: "memory",
      title: "记忆仓库",
      role: "memory_repository",
      execution_mode: "sync",
    },
    visual: { icon: "database", tone: "memory" },
  },
  {
    resource_id: "resource.artifact_repository",
    displayName: "产物仓库",
    kind: "artifact_repository",
    description: "保存节点输出、审查证据和最终产物引用。",
    defaultNodePatch: {
      node_type: "artifact",
      title: "产物仓库",
      role: "artifact_repository",
      execution_mode: "sync",
    },
    visual: { icon: "archive", tone: "artifact" },
  },
];

function agentCategory(value: string): AgentWorldRegistration["category"] {
  if (/review|audit|审核/i.test(value)) return "reviewer";
  if (/plan|planner|规划/i.test(value)) return "planner";
  if (/tool|operator|工具/i.test(value)) return "tool_operator";
  if (/writer|writing|写作/i.test(value)) return "writer";
  return "custom";
}
