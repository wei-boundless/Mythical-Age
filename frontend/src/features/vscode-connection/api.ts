import { apiRequest } from "@/lib/api/client";

import type { OpenSessionProjectInVSCodeResponse, VSCodeConnectionStatus } from "./types";

export async function getVSCodeConnectionStatus(sessionId: string) {
  return apiRequest<VSCodeConnectionStatus>(`/vscode/sessions/${encodeURIComponent(sessionId)}/status`);
}

export async function openSessionProjectInVSCode(sessionId: string) {
  return apiRequest<OpenSessionProjectInVSCodeResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/project-binding/open-vscode`,
    { method: "POST" },
  );
}
