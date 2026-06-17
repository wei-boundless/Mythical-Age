import { getApiBase } from "./client";
import { delay, request, sessionScopeQuery } from "./shared";
import type {
  AcceptanceRule,
  AgentTaskCarryingProfile,
  AgentTaskConnectionProfile,
  ArtifactRepositoryOverview,
  ArtifactRepositoryRecord,
  ArtifactRequirement,
  CapabilityEndpoint,
  CapabilitySystemAgentCatalog,
  CapabilitySystemCatalog,
  CapabilityUnit,
  ChatAttachment,
  ChatRun,
  ChatStreamCursor,
  CodeEnvironmentDiagnostic,
  CodeEnvironmentGitStatus,
  CodeEnvironmentStatus,
  CodeEnvironmentTreeNode,
  CodeEnvironmentWorkspaceTree,
  ComposableUnitSpec,
  ContextBudgetConfig,
  ContextBudgetPreset,
  ContextVisibilityPolicy,
  ContractCompileIssue,
  ContractField,
  ContractSpec,
  ContractSpecUpsertPayload,
  ContractValidationIssue,
  ConversationActiveEnvironment,
  ConversationEntryPolicy,
  ConversationEntryPolicyUpsertPayload,
  ConversationState,
  DurableMemoryNoteDetail,
  EngagementAssignee,
  EngagementEventRecord,
  EngagementExecutionStrategy,
  EngagementPlanDetailResponse,
  EngagementPlanListResponse,
  EngagementPlanUpsertPayload,
  EngagementRunCloseoutSyncResult,
  EngagementRunDetailResponse,
  EngagementRunListResponse,
  EngagementRunRecord,
  EngagementRuntimeProfile,
  EngagementStartPayload,
  EngagementStartResult,
  ExperimentTurnMemoryTrace,
  ExperimentTurnMemoryTraceResponse,
  ExternalMCPServerConfig,
  FailurePolicy,
  FileChangeRecord,
  FormalMemoryOverview,
  FormalMemoryReadLog,
  FormalMemoryRecord,
  FormalMemoryRepository,
  FormalMemoryVersion,
  GraphHarnessConfigPayload,
  GraphModuleExpansionPlanSpec,
  GraphModuleExpansionSpec,
  GraphRunBackgroundSubmitResult,
  GraphRunControlResult,
  GraphRunDispatchReadyResult,
  GraphRunMonitorView,
  GraphRunUntilIdleResult,
  GraphSchedulerViewPayload,
  GraphTaskDefinitionList,
  GraphTaskDefinitionSummary,
  GraphTaskInstanceArtifacts,
  GraphTaskInstanceCreateResult,
  GraphTaskInstanceDetail,
  GraphTaskInstanceFileReadResult,
  GraphTaskInstanceFileTree,
  GraphTaskInstanceFileWriteResult,
  GraphTaskInstanceHumanControls,
  GraphTaskInstanceList,
  GraphTaskInstanceMonitor,
  GraphTaskInstanceRunStartResult,
  GraphTaskInstanceSummary,
  HandoffPolicy,
  HarnessSessionLiveMonitor,
  HarnessSessionTaskRuns,
  HarnessTaskRunLiveMonitor,
  HarnessTaskRunSummary,
  HarnessTaskRunTrace,
  HarnessTraceEvent,
  HarnessTurnRunTrace,
  HealthAgentConversationMessage,
  HealthAgentConversationSession,
  HealthAgentRun,
  HealthAgentRunPreview,
  HealthAgentRunStart,
  HealthCommandResponse,
  HealthEfficiency,
  HealthIssue,
  HealthManagementCommand,
  HealthManagementReceipt,
  HealthMonitorGovernance,
  HealthProblemNode,
  HealthRecommendation,
  HealthReport,
  HealthRiskEvent,
  HealthSystemOverview,
  HealthTaskRecord,
  HealthTaskRecordMaintenance,
  HealthTaskRecordPruneResult,
  HealthTokenUsage,
  HealthTraceReport,
  HumanEdgeControlView,
  HumanEdgeDecisionKind,
  HumanEdgeDecisionSubmitRequest,
  HumanEdgeDecisionSubmitResult,
  HumanGatePolicy,
  ImageAssetConfig,
  LatestChatRunResult,
  MCPManagementCatalog,
  MCPManagementServer,
  MCPManagementTool,
  MemoryGovernanceResponse,
  MemoryHeader,
  MemoryNamespaceScope,
  MemoryOverview,
  MemoryRecallPreview,
  MemorySessionFile,
  MemorySessionFilesResponse,
  MemorySessionInspect,
  MemoryTraceSection,
  ModelCredentialRef,
  ModelProviderCatalog,
  ModelProviderConfig,
  ModelProviderOption,
  OperationBindingGraph,
  OperationDescriptor,
  OperationMCP,
  OperationSkill,
  OperationTool,
  OperationWorker,
  OrchestrationAgentGroup,
  OrchestrationAgentGroupUpsertPayload,
  OrchestrationAgentModelProfile,
  OrchestrationAgentRuntimeCatalog,
  OrchestrationAgentRuntimeProfile,
  OrchestrationAgentRuntimeProfileUpsertPayload,
  OrchestrationAgentUpsertPayload,
  OrchestrationCapabilityItem,
  OrchestrationCatalog,
  OrchestrationCatalogSkill,
  OrchestrationCatalogTool,
  OrchestrationEdge,
  OrchestrationEvent,
  OrchestrationNode,
  OrchestrationNodeStatus,
  OrchestrationOption,
  OrchestrationRuntimeOptionsPayload,
  OrchestrationSnapshot,
  OrchestrationSubagentPolicy,
  PersonalitySelection,
  PersonalitySelectorCatalog,
  PersonalitySelectorDimension,
  PersonalitySelectorOption,
  PiSidecarCommandResponse,
  PiSidecarLifecycleResponse,
  PiSidecarStatus,
  ProjectFilePayload,
  ProjectFileTreePayload,
  ProjectInstance,
  ProjectInstructionManagement,
  ProjectInstructionSource,
  ProjectLibraryManifest,
  ProjectLibraryPayload,
  ProjectLibraryRepository,
  ProjectLifecycleActionSpec,
  ProjectLifecycleActionsPayload,
  ProjectLifecyclePreviewPayload,
  ProjectLifecycleRunPayload,
  ProjectRepositoriesPayload,
  ProjectRepositoryBinding,
  ProjectRuntimeStatusView,
  ProjectTreeNode,
  ProjectWorkspaceSummary,
  ProjectionSlice,
  PromptManifest,
  PromptManifestResponse,
  PromptManifestSection,
  PublicChatTimelineDelta,
  PublicChatTimelineItem,
  PublicProjectionFrame,
  PublicTodoItem,
  RegisteredEngagementPlan,
  RetrievalResult,
  RunMonitorEventPayload,
  RuntimeApprovalResolution,
  RuntimeConfigConsole,
  RuntimeConfigField,
  RuntimeConfigGroup,
  RuntimeContextSection,
  RuntimeLogGap,
  RuntimeLogScope,
  RuntimeLogStreamPayload,
  RuntimeMonitorActionPayload,
  RuntimeMonitorActionResult,
  RuntimeMonitorEnvelope,
  RuntimeMonitorManagement,
  RuntimeMonitorSignal,
  RuntimeMonitorSignalAction,
  RuntimeRequirement,
  RuntimeResourceInventory,
  RuntimeResourceInventoryItem,
  SessionContinuationProjection,
  SessionContinuationRecord,
  SessionHistory,
  SessionProjectBinding,
  SessionRuntimeAttachment,
  SessionScope,
  SessionSummary,
  SessionTaskBinding,
  SessionTaskSummary,
  SessionTimeline,
  SessionTruncateResponse,
  SpecificTaskRecord,
  StreamHandlers,
  StreamResult,
  TaskAgentConnectionOverview,
  TaskAssignmentUpsertPayload,
  TaskCommunicationProtocol,
  TaskConnectionDiagnosticIssue,
  TaskContractDescriptor,
  TaskDomainRecord,
  TaskDomainUpsertPayload,
  TaskEnvironmentCatalog,
  TaskEnvironmentGroupUpsertPayload,
  TaskEnvironmentKindTemplate,
  TaskEnvironmentKindTemplateUpsertPayload,
  TaskEnvironmentSessionResolvePayload,
  TaskEnvironmentSessionResolveResponse,
  TaskEnvironmentTasksPayload,
  TaskEnvironmentUpsertPayload,
  TaskExecutionPolicy,
  TaskExecutionPolicyUpsertPayload,
  TaskFlowContractBinding,
  TaskFlowContractBindingUpsertPayload,
  TaskGraphBatchLifecycleView,
  TaskGraphContractPreview,
  TaskGraphDraftTopologySpec,
  TaskGraphEdgeRecord,
  TaskGraphLoopPlanEdgePreview,
  TaskGraphLoopPlanFramePreview,
  TaskGraphLoopPlanPreview,
  TaskGraphMemoryProtocol,
  TaskGraphMemoryProtocolCollection,
  TaskGraphMemoryProtocolEdge,
  TaskGraphMemoryProtocolRepository,
  TaskGraphNodeRecord,
  TaskGraphRecord,
  TaskGraphRunStartResult,
  TaskGraphRuntimeIsolationSpec,
  TaskGraphStandardEdgeSpec,
  TaskGraphStandardIssue,
  TaskGraphStandardNodeSpec,
  TaskGraphStandardResourceSpec,
  TaskGraphStandardTimelineSpec,
  TaskGraphStandardView,
  TaskGraphStandardViewUpsertPayload,
  TaskGraphUpsertPayload,
  TaskNodeConfigurationSpec,
  TaskNodeConfigurationUpsertPayload,
  TaskSystemAgentUpsertPayload,
  TaskSystemFlowUpsertPayload,
  TaskSystemNextIds,
  TaskSystemOverview,
  TaskWorkflowCatalog,
  TaskWorkflowRecord,
  TaskWorkflowUpsertPayload,
  ToolCall,
  ToolPackageDefinition,
  ToolPackageSelection,
  TurnEnvironmentSnapshot,
  UnitInterfaceSpec,
  UnitPortEdgeSpec,
  UnitPortSpec,
  VerificationRun,
  WorkbenchCurrentSessionPayload,
  WorkbenchSessionRef,
  WorkspaceContext,
  WritingAssetCategory,
  WritingChapterAction,
  WritingChapterActionRequest,
  WritingChapterActionSubmitResult,
  WritingChapterIndexItem,
  WritingGraphInstanceDesk,
} from "./types";

