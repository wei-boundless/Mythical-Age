import { request } from "./shared";
import type {
  CapabilitySystemCatalog,
  ExternalMCPServerConfig,
  MCPManagementCatalog,
  MCPManagementServer,
} from "./types";

export async function getCapabilitySystemCatalog() {
  return request<CapabilitySystemCatalog>("/capability-system/catalog");
}

export async function refreshCapabilitySystemCatalog() {
  return request<CapabilitySystemCatalog>("/capability-system/catalog/refresh", {
    method: "POST"
  });
}

export async function createCapabilitySystemSkill(payload: {
  name: string;
  title: string;
  description: string;
  content?: string;
}) {
  return request<CapabilitySystemCatalog>("/capability-system/skills", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function saveCapabilitySystemSkill(skillName: string, content: string) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}`, {
    method: "PUT",
    body: JSON.stringify({ content })
  });
}

export async function updateCapabilitySystemSkillPromptView(
  skillName: string,
  payload: {
    title: string;
    capability: string;
    use_when: string;
    output_rule: string;
  }
) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}/prompt-view`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteCapabilitySystemSkill(skillName: string) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}`, {
    method: "DELETE"
  });
}

export async function updateCapabilitySystemTool(toolName: string, payload: { tool_type: string; note?: string; llm_description?: string }) {
  return request<CapabilitySystemCatalog>(`/capability-system/tools/${encodeURIComponent(toolName)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getMCPManagementCatalog() {
  return request<MCPManagementCatalog>("/mcp-system/management/catalog");
}

export async function upsertMCPManagementExternalServer(serverId: string, payload: ExternalMCPServerConfig) {
  return request<MCPManagementCatalog>(`/mcp-system/management/providers/external/servers/${encodeURIComponent(serverId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteMCPManagementExternalServer(serverId: string) {
  return request<MCPManagementCatalog>(`/mcp-system/management/providers/external/servers/${encodeURIComponent(serverId)}`, {
    method: "DELETE"
  });
}

export async function inspectMCPManagementServer(providerId: string, serverId: string) {
  return request<MCPManagementServer>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/inspect`,
    {
      method: "POST"
    }
  );
}

export async function previewMCPManagementTool(
  providerId: string,
  serverId: string,
  toolName: string,
  argumentsPayload: Record<string, unknown>
) {
  return request<Record<string, unknown>>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/preview`,
    {
      method: "POST",
      body: JSON.stringify({ arguments: argumentsPayload })
    }
  );
}

export async function callMCPManagementTool(
  providerId: string,
  serverId: string,
  toolName: string,
  argumentsPayload: Record<string, unknown>
) {
  return request<Record<string, unknown>>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/call`,
    {
      method: "POST",
      body: JSON.stringify({ arguments: argumentsPayload })
    }
  );
}
