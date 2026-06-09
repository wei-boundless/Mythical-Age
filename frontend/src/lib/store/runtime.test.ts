import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStore, getDefaultState } from "./core";
import { reduceStreamEvent, startQueuedActiveTurn, startStreamingTurn } from "./events";
import { WorkspaceRuntime } from "./runtime";
import type { StoreState } from "./types";

const api = vi.hoisted(() => ({
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  getCodeEnvironmentWorkspaceTree: vi.fn(),
  getProjectWorkspaceTree: vi.fn(),
  getChatRun: vi.fn(),
  getLatestChatRunForSession: vi.fn(),
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
  clearChatStreamCursor: vi.fn(),
  getPermissionMode: vi.fn(),
  readChatStreamCursor: vi.fn(),
  resumeOrchestrationHarnessTaskRun: vi.fn(),
  submitGraphRunUntilIdle: vi.fn(),
  setSessionActiveTaskEnvironment: vi.fn(),
  setSessionPermissionMode: vi.fn(),
  setPermissionMode: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessionSummary: vi.fn(),
  getSessionTimeline: vi.fn(),
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
  listSkills: vi.fn(),
  loadFile: vi.fn(),
  loadFileForSession: vi.fn(),
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
  submitGraphRunUntilIdle: api.submitGraphRunUntilIdle,
  evaluateTaskGraphRunMonitor: vi.fn(),
  getCodeEnvironmentWorkspaceTree: api.getCodeEnvironmentWorkspaceTree,
  getProjectWorkspaceTree: api.getProjectWorkspaceTree,
  getChatRun: api.getChatRun,
  getLatestChatRunForSession: api.getLatestChatRunForSession,
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
  clearChatStreamCursor: api.clearChatStreamCursor,
  getPermissionMode: api.getPermissionMode,
  readChatStreamCursor: api.readChatStreamCursor,
  resumeOrchestrationHarnessTaskRun: api.resumeOrchestrationHarnessTaskRun,
  setSessionActiveTaskEnvironment: api.setSessionActiveTaskEnvironment,
  setSessionPermissionMode: api.setSessionPermissionMode,
  setPermissionMode: api.setPermissionMode,
  getSessionHistory: api.getSessionHistory,
  getSessionSummary: api.getSessionSummary,
  getSessionTimeline: api.getSessionTimeline,
  getSessionTokens: api.getSessionTokens,
  getWorkbenchCurrentSession: api.getWorkbenchCurrentSession,
  setWorkbenchCurrentSession: api.setWorkbenchCurrentSession,
  clearWorkbenchCurrentSession: api.clearWorkbenchCurrentSession,
  listSessions: api.listSessions,
  listProjectWorkspaces: api.listProjectWorkspaces,
  listProjectWorkspaceSessions: api.listProjectWorkspaceSessions,
  listSkills: api.listSkills,
  loadFile: api.loadFile,
  loadFileForSession: api.loadFileForSession,
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
    line: text(item.latest_public_progress_note) || text(item.latest_step_summary) || text(item.summary) || "正在处理当前请求。",
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
    tone: text(item.tone) || (isRunning ? "active" : activityState === "completed" ? "done" : activityState === "failed" ? "attention" : "neutral"),
    activity: {
      activity_state: activityState,
      activity_label: text(item.activity_label) || activityLabelForTest(activityState),
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

function emitRuntimeControlSteerDone(
  handlers: { onEvent: (event: string, data: Record<string, unknown>) => void },
  {
    taskRunId,
    activeTurnId,
    detail = "补充要求已进入当前工作队列。",
    completionState = "task_steer_accepted",
  }: {
    taskRunId: string;
    activeTurnId: string;
    detail?: string;
    completionState?: string;
  },
) {
  handlers.onEvent("runtime_status", {
    title: "已收到补充要求",
    detail,
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

describe("WorkspaceRuntime task graph monitor polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
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
    api.getCodeEnvironmentWorkspaceTree.mockReset();
    api.getCodeEnvironmentWorkspaceTree.mockResolvedValue({
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
    api.getLatestChatRunForSession.mockReset();
    api.getLatestChatRunForSession.mockRejectedValue(new Error("no active chat run"));
    api.pauseOrchestrationHarnessTaskRun.mockReset();
    api.pauseOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.approveOrchestrationHarnessTaskRunToolCall.mockReset();
    api.approveOrchestrationHarnessTaskRunToolCall.mockResolvedValue({ ok: true });
    api.clearChatStreamCursor.mockReset();
    api.resumeOrchestrationHarnessTaskRun.mockReset();
    api.resumeOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.submitGraphRunUntilIdle.mockReset();
    api.submitGraphRunUntilIdle.mockResolvedValue({ accepted: true, background_started: true });
    api.stopOrchestrationHarnessTaskRun.mockReset();
    api.stopOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.getSessionHistory.mockReset();
    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionSummary.mockReset();
    api.getSessionSummary.mockRejectedValue(new Error("no remembered session"));
    api.getSessionTimeline.mockReset();
    api.getSessionTimeline.mockResolvedValue({ messages: [], runtime_attachments: [] });
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
    api.listSkills.mockReset();
    api.listSkills.mockResolvedValue([]);
    api.loadFile.mockReset();
    api.loadFile.mockResolvedValue({ path: "durable_memory/index/MEMORY.md", content: "" });
    api.loadFileForSession.mockReset();
    api.loadFileForSession.mockResolvedValue({ path: "durable_memory/index/MEMORY.md", content: "" });
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
      permission_mode: String(mode || "full_access"),
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
      return { terminalEvent: "done", streamRunId: "strun:test", eventLogId: "chatrun:test", lastEventOffset: 1 };
    });
    api.streamChat.mockReset();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "done", streamRunId: "strun:test", eventLogId: "chatrun:test", lastEventOffset: 1 };
    });
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
      activeWorkspaceView: "code-environment",
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.openWorkspaceFile(" AGENTS.md ");

    expect(store.getState().activeWorkspaceView).toBe("code-environment");
    expect(store.getState().centerWorkspaceTarget).toMatchObject({
      layer: "file",
      file_path: "AGENTS.md",
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
    api.getSessionTimeline.mockImplementation(async (sessionId) => ({
      id: String(sessionId),
      title: "Session",
      created_at: 1,
      updated_at: 1,
      compressed_context: "",
      conversation_state: String(sessionId) === "session:full"
        ? { authority: "sessions.conversation_state", permission_mode: "full_access" }
        : { authority: "sessions.conversation_state", permission_mode: "default" },
      messages: [],
      runtime_attachments: [],
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
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      session_id: "session:plan",
      permission_mode: "plan",
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
      visible_files: [{
        path: "frontend/src/App.tsx",
        language_id: "typescriptreact",
        dirty: true,
      }],
    });
    expect((api.streamChat.mock.calls[0]?.[0]?.editor_context as Record<string, any>)?.active_file?.selection).toBeUndefined();
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
      activeWorkspaceView: "code-environment",
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

  it("pauses a bound GraphRun through its owning root TaskRun", async () => {
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

    expect(api.pauseOrchestrationHarnessTaskRun).toHaveBeenCalledWith("taskrun:graph-master", "user_pause_graph_run", "");
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

    expect(api.resumeOrchestrationHarnessTaskRun).not.toHaveBeenCalled();
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

  it("resumes the root TaskRun before continuing a paused GraphRun", async () => {
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

    expect(api.resumeOrchestrationHarnessTaskRun).toHaveBeenCalledWith("taskrun:graph-master", 12, "");
    expect(api.submitGraphRunUntilIdle).toHaveBeenCalledWith("grun:graph-master", {
      graph_harness_config_id: "ghcfg:graph-master",
      session_scope: undefined,
      max_node_executions: 1,
      max_loop_iterations: 4,
      max_dispatches: 1,
      max_dispatch_requests: 1,
    });
    expect(api.resumeOrchestrationHarnessTaskRun.mock.invocationCallOrder[0]).toBeLessThan(
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
    api.getSessionTimeline.mockResolvedValue({
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

    expect(store.getState().activeWorkspaceView).toBe("code-environment");
    expect(store.getState().currentSessionId).toBe("session-dev");
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      source: "workspace-mode",
    });
    expect(store.getState().chatTaskEnvironmentBinding).toBeNull();
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.getSessionTimeline).toHaveBeenCalledWith("session-dev", {
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

  it("starts the run monitor with an SSE stream and waits for the stream snapshot", async () => {
    const instances: Array<{ close: ReturnType<typeof vi.fn> }> = [];
    class MockEventSource {
      close = vi.fn();

      constructor(_url: string) {
        instances.push(this);
      }

      addEventListener() {}
    }
    vi.stubGlobal("EventSource", MockEventSource);
    api.getRunMonitor.mockResolvedValue(monitorForTest([]));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    await vi.advanceTimersByTimeAsync(0);

    expect(instances).toHaveLength(1);
    expect(api.getRunMonitor).not.toHaveBeenCalled();
    expect(store.getState().runMonitorStreamStatus).toBe("connecting");
  });

  it("polls the run monitor only when SSE is unavailable", async () => {
    vi.stubGlobal("EventSource", undefined);
    api.getRunMonitor.mockResolvedValue(monitorForTest([]));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getRunMonitor).toHaveBeenCalledTimes(1);
    expect(store.getState().runMonitorStreamStatus).toBe("fallback");

    await vi.advanceTimersByTimeAsync(2500);
    expect(api.getRunMonitor).toHaveBeenCalledTimes(2);
  });

  it("projects background TaskRun step summaries from the monitor event stream into chat", () => {
    const taskRunId = "taskrun:turn:session:stream:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stream",
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
    runtime.applyRunMonitorStreamPayload({
      source: "runtime_event_log",
      runtime_event: {
        event_id: "rtevt:step:2",
        run_id: taskRunId,
        event_type: "step_summary_recorded",
        offset: 2,
        created_at: 11,
        payload: {
          task_run_id: taskRunId,
          step: "task_model_action_invocation_started:1",
          status: "running",
          summary: "任务 runtime packet 已送入模型，系统正在等待 agent 返回任务动作。",
          public_progress_note: "我已经把任务上下文交给 agent，正在等待下一步动作。",
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:stream:1" },
        authority: "orchestration.runtime_event",
      },
    });

    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment?.run_id).toBe(taskRunId);
    expect(attachment?.anchor_turn_id).toBe("turn:session:stream:1");
    expect(attachment?.progress_entries?.map((item) => item.id)).toEqual(["rtevt:step:1", "rtevt:step:2"]);
    expect(attachment?.progress_entries?.at(-1)).toMatchObject({
      body: "我已经把任务上下文交给 agent，正在等待下一步动作。",
      eventType: "step_summary_recorded",
      taskRunId,
    });
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
    expect(store.getState().messages[1]?.runtimeAttachments ?? []).toEqual([]);
  });

  it("projects live tool observation summaries as observation rows", () => {
    const taskRunId = "taskrun:turn:session:observation:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:observation",
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
          public_timeline_delta: [
            {
              item_id: "observation:image-timeout",
              kind: "observation_report",
              detail: "结果返回失败：Image API request timed out",
              state: "error",
            },
          ],
        },
        refs: { task_run_ref: taskRunId, turn_ref: "turn:session:observation:1" },
        authority: "orchestration.runtime_event",
      },
    });

    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment?.progress_entries?.[0]).toMatchObject({
      id: "rtevt:observation",
      kind: "observation",
      level: "error",
      title: "结果已返回",
      body: "工具返回失败：Image API request timed out",
      publicNote: "工具调用已完成，正在根据结果继续。",
      agentBrief: "工具返回失败：Image API request timed out",
      eventType: "step_summary_recorded",
      taskRunId,
    });
    expect(attachment?.public_timeline?.[0]).toMatchObject({
      item_id: "observation:image-timeout",
      kind: "observation_report",
      detail: "结果返回失败：Image API request timed out",
      state: "error",
    });
  });

  it("projects public timeline deltas from monitor events without requiring a progress entry", () => {
    const taskRunId = "taskrun:turn:session:public-delta:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:public-delta",
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
        public_projection_authority: "runtime_monitor.public_event_projection.v1",
        public_event_type: "model_action_admission",
        public_anchor: {
          run_id: taskRunId,
          task_run_id: taskRunId,
          anchor_turn_id: "turn:session:public-delta:1",
          anchor_role: "assistant",
        },
        public_timeline_delta: [
          {
            item_id: "opening:public-delta",
            kind: "opening_judgment",
            title: "开局判断",
            text: "我正在公开说明当前判断。",
            state: "running",
          },
        ],
      },
    });

    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment).toMatchObject({
      run_id: taskRunId,
      anchor_turn_id: "turn:session:public-delta:1",
      summary: "我正在公开说明当前判断。",
      progress_entries: [],
    });
    expect(attachment?.public_timeline).toEqual([
      expect.objectContaining({
        item_id: "opening:public-delta",
        kind: "opening_judgment",
        text: "我正在公开说明当前判断。",
      }),
    ]);
  });

  it("keeps live monitor public timeline attachments after a stream snapshot hydrates the session", async () => {
    vi.useRealTimers();
    const taskRunId = "taskrun:turn:session:hydrate:1:abc";
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "开始长任务" },
        { role: "assistant", content: "任务已接管。" },
      ],
      runtime_attachments: [],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:hydrate",
      sessions: [{
        id: "session:hydrate",
        title: "Hydrate",
        created_at: 1,
        updated_at: 1,
        message_count: 2,
      }],
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
      runtime_event: {
        event_id: "rtevt:hydrate-public-delta",
        run_id: taskRunId,
        event_type: "model_action_request_received",
        offset: 1,
        created_at: 10,
        payload: {},
        refs: {},
        authority: "orchestration.runtime_event",
        public_anchor: {
          run_id: taskRunId,
          task_run_id: taskRunId,
          anchor_turn_id: "turn:session:hydrate:1",
          anchor_role: "assistant",
        },
        public_timeline_delta: [
          {
            item_id: "opening:hydrate",
            kind: "opening_judgment",
            title: "开局判断",
            text: "这条 live 公开反馈还没有持久化到 session timeline。",
            state: "running",
          },
        ],
      },
    });
    runtime.applyRunMonitorStreamPayload({
      source: "initial",
      monitor: monitorForTest([]),
    });
    await flushPromises(12);

    expect(api.getSessionTimeline).toHaveBeenCalledWith("session:hydrate", undefined);
    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment?.run_id).toBe(taskRunId);
    expect(attachment?.public_timeline?.[0]).toMatchObject({
      item_id: "opening:hydrate",
      text: "这条 live 公开反馈还没有持久化到 session timeline。",
    });
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

    expect(api.getSessionTimeline).not.toHaveBeenCalled();
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

    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment?.progress_entries ?? []).toEqual([]);
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
      return { terminalEvent: "done" };
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
    expect(store.getState().sessionActivity.title).toBe("正在处理");
    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session:background:1",
      task_run_id: "taskrun:background",
    });
    expect(store.getState().taskGraphLiveMonitor?.task_run_id).toBe("taskrun:background");
  });

  it("sends later main-chat input with the active task turn gate after task handoff", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", {
        content: "任务已进入后台执行。",
        answer_channel: "task_control",
        terminal_reason: "task_executor_scheduled",
        runtime_task_run_id: "taskrun:background",
        active_turn_id: "turn:session:background:1",
      });
      return { terminalEvent: "done" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:background",
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("开始后台任务");
    await runtime.actions.sendMessage("暂停一下");

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      expected_active_turn_id: "turn:session:background:1",
      active_turn_input_policy: "auto",
    });
    expect(store.getState().sessionActivity.event).not.toBe("done");
    expect(store.getState().sessionActivity.receipt?.debug?.event).not.toBe("done");
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

  it("submits active-task steer immediately while the main chat stream is still open", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("active_task_steer_accepted", {
        summary: "补充要求已进入当前工作队列。",
        status: "accepted",
        runtime_task_run_id: "taskrun:streaming",
        active_turn_id: "turn:session:streaming:1",
      });
      emitRuntimeControlSteerDone(handlers, {
        taskRunId: "taskrun:streaming",
        activeTurnId: "turn:session:streaming:1",
      });
      return { terminalEvent: "done", streamRunId: "strun:steer", eventLogId: "chatrun:steer", lastEventOffset: 2 };
    });
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

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      message: "补充：先检查边界。",
      session_id: "session:streaming",
      expected_active_turn_id: "turn:session:streaming:1",
      active_turn_input_policy: "steer",
    });
    expect(api.streamChat.mock.calls[0]?.[2]).toMatchObject({ persistCursor: false });
    expect(store.getState().activeStreamSessionIds).toEqual(["session:streaming"]);
    expect(store.getState().taskGraphLiveMonitor?.task_run_id).toBe("taskrun:streaming");
    expect(store.getState().messages.some((message) => message.content === "补充：先检查边界。")).toBe(true);
    expect(store.getState().sessionActivity.event).not.toBe("user_input_queued");
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
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
      title: "已加入发送队列",
    });
  });

  it("keeps the active task turn gate after a runtime control turn completes", async () => {
    let callIndex = 0;
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      callIndex += 1;
      if (callIndex === 1) {
        handlers.onEvent("done", {
          content: "任务已进入后台执行。",
          answer_channel: "task_control",
          terminal_reason: "task_executor_scheduled",
          runtime_task_run_id: "taskrun:background",
          active_turn_id: "turn:session:background:1",
        });
      } else {
        emitRuntimeControlSteerDone(handlers, {
          taskRunId: "taskrun:background",
          activeTurnId: "turn:session:background:1",
          detail: "已收到，会纳入当前处理。",
        });
      }
      return { terminalEvent: "done" };
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

    await runtime.actions.sendMessage("继续");

    expect(api.streamChat).toHaveBeenCalledTimes(3);
    expect(api.streamChat.mock.calls[2]?.[0]).toMatchObject({
      expected_active_turn_id: "turn:session:background:1",
      active_turn_input_policy: "auto",
    });
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
    expect(api.streamChat).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_active_turn_id: "turn:session-monitor-recover:1",
        active_turn_input_policy: "auto",
      }),
      expect.anything(),
      expect.anything(),
    );
  });

  it("sends running active task input as an auto active-work request with visible status feedback", async () => {
    const taskRunId = "taskrun:turn:session-queue-only:1:abc";
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("active_task_steer_accepted", {
        summary: "已加入当前任务队列，会在当前执行中优先纳入。",
        active_turn_id: "turn:session-queue-only:1",
        runtime_task_run_id: taskRunId,
        task_run: {
          task_run_id: taskRunId,
          status: "running",
          execution_runtime_kind: "single_agent_task",
        },
      });
      emitRuntimeControlSteerDone(handlers, {
        taskRunId,
        activeTurnId: "turn:session-queue-only:1",
        detail: "已加入当前任务队列，会在当前执行中优先纳入。",
      });
      return { terminalEvent: "done" };
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "开始任务" },
        { role: "assistant", content: "我会开始处理。" },
        { role: "user", content: "补充一个限制条件" },
      ],
      runtime_attachments: [],
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

    expect(api.streamChat).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_active_turn_id: "turn:session-queue-only:1",
        active_turn_input_policy: "auto",
      }),
      expect.anything(),
      expect.anything(),
    );
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
    expect(store.getState().messages.at(-1)).toMatchObject({
      role: "user",
      content: "补充一个限制条件",
    });
    expect(store.getState().sessionActivity).toMatchObject({
      level: "success",
      title: "已收到补充要求",
    });
    expect(store.getState().activeTurnSnapshot).toMatchObject({
      turn_id: "turn:session-queue-only:1",
      task_run_id: taskRunId,
    });
  });

  it("queues later input while an auto active-work turn stream is deciding", async () => {
    const taskRunId = "taskrun:turn:session-auto-active-stream:1:abc";
    let finishFirstStream: (() => void) | null = null;
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers) => {
        await new Promise<void>((resolve) => {
          finishFirstStream = () => {
            emitRuntimeControlSteerDone(handlers, {
              taskRunId,
              activeTurnId: "turn:session-auto-active-stream:1",
              detail: "已加入当前任务队列，会在当前执行中优先纳入。",
            });
            resolve();
          };
        });
        return { terminalEvent: "done" };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        emitRuntimeControlSteerDone(handlers, {
          taskRunId,
          activeTurnId: "turn:session-auto-active-stream:1",
          detail: "第二条补充已处理。",
        });
        return { terminalEvent: "done" };
      });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "开始任务" },
        { role: "assistant", content: "我会开始处理。" },
        { role: "user", content: "补充一" },
      ],
      runtime_attachments: [],
    });
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({
      active_task_run_id: taskRunId,
      active_turn_snapshot: {
        turn_id: "turn:session-auto-active-stream:1",
        bound_task_run_id: taskRunId,
        state: "running_task",
      },
      monitor: {
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
      },
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

    const firstSend = runtime.actions.sendMessage("补充一");
    await flushPromises();

    expect(store.getState().activeStreamSessionIds).toContain("session-auto-active-stream");
    await runtime.actions.sendMessage("补充二");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(store.getState().messages.map((message) => message.content)).toContain("补充二");
    expect(store.getState().sessionActivity).toMatchObject({
      event: "user_input_queued",
    });

    const finish = finishFirstStream as (() => void) | null;
    expect(finish).not.toBeNull();
    finish?.();
    await firstSend;
    await flushPromises(10);

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      message: "补充二",
      expected_active_turn_id: "turn:session-auto-active-stream:1",
      active_turn_input_policy: "auto",
    });
  });

  it("queues user input locally while the current stream is active and flushes it after handoff", async () => {
    const taskRunId = "taskrun:turn:session-stream-queue:1:abc";
    let finishFirstStream: (() => void) | null = null;
    api.streamChat
      .mockImplementationOnce(async (_payload, handlers) => {
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
        return { terminalEvent: "done" };
      })
      .mockImplementationOnce(async (_payload, handlers) => {
        emitRuntimeControlSteerDone(handlers, {
          taskRunId,
          activeTurnId: "turn:session-stream-queue:1",
          detail: "已加入当前任务队列，会在当前执行中优先纳入。",
        });
        return { terminalEvent: "done" };
      });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "开始任务" },
        { role: "assistant", content: "任务已进入后台执行。" },
        { role: "user", content: "补充一个限制条件" },
      ],
      runtime_attachments: [],
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
    expect(store.getState().sessionActivity).toMatchObject({
      title: "已加入发送队列",
    });

    const finish = finishFirstStream as (() => void) | null;
    expect(finish).not.toBeNull();
    finish?.();
    await firstSend;
    await flushPromises(10);

    expect(api.streamChat).toHaveBeenCalledTimes(2);
    expect(api.streamChat.mock.calls[1]?.[0]).toMatchObject({
      expected_active_turn_id: "turn:session-stream-queue:1",
      active_turn_input_policy: "auto",
    });
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
    expect(store.getState().sessionActivity).toMatchObject({
      level: "running",
      title: "正在处理",
    });
  });

  it("accumulates live TaskRun progress entries instead of replacing them with the latest step", async () => {
    const taskRunId = "taskrun:turn:session:live:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:live",
      activeTurnSnapshot: {
        turn_id: "turn:session:live:1",
        task_run_id: taskRunId,
      },
      messages: [
        {
          id: "user:1",
          role: "user",
          content: "开始任务",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0,
        },
        {
          id: "assistant:1",
          role: "assistant",
          content: "任务已接管",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 1,
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
    };
    api.getOrchestrationHarnessSessionLiveMonitor
      .mockResolvedValueOnce({
        active_task_run_id: taskRunId,
        monitor: {
          task_run_id: taskRunId,
          session_id: "session:live",
          status: "running",
          event_count: 1,
          latest_step: {
            event_id: "step:packet",
            step: "task_execution_packet_compiled:1",
            status: "running",
            created_at: 1,
          },
          latest_step_summary: "正在整理上下文，准备继续处理。",
          latest_event: { event_type: "step_summary_recorded" },
          updated_at: 1,
          task_run: {
            task_run_id: taskRunId,
            task_id: "task:turn:session:live:1",
            status: "running",
          },
        },
        task_runs: [],
      })
      .mockResolvedValueOnce({
        active_task_run_id: taskRunId,
        monitor: {
          task_run_id: taskRunId,
          session_id: "session:live",
          status: "running",
          event_count: 2,
          latest_step: {
            event_id: "step:model",
            step: "task_model_action_invocation_started:1",
            status: "running",
            created_at: 2,
          },
          latest_step_summary: "任务 runtime packet 已送入模型，系统正在等待 agent 返回任务动作。",
          latest_event: { event_type: "step_summary_recorded" },
          updated_at: 2,
          task_run: {
            task_run_id: taskRunId,
            task_id: "task:turn:session:live:1",
            status: "running",
          },
        },
        task_runs: [],
      });

    await runtime.hydrateLatestOrchestrationSnapshot("session:live");
    await runtime.hydrateLatestOrchestrationSnapshot("session:live");

    const attachment = store.getState().messages[1]?.runtimeAttachments?.[0];
    expect(attachment?.anchor_turn_id).toBe("turn:session:live:1");
    expect(attachment?.progress_entries?.map((item) => item.id)).toEqual(["step:packet", "step:model"]);
  });

  it("projects stale waiting monitor status into the assistant public timeline", async () => {
    const taskRunId = "taskrun:turn:session:waiting:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:waiting",
      activeTurnSnapshot: {
        turn_id: "turn:session:waiting:1",
        task_run_id: taskRunId,
      },
      messages: [
        {
          id: "user:1",
          role: "user",
          content: "开始任务",
          toolCalls: [],
          retrievals: [],
          sourceIndex: 0,
        },
        {
          id: "assistant:1",
          role: "assistant",
          content: "任务已接管",
          toolCalls: [],
          retrievals: [],
          runtimePublicTimelineDraft: [
            {
              item_id: "tool:image",
              kind: "work_action",
              action_kind: "image",
              public_summary: "正在生成图像",
              state: "running",
              stream_state: "streaming",
            },
          ],
          sourceIndex: 1,
        },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
    };
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValueOnce({
      active_task_run_id: taskRunId,
      monitor: {
        task_run_id: taskRunId,
        session_id: "session:waiting",
        status: "waiting_executor",
        terminal_reason: "waiting_executor",
        lifecycle: "stale",
        bucket: "diagnostics",
        stale: true,
        execution_runtime_kind: "single_agent_task",
        event_count: 11,
        latest_step: {
          event_id: "step:image",
          step: "task_tool_executed:11",
          status: "running",
          public_progress_note: "正在生成图像",
          created_at: 11,
        },
        latest_step_summary: "处理已超过2小时没有新的运行事件；当前处理已进入诊断状态。",
        latest_event: { event_type: "step_summary_recorded" },
        updated_at: 12,
        task_run: {
          task_run_id: taskRunId,
          task_id: "task:turn:session:waiting:1",
          status: "waiting_executor",
          execution_runtime_kind: "single_agent_task",
        },
      },
      task_runs: [],
    });

    await runtime.hydrateLatestOrchestrationSnapshot("session:waiting");

    const publicTimeline = store.getState().messages[1]?.runtimeAttachments?.[0]?.public_timeline ?? [];
    expect(publicTimeline).toEqual(expect.arrayContaining([
      expect.objectContaining({
        item_id: `live:${taskRunId}:monitor-status`,
        kind: "status_update",
        title: "等待检查",
        state: "stale",
        phase: "stale",
      }),
    ]));
    expect(store.getState().sessionActivity).toMatchObject({
      level: "warning",
      title: "等待检查",
    });
  });

  it("anchors resumed task progress to the turn that resumed it", async () => {
    const taskRunId = "taskrun:turn:session:live:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:live",
      activeTurnSnapshot: {
        turn_id: "turn:session:live:1",
        task_run_id: taskRunId,
      },
      messages: [
        { id: "user:1", role: "user", content: "开始任务", toolCalls: [], retrievals: [], sourceIndex: 0 },
        { id: "assistant:1", role: "assistant", content: "任务已接管", toolCalls: [], retrievals: [], sourceIndex: 1 },
        { id: "user:2", role: "user", content: "继续", toolCalls: [], retrievals: [], sourceIndex: 2 },
        { id: "assistant:2", role: "assistant", content: "我会继续处理当前工作。", toolCalls: [], retrievals: [], sourceIndex: 3 },
      ],
    });
    const runtime = new WorkspaceRuntime(store) as unknown as {
      hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
    };
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValueOnce({
      active_task_run_id: taskRunId,
      monitor: {
        task_run_id: taskRunId,
        session_id: "session:live",
        status: "running",
        event_count: 3,
        latest_interaction_turn_id: "turn:session:live:3",
        latest_step: {
          event_id: "step:resume",
          step: "task_executor_scheduled",
          status: "running",
          created_at: 3,
        },
        latest_step_summary: "已开始继续处理；接下来会持续汇报正在推进的步骤。",
        latest_event: { event_type: "step_summary_recorded" },
        updated_at: 3,
        task_run: {
          task_run_id: taskRunId,
          task_id: "task:turn:session:live:1",
          status: "running",
        },
      },
      task_runs: [],
    });

    await runtime.hydrateLatestOrchestrationSnapshot("session:live");

    expect(store.getState().messages[1]?.runtimeAttachments ?? []).toHaveLength(0);
    expect(store.getState().messages[3]?.runtimeAttachments?.[0]?.anchor_turn_id).toBe("turn:session:live:3");
    expect(store.getState().messages[3]?.runtimeAttachments?.[0]?.progress_entries?.[0]?.id).toBe("step:resume");
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
    vi.stubGlobal("EventSource", undefined);
    api.getRunMonitor.mockRejectedValue(new DOMException("signal is aborted without reason", "AbortError"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startRunMonitor();
    await vi.runOnlyPendingTimersAsync();

    expect(store.getState().runMonitorError).toBe("");
    expect(store.getState().runMonitorLoading).toBe(false);
  });

  it("renders new runtime answer events before final done", () => {
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
    transition = reduceStreamEvent(transition.state, transition.session, "answer_candidate", { content: "候选答案不应覆盖已有流式内容。" });
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
    expect(assistant?.content).toBe("你好，我在。");
    expect(assistant?.stageStatus).toBe("完成");
    expect(assistant?.answerCanonicalState).toBe("stable_answer");
    expect(assistant?.answerPersistPolicy).toBe("persist_canonical");
    expect(assistant?.answerSelectedChannel).toBe("answer_candidate");
    expect(assistant?.answerLeakFlags).toEqual(["internal_protocol_final_text"]);
  });

  it("does not append legacy content_delta after typed stream cutover", () => {
    let transition = startStreamingTurn(getDefaultState(), "你好");
    transition = reduceStreamEvent(transition.state, transition.session, "content_delta", { content: "旧流式内容。" });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("");
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
      content: "提前候选答案不应显示。",
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
    expect(assistant?.content).toBe("最终回答。");
  });

  it("uses done summary as assistant prose when final content is absent", () => {
    let transition = startStreamingTurn(getDefaultState(), "修一下页面反馈");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      summary: "已完成页面反馈修复，最终正文不应被工具反馈替代。",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("已完成页面反馈修复，最终正文不应被工具反馈替代。");
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

  it("uses assistant_text as visible prose before task handoff done", () => {
    let transition = startStreamingTurn(getDefaultState(), "开始任务");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      content: "我先把目标转成可执行任务，然后持续推进实现和验证。",
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "done 不应覆盖已经显示的 agent 正文。",
      answer_channel: "task_control",
      answer_source: "harness.single_agent_turn.request_task_run",
      answer_canonical_state: "progress_only",
      answer_persist_policy: "persist_debug_only",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("我先把目标转成可执行任务，然后持续推进实现和验证。");
    expect(assistant?.answerChannel).toBe("task_control");
    expect(assistant?.answerPersistPolicy).toBe("persist_debug_only");
  });

  it("renders task steer acknowledgements as status for queued active work", () => {
    let transition = startQueuedActiveTurn(getDefaultState(), "补充限制条件");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      title: "已收到补充要求",
      detail: "已加入当前任务队列，会在当前执行中优先纳入。",
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

    expect(transition.state.messages).toHaveLength(1);
    expect(transition.state.messages[0]).toMatchObject({
      role: "user",
      content: "补充限制条件",
    });
    expect(transition.state.sessionActivity).toMatchObject({
      level: "success",
      title: "已收到补充要求",
    });
  });

  it("projects stopped turns into the assistant public timeline", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续生成");
    transition = reduceStreamEvent(transition.state, transition.session, "tool_observation", {
      tool_observation: {
        tool_name: "read_file",
        status: "error",
        text: "Read failed: start_line 900 exceeds total_lines 872",
      },
      event_offset: 1,
    });
    transition = reduceStreamEvent(transition.state, transition.session, "stopped", {
      reason: "user_stopped",
      event_offset: 2,
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.stageStatus).toBe("已停止");
    expect(assistant?.runtimePublicTimelineDraft).toEqual(expect.arrayContaining([
      expect.objectContaining({
        item_id: "stream:stopped",
        kind: "status_update",
        title: "已停止本轮生成",
        state: "stopped",
      }),
    ]));
  });

  it("keeps chat usable when noncritical workspace metadata is still loading", async () => {
    vi.useRealTimers();
    api.listSkills.mockImplementation(() => new Promise(() => undefined));
    api.loadFile.mockImplementation(() => new Promise(() => undefined));
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "done" };
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await runtime.actions.sendMessage("你好");

    expect(store.getState().currentSessionId).toBe("session:fresh");
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.session_id).toBe("session:fresh");
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

  it("keeps stopped activity scoped to the session that was stopped", async () => {
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
      level: "stopped",
      title: "已停止本轮生成",
      event: "stopped",
    });
    expect(store.getState().sessionActivitiesById["session:stopped"]).toMatchObject({
      level: "stopped",
      title: "已停止本轮生成",
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
      level: "stopped",
      title: "已停止本轮生成",
      event: "stopped",
    });
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
    api.getSessionTimeline.mockResolvedValue({
      messages: [{ role: "assistant", content: "当前会话内容" }],
      runtime_attachments: [],
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
    expect(api.getWorkbenchCurrentSession).not.toHaveBeenCalled();
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(api.listProjectWorkspaces).toHaveBeenCalledTimes(1);
    expect(store.getState().workspaceInitializing).toBe(false);
    expect(store.getState().currentSessionId).toBe("session:current");
    expect(store.getState().sessions.map((session) => session.id)).toContain("session:current");
    expect(store.getState().permissionMode).toBe("plan");
    expect(store.getState().messages).toMatchObject([
      { role: "assistant", content: "当前会话内容" },
    ]);
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      "agentWorkbench.lastActiveSessionRef",
      JSON.stringify({ sessionId: "session:current", poolKey: "main-chat" }),
    );
    expect(api.setWorkbenchCurrentSession).toHaveBeenCalledWith({
      sessionId: "session:current",
      scope: undefined,
      poolKey: "main-chat",
    });
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

  it("keeps session history visible when token statistics refresh fails", async () => {
    api.getSessionTimeline.mockResolvedValue({
      messages: [{ role: "user", content: "继续修复 token 统计" }],
      runtime_attachments: [],
      conversation_state: { authority: "sessions.conversation_state", permission_mode: "full_access" },
    });
    api.getSessionTokens.mockRejectedValue(new Error("token endpoint failed"));
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
  });

  it("keeps the local streaming assistant shell when session history refresh races with deltas", async () => {
    const sessionId = "session:live-refresh";
    const assistantId = "assistant:local-live";
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "请回答" },
        { role: "assistant", content: "后端历史旧壳" },
      ],
      runtime_attachments: [],
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
          runtimePublicTimelineDraft: [],
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
    expect(store.getState().messages.at(-1)?.content).toBe("遇到前端");
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
    api.getChatRun.mockResolvedValue({
      stream_run_id: "strun:resume",
      session_id: "session:existing",
      event_log_id: "chatrun:resume",
      root_request_ref: "chatreq:resume",
      status: "running",
      latest_event_offset: 3,
      is_reconnectable: true,
      stream_url: "/api/chat/runs/strun:resume/events",
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
        { role: "assistant", content: "续接完成" },
      ],
      runtime_attachments: [],
    });
    const store = createStore(getDefaultState());
    let recoveryFeedbackDuringAttach: unknown;
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      recoveryFeedbackDuringAttach = store.getState().messages
        .flatMap((message) => message.runtimePublicTimelineDraft ?? [])
        .find((item) => item.item_id === "stream-restore:strun:resume");
      handlers.onEvent("assistant_text_delta", { sequence: 1, content: "续", content_utf8_start: 0, event_offset: 4 });
      handlers.onEvent("assistant_text_final", { sequence: 2, content: "续接完成", content_sha256: "sha256:resume", event_offset: 5 });
      handlers.onEvent("done", { content: "续接完成", event_offset: 5 });
      return { terminalEvent: "done", streamRunId: "strun:resume", eventLogId: "chatrun:resume", lastEventOffset: 5 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.getLatestChatRunForSession).not.toHaveBeenCalled();
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:existing",
      "strun:resume",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: cursor,
        replayFromStart: false,
      }),
    );
    expect(store.getState().currentSessionId).toBe("session:existing");
    expect(store.getState().messages.some((message) => message.role === "assistant" && message.content.includes("续"))).toBe(true);
    expect(recoveryFeedbackDuringAttach).toMatchObject({
      kind: "status_update",
      surface: "status",
      source_authority: "system",
      title: "同步运行进度",
      detail: "已拿到上次进度，继续同步后续结果。",
      state: "running",
    });
    expect(JSON.stringify(store.getState().messages)).not.toContain("正在重新连接");
  });

  it("reattaches the latest active chat run without a cursor by replaying from the beginning", async () => {
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
      latest_event_offset: 7,
      is_reconnectable: true,
      stream_url: "/api/chat/runs/strun:latest/events",
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
      ],
      runtime_attachments: [],
    });
    const store = createStore(getDefaultState());
    let recoveryFeedbackDuringAttach: unknown;
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      recoveryFeedbackDuringAttach = store.getState().messages
        .flatMap((message) => message.runtimePublicTimelineDraft ?? [])
        .find((item) => item.item_id === "stream-restore:strun:latest");
      handlers.onEvent("assistant_text_delta", { sequence: 1, content: "恢复", content_utf8_start: 0, event_offset: 1 });
      handlers.onEvent("assistant_text_final", { sequence: 2, content: "恢复完成", content_sha256: "sha256:latest", event_offset: 2 });
      handlers.onEvent("done", { content: "恢复完成", event_offset: 2 });
      return { terminalEvent: "done", streamRunId: "strun:latest", eventLogId: "chatrun:latest", lastEventOffset: 2 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.getLatestChatRunForSession).toHaveBeenCalledWith("session:latest", true, undefined);
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:latest",
      "strun:latest",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: null,
        replayFromStart: true,
      }),
    );
    expect(recoveryFeedbackDuringAttach).toMatchObject({
      kind: "status_update",
      surface: "status",
      source_authority: "system",
      title: "同步运行进度",
      detail: "正在同步这个会话里仍在运行的进度。",
      state: "running",
    });
  });

  it("hydrates the selected session when an active stream marker has no visible cache", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:stale-active",
      sessions: [{
        id: "session:stale-active",
        title: "Stale active",
        created_at: 1,
        updated_at: 2,
        message_count: 1,
      }],
      activeStreamSessionIds: ["session:stale-active"],
      isStreaming: true,
      messages: [],
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "继续修复", turn_id: "turn:session:stale-active:1" },
      ],
      runtime_attachments: [{
        attachment_id: "runtime-attachment:stale-active",
        run_id: "turnrun:turn:session:stale-active:1",
        anchor_turn_id: "turn:session:stale-active:1",
        anchor_message_id: "history-message:turn:session:stale-active:1:assistant",
        anchor_role: "assistant",
        status: "running",
        lifecycle: "running",
        public_timeline: [{
          item_id: "work-action:read-context",
          kind: "work_action",
          title: "已读取上下文",
          public_summary: "已读取上下文 adventure-island-standalone/index.html",
          state: "done",
        }],
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    const reattached = await (runtime as unknown as {
      reattachChatRunForSession: (sessionId: string) => Promise<boolean>;
    }).reattachChatRunForSession("session:stale-active");

    expect(reattached).toBe(true);
    expect(api.getSessionTimeline).toHaveBeenCalledWith("session:stale-active", undefined);
    expect(api.streamExistingChatRun).not.toHaveBeenCalled();
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(store.getState().messages[1].runtimeAttachments?.[0]?.public_timeline?.[0]).toMatchObject({
      title: "已读取上下文",
    });
  });

  it("hydrates monitor snapshots when the current active stream has no visible messages", async () => {
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:monitor-empty",
      activeStreamSessionIds: ["session:monitor-empty"],
      isStreaming: true,
      messages: [],
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "继续", turn_id: "turn:session:monitor-empty:1" },
      ],
      runtime_attachments: [{
        attachment_id: "runtime-attachment:monitor-empty",
        run_id: "turnrun:turn:session:monitor-empty:1",
        anchor_turn_id: "turn:session:monitor-empty:1",
        anchor_message_id: "history-message:turn:session:monitor-empty:1:assistant",
        anchor_role: "assistant",
        status: "running",
        lifecycle: "running",
        public_timeline: [{
          item_id: "work-action:monitor-read",
          kind: "work_action",
          title: "已同步运行反馈",
          public_summary: "已同步运行反馈",
          state: "done",
        }],
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    runtime.applyRunMonitorStreamPayload({ monitor: monitorForTest([]) });
    await flushPromises(12);

    expect(api.getSessionTimeline).toHaveBeenCalledWith("session:monitor-empty", undefined);
    expect(store.getState().messages.map((message) => message.role)).toEqual(["user", "assistant"]);
  });

  it("drops an invalid persisted cursor before reattaching the latest active chat run", async () => {
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
    api.getChatRun.mockResolvedValue({
      stream_run_id: "strun:stale",
      session_id: "session:other",
      event_log_id: "chatrun:stale",
      root_request_ref: "chatreq:stale",
      status: "running",
      latest_event_offset: 99,
      is_reconnectable: true,
      stream_url: "/api/chat/runs/strun:stale/events",
    });
    api.getLatestChatRunForSession.mockResolvedValue({
      stream_run_id: "strun:fresh",
      session_id: "session:latest-after-stale",
      event_log_id: "chatrun:fresh",
      root_request_ref: "chatreq:fresh",
      status: "running",
      latest_event_offset: 4,
      is_reconnectable: true,
      stream_url: "/api/chat/runs/strun:fresh/events",
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "继续处理" },
      ],
      runtime_attachments: [],
    });
    const store = createStore(getDefaultState());
    let recoveryFeedbackDuringAttach: unknown;
    api.streamExistingChatRun.mockImplementation(async (_sessionId, _streamRunId, handlers) => {
      recoveryFeedbackDuringAttach = store.getState().messages
        .flatMap((message) => message.runtimePublicTimelineDraft ?? [])
        .find((item) => item.item_id === "stream-restore:strun:fresh");
      handlers.onEvent("done", { content: "已接回", event_offset: 5 });
      return { terminalEvent: "done", streamRunId: "strun:fresh", eventLogId: "chatrun:fresh", lastEventOffset: 5 };
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.clearChatStreamCursor).toHaveBeenCalledWith("session:latest-after-stale");
    expect(api.streamExistingChatRun).toHaveBeenCalledWith(
      "session:latest-after-stale",
      "strun:fresh",
      expect.any(Object),
      expect.objectContaining({
        initialCursor: null,
        replayFromStart: true,
      }),
    );
    expect(recoveryFeedbackDuringAttach).toMatchObject({
      kind: "status_update",
      surface: "status",
      source_authority: "system",
      title: "同步运行进度",
      detail: "正在同步这个会话里仍在运行的进度。",
      state: "running",
    });
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
    api.getChatRun.mockResolvedValue({
      stream_run_id: "strun:terminal",
      session_id: "session:terminal",
      event_log_id: "chatrun:terminal",
      root_request_ref: "chatreq:terminal",
      status: "completed",
      latest_event_offset: 9,
      terminal_event: "done",
      is_reconnectable: true,
      stream_url: "/api/chat/runs/strun:terminal/events",
    });
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "任务" },
        { role: "assistant", content: "完成" },
      ],
      runtime_attachments: [],
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    await runtime.initialize();
    await Promise.resolve();

    expect(api.clearChatStreamCursor).toHaveBeenCalledWith("session:terminal");
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

  it("keeps the page alive when selected session history times out", async () => {
    vi.useRealTimers();
    api.getSessionTimeline.mockRejectedValue(new Error("Request timed out after 12000ms: /sessions/session:slow/timeline"));
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
    api.getSessionTimeline.mockResolvedValue({
      messages: [{ role: "assistant", content: "恢复成功" }],
      runtime_attachments: [],
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
    api.streamChat.mockResolvedValue({ terminalEvent: "done" });
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
        legacy_content_delta_public_stream: false,
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
        legacy_content_delta_public_stream: false,
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

  it("sends disabled stream policy when stream display is turned off", async () => {
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
        enabled: false,
        mode: "disabled",
        emit_assistant_text_delta: false,
        legacy_content_delta_public_stream: false,
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
      return { terminalEvent: "done" };
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

  it("keeps image turn errors visible instead of replacing them with refreshed empty history", async () => {
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
    expect(lastMessage?.content).toContain("Image API failed with status 400");
    expect(store.getState().sessionActivity.level).toBe("error");
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
    api.getSessionTimeline.mockResolvedValue({
      messages: [],
      runtime_attachments: [],
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
    api.getSessionTimeline.mockResolvedValue({
      messages: [],
      runtime_attachments: [],
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
    expect(api.getSessionTimeline).not.toHaveBeenCalled();
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

  it("keeps the visible chat session when changing the outer task environment mode", async () => {
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

    runtime.actions.setTaskEnvironmentWorkspaceView("code-environment");
    await flushPromises();

    expect(store.getState().activeWorkspaceView).toBe("code-environment");
    expect(store.getState().currentSessionId).toBe("session:general");
    expect(store.getState().messages.map((message) => message.content)).toEqual(["通用环境问题", "通用环境回答"]);
    expect(store.getState().conversationActiveEnvironment).toMatchObject({
      task_environment_id: "env.coding.vibe_workspace",
      environment_label: "Vibe 编码工作区",
      source: "workspace-mode",
    });
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(api.getSessionTimeline).not.toHaveBeenCalled();
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

    expect(store.getState().activeWorkspaceView).toBe("code-environment");
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
      return { terminalEvent: "done" };
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
    expect(assistant?.runtimeProgress ?? []).not.toContainEqual(
      expect.objectContaining({ title: "正式任务已创建" }),
    );
  });

  it("attaches formal task lifecycle signals to the assistant task flow", () => {
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
    expect(assistant?.runtimeProgress?.map((entry) => entry.title)).toEqual([
      "处理已开始",
      "处理清单已建立",
      "继续在后台处理",
    ]);
    expect(assistant?.runtimeProgress?.at(-1)).toMatchObject({
      level: "waiting",
      statusText: "等待",
      taskRunId: "taskrun:abc",
    });
    expect(assistant?.stageStatus).toBe("继续在后台处理");
  });

  it("attaches tool runtime requests to the assistant task flow without reviving legacy tool results", () => {
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
    expect(assistant?.runtimeProgress?.map((entry) => entry.kind)).toEqual(["tool"]);
    expect(assistant?.runtimeProgress?.[0]).toMatchObject({
      statusText: "写入中",
      toolName: "write_file",
    });
  });

  it("shows single-agent turn tool events in session activity and assistant progress", () => {
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
      level: "running",
      title: "正在写入",
      detail: "docs/turn.md",
      toolName: "write_file",
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
      level: "running",
      title: "写入完成",
      detail: "docs/turn.md",
      toolName: "write_file",
      receipt: {
        artifacts: [{ label: "产物", path: "docs/turn.md" }],
      },
    });
    expect(assistant?.runtimeProgress?.map((entry) => entry.title)).toEqual([
      "正在写入 docs/turn.md",
      "写入完成 docs/turn.md",
    ]);
    expect(assistant?.runtimeProgress?.[1]).toMatchObject({
      kind: "tool",
      statusText: "已完成",
      toolName: "write_file",
      artifacts: [{ label: "产物", path: "docs/turn.md" }],
    });
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
    expect(assistant?.stageStatus).toBe("权限已检查");
    expect(assistant?.runtimeProgress).toEqual([]);
  });

  it("writes terminal error detail into the assistant message instead of only the status bar", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "error", {
      error: "当前环境的写入权限不足，且创建文件的工具不可见。",
      code: "agent_blocked",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("处理失败\n\n当前环境的写入权限不足，且创建文件的工具不可见。");
    expect(assistant?.runtimeProgress?.at(-1)).toMatchObject({
      title: "处理失败",
      body: "当前环境的写入权限不足，且创建文件的工具不可见。",
      kind: "terminal",
      level: "error",
    });
    expect(transition.state.sessionActivity).toMatchObject({
      level: "error",
      title: "处理失败",
      detail: "详情已写入会话。",
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
    expect(assistant?.stageStatus).toBe("正在整理上下文");
    expect(assistant?.runtimeProgress).toEqual([]);
  });

  it("attaches session timeline TaskRun activity to the assistant message", async () => {
    vi.useRealTimers();
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "执行任务" },
        { role: "assistant", content: "任务已接管" },
        { role: "assistant", content: "任务完成" },
      ],
      runtime_attachments: [{
        attachment_id: "runtime-attachment:taskrun:turn:session:timeline:1:abc",
        run_id: "taskrun:turn:session:timeline:1:abc",
        anchor_turn_id: "turn:session:timeline:1",
        task_run_id: "taskrun:turn:session:timeline:1:abc",
        status: "completed",
        lifecycle: "completed",
        title: "Agent 运行",
        latest_step_summary: "任务合同已满足。",
        progress_entries: [{
          id: "step:1",
          title: "任务已完成",
          body: "任务合同已满足。",
          kind: "terminal",
          level: "success",
          eventType: "step_summary_recorded",
        }],
        artifact_refs: [{ path: "storage/task.txt" }],
      }],
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:timeline",
      sessions: [{
        id: "session:timeline",
        title: "Timeline",
        created_at: 1,
        updated_at: 1,
        message_count: 3,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.selectSession({ sessionId: "session:timeline", poolKey: "main-chat" });

    const assistant = store.getState().messages.find((message) => message.role === "assistant" && message.content === "任务已接管");
    expect(assistant?.runtimeAttachments?.[0]).toMatchObject({
      run_id: "taskrun:turn:session:timeline:1:abc",
      task_run_id: "taskrun:turn:session:timeline:1:abc",
      status: "completed",
    });
  });

  it("keeps streamed public progress after session timeline refresh", async () => {
    vi.useRealTimers();
    api.getSessionTimeline.mockResolvedValue({
      messages: [
        { role: "user", content: "请直接回复" },
        { role: "assistant", content: "已直接回复。" },
      ],
      runtime_attachments: [],
    });
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("runtime_step_summary", {
        step: "model_action_received",
        status: "running",
        summary: "内部摘要",
        event: {
          event_id: "rtevt:public-progress",
          run_id: "turnrun:turn:session:progress:1",
          created_at: 10,
          payload: {
            public_progress_note: "我正在直接回复这条消息。",
            agent_brief_output: "已形成一句话回复。",
          },
        },
      });
      handlers.onEvent("done", { content: "已直接回复。" });
      return { terminalEvent: "done" };
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:progress",
      sessions: [{
        id: "session:progress",
        title: "Progress",
        created_at: 1,
        updated_at: 1,
        message_count: 0,
      }],
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("请直接回复");

    const assistant = store.getState().messages.find((message) => message.role === "assistant");
    expect(assistant?.runtimeProgress?.[0]).toMatchObject({
      publicNote: "我正在直接回复这条消息。",
      agentBrief: "已形成一句话回复。",
    });
  });

  it("writes public timeline delta into the assistant draft during live stream", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续执行");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_step_summary", {
      step: "task_tool_executed",
      status: "running",
      public_timeline_delta: [
        {
          item_id: "tool:write",
          kind: "work_action",
          action_kind: "edit",
          title: "正在更新文件",
          subject_label: "docs/plan.md",
          public_summary: "正在更新文件 docs/plan.md",
          state: "running",
        },
      ],
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.runtimePublicTimelineDraft).toEqual([
      expect.objectContaining({
        item_id: "tool:write",
        kind: "work_action",
        public_summary: "正在更新文件 docs/plan.md",
      }),
    ]);
  });

  it("finalizes live public timeline draft when the turn completes without a matching tool completion delta", () => {
    let transition = startStreamingTurn(getDefaultState(), "再做一个踢足球小游戏");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_step_summary", {
      step: "task_tool_executed",
      status: "running",
      public_timeline_delta: [
        {
          item_id: "tool:football:start",
          kind: "work_action",
          action_kind: "edit",
          title: "正在更新文件",
          subject_label: "artifacts/football.html",
          public_summary: "正在更新文件 artifacts/football.html",
          state: "running",
          stream_state: "streaming",
        },
      ],
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "写好了。\n\nD:\\AI应用\\langchain-agent\\storage\\task_environments\\general\\workspace\\artifacts\\football.html",
      answer_canonical_state: "stable_answer",
      answer_channel: "conversation",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.runtimePublicTimelineDraft).toEqual([
      expect.objectContaining({
        item_id: "tool:football:start",
        kind: "work_action",
        state: "done",
        stream_state: "done",
      }),
    ]);
  });

  it("does not block send completion on post-stream session refresh", async () => {
    vi.useRealTimers();
    api.listSessions.mockImplementation(() => new Promise(() => undefined));
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("error", {
        error: "backend failed",
        terminal_reason: "backend_error",
      });
      return { terminalEvent: "error" };
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
      level: "error",
      event: "error",
    });
  });
});
