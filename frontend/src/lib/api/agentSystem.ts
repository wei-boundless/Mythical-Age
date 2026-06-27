import { request } from "./shared";
import type {
  AgentSystemAgentGroupUpsertPayload,
  AgentSystemAgentRuntimeCatalog,
  AgentSystemAgentRuntimeProfileUpsertPayload,
  AgentSystemAgentUpsertPayload,
  AgentSystemCapabilityItem,
  AgentSystemCatalog,
  AgentSystemRuntimeOptionsPayload,
  HarnessTurnSnapshot,
  RuntimeResourceInventory,
} from "./types";

export async function runAgentSystemDryRun(payload: {
  session_id: string;
  message: string;
  explicit_subtasks?: Array<Record<string, unknown>>;
}) {
  return request<HarnessTurnSnapshot>("/agent-system/dry-run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getAgentSystemCatalog() {
  return request<AgentSystemCatalog>("/agent-system/catalog");
}

export async function refreshAgentSystemCatalog() {
  return request<AgentSystemCatalog>("/agent-system/catalog/refresh", {
    method: "POST"
  });
}

export async function setAgentSystemPlanMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/agent-system/plan-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function getAgentSystemAgents(options: { includeOptions?: boolean } = {}) {
  const includeOptions = options.includeOptions ?? true;
  const suffix = includeOptions ? "" : "?include_options=false";
  return request<AgentSystemAgentRuntimeCatalog>(`/agent-system/agents${suffix}`);
}

export async function getAgentSystemRuntimeOptions() {
  return request<AgentSystemRuntimeOptionsPayload>("/agent-system/runtime-options");
}

export async function getAgentSystemCapabilityItems() {
  return request<{ authority: string; capability_items: AgentSystemCapabilityItem[] }>("/agent-system/capability-items");
}

export async function getNextAgentSystemWorkerAgentId() {
  return request<{ authority: string; agent_id: string }>("/agent-system/agents/next-worker-id");
}

export async function upsertAgentSystemAgent(agentId: string, payload: AgentSystemAgentUpsertPayload) {
  return request<AgentSystemAgentRuntimeCatalog>(`/agent-system/agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteAgentSystemAgent(agentId: string) {
  return request<AgentSystemAgentRuntimeCatalog>(`/agent-system/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE"
  });
}

export async function upsertAgentSystemAgentGroup(groupId: string, payload: AgentSystemAgentGroupUpsertPayload) {
  return request<AgentSystemAgentRuntimeCatalog>(`/agent-system/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteAgentSystemAgentGroup(groupId: string) {
  return request<AgentSystemAgentRuntimeCatalog>(`/agent-system/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "DELETE"
  });
}

export async function updateAgentSystemAgentRuntimeProfile(
  agentId: string,
  payload: AgentSystemAgentRuntimeProfileUpsertPayload
) {
  return request<AgentSystemAgentRuntimeCatalog>(
    `/agent-system/agents/${encodeURIComponent(agentId)}/runtime-profile`,
    {
      method: "PUT",
      body: JSON.stringify(payload)
    }
  );
}

export async function getAgentSystemResourceInventory() {
  return request<RuntimeResourceInventory>("/agent-system/resource-inventory");
}