const TURN_COMPLETED_EVENT = "turn_completed";
const TERMINAL_STREAM_EVENTS = new Set([TURN_COMPLETED_EVENT]);
const MAX_STREAM_BUFFER_CHARS = 1_000_000;
const CHAT_STREAM_RECONNECT_INITIAL_DELAY_MS = 500;
const CHAT_STREAM_RECONNECT_MAX_DELAY_MS = 30_000;
const CHAT_STREAM_CONSUME_BURST_EVENT_LIMIT = 64;
const CHAT_STREAM_CONSUME_BURST_TIME_MS = 12;

type ChatStreamError = Error & {
  status?: number;
  reconnectable?: boolean;
};

function nonReconnectableChatStreamError(message: string, status?: number): ChatStreamError {
  const error = new Error(message) as ChatStreamError;
  error.name = "ChatStreamProtocolError";
  error.reconnectable = false;
  if (status !== undefined) {
    error.status = status;
  }
  return error;
}

function chatStreamErrorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || fallback;
}

function isReconnectableChatStreamTransportError(error: unknown) {
  if (error instanceof TypeError) {
    return true;
  }
  if (!error || typeof error !== "object") {
    return false;
  }
  const record = error as { name?: unknown; message?: unknown; reconnectable?: unknown };
  if (record.reconnectable === false) {
    return false;
  }
  const name = String(record.name ?? "");
  const message = String(record.message ?? "");
  return name === "AbortError"
    || name === "TimeoutError"
    || name === "NetworkError"
    || name === "RequestTimeoutError"
    || message.includes("Failed to fetch")
    || message.includes("NetworkError")
    || message.includes("Load failed")
    || message.includes("The network connection was lost");
}

