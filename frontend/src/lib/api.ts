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
  harness_profile?: string;
  extra_args?: string[];
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

export type ExperimentTurn = {
  turn_id: string;
  index: number;
  scenario: string;
  session_alias: string;
  status: string;
  summary: string;
  problem_node_id?: string;
  problem_node_label?: string;
  artifact_path: string;
  issue_count: number;
  has_trace: boolean;
  has_prompt_manifest: boolean;
  has_memory_trace: boolean;
};

export type SystemGraphOverlayItem = {
  id: string;
  status: "passed" | "failed" | "warning" | "unknown";
  label: string;
  events: string[];
  latency_ms: number | null;
  reason: string;
};

export type SystemGraphOverlay = {
  run_id: string;
  turn_id: string | null;
  mode: "inferred" | "observed";
  status: "passed" | "failed" | "warning" | "unknown";
  summary: string;
  nodes: SystemGraphOverlayItem[];
  edges: SystemGraphOverlayItem[];
  artifacts: Record<string, string>;
  prompt_manifest_id: string | null;
};

export type OrchestrationNodeStatus = "idle" | "visited" | "warning" | "failed" | "success" | "blocked" | "skipped";

export type OrchestrationNode = {
  id: string;
  index: number;
  label: string;
  description: string;
  status: OrchestrationNodeStatus;
  summary: string;
  source_event: string;
  source_module?: string;
  reasons?: string[];
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  refs?: Record<string, unknown>;
};

export type OrchestrationEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
  status: OrchestrationNodeStatus;
  summary: string;
};

export type OrchestrationEvent = {
  index: number;
  event: string;
  node_id: string;
  summary: string;
  ts_ms?: number | null;
  data: Record<string, unknown>;
};

export type OrchestrationSnapshot = {
  source: "live-session" | "test-turn" | "inferred" | "dry-run" | string;
  session_id: string;
  run_id?: string;
  turn_id?: string;
  turn_index?: number;
  execution_mode: string;
  route: string;
  status: "idle" | "running" | "success" | "warning" | "failed" | string;
  summary: string;
  problem_node_id?: string;
  nodes: OrchestrationNode[];
  edges: OrchestrationEdge[];
  events: OrchestrationEvent[];
  artifacts?: Record<string, string>;
  decision_trace?: Record<string, unknown>;
  dry_run?: Record<string, unknown>;
  orchestration_plan?: Record<string, unknown>;
  orchestration_diff?: Record<string, unknown>;
};

export type OrchestrationCatalogSkill = {
  runtime: {
    name: string;
    title: string;
    description: string;
    path: string;
    allowed_tools: string[];
    supported_modalities: string[];
    supported_task_kinds: string[];
    supported_source_kinds: string[];
    capability_tags: string[];
    preferred_route: string;
    forbidden_routes: string[];
    routing_hints: string[];
    examples: string[];
    activation_policy: string;
    context_mode: string;
    route_authority: string;
    reference_paths: string[];
  };
  prompt_view: {
    name: string;
    title: string;
    capability: string;
    use_when: string;
    output_rule: string;
  };
  tool_scope: Record<string, unknown>;
};

export type OrchestrationCatalogTool = {
  name: string;
  module: string;
  contract: Record<string, unknown>;
  resolution_contract: Record<string, unknown>;
  output_contract: Record<string, unknown>;
  projection_contract: Record<string, unknown>;
  capability_tags: string[];
  supported_modalities: string[];
  safety_tags: string[];
  route_hints: string[];
  safe_for_auto_route: boolean;
  runtime_visibility: string;
  prompt_exposure_policy: string;
  resource_exposure_policy: string;
  is_read_only: boolean;
  is_destructive: boolean;
  is_concurrency_safe: boolean;
};

export type OrchestrationCatalog = {
  permission_mode: string;
  supported_permission_modes: string[];
  tool_contract_mode: string;
  orchestration_plan_mode: string;
  supported_orchestration_plan_modes: string[];
  skills: OrchestrationCatalogSkill[];
  tools: OrchestrationCatalogTool[];
};

