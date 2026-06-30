import { request } from "./shared";
import type { AgentControlNetworkPayload } from "./types";


export async function getAgentControlNetwork() {
  return request<AgentControlNetworkPayload>("/agent-control-network");
}


export async function getAgentControlNetworkSession(sessionId: string) {
  return request<AgentControlNetworkPayload>(
    `/agent-control-network/session/${encodeURIComponent(sessionId)}`,
  );
}
