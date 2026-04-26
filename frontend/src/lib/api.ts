export type ToolCall = {
  tool: string;
  input: string;
  output: string;
};

export type RetrievalResult = {
  text: string;
  score: number;
  source: string;
};

export type SessionSummary = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
};

export type SessionHistory = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  compressed_context?: string;
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    tool_calls?: ToolCall[];
  }>;
};

export type ExperimentProfile = {
  id: string;
  title: string;
  description: string;
  command_preview: string;
  risk: string;
  estimated_duration: string;
  requires_confirmation: boolean;
};

export type ExperimentRun = {
  run_id: string;
  profile: string;
  status: string;
  command_preview: string;
  output_dir: string;
  log_path: string;
  log_tail?: string;
  started_at: number;
  ended_at: number;
  duration_ms: number;
  returncode: number | null;
  pid: number | null;
  summary: {
    total: number;
    passed: number;
    failed: number;
    first_failure: string;
  };
};

export type ExperimentArtifacts = {
  run_result: Record<string, unknown>;
  issues: Array<Record<string, unknown>>;
  report: string;
  trace_tail: string;
  summary: ExperimentRun["summary"];
};

export type StreamHandlers = {
  onEvent: (event: string, data: Record<string, unknown>) => void;
};

function getApiBase() {
  const explicitBase = process.env.NEXT_PUBLIC_API_BASE?.trim();
  if (explicitBase) {
    return explicitBase.replace(/\/$/, "");
  }

  if (typeof window === "undefined") {
    return "http://127.0.0.1:8002/api";
  }

  return "http://127.0.0.1:8002/api";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function listSessions() {
  return request<SessionSummary[]>("/sessions");
}

export async function createSession(title = "New Session") {
  return request<SessionSummary>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title })
  });
}

export async function renameSession(sessionId: string, title: string) {
  return request<SessionSummary>(`/sessions/${sessionId}`, {
    method: "PUT",
    body: JSON.stringify({ title })
  });
}

export async function deleteSession(sessionId: string) {
  return request<{ ok: boolean }>(`/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export async function getSessionHistory(sessionId: string) {
  return request<SessionHistory>(`/sessions/${sessionId}/history`);
}

export async function getSessionTokens(sessionId: string) {
  return request<{
    system_tokens: number;
    message_tokens: number;
    total_tokens: number;
    raw_history_tokens: number;
    history_tokens: number;
    history_budget_tokens: number;
    history_remaining_tokens: number;
    history_usage_ratio: number;
    history_remaining_ratio: number;
    history_pressure_level: string;
    history_compaction_strategy: string;
    history_did_compact: boolean;
    history_did_microcompact: boolean;
    history_did_full_compact: boolean;
  }>(`/tokens/session/${sessionId}`);
}

export async function listSkills() {
  return request<Array<{ name: string; title: string; description: string; path: string }>>(
    "/skills"
  );
}

export async function loadFile(path: string) {
  return request<{ path: string; content: string }>(
    `/files?path=${encodeURIComponent(path)}`
  );
}

export async function saveFile(path: string, content: string) {
  return request<{ ok: boolean; path: string }>("/files", {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function getRagMode() {
  return request<{ enabled: boolean }>("/config/rag-mode");
}

export async function setRagMode(enabled: boolean) {
  return request<{ enabled: boolean }>("/config/rag-mode", {
    method: "PUT",
    body: JSON.stringify({ enabled })
  });
}

export async function getPermissionMode() {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode");
}

export async function setPermissionMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function listExperimentProfiles() {
  return request<ExperimentProfile[]>("/experiments/profiles");
}

export async function listExperimentRuns(limit = 20) {
  return request<ExperimentRun[]>(`/experiments/runs?limit=${limit}`);
}

export async function startExperimentRun(profile: string) {
  return request<ExperimentRun>("/experiments/runs", {
    method: "POST",
    body: JSON.stringify({ profile })
  });
}

export async function getExperimentRun(runId: string) {
  return request<ExperimentRun>(`/experiments/runs/${encodeURIComponent(runId)}`);
}

export async function getExperimentArtifacts(runId: string) {
  return request<ExperimentArtifacts>(`/experiments/runs/${encodeURIComponent(runId)}/artifacts`);
}

export async function cancelExperimentRun(runId: string) {
  return request<ExperimentRun>(`/experiments/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST"
  });
}

export async function streamChat(
  payload: {
    message: string;
    session_id: string;
    ephemeral_system_messages?: string[];
  },
  handlers: StreamHandlers
) {
  const response = await fetch(`${getApiBase()}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      ...payload,
      stream: true
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlock = (block: string) => {
    const lines = block.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (!dataLines.length) {
      return;
    }

    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    handlers.onEvent(event, data);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      flushBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      if (buffer.trim()) {
        flushBlock(buffer);
      }
      break;
    }
  }
}