export type PromptManifestSection = {
  id: string;
  title: string;
  layer: "static" | "session" | "turn" | string;
  source: string;
  model_visible: boolean;
  chars: number;
  preview: string;
  order: number;
};

export type PromptManifest = {
  prompt_id: string;
  session_id: string;
  turn_id: string;
  assembly_order: string[];
  total_chars: number;
  total_sections: number;
  sections: PromptManifestSection[];
  debug_policy: string;
};

export type PromptManifestResponse = {
  status: "available" | "missing_manifest";
  reason: string;
  prompt_manifest: PromptManifest | null;
};

export type MemoryTraceSection = {
  id: string;
  label: string;
  items: string[];
  count: number;
};

export type ExperimentTurnMemoryTrace = {
  run_id: string;
  turn_id: string;
  has_memory_signal: boolean;
  turn_context?: {
    index: number;
    session_alias: string;
    speaker: string;
    user_input: string;
    assistant_output: string;
    status: string;
    failed_checks: string[];
    artifact_path: string;
  };
  summary: string;
  context_management: {
    pressure_level: string;
    strategy: string;
    selected_sections: string[];
    debug_selected_sections: string[];
    dropped_sections: string[];
    token_accounting: Record<string, number>;
  };
  session_memory: {
    section_count: number;
    model_sections: MemoryTraceSection[];
    debug_sections: MemoryTraceSection[];
    active_goal: string;
    flow_state: Record<string, unknown>;
    task_state: Record<string, unknown>;
    context_slots: Record<string, unknown>;
  };
  durable_memory: {
    exact_count: number;
    relevant_count: number;
    exact_matches: Array<Record<string, unknown>>;
    relevant_notes: Array<Record<string, unknown>>;
    model_sections: MemoryTraceSection[];
    debug_sections: MemoryTraceSection[];
  };
  prompt_injection: {
    section_count: number;
    total_chars: number;
    sections: Array<{
      id: string;
      title: string;
      layer: string;
      source: string;
      chars: number;
      preview: string;
      order: number;
    }>;
  };
};

export type ExperimentTurnMemoryTraceResponse = {
  status: "available" | "missing_trace";
  reason: string;
  memory_trace: ExperimentTurnMemoryTrace | null;
};

export type MemoryHeader = {
  note_id: string;
  filename: string;
  memory_type: string;
  memory_class: string;
  title: string;
  description: string;
  status: string;
  confidence: string;
  updated_at: string;
  retrieval_hints: string[];
  eligible_for_injection: boolean;
  canonical_statement: string;
  summary: string;
};

export type MemorySessionInspect = {
  present: boolean;
  preview: string;
  model_preview: string;
  debug_preview: string;
  active_goal: string;
  flow_state: Record<string, unknown>;
  task_state: Record<string, unknown>;
  context_slots: Record<string, unknown>;
  risk: Record<string, unknown>;
  warm_snapshots: Array<Record<string, unknown>>;
  storage: Record<string, unknown>;
  context_management: Record<string, unknown>;
  durable_matches: Record<string, unknown>;
};

export type MemorySessionFile = {
  id: string;
  label: string;
  description: string;
  path: string;
  kind: "json" | "markdown" | string;
  exists: boolean;
  size: number;
  updated_at: number | null;
  preview: string;
};

export type MemorySessionFilesResponse = {
  session_id: string;
  root: string;
  present: boolean;
  existing_count: number;
  missing_count: number;
  files: MemorySessionFile[];
};

export type MemoryOverview = {
  session_id: string;
  query: string;
  durable_memory: {
    total: number;
    active: number;
    injectable: number;
    by_type: Record<string, number>;
    by_class: Record<string, number>;
    headers: MemoryHeader[];
    extraction_runtime: Record<string, unknown>;
  };
  session_memory: MemorySessionInspect | null;
};

