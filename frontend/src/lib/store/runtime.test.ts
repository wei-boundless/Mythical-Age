import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStore, getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";
import { WorkspaceRuntime } from "./runtime";
import type { StoreState } from "./types";

const api = vi.hoisted(() => ({
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  deriveSessionTitleFromFirstUserMessage: vi.fn(),
  enqueueQueuedChatInput: vi.fn(),
  getProjectWorkspaceTree: vi.fn(),
  getSessionWorkspaceTree: vi.fn(),
  getChatRun: vi.fn(),
  getLatestChatRunForSession: vi.fn(),
  getLatestSessionContinuation: vi.fn(),
  getRunMonitor: vi.fn(),
  executeRunMonitorAction: vi.fn(),
  preflightRunMonitorAction: vi.fn(),
  getModelProviderConfig: vi.fn(),
  getTaskEnvironmentCatalog: vi.fn(),
  getOrchestrationHarnessTaskRunLiveMonitor: vi.fn(),
  getOrchestrationHarnessSessionLiveMonitor: vi.fn(),
  getOrchestrationRuntimeOptions: vi.fn(),
  approveOrchestrationHarnessTaskRunToolCall: vi.fn(),
  pauseOrchestrationHarnessTaskRun: vi.fn(),
  pauseGraphRun: vi.fn(),
  clearChatStreamCursor: vi.fn(),
  getPermissionMode: vi.fn(),
  readChatStreamCursor: vi.fn(),
  resumeOrchestrationHarnessTaskRun: vi.fn(),
  resumeGraphRun: vi.fn(),
  submitGraphRunUntilIdle: vi.fn(),
  setSessionActiveTaskEnvironment: vi.fn(),
  setSessionChatModelSelection: vi.fn(),
  setSessionPermissionMode: vi.fn(),
  setPermissionMode: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessionRuntimeProjection: vi.fn(),
  getSessionSummary: vi.fn(),
  getSessionTokens: vi.fn(),
  getWorkbenchCurrentSession: vi.fn(),
  setWorkbenchCurrentSession: vi.fn(),
  clearWorkbenchCurrentSession: vi.fn(),
  getImageAssetConfig: vi.fn(),
  getGraphRunMonitor: vi.fn(),
  getWorkspaceContext: vi.fn(),
  listSessions: vi.fn(),
  listProjectWorkspaces: vi.fn(),
  listProjectWorkspaceSessions: vi.fn(),
  listFileChanges: vi.fn(),
  listSkills: vi.fn(),
  loadFile: vi.fn(),
  loadFileForSession: vi.fn(),
  readManagedFile: vi.fn(),
  selectManagedFileForOpen: vi.fn(),
  writeManagedFile: vi.fn(),
  openManagedFileInVSCode: vi.fn(),
  saveFileForSession: vi.fn(),
  createProjectWorkspaceSession: vi.fn(),
  selectProjectWorkspaceDirectory: vi.fn(),
  stopOrchestrationHarnessTaskRun: vi.fn(),
  streamExistingChatRun: vi.fn(),
  streamChat: vi.fn(),
  truncateSessionMessages: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  createSession: api.createSession,
  deleteSession: api.deleteSession,
  deriveSessionTitleFromFirstUserMessage: api.deriveSessionTitleFromFirstUserMessage,
  enqueueQueuedChatInput: api.enqueueQueuedChatInput,
  submitGraphRunUntilIdle: api.submitGraphRunUntilIdle,
  evaluateTaskGraphRunMonitor: vi.fn(),
  getProjectWorkspaceTree: api.getProjectWorkspaceTree,
  getSessionWorkspaceTree: api.getSessionWorkspaceTree,
  getChatRun: api.getChatRun,
  getLatestChatRunForSession: api.getLatestChatRunForSession,
  getLatestSessionContinuation: api.getLatestSessionContinuation,
  getRunMonitor: api.getRunMonitor,
  executeRunMonitorAction: api.executeRunMonitorAction,
  preflightRunMonitorAction: api.preflightRunMonitorAction,
  getTaskEnvironmentCatalog: api.getTaskEnvironmentCatalog,
  getRuntimeMonitorEventStreamUrl: vi.fn(() => "http://127.0.0.1:8003/api/orchestration/runtime-monitor/events"),
  getModelProviderConfig: api.getModelProviderConfig,
  getImageAssetConfig: api.getImageAssetConfig,
  getWorkspaceContext: api.getWorkspaceContext,
  isRequestAbortError: (error: unknown) => error instanceof DOMException && error.name === "AbortError",
  getGraphRunMonitor: api.getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor: api.getOrchestrationHarnessTaskRunLiveMonitor,
  getOrchestrationHarnessSessionLiveMonitor: api.getOrchestrationHarnessSessionLiveMonitor,
  getOrchestrationRuntimeOptions: api.getOrchestrationRuntimeOptions,
  approveOrchestrationHarnessTaskRunToolCall: api.approveOrchestrationHarnessTaskRunToolCall,
  pauseOrchestrationHarnessTaskRun: api.pauseOrchestrationHarnessTaskRun,
  pauseGraphRun: api.pauseGraphRun,
  clearChatStreamCursor: api.clearChatStreamCursor,
  getPermissionMode: api.getPermissionMode,
  readChatStreamCursor: api.readChatStreamCursor,
  resumeOrchestrationHarnessTaskRun: api.resumeOrchestrationHarnessTaskRun,
  resumeGraphRun: api.resumeGraphRun,
  setSessionActiveTaskEnvironment: api.setSessionActiveTaskEnvironment,
  setSessionChatModelSelection: api.setSessionChatModelSelection,
  setSessionPermissionMode: api.setSessionPermissionMode,
  setPermissionMode: api.setPermissionMode,
  getSessionHistory: api.getSessionHistory,
  getSessionRuntimeProjection: api.getSessionRuntimeProjection,
  getSessionSummary: api.getSessionSummary,
  getSessionTokens: api.getSessionTokens,
  getWorkbenchCurrentSession: api.getWorkbenchCurrentSession,
  setWorkbenchCurrentSession: api.setWorkbenchCurrentSession,
  clearWorkbenchCurrentSession: api.clearWorkbenchCurrentSession,
  listSessions: api.listSessions,
  listProjectWorkspaces: api.listProjectWorkspaces,
  listProjectWorkspaceSessions: api.listProjectWorkspaceSessions,
  listFileChanges: api.listFileChanges,
  listSkills: api.listSkills,
  loadFile: api.loadFile,
  loadFileForSession: api.loadFileForSession,
  readManagedFile: api.readManagedFile,
  selectManagedFileForOpen: api.selectManagedFileForOpen,
  writeManagedFile: api.writeManagedFile,
  openManagedFileInVSCode: api.openManagedFileInVSCode,
  renameSession: vi.fn(),
  saveFile: vi.fn(),
  saveFileForSession: api.saveFileForSession,
  createProjectWorkspaceSession: api.createProjectWorkspaceSession,
  selectProjectWorkspaceDirectory: api.selectProjectWorkspaceDirectory,
  stopOrchestrationHarnessTaskRun: api.stopOrchestrationHarnessTaskRun,
  stopOrchestrationTaskRun: vi.fn(),
  streamExistingChatRun: api.streamExistingChatRun,
  streamChat: api.streamChat,
  truncateSessionMessages: api.truncateSessionMessages,
}));

