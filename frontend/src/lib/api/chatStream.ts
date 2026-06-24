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
  CapabilitySystemCatalog,
  CapabilityUnit,
  ChatAttachment,
  ChatRun,
  ChatStreamCursor,
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
const CHAT_STREAM_RECONNECT_INITIAL_DELAY_MS = 500;
const CHAT_STREAM_RECONNECT_MAX_DELAY_MS = 30_000;
const CHAT_STREAM_RECONNECT_MAX_ATTEMPTS = 6;
const CHAT_STREAM_CONSUME_BURST_EVENT_LIMIT = 64;
const CHAT_STREAM_CONSUME_BURST_TIME_MS = 12;
const CHAT_LIVE_PROTOCOL = "agent-live.v1";

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
  client_message_id?: string;
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

type ChatLiveEnvelope = {
  type?: string;
  protocol?: string;
  stream_run_id?: string;
  event_log_id?: string;
  event_id?: string;
  event_offset?: number;
  public_event_type?: string;
  terminal?: boolean;
  status?: string;
  data?: Record<string, unknown>;
  replay_url?: string;
  reason?: string;
  code?: string;
};

type ChatReplayResponse = {
  stream_run_id: string;
  event_log_id: string;
  after_offset: number;
  latest_event_offset: number;
  events: ChatLiveEnvelope[];
  terminal: boolean;
  authority: string;
};