export type MemoryRecallPreview = {
  query: string;
  session_id: string;
  intent: {
    intent: string;
    read_mode: string;
    write_mode: string;
    explicit_read_inventory: boolean;
    ignore_memory: boolean;
    preferred_types: string[];
    preferred_memory_classes: string[];
  };
  selection: {
    should_recall: boolean;
    selected_note_ids: string[];
    reason: string;
    confidence: number;
    needs_verification: boolean;
    manifest_only: boolean;
    ignore_memory: boolean;
  };
  selected_headers: MemoryHeader[];
  selected_notes: Array<{
    note_id: string;
    filename: string;
    title: string;
    summary: string;
    canonical_statement: string;
    content_preview: string;
    memory_type: string;
    memory_class: string;
    confidence: string;
    status: string;
    retrieval_hints: string[];
    eligible_for_injection: boolean;
  }>;
  rendered_summary: string;
  context_preview: MemorySessionInspect | null;
};

export type MemoryGovernanceResponse = {
  ok: boolean;
  action: string;
  filename: string;
  merged?: string[];
  deleted_at?: string;
  trash_path?: string;
  header?: MemoryHeader | null;
};

export type DurableMemoryNoteDetail = {
  header: MemoryHeader | null;
  content_preview: string;
  path: string;
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

export async function getMemoryOverview(sessionId?: string, query = "") {
  const params = new URLSearchParams();
  if (sessionId) {
    params.set("session_id", sessionId);
  }
  if (query.trim()) {
    params.set("query", query.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<MemoryOverview>(`/memory/overview${suffix}`);
}

export async function getSessionMemoryFiles(sessionId: string) {
  return request<MemorySessionFilesResponse>(`/memory/session/${encodeURIComponent(sessionId)}/files`);
}

export async function recallMemoryPreview(payload: { query: string; session_id?: string; limit?: number }) {
  return request<MemoryRecallPreview>("/memory/recall-preview", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDurableMemory(payload: {
  title: string;
  canonical_statement: string;
  summary?: string;
  memory_type?: string;
  memory_class?: string;
  retrieval_hints?: string[];
  confidence?: string;
  source_kind?: string;
  source_message_excerpt?: string;
}) {
  return request<MemoryGovernanceResponse>("/memory/durable", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function disableDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/disable`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function activateDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/activate`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function archiveDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function deleteDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    body: JSON.stringify({ reason })
  });
}

export async function getDurableMemoryNote(filename: string) {
  return request<DurableMemoryNoteDetail>(`/memory/durable/${encodeURIComponent(filename)}`);
}

export async function mergeDurableMemories(payload: {
  filenames: string[];
  title: string;
  canonical_statement: string;
  summary?: string;
  reason?: string;
}) {
  return request<MemoryGovernanceResponse>("/memory/durable/merge", {
    method: "POST",
    body: JSON.stringify(payload)
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

export async function listExperimentTurns(runId: string) {
  return request<ExperimentTurn[]>(`/experiments/runs/${encodeURIComponent(runId)}/turns`);
}

export async function getExperimentGraphOverlay(runId: string) {
  return request<SystemGraphOverlay>(`/experiments/runs/${encodeURIComponent(runId)}/graph-overlay`);
}

export async function getExperimentTurnGraphOverlay(runId: string, turnId: string) {
  return request<SystemGraphOverlay>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/graph-overlay`
  );
}

export async function getExperimentTurnPromptManifest(runId: string, turnId: string) {
  return request<PromptManifestResponse>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/prompt-manifest`
  );
}

export async function getExperimentTurnMemoryTrace(runId: string, turnId: string) {
  return request<ExperimentTurnMemoryTraceResponse>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/memory-trace`
  );
}

export async function getExperimentTurnOrchestration(runId: string, turnId: string, artifactPath = "") {
  const params = new URLSearchParams();
  if (artifactPath.trim()) {
    params.set("artifact_path", artifactPath.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<OrchestrationSnapshot>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/orchestration${suffix}`
  );
}

export async function runOrchestrationDryRun(payload: {
  session_id: string;
  message: string;
  ephemeral_system_messages?: string[];
  explicit_subtasks?: Array<Record<string, unknown>>;
}) {
  return request<OrchestrationSnapshot>("/orchestration/dry-run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog");
}

export async function refreshOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog/refresh", {
    method: "POST"
  });
}

export async function setOrchestrationPlanMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/orchestration/plan-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
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