function findSseBoundary(buffer: string): { index: number; length: number } | null {
  const boundaries = [
    { index: buffer.indexOf("\n\n"), length: 2 },
    { index: buffer.indexOf("\r\n\r\n"), length: 4 },
    { index: buffer.indexOf("\r\r"), length: 2 },
  ].filter((item) => item.index >= 0);
  if (!boundaries.length) {
    return null;
  }
  return boundaries.sort((left, right) => left.index - right.index)[0];
}

function chatStreamCursorKey(sessionId: string) {
  return `chat.stream.cursor.${sessionId}`;
}

function browserStorage() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readChatStreamCursor(sessionId: string): ChatStreamCursor | null {
  const storage = browserStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(chatStreamCursorKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChatStreamCursor>;
    const streamRunId = String(parsed.streamRunId || "").trim();
    const eventLogId = String(parsed.eventLogId || "").trim();
    const lastEventOffset = Number(parsed.lastEventOffset ?? -1);
    const lastEventId = String(parsed.lastEventId || "").trim();
    if (!streamRunId || !eventLogId || !Number.isFinite(lastEventOffset)) {
      return null;
    }
    return { streamRunId, eventLogId, lastEventOffset, lastEventId };
  } catch {
    return null;
  }
}

export function saveChatStreamCursor(sessionId: string, cursor: ChatStreamCursor) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.setItem(chatStreamCursorKey(sessionId), JSON.stringify(cursor));
  } catch {
    // Storage can be unavailable in private or locked-down browser contexts.
  }
}