export async function replayChatRunEvents(streamRunId: string, afterOffset: number, limit = 500) {
  const params = new URLSearchParams({ after_offset: String(afterOffset), limit: String(limit) });
  return request<ChatReplayResponse>(`/chat/runs/${encodeURIComponent(streamRunId)}/events/replay?${params.toString()}`);
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

async function consumeChatRunLive(
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
    : Number(options.initialCursor?.lastEventOffset ?? -1);
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

  const persistCurrentCursor = () => {
    if (!persistCursor) return;
    saveChatStreamCursor(sessionId, {
      streamRunId: run.stream_run_id,
      eventLogId: run.event_log_id,
      lastEventOffset,
      lastEventId,
    });
  };

  const consumeEnvelope = async (envelope: ChatLiveEnvelope, socket?: WebSocket | null) => {
    const envelopeType = String(envelope.type || "");
    if (envelopeType === "hello" || envelopeType === "heartbeat") {
      return "";
    }
    if (envelopeType === "error") {
      throw nonReconnectableChatStreamError(String(envelope.code || envelope.reason || "chat_live_protocol_error"));
    }
    if (envelopeType === "gap") {
      await replayFromHttp("chat_live_gap");
      socket?.close();
      return "";
    }
    if (envelopeType === "terminal") {
      terminalEvent = TURN_COMPLETED_EVENT;
      terminalStatus = String(envelope.status || terminalStatus || "completed");
      return terminalEvent;
    }
    if (envelopeType !== "event") {
      return "";
    }
    const eventName = String(envelope.public_event_type || "message");
    const data: Record<string, unknown> = {
      ...(envelope.data ?? {}),
      diagnostics: {
        ...(typeof envelope.data?.diagnostics === "object" && envelope.data.diagnostics !== null && !Array.isArray(envelope.data.diagnostics)
          ? envelope.data.diagnostics
          : {}),
        client_received_at: clientNow(),
      },
    };
    const eventOffset = Number(envelope.event_offset ?? data.event_offset);
    if (Number.isFinite(eventOffset)) {
      if (eventOffset <= lastEventOffset) {
        return eventName;
      }
      lastEventOffset = eventOffset;
      lastEventId = String(envelope.event_id || `${run.stream_run_id}:${run.event_log_id}:${lastEventOffset}`);
      persistCurrentCursor();
    }
    if (reconnectAttempt > 0) {
      handlers.onEvent("stream_reconnected", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        attempt: reconnectAttempt,
        transport: "websocket",
      });
      reconnectAttempt = 0;
    }
    handlers.onEvent(eventName, data);
    if (socket && Number.isFinite(lastEventOffset) && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: "ack",
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        last_event_offset: lastEventOffset,
        last_event_id: lastEventId,
        client_rendered_at: clientNow(),
      }));
    }
    if (TERMINAL_STREAM_EVENTS.has(eventName) || envelope.terminal === true) {
      terminalEvent = TURN_COMPLETED_EVENT;
      terminalStatus = terminalStatusFromTurnCompleted(data);
    } else {
      await yieldAfterBufferedStreamBurst(consumeBudget, options.signal);
    }
    return eventName;
  };

  const replayFromHttp = async (reason: string, options: { notifyIfPending?: boolean } = {}) => {
    const replay = await replayChatRunEvents(run.stream_run_id, lastEventOffset);
    for (const event of replay.events ?? []) {
      await consumeEnvelope(event, null);
      if (terminalEvent) break;
    }
    if (!terminalEvent && replay.terminal && replay.latest_event_offset <= lastEventOffset) {
      terminalEvent = TURN_COMPLETED_EVENT;
      terminalStatus = "completed";
    }
    if (!terminalEvent && reconnectAttempt > 0 && options.notifyIfPending !== false) {
      handlers.onEvent("stream_reconnecting", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        last_event_id: lastEventId,
        attempt: reconnectAttempt,
        reason,
        transport: "websocket",
      });
    }
  };

  while (!terminalEvent) {
    if (options.signal?.aborted) {
      if (persistCursor) {
        clearChatStreamCursor(sessionId);
      }
      throw new DOMException("Aborted", "AbortError");
    }
    let reconnectReason = "stream_closed_without_terminal";
    try {
      if (reconnectAttempt > 0) {
        await replayFromHttp(reconnectReason);
      }
      if (terminalEvent) break;
      await consumeChatRunWebSocketConnection({
        run,
        sessionId,
        afterOffset: lastEventOffset,
        lastEventId,
        signal: options.signal,
        consumeEnvelope,
      });
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
    }

    if (!terminalEvent) {
      reconnectAttempt += 1;
      if (reconnectAttempt > CHAT_STREAM_RECONNECT_MAX_ATTEMPTS) {
        const reason = "stream_reconnect_attempts_exhausted";
        const exhaustedAttempt = reconnectAttempt - 1;
        const replayStartOffset = lastEventOffset;
        let finalReplayError = "";
        try {
          await replayFromHttp(reason, { notifyIfPending: false });
        } catch (error) {
          finalReplayError = chatStreamErrorMessage(error, "stream_replay_failed");
        }
        if (terminalEvent) {
          break;
        }
        if (lastEventOffset > replayStartOffset) {
          continue;
        }
        handlers.onEvent("stream_reconnect_failed", {
          stream_run_id: run.stream_run_id,
          event_log_id: run.event_log_id,
          event_offset: lastEventOffset,
          last_event_id: lastEventId,
          attempt: exhaustedAttempt,
          max_attempts: CHAT_STREAM_RECONNECT_MAX_ATTEMPTS,
          reason,
          transport: "websocket",
          ...(finalReplayError ? { replay_error: finalReplayError } : {}),
        });
        throw nonReconnectableChatStreamError(reason);
      }
      handlers.onEvent("stream_reconnecting", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        last_event_id: lastEventId,
        attempt: reconnectAttempt,
        max_attempts: CHAT_STREAM_RECONNECT_MAX_ATTEMPTS,
        reason: reconnectReason,
        transport: "websocket",
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

async function consumeChatRunWebSocketConnection({
  run,
  sessionId,
  afterOffset,
  lastEventId,
  signal,
  consumeEnvelope,
}: {
  run: ChatRun;
  sessionId: string;
  afterOffset: number;
  lastEventId: string;
  signal?: AbortSignal;
  consumeEnvelope: (envelope: ChatLiveEnvelope, socket?: WebSocket | null) => Promise<string>;
}) {
  if (typeof WebSocket === "undefined") {
    throw nonReconnectableChatStreamError("WebSocket is not available in this environment.");
  }
  const socket = new WebSocket(chatLiveWebSocketUrl(run, sessionId));
  let settled = false;
  let opened = false;
  let processing = Promise.resolve();
  await new Promise<void>((resolve, reject) => {
    const settleResolve = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };
    const settleReject = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const onAbort = () => {
      socket.close();
      settleReject(new DOMException("Aborted", "AbortError"));
    };
    const cleanup = () => {
      signal?.removeEventListener("abort", onAbort);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    socket.onopen = () => {
      opened = true;
      socket.send(JSON.stringify({
        type: "subscribe",
        protocol: CHAT_LIVE_PROTOCOL,
        session_id: sessionId,
        subscriptions: [
          {
            kind: "chat_run",
            stream_run_id: run.stream_run_id,
            event_log_id: run.event_log_id,
            after_offset: afterOffset,
            last_event_id: lastEventId,
          },
        ],
      }));
    };
    socket.onmessage = (message) => {
      processing = processing
        .then(async () => {
          const envelope = JSON.parse(String(message.data ?? "{}")) as ChatLiveEnvelope;
          await consumeEnvelope(envelope, socket);
          if (envelope.type === "terminal" || envelope.terminal === true) {
            socket.close(1000);
          }
        })
        .catch((error) => {
          socket.close();
          settleReject(error);
        });
    };
    socket.onerror = () => {
      if (!opened) {
        settleReject(new TypeError("WebSocket connection failed"));
        return;
      }
      socket.close();
    };
    socket.onclose = () => {
      processing.then(settleResolve, settleReject);
    };
  });
}

function chatLiveWebSocketUrl(run: ChatRun, sessionId: string) {
  const liveUrl = String(run.live_ws_url || "").trim();
  if (!liveUrl) {
    throw nonReconnectableChatStreamError("chat_live_url_missing");
  }
  const url = new URL(liveUrl, getApiBase());
  if (url.protocol === "https:") {
    url.protocol = "wss:";
  } else if (url.protocol === "http:") {
    url.protocol = "ws:";
  } else if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw nonReconnectableChatStreamError("chat_live_url_unsupported_protocol");
  }
  return url.toString();
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
  const run = await getChatRun(streamRunId);
  return consumeChatRunLive(run, sessionId, handlers, options);
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
  return consumeChatRunLive(run, payload.session_id, handlers, options);
}