function itemForMonitor(patch: Record<string, unknown>) {
  return {
    task_run_id: "taskrun:test",
    session_id: "session:test",
    task_id: "task:turn:session:test:1",
    title: "会话运行",
    status: "running",
    terminal_reason: "",
    lifecycle: "running",
    bucket: "running",
    resource_class: "dynamic",
    started_at: 1,
    ended_at: null,
    duration_seconds: 1,
    elapsed_seconds: 1,
    latest_event_type: "task_run_started",
    latest_event_at: 2,
    event_count: 1,
    graph_run_id: "",
    graph_harness_config_id: "",
    graph_id: "",
    active_node_id: "",
    project_id: "",
    project_title: "",
    project_runtime_status: null,
    has_graph_run: false,
    is_live: true,
    activity_state: "running",
    activity_label: "运行中",
    is_running: true,
    is_waiting: false,
    is_resumable: false,
    is_interruptible: true,
    route: { kind: "agent_runtime_run", session_id: "session:test", task_run_id: "taskrun:test" },
    ...patch,
  };
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

function taskProjectionForTest(taskRunId: string, patch: Record<string, unknown> = {}) {
  const updatedAt = Number(patch.updated_at ?? 1) || 1;
  const currentAction = recordValue(patch.current_action);
  return {
    authority: "harness.runtime.single_agent_task_projection.v1",
    projection_id: text(patch.projection_id) || `projection:${taskRunId}:${updatedAt}`,
    task_run_id: taskRunId,
    task_id: text(patch.task_id) || "task:turn:session:test:1",
    status: text(patch.status) || "running",
    phase: text(patch.phase) || "executing",
    title: text(patch.title) || "处理进展",
    ...patch,
    current_action: {
      title: text(currentAction.title) || text(patch.summary) || "正在处理当前请求。",
      detail: text(currentAction.detail) || text(patch.detail),
      state: text(currentAction.state) || text(patch.status) || "running",
      source_kind: text(currentAction.source_kind) || "task_projection",
      ...currentAction,
    },
    updated_at: updatedAt,
  };
}

function taskProjectionLineForTest(item: Record<string, unknown>) {
  const projection = recordValue(item.task_projection);
  const action = recordValue(projection.current_action);
  return text(action.title) || text(action.detail) || text(projection.summary) || text(projection.title);
}

function signalLaneState(item: Record<string, unknown>) {
  const activityState = activityStateForTest(item);
  if (activityState === "running") return "active";
  if (activityState === "waiting" || activityState === "paused") return "waiting";
  if (activityState === "failed") return "failed";
  if (activityState === "completed" || activityState === "stopped") return "completed";
  if (activityState === "stale") return "stale";
  return "attention";
}

function activityStateForTest(item: Record<string, unknown>) {
  const explicit = text(item.activity_state);
  if (explicit) return explicit;
  const status = text(item.status);
  const lifecycle = text(item.lifecycle);
  const bucket = text(item.bucket);
  const terminalReason = text(item.terminal_reason);
  const controlState = text(item.control_state);
  if (["user_aborted", "stopped", "cancelled", "canceled"].includes(status) || ["user_aborted", "stopped", "cancelled", "canceled"].includes(terminalReason) || controlState === "stopped") return "stopped";
  if (["failed", "aborted", "error"].includes(status) || lifecycle === "failed" || bucket === "failed") return "failed";
  if (["completed", "success"].includes(status) || lifecycle === "completed" || bucket === "completed") return "completed";
  if (controlState === "paused" || lifecycle === "paused") return "paused";
  if (bucket === "diagnostics" || lifecycle === "stale" || item.stale === true) return "stale";
  if (["waiting_executor", "waiting_approval", "waiting_user", "blocked"].includes(status) || ["waiting", "action_required"].includes(lifecycle) || bucket === "waiting" || item.action_required === true) return "waiting";
  if (item.is_running === true || ["created", "running"].includes(status) || lifecycle === "running") return "running";
  return "idle";
}

function monitorSignalForTest(item: Record<string, unknown>) {
  const route = recordValue(item.route);
  const sessionScope = recordValue(item.session_scope);
  const navigationPatch = recordValue(item.navigation_target);
  const activityPatch = recordValue(item.activity);
  const taskRunId = text(item.task_run_id);
  const graphRunId = text(item.graph_run_id);
  const graphHarnessConfigId = text(item.graph_harness_config_id);
  const graphId = text(item.graph_id);
  const isGraph = graphRunId || text(route.kind) === "task_graph_run" || item.has_graph_run === true;
  const sessionId = text(item.session_id);
  const taskEnvironmentId = text(sessionScope.task_environment_id || navigationPatch.task_environment_id);
  const workspaceView = text(sessionScope.workspace_view || navigationPatch.workspace_view || (isGraph ? "task_environment" : ""));
  const navigationTarget = {
    target_kind: isGraph ? "graph_task" : "session",
    session_id: sessionId,
    task_run_id: taskRunId,
    task_instance_id: text(item.task_instance_id) || taskRunId,
    graph_run_id: graphRunId,
    graph_harness_config_id: graphHarnessConfigId,
    graph_id: graphId,
    workspace_view: workspaceView,
    task_environment_id: taskEnvironmentId,
    project_id: text(sessionScope.project_id || item.project_id),
    environment_label: taskEnvironmentId,
    ...navigationPatch,
  };
  const state = signalLaneState(item);
  const activityState = activityStateForTest(item);
  const isRunning = activityState === "running";
  const isWaiting = activityState === "waiting" || activityState === "paused";
  const isResumable = item.is_resumable === true || controlStateForTest(item) === "paused";
  const isInterruptible = item.is_interruptible === true || Boolean(isRunning && taskRunId && !taskRunId.startsWith("turnrun:"));
  return {
    authority: "runtime_monitor.signal",
    signal_id: text(item.task_instance_id) || taskRunId,
    source_kind: isGraph ? "graph_run" : taskRunId.startsWith("turnrun:") ? "turn_run" : "task_run",
    work_kind: isGraph ? "graph_task" : taskRunId.startsWith("turnrun:") ? "chat_turn" : "agent_task",
    state,
    priority: state === "active" ? 100 : state === "waiting" ? 80 : state === "failed" ? 60 : 20,
    title: text(item.project_title) || text(item.title) || "持续处理",
    line: taskProjectionLineForTest(item) || text(item.summary) || "正在处理当前请求。",
    detail: "运行 1s",
    status: text(item.status),
    lifecycle: text(item.lifecycle),
    bucket: text(item.bucket),
    activity_state: activityState,
    activity_label: text(item.activity_label) || activityLabelForTest(activityState),
    is_running: isRunning,
    is_waiting: isWaiting,
    is_resumable: isResumable,
    is_interruptible: isInterruptible,
    control_reason: text(item.control_reason),
    recovery_cause: text(item.recovery_cause),
    tone: text(item.tone) || (isRunning ? "active" : activityState === "completed" ? "done" : activityState === "failed" ? "attention" : "neutral"),
    activity: {
      activity_state: activityState,
      activity_label: text(item.activity_label) || activityLabelForTest(activityState),
      detail: text(activityPatch.detail || item.activity_detail),
      is_running: isRunning,
      is_waiting: isWaiting,
      is_resumable: isResumable,
      is_interruptible: isInterruptible,
      control_reason: text(item.control_reason),
    },
    control_capability: {
      is_resumable: isResumable,
      is_interruptible: isInterruptible,
      control_reason: text(item.control_reason),
    },
    session_output_commit: recordValue(item.session_output_commit),
    session_id: sessionId,
    task_run_id: taskRunId,
    task_instance_id: text(item.task_instance_id) || taskRunId,
    graph_run_id: graphRunId,
    graph_id: graphId,
    navigation_target: navigationTarget,
    detail_ref: {
      kind: isGraph ? "graph_run" : "task_run",
      task_run_id: taskRunId,
      turn_run_id: taskRunId.startsWith("turnrun:") ? taskRunId : "",
      graph_run_id: graphRunId,
      graph_harness_config_id: graphHarnessConfigId,
      resource_ref: "",
    },
    graph_ref: {
      graph_id: graphId,
      graph_run_id: graphRunId,
      graph_harness_config_id: graphHarnessConfigId,
    },
    timestamps: {
      started_at: Number(item.started_at ?? 1),
      updated_at: Number(item.updated_at ?? item.latest_event_at ?? 2),
      last_activity_at: Number(item.last_activity_at ?? item.latest_event_at ?? item.updated_at ?? 2),
      elapsed_seconds: Number(item.elapsed_seconds ?? 1),
    },
    raw_refs: {
      task_id: text(item.task_id),
      route,
    },
  };
}

function controlStateForTest(item: Record<string, unknown>) {
  const runtimeControl = recordValue(item.runtime_control);
  return text(item.control_state || runtimeControl.state);
}

function activityLabelForTest(activityState: string) {
  if (activityState === "running") return "运行中";
  if (activityState === "paused") return "已暂停";
  if (activityState === "waiting") return "等待继续";
  if (activityState === "stopped") return "已停止";
  if (activityState === "failed") return "失败";
  if (activityState === "completed") return "已完成";
  if (activityState === "stale") return "等待检查";
  return "待命";
}

async function flushPromises(times = 5) {
  for (let index = 0; index < times; index += 1) {
    await Promise.resolve();
  }
}

function deepseekProviderConfig(defaultModel = "deepseek-v4-flash") {
  return {
    provider: "deepseek",
    model: defaultModel,
    base_url: "https://api.deepseek.com/v1",
    credential_ref: "provider:deepseek:primary",
    api_key_configured: true,
    fallback_provider: "",
    fallback_model: "",
    fallback_base_url: "",
    fallback_api_key_configured: false,
    supported_providers: {
      deepseek: {
        provider: "deepseek",
        default_model: defaultModel,
        default_base_url: "https://api.deepseek.com/v1",
        credential_ref: "provider:deepseek:primary",
        capability_tags: ["reasoning", "openai_compatible"],
        model_presets: ["deepseek-v4-pro", "deepseek-v4-flash"],
      },
    },
    authority: "runtime.model_provider",
  };
}

function sessionSummaryWithChatModel(id: string, selectionId = "system-default", updatedAt = 1) {
  const [provider, ...modelParts] = selectionId === "system-default" ? ["", ""] : selectionId.split("::");
  return {
    id,
    title: id,
    created_at: 1,
    updated_at: updatedAt,
    message_count: 0,
    conversation_state: {
      authority: "sessions.conversation_state",
      permission_mode: "full_access",
      chat_model_selection: {
        selection_id: selectionId,
        provider,
        model: modelParts.join("::"),
        authority: "sessions.chat_model_selection",
      },
    },
  };
}

function expectQueuedChatInputCall(callIndex: number, sessionId: string, message: string) {
  const call = api.enqueueQueuedChatInput.mock.calls[callIndex];
  expect(call?.[0]).toBe(sessionId);
  expect(call?.[1]).toMatchObject({
    message,
    client_message_id: expect.any(String),
    environment_binding: expect.any(Object),
    model_selection: expect.any(Object),
    permission_mode: expect.any(String),
  });
  expect(call?.[1]).toHaveProperty("session_scope");
  expect(call?.[1]).toHaveProperty("editor_context");
  expect(call?.[1]).not.toHaveProperty("active_turn_input_policy");
  expect(call?.[1]).not.toHaveProperty("expected_active_turn_id");
}

function emitRuntimeControlSteerDone(
  handlers: { onEvent: (event: string, data: Record<string, unknown>) => void },
  {
    taskRunId,
    activeTurnId,
    completionState = "task_steer_accepted",
  }: {
    taskRunId: string;
    activeTurnId: string;
    completionState?: string;
  },
) {
  handlers.onEvent("runtime_status", {
    state: "running",
    phase: "active_turn_steer",
    runtime_task_run_id: taskRunId,
    active_turn_id: activeTurnId,
  });
  handlers.onEvent("done", {
    content: "",
    answer_channel: "runtime_control",
    answer_source: "harness.entrypoint.active_turn_steer",
    terminal_reason: "append_instruction_to_active_work",
    completion_state: completionState,
    runtime_task_run_id: taskRunId,
    active_turn_id: activeTurnId,
  });
}

function anchoredStatusProjectionEnvelope({
  projectionId,
  runId,
  taskRunId,
  turnId,
  itemId,
  text,
  state = "running",
}: {
  projectionId: string;
  runId: string;
  taskRunId: string;
  turnId: string;
  itemId: string;
  text: string;
  state?: string;
}) {
  return {
    authority: "harness.public_projection",
    projection_id: projectionId,
    lifecycle: state,
    source_authority: "runtime",
    surface: "timeline",
    anchor: {
      run_id: runId,
      task_run_id: taskRunId,
      turn_id: turnId,
      anchor_role: "assistant",
    },
    items: [
      {
        item_id: itemId,
        kind: "status_update",
        slot: "status",
        surface: "timeline",
        source_authority: "runtime",
        title: text,
        detail: text,
        state,
      },
    ],
  };
}

function monitorForTest(items: Array<Record<string, unknown>>, patch: Record<string, unknown> = {}) {
  const signals = items.map(monitorSignalForTest);
  const primary = signals.filter((signal) => signal.is_running === true);
  const attention = signals.filter((signal) => ["waiting", "attention", "stale", "failed"].includes(signal.state));
  const recent = signals.filter((signal) => signal.state === "completed");
  const projects = signals.filter((signal) => signal.work_kind === "graph_task");
  return {
    authority: "runtime_monitor",
    revision: text(patch.revision) || "rtmon:1:test",
    updated_at: Number(patch.updated_at ?? 1),
    summary: {
      active: primary.length,
      attention: attention.length,
      waiting: signals.filter((signal) => ["waiting", "paused"].includes(text(signal.activity_state))).length,
      failed: signals.filter((signal) => signal.state === "failed").length,
      recent: recent.length,
      projects: projects.length,
      total: signals.length,
    },
    primary,
    attention,
    recent,
    projects,
    signals,
    ...patch,
  };
}

const TASK_ENVIRONMENT_CATALOG = {
  authority: "task_system.task_environment_catalog",
  groups: [],
  environments: [
    {
      record: {
        environment_id: "env.coding.vibe_workspace",
        title: "Vibe 编码工作区",
        group_id: "environment_group.coding",
        environment_kind: "coding",
        enabled: true,
      },
      spec: {},
      management_scope: "builtin_template",
    },
    {
      record: {
        environment_id: "env.office.file_search",
        title: "轻量办公文件检索",
        group_id: "environment_group.office",
        environment_kind: "office",
        enabled: true,
      },
      spec: {},
      management_scope: "builtin_template",
    },
    {
      record: {
        environment_id: "env.general.workspace",
        title: "通用工作区",
        group_id: "environment_group.general",
        environment_kind: "general",
        enabled: true,
      },
      spec: {},
      management_scope: "builtin_template",
    },
  ],
  records: [],
  summary: { environment_count: 3 },
};

function conversationState(environmentId: string, label = environmentId, source = "conversation", permissionMode = "full_access") {
  return {
    authority: "sessions.conversation_state",
    permission_mode: permissionMode,
    active_task_environment: {
      task_environment_id: environmentId,
      environment_label: label,
      source,
      updated_at: 1,
      authority: "sessions.conversation_active_task_environment",
    },
  };
}

let projectionFrameOffset = 0;

type StreamEventHandlers = {
  onEvent: (event: string, data: Record<string, unknown>) => void;
};

function requireStreamHandlers(value: StreamEventHandlers | null) {
  if (!value) {
    throw new Error("stream handlers were not captured");
  }
  return value;
}

function publicBodyFrame(patch: Record<string, unknown> = {}) {
  projectionFrameOffset += 1;
  return {
    authority: "harness.public_projection",
    contract_revision: "20260614-dual-channel-v1",
    frame_id: `frame:runtime-test:${projectionFrameOffset}`,
    event_offset: projectionFrameOffset,
    event_family: "assistant_body",
    channel: "body",
    lossless: true,
    op: "body_append",
    slot: "body",
    source_authority: "model",
    main_visibility: "visible_live",
    retention: "final",
    anchor: {
      turn_id: "turn:runtime-test:1",
      turn_run_id: "turnrun:runtime-test:1",
      run_id: "turnrun:runtime-test:1",
    },
    ...patch,
  };
}

function runtimeProjectionAttachmentForTest(options: {
  sessionId: string;
  turnId: string;
  assistantMessageId: string;
  streamRunId: string;
  turnRunId: string;
  text: string;
}) {
  const frame = publicBodyFrame({
    frame_id: `frame:${options.streamRunId}:body`,
    projection_id: `frame:${options.streamRunId}:body`,
    event_offset: 10,
    sequence: 10,
    retention: "transient",
    text: options.text,
    item_id: options.assistantMessageId,
    anchor: {
      session_id: options.sessionId,
      turn_id: options.turnId,
      message_id: options.assistantMessageId,
      stream_run_id: options.streamRunId,
      run_id: options.streamRunId,
      turn_run_id: options.turnRunId,
    },
  });
  return {
    attachment_id: `runtime-attachment:${options.streamRunId}`,
    run_id: options.streamRunId,
    stream_run_id: options.streamRunId,
    event_log_id: `chatrun:${options.streamRunId}`,
    anchor_turn_id: options.turnId,
    anchor_message_id: options.assistantMessageId,
    anchor_role: "assistant",
    turn_run_id: options.turnRunId,
    status: "running",
    display_state: "running",
    main_chat_surface: "live",
    projection_anchor: {
      session_id: options.sessionId,
      anchor_turn_id: options.turnId,
      anchor_message_id: options.assistantMessageId,
      stream_run_id: options.streamRunId,
      run_id: options.streamRunId,
      turn_run_id: options.turnRunId,
    },
    projection_slices: [{
      slice_id: `projection-slice:${options.streamRunId}`,
      schema_version: "chronological_projection",
      event_log_id: `chatrun:${options.streamRunId}`,
      start_offset: 10,
      end_offset: 10,
      integrity: "bounded",
      committed: false,
      cursor: {
        min_event_offset: 10,
        max_event_offset: 10,
        frame_count: 1,
      },
      frames: [frame],
      display_hint: {
        lifecycle: "running",
        main_surface_hint: "live",
      },
      authority: "session_runtime_timeline.projection_slice",
    }],
  };
}

function latestProjectionView(state: StoreState) {
  const assistant = [...state.messages].reverse().find((message) => message.role === "assistant");
  const key = assistant?.projectionKeyString ?? "";
  return key ? state.activeProjectionsByKey[key]?.view : undefined;
}

describe("WorkspaceRuntime task graph monitor polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    projectionFrameOffset = 0;
    api.getChatRun.mockReset();
    api.getChatRun.mockResolvedValue(null);
    api.getLatestChatRunForSession.mockReset();
    api.getLatestChatRunForSession.mockResolvedValue(null);
    api.getLatestSessionContinuation.mockReset();
    api.getLatestSessionContinuation.mockResolvedValue({
      session_id: "",
      available: false,
      reason: "no_recoverable_work",
      authority: "session.continuation.latest",
    });
    api.getRunMonitor.mockReset();
    api.getRunMonitor.mockResolvedValue(monitorForTest([]));
    api.executeRunMonitorAction.mockReset();
    api.executeRunMonitorAction.mockResolvedValue({
      authority: "runtime_monitor.actions",
      accepted: true,
      action: "clear_from_monitor",
      target: {},
      effects: {},
      monitor: monitorForTest([]),
      updated_at: 1,
    });
    api.preflightRunMonitorAction.mockReset();
    api.preflightRunMonitorAction.mockResolvedValue({
      authority: "runtime_monitor.actions",
      mode: "preflight",
      accepted: true,
      action: "clear_from_monitor",
      target: {},
      effects: {},
      monitor: monitorForTest([]),
      updated_at: 1,
    });
    api.getSessionWorkspaceTree.mockReset();
    api.getSessionWorkspaceTree.mockResolvedValue({
      authority: "langchain-agent.code_environment.workspace_tree",
      root_name: "langchain-agent",
      root_path: "D:/AI应用/langchain-agent",
      max_depth: 10,
      max_entries: 10000,
      total_entries: 0,
      truncated: false,
      tree: {
        name: "langchain-agent",
        path: "",
        kind: "directory",
        depth: 0,
        children: [],
        truncated: false,
      },
    });
    api.getProjectWorkspaceTree.mockReset();
    api.getProjectWorkspaceTree.mockResolvedValue({
      authority: "langchain-agent.code_environment.workspace_tree",
      root_name: "repo",
      root_path: "D:/repo",
      max_depth: 10,
      max_entries: 10000,
      total_entries: 0,
      truncated: false,
      tree: {
        name: "repo",
        path: "",
        kind: "directory",
        depth: 0,
        children: [],
        truncated: false,
      },
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockReset();
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({ monitor: null });
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockReset();
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockResolvedValue({ monitor: null });
    api.getChatRun.mockReset();
    api.getChatRun.mockRejectedValue(new Error("no chat run"));
    api.pauseOrchestrationHarnessTaskRun.mockReset();
    api.pauseOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.pauseGraphRun.mockReset();
    api.pauseGraphRun.mockResolvedValue({ ok: true, accepted: true });
    api.approveOrchestrationHarnessTaskRunToolCall.mockReset();
    api.approveOrchestrationHarnessTaskRunToolCall.mockResolvedValue({ ok: true });
    api.clearChatStreamCursor.mockReset();
    api.resumeOrchestrationHarnessTaskRun.mockReset();
    api.resumeOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.resumeGraphRun.mockReset();
    api.resumeGraphRun.mockResolvedValue({ ok: true, accepted: true });
    api.submitGraphRunUntilIdle.mockReset();
    api.submitGraphRunUntilIdle.mockResolvedValue({ accepted: true, background_started: true });
    api.stopOrchestrationHarnessTaskRun.mockReset();
    api.stopOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.getSessionHistory.mockReset();
    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionRuntimeProjection.mockReset();
    api.getSessionRuntimeProjection.mockResolvedValue({ messages: [], runtime_attachments: [] });
    api.getSessionSummary.mockReset();
    api.getSessionSummary.mockRejectedValue(new Error("no remembered session"));
    api.getSessionTokens.mockReset();
    api.getSessionTokens.mockResolvedValue(null);
    api.getWorkbenchCurrentSession.mockReset();
    api.getWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: null,
    });
    api.setWorkbenchCurrentSession.mockReset();
    api.setWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: null,
    });
    api.clearWorkbenchCurrentSession.mockReset();
    api.clearWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: null,
    });
    api.getGraphRunMonitor.mockReset();
    api.getGraphRunMonitor.mockResolvedValue({
      authority: "harness.graph_run_monitor",
      graph_run_id: "grun:bound",
      graph_run: { graph_run_id: "grun:bound", task_run_id: "taskrun:bound", graph_id: "graph:test", config_id: "ghcfg:bound" },
      task_run_id: "taskrun:bound",
      task_run: { task_run_id: "taskrun:bound", status: "running" },
      graph_harness_config: { config_id: "ghcfg:bound", graph_id: "graph:test" },
      graph_loop_state: { status: "running", active_node_ids: ["draft"] },
      active_node_work_orders: [{ node_id: "draft", work_order_id: "gwork:bound:draft" }],
      active_node_work_order_count: 1,
      events: [],
      event_count: 1,
    });
    api.createSession.mockReset();
    api.createSession.mockResolvedValue({
      id: "session:fresh",
      title: "New Session",
      created_at: 1,
      updated_at: 1,
      message_count: 0,
    });
    api.createProjectWorkspaceSession.mockReset();
    api.createProjectWorkspaceSession.mockResolvedValue({
      authority: "project_workspaces.session_create",
      project_key: "workspace:repo",
      session: {
        id: "session:fresh",
        title: "New Session",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "project_workspace",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      },
      created: true,
    });
    api.selectProjectWorkspaceDirectory.mockReset();
    api.selectProjectWorkspaceDirectory.mockResolvedValue({
      authority: "project_workspaces.directory_picker",
      project: {
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "frontend.directory_picker",
        created_at: 1,
        last_seen_at: 1,
        session_count: 0,
        latest_session_at: 0,
        available: true,
        authority: "project_workspaces.workspace",
      },
      selected_path: "D:/repo",
    });
    api.deleteSession.mockReset();
    api.deleteSession.mockResolvedValue({ ok: true });
    api.deriveSessionTitleFromFirstUserMessage.mockReset();
    api.deriveSessionTitleFromFirstUserMessage.mockResolvedValue({
      session_id: "session:fresh",
      title: "首轮标题",
    });
    api.getPermissionMode.mockReset();
    api.getPermissionMode.mockResolvedValue({
      mode: "default",
      supported_modes: ["default", "plan", "accept_edits", "bypass", "full_access"],
    });
    api.getModelProviderConfig.mockReset();
    api.getModelProviderConfig.mockResolvedValue(null);
    api.getTaskEnvironmentCatalog.mockReset();
    api.getTaskEnvironmentCatalog.mockResolvedValue(TASK_ENVIRONMENT_CATALOG);
    api.getImageAssetConfig.mockReset();
    api.getImageAssetConfig.mockResolvedValue(null);
    api.getWorkspaceContext.mockReset();
    api.getWorkspaceContext.mockResolvedValue(null);
    api.getOrchestrationRuntimeOptions.mockReset();
    api.getOrchestrationRuntimeOptions.mockResolvedValue({
      authority: "orchestration.runtime_options",
      options: {},
    });
    api.listSessions.mockReset();
    api.listSessions.mockResolvedValue([]);
    api.listProjectWorkspaces.mockReset();
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [],
      summary: { project_count: 0 },
    });
    api.listProjectWorkspaceSessions.mockReset();
    api.listProjectWorkspaceSessions.mockResolvedValue({
      authority: "project_workspaces.sessions",
      project_key: "workspace:repo",
      sessions: [],
    });
    api.listFileChanges.mockReset();
    api.listFileChanges.mockResolvedValue({
      records: [],
      summary: { count: 0 },
      authority: "api.file_changes.list",
    });
    api.listSkills.mockReset();
    api.listSkills.mockResolvedValue([]);
    api.loadFile.mockReset();
    api.loadFile.mockResolvedValue({ path: "durable_memory/index/MEMORY.md", content: "" });
    api.loadFileForSession.mockReset();
    api.loadFileForSession.mockResolvedValue({ path: "durable_memory/index/MEMORY.md", content: "" });
    api.readManagedFile.mockReset();
    api.readManagedFile.mockImplementation(async (target) => ({
      target,
      path: target.logical_path,
      content: "",
      content_sha256: "sha256-initial",
      authority: "file_management.service.read",
    }));
    api.writeManagedFile.mockReset();
    api.writeManagedFile.mockImplementation(async (payload) => ({
      ok: true,
      target: payload.target,
      path: payload.target.logical_path,
      content_sha256: "sha256-saved",
      file_change_record: {
        record_id: "file-change:test",
        session_id: payload.sessionId || "",
        logical_path: payload.target.logical_path,
      },
      authority: "file_management.service.write",
    }));
    api.openManagedFileInVSCode.mockReset();
    api.openManagedFileInVSCode.mockResolvedValue({ ok: true, authority: "api.file_management.open_vscode" });
    api.saveFileForSession.mockReset();
    api.saveFileForSession.mockResolvedValue({ ok: true, path: "durable_memory/index/MEMORY.md" });
    api.readChatStreamCursor.mockReset();
    api.readChatStreamCursor.mockReturnValue(null);
    api.setSessionActiveTaskEnvironment.mockReset();
    api.setSessionActiveTaskEnvironment.mockImplementation(async (_sessionId, payload) =>
      conversationState(String(payload.task_environment_id || ""), String(payload.environment_label || payload.task_environment_id), String(payload.source || "conversation"))
    );
    api.setSessionPermissionMode.mockReset();
    api.setSessionPermissionMode.mockImplementation(async (_sessionId, mode) => ({
      active_task_environment: {},
      chat_model_selection: {},
      permission_mode: String(mode || "full_access"),
      authority: "sessions.conversation_state",
    }));
    api.setSessionChatModelSelection.mockReset();
    api.setSessionChatModelSelection.mockImplementation(async (_sessionId, payload) => ({
      active_task_environment: {},
      chat_model_selection: {
        selection_id: String(payload.selection_id || "system-default"),
        provider: String(payload.provider || ""),
        model: String(payload.model || ""),
        source: String(payload.source || "user"),
        authority: "sessions.chat_model_selection",
      },
      permission_mode: "full_access",
      authority: "sessions.conversation_state",
    }));
    api.setPermissionMode.mockReset();
    api.setPermissionMode.mockImplementation(async (mode) => ({
      mode: String(mode || "default"),
      supported_modes: ["default", "plan", "accept_edits", "bypass", "full_access"],
    }));
    api.streamExistingChatRun.mockReset();
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:test", eventLogId: "chatrun:test", lastEventOffset: 1 };
    });
    api.streamChat.mockReset();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:test", eventLogId: "chatrun:test", lastEventOffset: 1 };
    });
    api.enqueueQueuedChatInput.mockReset();
    api.enqueueQueuedChatInput.mockImplementation(async (sessionId, payload) => ({
      session_id: sessionId,
      item: {
        queue_item_id: "qinp:test",
        session_id: sessionId,
        client_message_id: payload.client_message_id ?? "",
        content: payload.message,
        input_policy: "auto",
        status: "queued",
        created_at: 1,
        updated_at: 1,
        dispatch_stream_run_id: "",
      },
      items: [],
      authority: "api.chat.queued_user_inputs",
    }));
    api.truncateSessionMessages.mockReset();
    api.truncateSessionMessages.mockResolvedValue({ ok: true });
    vi.stubGlobal("window", {
      clearTimeout,
      localStorage: {
        getItem: vi.fn(),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
      setTimeout,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("binds a TaskGraph run without starting legacy graph detail polling", async () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.bindTaskGraphMonitorRun({
      task_run_id: "taskrun:bound",
      graph_run_id: "grun:bound",
      graph_harness_config_id: "ghcfg:bound",
      graph_id: "graph:test",
    });
    await vi.runOnlyPendingTimersAsync();
    runtime.actions.setTaskGraphRunInteractionOpen(false);
    await vi.advanceTimersByTimeAsync(1200);

    expect(api.getGraphRunMonitor).not.toHaveBeenCalled();
    expect(store.getState().taskGraphMonitorBinding?.task_run_id).toBe("taskrun:bound");
    expect(store.getState().taskGraphBoundRunMonitor).toBeNull();
    expect(store.getState().taskGraphMonitorError).toBe("");
  });

  it("surfaces project file open failures instead of leaving stale inspector content", async () => {
    api.loadFile.mockRejectedValue(new Error("Path is not visible in the project file tree"));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      inspectorPath: "AGENTS.md",
      inspectorContent: "previous content",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.loadInspectorFile(".env");

    expect(store.getState().inspectorPath).toBe(".env");
    expect(store.getState().inspectorContent).toContain("Path is not visible in the project file tree");
    expect(store.getState().workspaceTreeError).toContain("Path is not visible in the project file tree");
    expect(store.getState().inspectorDirty).toBe(false);
  });

  it("loads and saves project files through the managed file authority", async () => {
    api.readManagedFile.mockResolvedValueOnce({
      target: {
        repository_id: "repo.managed_project.project_workspace",
        repository_kind: "project_workspace",
        scope_kind: "project_scoped",
        scope_id: "session:code",
        logical_path: "src/app.ts",
        workspace_root: "D:/repo",
        profile_id: "file_profile.managed_project_workspace",
      },
      path: "src/app.ts",
      content: "export const value = 1;\n",
      content_sha256: "sha-before",
      authority: "file_management.service.read",
    });
    api.writeManagedFile.mockResolvedValueOnce({
      ok: true,
      target: {
        repository_id: "repo.managed_project.project_workspace",
        repository_kind: "project_workspace",
        scope_kind: "project_scoped",
        scope_id: "session:code",
        logical_path: "src/app.ts",
        workspace_root: "D:/repo",
        profile_id: "file_profile.managed_project_workspace",
      },
      path: "src/app.ts",
      content_sha256: "sha-after",
      file_change_record: {
        record_id: "change:managed",
        session_id: "session:code",
        logical_path: "src/app.ts",
      },
      authority: "file_management.service.write",
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:code",
      sessions: [{
        id: "session:code",
        title: "Code",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "project_workspace",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      }],
    });
    const runtime = new WorkspaceRuntime(store);
    const initialRevision = store.getState().fileChangesRevision;

    await runtime.actions.loadInspectorFile("src/app.ts");
    runtime.actions.updateInspectorContent("export const value = 2;\n");
    await runtime.actions.saveInspector();

    expect(api.readManagedFile).toHaveBeenCalledWith(
      expect.objectContaining({
        repository_id: "repo.managed_project.project_workspace",
        logical_path: "src/app.ts",
        workspace_root: "D:/repo",
      }),
      "session:code",
    );
    expect(api.writeManagedFile).toHaveBeenCalledWith(expect.objectContaining({
      content: "export const value = 2;\n",
      expectedSha256: "sha-before",
      sessionId: "session:code",
      target: expect.objectContaining({
        logical_path: "src/app.ts",
        workspace_root: "D:/repo",
      }),
    }));
    expect(api.saveFileForSession).not.toHaveBeenCalled();
    expect(store.getState().inspectorContentSha256).toBe("sha-after");
    expect(store.getState().inspectorLastChangeRecordId).toBe("change:managed");
    expect(store.getState().fileChangesRevision).toBe(initialRevision + 1);
    expect(store.getState().fileChangeRecordsBySession["session:code"]?.[0]).toMatchObject({
      record_id: "change:managed",
      session_id: "session:code",
      logical_path: "src/app.ts",
    });
    expect(store.getState().inspectorDirty).toBe(false);
  });

  it("reads TaskGraph detail only through explicit monitor evaluation", async () => {
    api.getGraphRunMonitor.mockRejectedValue(new Error('{"detail":"GraphHarnessConfig not found"}'));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.bindTaskGraphMonitorRun({
      task_run_id: "taskrun:old-graph",
      graph_run_id: "grun:old-graph",
      graph_harness_config_id: "ghcfg:old-missing",
      graph_id: "graph:old",
    });
    await runtime.actions.evaluateBoundTaskGraphMonitor();
    await vi.advanceTimersByTimeAsync(6000);

    expect(api.getGraphRunMonitor).toHaveBeenCalledTimes(1);
    expect(store.getState().taskGraphMonitorBinding?.task_run_id).toBe("taskrun:old-graph");
    expect(store.getState().taskGraphBoundRunMonitor).toBeNull();
    expect(store.getState().taskGraphMonitorError).toContain("GraphHarnessConfig not found");
  });

  it("keeps the run monitor selection on known signals and clears missing ones", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>, options?: { selectedSignalId?: string }) => void;
    };
    const monitor = monitorForTest([
        itemForMonitor({
          task_run_id: "taskrun:agent",
          session_id: "session",
          title: "world_design",
          latest_event_type: "executor_started",
          route: { kind: "agent_runtime_run", session_id: "session", task_run_id: "taskrun:agent" },
        }),
        itemForMonitor({
          task_run_id: "taskrun:master",
          session_id: "session",
          title: "洪荒时代",
          latest_event_type: "graph_run_created",
          graph_run_id: "grun:master",
          graph_harness_config_id: "ghcfg:master",
          graph_id: "graph.writing.modular_novel.master",
          active_node_id: "graph_module.design_init",
          project_id: "project",
          project_title: "洪荒时代",
          has_graph_run: true,
          route: { kind: "task_graph_run", session_id: "session", task_run_id: "taskrun:master", graph_id: "graph.writing.modular_novel.master", graph_run_id: "grun:master", graph_harness_config_id: "ghcfg:master" },
        }),
      ]);

    runtimeHarness.applyRunMonitorSnapshot(monitor, { selectedSignalId: "taskrun:agent" });

    expect(store.getState().runMonitorSelectedTaskRunId).toBe("taskrun:agent");

    runtime.actions.openRunMonitorSignal("taskrun:module");

    expect(store.getState().runMonitorSelectedTaskRunId).toBe("");
  });

  it("opens a run monitor TaskGraph signal with its session scope for explicit graph refresh", async () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };
    const graphSessionScope = {
      workspace_view: "graph_task",
      task_environment_id: "",
      project_id: "project",
    };

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([
      itemForMonitor({
        task_run_id: "taskrun:master",
        session_id: "session",
        title: "长篇小说",
        latest_event_type: "graph_run_created",
        graph_run_id: "grun:master",
        graph_harness_config_id: "ghcfg:master",
        graph_id: "graph.writing.master",
        active_node_id: "world_review",
        project_id: "project",
        project_title: "长篇小说",
        has_graph_run: true,
        session_scope: graphSessionScope,
        route: { kind: "task_graph_run", session_id: "session", task_run_id: "taskrun:master", graph_id: "graph.writing.master", graph_run_id: "grun:master", graph_harness_config_id: "ghcfg:master" },
      }),
    ]));

    runtime.actions.openRunMonitorSignal("taskrun:master");

    expect(store.getState().activeWorkspaceView).toBe("creative");
    expect(store.getState().currentSessionId).toBeNull();
    expect(store.getState().runMonitorSelectedTaskRunId).toBe("taskrun:master");
    expect(store.getState().chatTaskEnvironmentBinding).toBeNull();
    expect(store.getState().conversationActiveEnvironment).toBeNull();
    expect(store.getState().taskGraphMonitorBinding).toMatchObject({
      task_run_id: "taskrun:master",
      graph_run_id: "grun:master",
      graph_harness_config_id: "ghcfg:master",
      graph_id: "graph.writing.master",
      session_id: "session",
      project_id: "project",
      session_scope: graphSessionScope,
      title: "长篇小说",
    });
    expect(store.getState().taskGraphRunInteractionOpen).toBe(false);
    expect(store.getState().taskGraphWorkspaceTarget).toMatchObject({
      task_run_id: "taskrun:master",
      layer: "task-graph",
      mode: "monitor",
      graph_id: "graph.writing.master",
    });

    await runtime.actions.evaluateBoundTaskGraphMonitor();

    expect(api.getGraphRunMonitor).toHaveBeenCalledWith(
      "grun:master",
      "ghcfg:master",
      80,
      graphSessionScope,
    );
  });

  it("opens workspace files inside the current shared center workspace", () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "task-system",
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.openWorkspaceFile(" AGENTS.md ");

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().centerWorkspaceTarget).toMatchObject({
      layer: "file",
      file_path: "AGENTS.md",
    });
  });

  it("opens runtime logs inside the shared center workspace", () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "task-system",
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.openRuntimeLog({
      scope: "task_run",
      run_id: " taskrun:log:1 ",
      title: "运行日志",
      subtitle: "TaskRun",
    });

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().centerWorkspaceTarget).toMatchObject({
      layer: "runtime-log",
      scope: "task_run",
      run_id: "taskrun:log:1",
      title: "运行日志",
      subtitle: "TaskRun",
    });
  });

  it("loads and updates the runtime permission mode selector state", async () => {
    vi.useRealTimers();
    api.getPermissionMode.mockResolvedValueOnce({
      mode: "full_access",
      supported_modes: ["default", "plan", "accept_edits", "bypass", "full_access"],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(store.getState().permissionMode).toBe("full_access");

    await runtime.actions.setPermissionMode("default");

    expect(api.setSessionPermissionMode).not.toHaveBeenCalled();
    expect(api.setPermissionMode).toHaveBeenLastCalledWith("default");
    expect(store.getState().permissionMode).toBe("default");
  });

  it("restores permission mode from the selected conversation session", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:default",
        title: "Default Session",
        created_at: 1,
        updated_at: 2,
        message_count: 0,
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "default" },
      },
      {
        id: "session:full",
        title: "Full Session",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
      },
    ]);
    api.getSessionHistory.mockImplementation(async (sessionId) => ({
      id: String(sessionId),
      title: "Session",
      created_at: 1,
      updated_at: 1,
      compressed_context: "",
      conversation_state: String(sessionId) === "session:full"
        ? { authority: "sessions.conversation_state", permission_mode: "full_access" }
        : { authority: "sessions.conversation_state", permission_mode: "default" },
      messages: [],
    }));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:default");
    expect(store.getState().permissionMode).toBe("default");

    await runtime.actions.selectSession({ sessionId: "session:full" });
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:full");
    expect(store.getState().permissionMode).toBe("full_access");
  });

  it("sends the selected session permission mode with new chat runs", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:plan",
        title: "Plan Session",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "plan" },
      },
    ]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();
    await runtime.actions.sendMessage("检查当前项目。");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    const payload = api.streamChat.mock.calls[0]?.[0];
    const userMessage = store.getState().messages.find((message) => message.role === "user" && message.content === "检查当前项目。");
    expect(payload).toMatchObject({
      session_id: "session:plan",
      client_message_id: userMessage?.id,
      permission_mode: "plan",
    });
  });

  it("signals native file changes from chat stream tool results", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:file-change",
        title: "File Change Session",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
      },
    ]);
    api.streamChat.mockImplementationOnce(async (_payload, handlers) => {
      handlers.onEvent("tool_result", {
        result_envelope: {
          structured_payload: {
            file_change: {
              status: "recorded",
              record: {
                record_id: "filechange-native-single",
                session_id: "session:file-change",
                logical_path: "src/app.ts",
                created_at: 11,
              },
            },
          },
        },
      });
      handlers.onEvent("tool_result", {
        result_envelope: {
          structured_payload: {
            file_changes: {
              status: "recorded",
              records: [{
                record_id: "filechange-native-batch",
                session_id: "session:file-change",
                logical_path: "src/generated.ts",
                created_at: 12,
              }],
            },
          },
        },
      });
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:file-change", eventLogId: "chatrun:file-change", lastEventOffset: 3 };
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();
    const initialRevision = store.getState().fileChangesRevision;
    await runtime.actions.sendMessage("写一个文件。");

    expect(store.getState().fileChangesRevision).toBe(initialRevision + 2);
    expect(store.getState().fileChangeRecordsBySession["session:file-change"]?.map((record) => record.record_id)).toEqual([
      "filechange-native-batch",
      "filechange-native-single",
    ]);
  });

  it("hydrates file changes once and then relies on record signals", async () => {
    api.listFileChanges.mockResolvedValueOnce({
      records: [{
        record_id: "filechange:initial",
        session_id: "session:file-change",
        logical_path: "src/initial.ts",
        created_at: 10,
      }],
      summary: { count: 1 },
      authority: "api.file_changes.list",
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:file-change",
    });
    const runtime = new WorkspaceRuntime(store);

    await Promise.all([
      runtime.actions.hydrateFileChangesForSession("session:file-change"),
      runtime.actions.hydrateFileChangesForSession("session:file-change"),
    ]);
    runtime.actions.applyFileChangeRecord({
      record_id: "filechange:signal",
      session_id: "session:file-change",
      logical_path: "src/signal.ts",
      created_at: 11,
    });
    await runtime.actions.hydrateFileChangesForSession("session:file-change");

    expect(api.listFileChanges).toHaveBeenCalledTimes(1);
    expect(store.getState().fileChangeRecordsBySession["session:file-change"].map((record) => record.record_id)).toEqual([
      "filechange:signal",
      "filechange:initial",
    ]);
  });

  it("restores the selected chat model from the active conversation session", async () => {
    vi.useRealTimers();
    api.getModelProviderConfig.mockResolvedValue(deepseekProviderConfig("deepseek-v4-flash"));
    api.listSessions.mockResolvedValue([
      sessionSummaryWithChatModel("session:pro", "deepseek::deepseek-v4-pro", 2),
      sessionSummaryWithChatModel("session:default", "system-default", 1),
    ]);
    api.getSessionHistory.mockImplementation(async (sessionId) => ({
      id: String(sessionId),
      title: "Session",
      created_at: 1,
      updated_at: 1,
      compressed_context: "",
      conversation_state: sessionSummaryWithChatModel(
        String(sessionId),
        String(sessionId) === "session:pro" ? "deepseek::deepseek-v4-pro" : "system-default",
      ).conversation_state,
      messages: [],
    }));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:pro");
    expect(store.getState().selectedChatModelId).toBe("deepseek::deepseek-v4-pro");

    await runtime.actions.selectSession({ sessionId: "session:default" });
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:default");
    expect(store.getState().selectedChatModelId).toBe("system-default");
  });

  it("coalesces duplicate session history refreshes for the same active session", async () => {
    const sessionId = "session:coalesced-history";
    let resolveHistory: ((value: {
      messages: { role: string; content: string }[];
      conversation_state: { authority: string; permission_mode: string };
    }) => void) | undefined;
    api.getSessionHistory.mockImplementation(() => new Promise((resolve) => {
      resolveHistory = resolve;
    }));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      sessions: [{
        id: sessionId,
        title: "Coalesced History",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    const first = runtime.refreshSessionDetails(sessionId);
    const second = runtime.refreshSessionDetails(sessionId);

    expect(api.getSessionHistory).toHaveBeenCalledTimes(1);
    resolveHistory?.({
      messages: [{ role: "assistant", content: "只读取一次" }],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    await Promise.all([first, second]);

    expect(api.getSessionHistory).toHaveBeenCalledTimes(1);
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "只读取一次" },
    ]);
  });

  it("does not reuse completed session history refreshes after in-flight coalescing ends", async () => {
    const sessionId = "session:history-no-ttl";
    api.getSessionHistory
      .mockResolvedValueOnce({
        messages: [{ role: "assistant", content: "第一次读取" }],
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
      })
      .mockResolvedValueOnce({
        messages: [{ role: "assistant", content: "第二次读取" }],
        conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
      });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      sessions: [{
        id: sessionId,
        title: "No TTL History",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    await runtime.refreshSessionDetails(sessionId);
    await runtime.refreshSessionDetails(sessionId);

    expect(api.getSessionHistory).toHaveBeenCalledTimes(2);
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "第二次读取" },
    ]);
  });

  it("persists explicit chat model changes to the current session and uses them for chat runs", async () => {
    vi.useRealTimers();
    api.getModelProviderConfig.mockResolvedValue(deepseekProviderConfig("deepseek-v4-flash"));
    api.listSessions.mockResolvedValue([
      sessionSummaryWithChatModel("session:model-choice"),
    ]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();
    runtime.actions.setSelectedChatModel("deepseek::deepseek-v4-pro");
    await flushPromises();
    await runtime.actions.sendMessage("用当前会话模型回答");

    expect(api.setSessionChatModelSelection).toHaveBeenCalledWith(
      "session:model-choice",
      {
        selection_id: "deepseek::deepseek-v4-pro",
        provider: "deepseek",
        model: "deepseek-v4-pro",
        source: "user",
      },
      undefined,
    );
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toMatchObject({
      selection_id: "deepseek::deepseek-v4-pro",
      provider: "deepseek",
      model: "deepseek-v4-pro",
    });
  });

  it("writes a preselected chat model to a newly created session", async () => {
    vi.useRealTimers();
    api.getModelProviderConfig.mockResolvedValue(deepseekProviderConfig("deepseek-v4-flash"));
    api.listSessions.mockResolvedValue([]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();
    runtime.actions.setSelectedChatModel("deepseek::deepseek-v4-pro");
    await runtime.actions.sendMessage("新会话也使用我选的模型");

    expect(store.getState().currentSessionId).toBe("session:fresh");
    expect(api.setSessionChatModelSelection).toHaveBeenCalledWith(
      "session:fresh",
      {
        selection_id: "deepseek::deepseek-v4-pro",
        provider: "deepseek",
        model: "deepseek-v4-pro",
        source: "user",
      },
      undefined,
    );
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toMatchObject({
      selection_id: "deepseek::deepseek-v4-pro",
      model: "deepseek-v4-pro",
    });
  });

  it("keeps an unbound legacy session usable without loading the host default inspector file", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:unbound",
        title: "Unbound",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {},
        },
      },
    ]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:unbound");
    expect(store.getState().activeProjectRoot).toBe("");
    expect(api.loadFile).not.toHaveBeenCalled();
    expect(api.loadFileForSession).not.toHaveBeenCalled();
  });

  it("loads the default inspector file through the bound session file API", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveSessionRef"
        ? JSON.stringify({ sessionId: "session:bound", poolKey: "main-chat" })
        : null
    );
    api.getSessionSummary.mockResolvedValue({
      id: "session:bound",
      title: "Bound",
      created_at: 1,
      updated_at: 1,
      message_count: 0,
      conversation_state: {
        authority: "sessions.conversation_state",
        project_binding: {
          workspace_root: "D:/repo",
          source: "vscode",
          bound_at: 1,
          last_seen_at: 1,
          immutable: true,
          authority: "sessions.project_binding",
        },
      },
    });
    api.listSessions.mockResolvedValue([
      {
        id: "session:bound",
        title: "Bound",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "vscode",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      },
    ]);
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [{
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "session.project_binding",
        created_at: 1,
        last_seen_at: 1,
        session_count: 1,
        latest_session_at: 1,
        available: true,
        authority: "project_workspaces.workspace",
      }],
      summary: { project_count: 1 },
    });
    api.listProjectWorkspaceSessions.mockResolvedValue({
      authority: "project_workspaces.sessions",
      project_key: "workspace:repo",
      sessions: [{
        id: "session:bound",
        title: "Bound",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "vscode",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      }],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.loadFile).not.toHaveBeenCalled();
    expect(api.loadFileForSession).toHaveBeenCalledWith(
      "durable_memory/index/MEMORY.md",
      "session:bound",
      undefined,
    );
  });

  it("selects a project workspace through the native directory picker without rebinding an existing session", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:unbound",
      sessions: [{
        id: "session:unbound",
        title: "Unbound",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
        },
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectProjectWorkspaceDirectory();

    expect(api.selectProjectWorkspaceDirectory).toHaveBeenCalledTimes(1);
    expect(store.getState().activeProjectKey).toBe("workspace:repo");
    expect(store.getState().activeProjectRoot).toBe("D:/repo");
    expect(store.getState().currentSessionId).toBeNull();
    expect(api.getProjectWorkspaceTree).toHaveBeenCalledWith("workspace:repo");
    expect(api.loadFileForSession).not.toHaveBeenCalled();
  });

  it("deduplicates concurrent workspace tree refreshes for the same target", async () => {
    let resolveTree: (value: Awaited<ReturnType<typeof api.getProjectWorkspaceTree>>) => void = () => undefined;
    api.getProjectWorkspaceTree.mockImplementation(() => new Promise((resolve) => {
      resolveTree = resolve;
    }));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeProjectKey: "workspace:repo",
      activeProjectRoot: "D:/repo",
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshWorkspaceTree: () => Promise<void>;
    };

    const first = runtime.refreshWorkspaceTree();
    const second = runtime.refreshWorkspaceTree();

    expect(api.getProjectWorkspaceTree).toHaveBeenCalledTimes(1);
    resolveTree({
      root: "D:/repo",
      max_depth: 10,
      max_entries: 10000,
      total_entries: 0,
      truncated: false,
      tree: {
        name: "repo",
        path: "",
        kind: "directory",
        depth: 0,
        children: [],
        truncated: false,
      },
    });
    await Promise.all([first, second]);
    expect(store.getState().workspaceTreeLoading).toBe(false);
  });

  it("keeps startup in the unbound conversation scope when project workspaces exist", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:unbound",
      title: "Unbound",
      created_at: 1,
      updated_at: 2,
      message_count: 0,
      conversation_state: {
        authority: "sessions.conversation_state",
      },
    }]);
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [{
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "session.project_binding",
        created_at: 1,
        last_seen_at: 2,
        session_count: 1,
        latest_session_at: 2,
        available: true,
        authority: "project_workspaces.workspace",
      }],
      summary: { project_count: 1 },
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(store.getState().currentSessionId).toBe("session:unbound");
    expect(store.getState().activeProjectKey).toBe("");
    expect(store.getState().activeProjectRoot).toBe("");
    expect(api.listProjectWorkspaceSessions).not.toHaveBeenCalled();
    expect(api.getProjectWorkspaceTree).not.toHaveBeenCalled();
  });

  it("clears the active project and selects an unbound session when switching to the unbound scope", async () => {
    vi.useRealTimers();
    const boundSession = {
      id: "session:bound",
      title: "Bound",
      created_at: 1,
      updated_at: 3,
      message_count: 0,
      conversation_state: {
        authority: "sessions.conversation_state",
        project_binding: {
          workspace_root: "D:/repo",
          source: "project_workspace",
          bound_at: 1,
          last_seen_at: 3,
          immutable: true,
          authority: "sessions.project_binding",
        },
      },
    };
    const unboundSession = {
      id: "session:unbound",
      title: "Unbound",
      created_at: 1,
      updated_at: 2,
      message_count: 0,
      conversation_state: {
        authority: "sessions.conversation_state",
      },
    };
    api.listSessions.mockResolvedValue([boundSession, unboundSession]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeProjectKey: "workspace:repo",
      activeProjectRoot: "D:/repo",
      currentSessionId: "session:bound",
      sessions: [boundSession, unboundSession],
      projectSessions: [boundSession],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectProjectWorkspace("");
    await flushPromises();

    expect(store.getState().activeProjectKey).toBe("");
    expect(store.getState().activeProjectRoot).toBe("");
    expect(store.getState().projectSessions).toEqual([]);
    expect(store.getState().currentSessionId).toBe("session:unbound");
    expect(api.listProjectWorkspaceSessions).not.toHaveBeenCalled();
  });

  it("treats a cancelled project directory picker as a quiet no-op", async () => {
    vi.useRealTimers();
    api.selectProjectWorkspaceDirectory.mockRejectedValueOnce(new Error('{"detail":"project directory selection cancelled"}'));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      projectWorkspacesError: "previous error",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectProjectWorkspaceDirectory();

    expect(store.getState().projectWorkspacesLoading).toBe(false);
    expect(store.getState().projectWorkspacesError).toBe("");
    expect(store.getState().activeProjectKey).toBe("");
  });

  it("sends frontend page editor context only for the current session", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:code",
      workspaceContext: {
        project_name: "host",
        project_root: "D:/host/langchain-agent",
        backend_root: "D:/host/langchain-agent/backend",
        storage_root: "D:/host/langchain-agent/.runtime",
        editable_prefixes: ["frontend/src/"],
        readable_prefixes: ["frontend/src/"],
      },
      sessions: [{
        id: "session:code",
        title: "Code",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "vscode",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      }],
      inspectorPath: "frontend/src/App.tsx",
      inspectorContent: "export function App() { return null; }",
      inspectorDirty: true,
      sessionEditorContexts: {
        "session:code": {
          activeFilePath: "frontend/src/App.tsx",
          openFilePaths: ["frontend/src/App.tsx"],
          inspectorPath: "frontend/src/App.tsx",
          inspectorContent: "export function App() { return null; }",
          inspectorDirty: true,
          updatedAt: 1,
        },
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("检查当前文件。");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.editor_context).toMatchObject({
      source: "frontend.center_workspace",
      workspace_roots: ["D:/repo"],
      active_file: {
        path: "frontend/src/App.tsx",
        language_id: "typescriptreact",
        dirty: true,
        content_preview: {
          text: "export function App() { return null; }",
          truncated: false,
        },
      },
      open_tabs: [{
        path: "frontend/src/App.tsx",
        language_id: "typescriptreact",
        dirty: true,
        active: true,
        visible: true,
      }],
    });
    expect((api.streamChat.mock.calls[0]?.[0]?.editor_context as Record<string, any>)?.active_file?.selection).toBeUndefined();
  });

  it("does not send workspace-only editor context when no editor file is active", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:bound-without-file",
      sessions: [{
        id: "session:bound-without-file",
        title: "Bound",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "vscode",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      }],
      sessionEditorContexts: {},
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("继续修复当前绑定文件。");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.editor_context).toBeUndefined();
  });

  it("does not send the host project root as editor workspace root for unbound sessions", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:code",
      workspaceContext: {
        project_name: "host",
        project_root: "D:/host/langchain-agent",
        backend_root: "D:/host/langchain-agent/backend",
        storage_root: "D:/host/langchain-agent/.runtime",
        editable_prefixes: ["frontend/src/"],
        readable_prefixes: ["frontend/src/"],
      },
      sessions: [{
        id: "session:code",
        title: "Code",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
      inspectorPath: "frontend/src/App.tsx",
      inspectorContent: "export function App() { return null; }",
      inspectorDirty: false,
      sessionEditorContexts: {
        "session:code": {
          activeFilePath: "frontend/src/App.tsx",
          openFilePaths: ["frontend/src/App.tsx"],
          inspectorPath: "frontend/src/App.tsx",
          inspectorContent: "export function App() { return null; }",
          inspectorDirty: false,
          updatedAt: 1,
        },
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("检查当前文件。");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.editor_context).toMatchObject({
      source: "frontend.center_workspace",
      workspace_roots: [],
      active_file: {
        path: "frontend/src/App.tsx",
      },
    });
  });

  it("does not carry an opened file context into another session", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:a",
      sessions: [
        {
          id: "session:a",
          title: "A",
          created_at: 1,
          updated_at: 2,
          message_count: 0,
        },
        {
          id: "session:b",
          title: "B",
          created_at: 1,
          updated_at: 3,
          message_count: 0,
        },
      ],
      inspectorPath: "frontend/src/A.tsx",
      inspectorContent: "export const a = 1;",
      sessionEditorContexts: {
        "session:a": {
          activeFilePath: "frontend/src/A.tsx",
          openFilePaths: ["frontend/src/A.tsx"],
          inspectorPath: "frontend/src/A.tsx",
          inspectorContent: "export const a = 1;",
          inspectorDirty: false,
          updatedAt: 1,
        },
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectSession({ sessionId: "session:b", poolKey: "main-chat" });
    await runtime.actions.sendMessage("普通问题。");

    expect(store.getState().inspectorPath).toBe("durable_memory/index/MEMORY.md");
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.session_id).toBe("session:b");
    expect(api.streamChat.mock.calls[0]?.[0]?.editor_context).toBeUndefined();
  });

  it("clears frontend editor context after the session closes its last file", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:code",
      sessions: [{
        id: "session:code",
        title: "Code",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
      inspectorPath: "frontend/src/App.tsx",
      inspectorContent: "export const app = true;",
      sessionEditorContexts: {
        "session:code": {
          activeFilePath: "frontend/src/App.tsx",
          openFilePaths: ["frontend/src/App.tsx"],
          inspectorPath: "frontend/src/App.tsx",
          inspectorContent: "export const app = true;",
          inspectorDirty: false,
          updatedAt: 1,
        },
      },
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.setSessionEditorPageState({ activeFilePath: "", openFilePaths: [] });
    await runtime.actions.sendMessage("不带文件上下文。");

    expect(store.getState().inspectorPath).toBe("durable_memory/index/MEMORY.md");
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.editor_context).toBeUndefined();
  });

  it("opens graph task operations inside the foreground graph task workspace by default", () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "chat",
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.openTaskGraphWorkspace({ graph_id: "graph.dev.review" });

    expect(store.getState().activeWorkspaceView).toBe("creative");
    expect(store.getState().taskGraphWorkspaceTarget).toMatchObject({
      layer: "task-graph",
      mode: "monitor",
      graph_id: "graph.dev.review",
    });
  });

  it("opens graph definition editing inside the task system", () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "creative",
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.openTaskGraphWorkspace({ graph_id: "graph.dev.review", mode: "editor" });

    expect(store.getState().activeWorkspaceView).toBe("task-system");
    expect(store.getState().taskGraphWorkspaceTarget).toMatchObject({
      layer: "task-graph",
      mode: "editor",
      graph_id: "graph.dev.review",
    });
  });

  it("loads graph monitor details when a run monitor graph signal is opened", async () => {
    api.getGraphRunMonitor.mockRejectedValue(new Error('{"detail":"GraphHarnessConfig not found"}'));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([
      itemForMonitor({
        task_run_id: "taskrun:old-master",
        session_id: "session",
        title: "旧图任务",
        graph_run_id: "grun:old-master",
        graph_harness_config_id: "ghcfg:old-missing",
        graph_id: "graph.writing.master",
        has_graph_run: true,
        route: { kind: "task_graph_run", session_id: "session", task_run_id: "taskrun:old-master", graph_id: "graph.writing.master", graph_run_id: "grun:old-master", graph_harness_config_id: "ghcfg:old-missing" },
      }),
    ]));

    runtime.actions.openRunMonitorSignal("taskrun:old-master");
    await Promise.resolve();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(6000);

    expect(api.getGraphRunMonitor).toHaveBeenCalledWith("grun:old-master", "ghcfg:old-missing", 80, {
      workspace_view: "graph_task",
      task_environment_id: "",
      project_id: "",
    });
    expect(store.getState().taskGraphMonitorBinding?.task_run_id).toBe("taskrun:old-master");
    expect(store.getState().taskGraphMonitorError).toBe("");
  });

  it("stops a bound GraphRun through its owning TaskRun", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskGraphMonitorBinding: {
        task_run_id: "taskrun:graph-master",
        graph_run_id: "grun:graph-master",
        graph_harness_config_id: "ghcfg:graph-master",
        bound_at: 1,
      },
      taskGraphBoundRunMonitor: {
        graph_run_id: "grun:graph-master",
        task_run_id: "taskrun:graph-master",
        task_run: {
          task_run_id: "taskrun:graph-master",
          status: "running",
        },
        graph_loop_state: { status: "running" },
      } as never,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.stopBoundTaskGraphRun();

    expect(api.stopOrchestrationHarnessTaskRun).toHaveBeenCalledWith("taskrun:graph-master", "user_stop_graph_run", "");
    expect(store.getState().taskGraphMonitorActionLoading).toBe(false);
  });

  it("pauses a bound GraphRun through graph run control", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskGraphAutoAdvanceEnabled: true,
      taskGraphAutoAdvancePending: true,
      taskGraphMonitorBinding: {
        task_run_id: "taskrun:graph-master",
        graph_run_id: "grun:graph-master",
        graph_harness_config_id: "ghcfg:graph-master",
        bound_at: 1,
      },
      taskGraphBoundRunMonitor: {
        graph_run_id: "grun:graph-master",
        task_run_id: "taskrun:graph-master",
        task_run: {
          task_run_id: "taskrun:graph-master",
          status: "running",
        },
        graph_loop_state: { status: "running" },
      } as never,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.pauseBoundTaskGraphRun();

    expect(api.pauseGraphRun).toHaveBeenCalledWith("grun:graph-master", {
      graph_harness_config_id: "ghcfg:graph-master",
      session_scope: undefined,
      reason: "user_pause_graph_run",
    });
    expect(store.getState().taskGraphAutoAdvanceEnabled).toBe(false);
    expect(store.getState().taskGraphAutoAdvancePending).toBe(false);
    expect(store.getState().taskGraphMonitorActionLoading).toBe(false);
  });

  it("manually continues a bound GraphRun by dispatching ready nodes", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskGraphMonitorBinding: {
        task_run_id: "taskrun:graph-master",
        graph_run_id: "grun:graph-master",
        graph_harness_config_id: "ghcfg:graph-master",
        session_scope: {
          workspace_view: "task_environment",
          task_environment_id: "env.general.workspace",
          project_id: "project.general.workspace.demo",
        },
        bound_at: 1,
      },
      taskGraphBoundRunMonitor: {
        graph_run_id: "grun:graph-master",
        task_run_id: "taskrun:graph-master",
        task_run: {
          task_run_id: "taskrun:graph-master",
          status: "running",
        },
        graph_loop_state: { status: "running", ready_node_ids: ["draft"] },
      } as never,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.continueBoundTaskGraphRun();

    expect(api.resumeGraphRun).not.toHaveBeenCalled();
    expect(api.submitGraphRunUntilIdle).toHaveBeenCalledWith("grun:graph-master", {
      graph_harness_config_id: "ghcfg:graph-master",
      session_scope: {
        workspace_view: "task_environment",
        task_environment_id: "env.general.workspace",
        project_id: "project.general.workspace.demo",
      },
      max_node_executions: 1,
      max_loop_iterations: 4,
      max_dispatches: 1,
      max_dispatch_requests: 1,
    });
    expect(store.getState().taskGraphMonitorActionLoading).toBe(false);
  });

  it("resumes graph run control before continuing a paused GraphRun", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskGraphMonitorBinding: {
        task_run_id: "taskrun:graph-master",
        graph_run_id: "grun:graph-master",
        graph_harness_config_id: "ghcfg:graph-master",
        bound_at: 1,
      },
      taskGraphBoundRunMonitor: {
        graph_run_id: "grun:graph-master",
        task_run_id: "taskrun:graph-master",
        task_run: {
          task_run_id: "taskrun:graph-master",
          status: "running",
        },
        task_run_monitor: {
          task_run_id: "taskrun:graph-master",
          control_state: "paused",
        },
        graph_loop_state: { status: "running", ready_node_ids: ["draft"] },
      } as never,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.continueBoundTaskGraphRun();

    expect(api.resumeGraphRun).toHaveBeenCalledWith("grun:graph-master", {
      graph_harness_config_id: "ghcfg:graph-master",
      session_scope: undefined,
      reason: "run_monitor_continue_graph_run",
    });
    expect(api.submitGraphRunUntilIdle).toHaveBeenCalledWith("grun:graph-master", {
      graph_harness_config_id: "ghcfg:graph-master",
      session_scope: undefined,
      max_node_executions: 1,
      max_loop_iterations: 4,
      max_dispatches: 1,
      max_dispatch_requests: 1,
    });
    expect(api.resumeGraphRun.mock.invocationCallOrder[0]).toBeLessThan(
      api.submitGraphRunUntilIdle.mock.invocationCallOrder[0],
    );
  });

  it("opens a run monitor agent signal in its owning session", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };

    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionTokens.mockResolvedValue(null);
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue(null);

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([
      itemForMonitor({
        task_run_id: "taskrun:turn:session-a:1:abc",
        session_id: "session-a",
        task_id: "task:turn:session-a:1",
        title: "会话运行",
        status: "waiting_executor",
        terminal_reason: "waiting_executor",
        lifecycle: "waiting",
        latest_event_type: "task_run_lifecycle_waiting_executor",
        route: { kind: "agent_runtime_run", session_id: "session-a", task_run_id: "taskrun:turn:session-a:1:abc" },
      }),
    ]));

    runtime.actions.openRunMonitorSignal("taskrun:turn:session-a:1:abc");

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().currentSessionId).toBe("session-a");
    expect(store.getState().runMonitorSelectedTaskRunId).toBe("taskrun:turn:session-a:1:abc");
    expect(store.getState().centerWorkspaceTarget).toBeNull();
  });

  it("opens a run monitor agent signal without switching the visible session list scope", async () => {
    vi.useRealTimers();
    api.getSessionRuntimeProjection.mockResolvedValue({
      messages: [{ role: "user", content: "开发任务" }],
      runtime_attachments: [],
    });
    api.getSessionTokens.mockResolvedValue(null);
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue(null);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "chat",
      currentSessionId: "session-general",
      activeSessionScope: {
        workspace_view: "task_environment",
        task_environment_id: "env.general.workspace",
        project_id: "",
      },
      sessions: [{
        id: "session-general",
        title: "General",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
        scope: {
          workspace_view: "task_environment",
          task_environment_id: "env.general.workspace",
          project_id: "",
        },
      }],
    });
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([
      itemForMonitor({
        task_run_id: "taskrun:turn:session-dev:1:abc",
        session_id: "session-dev",
        task_id: "task.dev.calculator",
        title: "开发计算器",
        navigation_target: {
          target_kind: "session",
          workspace_view: "task_environment",
          task_environment_id: "env.coding.vibe_workspace",
          session_id: "session-dev",
          task_run_id: "taskrun:turn:session-dev:1:abc",
          task_instance_id: "taskrun:turn:session-dev:1:abc",
          mode: "conversation",
        },
        route: { kind: "agent_runtime_run", session_id: "session-dev", task_run_id: "taskrun:turn:session-dev:1:abc" },
      }),
    ]));

    runtime.actions.openRunMonitorSignal("taskrun:turn:session-dev:1:abc");
    await flushPromises(12);

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().currentSessionId).toBe("session-dev");
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      source: "workspace-mode",
    });
    expect(store.getState().chatTaskEnvironmentBinding).toBeNull();
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.getSessionHistory).toHaveBeenCalledWith("session-dev", {
      workspace_view: "task_environment",
      task_environment_id: "env.coding.vibe_workspace",
    });
  });

  it("ignores stale run monitor snapshots after a newer revision has landed", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };

    const newerRun = itemForMonitor({ task_run_id: "taskrun:newer", title: "新任务" });
    const olderRun = itemForMonitor({ task_run_id: "taskrun:older", title: "旧任务" });

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([newerRun], { revision: "rtmon:20:new", updated_at: 20 }));
    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([olderRun], { revision: "rtmon:10:old", updated_at: 10 }));

    expect(store.getState().runMonitorRevision).toBe("rtmon:20:new");
    expect(store.getState().runMonitorSelectedTaskRunId).toBe("taskrun:newer");
  });

  it("does not let a stale detail response overwrite the currently selected monitor detail", async () => {
    vi.useRealTimers();
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyRunMonitorSnapshot: (monitor: ReturnType<typeof monitorForTest>) => void;
    };
    let resolveOldDetail: (value: unknown) => void = () => undefined;
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveOldDetail = resolve;
      }),
    );
    const oldRun = itemForMonitor({ task_run_id: "taskrun:old", title: "旧任务" });
    const newRun = itemForMonitor({ task_run_id: "taskrun:new", title: "新任务" });

    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([oldRun], { revision: "rtmon:10:old", updated_at: 10 }));
    runtime.actions.openRunMonitorSignal("taskrun:old");
    await flushPromises(2);
    runtimeHarness.applyRunMonitorSnapshot(monitorForTest([newRun], { revision: "rtmon:20:new", updated_at: 20 }));
    resolveOldDetail({ monitor: { status: "running", task_run: { task_run_id: "taskrun:old" } } });
    await flushPromises(4);

    expect(store.getState().runMonitorRevision).toBe("rtmon:20:new");
    expect(store.getState().runMonitorSelectedTaskRunId).toBe("taskrun:new");
    expect(store.getState().runMonitorSelectedDetail).toBeNull();
  });

  it("applies run monitor action results to the shared monitor store", async () => {
    vi.useRealTimers();
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const completed = itemForMonitor({
      task_run_id: "taskrun:completed",
      title: "已完成任务",
      status: "completed",
      lifecycle: "completed",
      bucket: "completed",
      resource_class: "static",
      is_live: false,
    });
    const nextMonitor = monitorForTest([completed], { revision: "rtmon:30:cleared", updated_at: 30 }) as ReturnType<typeof monitorForTest> & {
      management?: Record<string, unknown>;
      signals: Array<Record<string, unknown>>;
    };
    nextMonitor.management = {
      authority: "runtime_monitor.management",
      policy: {},
      summary: { hidden: 1, visible: 0, total: 1 },
      lanes: {
        hidden: [{
          ...nextMonitor.signals[0],
          visibility: { hidden: true, visible: false, lane: "hidden", hidden_reason: "user_cleared" },
          actions: [{ action: "restore_to_monitor", label: "恢复显示", enabled: true }],
        }],
      },
    };
    nextMonitor.signals = [];
    api.executeRunMonitorAction.mockResolvedValueOnce({
      authority: "runtime_monitor.actions",
      accepted: true,
      action: "clear_from_monitor",
      target: { signal_id: "taskrun:completed" },
      effects: {},
      monitor: nextMonitor,
      updated_at: 30,
    });

    const result = await runtime.actions.runMonitorAction({
      action: "clear_from_monitor",
      signal_id: "taskrun:completed",
    });

    expect(result?.accepted).toBe(true);
    expect(api.executeRunMonitorAction).toHaveBeenCalledWith({
      action: "clear_from_monitor",
      signal_id: "taskrun:completed",
      source_revision: "",
    });
    expect(store.getState().runMonitorRevision).toBe("rtmon:30:cleared");
    expect(store.getState().runMonitorLastActionResult?.action).toBe("clear_from_monitor");
    expect(store.getState().runMonitorActionLoading).toBe("");
  });

  it("starts the run monitor with an SSE stream and consumes file change signals", async () => {
    const instances: Array<{ close: ReturnType<typeof vi.fn>; listeners: Record<string, (event: MessageEvent) => void> }> = [];
    class MockEventSource {
      close = vi.fn();
      listeners: Record<string, (event: MessageEvent) => void> = {};

      constructor(_url: string) {
        instances.push(this);
      }

      addEventListener(event: string, handler: (message: MessageEvent) => void) {
        this.listeners[event] = handler;
      }
    }
    vi.stubGlobal("EventSource", MockEventSource);
    api.getRunMonitor.mockResolvedValue(monitorForTest([]));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    runtime.startRunMonitor();
    await vi.advanceTimersByTimeAsync(0);

    expect(instances).toHaveLength(1);
    expect(api.getRunMonitor).not.toHaveBeenCalled();
    expect(store.getState().runMonitorStreamStatus).toBe("connecting");

    const initialRevision = store.getState().fileChangesRevision;
    instances[0].listeners.runtime_monitor_file_change?.({
      data: JSON.stringify({
        source: "runtime_event_log",
        record_id: "filechange-sse",
        session_id: "session:sse",
        logical_path: "signal-wrapper-only.ts",
        file_change_record: {
          record_id: "filechange-sse",
          session_id: "session:sse",
          logical_path: "src/app.ts",
          before_sha256: "sha-before",
          after_sha256: "sha-after",
        },
      }),
    } as MessageEvent);
    expect(store.getState().fileChangesRevision).toBe(initialRevision + 1);
    expect(store.getState().fileChangeRecordsBySession["session:sse"]?.[0]).toMatchObject({
      record_id: "filechange-sse",
      session_id: "session:sse",
      logical_path: "src/app.ts",
      before_sha256: "sha-before",
      after_sha256: "sha-after",
    });
  });

  it("does not reopen the run monitor stream after disposal", async () => {
    const instances: Array<{ close: ReturnType<typeof vi.fn>; listeners: Record<string, (event: MessageEvent) => void> }> = [];
    class MockEventSource {
      close = vi.fn();
      listeners: Record<string, (event: MessageEvent) => void> = {};

      constructor(_url: string) {
        instances.push(this);
      }

      addEventListener(event: string, handler: (message: MessageEvent) => void) {
        this.listeners[event] = handler;
      }
    }
    vi.stubGlobal("EventSource", MockEventSource);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    runtime.dispose();
    runtime.startRunMonitor();
    await vi.advanceTimersByTimeAsync(0);

    expect(instances).toHaveLength(1);
    expect(instances[0].close).toHaveBeenCalledTimes(1);
    expect(store.getState().runMonitorStreamStatus).toBe("closed");
  });

  it("does not start legacy run monitor polling when SSE is unavailable", async () => {
    vi.stubGlobal("EventSource", undefined);
    api.getRunMonitor.mockResolvedValue(monitorForTest([]));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getRunMonitor).not.toHaveBeenCalled();
    expect(store.getState().runMonitorStreamStatus).toBe("disconnected");

    await vi.advanceTimersByTimeAsync(30000);
    expect(api.getRunMonitor).not.toHaveBeenCalled();
  });

  it("ignores legacy runtime_event payloads from the monitor stream", () => {
    const taskRunId = "taskrun:turn:session:stream:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stream",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:stream:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:stream:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:stream",
          task_id: "task:turn:session:stream:1",
          latest_event_type: "step_summary_recorded",
          route: { kind: "agent_runtime_run", session_id: "session:stream", task_run_id: taskRunId },
        }),
      ]),
      runtime_event: {
        event_id: "rtevt:step:1",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 1,
        created_at: 10,
        payload: {
          task_run_id: taskRunId,
          step: "task_executor_started",
          status: "running",
          summary: "已接上当前工作，正在整理上下文。",
          public_progress_note: "我正在整理任务上下文。",
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:stream:1" },
        authority: "orchestration.runtime_event",
      },
    });
    expect(store.getState().runMonitor).not.toBeNull();
    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("surfaces runtime restart recovery as an explicit waiting-resume state", () => {
    const taskRunId = "taskrun:turn:session:restart:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:restart",
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:restart",
          task_id: "task:turn:session:restart:1",
          status: "waiting_executor",
          lifecycle: "waiting",
          bucket: "waiting",
          activity_state: "waiting",
          activity_label: "连接恢复后待续跑",
          recovery_cause: "runtime_restart",
          control_reason: "runtime_restart_waiting_resume",
          activity: {
            detail: "连接已恢复，任务已停在可恢复边界；点击继续或发送继续后会从当前任务继续调度。",
          },
          route: { kind: "agent_runtime_run", session_id: "session:restart", task_run_id: taskRunId },
        }),
      ]),
    });

    expect(store.getState().sessionActivity).toMatchObject({
      level: "waiting",
      title: "连接恢复后待续跑",
      detail: expect.stringContaining("连接已恢复"),
    });
  });

  it("does not hydrate the current session from monitor snapshots before output commit ack", async () => {
    const taskRunId = "taskrun:turn:session:stream-running:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stream-running",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:stream-running:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:stream-running:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };
    api.getSessionRuntimeProjection.mockClear();

    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:stream-running",
          task_id: "task:turn:session:stream-running:1",
          status: "running",
          lifecycle: "running",
          activity_state: "running",
          task_projection: {
            current_action: {
              kind: "work",
              title: "继续执行任务",
            },
          },
        }),
      ], { revision: "rtmon:10:running" }),
    });

    expect(store.getState().runMonitorRevision).toBe("rtmon:10:running");
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
    await Promise.resolve();
  });

  it("does not hydrate the current session from monitor snapshots even after output commit ack", async () => {
    const taskRunId = "taskrun:turn:session:stream-commit:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stream-commit",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:stream-commit:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:stream-commit:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };
    api.getSessionRuntimeProjection.mockClear();

    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:stream-commit",
          task_id: "task:turn:session:stream-commit:1",
          status: "completed",
          lifecycle: "completed",
          activity_state: "completed",
          is_live: false,
          is_running: false,
          session_output_commit: {
            state: "committed",
            session_id: "session:stream-commit",
            turn_id: "turn:session:stream-commit:1",
            task_run_id: taskRunId,
            commit_event_offset: 12,
            content_sha256: "sha256:test",
          },
          task_projection: {
            current_action: {
              kind: "closeout",
              title: "输出记录",
              state: "completed",
            },
          },
        }),
      ], { revision: "rtmon:10:commit" }),
    });

    expect(store.getState().runMonitorRevision).toBe("rtmon:10:commit");
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
    await Promise.resolve();
  });

  it("does not use repeated monitor output commit ack keys as hydrate triggers", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const taskRunId = "taskrun:turn:session:stream-commit-once:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stream-commit-once",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:stream-commit-once:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:stream-commit-once:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };
    const commitItem = (offset: number, hash: string) => itemForMonitor({
      task_run_id: taskRunId,
      session_id: "session:stream-commit-once",
      task_id: "task:turn:session:stream-commit-once:1",
      status: "completed",
      lifecycle: "completed",
      activity_state: "completed",
      is_live: false,
      is_running: false,
      session_output_commit: {
        state: "committed",
        session_id: "session:stream-commit-once",
        turn_id: "turn:session:stream-commit-once:1",
        task_run_id: taskRunId,
        commit_event_offset: offset,
        content_sha256: hash,
      },
    });
    api.getSessionRuntimeProjection.mockClear();

    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([commitItem(12, "sha256:first")], { revision: "rtmon:commit-once:1" }),
    });
    vi.advanceTimersByTime(4_000);
    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([commitItem(12, "sha256:first")], { revision: "rtmon:commit-once:2" }),
    });
    vi.advanceTimersByTime(4_000);
    runtime.applyRunMonitorStreamPayload({
      monitor: monitorForTest([commitItem(13, "sha256:second")], { revision: "rtmon:commit-once:3" }),
    });

    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("does not project runtime events from a stale run monitor snapshot", () => {
    const taskRunId = "taskrun:turn:session:stale-stream:1:abc";
    const currentMonitor = monitorForTest([
      itemForMonitor({
        task_run_id: taskRunId,
        session_id: "session:stale-stream",
        task_id: "task:turn:session:stale-stream:1",
      }),
    ], { revision: "rtmon:2:test" });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stale-stream",
      runMonitor: currentMonitor as any,
      runMonitorRevision: "rtmon:2:test",
      activeTurnSnapshot: {
        turn_id: "turn:session:stale-stream:1",
        task_run_id: taskRunId,
      },
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:stale-stream",
          task_id: "task:turn:session:stale-stream:1",
        }),
      ], { revision: "rtmon:1:test" }),
      runtime_event: {
        event_id: "rtevt:stale:1",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 1,
        created_at: 9,
        payload: {
          task_run_id: taskRunId,
          step: "task_executor_started",
          status: "running",
          public_progress_note: "旧事件不应投影。",
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:stale-stream:1" },
        authority: "orchestration.runtime_event",
      },
    });

    expect(store.getState().runMonitorRevision).toBe("rtmon:2:test");
    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("ignores raw tool observation runtime_event payloads from the monitor stream", () => {
    const taskRunId = "taskrun:turn:session:observation:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:observation",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:observation:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:observation:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:observation",
          task_id: "task:turn:session:observation:1",
          latest_event_type: "step_summary_recorded",
          route: { kind: "agent_runtime_run", session_id: "session:observation", task_run_id: taskRunId },
        }),
      ]),
      runtime_event: {
        event_id: "rtevt:observation",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 12,
        created_at: 12,
        payload: {
          task_run_id: taskRunId,
          step: "task_tool_observation_recorded:3",
          status: "running",
          summary: "工具调用已完成，正在根据结果继续。",
          agent_brief_output: JSON.stringify({
            ok: false,
            error: "Image API request timed out",
            retryable: true,
          }),
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:observation:1" },
        authority: "orchestration.runtime_event",
      },
    });

    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("does not project system tool step summaries from the legacy monitor stream", () => {
    const taskRunId = "taskrun:turn:session:tool-system:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:tool-system",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:tool-system:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:tool-system:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    for (const payload of [
      {
        step: "task_tool_batch_started:4",
        status: "running",
        summary: "执行 7 个工具调用：读取文件 backend/harness/runtime/compiler.py 等。",
        presentation_source: "system.tool_call_status",
      },
      {
        step: "task_tool_repair_required:4",
        status: "running",
        summary: "工具调用失败，正在根据失败原因调整处理路径。",
      },
    ]) {
      runtime.applyRunMonitorStreamPayload({
        source: "runtime_event_log",
        monitor: monitorForTest([
          itemForMonitor({
            task_run_id: taskRunId,
            session_id: "session:tool-system",
            task_id: "task:turn:session:tool-system:1",
            latest_event_type: "step_summary_recorded",
            route: { kind: "agent_runtime_run", session_id: "session:tool-system", task_run_id: taskRunId },
          }),
        ]),
        runtime_event: {
          event_id: `rtevt:${payload.step}`,
          run_id: taskRunId,
          event_type: "step_summary_recorded",
          offset: 14,
          created_at: 14,
          payload: {
            task_run_id: taskRunId,
            ...payload,
          },
          refs: { task_run_ref: taskRunId, turn_ref: "turn:session:tool-system:1" },
          authority: "orchestration.runtime_event",
        },
      });
    }

    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("does not synthesize generic successful tool observation feedback", () => {
    const taskRunId = "taskrun:turn:session:generic-observation:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:generic-observation",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:generic-observation:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:generic-observation:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:generic-observation",
          task_id: "task:turn:session:generic-observation:1",
          latest_event_type: "step_summary_recorded",
          route: { kind: "agent_runtime_run", session_id: "session:generic-observation", task_run_id: taskRunId },
        }),
      ]),
      runtime_event: {
        event_id: "rtevt:generic-observation",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 13,
        created_at: 13,
        payload: {
          task_run_id: taskRunId,
          step: "task_tool_observation_recorded:4",
          status: "running",
          summary: "工具调用已完成，正在根据结果继续。",
          agent_brief_output: JSON.stringify({ ok: true }),
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:generic-observation:1" },
        authority: "orchestration.runtime_event",
      },
    });

    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("ignores public projection envelopes carried by legacy monitor events", () => {
    const taskRunId = "taskrun:turn:session:public-delta:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:public-delta",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0, sourceTurnId: "turn:session:public-delta:1" },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1, sourceTurnId: "turn:session:public-delta:1" },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      runtime_event: {
        event_id: "rtevt:public-delta",
        run_id: taskRunId,
        event_type: "model_action_request_received",
        offset: 4,
        created_at: 14,
        payload: {
          model_action_request: {
            request_id: "act:public-delta",
            action_type: "respond",
            public_progress_note: "我正在公开说明当前判断。",
          },
        },
        refs: {},
        authority: "orchestration.runtime_event",
        public_projection_authority: "public_stream.public_projection.v1",
        public_event_type: "model_action_admission",
        public_projection_envelope: anchoredStatusProjectionEnvelope({
          projectionId: "publicproj:public-delta",
          runId: taskRunId,
          taskRunId,
          turnId: "turn:session:public-delta:1",
          itemId: "status:public-delta",
          text: "我正在公开说明当前判断。",
        }),
      },
    });

    expect(store.getState().messages[1]?.projectionView).toBeUndefined();
  });

  it("does not hydrate session details from monitor snapshots while a chat stream is active", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:active-stream",
      activeStreamSessionIds: ["session:active-stream"],
      isStreaming: true,
      messages: [
        { id: "assistant:active-stream", role: "assistant", content: "正在处理。", toolCalls: [], retrievals: [], sourceIndex: 0 },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "initial",
      monitor: monitorForTest([]),
    });
    await flushPromises(4);

    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
  });

  it("does not show internal agent todo observations as user-facing observation rows", () => {
    const taskRunId = "taskrun:turn:session:todo-observation:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:todo-observation",
      messages: [
        { id: "user:1", role: "user", content: "开始长任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "任务已接管。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      applyRunMonitorStreamPayload: (payload: Record<string, unknown>) => void;
    };

    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      monitor: monitorForTest([
        itemForMonitor({
          task_run_id: taskRunId,
          session_id: "session:todo-observation",
          task_id: "task:turn:session:todo-observation:1",
          latest_event_type: "step_summary_recorded",
          route: { kind: "agent_runtime_run", session_id: "session:todo-observation", task_run_id: taskRunId },
        }),
      ]),
      runtime_event: {
        event_id: "rtevt:todo-observation",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 12,
        created_at: 12,
        payload: {
          task_run_id: taskRunId,
          step: "task_tool_observation_recorded:3",
          status: "running",
          summary: "工具调用已完成，正在根据结果继续。",
          agent_brief_output: JSON.stringify({
            status: "ok",
            plan_id: "agent-todo:test",
            items: [{ todo_id: "step1", status: "completed" }],
          }),
        },
        refs: { task_run_ref: taskRunId },
        authority: "orchestration.runtime_event",
      },
    });

    const visibleState = JSON.stringify({
      messages: store.getState().messages,
      activeProjectionsByKey: store.getState().activeProjectionsByKey,
    });
    expect(visibleState).not.toContain("agent-todo:test");
  });

  it("does not start TaskGraph detail polling while a chat stream is active", async () => {
    api.streamChat.mockImplementation(() => new Promise(() => undefined));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:streaming",
      sessions: [{
        id: "session:streaming",
        title: "Streaming",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.bindTaskGraphMonitorRun({
      task_run_id: "taskrun:bound",
      graph_run_id: "grun:bound",
      graph_harness_config_id: "ghcfg:bound",
      graph_id: "graph:test",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getGraphRunMonitor).not.toHaveBeenCalled();

    void runtime.actions.sendMessage("你好").catch(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(4999);
    expect(api.getGraphRunMonitor).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(api.getGraphRunMonitor).not.toHaveBeenCalled();
  });

  it("refreshes session task monitor once after chat stream hands off to a background task", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("agent_turn_terminal", {
        active_turn_id: "turn:session:background:1",
        runtime_task_run_id: "taskrun:background",
        event: {
          event_id: "rtevt:handoff",
          run_id: "turnrun:test",
          created_at: 2,
          payload: {
            status: "task_executor_scheduled",
            terminal_reason: "task_executor_scheduled",
            task_run: {
              task_run_id: "taskrun:background",
              status: "running",
            },
          },
        },
      });
      handlers.onEvent("done", {
        content: "任务已进入后台执行。",
        answer_channel: "task_control",
        terminal_reason: "task_executor_scheduled",
        runtime_task_run_id: "taskrun:background",
        active_turn_id: "turn:session:background:1",
      });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: "taskrun:background",
      monitor: {
        task_run_id: "taskrun:background",
        session_id: "session:background",
        status: "running",
        task_run: {
          task_run_id: "taskrun:background",
          status: "running",
        },
      },
      task_runs: [],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:background",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始后台任务");

    expect(api.getOrchestrationHarnessSessionLiveMonitor).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1500);
    expect(api.getOrchestrationHarnessSessionLiveMonitor).toHaveBeenCalledTimes(1);
    expect(store.getState().sessionActivity.title).toBe("");
    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session:background:1",
      task_run_id: "taskrun:background",
    });
    expect(store.getState().taskGraphLiveMonitor?.task_run_id).toBe("taskrun:background");
  });

  it("queues later main-chat input through the backend after task handoff", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", {
        content: "任务已进入后台执行。",
        answer_channel: "task_control",
        terminal_reason: "task_executor_scheduled",
        runtime_task_run_id: "taskrun:background",
        active_turn_id: "turn:session:background:1",
      });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:background",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始后台任务");
    await runtime.actions.sendMessage("暂停一下");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:background", "暂停一下");
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
  });

  it("keeps task handoff done events invisible in session activity", () => {
    let transition = startStreamingTurn(getDefaultState(), "开始后台任务");
    const activityBeforeHandoffDone = transition.state.sessionActivity;

    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "任务已进入后台执行。",
      answer_channel: "task_control",
      terminal_reason: "task_executor_scheduled",
      runtime_task_run_id: "taskrun:background",
      active_turn_id: "turn:session:background:1",
    });

    expect(transition.state.sessionActivity).toBe(activityBeforeHandoffDone);
    expect(transition.state.activeTurnSnapshot).toMatchObject({
      task_run_id: "taskrun:background",
      state: "waiting_executor",
    });
  });

  it("releases active-turn routing after a completed backend closeout signal", async () => {
    const taskRunId = "taskrun:session-closeout:1";
    const activeTurnId = "turn:session-closeout:1";
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("runtime_status", {
          title: "任务运行中",
          state: "running",
          phase: "task_run",
          runtime_task_run_id: taskRunId,
          active_turn_id: activeTurnId,
        });
        handlers.onEvent("turn_completed", {
          status: "completed",
          task_run_id: taskRunId,
          runtime_task_run_id: taskRunId,
          active_turn_id: activeTurnId,
          turn_id: activeTurnId,
          completion_state: "completed",
          terminal_reason: "completed",
        });
        return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:closeout", eventLogId: "chatrun:closeout", lastEventOffset: 2 };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("done", { content: "新问题已正常发送" });
        return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:after-closeout", eventLogId: "chatrun:after-closeout", lastEventOffset: 1 };
      });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:closeout",
      sessions: [{
        id: "session:closeout",
        title: "Closeout",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始任务");

    expect(store.getState().activeTurnSnapshot).toBeNull();

    await runtime.actions.sendMessage("收口后的新问题");

    expect(api.enqueueQueuedChatInput).not.toHaveBeenCalled();
    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      message: "收口后的新问题",
      session_id: "session:closeout",
      active_turn_input_policy: "auto",
      expected_active_turn_id: "",
    });
    expect(store.getState().sessionActivity.event).not.toBe("user_input_queued");
  });

  it("queues active-task input through the backend while the main chat stream is still open", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:streaming",
      activeStreamSessionIds: ["session:streaming"],
      isStreaming: true,
      activeTurnSnapshot: {
        turn_id: "turn:session:streaming:1",
        task_run_id: "taskrun:streaming",
        state: "running_task",
      },
      taskGraphLiveMonitor: itemForMonitor({
        session_id: "session:streaming",
        task_run_id: "taskrun:streaming",
        status: "running",
        execution_runtime_kind: "single_agent_task",
      }) as any,
      messages: [
        { id: "assistant:main", role: "assistant", content: "正在处理。", toolCalls: [], retrievals: [], sourceIndex: 0 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充：先检查边界。");

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:streaming", "补充：先检查边界。");
    expect(store.getState().activeStreamSessionIds).toEqual(["session:streaming"]);
    expect(store.getState().taskGraphLiveMonitor?.task_run_id).toBe("taskrun:streaming");
    expect(store.getState().messages.some((message) => message.content === "补充：先检查边界。")).toBe(true);
    expect(store.getState().sessionActivity.event).toBe("user_input_queued");
  });

  it("queues input during an ordinary active chat stream instead of sending steer without a task run", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:plain-stream",
      activeStreamSessionIds: ["session:plain-stream"],
      isStreaming: true,
      activeTurnSnapshot: {
        turn_id: "turn:session:plain-stream:1",
        state: "running_task",
      },
      messages: [
        { id: "assistant:plain", role: "assistant", content: "正在回答。", toolCalls: [], retrievals: [], sourceIndex: 0 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充：先查官方说明。");

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:plain-stream", "补充：先查官方说明。");
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
    expect(store.getState().messages.some((message) => message.content === "补充：先查官方说明。")).toBe(true);
  });

  it("queues input for a detached active model turn instead of starting a competing run", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:detached-model-turn",
      activeStreamSessionIds: [],
      isStreaming: false,
      activeTurnSnapshot: {
        turn_id: "turn:session:detached-model-turn:1",
        state: "model_turn",
      },
      messages: [
        { id: "assistant:detached", role: "assistant", content: "正在处理主题设置。", toolCalls: [], retrievals: [], sourceIndex: 0 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("只要加几个主题就行了");

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:detached-model-turn", "只要加几个主题就行了");
    expect(store.getState().messages.some((message) => message.content === "只要加几个主题就行了")).toBe(true);
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
  });

  it("starts a new run after a terminal active turn snapshot", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:terminal-model-turn",
      activeTurnSnapshot: {
        turn_id: "turn:session:terminal-model-turn:1",
        state: "terminal",
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始一个新问题");

    expect(api.enqueueQueuedChatInput).not.toHaveBeenCalled();
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      message: "开始一个新问题",
      session_id: "session:terminal-model-turn",
      active_turn_input_policy: "auto",
    });
  });

  it("keeps active stream input queued when the active task is paused", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:paused",
      activeStreamSessionIds: ["session:paused"],
      isStreaming: true,
      activeTurnSnapshot: {
        turn_id: "turn:session:paused:1",
        task_run_id: "taskrun:paused",
        state: "running_task",
      },
      taskGraphLiveMonitor: itemForMonitor({
        session_id: "session:paused",
        task_run_id: "taskrun:paused",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        control_state: "paused",
        runtime_control: { state: "paused" },
      }) as any,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("暂停后补充。");

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:paused", "暂停后补充。");
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
  });

  it("keeps the active task turn gate and queues follow-up after a runtime control turn completes", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", {
        content: "任务已进入后台执行。",
        answer_channel: "task_control",
        terminal_reason: "task_executor_scheduled",
        runtime_task_run_id: "taskrun:background",
        active_turn_id: "turn:session:background:1",
      });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:background",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始后台任务");
    await runtime.actions.sendMessage("暂停一下");

    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session:background:1",
      task_run_id: "taskrun:background",
    });
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session:background", "暂停一下");
  });

  it("recovers the active task turn gate from the session live monitor before later input", async () => {
    const taskRunId = "taskrun:turn:session-monitor-recover:1:abc";
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      active_turn_snapshot: {
        turn_id: "turn:session-monitor-recover:1",
        bound_task_run_id: taskRunId,
        state: "running_task",
      },
      monitor: {
        task_run_id: taskRunId,
        session_id: "session-monitor-recover",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        event_count: 2,
        latest_interaction_turn_id: "turn:session-monitor-recover:1",
        latest_step: {
          event_id: "step:recover",
          step: "task_model_action_invocation_started:1",
          status: "running",
          created_at: 2,
        },
        latest_step_summary: "正在推进当前任务。",
        latest_event: { event_type: "step_summary_recorded" },
        task_run: {
          task_run_id: taskRunId,
          task_id: "task:turn:session-monitor-recover:1",
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      },
      task_runs: [],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-monitor-recover",
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "我会开始处理。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
      activeTurnSnapshot: null,
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      actions: WorkspaceRuntime["actions"];
      hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
    };

    await runtime.hydrateLatestOrchestrationSnapshot("session-monitor-recover");
    await runtime.actions.sendMessage("补充一个限制条件");

    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session-monitor-recover:1",
      task_run_id: taskRunId,
    });
    expect(store.getState().taskGraphLiveMonitor?.task_run_id).toBe(taskRunId);
    expect(store.getState().messages.some((message) =>
      message.role === "assistant"
      && message.content === ""
      && message.sourceTaskRunId === taskRunId
    )).toBe(false);
    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-monitor-recover", "补充一个限制条件");
  });

  it("does not preselect recoverable work during a normal message send", async () => {
    const taskRunId = "taskrun:turn:session-recovery:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-recovery",
      activeTurnSnapshot: null,
      taskGraphLiveMonitor: itemForMonitor({
        session_id: "session-recovery",
        task_run_id: taskRunId,
        status: "waiting_executor",
        lifecycle: "waiting",
        bucket: "waiting",
        execution_runtime_kind: "single_agent_task",
        is_running: false,
        is_waiting: true,
        is_resumable: true,
        is_interruptible: false,
        control_reason: "runtime_restart_waiting_resume",
        activity: {
          is_resumable: true,
          control_reason: "runtime_restart_waiting_resume",
        },
        control_capability: {
          is_resumable: true,
          control_reason: "runtime_restart_waiting_resume",
        },
        task_run: {
          task_run_id: taskRunId,
          status: "waiting_executor",
          execution_runtime_kind: "single_agent_task",
        },
      }) as any,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("继续");

    expect(api.getLatestSessionContinuation).not.toHaveBeenCalled();
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    const payload = api.streamChat.mock.calls[0]?.[0];
    expect(payload).toMatchObject({
      message: "继续",
      session_id: "session-recovery",
      expected_active_turn_id: "",
      active_turn_input_policy: "auto",
    });
    expect(payload?.expected_task_run_id).toBeUndefined();
    expect(payload?.expected_continuation_id).toBeUndefined();
    expect(payload?.recovery_input_policy).toBeUndefined();
  });

  it("uses the live monitor only to route active-task input into the backend queue", async () => {
    const taskRunId = "taskrun:turn:session-monitor-steer:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-monitor-steer",
      activeTurnSnapshot: null,
      taskGraphLiveMonitor: itemForMonitor({
        session_id: "session-monitor-steer",
        task_run_id: taskRunId,
        status: "running",
        execution_runtime_kind: "single_agent_task",
        latest_interaction_turn_id: "turn:session-monitor-steer:1",
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      }) as any,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充：先保留现有链路。");

    expect(api.getLatestSessionContinuation).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-monitor-steer", "补充：先保留现有链路。");
  });

  it("queues running active task input without adding system-authored feedback", async () => {
    const taskRunId = "taskrun:turn:session-queue-only:1:abc";
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "开始任务" },
        { role: "assistant", content: "我会开始处理。" },
        { role: "user", content: "补充一个限制条件" },
      ],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-queue-only",
      activeTurnSnapshot: {
        turn_id: "turn:session-queue-only:1",
        task_run_id: taskRunId,
        state: "running_task",
      },
      taskGraphLiveMonitor: ({
        task_run_id: taskRunId,
        session_id: "session-queue-only",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        route: { kind: "agent_runtime_run", session_id: "session-queue-only", task_run_id: taskRunId },
        runtime_control: { state: "running" },
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      } as unknown) as StoreState["taskGraphLiveMonitor"],
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "我会开始处理。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充一个限制条件");

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-queue-only", "补充一个限制条件");
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
    expect(store.getState().messages.at(-1)).toMatchObject({
      role: "user",
      content: "补充一个限制条件",
    });
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session-queue-only:1",
      task_run_id: taskRunId,
    });
  });

  it("reattaches the current stream after a detached active-turn steer without hiding the user feedback", async () => {
    const taskRunId = "taskrun:turn:session-detached-steer:1:abc";
    let handlers: StreamEventHandlers | null = null;
    api.enqueueQueuedChatInput.mockImplementationOnce(async (sessionId, payload) => ({
      session_id: sessionId,
      item: {
        queue_item_id: "qinp:detached-steer",
        session_id: sessionId,
        client_message_id: payload.client_message_id ?? "",
        content: payload.message,
        input_policy: "steer",
        status: "queued",
        expected_active_turn_id: "turn:session-detached-steer:1",
        task_run_id: taskRunId,
        created_at: 1,
        updated_at: 1,
        dispatch_stream_run_id: "",
      },
      items: [],
      authority: "api.chat.queued_user_inputs",
    }));
    api.getLatestChatRunForSession.mockResolvedValueOnce({
      stream_run_id: "strun:detached-steer",
      session_id: "session-detached-steer",
      event_log_id: "chatrun:detached-steer",
      root_request_ref: "chatreq:detached-steer",
      status: "running",
      diagnostics: {
        active_turn_id: "turn:session-detached-steer:1",
        runtime_task_run_id: taskRunId,
      },
      latest_event_offset: 0,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:detached-steer/events/replay",
      live_ws_url: "/api/chat/sessions/session-detached-steer/live",
    });
    api.streamExistingChatRun.mockImplementationOnce(async (_sessionId, _streamRunId, streamHandlers) => {
      handlers = streamHandlers;
      return new Promise(() => undefined);
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-detached-steer",
      activeStreamSessionIds: [],
      isStreaming: false,
      activeTurnSnapshot: {
        turn_id: "turn:session-detached-steer:1",
        task_run_id: taskRunId,
        state: "running_task",
      },
      taskGraphLiveMonitor: (itemForMonitor({
        task_run_id: taskRunId,
        session_id: "session-detached-steer",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        latest_interaction_turn_id: "turn:session-detached-steer:1",
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      }) as unknown) as StoreState["taskGraphLiveMonitor"],
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "我会开始处理。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充：优先保持当前链路。");
    await flushPromises(4);

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-detached-steer", "补充：优先保持当前链路。");
    expect(api.getLatestChatRunForSession).toHaveBeenCalledWith("session-detached-steer", undefined);
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session-detached-steer",
      "strun:detached-steer",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: expect.objectContaining({
          streamRunId: "strun:detached-steer",
          eventLogId: "chatrun:detached-steer",
        }),
      }),
    );
    expect(handlers).not.toBeNull();
    expect(store.getState().activeStreamSessionIds).toContain("session-detached-steer");
    expect(store.getState().messages.filter((message) => message.content === "补充：优先保持当前链路。")).toHaveLength(1);
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入当前回合",
    });
  });

  it("reattaches a backend-dispatched queued input instead of opening a frontend steer run", async () => {
    const taskRunId = "taskrun:turn:session-auto-active-stream:1:abc";
    api.enqueueQueuedChatInput.mockImplementationOnce(async (sessionId, payload) => ({
      session_id: sessionId,
      item: {
        queue_item_id: "qinp:dispatched",
        session_id: sessionId,
        client_message_id: payload.client_message_id ?? "",
        content: payload.message,
        input_policy: "steer",
        status: "dispatched",
        created_at: 1,
        updated_at: 2,
        dispatch_stream_run_id: "strun:queued-dispatch",
      },
      items: [],
      authority: "api.chat.queued_user_inputs",
    }));
    api.getChatRun.mockResolvedValue({
      stream_run_id: "strun:queued-dispatch",
      session_id: "session-auto-active-stream",
      event_log_id: "chatrun:queued-dispatch",
      root_request_ref: "chatreq:queued-dispatch",
      status: "running",
      diagnostics: {
        active_turn_id: "turn:session-auto-active-stream:1",
        runtime_task_run_id: taskRunId,
        expected_active_turn_id: "turn:session-auto-active-stream:1",
        active_turn_input_policy: "steer",
      },
      latest_event_offset: 0,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:queued-dispatch/events/replay",
      live_ws_url: "/api/chat/sessions/session-auto-active-stream/live",
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-auto-active-stream",
      activeTurnSnapshot: {
        turn_id: "turn:session-auto-active-stream:1",
        task_run_id: taskRunId,
        state: "running_task",
      },
      taskGraphLiveMonitor: ({
        task_run_id: taskRunId,
        session_id: "session-auto-active-stream",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        route: { kind: "agent_runtime_run", session_id: "session-auto-active-stream", task_run_id: taskRunId },
        runtime_control: { state: "running" },
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      } as unknown) as StoreState["taskGraphLiveMonitor"],
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "我会开始处理。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充一");
    await flushPromises(10);

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-auto-active-stream", "补充一");
    expect(api.getChatRun).toHaveBeenCalledWith("strun:queued-dispatch");
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session-auto-active-stream",
      "strun:queued-dispatch",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: expect.objectContaining({
          streamRunId: "strun:queued-dispatch",
          eventLogId: "chatrun:queued-dispatch",
        }),
      }),
    );
    expect(api.streamExistingChatRun.mock.calls.at(-1)?.[3]).not.toHaveProperty("replayFromStart", true);
    expect(store.getState().messages.filter((message) => message.content === "补充一")).toHaveLength(1);
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
    });
  });

  it("preserves queued user identity when posting active-stream input to the backend", async () => {
    const taskRunId = "taskrun:turn:session-queued-target:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-queued-target",
      activeStreamSessionIds: ["session-queued-target"],
      isStreaming: true,
      activeTurnSnapshot: {
        turn_id: "turn:session-queued-target:1",
        task_run_id: taskRunId,
        state: "running_task",
      },
      taskGraphLiveMonitor: (itemForMonitor({
        task_run_id: taskRunId,
        session_id: "session-queued-target",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        latest_interaction_turn_id: "turn:session-queued-target:1",
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      }) as unknown) as StoreState["taskGraphLiveMonitor"],
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "我会开始处理。", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("补充二", { queuedUserMessageId: "user:queued:2" });

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-queued-target", "补充二");
    expect(api.enqueueQueuedChatInput.mock.calls[0]?.[1]?.client_message_id).toBe("user:queued:2");
    expect(store.getState().messages.filter((message) => message.id === "user:queued:2")).toHaveLength(1);
    expect(store.getState().messages.find((message) => message.id === "user:queued:2")).toMatchObject({
      role: "user",
      content: "补充二",
    });
  });

  it("keeps active-stream input in the backend queue after handoff instead of local flush", async () => {
    const taskRunId = "taskrun:turn:session-stream-queue:1:abc";
    let finishFirstStream: (() => void) | null = null;
    api.streamChat.mockImplementationOnce(async (_payload, handlers) => {
      await new Promise<void>((resolve) => {
        finishFirstStream = () => {
          handlers.onEvent("done", {
            content: "任务已进入后台执行。",
            answer_channel: "task_control",
            terminal_reason: "task_executor_scheduled",
            runtime_task_run_id: taskRunId,
            active_turn_id: "turn:session-stream-queue:1",
          });
          resolve();
        };
      });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "开始任务" },
        { role: "assistant", content: "任务已进入后台执行。" },
        { role: "user", content: "补充一个限制条件" },
      ],
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      active_turn_snapshot: {
        turn_id: "turn:session-stream-queue:1",
        bound_task_run_id: taskRunId,
        state: "running_task",
      },
      monitor: {
        task_run_id: taskRunId,
        session_id: "session-stream-queue",
        status: "running",
        execution_runtime_kind: "single_agent_task",
        route: { kind: "agent_runtime_run", session_id: "session-stream-queue", task_run_id: taskRunId },
        runtime_control: { state: "running" },
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      },
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-stream-queue",
    });
    const runtime = new WorkspaceRuntime(store);

    const firstSend = runtime.actions.sendMessage("开始任务");
    await flushPromises();
    await runtime.actions.sendMessage("补充一个限制条件");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
    expect(store.getState().messages.at(-1)).toMatchObject({
      role: "user",
      content: "补充一个限制条件",
    });
    expect(store.getState().sessionActivity).toMatchObject({
      title: "已加入当前回合",
    });
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expectQueuedChatInputCall(0, "session-stream-queue", "补充一个限制条件");

    const finish = finishFirstStream as (() => void) | null;
    expect(finish).not.toBeNull();
    finish?.();
    await firstSend;
    await flushPromises(10);

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expect(store.getState().messages.filter((message) => message.content === "补充一个限制条件")).toHaveLength(1);
  });

  it("controls the active session task run from chat actions", async () => {
    const taskRunId = "taskrun:turn:session-control:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-control",
      activeTurnSnapshot: {
        turn_id: "turn:session-control:1",
        task_run_id: taskRunId,
      },
      taskGraphLiveMonitor: {
        authority: "single_agent_runtime_monitor.item",
        task_run_id: taskRunId,
        session_id: "session-control",
      task_id: "task:turn:session-control:1",
      execution_runtime_kind: "single_agent_task",
      task_run: { task_run_id: taskRunId },
        loop_state: {},
        has_graph_run: false,
        status: "running",
        terminal_reason: "",
        updated_at: 1,
      },
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      monitor: {
        task_run_id: taskRunId,
        session_id: "session-control",
        status: "waiting_executor",
        execution_runtime_kind: "single_agent_task",
        terminal_reason: "waiting_executor",
        runtime_control: { state: "paused" },
        control_state: "paused",
        latest_step: {},
        loop_state: {},
        has_graph_run: false,
        task_run: { task_run_id: taskRunId },
      },
      task_runs: [],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.pauseActiveTaskRun();
    await runtime.actions.resumeActiveTaskRun();
    await runtime.actions.stopActiveTaskRun();

    expect(api.pauseOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, "user_pause_from_chat", "turn:session-control:1");
    expect(api.resumeOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, 12, "turn:session-control:1");
    expect(api.stopOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, "user_stop_from_chat", "turn:session-control:1");
    expect(store.getState().sessionActivity.title).toBe("已暂停");
  });

  it("treats pause as a hard local stream boundary and ignores late assistant output", async () => {
    const sessionId = "session-control-pause-boundary";
    const taskRunId = "taskrun:turn:session-control-pause-boundary:1:abc";
    const turnId = "turn:session-control-pause-boundary:1";
    let handlers: StreamEventHandlers | null = null;
    let streamSignal: AbortSignal | null = null;
    api.streamChat.mockImplementationOnce(async (_payload, streamHandlers, options) => {
      handlers = streamHandlers;
      streamSignal = options?.signal ?? null;
      streamHandlers.onEvent("assistant_text_delta", {
        sequence: 1,
        content: "暂停前",
        event_offset: 1,
        runtime_task_run_id: taskRunId,
        active_turn_id: turnId,
        public_projection_frame: publicBodyFrame({
          text: "暂停前",
          event_offset: 1,
          anchor: {
            session_id: sessionId,
            turn_id: turnId,
            task_run_id: taskRunId,
            stream_run_id: "strun:pause-boundary",
          },
        }),
      });
      await new Promise<void>(() => undefined);
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      monitor: {
        task_run_id: taskRunId,
        session_id: sessionId,
        status: "waiting_executor",
        execution_runtime_kind: "single_agent_task",
        terminal_reason: "waiting_executor",
        runtime_control: { state: "paused" },
        control_state: "paused",
        latest_step: {},
        loop_state: {},
        has_graph_run: false,
        task_run: { task_run_id: taskRunId },
      },
      task_runs: [],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      sessions: [{
        id: sessionId,
        title: "Pause boundary",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    void runtime.actions.sendMessage("开始一个会被暂停的任务").catch(() => undefined);
    await flushPromises();
    store.setState((prev) => ({
      ...prev,
      activeTurnSnapshot: { turn_id: turnId, task_run_id: taskRunId },
    }));

    await runtime.actions.pauseActiveTaskRun();

    const pausedStreamSignal = streamSignal as AbortSignal | null;
    expect(pausedStreamSignal?.aborted).toBe(true);
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().chatStreamConnectionStatus).toMatchObject({
      state: "paused",
      reason: "user_paused",
    });
    requireStreamHandlers(handlers).onEvent("assistant_text_delta", {
      sequence: 2,
      content: "迟到重复输出",
      event_offset: 2,
      runtime_task_run_id: taskRunId,
      active_turn_id: turnId,
      public_projection_frame: publicBodyFrame({
        text: "迟到重复输出",
        event_offset: 2,
        anchor: {
          session_id: sessionId,
          turn_id: turnId,
          task_run_id: taskRunId,
          stream_run_id: "strun:pause-boundary",
        },
      }),
    });

    expect(JSON.stringify(store.getState().messages)).not.toContain("迟到重复输出");
    expect(api.pauseOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, "user_pause_from_chat", turnId);
  });

  it("surfaces active task control failures without throwing from chat actions", async () => {
    const taskRunId = "taskrun:turn:session-control-error:1:abc";
    api.pauseOrchestrationHarnessTaskRun.mockRejectedValue(new Error("active_turn_mismatch"));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-control-error",
      activeTurnSnapshot: {
        turn_id: "turn:session-control-error:1",
        task_run_id: taskRunId,
      },
      taskGraphLiveMonitor: {
        authority: "single_agent_runtime_monitor.item",
        task_run_id: taskRunId,
        session_id: "session-control-error",
        task_id: "task:turn:session-control-error:1",
        execution_runtime_kind: "single_agent_task",
        task_run: { task_run_id: taskRunId },
        loop_state: {},
        has_graph_run: false,
        status: "running",
        terminal_reason: "",
        updated_at: 1,
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await expect(runtime.actions.pauseActiveTaskRun()).resolves.toBeUndefined();

    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "暂停失败",
      detail: "active_turn_mismatch",
      event: "active_task_pause_failed",
    });
    expect(store.getState().sessionActivitiesById["session-control-error"]).toMatchObject({
      level: "error",
      title: "暂停失败",
    });
  });

  it("approves a waiting tool approval before resuming the active task run", async () => {
    const taskRunId = "taskrun:turn:session-approval:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-approval",
      activeTurnSnapshot: {
        turn_id: "turn:session-approval:1",
        task_run_id: taskRunId,
      },
      taskGraphLiveMonitor: {
        authority: "single_agent_runtime_monitor.item",
        task_run_id: taskRunId,
        session_id: "session-approval",
        task_id: "task:turn:session-approval:1",
        execution_runtime_kind: "single_agent_task",
        task_run: { task_run_id: taskRunId, status: "waiting_approval" },
        loop_state: { terminal_reason: "waiting_approval" },
        has_graph_run: false,
        status: "waiting_approval",
        terminal_reason: "waiting_approval",
        updated_at: 1,
      },
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      monitor: null,
      task_runs: [],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.resumeActiveTaskRun();

    expect(api.approveOrchestrationHarnessTaskRunToolCall).toHaveBeenCalledWith(
      taskRunId,
      "user_approve_tool_from_chat",
      12,
      "turn:session-approval:1",
    );
    expect(api.resumeOrchestrationHarnessTaskRun).not.toHaveBeenCalled();
  });

  it("does not surface transient run monitor aborts as user-visible errors", async () => {
    api.getRunMonitor.mockRejectedValue(new DOMException("signal is aborted without reason", "AbortError"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.refreshRunMonitor();
    await vi.runOnlyPendingTimersAsync();

    expect(store.getState().runMonitorError).toBe("");
    expect(store.getState().runMonitorLoading).toBe(false);
  });

  it("does not render bare runtime answer events as the visible assistant body", () => {
    let transition = startStreamingTurn(getDefaultState(), "你好");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "你好，",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:partial-1",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "我在。",
      content_utf8_start: 9,
      accumulated_utf8_bytes: 18,
      accumulated_sha256: "sha256:partial-2",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "answer_candidate", { content: "旧正文事件不应覆盖已有流式内容。" });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 3,
      content: "你好，我在。",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
      answer_selected_channel: "answer_candidate",
      answer_leak_flags: ["internal_protocol_final_text"],
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "最终 done 不应重复覆盖已有流式内容。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
      answer_selected_channel: "answer_candidate",
      answer_leak_flags: ["internal_protocol_final_text"],
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.stageStatus).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
    expect(assistant?.answerPersistPolicy).toBe("persist_canonical");
    expect(assistant?.answerSelectedChannel).toBe("answer_candidate");
    expect(assistant?.answerLeakFlags).toEqual(["internal_protocol_final_text"]);
  });

  it("keeps streamed deltas out of the visible assistant message when stream display is disabled", () => {
    let transition = startStreamingTurn({
      ...getDefaultState(),
      chatStreamDisplayEnabled: false,
    }, "你好");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "你好，",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:partial-1",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "token", { content: "旧 token 不应显示。" });
    transition = reduceStreamEvent(transition.state, transition.session, "answer_candidate", {
      content: "提前旧正文事件不应显示。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      content: "提前 assistant_text 不应显示。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });
    expect(transition.state.messages.at(-1)?.content).toBe("");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 2,
      content: "最终回答。",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "done 不应覆盖 final。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
  });

  it("keeps bare active-work control prose out of the visible assistant body", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      content: "好，用户说“继续”，指向当前活跃工作（修复篮球游戏2D瞄准）。用 answer_then_continue_active_work 简短确认后继续推进。",
      content_sha256: "sha256:internal-control",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "好，用户说“继续”，指向当前活跃工作（修复篮球游戏2D瞄准）。用 answer_then_continue_active_work 简短确认后继续推进。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });
  it("does not use done summary as assistant prose when final content is absent", () => {
    let transition = startStreamingTurn(getDefaultState(), "修一下页面反馈");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      summary: "已完成页面反馈修复，最终正文不应被工具反馈替代。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use raw file listing output as done assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "检查目录");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      summary: "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use copied shell output as done assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "复制素材");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      summary: "Copied: game-boss-demon-king.png Copied: game-map-castle.png",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use read-only shell validator failures as done assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "回答这个问题");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "shell command executable is not allowlisted read-only",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use persisted tool result read failures as done assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续吧");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "Read persisted tool result failed: D:\\AI应用\\langchain-agent\\backend\\storage\\task_environments\\general\\workspace\\runtime_state\\storage\\runtime_context\\tool-results\\session-fad8ee446.txt",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use runtime replacement artifact paths as done assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续吧");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
  });

  it("does not use task-control assistant_text as visible prose before task handoff done", () => {
    let transition = startStreamingTurn(getDefaultState(), "开始任务");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      content: "正在建立任务运行。",
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "正在建立任务运行。",
      content_utf8_start: 0,
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      content: "正在建立任务运行。",
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
      answer_canonical_state: "progress_only",
      answer_persist_policy: "persist_debug_only",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "done 不应覆盖已经显示的 agent 正文。",
      runtime_task_run_id: "taskrun:turn:session:1:abc",
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
      answer_canonical_state: "progress_only",
      answer_persist_policy: "persist_debug_only",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.answerChannel).toBe("task_control");
    expect(assistant?.answerPersistPolicy).toBe("persist_debug_only");
  });

  it("keeps task steer acknowledgements out of visible status projection", () => {
    let transition = startStreamingTurn(getDefaultState(), "补充限制条件");
    const activityBeforeSteer = transition.state.sessionActivity;
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      state: "running",
      phase: "active_turn_steer",
      runtime_task_run_id: "taskrun:background",
      active_turn_id: "turn:session:background:1",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "",
      answer_channel: "runtime_control",
      completion_state: "task_steer_accepted",
      runtime_task_run_id: "taskrun:background",
      active_turn_id: "turn:session:background:1",
    });

    expect(transition.state.messages).toHaveLength(2);
    expect(transition.state.messages[0]).toMatchObject({
      role: "user",
      content: "补充限制条件",
    });
    expect(transition.state.messages[1]).toMatchObject({
      role: "assistant",
      content: "",
      answerChannel: "runtime_control",
    });
    expect(transition.state.messages[1]?.projectionView).toBeUndefined();
    expect(transition.state.sessionActivity).toBe(activityBeforeSteer);
  });

  it("treats provider stream recovery as connection state without appending assistant body", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续输出");
    transition = reduceStreamEvent(transition.state, transition.session, "stream_recovery", {
      status: "started",
      reason: "partial_stream_error",
      recovery_mode: "continue_from_visible_prefix",
      partial_utf8_bytes: 18,
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
    expect(transition.state.chatStreamConnectionStatus).toMatchObject({
      state: "streaming",
      reason: "partial_stream_recovery",
    });
  });

  it("keeps chat usable when noncritical workspace metadata is still loading", async () => {
    vi.useRealTimers();
    api.getTaskEnvironmentCatalog.mockImplementation(() => new Promise(() => undefined));
    api.listSkills.mockImplementation(() => new Promise(() => undefined));
    api.loadFile.mockImplementation(() => new Promise(() => undefined));
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await runtime.actions.sendMessage("你好");

    expect(store.getState().currentSessionId).toBe("session:fresh");
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.session_id).toBe("session:fresh");
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection?.stream_policy).toEqual(expect.objectContaining({
      enabled: true,
      upstream_reconnect_enabled: true,
      partial_stream_recovery: "continue_from_visible_prefix",
      chunk_strategy: "adaptive_buffer",
      first_flush_delay_ms: 70,
      target_buffer_delay_ms: 150,
      adaptive_min_buffer_delay_ms: 80,
      adaptive_max_buffer_delay_ms: 240,
      release_tick_ms: 16,
      max_buffer_delay_ms: 320,
      max_pending_utf8_bytes: 1536,
      max_release_utf8_bytes: 192,
      min_event_interval_ms: 16,
      event_budget_per_second: 45,
    }));
  });

  it("coalesces same-turn visible assistant body deltas on the next paint frame", async () => {
    let handlers: StreamEventHandlers | null = null;
    let resolveStream: (value: {
      terminalEvent: "turn_completed";
      terminalStatus: "completed";
      streamRunId: string;
      eventLogId: string;
      lastEventOffset: number;
    }) => void = () => undefined;
    const animationFrameCallbacks: FrameRequestCallback[] = [];
    const requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
      animationFrameCallbacks.push(callback);
      return animationFrameCallbacks.length;
    });
    Object.assign(window, {
      requestAnimationFrame,
      cancelAnimationFrame: vi.fn(),
    });
    api.streamChat.mockImplementation(async (_payload, streamHandlers) => {
      handlers = streamHandlers;
      streamHandlers.onEvent("assistant_text_delta", {
        sequence: 1,
        content: "甲",
        event_offset: 1,
        diagnostics: {
          server_event_created_at: 10,
          server_ws_sent_at: 11,
          client_received_at: 12,
        },
        public_projection_frame: publicBodyFrame({ text: "甲" }),
      });
      streamHandlers.onEvent("assistant_text_delta", {
        sequence: 2,
        content: "乙",
        event_offset: 2,
        diagnostics: {
          server_event_created_at: 20,
          server_ws_sent_at: 21,
          client_received_at: 22,
        },
        public_projection_frame: publicBodyFrame({ text: "乙" }),
      });
      return new Promise((resolve) => {
        resolveStream = resolve;
      });
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:visible-stream",
      sessions: [{
        id: "session:visible-stream",
        title: "Visible Stream",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    const sendPromise = runtime.actions.sendMessage("写一段");
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
    expect(store.getState().messages.at(-1)?.role).toBe("assistant");
    expect(store.getState().messages.at(-1)?.content).toBe("");
    expect(latestProjectionView(store.getState())?.canonicalContent).toBeUndefined();
    expect(store.getState().chatStreamLatencySummary).toBeNull();

    animationFrameCallbacks.shift()?.(Date.now());
    expect(latestProjectionView(store.getState())?.canonicalContent).toBe("甲乙");
    expect(store.getState().chatStreamLatencySummary).toEqual(expect.objectContaining({
      sessionId: "session:visible-stream",
      event: "assistant_text_delta",
      eventOffset: 2,
      serverEventCreatedAt: 20,
      serverWsSentAt: 21,
      clientReceivedAt: 22,
      clientVisibleFlushedAt: expect.any(Number),
    }));

    const activeHandlers = requireStreamHandlers(handlers);
    activeHandlers.onEvent("assistant_text_delta", {
      sequence: 3,
      content: "丙",
      event_offset: 3,
      public_projection_frame: publicBodyFrame({ text: "丙" }),
    });
    expect(requestAnimationFrame).toHaveBeenCalledTimes(2);
    expect(latestProjectionView(store.getState())?.canonicalContent).toBe("甲乙");

    activeHandlers.onEvent("assistant_text_final", {
      sequence: 4,
      content: "甲乙丙",
      content_sha256: "sha256:final",
      event_offset: 4,
      public_projection_frame: publicBodyFrame({
        op: "body_finalize",
        main_visibility: "visible_final",
        text: "甲乙丙",
      }),
    });
    expect(store.getState().messages.at(-1)?.content).toBe("");
    expect(latestProjectionView(store.getState())?.canonicalContent).toBe("甲乙丙");
    animationFrameCallbacks.shift()?.(Date.now());
    expect(latestProjectionView(store.getState())?.canonicalContent).toBe("甲乙丙");

    resolveStream({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:visible-stream",
      eventLogId: "chatrun:visible-stream",
      lastEventOffset: 4,
    });
    await sendPromise;
  });

  it("preserves queued user input when a delayed stream flush arrives after reconnect loss", async () => {
    let handlers: StreamEventHandlers | null = null;
    let resolveStream: (value: {
      terminalEvent: "turn_completed";
      terminalStatus: "completed";
      streamRunId: string;
      eventLogId: string;
      lastEventOffset: number;
    }) => void = () => undefined;
    const animationFrameCallbacks: FrameRequestCallback[] = [];
    Object.assign(window, {
      requestAnimationFrame: vi.fn((callback: FrameRequestCallback) => {
        animationFrameCallbacks.push(callback);
        return animationFrameCallbacks.length;
      }),
      cancelAnimationFrame: vi.fn(),
    });
    api.streamChat.mockImplementationOnce(async (_payload, streamHandlers) => {
      handlers = streamHandlers;
      streamHandlers.onEvent("assistant_text_delta", {
        sequence: 1,
        content: "旧",
        event_offset: 1,
        public_projection_frame: publicBodyFrame({ text: "旧" }),
      });
      streamHandlers.onEvent("stream_reconnecting", {
        stream_run_id: "strun:delayed-flush",
        event_log_id: "chatrun:delayed-flush",
        event_offset: 1,
        attempt: 1,
        reason: "stream_transport_error",
      });
      return new Promise((resolve) => {
        resolveStream = resolve;
      });
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:delayed-flush",
      sessions: [{
        id: "session:delayed-flush",
        title: "Delayed flush",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    const firstSend = runtime.actions.sendMessage("开始输出");
    await flushPromises();
    expect(animationFrameCallbacks).toHaveLength(1);
    expect(store.getState().chatStreamConnectionStatus.state).toBe("reconnecting");

    await runtime.actions.sendMessage("掉线后的补充输入", { queuedUserMessageId: "user:queued:lost-link" });
    expect(api.enqueueQueuedChatInput).toHaveBeenCalledTimes(1);
    expect(store.getState().messages.some((message) => message.id === "user:queued:lost-link")).toBe(true);

    animationFrameCallbacks.shift()?.(Date.now());
    expect(store.getState().messages.filter((message) => message.id === "user:queued:lost-link")).toHaveLength(1);
    expect(store.getState().messages.find((message) => message.id === "user:queued:lost-link")).toMatchObject({
      role: "user",
      content: "掉线后的补充输入",
    });
    expect(store.getState().sessionActivity.event).toBe("user_input_queued");

    requireStreamHandlers(handlers).onEvent("assistant_text_final", {
      sequence: 2,
      content: "旧输出完成",
      event_offset: 2,
      public_projection_frame: publicBodyFrame({
        op: "body_finalize",
        main_visibility: "visible_final",
        text: "旧输出完成",
      }),
    });
    expect(store.getState().messages.filter((message) => message.id === "user:queued:lost-link")).toHaveLength(1);

    resolveStream({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:delayed-flush",
      eventLogId: "chatrun:delayed-flush",
      lastEventOffset: 2,
    });
    await firstSend;
    expect(store.getState().messages.filter((message) => message.id === "user:queued:lost-link")).toHaveLength(1);
  });

  it("creates a new conversation inside the active project workspace", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeProjectKey: "workspace:repo",
      activeProjectRoot: "D:/repo",
      projectWorkspaces: [{
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "test",
        created_at: 1,
        last_seen_at: 1,
        session_count: 0,
        latest_session_at: 0,
        available: true,
        authority: "project_workspaces.workspace",
      }],
    });
    api.listProjectWorkspaceSessions.mockResolvedValue({
      authority: "project_workspaces.sessions",
      project_key: "workspace:repo",
      sessions: [{
        id: "session:fresh",
        title: "New Session",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: {
          authority: "sessions.conversation_state",
          project_binding: {
            workspace_root: "D:/repo",
            source: "project_workspace",
            bound_at: 1,
            last_seen_at: 1,
            immutable: true,
            authority: "sessions.project_binding",
          },
        },
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.createNewSession();

    expect(api.createProjectWorkspaceSession).toHaveBeenCalledWith("workspace:repo", "New Session");
    expect(api.createSession).not.toHaveBeenCalled();
    expect(store.getState().currentSessionId).toBe("session:fresh");
    expect(store.getState().projectSessions[0]?.conversation_state?.project_binding?.workspace_root).toBe("D:/repo");
  });

  it("truncates from the edited user message and sends the replacement text", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:edit",
      sessions: [{
        id: "session:edit",
        title: "Edit",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
      messages: [
        { id: "user:1", role: "user", content: "旧问题", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "旧回答", toolCalls: [], retrievals: [], sourceIndex: 1 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.resendEditedMessage("user:1", "新问题");

    expect(api.truncateSessionMessages).toHaveBeenCalledWith("session:edit", 0, undefined);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.message).toBe("新问题");
  });

  it("normalizes fractional source indexes before truncating an edited message", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:edit-fractional-index",
      sessions: [{
        id: "session:edit-fractional-index",
        title: "Edit",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
      messages: [
        { id: "user:1", role: "user", content: "旧问题", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:recovered", role: "assistant", content: "恢复中的回答", toolCalls: [], retrievals: [], sourceIndex: 0.5 },
        { id: "user:2", role: "user", content: "要重写的问题", toolCalls: [], retrievals: [], sourceIndex: 1.5 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.resendEditedMessage("user:2", "改写后的问题");

    expect(api.truncateSessionMessages).toHaveBeenCalledWith("session:edit-fractional-index", 1, undefined);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.message).toBe("改写后的问题");
  });

  it("allocates integer source indexes after recovered fractional assistant shells", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:fractional-next-index",
      sessions: [{
        id: "session:fractional-next-index",
        title: "Fractional",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
      messages: [
        { id: "user:1", role: "user", content: "旧问题", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:recovered", role: "assistant", content: "恢复中的回答", toolCalls: [], retrievals: [], sourceIndex: 0.5 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("新问题");

    const newUser = store.getState().messages.find((message) => message.role === "user" && message.content === "新问题");
    expect(newUser?.sourceIndex).toBe(1);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
  });

  it("does not resend an older user message because the edit affordance is only for the latest user message", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:edit",
      sessions: [{
        id: "session:edit",
        title: "Edit",
        created_at: 1,
        updated_at: 1,
        message_count: 3,
      }],
      messages: [
        { id: "user:1", role: "user", content: "第一条", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "回答", toolCalls: [], retrievals: [], sourceIndex: 1 },
        { id: "user:2", role: "user", content: "第二条", toolCalls: [], retrievals: [], sourceIndex: 2 },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.resendEditedMessage("user:1", "改第一条");
    expect(api.truncateSessionMessages).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("loads ordinary chat sessions without task-environment session scope", async () => {
    vi.useRealTimers();
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(api.listSessions.mock.calls[0]?.[0]).toBeUndefined();
    expect(api.createSession.mock.calls[0]?.[1]).toBeUndefined();
  });

  it("keeps writing graph sessions out of the ordinary main-chat session list", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:general",
        title: "General",
        created_at: 1,
        updated_at: 2,
        message_count: 1,
      },
      {
        id: "session:graph",
        title: "Graph",
        created_at: 1,
        updated_at: 3,
        message_count: 1,
        scope: {
          workspace_view: "task_environment",
          task_environment_id: "env.general.workspace",
          project_id: "project.general.workspace.demo",
        },
      },
    ]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(store.getState().sessions.map((session) => session.id)).toEqual(["session:general"]);
    expect(store.getState().currentSessionId).toBe("session:general");
  });

  it("removes a session from the local list before the delete request settles", async () => {
    vi.useRealTimers();
    const deleteDeferred: { resolve?: (value: { ok: boolean }) => void } = {};
    api.deleteSession.mockImplementation(() => new Promise<{ ok: boolean }>((resolve) => {
      deleteDeferred.resolve = resolve;
    }));
    api.listSessions.mockResolvedValue([{
      id: "session:keep",
      title: "Keep",
      created_at: 1,
      updated_at: 5,
      message_count: 0,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:keep",
      sessions: [
        {
          id: "session:delete",
          title: "Delete me",
          created_at: 1,
          updated_at: 6,
          message_count: 0,
        },
        {
          id: "session:keep",
          title: "Keep",
          created_at: 1,
          updated_at: 5,
          message_count: 0,
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    const deletion = runtime.actions.removeSession({
      sessionId: "session:delete",
      poolKey: "main-chat",
    });

    expect(api.deleteSession).toHaveBeenCalledWith("session:delete", undefined);
    expect(store.getState().sessions.map((session) => session.id)).toEqual(["session:keep"]);

    deleteDeferred.resolve?.({ ok: true });
    await deletion;
    expect(api.listSessions).toHaveBeenCalled();
  });

  it("keeps scoped session index when deleting the selected task-environment session", async () => {
    vi.useRealTimers();
    const poolKey = "task_environment:env.development.code:project:code" as const;
    const scope = {
      workspace_view: "task_environment",
      task_environment_id: "env.development.code",
      project_id: "project:code",
    };
    const nextScopedSession = {
      id: "session:scoped-b",
      title: "Scoped B",
      created_at: 1,
      updated_at: 4,
      message_count: 0,
      scope,
    };
    api.listSessions.mockImplementation(async (receivedScope) => {
      if (receivedScope?.workspace_view === scope.workspace_view
        && receivedScope?.task_environment_id === scope.task_environment_id
        && receivedScope?.project_id === scope.project_id) {
        return [nextScopedSession];
      }
      return [{
        id: "session:main",
        title: "Main",
        created_at: 1,
        updated_at: 9,
        message_count: 0,
      }];
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:scoped-a",
      activeSessionScope: scope,
      activeSessionRef: {
        sessionId: "session:scoped-a",
        scope,
        poolKey,
      },
      sessions: [
        {
          id: "session:main",
          title: "Main",
          created_at: 1,
          updated_at: 9,
          message_count: 0,
        },
      ],
      messages: [{
        id: "old",
        role: "assistant",
        content: "旧 scoped 会话",
        toolCalls: [],
        retrievals: [],
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.removeSession({
      sessionId: "session:scoped-a",
      scope,
      poolKey,
    });

    expect(api.deleteSession).toHaveBeenCalledWith("session:scoped-a", scope);
    expect(api.listSessions).toHaveBeenCalledWith(scope);
    expect(api.listSessions.mock.calls.some((call) => call.length === 0)).toBe(false);
    expect(store.getState().sessions.map((session) => session.id)).toEqual(["session:main"]);
    expect(store.getState().currentSessionId).toBe("session:scoped-b");
    expect(store.getState().activeSessionScope).toEqual(scope);
    expect(store.getState().activeSessionRef).toEqual({
      sessionId: "session:scoped-b",
      scope,
      poolKey,
    });
  });

  it("clears the selected task-environment session without falling back to main chat when the scoped pool is empty", async () => {
    vi.useRealTimers();
    const poolKey = "task_environment:env.general.workspace:project:novel" as const;
    const scope = {
      workspace_view: "task_environment",
      task_environment_id: "env.general.workspace",
      project_id: "project:novel",
    };
    api.listSessions.mockImplementation(async (receivedScope) => {
      if (receivedScope?.workspace_view === scope.workspace_view
        && receivedScope?.task_environment_id === scope.task_environment_id
        && receivedScope?.project_id === scope.project_id) {
        return [];
      }
      return [{
        id: "session:main",
        title: "Main",
        created_at: 1,
        updated_at: 9,
        message_count: 0,
      }];
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:scoped-empty",
      activeSessionScope: scope,
      activeSessionRef: {
        sessionId: "session:scoped-empty",
        scope,
        poolKey,
      },
      sessions: [
        {
          id: "session:main",
          title: "Main",
          created_at: 1,
          updated_at: 9,
          message_count: 0,
        },
      ],
      messages: [{
        id: "old",
        role: "assistant",
        content: "旧 scoped 会话",
        toolCalls: [],
        retrievals: [],
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.removeSession({
      sessionId: "session:scoped-empty",
      scope,
      poolKey,
    });

    expect(api.deleteSession).toHaveBeenCalledWith("session:scoped-empty", scope);
    expect(api.listSessions).toHaveBeenCalledWith(scope);
    expect(api.listSessions.mock.calls.some((call) => call.length === 0)).toBe(false);
    expect(store.getState().sessions.map((session) => session.id)).toEqual(["session:main"]);
    expect(store.getState().currentSessionId).toBeNull();
    expect(store.getState().activeSessionScope).toBeNull();
    expect(store.getState().activeSessionRef).toBeNull();
    expect(store.getState().messages).toEqual([]);
  });

  it("does not synthesize stopped projection from a local abort", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([
      {
        id: "session:stopped",
        title: "Stopped",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      },
      {
        id: "session:other",
        title: "Other",
        created_at: 2,
        updated_at: 2,
        message_count: 0,
      },
    ]);
    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.createSession.mockResolvedValue({
      id: "session:new",
      title: "New Session",
      created_at: 3,
      updated_at: 3,
      message_count: 0,
    });
    api.streamChat.mockImplementation(async () => {
      throw new DOMException("signal is aborted without reason", "AbortError");
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stopped",
      sessions: [
        {
          id: "session:stopped",
          title: "Stopped",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
        },
        {
          id: "session:other",
          title: "Other",
          created_at: 2,
          updated_at: 2,
          message_count: 0,
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("停一下");
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      title: "",
      event: "",
    });
    expect(store.getState().sessionActivitiesById["session:stopped"]).toMatchObject({
      level: "idle",
      title: "",
    });

    await runtime.actions.createNewSession();
    expect(store.getState().currentSessionId).toBe("session:new");
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      event: "",
    });

    await runtime.actions.selectSession({ sessionId: "session:other", poolKey: "main-chat" });
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      event: "",
    });

    await runtime.actions.selectSession({ sessionId: "session:stopped", poolKey: "main-chat" });
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      title: "",
      event: "",
    });
  });

  it("releases the local stream boundary immediately when the user stops output", async () => {
    const firstStreamHandlers: Array<{ onEvent: (event: string, data: Record<string, unknown>) => void }> = [];
    const firstStreamSignals: AbortSignal[] = [];
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers, options) => {
        firstStreamHandlers.push(handlers);
        if (options?.signal) {
          firstStreamSignals.push(options.signal);
        }
        await new Promise<void>(() => undefined);
        return { terminalEvent: "turn_completed", terminalStatus: "completed" };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("done", { content: "第二条已发送" });
        return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:after-stop", eventLogId: "chatrun:after-stop", lastEventOffset: 1 };
      });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stop-boundary",
      sessions: [{
        id: "session:stop-boundary",
        title: "Stop boundary",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    void runtime.actions.sendMessage("第一条会被停止").catch(() => undefined);
    await flushPromises();
    expect(store.getState().activeStreamSessionIds).toEqual(["session:stop-boundary"]);

    runtime.actions.stopCurrentStream();
    const stoppedSignal = firstStreamSignals[0];
    expect(stoppedSignal).toBeDefined();
    expect(stoppedSignal.aborted).toBe(true);
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().chatStreamConnectionStatus.state).toBe("stopped");
    const stoppedHandlers = firstStreamHandlers[0];
    expect(stoppedHandlers).toBeDefined();
    stoppedHandlers.onEvent("assistant_text_delta", { sequence: 1, content: "迟到输出" });
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(JSON.stringify(store.getState().messages)).not.toContain("迟到输出");

    await runtime.actions.sendMessage("停止后继续输入");

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      message: "停止后继续输入",
      session_id: "session:stop-boundary",
    });
    expect(store.getState().sessionActivity.event).not.toBe("user_input_queued");
  });

  it("releases the local stream boundary after reconnect exhaustion without immediate reattach", async () => {
    api.streamChat.mockImplementationOnce(async (_payload, handlers) => {
      handlers.onEvent("stream_reconnect_failed", {
        stream_run_id: "strun:reconnect-exhausted",
        event_log_id: "chatrun:reconnect-exhausted",
        event_offset: 1,
        attempt: 6,
        max_attempts: 6,
        reason: "stream_reconnect_attempts_exhausted",
      });
      throw new Error("stream_reconnect_attempts_exhausted");
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:reconnect-exhausted",
      sessions: [{
        id: "session:reconnect-exhausted",
        title: "Reconnect exhausted",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("这轮会掉线");
    await flushPromises();

    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().isStreaming).toBe(false);
    expect(store.getState().chatStreamConnectionStatus).toMatchObject({
      state: "failed",
      reason: "stream_reconnect_attempts_exhausted",
    });
    expect(api.getLatestChatRunForSession).not.toHaveBeenCalled();
  });

  it("does not reattach after a normal chat stream completion", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:normal-complete",
      sessions: [{
        id: "session:normal-complete",
        title: "Normal complete",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("正常完成");
    await flushPromises();

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.getLatestChatRunForSession).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).not.toHaveBeenCalled();
  });

  it("uses canonical monitor control_state instead of raw runtime_control fallback", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store) as unknown as {
      runtimeControlState: (monitor: Record<string, unknown>) => string;
    };

    expect(runtime.runtimeControlState({
      status: "waiting_executor",
      runtime_control: { state: "paused" },
      task_run: {
        diagnostics: {
          runtime_control: { state: "paused" },
        },
      },
    })).toBe("");
    expect(runtime.runtimeControlState({
      status: "waiting_executor",
      control_state: "paused",
      runtime_control: { state: "running" },
    })).toBe("paused");
  });

  it("stops the task bound to the current chat stream when the user stops output", async () => {
    const taskRunId = "taskrun:turn:session-stop-bound-task:1:abc";
    const activeTurnId = "turn:session-stop-bound-task:1";
    const firstStreamHandlers: Array<{ onEvent: (event: string, data: Record<string, unknown>) => void }> = [];
    const firstStreamSignals: AbortSignal[] = [];
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers, options) => {
        firstStreamHandlers.push(handlers);
        if (options?.signal) {
          firstStreamSignals.push(options.signal);
        }
        await new Promise<void>(() => undefined);
        return { terminalEvent: "turn_completed", terminalStatus: "completed" };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("done", { content: "停止后新输入已发送" });
        return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:after-bound-stop", eventLogId: "chatrun:after-bound-stop", lastEventOffset: 1 };
      });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-stop-bound-task",
      sessions: [{
        id: "session-stop-bound-task",
        title: "Stop bound task",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    void runtime.actions.sendMessage("开始可停止任务").catch(() => undefined);
    await flushPromises();
    firstStreamHandlers[0]?.onEvent("runtime_status", {
      title: "任务运行中",
      state: "running",
      phase: "task_run",
      runtime_task_run_id: taskRunId,
      active_turn_id: activeTurnId,
    });
    await flushPromises();

    runtime.actions.stopCurrentStream();
    await flushPromises();

    expect(firstStreamSignals[0]?.aborted).toBe(true);
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().activeTurnSnapshot).toBeNull();
    expect(api.stopOrchestrationHarnessTaskRun).toHaveBeenCalledWith(
      taskRunId,
      "user_stop_from_chat_stream",
      activeTurnId,
    );

    await runtime.actions.sendMessage("停止后的新要求");

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      message: "停止后的新要求",
      active_turn_input_policy: "auto",
      expected_active_turn_id: "",
    });
    expect(store.getState().sessionActivity.event).not.toBe("user_input_queued");
  });

  it("releases active work gates when a stopped work-control event arrives before the HTTP stream ends", async () => {
    const taskRunId = "taskrun:turn:session-work-control-stop:1:abc";
    const activeTurnId = "turn:session-work-control-stop:1";
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("runtime_status", {
          title: "当前工作已停止",
          detail: "当前工作已停止。",
          state: "stopped",
          phase: "work_control",
          runtime_task_run_id: taskRunId,
          active_turn_id: activeTurnId,
        });
        await new Promise<void>(() => undefined);
        return { terminalEvent: "turn_completed", terminalStatus: "completed" };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        handlers.onEvent("done", { content: "新的要求已发送" });
        return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:after-work-stop", eventLogId: "chatrun:after-work-stop", lastEventOffset: 1 };
      });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-work-control-stop",
      sessions: [{
        id: "session-work-control-stop",
        title: "Work control stop",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    void runtime.actions.sendMessage("停下当前任务").catch(() => undefined);
    await flushPromises();

    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().activeTurnSnapshot).toBeNull();
    expect(store.getState().taskGraphLiveMonitor).toBeNull();
    expect(store.getState().chatStreamConnectionStatus.state).toBe("stopped");

    await runtime.actions.sendMessage("这是新的要求");

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      message: "这是新的要求",
      session_id: "session-work-control-stop",
      active_turn_input_policy: "auto",
      expected_active_turn_id: "",
    });
    expect(store.getState().sessionActivity.event).not.toBe("user_input_queued");
  });

  it("keeps the page mounted when session creation times out during initialization", async () => {
    vi.useRealTimers();
    api.listSessions.mockRejectedValue(new Error("Request timed out after 12000ms: /sessions"));
    api.createSession.mockRejectedValue(new Error("Request timed out after 12000ms: /sessions"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await expect(runtime.initialize()).resolves.toBeUndefined();

    expect(store.getState().workspaceInitializing).toBe(false);
    expect(store.getState().currentSessionId).toBeNull();
    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "会话连接失败",
      event: "workspace_initialize_failed",
    });
  });

  it("restores the last active session and backfills session and project indexes", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveSessionRef"
        ? JSON.stringify({ sessionId: "session:current", poolKey: "main-chat" })
        : null
    );
    api.getSessionSummary.mockResolvedValue({
      id: "session:current",
      title: "Current",
      created_at: 1,
      updated_at: 2,
      message_count: 1,
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "plan" },
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [{ role: "assistant", content: "当前会话内容" }],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "plan" },
    });
    api.listSessions.mockResolvedValue([{
      id: "session:current",
      title: "Current",
      created_at: 1,
      updated_at: 2,
      message_count: 1,
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "plan" },
    }]);
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [],
      summary: { project_count: 0 },
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.getSessionSummary).toHaveBeenCalledWith("session:current", undefined);
    expect(api.getWorkbenchCurrentSession).toHaveBeenCalledTimes(1);
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(api.listProjectWorkspaces).toHaveBeenCalledTimes(1);
    expect(store.getState().workspaceInitializing).toBe(false);
    expect(store.getState().currentSessionId).toBe("session:current");
    expect(store.getState().sessions.map((session) => session.id)).toContain("session:current");
    expect(store.getState().permissionMode).toBe("plan");
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "当前会话内容" },
    ]);
    const rememberedRefWrite = vi.mocked(window.localStorage.setItem).mock.calls.find(([key]) =>
      key === "agentWorkbench.lastActiveSessionRef"
    );
    expect(rememberedRefWrite).toBeTruthy();
    const rememberedRefPayload = JSON.parse(String(rememberedRefWrite?.[1] || "{}"));
    expect(rememberedRefPayload).toMatchObject({ sessionId: "session:current", poolKey: "main-chat" });
    expect(typeof rememberedRefPayload.updatedAt).toBe("number");
    expect(api.setWorkbenchCurrentSession).toHaveBeenCalledWith({
      sessionId: "session:current",
      scope: undefined,
      poolKey: "main-chat",
    });
  });

  it("restores a project-bound remembered session before project metadata finishes loading", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveSessionRef"
        ? JSON.stringify({ sessionId: "session:project", poolKey: "main-chat" })
        : null
    );
    api.getSessionSummary.mockResolvedValue({
      id: "session:project",
      title: "Project session",
      created_at: 1,
      updated_at: 2,
      message_count: 1,
      conversation_state: {
        authority: "sessions.conversation_state",
        project_binding: { workspace_root: "D:/repo", source: "test" },
      },
    });
    api.listProjectWorkspaces.mockImplementation(() => new Promise(() => undefined));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(store.getState().workspaceInitializing).toBe(false);
    expect(store.getState().currentSessionId).toBe("session:project");
    expect(store.getState().activeSessionRef?.sessionId).toBe("session:project");
    expect(api.listProjectWorkspaces).toHaveBeenCalledTimes(1);
  });

  it("restores the backend-persisted current session when local storage has no ref", async () => {
    vi.useRealTimers();
    api.getWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: {
        authority: "workbench.current_session_ref",
        session_id: "session:persisted",
        scope: {},
        pool_key: "main-chat",
        updated_at: 2,
      },
    });
    api.getSessionSummary.mockResolvedValue({
      id: "session:persisted",
      title: "Persisted",
      created_at: 1,
      updated_at: 2,
      message_count: 0,
    });
    api.listSessions.mockResolvedValue([{
      id: "session:persisted",
      title: "Persisted",
      created_at: 1,
      updated_at: 2,
      message_count: 0,
    }]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.getWorkbenchCurrentSession).toHaveBeenCalledTimes(1);
    expect(api.getSessionSummary).toHaveBeenCalledWith("session:persisted", undefined);
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(api.listProjectWorkspaces).toHaveBeenCalledTimes(1);
    expect(store.getState().currentSessionId).toBe("session:persisted");
    expect(store.getState().sessions.map((session) => session.id)).toContain("session:persisted");
  });

  it("prefers the newer backend current session over a stale browser ref", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveSessionRef"
        ? JSON.stringify({ sessionId: "session:stale", poolKey: "main-chat" })
        : null
    );
    api.getWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: {
        authority: "workbench.current_session_ref",
        session_id: "session:persisted-current",
        scope: {},
        pool_key: "main-chat",
        updated_at: 20,
      },
    });
    api.getSessionSummary.mockImplementation(async (sessionId) => ({
      id: String(sessionId),
      title: String(sessionId) === "session:persisted-current" ? "Persisted Current" : "Stale",
      created_at: 1,
      updated_at: String(sessionId) === "session:persisted-current" ? 20 : 1,
      message_count: 0,
    }));
    api.listSessions.mockResolvedValue([{
      id: "session:persisted-current",
      title: "Persisted Current",
      created_at: 1,
      updated_at: 20,
      message_count: 0,
    }, {
      id: "session:stale",
      title: "Stale",
      created_at: 1,
      updated_at: 1,
      message_count: 0,
    }]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.getWorkbenchCurrentSession).toHaveBeenCalledTimes(1);
    expect(api.getSessionSummary).toHaveBeenCalledWith("session:persisted-current", undefined);
    expect(api.getSessionSummary).not.toHaveBeenCalledWith("session:stale", undefined);
    expect(store.getState().currentSessionId).toBe("session:persisted-current");
  });

  it("restores a backend-persisted project-bound current session into its project workspace", async () => {
    vi.useRealTimers();
    const boundSession = {
      id: "session:bound-current",
      title: "Bound Current",
      created_at: 1,
      updated_at: 3,
      message_count: 12,
      conversation_state: {
        authority: "sessions.conversation_state",
        project_binding: {
          workspace_root: "D:/repo",
          source: "project_workspace",
          bound_at: 1,
          last_seen_at: 3,
          immutable: true,
          authority: "sessions.project_binding",
        },
      },
    };
    api.getWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: {
        authority: "workbench.current_session_ref",
        session_id: "session:bound-current",
        scope: {},
        pool_key: "main-chat",
        updated_at: 3,
      },
    });
    api.getSessionSummary.mockResolvedValue(boundSession);
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [{
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "session.project_binding",
        created_at: 1,
        last_seen_at: 3,
        session_count: 1,
        latest_session_at: 3,
        available: true,
        authority: "project_workspaces.workspace",
      }],
      summary: { project_count: 1 },
    });
    api.listProjectWorkspaceSessions.mockResolvedValue({
      authority: "project_workspaces.sessions",
      project_key: "workspace:repo",
      sessions: [],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.listProjectWorkspaces).toHaveBeenCalledTimes(1);
    expect(api.listProjectWorkspaceSessions).toHaveBeenCalledWith("workspace:repo");
    expect(store.getState().activeProjectKey).toBe("workspace:repo");
    expect(store.getState().activeProjectRoot).toBe("D:/repo");
    expect(store.getState().currentSessionId).toBe("session:bound-current");
    expect(store.getState().projectSessions.map((session) => session.id)).toContain("session:bound-current");
  });

  it("ignores a backend-persisted graph node current session and restores the latest visible project chat", async () => {
    vi.useRealTimers();
    const graphNodeSession = {
      id: "gsess:graph-node",
      title: "Graph node",
      created_at: 1,
      updated_at: 5,
      message_count: 1,
      scope: {
        workspace_view: "project",
        project_id: "project.creation.writing.honghuang",
      },
    };
    const boundSession = {
      id: "session:bound-latest",
      title: "Bound Latest",
      created_at: 1,
      updated_at: 4,
      message_count: 12,
      conversation_state: {
        authority: "sessions.conversation_state",
        project_binding: {
          workspace_root: "D:/repo",
          source: "project_workspace",
          bound_at: 1,
          last_seen_at: 4,
          immutable: true,
          authority: "sessions.project_binding",
        },
      },
    };
    const unboundSession = {
      id: "session:unbound",
      title: "Unbound",
      created_at: 1,
      updated_at: 3,
      message_count: 1,
      conversation_state: {
        authority: "sessions.conversation_state",
      },
    };
    api.getWorkbenchCurrentSession.mockResolvedValue({
      authority: "workbench.current_session_ref",
      current_session: {
        authority: "workbench.current_session_ref",
        session_id: "gsess:graph-node",
        scope: {
          workspace_view: "project",
          project_id: "project.creation.writing.honghuang",
        },
        pool_key: "main-chat",
        updated_at: 5,
      },
    });
    api.getSessionSummary.mockResolvedValue(graphNodeSession);
    api.listSessions.mockResolvedValue([graphNodeSession, boundSession, unboundSession]);
    api.listProjectWorkspaces.mockResolvedValue({
      authority: "project_workspaces.list",
      projects: [{
        key: "workspace:repo",
        workspace_root: "D:/repo",
        name: "repo",
        source: "session.project_binding",
        created_at: 1,
        last_seen_at: 4,
        session_count: 1,
        latest_session_at: 4,
        available: true,
        authority: "project_workspaces.workspace",
      }],
      summary: { project_count: 1 },
    });
    api.listProjectWorkspaceSessions.mockResolvedValue({
      authority: "project_workspaces.sessions",
      project_key: "workspace:repo",
      sessions: [boundSession],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await flushPromises();

    expect(api.clearWorkbenchCurrentSession).toHaveBeenCalledWith("gsess:graph-node");
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(api.listProjectWorkspaceSessions).toHaveBeenCalledWith("workspace:repo");
    expect(store.getState().activeProjectKey).toBe("workspace:repo");
    expect(store.getState().activeProjectRoot).toBe("D:/repo");
    expect(store.getState().currentSessionId).toBe("session:bound-latest");
    expect(store.getState().projectSessions.map((session) => session.id)).toEqual(["session:bound-latest"]);
  });

  it("falls back to the session index when the remembered session is gone", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveSessionRef"
        ? JSON.stringify({ sessionId: "session:missing", poolKey: "main-chat" })
        : null
    );
    api.getSessionSummary.mockRejectedValue(new Error('{"detail":"Unknown session_id"}'));
    api.listSessions.mockResolvedValue([{
      id: "session:fallback",
      title: "Fallback",
      created_at: 1,
      updated_at: 1,
      message_count: 0,
    }]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(api.getSessionSummary).toHaveBeenCalledWith("session:missing", undefined);
    expect(window.localStorage.removeItem).toHaveBeenCalledWith("agentWorkbench.lastActiveSessionRef");
    expect(api.clearWorkbenchCurrentSession).toHaveBeenCalledWith("session:missing");
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(store.getState().currentSessionId).toBe("session:fallback");
  });

  it("does not surface delayed session refresh timeouts as unhandled errors", async () => {
    api.listSessions.mockRejectedValue(new Error("Request timed out after 12000ms: /sessions"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      scheduleSessionRefreshes: (delays: number[]) => void;
    };

    runtimeHarness.scheduleSessionRefreshes([1500]);
    await vi.advanceTimersByTimeAsync(1500);

    expect(store.getState().sessionActivity.event).toBe("");
    expect(store.getState().sessionActivity.level).toBe("idle");
  });

  it("unblocks chat before existing session history and monitor metadata finish loading", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:existing",
      title: "Existing",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.getSessionHistory.mockImplementation(() => new Promise(() => undefined));
    api.getSessionTokens.mockImplementation(() => new Promise(() => undefined));
    api.getOrchestrationHarnessSessionLiveMonitor.mockImplementation(() => new Promise(() => undefined));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(store.getState().currentSessionId).toBe("session:existing");
    expect(store.getState().workspaceInitializing).toBe(false);
  });

  it("keeps session history visible while token statistics are still loading", async () => {
    api.getSessionHistory.mockResolvedValue({
      messages: [{ role: "user", content: "继续修复 token 统计" }],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    api.getSessionTokens.mockImplementation(() => new Promise(() => undefined));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:tokens",
      sessions: [{
        id: "session:tokens",
        title: "Token Session",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
      tokenStats: {
        system_tokens: 1,
        message_tokens: 2,
        total_tokens: 3,
        raw_history_tokens: 3,
        history_tokens: 3,
        history_budget_tokens: 100,
        history_remaining_tokens: 97,
        history_usage_ratio: 0.03,
        history_remaining_ratio: 0.97,
        history_pressure_level: "normal",
        history_compaction_strategy: "none",
        history_did_compact: false,
        history_did_microcompact: false,
        history_did_full_compact: false,
      },
    });
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    await runtimeHarness.refreshSessionDetails("session:tokens");

    expect(store.getState().messages).toHaveLength(1);
    expect(store.getState().messages[0].content).toBe("继续修复 token 统计");
    expect(store.getState().tokenStats?.total_tokens).toBe(3);
    expect(store.getState().sessionActivity.event).toBe("");
    expect(api.getSessionTokens).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(4999);
    expect(api.getSessionTokens).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(api.getSessionTokens).toHaveBeenCalledWith("session:tokens", undefined);
  });

  it("shows lightweight session history before delayed runtime projection starts", async () => {
    api.getSessionHistory.mockResolvedValue({
      messages: [{ role: "assistant", content: "轻量历史先显示" }],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    api.getSessionRuntimeProjection.mockImplementation(() => new Promise(() => undefined));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:projection-pending",
      sessions: [{
        id: "session:projection-pending",
        title: "Projection Pending",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    await runtime.refreshSessionDetails("session:projection-pending");

    expect(api.getSessionHistory).toHaveBeenCalledWith("session:projection-pending", undefined);
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1599);
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(api.getSessionRuntimeProjection).toHaveBeenCalledWith("session:projection-pending", undefined);
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "轻量历史先显示" },
    ]);
  });

  it("does not carry a volatile attachment to a refreshed message with the same source index but a different turn", async () => {
    const sessionId = "session:source-index-noise";
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "新问题", turn_id: "turn:session:source-index-noise:2" },
        { id: "assistant:new", role: "assistant", content: "新回答", turn_id: "turn:session:source-index-noise:2" },
      ],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      sessions: [{
        id: sessionId,
        title: "Source index noise",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
      messages: [
        {
          id: "user:old",
          role: "user",
          content: "旧问题",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0,
          sourceTurnId: "turn:session:source-index-noise:1",
        },
        {
          id: "assistant:old",
          role: "assistant",
          content: "旧回答",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 1,
          sourceTurnId: "turn:session:source-index-noise:1",
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    await runtime.refreshSessionDetails(sessionId);

    const visiblePayload = JSON.stringify(store.getState().messages);
    expect(visiblePayload).toContain("新回答");
    expect(visiblePayload).not.toContain("backend/old_context.py");
  });

  it("keeps the local streaming assistant shell when session history refresh races with deltas", async () => {
    const sessionId = "session:live-refresh";
    const assistantId = "assistant:local-live";
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "请回答" },
        { role: "assistant", content: "后端历史旧壳" },
      ],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      activeStreamSessionIds: [sessionId],
      isStreaming: true,
      sessions: [{
        id: sessionId,
        title: "Live",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
      messages: [
        {
          id: "user:local-live",
          role: "user",
          content: "请回答",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0,
        },
        {
          id: assistantId,
          role: "assistant",
          content: "遇到",
          toolCalls: [],
          retrievals: [],
          runtimeProgress: [],
          sourceIndex: 1,
        },
      ],
      assistantTextStreamsByMessageId: {
        [assistantId]: {
          messageId: assistantId,
          messageRef: "turn:session:live-refresh:assistant",
          streamRef: "modelreq:live-refresh",
          latestSequence: 1,
          canonicalContent: "遇到",
          canonicalContentSha256: "sha256:first",
          accumulatedUtf8Bytes: 6,
          finalReceived: false,
          terminal: false,
          repairState: "none",
          displayHintsBySequence: {},
        },
      },
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionDetails: (sessionId: string) => Promise<void>;
    };

    await runtime.refreshSessionDetails(sessionId);

    expect(store.getState().messages.at(-1)?.id).toBe(assistantId);
    expect(store.getState().messages.at(-1)?.content).toBe("遇到");

    const transition = reduceStreamEvent(
      store.getState(),
      { assistantId },
      "assistant_text_delta",
      {
        sequence: 2,
        content: "前端",
        content_utf8_start: 6,
        accumulated_utf8_bytes: 12,
        accumulated_sha256: "sha256:second",
      },
    );
    store.setState(() => transition.state);

    expect(store.getState().messages.at(-1)?.id).toBe(assistantId);
    expect(store.getState().messages.at(-1)?.content).toBe("遇到");
    expect(store.getState().assistantTextStreamsByMessageId[assistantId]?.canonicalContent).toBe("遇到");
  });

  it("reattaches a persisted chat run during initialization without starting a new run", async () => {
    vi.useRealTimers();
    const cursor = {
      streamRunId: "strun:resume",
      eventLogId: "chatrun:resume",
      lastEventOffset: 3,
      lastEventId: "strun:resume:chatrun:resume:3",
    };
    api.listSessions.mockResolvedValue([{
      id: "session:existing",
      title: "Existing",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(cursor);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:resume",
      session_id: "session:existing",
      event_log_id: "chatrun:resume",
      root_request_ref: "chatreq:resume",
      status: "running",
      diagnostics: {
        active_turn_id: "turn:session:existing:7",
        runtime_turn_run_id: "turnrun:strun:resume",
        runtime_task_run_id: "taskrun:session:existing:7",
      },
      latest_event_offset: 3,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:resume/events/replay",
      live_ws_url: "/api/chat/sessions/session:existing/live",
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
        { role: "assistant", content: "续接完成" },
      ],
    });
    const store = createStore(getDefaultState());
    let recoveryActivityDuringAttach: unknown;
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      recoveryActivityDuringAttach = store.getState().sessionActivity;
      handlers.onEvent("assistant_text_delta", { sequence: 1, content: "续", content_utf8_start: 0, event_offset: 4 });
      handlers.onEvent("assistant_text_final", { sequence: 2, content: "续接完成", content_sha256: "sha256:resume", event_offset: 5 });
      handlers.onEvent("done", { content: "续接完成", event_offset: 5 });
      return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:resume", eventLogId: "chatrun:resume", lastEventOffset: 5 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:existing",
      "strun:resume",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: cursor,
      }),
    );
    expect(api.streamExistingChatRun.mock.calls.at(-1)?.[3]).not.toHaveProperty("replayFromStart", true);
    expect(store.getState().currentSessionId).toBe("session:existing");
    expect(store.getState().messages.some((message) => message.role === "assistant" && message.content.includes("续"))).toBe(true);
    expect(store.getState().activeTurnSnapshot).toBeNull();
    expect(recoveryActivityDuringAttach).toMatchObject({
      level: "running",
      title: "恢复输出流",
      detail: "检测到同一会话的流式 cursor，正在按事件时序重放公开投影。",
      event: "stream_cursor_restore_started",
    });
    expect(JSON.stringify(store.getState().messages)).not.toContain("正在重新连接");
  });

  it("does not reattach from a persisted cursor when there is no backend-confirmed active run", async () => {
    vi.useRealTimers();
    const cursor = {
      streamRunId: "strun:old-cursor",
      eventLogId: "chatrun:old-cursor",
      lastEventOffset: 7,
      lastEventId: "strun:old-cursor:chatrun:old-cursor:7",
    };
    api.listSessions.mockResolvedValue([{
      id: "session:no-active-run",
      title: "No active run",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(cursor);
    api.getLatestChatRunForSession.mockResolvedValue(null);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.clearChatStreamCursor).toHaveBeenCalledWith("session:no-active-run");
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().isStreaming).toBe(false);
  });

  it("creates a transient assistant shell for recovered live streams without persisted assistant output", async () => {
    vi.useRealTimers();
    const cursor = {
      streamRunId: "strun:wait",
      eventLogId: "chatrun:wait",
      lastEventOffset: 1,
      lastEventId: "strun:wait:chatrun:wait:1",
    };
    api.listSessions.mockResolvedValue([{
      id: "session:wait",
      title: "Waiting",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(cursor);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:wait",
      session_id: "session:wait",
      event_log_id: "chatrun:wait",
      root_request_ref: "chatreq:wait",
      status: "running",
      diagnostics: {
        active_turn_id: "turn:session:wait:1",
        runtime_turn_run_id: "turnrun:wait",
        runtime_task_run_id: "taskrun:wait",
      },
      latest_event_offset: 1,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:wait/events/replay",
      live_ws_url: "/api/chat/sessions/session:wait/live",
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理", turn_id: "turn:session:wait:1" },
      ],
    });
    const store = createStore(getDefaultState());
    let messagesDuringAttach: StoreState["messages"] = [];
    api.streamExistingChatRun.mockImplementation(async () => {
      messagesDuringAttach = store.getState().messages;
      return { terminalEvent: "turn_completed", terminalStatus: "completed", streamRunId: "strun:wait", eventLogId: "chatrun:wait", lastEventOffset: 1 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    const shell = messagesDuringAttach.find((message) => message.role === "assistant");
    expect(shell).toMatchObject({
      content: "",
      sourceStreamRunId: "strun:wait",
      sourceTaskRunId: "taskrun:wait",
      sourceTurnId: "turn:session:wait:1",
      sourceTurnRunId: "turnrun:wait",
    });
    expect(api.getSessionHistory).toHaveBeenCalled();
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("reattaches a recovered chat stream without rereading history when visible messages are already hydrated", async () => {
    vi.useRealTimers();
    const sessionId = "session:visible-recovery";
    const cursor = {
      streamRunId: "strun:visible-recovery",
      eventLogId: "chatrun:visible-recovery",
      lastEventOffset: 1,
      lastEventId: "strun:visible-recovery:chatrun:visible-recovery:1",
    };
    api.readChatStreamCursor.mockReturnValue(cursor);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: cursor.streamRunId,
      session_id: sessionId,
      event_log_id: cursor.eventLogId,
      root_request_ref: "chatreq:visible-recovery",
      status: "running",
      diagnostics: {},
      latest_event_offset: 1,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:visible-recovery/events/replay",
      live_ws_url: "/api/chat/sessions/session:visible-recovery/live",
    });
    api.streamExistingChatRun.mockResolvedValue({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: cursor.streamRunId,
      eventLogId: cursor.eventLogId,
      lastEventOffset: 1,
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      sessions: [{
        id: sessionId,
        title: "Visible Recovery",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
      messages: [
        { id: "user:visible", role: "user", content: "已有历史", toolCalls: [], retrievals: [] },
        { id: "assistant:visible", role: "assistant", content: "已有回答", toolCalls: [], retrievals: [] },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      reattachChatRunForSession: (sessionId: string) => Promise<boolean>;
    };

    const reattached = await runtime.reattachChatRunForSession(sessionId);
    await flushPromises(10);

    expect(reattached).toBe(true);
    expect(api.getSessionHistory).not.toHaveBeenCalled();
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).toHaveBeenCalled();
  });

  it("merges runtime projection refresh into an active recovered stream shell", async () => {
    vi.useRealTimers();
    const sessionId = "session:projection-refresh-active";
    const turnId = "turn:projection-refresh-active:1";
    const streamRunId = "strun:projection-refresh-active";
    const turnRunId = "turnrun:projection-refresh-active";
    const assistantMessageId = "turn:projection-refresh-active:1:assistant";
    const shellAssistantId = "assistant:projection-refresh-shell";
    api.getSessionRuntimeProjection.mockResolvedValue({
      messages: [
        {
          id: "user:projection-refresh-active",
          role: "user",
          content: "继续",
          turn_id: turnId,
        },
      ],
      runtime_attachments: [
        runtimeProjectionAttachmentForTest({
          sessionId,
          turnId,
          assistantMessageId,
          streamRunId,
          turnRunId,
          text: "恢复后的公开正文。",
        }),
      ],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: sessionId,
      activeStreamSessionIds: [sessionId],
      isStreaming: true,
      messages: [
        {
          id: "user:projection-refresh-active",
          role: "user",
          content: "继续",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0,
          sourceTurnId: turnId,
        },
        {
          id: shellAssistantId,
          role: "assistant",
          content: "",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0.5,
          sourceTurnId: turnId,
          sourceStreamRunId: streamRunId,
          sourceRunId: streamRunId,
          sourceTurnRunId: turnRunId,
        },
      ],
      activeProjectionsByKey: {},
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      refreshSessionRuntimeProjection: (sessionId: string, detailsRequestId?: number) => Promise<void>;
    };

    await runtime.refreshSessionRuntimeProjection(sessionId);

    const state = store.getState();
    const assistantMessages = state.messages.filter((message) =>
      message.role === "assistant" && message.sourceTurnId === turnId
    );
    const assistant = state.messages.find((message) => message.id === shellAssistantId);
    const projectionView = assistant?.projectionKeyString
      ? state.activeProjectionsByKey[assistant.projectionKeyString]?.view
      : undefined;

    expect(assistantMessages).toHaveLength(1);
    expect(assistant?.projectionKeyString).toBeTruthy();
    expect(projectionView?.canonicalContent).toBe("恢复后的公开正文。");
  });

  it("reattaches the latest active chat run when the local cursor is missing", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:latest",
      title: "Latest",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(null);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:latest",
      session_id: "session:latest",
      event_log_id: "chatrun:latest",
      root_request_ref: "chatreq:latest",
      status: "running",
      latest_event_offset: 3,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:latest/events/replay",
      live_ws_url: "/api/chat/sessions/session:latest/live",
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
      ],
    });
    const store = createStore(getDefaultState());
    let recoveryActivityDuringAttach: unknown;
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      recoveryActivityDuringAttach = store.getState().sessionActivity;
      handlers.onEvent("assistant_text_delta", { sequence: 1, content: "续", content_utf8_start: 0, event_offset: 4 });
      return { terminalEvent: "", terminalStatus: "running", streamRunId: "strun:latest", eventLogId: "chatrun:latest", lastEventOffset: 4 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:latest",
      "strun:latest",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: {
          streamRunId: "strun:latest",
          eventLogId: "chatrun:latest",
          lastEventOffset: -1,
          lastEventId: "",
        },
      }),
    );
    expect(recoveryActivityDuringAttach).toMatchObject({
      event: "stream_cursor_restore_started",
      title: "恢复输出流",
    });
  });

  it("drops an invalid persisted cursor and reattaches the latest active chat run", async () => {
    vi.useRealTimers();
    const staleCursor = {
      streamRunId: "strun:stale",
      eventLogId: "chatrun:stale",
      lastEventOffset: 99,
      lastEventId: "strun:stale:chatrun:stale:99",
    };
    api.listSessions.mockResolvedValue([{
      id: "session:latest-after-stale",
      title: "Latest after stale",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(staleCursor);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:latest-after-stale",
      session_id: "session:latest-after-stale",
      event_log_id: "chatrun:latest-after-stale",
      root_request_ref: "chatreq:latest-after-stale",
      status: "running",
      latest_event_offset: 1,
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:latest-after-stale/events/replay",
      live_ws_url: "/api/chat/sessions/session:latest-after-stale/live",
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
      ],
    });
    const store = createStore(getDefaultState());
    api.streamExistingChatRun.mockResolvedValue({
      terminalEvent: "",
      terminalStatus: "running",
      streamRunId: "strun:latest-after-stale",
      eventLogId: "chatrun:latest-after-stale",
      lastEventOffset: 1,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.clearChatStreamCursor).toHaveBeenCalledWith("session:latest-after-stale");
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:latest-after-stale",
      "strun:latest-after-stale",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: {
          streamRunId: "strun:latest-after-stale",
          eventLogId: "chatrun:latest-after-stale",
          lastEventOffset: -1,
          lastEventId: "",
        },
      }),
    );
  });

  it("does not reattach a terminal chat run when the persisted cursor already reached the final event", async () => {
    vi.useRealTimers();
    const cursor = {
      streamRunId: "strun:terminal",
      eventLogId: "chatrun:terminal",
      lastEventOffset: 9,
      lastEventId: "strun:terminal:chatrun:terminal:9",
    };
    api.listSessions.mockResolvedValue([{
      id: "session:terminal",
      title: "Terminal",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.readChatStreamCursor.mockReturnValue(cursor);
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:terminal",
      session_id: "session:terminal",
      event_log_id: "chatrun:terminal",
      root_request_ref: "chatreq:terminal",
      status: "completed",
      latest_event_offset: 9,
      terminal_event: "turn_completed",
      is_reconnectable: true,
      replay_url: "/api/chat/runs/strun:terminal/events/replay",
      live_ws_url: "/api/chat/sessions/session:terminal/live",
    });
    api.getSessionHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "任务" },
        { role: "assistant", content: "完成" },
      ],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.clearChatStreamCursor).toHaveBeenCalledWith("session:terminal");
    expect(api.getChatRun).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("sends to the newly created session when the user submits during creation", async () => {
    vi.useRealTimers();
    let resolveCreate: (value: {
      id: string;
      title: string;
      created_at: number;
      updated_at: number;
      message_count: number;
    }) => void = () => undefined;
    api.createSession.mockImplementation(() => new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    api.listSessions.mockResolvedValue([
      {
        id: "session:new",
        title: "New Session",
        created_at: 2,
        updated_at: 2,
        message_count: 0,
      },
      {
        id: "session:old",
        title: "Old",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      },
    ]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:old",
      sessions: [
        {
          id: "session:old",
          title: "Old",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    const createPromise = runtime.actions.createNewSession();
    const sendPromise = runtime.actions.sendMessage("马上发送");
    expect(api.streamChat).not.toHaveBeenCalled();

    resolveCreate({
      id: "session:new",
      title: "New Session",
      created_at: 2,
      updated_at: 2,
      message_count: 0,
    });
    await Promise.all([createPromise, sendPromise]);

    expect(api.streamChat).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "马上发送",
        session_id: "session:new",
      }),
      expect.any(Object),
      expect.any(Object),
    );
    expect(store.getState().currentSessionId).toBe("session:new");
  });

  it("does not carry a previous active turn into the first message of a new session", async () => {
    vi.useRealTimers();
    api.createSession.mockResolvedValue({
      id: "session:new-clean",
      title: "New Session",
      created_at: 2,
      updated_at: 2,
      message_count: 0,
    });
    api.listSessions.mockResolvedValue([{
      id: "session:new-clean",
      title: "New Session",
      created_at: 2,
      updated_at: 2,
      message_count: 0,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:old",
      sessions: [{
        id: "session:old",
        title: "Old",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
      activeTurnSnapshot: {
        turn_id: "turn:session-old:1",
        task_run_id: "taskrun:session-old:1",
        state: "running_task",
      },
      taskGraphLiveMonitor: itemForMonitor({
        session_id: "session:old",
        task_run_id: "taskrun:session-old:1",
        status: "running",
        execution_runtime_kind: "single_agent_task",
      }) as any,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.createNewSession();
    expect(store.getState().currentSessionId).toBe("session:new-clean");
    expect(store.getState().activeTurnSnapshot).toBeNull();
    expect(store.getState().taskGraphLiveMonitor).toBeNull();

    await runtime.actions.sendMessage("新对话第一句");

    expect(api.enqueueQueuedChatInput).not.toHaveBeenCalled();
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      message: "新对话第一句",
      session_id: "session:new-clean",
    });
  });

  it("derives a session title from the first user message after the first completed turn", async () => {
    vi.useRealTimers();
    api.deriveSessionTitleFromFirstUserMessage.mockResolvedValueOnce({
      session_id: "session:fresh",
      title: "会话标题修复",
    });
    api.listSessions.mockResolvedValue([{
      id: "session:fresh",
      title: "会话标题修复",
      created_at: 1,
      updated_at: 2,
      message_count: 2,
    }]);
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("我的对话名怎么都成 New Session 了，帮我修一下");
    await flushPromises(8);

    expect(api.deriveSessionTitleFromFirstUserMessage).toHaveBeenCalledWith("session:fresh", undefined);
    expect(store.getState().sessions.find((session) => session.id === "session:fresh")?.title).toBe("会话标题修复");
  });

  it("does not derive a summary title for a manually titled session", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:manual",
      sessions: [{
        id: "session:manual",
        title: "手动标题",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    api.listSessions.mockResolvedValue([{
      id: "session:manual",
      title: "手动标题",
      created_at: 1,
      updated_at: 2,
      message_count: 2,
    }]);
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("这句话不应该覆盖标题");
    await flushPromises(8);

    expect(api.deriveSessionTitleFromFirstUserMessage).not.toHaveBeenCalled();
    expect(store.getState().sessions.find((session) => session.id === "session:manual")?.title).toBe("手动标题");
  });

  it("keeps the page alive when selected session history times out", async () => {
    vi.useRealTimers();
    api.getSessionHistory.mockRejectedValue(new Error("Request timed out after 12000ms: /sessions/session:slow/history"));
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:current",
      sessions: [
        {
          id: "session:current",
          title: "Current",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
        },
        {
          id: "session:slow",
          title: "Slow",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
        },
      ],
      messages: [{
        id: "existing-message",
        role: "assistant",
        content: "旧消息",
        toolCalls: [],
        retrievals: [],
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await expect(runtime.actions.selectSession({ sessionId: "session:slow", poolKey: "main-chat" })).resolves.toBeUndefined();

    expect(store.getState().currentSessionId).toBe("session:slow");
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().isStreaming).toBe(false);
    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "历史读取超时",
      event: "session_history_load_failed",
    });
  });

  it("keeps the workspace interactive and reports an error when the project/session index fails", async () => {
    vi.useRealTimers();
    api.listProjectWorkspaces.mockRejectedValue(new Error("backend offline"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();

    expect(store.getState().workspaceInitializing).toBe(false);
    expect(store.getState().currentSessionId).toBeNull();
    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "会话连接失败",
      event: "workspace_initialize_failed",
    });
  });

  it("clears the initialization failure state after a session loads successfully", async () => {
    vi.useRealTimers();
    api.getSessionHistory.mockResolvedValue({
      messages: [{ role: "assistant", content: "恢复成功" }],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:recover",
      sessions: [
        {
          id: "session:recover",
          title: "Recover",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
        },
      ],
      sessionActivity: {
        level: "error",
        title: "会话连接失败",
        detail: "无法创建或读取会话。",
        event: "workspace_initialize_failed",
        updatedAt: 1,
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectSession({ sessionId: "session:recover", poolKey: "main-chat" });

    expect(store.getState().sessionActivity.event).toBe("");
    expect(store.getState().sessionActivity.level).toBe("idle");
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "恢复成功" },
    ]);
  });

  it("throws and leaves no optimistic user message when sending cannot create a session", async () => {
    vi.useRealTimers();
    api.createSession.mockRejectedValue(new Error("backend offline"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await expect(runtime.actions.sendMessage("你好")).rejects.toThrow("backend offline");

    expect(store.getState().messages).toEqual([]);
    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "会话连接失败",
      event: "session_create_failed",
    });
  });

  it("sends enabled thinking without explicit effort for a reasoning-capable system default chat model", async () => {
    vi.useRealTimers();
    api.streamChat.mockResolvedValue({ terminalEvent: "turn_completed", terminalStatus: "completed" });
    api.listSessions.mockResolvedValue([{
      id: "session:reasoning",
      title: "Reasoning",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:reasoning",
      modelProviderConfig: {
        provider: "openai",
        model: "gpt-5",
        base_url: "https://api.openai.com/v1",
        credential_ref: "provider:openai:primary",
        api_key_configured: true,
        fallback_provider: "",
        fallback_model: "",
        fallback_base_url: "",
        fallback_credential_ref: "",
        fallback_api_key_configured: false,
        supported_providers: {
          openai: {
            provider: "openai",
            default_model: "gpt-5",
            default_base_url: "https://api.openai.com/v1",
            credential_ref: "provider:openai:primary",
            capability_tags: ["reasoning", "openai_compatible"],
          },
        },
        provider_catalog: {
          authority: "runtime.model_provider_catalog",
          default_provider: "openai",
          default_model: "gpt-5",
          providers: {
            openai: {
              provider: "openai",
              default_model: "gpt-5",
              default_base_url: "https://api.openai.com/v1",
              credential_ref: "provider:openai:primary",
              capability_tags: ["reasoning", "openai_compatible"],
            },
          },
          credential_refs: [],
        },
        authority: "runtime.model_provider",
      },
      chatThinkingMode: "thinking",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("需要深度审查这一段");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toEqual({
      selection_id: "system-default",
      provider: "openai",
      model: "gpt-5",
      base_url: "https://api.openai.com/v1",
      credential_ref: "provider:openai:primary",
      thinking_mode: "enabled",
      stream_policy: {
        enabled: true,
        mode: "model_text_stream",
        emit_assistant_text_delta: true,
        upstream_reconnect_enabled: true,
        partial_stream_recovery: "continue_from_visible_prefix",
        chunk_strategy: "adaptive_buffer",
        first_flush_delay_ms: 70,
        target_buffer_delay_ms: 150,
        adaptive_min_buffer_delay_ms: 80,
        adaptive_max_buffer_delay_ms: 240,
        release_tick_ms: 16,
        max_buffer_delay_ms: 320,
        max_pending_utf8_bytes: 1536,
        max_release_utf8_bytes: 192,
        max_pending_line_count: 1,
        min_event_interval_ms: 16,
        event_budget_per_second: 45,
        source: "frontend.chat_stream_display_toggle",
      },
    });
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).not.toHaveProperty("reasoning_effort");
  });

  it("omits explicit effort when chat thinking mode is auto thinking", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:thinking-high",
      title: "Thinking High",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:thinking-high",
      modelProviderConfig: {
        provider: "deepseek",
        model: "deepseek-v4-flash",
        base_url: "https://api.deepseek.com",
        credential_ref: "provider:deepseek:primary",
        api_key_configured: true,
        fallback_provider: "",
        fallback_model: "",
        fallback_base_url: "",
        fallback_credential_ref: "",
        fallback_api_key_configured: false,
        supported_providers: {
          deepseek: {
            provider: "deepseek",
            default_model: "deepseek-v4-flash",
            default_base_url: "https://api.deepseek.com",
            credential_ref: "provider:deepseek:primary",
            capability_tags: ["reasoning", "openai_compatible"],
          },
        },
        provider_catalog: {
          authority: "runtime.model_provider_catalog",
          default_provider: "deepseek",
          default_model: "deepseek-v4-flash",
          providers: {
            deepseek: {
              provider: "deepseek",
              default_model: "deepseek-v4-flash",
              default_base_url: "https://api.deepseek.com",
              credential_ref: "provider:deepseek:primary",
              capability_tags: ["reasoning", "openai_compatible"],
            },
          },
          credential_refs: [],
        },
        authority: "runtime.model_provider",
      },
      chatThinkingMode: "thinking",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("检查设计");

    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toMatchObject({
      thinking_mode: "enabled",
    });
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).not.toHaveProperty("reasoning_effort");
  });

  it("sends same-provider preset model selections", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:model-preset",
      title: "Model Preset",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const providerConfig = {
      provider: "deepseek",
      model: "deepseek-v4-pro",
      base_url: "https://api.deepseek.com",
      credential_ref: "provider:deepseek:primary",
      api_key_configured: true,
      fallback_provider: "",
      fallback_model: "",
      fallback_base_url: "",
      fallback_credential_ref: "",
      fallback_api_key_configured: false,
      supported_providers: {
        deepseek: {
          provider: "deepseek",
          default_model: "deepseek-v4-pro",
          default_base_url: "https://api.deepseek.com",
          credential_ref: "provider:deepseek:primary",
          capability_tags: ["reasoning", "openai_compatible"],
          model_presets: ["deepseek-v4-pro", "deepseek-v4-flash"],
        },
      },
      provider_catalog: {
        authority: "runtime.model_provider_catalog",
        default_provider: "deepseek",
        default_model: "deepseek-v4-pro",
        providers: {
          deepseek: {
            provider: "deepseek",
            default_model: "deepseek-v4-pro",
            default_base_url: "https://api.deepseek.com",
            credential_ref: "provider:deepseek:primary",
            capability_tags: ["reasoning", "openai_compatible"],
            model_presets: ["deepseek-v4-pro", "deepseek-v4-flash"],
          },
        },
        credential_refs: [],
      },
      authority: "runtime.model_provider",
    };
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:model-preset",
      modelProviderConfig: providerConfig,
      selectedChatModelId: "deepseek::deepseek-v4-flash",
      chatThinkingMode: "normal",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("用快速模型回答");

    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toEqual({
      selection_id: "deepseek::deepseek-v4-flash",
      provider: "deepseek",
      model: "deepseek-v4-flash",
      base_url: "https://api.deepseek.com",
      credential_ref: "provider:deepseek:primary",
      thinking_mode: "disabled",
      stream_policy: {
        enabled: true,
        mode: "model_text_stream",
        emit_assistant_text_delta: true,
        upstream_reconnect_enabled: true,
        partial_stream_recovery: "continue_from_visible_prefix",
        chunk_strategy: "adaptive_buffer",
        first_flush_delay_ms: 70,
        target_buffer_delay_ms: 150,
        adaptive_min_buffer_delay_ms: 80,
        adaptive_max_buffer_delay_ms: 240,
        release_tick_ms: 16,
        max_buffer_delay_ms: 320,
        max_pending_utf8_bytes: 1536,
        max_release_utf8_bytes: 192,
        max_pending_line_count: 1,
        min_event_interval_ms: 16,
        event_budget_per_second: 45,
        source: "frontend.chat_stream_display_toggle",
      },
    });
  });

  it("sends disabled thinking when chat thinking mode is normal", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:thinking-normal",
      title: "Thinking Normal",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:thinking-normal",
      modelProviderConfig: {
        provider: "deepseek",
        model: "deepseek-v4-flash",
        base_url: "https://api.deepseek.com",
        credential_ref: "provider:deepseek:primary",
        api_key_configured: true,
        fallback_provider: "",
        fallback_model: "",
        fallback_base_url: "",
        fallback_credential_ref: "",
        fallback_api_key_configured: false,
        supported_providers: {
          deepseek: {
            provider: "deepseek",
            default_model: "deepseek-v4-flash",
            default_base_url: "https://api.deepseek.com",
            credential_ref: "provider:deepseek:primary",
            capability_tags: ["reasoning", "openai_compatible"],
          },
        },
        provider_catalog: {
          authority: "runtime.model_provider_catalog",
          default_provider: "deepseek",
          default_model: "deepseek-v4-flash",
          providers: {
            deepseek: {
              provider: "deepseek",
              default_model: "deepseek-v4-flash",
              default_base_url: "https://api.deepseek.com",
              credential_ref: "provider:deepseek:primary",
              capability_tags: ["reasoning", "openai_compatible"],
            },
          },
          credential_refs: [],
        },
        authority: "runtime.model_provider",
      },
      chatThinkingMode: "normal",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("普通回答");

    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toMatchObject({
      thinking_mode: "disabled",
    });
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).not.toHaveProperty("reasoning_effort");
  });

  it("keeps public projection text deltas enabled when stream display is turned off", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:no-stream-display",
      title: "No Stream Display",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:no-stream-display",
      chatStreamDisplayEnabled: false,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("等最终结果再显示");

    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toEqual({
      stream_policy: {
        enabled: true,
        mode: "public_projection_stream",
        emit_assistant_text_delta: true,
        upstream_reconnect_enabled: true,
        partial_stream_recovery: "continue_from_visible_prefix",
        chunk_strategy: "adaptive_buffer",
        first_flush_delay_ms: 70,
        target_buffer_delay_ms: 150,
        adaptive_min_buffer_delay_ms: 80,
        adaptive_max_buffer_delay_ms: 240,
        release_tick_ms: 16,
        max_buffer_delay_ms: 320,
        max_pending_utf8_bytes: 1536,
        max_release_utf8_bytes: 192,
        max_pending_line_count: 1,
        min_event_interval_ms: 16,
        event_budget_per_second: 45,
        source: "frontend.chat_stream_display_toggle",
      },
    });
  });

  it("routes image turns without starting TaskGraph session monitor polling", async () => {
    vi.useRealTimers();
    api.listSessions.mockResolvedValue([{
      id: "session:image",
      title: "Image",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", {
        content: "已生成图像。",
        image: {
          src: "/api/image-assets/files/chat-turn.png",
          alt: "睡着的小猫",
          caption: "revised prompt",
        },
      });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:image",
      selectedChatModelId: "openai::gpt-image-2",
      selectedChatMode: "image",
      taskGraphLiveMonitor: { status: "running", has_graph_run: true } as never,
      taskGraphBoundRunMonitor: { runtime: { status: "running" } } as never,
      imageAssetConfig: {
        configured: true,
        base_url: "https://api.openai.com/v1",
        model: "gpt-image-2",
        api_key_present: true,
        asset_dir: "D:/AI应用/langchain-agent/storage/generated/images",
        asset_route_prefix: "/api/image-assets/files",
        asset_store_relative_dir: "storage/generated/images",
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("为我生成一张睡着的小猫图片");

    expect(api.getOrchestrationHarnessSessionLiveMonitor).not.toHaveBeenCalled();
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      message: "为我生成一张睡着的小猫图片",
      session_id: "session:image",
      image_generation: {
        mode: "generate",
        selection_id: "openai::gpt-image-2",
        provider: "openai",
        selected_model: "gpt-image-2",
        model: "gpt-image-2",
        asset_kind: "chat",
        size: "1024x1024",
        overwrite: true,
      },
    });
    expect(api.streamChat.mock.calls[0]?.[0]?.image_generation?.target_id).toEqual(
      expect.stringMatching(/^turn-session:image-\d+$/)
    );
    expect(store.getState().taskGraphLiveMonitor).toBeNull();
    expect(store.getState().taskGraphBoundRunMonitor).not.toBeNull();
    expect(store.getState().messages.at(-1)?.image?.src).toBe("/api/image-assets/files/chat-turn.png");
  });

  it("does not synthesize image transport errors as assistant projection", async () => {
    vi.useRealTimers();
    api.getSessionHistory.mockResolvedValue({
      messages: [
        {
          role: "user",
          content: "为我生成一张美少女的图片，要求她是双鱼座女生",
        },
      ],
    });
    api.streamChat.mockImplementation(async () => {
      throw new Error("Image API failed with status 400");
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:image-error",
      selectedChatModelId: "openai::gpt-image-2",
      selectedChatMode: "image",
      imageAssetConfig: {
        configured: true,
        base_url: "https://api.openai.com/v1",
        model: "gpt-image-2",
        api_key_present: true,
        asset_dir: "D:/AI应用/langchain-agent/storage/generated/images",
        asset_route_prefix: "/api/image-assets/files",
        asset_store_relative_dir: "storage/generated/images",
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("为我生成一张美少女的图片，要求她是双鱼座女生");

    const lastMessage = store.getState().messages.at(-1);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.getSessionHistory).not.toHaveBeenCalled();
    expect(lastMessage?.role).toBe("assistant");
    expect(lastMessage?.content).toBe("");
    expect(lastMessage?.projectionView).toBeUndefined();
    expect(lastMessage?.runtimeProgress ?? []).toEqual([]);
    expect(store.getState().sessionActivity.level).toBe("idle");
  });

  it("uses the conversation active environment for ordinary main-chat turns", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:order",
      taskSelection: {
        selected_task_id: "task.dev.frontend_ui",
        label: "前端 UI 优化",
        mode: "single_task",
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("你好");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).not.toHaveProperty("task_selection");
    expect(api.streamChat.mock.calls[0]?.[0]?.environment_binding).toMatchObject({
      task_environment_id: "env.general.workspace",
      environment_id: "env.general.workspace",
      environment_label: "env.general.workspace",
      binding_kind: "conversation_active_task_environment",
    });
  });

  it("sends the selected active task environment to main-chat turns", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:env-bound",
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.setActiveTaskEnvironment("env.coding.vibe_workspace", { source: "task-system" });
    await runtime.actions.sendMessage("检查当前环境。");

    expect(api.setSessionActiveTaskEnvironment).toHaveBeenCalledWith(
      "session:env-bound",
      {
        task_environment_id: "env.coding.vibe_workspace",
        environment_label: "Vibe 编码工作区",
        source: "task-system",
      },
      undefined,
    );
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).not.toHaveProperty("task_selection");
    expect(api.streamChat.mock.calls[0]?.[0]?.environment_binding).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      binding_kind: "conversation_active_task_environment",
      binding_source: "task-system",
    });
  });

  it("remembers the last selected task environment for later default selection", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:env-bound",
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.setActiveTaskEnvironment("env.coding.vibe_workspace", { source: "workspace-mode" });

    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      "agentWorkbench.lastActiveTaskEnvironment",
      "env.coding.vibe_workspace",
    );
  });

  it("restores the last selected task environment instead of defaulting to general", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveTaskEnvironment" ? "env.coding.vibe_workspace" : null
    );
    const store = createStore<StoreState>(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.refreshTaskEnvironmentCatalog();

    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      source: "workspace-mode",
    });
  });

  it("restores the active task environment from session conversation state", async () => {
    vi.useRealTimers();
    api.getSessionHistory.mockResolvedValue({
      messages: [],
      conversation_state: conversationState("env.coding.vibe_workspace", "Vibe Coding Workspace", "conversation"),
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
      sessions: [{
        id: "session:restore-env",
        title: "Restore",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: conversationState("env.coding.vibe_workspace", "Vibe Coding Workspace", "conversation"),
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectSession({ sessionId: "session:restore-env", poolKey: "main-chat" });

    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
    });
  });

  it("uses the remembered task environment over an implicit general session default", async () => {
    vi.useRealTimers();
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === "agentWorkbench.lastActiveTaskEnvironment" ? "env.coding.vibe_workspace" : null
    );
    api.getSessionHistory.mockResolvedValue({
      messages: [],
      conversation_state: conversationState("env.general.workspace", "通用工作区", "conversation"),
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
      sessions: [{
        id: "session:general-default",
        title: "General",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
        conversation_state: conversationState("env.general.workspace", "通用工作区", "conversation"),
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectSession({ sessionId: "session:general-default", poolKey: "main-chat" });

    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      source: "workspace-mode",
    });
  });

  it("keeps the visible chat session when binding a different task environment", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:env-a",
      activeSessionScope: {
        workspace_view: "chat",
      },
      chatTaskEnvironmentBinding: {
        task_environment_id: "env.a",
        environment_label: "Env A",
        source: "task-system",
        bound_at: 1,
      },
      sessions: [{
        id: "session:env-a",
        title: "Env A",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
        scope: {
          workspace_view: "chat",
        },
      }],
      messages: [
        { id: "old-user", role: "user", content: "A 环境问题", toolCalls: [], retrievals: [] },
        { id: "old-assistant", role: "assistant", content: "A 环境回答", toolCalls: [], retrievals: [] },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.setChatTaskEnvironmentBinding({
      task_environment_id: "env.b",
      environment_label: "Env B",
      source: "task-system",
      bound_at: 2,
    });

    expect(store.getState().currentSessionId).toBe("session:env-a");
    expect(store.getState().messages.map((message) => message.content)).toEqual(["A 环境问题", "A 环境回答"]);
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.b",
      environment_label: "Env B",
      source: "task-system",
    });
    expect(store.getState().chatTaskEnvironmentBinding).toBeNull();
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
  });

  it("does not bind removed task environments to the ordinary main chat", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "chat",
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
      conversationActiveEnvironment: {
        task_environment_id: "env.general.workspace",
        environment_label: "通用工作区",
        source: "workspace-mode",
        updated_at: 1,
      },
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.setChatTaskEnvironmentBinding({
      task_environment_id: "env.removed.legacy",
      environment_label: "已删除环境",
      source: "task-system",
      bound_at: 2,
    });
    await flushPromises();

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().chatTaskEnvironmentBinding).toBeNull();
    expect(store.getState().conversationActiveEnvironment?.task_environment_id).toBe("env.general.workspace");
  });

  it("keeps the visible chat session when selecting a coding task environment", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "chat",
      currentSessionId: "session:general",
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
      activeSessionScope: {
        workspace_view: "chat",
      },
      sessions: [{
        id: "session:general",
        title: "General",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
        scope: {
          workspace_view: "chat",
        },
      }],
      messages: [
        { id: "general-user", role: "user", content: "通用环境问题", toolCalls: [], retrievals: [] },
        { id: "general-assistant", role: "assistant", content: "通用环境回答", toolCalls: [], retrievals: [] },
      ],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.setActiveTaskEnvironment("env.coding.vibe_workspace", { source: "workspace-mode" });
    await flushPromises();

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().currentSessionId).toBe("session:general");
    expect(store.getState().messages.map((message) => message.content)).toEqual(["通用环境问题", "通用环境回答"]);
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      source: "workspace-mode",
    });
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.getSessionRuntimeProjection).not.toHaveBeenCalled();
  });

  it("does not reset a selected coding environment when opening the workbench shell", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      activeWorkspaceView: "orchestration",
      currentSessionId: "session:coding",
      taskEnvironmentCatalog: TASK_ENVIRONMENT_CATALOG,
      conversationActiveEnvironment: {
        task_environment_id: "env.coding.vibe_workspace",
        environment_label: "Vibe 编码工作区",
        source: "workspace-mode",
        updated_at: 1,
      },
      activeSessionScope: {
        workspace_view: "chat",
      },
      sessions: [{
        id: "session:coding",
        title: "Coding",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
        scope: {
          workspace_view: "chat",
        },
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.setWorkspaceView("chat");
    await flushPromises();

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      source: "workspace-mode",
    });
    expect(api.setSessionActiveTaskEnvironment).not.toHaveBeenCalled();
  });

  it("returns to the general task environment after clearing an explicit binding", async () => {
    vi.useRealTimers();
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:env-clear",
      chatTaskEnvironmentBinding: {
        task_environment_id: "env.coding.vibe_workspace",
        environment_label: "Vibe 编码工作区",
        source: "task-system",
        bound_at: 123,
      },
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.clearChatTaskEnvironmentBinding();
    await runtime.actions.sendMessage("普通聊天。");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).not.toHaveProperty("task_selection");
    expect(api.streamChat.mock.calls[0]?.[0]?.environment_binding).toMatchObject({
      task_environment_id: "env.general.workspace",
      environment_id: "env.general.workspace",
      binding_kind: "conversation_active_task_environment",
    });
  });

  it("keeps task selection after chat stream start events", async () => {
    vi.useRealTimers();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("harness_run_started", {
        turn_run: {
          turn_run_id: "turnrun:abc",
          execution_runtime_kind: "single_agent_turn",
          status: "running",
        },
        agent_run: { agent_run_id: "agentrun:abc" },
      });
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "turn_completed", terminalStatus: "completed" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:order",
      taskSelection: {
        selected_task_id: "task.dev.frontend_ui",
        label: "前端 UI 优化",
        mode: "single_task",
      },
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始执行。");
    await runtime.actions.sendMessage("普通后续聊天。");

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[0]?.[0]).not.toHaveProperty("task_selection");
    expect(api.streamChat.mock.calls[0]?.[0]?.environment_binding).toMatchObject({
      task_environment_id: "env.general.workspace",
      binding_kind: "conversation_active_task_environment",
    });
    expect(api.streamChat.mock.calls[1]?.[0]).not.toHaveProperty("task_selection");
    expect(api.streamChat.mock.calls[1]?.[0]?.environment_binding).toMatchObject({
      task_environment_id: "env.general.workspace",
      binding_kind: "conversation_active_task_environment",
    });
    expect(store.getState().taskSelection).toMatchObject({
      selected_task_id: "task.dev.frontend_ui",
    });
    const assistant = store.getState().messages.at(-1);
    expect(assistant?.projectionView).toBeUndefined();
  });

  it("ignores raw formal task lifecycle signals without a public projection envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "开始正式任务");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_run_started", {
      task_run: {
        task_run_id: "taskrun:abc",
        status: "running",
      },
      event: {
        event_id: "rtevt:start",
        run_id: "taskrun:abc",
        created_at: 1,
        payload: {
          contract: {
            user_visible_goal: "实现主会话监控",
          },
        },
      },
    });
    transition = reduceStreamEvent(transition.state, transition.session, "task_run_lifecycle_event", {
      event: {
        event_id: "rtevt:todo",
        run_id: "taskrun:abc",
        event_type: "agent_todo_initialized",
        created_at: 2,
        payload: {
          task_run: {
            task_run_id: "taskrun:abc",
            status: "running",
          },
          observation: {
            summary: "待办已建立",
            source: "agent_todo",
          },
        },
      },
    });
    transition = reduceStreamEvent(transition.state, transition.session, "agent_turn_terminal", {
      event: {
        event_id: "rtevt:terminal",
        run_id: "turnrun:abc",
        created_at: 3,
        payload: {
          status: "task_executor_scheduled",
          terminal_reason: "task_executor_scheduled",
          task_run: {
            task_run_id: "taskrun:abc",
            status: "running",
          },
        },
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.projectionView).toBeUndefined();
    expect(assistant?.stageStatus).toBe("");
  });

  it("ignores raw tool runtime requests without reviving legacy tool results", () => {
    let transition = startStreamingTurn(getDefaultState(), "执行前端任务");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_loop_event", {
      event: {
        event_id: "rtevt:tool-request",
        run_id: "taskrun:abc",
        event_type: "tool_call_requested",
        created_at: 2,
        payload: {
          action_request: {
            request_id: "rtact:abc",
            operation_id: "operation.write_file",
            payload: {
              tool_name: "write_file",
              tool_call: { name: "write_file", args: { path: "docs/plan.md" } },
            },
          },
        },
      },
    });
    transition = reduceStreamEvent(transition.state, transition.session, "harness_loop_event", {
      event: {
        event_id: "rtevt:tool-result",
        run_id: "taskrun:abc",
        event_type: "tool_result_received",
        created_at: 3,
        payload: {
          observation: {
            observation_id: "rtobs:abc",
            source: "tool:write_file",
            payload: {
              tool_name: "write_file",
              result: "wrote docs/plan.md",
              observed_paths: ["docs/plan.md"],
            },
          },
        },
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.projectionView).toBeUndefined();
  });

  it("ignores raw single-agent turn tool events without a public projection envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "写一个文件");
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      event: {
        event_id: "rtevt:turn-tool-request",
        run_id: "turnrun:turn:session:77",
        event_type: "model_action_admission_checked",
        created_at: 2,
        payload: {
          model_action_request: {
            action_type: "tool_call",
            public_progress_note: "已发起工具调用，正在等待工具返回：write_file。",
            tool_call: {
              name: "write_file",
              args: { path: "docs/turn.md" },
            },
          },
          admission: {
            decision: "allow",
          },
        },
      },
    });

    expect(transition.state.sessionActivity).toMatchObject({
      level: "idle",
      title: "",
      detail: "",
    });

    transition = reduceStreamEvent(transition.state, transition.session, "turn_tool_observation_recorded", {
      event: {
        event_id: "rtevt:turn-tool-result",
        run_id: "turnrun:turn:session:77",
        event_type: "turn_tool_observation_recorded",
        created_at: 3,
        payload: {
          preview: {
            tool_observation: {
              observation_id: "toolobs:turn",
              caller_ref: "turnrun:turn:session:77",
              tool_name: "write_file",
              status: "ok",
              text: "Write succeeded: docs/turn.md",
              result_envelope: {
                tool_args: { path: "docs/turn.md" },
              },
              structured_payload: {
                artifact_refs: [{ path: "docs/turn.md", kind: "file" }],
              },
            },
          },
        },
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(transition.state.sessionActivity).toMatchObject({
      level: "idle",
      title: "",
    });
    expect(assistant?.projectionView).toBeUndefined();
  });

  it("does not attach permission gate checks to the assistant task flow", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_loop_event", {
      event: {
        event_id: "rtevt:gate",
        run_id: "taskrun:abc",
        event_type: "operation_gate_checked",
        created_at: 2,
        payload: {
          gate: {
            allowed: true,
            decision: "allow",
            operation_id: "op.model_response",
            reason: "operation allowed by adopted resource policy",
          },
        },
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.stageStatus).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
  });

  it("writes terminal error detail into timeline status without changing assistant prose", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "error", {
      error: "当前环境的写入权限不足，且创建文件的工具不可见。",
      code: "agent_blocked",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
    expect(assistant?.runtimeProgress ?? []).toEqual([]);
    expect(transition.state.sessionActivity).toMatchObject({
      level: "idle",
      title: "",
      detail: "",
    });
  });

  it("does not expose internal runtime loop bookkeeping as chat progress", () => {
    let transition = startStreamingTurn(getDefaultState(), "你好");
    for (const step of [
      "turn_started",
      "runtime_packet_compiled",
      "model_action_received",
      "action_admission_checked",
      "bounded_observation_recorded",
    ]) {
      transition = reduceStreamEvent(transition.state, transition.session, "runtime_step_summary", {
        step,
        status: "running",
        summary: `internal ${step}`,
      });
    }

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.stageStatus).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
  });

  it("keeps raw tool lifecycle events out of the assistant main projection", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续执行");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_run_started", {
      turn_run: {
        turn_id: "turn:runtime:tool-write:1",
        turn_run_id: "turnrun:turn:runtime:tool-write:1",
      },
    });
    transition = reduceStreamEvent(transition.state, transition.session, "tool_item_started", {
      item_id: "call:write",
      tool_call_id: "call:write",
      turn_run_id: "turnrun:turn:runtime:tool-write:1",
      tool_name: "write_file",
      title: "正在更新文件",
      target: "docs/plan.md",
      arguments_preview: "path=docs/plan.md",
      status: "running",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "tool_item_completed", {
      item_id: "call:write",
      tool_call_id: "call:write",
      turn_run_id: "turnrun:turn:runtime:tool-write:1",
      tool_name: "write_file",
      state: "done",
      observation: "文件已更新",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.projectionView).toBeUndefined();
    expect(assistant?.stageStatus).toBe("");
    expect(transition.state.sessionActivity.event).toBe("");
  });

  it("does not block send completion on post-stream session refresh", async () => {
    vi.useRealTimers();
    api.listSessions.mockImplementation(() => new Promise(() => undefined));
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("error", {
        error: "backend failed",
        terminal_reason: "backend_error",
      });
      return { terminalEvent: "turn_completed", terminalStatus: "failed" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:timeout",
      sessions: [{
        id: "session:timeout",
        title: "Timeout",
        created_at: 1,
        updated_at: 1,
        message_count: 1,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await expect(runtime.actions.sendMessage("你好")).resolves.toBeUndefined();

    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().isStreaming).toBe(false);
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      event: "",
    });
  });
});