export function clearChatStreamCursor(sessionId: string) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.removeItem(chatStreamCursorKey(sessionId));
  } catch {
    // Storage cleanup is best-effort; the backend run remains authoritative.
  }
}

export type ChatRunCreatePayload = {
  message: string;
  session_id: string;
  session_scope?: Partial<SessionScope>;
  environment_binding?: Record<string, unknown>;
  runtime_contract?: Record<string, unknown>;
  model_selection?: Record<string, unknown>;
  image_generation?: Record<string, unknown>;
  attachments?: ChatAttachment[];
  permission_mode?: string;
  expected_active_turn_id?: string;
  active_turn_input_policy?: string;
  editor_context?: Record<string, unknown>;
};

export type QueuedChatInput = {
  queue_item_id: string;
  session_id: string;
  client_message_id: string;
  content: string;
  input_policy: "auto" | "steer";
  status: "queued" | "dispatching" | "dispatched" | "failed" | "canceled";
  created_at: number;
  updated_at: number;
  attachments?: ChatAttachment[];
  session_scope?: Record<string, unknown>;
  environment_binding?: Record<string, unknown>;
  runtime_contract?: Record<string, unknown>;
  explicit_subtasks?: Record<string, unknown>[];
  model_selection?: Record<string, unknown>;
  permission_mode?: string;
  expected_active_turn_id?: string;
  task_run_id?: string;
  editor_context?: Record<string, unknown>;
  dispatch_stream_run_id?: string;
  failure_reason?: string;
  authority?: string;
};

export type QueuedChatInputPayload = {
  message: string;
  client_message_id?: string;
  session_scope?: Partial<SessionScope>;
  environment_binding?: Record<string, unknown>;
  runtime_contract?: Record<string, unknown>;
  explicit_subtasks?: Record<string, unknown>[];
  model_selection?: Record<string, unknown>;
  attachments?: ChatAttachment[];
  permission_mode?: string;
  editor_context?: Record<string, unknown>;
};

export type QueuedChatInputResponse = {
  session_id: string;
  item: QueuedChatInput;
  items: QueuedChatInput[];
  authority: string;
};

export async function uploadChatAttachment(sessionId: string, file: File) {
  const formData = new FormData();
  formData.set("session_id", sessionId);
  formData.set("file", file);
  return request<ChatAttachment>("/chat/attachments", {
    method: "POST",
    body: formData,
  });
}

export async function createChatRun(payload: ChatRunCreatePayload) {
  return request<ChatRun>("/chat/runs", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      stream: true,
    }),
  });
}

export async function enqueueQueuedChatInput(sessionId: string, payload: QueuedChatInputPayload) {
  return request<QueuedChatInputResponse>(`/chat/sessions/${encodeURIComponent(sessionId)}/queued-inputs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listQueuedChatInputs(sessionId: string, scope?: Partial<SessionScope>, includeTerminal = true) {
  const params = sessionScopeQuery(scope);
  params.set("include_terminal", includeTerminal ? "true" : "false");
  return request<{ session_id: string; items: QueuedChatInput[]; authority: string }>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/queued-inputs?${params.toString()}`,
  );
}

export async function cancelQueuedChatInput(sessionId: string, queueItemId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return request<{ session_id: string; item: QueuedChatInput; authority: string }>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/queued-inputs/${encodeURIComponent(queueItemId)}${query ? `?${query}` : ""}`,
    { method: "DELETE" },
  );
}

export async function getChatRun(streamRunId: string) {
  return request<ChatRun>(`/chat/runs/${encodeURIComponent(streamRunId)}`);
}

export async function getLatestChatRunForSession(sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("active_only", "true");
  return request<LatestChatRunResult>(`/chat/sessions/${encodeURIComponent(sessionId)}/latest-run?${params.toString()}`);
}

export async function getLatestSessionContinuation(sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return request<SessionContinuationProjection>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/continuations/latest${query ? `?${query}` : ""}`,
  );
}

export async function resumeChatRun(streamRunId: string) {
  return request<ChatRun & { resume_mode: string }>(`/chat/runs/${encodeURIComponent(streamRunId)}/resume`, {
    method: "POST",
  });
}

function parseSseBlock(block: string): { id: string; event: string; data: Record<string, unknown> } | null {
  const lines = block.split(/\r?\n|\r/);
  let id = "";
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!dataLines.length) {
    return null;
  }
  return {
    id,
    event,
    data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>,
  };
}

function terminalStatusFromTurnCompleted(data: Record<string, unknown>) {
  const status = String(data.status ?? "").trim().toLowerCase();
  if (status === "failed" || status === "stopped" || status === "completed") {
    return status;
  }
  return "completed";
}

function clientNow() {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

type ChatStreamConsumeBudget = {
  eventsSinceYield: number;
  burstStartedAt: number;
};

function resetChatStreamConsumeBudget(budget: ChatStreamConsumeBudget) {
  budget.eventsSinceYield = 0;
  budget.burstStartedAt = clientNow();
}

async function yieldAfterBufferedStreamBurst(budget: ChatStreamConsumeBudget, signal?: AbortSignal) {
  if (signal?.aborted) {
    throw new DOMException("Aborted", "AbortError");
  }
  budget.eventsSinceYield += 1;
  const elapsed = clientNow() - budget.burstStartedAt;
  if (
    budget.eventsSinceYield < CHAT_STREAM_CONSUME_BURST_EVENT_LIMIT
    && elapsed < CHAT_STREAM_CONSUME_BURST_TIME_MS
  ) {
    return;
  }
  resetChatStreamConsumeBudget(budget);
  await delay(0, signal);
  resetChatStreamConsumeBudget(budget);
}

async function consumeChatRunStream(
  run: ChatRun,
  sessionId: string,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    initialCursor?: ChatStreamCursor | null;
    replayFromStart?: boolean;
    persistCursor?: boolean;
  } = {}
): Promise<StreamResult> {
  const persistCursor = options.persistCursor !== false;
  let lastEventOffset = options.replayFromStart
    ? -1
    : Number(options.initialCursor?.lastEventOffset ?? run.latest_event_offset ?? -1);
  let lastEventId = options.replayFromStart ? "" : String(options.initialCursor?.lastEventId || "");
  let terminalEvent: StreamResult["terminalEvent"] | "" = "";
  let terminalStatus: StreamResult["terminalStatus"] = "";
  let reconnectAttempt = 0;
  const consumeBudget: ChatStreamConsumeBudget = {
    eventsSinceYield: 0,
    burstStartedAt: clientNow(),
  };

  if (persistCursor) {
    saveChatStreamCursor(sessionId, {
      streamRunId: run.stream_run_id,
      eventLogId: run.event_log_id,
      lastEventOffset,
      lastEventId,
    });
  }

  const consumeBlock = async (block: string) => {
    const parsed = parseSseBlock(block);
    if (!parsed) {
      return "";
    }
    parsed.data = {
      ...parsed.data,
      diagnostics: {
        ...(typeof parsed.data.diagnostics === "object" && parsed.data.diagnostics !== null && !Array.isArray(parsed.data.diagnostics)
          ? parsed.data.diagnostics
          : {}),
        client_received_at: clientNow(),
      },
    };
    const eventOffset = Number(parsed.data.event_offset);
    if (Number.isFinite(eventOffset)) {
      if (eventOffset <= lastEventOffset) {
        return parsed.event;
      }
      lastEventOffset = eventOffset;
      lastEventId = parsed.id || `${run.stream_run_id}:${run.event_log_id}:${lastEventOffset}`;
      if (persistCursor) {
        saveChatStreamCursor(sessionId, {
          streamRunId: run.stream_run_id,
          eventLogId: run.event_log_id,
          lastEventOffset,
          lastEventId,
        });
      }
    }
    if (reconnectAttempt > 0) {
      handlers.onEvent("stream_reconnected", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        attempt: reconnectAttempt,
      });
      reconnectAttempt = 0;
    }
    handlers.onEvent(parsed.event, parsed.data);
    if (TERMINAL_STREAM_EVENTS.has(parsed.event)) {
      terminalStatus = terminalStatusFromTurnCompleted(parsed.data);
    } else {
      await yieldAfterBufferedStreamBurst(consumeBudget, options.signal);
    }
    return parsed.event;
  };

  while (!terminalEvent) {
    if (options.signal?.aborted) {
      if (persistCursor) {
        clearChatStreamCursor(sessionId);
      }
      throw new DOMException("Aborted", "AbortError");
    }
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let readerClosed = false;
    let readerCancelled = false;
    let reconnectReason = "stream_closed_without_terminal";
    try {
      const params = new URLSearchParams({ after_offset: String(lastEventOffset) });
      const response = await fetch(`${getApiBase()}/chat/runs/${encodeURIComponent(run.stream_run_id)}/events?${params.toString()}`, {
        method: "GET",
        headers: lastEventId ? { "Last-Event-ID": lastEventId } : undefined,
        signal: options.signal,
      });

      if (!response.ok) {
        throw nonReconnectableChatStreamError(`Chat stream request failed: ${response.status}`, response.status);
      }
      if (!response.body) {
        throw nonReconnectableChatStreamError("Chat stream response did not include a readable body.");
      }

      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        resetChatStreamConsumeBudget(consumeBudget);
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        if (buffer.length > MAX_STREAM_BUFFER_CHARS) {
          throw new Error("Chat stream SSE buffer exceeded 1MB without a complete event boundary.");
        }

        let boundary = findSseBoundary(buffer);
        while (boundary) {
          const event = await consumeBlock(buffer.slice(0, boundary.index));
          buffer = buffer.slice(boundary.index + boundary.length);
          if (TERMINAL_STREAM_EVENTS.has(event)) {
            terminalEvent = event as StreamResult["terminalEvent"];
            break;
          }
          boundary = findSseBoundary(buffer);
        }

        if (terminalEvent) {
          if (!done) {
            await reader.cancel().catch(() => undefined);
            readerCancelled = true;
          } else {
            readerClosed = true;
          }
          break;
        }

        if (done) {
          readerClosed = true;
          if (buffer.trim()) {
            const event = await consumeBlock(buffer);
            if (TERMINAL_STREAM_EVENTS.has(event)) {
              terminalEvent = event as StreamResult["terminalEvent"];
            }
          }
          break;
        }
      }
    } catch (error) {
      if (options.signal?.aborted) {
        if (persistCursor) {
          clearChatStreamCursor(sessionId);
        }
        throw error;
      }
      if (!isReconnectableChatStreamTransportError(error)) {
        handlers.onEvent("stream_reconnect_failed", {
          stream_run_id: run.stream_run_id,
          event_log_id: run.event_log_id,
          event_offset: lastEventOffset,
          last_event_id: lastEventId,
          attempt: reconnectAttempt,
          reason: chatStreamErrorMessage(error, "stream_protocol_error"),
        });
        throw error;
      }
      reconnectReason = chatStreamErrorMessage(error, "stream_transport_error");
    } finally {
      if (reader && !readerClosed && !readerCancelled) {
        await reader.cancel().catch(() => undefined);
      }
    }

    if (!terminalEvent) {
      reconnectAttempt += 1;
      handlers.onEvent("stream_reconnecting", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        last_event_id: lastEventId,
        attempt: reconnectAttempt,
        reason: reconnectReason,
      });
      const reconnectDelay = Math.min(
        CHAT_STREAM_RECONNECT_MAX_DELAY_MS,
        CHAT_STREAM_RECONNECT_INITIAL_DELAY_MS * 2 ** Math.min(Math.max(0, reconnectAttempt - 1), 6),
      );
      await delay(reconnectDelay, options.signal);
    }
  }

  if (persistCursor) {
    clearChatStreamCursor(sessionId);
  }

  return {
    terminalEvent,
    terminalStatus: terminalStatus || "completed",
    streamRunId: run.stream_run_id,
    eventLogId: run.event_log_id,
    lastEventOffset,
  };
}

export async function streamExistingChatRun(
  sessionId: string,
  streamRunId: string,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    initialCursor?: ChatStreamCursor | null;
    replayFromStart?: boolean;
    persistCursor?: boolean;
  } = {}
) {
  const run = await resumeChatRun(streamRunId);
  return consumeChatRunStream(run, sessionId, handlers, options);
}

export async function streamChat(
  payload: ChatRunCreatePayload,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    persistCursor?: boolean;
  } = {}
): Promise<StreamResult> {
  const run = await createChatRun(payload);
  return consumeChatRunStream(run, payload.session_id, handlers, options);
}
