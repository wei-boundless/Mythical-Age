import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStore, getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";
import { WorkspaceRuntime } from "./runtime";
import type { StoreState } from "./types";

const api = vi.hoisted(() => ({
  createSession: vi.fn(),
  getCodeEnvironmentWorkspaceTree: vi.fn(),
  getGlobalRuntimeMonitor: vi.fn(),
  getModelProviderConfig: vi.fn(),
  getOrchestrationHarnessTaskRunLiveMonitor: vi.fn(),
  getOrchestrationHarnessSessionLiveMonitor: vi.fn(),
  pauseOrchestrationHarnessTaskRun: vi.fn(),
  getRagMode: vi.fn(),
  resumeOrchestrationHarnessTaskRun: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessionTimeline: vi.fn(),
  getSessionTokens: vi.fn(),
  getSoulImageAssetConfig: vi.fn(),
  getGraphRunMonitor: vi.fn(),
  getWorkspaceContext: vi.fn(),
  listSessions: vi.fn(),
  listSkills: vi.fn(),
  loadFile: vi.fn(),
  stopOrchestrationHarnessTaskRun: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  createSession: api.createSession,
  deleteSession: vi.fn(),
  runGraphRunUntilIdle: vi.fn(),
  evaluateTaskGraphRunMonitor: vi.fn(),
  getCodeEnvironmentWorkspaceTree: api.getCodeEnvironmentWorkspaceTree,
  getGlobalRuntimeMonitor: api.getGlobalRuntimeMonitor,
  getRuntimeMonitorEventStreamUrl: vi.fn(() => "http://127.0.0.1:8003/api/orchestration/harness/monitor-events"),
  getModelProviderConfig: api.getModelProviderConfig,
  getSoulImageAssetConfig: api.getSoulImageAssetConfig,
  getWorkspaceContext: api.getWorkspaceContext,
  isRequestAbortError: (error: unknown) => error instanceof DOMException && error.name === "AbortError",
  getGraphRunMonitor: api.getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor: api.getOrchestrationHarnessTaskRunLiveMonitor,
  getOrchestrationHarnessSessionLiveMonitor: api.getOrchestrationHarnessSessionLiveMonitor,
  pauseOrchestrationHarnessTaskRun: api.pauseOrchestrationHarnessTaskRun,
  getRagMode: api.getRagMode,
  resumeOrchestrationHarnessTaskRun: api.resumeOrchestrationHarnessTaskRun,
  getSessionHistory: api.getSessionHistory,
  getSessionTimeline: api.getSessionTimeline,
  getSessionTokens: api.getSessionTokens,
  listSessions: api.listSessions,
  listSkills: api.listSkills,
  loadFile: api.loadFile,
  renameSession: vi.fn(),
  resolveHarnessTaskRunApproval: vi.fn(),
  saveFile: vi.fn(),
  setRagMode: vi.fn(),
  stopOrchestrationHarnessTaskRun: api.stopOrchestrationHarnessTaskRun,
  stopOrchestrationTaskRun: vi.fn(),
  streamChat: api.streamChat,
  switchSoulSystemSeed: vi.fn(),
  truncateSessionMessages: vi.fn(),
}));

vi.mock("@/lib/mainAgentAssemblyModes", () => ({
  buildMainAgentTaskSelection: vi.fn((selection) => selection),
}));

vi.mock("@/lib/souls", () => ({
  ACTIVE_SOUL_PATH: "soul/active.json",
  SOUL_SEED_PATHS: {},
  inferSoulKey: vi.fn(() => "default"),
  parseSoulSeed: vi.fn(() => ({ key: "default", label: "Default" })),
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
    route: { kind: "chat_turn_runtime", session_id: "session:test", task_run_id: "taskrun:test" },
    ...patch,
  };
}

function monitorForTest(items: Array<Record<string, unknown>>, patch: Record<string, unknown> = {}) {
  const buckets = {
    running: items.filter((item) => item.bucket === "running"),
    completed: items.filter((item) => item.bucket === "completed"),
    failed: items.filter((item) => item.bucket === "failed"),
    diagnostics: items.filter((item) => item.bucket === "diagnostics"),
  };
  return {
    authority: "runtime_live_monitor.global",
    summary: {
      total: items.length,
      running: buckets.running.length,
      waiting: buckets.running.filter((item) => item.lifecycle === "waiting").length,
      completed: buckets.completed.length,
      failed: buckets.failed.length,
      diagnostics: buckets.diagnostics.length,
      action_required: items.filter((item) => item.action_required === true).length,
    },
    buckets,
    task_runs: items,
    updated_at: 1,
    ...patch,
  };
}

describe("WorkspaceRuntime task graph monitor polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.getGlobalRuntimeMonitor.mockReset();
    api.getGlobalRuntimeMonitor.mockResolvedValue({
      authority: "runtime_live_monitor.global",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      task_runs: [],
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
    api.getOrchestrationHarnessSessionLiveMonitor.mockReset();
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue({ monitor: null });
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockReset();
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockResolvedValue({ monitor: null });
    api.pauseOrchestrationHarnessTaskRun.mockReset();
    api.pauseOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.resumeOrchestrationHarnessTaskRun.mockReset();
    api.resumeOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.stopOrchestrationHarnessTaskRun.mockReset();
    api.stopOrchestrationHarnessTaskRun.mockResolvedValue({ ok: true });
    api.getSessionHistory.mockReset();
    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionTimeline.mockReset();
    api.getSessionTimeline.mockResolvedValue({ messages: [], runtime_attachments: [] });
    api.getSessionTokens.mockReset();
    api.getSessionTokens.mockResolvedValue(null);
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
    api.getRagMode.mockReset();
    api.getRagMode.mockResolvedValue({ enabled: false });
    api.getModelProviderConfig.mockReset();
    api.getModelProviderConfig.mockResolvedValue(null);
    api.getSoulImageAssetConfig.mockReset();
    api.getSoulImageAssetConfig.mockResolvedValue(null);
    api.getWorkspaceContext.mockReset();
    api.getWorkspaceContext.mockResolvedValue(null);
    api.listSessions.mockReset();
    api.listSessions.mockResolvedValue([]);
    api.listSkills.mockReset();
    api.listSkills.mockResolvedValue([]);
    api.loadFile.mockReset();
    api.loadFile.mockResolvedValue({ path: "durable_memory/index/MEMORY.md", content: "" });
    api.streamChat.mockReset();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
      return { terminalEvent: "done" };
    });
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

  it("keeps polling a bound TaskGraph run when the interaction dock is closed", async () => {
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

    expect(api.getGraphRunMonitor).toHaveBeenCalledTimes(3);
    expect(store.getState().taskGraphMonitorBinding?.task_run_id).toBe("taskrun:bound");
    expect(store.getState().taskGraphBoundRunMonitor?.active_node_work_orders?.[0]?.node_id).toBe("draft");
  });

  it("keeps the global monitor selection on top-level TaskGraph runs", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyGlobalRuntimeMonitorSnapshot: (monitor: {
        authority: string;
        summary: {
          total: number;
          running: number;
          waiting: number;
          completed: number;
          failed: number;
        };
        task_runs: Array<Record<string, unknown>>;
        updated_at: number;
      }, options?: { detailTaskRunId?: string }) => void;
      selectGlobalRuntimeMonitorTaskRun: (taskRunId: string) => void;
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

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot(monitor, { detailTaskRunId: "taskrun:agent" });

    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:agent");

    runtimeHarness.selectGlobalRuntimeMonitorTaskRun("taskrun:module");

    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("");
  });

  it("opens a global monitor TaskGraph run in the task-system runtime page", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyGlobalRuntimeMonitorSnapshot: (monitor: {
        authority: string;
        summary: {
          total: number;
          running: number;
          waiting: number;
          completed: number;
          failed: number;
        };
        task_runs: Array<Record<string, unknown>>;
        updated_at: number;
      }) => void;
    };

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot(monitorForTest([
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
        route: { kind: "task_graph_run", session_id: "session", task_run_id: "taskrun:master", graph_id: "graph.writing.master", graph_run_id: "grun:master", graph_harness_config_id: "ghcfg:master" },
      }),
    ]));

    runtime.actions.openGlobalRuntimeMonitorTaskRun("taskrun:master");

    expect(store.getState().activeWorkspaceView).toBe("task-system");
    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:master");
    expect(store.getState().taskGraphMonitorBinding).toMatchObject({
      task_run_id: "taskrun:master",
      graph_run_id: "grun:master",
      graph_harness_config_id: "ghcfg:master",
      graph_id: "graph.writing.master",
      session_id: "session",
      title: "长篇小说",
    });
    expect(store.getState().taskGraphRunInteractionOpen).toBe(false);
    expect(store.getState().taskSystemRuntimeNavigationTarget).toMatchObject({
      task_run_id: "taskrun:master",
      layer: "runtime",
      graph_id: "graph.writing.master",
    });
  });

  it("opens a global monitor chat-turn run in its conversation page", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyGlobalRuntimeMonitorSnapshot: (monitor: {
        authority: string;
        summary: {
          total: number;
          running: number;
          waiting: number;
          completed: number;
          failed: number;
        };
        task_runs: Array<Record<string, unknown>>;
        updated_at: number;
      }) => void;
    };

    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionTokens.mockResolvedValue(null);
    api.getOrchestrationHarnessSessionLiveMonitor.mockResolvedValue(null);

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot(monitorForTest([
      itemForMonitor({
        task_run_id: "taskrun:turn:session-a:1:abc",
        session_id: "session-a",
        task_id: "task:turn:session-a:1",
        title: "会话运行",
        status: "waiting_executor",
        terminal_reason: "waiting_executor",
        lifecycle: "waiting",
        latest_event_type: "task_run_lifecycle_waiting_executor",
        route: { kind: "chat_turn_runtime", session_id: "session-a", task_run_id: "taskrun:turn:session-a:1:abc" },
      }),
    ]));

    runtime.actions.openGlobalRuntimeMonitorTaskRun("taskrun:turn:session-a:1:abc");

    expect(store.getState().activeWorkspaceView).toBe("chat");
    expect(store.getState().currentSessionId).toBe("session-a");
    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:turn:session-a:1:abc");
    expect(store.getState().taskSystemRuntimeNavigationTarget).toBeNull();
  });

  it("ignores stale global monitor snapshots after a newer revision has landed", () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyGlobalRuntimeMonitorSnapshot: (monitor: {
        authority: string;
        revision: string;
        summary: {
          total: number;
          running: number;
          waiting: number;
          completed: number;
          failed: number;
        };
        buckets: {
          running: Array<Record<string, unknown>>;
        };
        task_runs: Array<Record<string, unknown>>;
        updated_at: number;
      }) => void;
    };

    const newerRun = itemForMonitor({ task_run_id: "taskrun:newer", title: "新任务" });
    const olderRun = itemForMonitor({ task_run_id: "taskrun:older", title: "旧任务" });

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot({
      authority: "runtime_live_monitor.global",
      revision: "rtmon:20:new",
      summary: { total: 1, running: 1, waiting: 0, completed: 0, failed: 0 },
      buckets: { running: [newerRun] },
      task_runs: [newerRun],
      updated_at: 20,
    });
    runtimeHarness.applyGlobalRuntimeMonitorSnapshot({
      authority: "runtime_live_monitor.global",
      revision: "rtmon:10:old",
      summary: { total: 1, running: 1, waiting: 0, completed: 0, failed: 0 },
      buckets: { running: [olderRun] },
      task_runs: [olderRun],
      updated_at: 10,
    });

    expect(store.getState().globalRuntimeMonitorRevision).toBe("rtmon:20:new");
    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:newer");
  });

  it("does not let a stale detail response overwrite the currently selected monitor detail", async () => {
    vi.useRealTimers();
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);
    const runtimeHarness = runtime as unknown as {
      applyGlobalRuntimeMonitorSnapshot: (monitor: {
        authority: string;
        revision: string;
        summary: {
          total: number;
          running: number;
          waiting: number;
          completed: number;
          failed: number;
        };
        buckets: {
          running: Array<Record<string, unknown>>;
        };
        task_runs: Array<Record<string, unknown>>;
        updated_at: number;
      }) => void;
      loadGlobalRuntimeMonitorTaskRunDetail: (taskRunId: string, revision?: string) => Promise<void>;
    };
    let resolveOldDetail: (value: unknown) => void = () => undefined;
    api.getOrchestrationHarnessTaskRunLiveMonitor.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveOldDetail = resolve;
      }),
    );
    const oldRun = itemForMonitor({ task_run_id: "taskrun:old", title: "旧任务" });
    const newRun = itemForMonitor({ task_run_id: "taskrun:new", title: "新任务" });

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot({
      authority: "runtime_live_monitor.global",
      revision: "rtmon:10:old",
      summary: { total: 1, running: 1, waiting: 0, completed: 0, failed: 0 },
      buckets: { running: [oldRun] },
      task_runs: [oldRun],
      updated_at: 10,
    });
    const loadingOldDetail = runtimeHarness.loadGlobalRuntimeMonitorTaskRunDetail("taskrun:old", "rtmon:10:old");
    runtimeHarness.applyGlobalRuntimeMonitorSnapshot({
      authority: "runtime_live_monitor.global",
      revision: "rtmon:20:new",
      summary: { total: 1, running: 1, waiting: 0, completed: 0, failed: 0 },
      buckets: { running: [newRun] },
      task_runs: [newRun],
      updated_at: 20,
    });
    resolveOldDetail({ monitor: { status: "running", task_run: { task_run_id: "taskrun:old" } } });
    await loadingOldDetail;

    expect(store.getState().globalRuntimeMonitorRevision).toBe("rtmon:20:new");
    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:new");
    expect(store.getState().globalRuntimeMonitorSelectedLiveMonitor).toBeNull();
  });

  it("closes a broken global monitor stream and reconnects after fallback polling", async () => {
    const instances: Array<{ close: ReturnType<typeof vi.fn>; onerror: (() => void) | null; onopen: (() => void) | null }> = [];
    class MockEventSource {
      onerror: (() => void) | null = null;
      onopen: (() => void) | null = null;
      close = vi.fn();

      constructor(_url: string) {
        instances.push(this);
      }

      addEventListener() {}
    }
    vi.stubGlobal("EventSource", MockEventSource);
    api.getGlobalRuntimeMonitor.mockResolvedValue({
      authority: "runtime_live_monitor.global",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      task_runs: [],
      updated_at: 1,
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startGlobalRuntimeMonitor();
    expect(instances).toHaveLength(1);

    instances[0].onerror?.();
    expect(instances[0].close).toHaveBeenCalledTimes(1);
    expect(store.getState().globalRuntimeMonitorStreamStatus).toBe("fallback");

    await vi.advanceTimersByTimeAsync(5000);

    expect(instances).toHaveLength(2);
    expect(store.getState().globalRuntimeMonitorStreamStatus).toBe("connecting");
  });

  it("backs off global monitor polling after the SSE monitor connects", async () => {
    const instances: Array<{ close: ReturnType<typeof vi.fn>; onerror: (() => void) | null; onopen: (() => void) | null }> = [];
    class MockEventSource {
      onerror: (() => void) | null = null;
      onopen: (() => void) | null = null;
      close = vi.fn();

      constructor(_url: string) {
        instances.push(this);
      }

      addEventListener() {}
    }
    vi.stubGlobal("EventSource", MockEventSource);
    api.getGlobalRuntimeMonitor.mockResolvedValue({
      authority: "runtime_live_monitor.global",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      task_runs: [],
      updated_at: 1,
    });
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startGlobalRuntimeMonitor();
    instances[0].onopen?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getGlobalRuntimeMonitor).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(59000);
    expect(api.getGlobalRuntimeMonitor).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000);
    expect(api.getGlobalRuntimeMonitor).toHaveBeenCalledTimes(2);
  });

  it("slows bound monitor polling while a chat stream is active", async () => {
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
    expect(api.getGraphRunMonitor).toHaveBeenCalledTimes(1);

    void runtime.actions.sendMessage("你好").catch(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(4999);
    expect(api.getGraphRunMonitor).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(api.getGraphRunMonitor).toHaveBeenCalledTimes(2);
  });

  it("continues session task monitor polling after chat stream hands off to a background task", async () => {
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("agent_turn_terminal", {
        event: {
          event_id: "rtevt:handoff",
          task_run_id: "turnrun:test",
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
      handlers.onEvent("done", { content: "任务已进入后台执行。" });
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

    expect(api.getOrchestrationHarnessSessionLiveMonitor).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1500);
    expect(api.getOrchestrationHarnessSessionLiveMonitor).toHaveBeenCalledTimes(3);
    expect(store.getState().sessionActivity.title).toBe("任务运行中");
  });

  it("accumulates live TaskRun progress entries instead of replacing them with the latest step", async () => {
    const taskRunId = "taskrun:turn:session:live:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:live",
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
          latest_step_summary: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
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

  it("controls the active session task run from chat actions", async () => {
    const taskRunId = "taskrun:turn:session-control:1:abc";
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session-control",
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

    expect(api.pauseOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, "user_pause_from_chat");
    expect(api.resumeOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, 12);
    expect(api.stopOrchestrationHarnessTaskRun).toHaveBeenCalledWith(taskRunId, "user_stop_from_chat");
    expect(store.getState().sessionActivity.title).toBe("任务已暂停");
  });

  it("does not surface transient global monitor aborts as user-visible errors", async () => {
    vi.stubGlobal("EventSource", undefined);
    api.getGlobalRuntimeMonitor.mockRejectedValue(new DOMException("signal is aborted without reason", "AbortError"));
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.startGlobalRuntimeMonitor();
    await vi.runOnlyPendingTimersAsync();

    expect(store.getState().globalRuntimeMonitorError).toBe("");
    expect(store.getState().globalRuntimeMonitorLoading).toBe(false);
  });

  it("renders new runtime answer events before final done", () => {
    let transition = startStreamingTurn(getDefaultState(), "你好");
    transition = reduceStreamEvent(transition.state, transition.session, "content_delta", { content: "你好，" });
    transition = reduceStreamEvent(transition.state, transition.session, "content_delta", { content: "我在。" });
    transition = reduceStreamEvent(transition.state, transition.session, "answer_candidate", { content: "候选答案不应覆盖已有流式内容。" });
    transition = reduceStreamEvent(transition.state, transition.session, "done", { content: "最终 done 不应重复覆盖已有流式内容。" });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.role).toBe("assistant");
    expect(assistant?.content).toBe("你好，我在。");
    expect(assistant?.stageStatus).toBe("完成");
  });

  it("keeps chat usable when noncritical workspace metadata is still loading", async () => {
    vi.useRealTimers();
    api.getRagMode.mockImplementation(() => new Promise(() => undefined));
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

    await runtime.actions.selectSession("session:other");
    expect(store.getState().sessionActivity).toMatchObject({
      level: "idle",
      event: "",
    });

    await runtime.actions.selectSession("session:stopped");
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

    await expect(runtime.actions.selectSession("session:slow")).resolves.toBeUndefined();

    expect(store.getState().currentSessionId).toBe("session:slow");
    expect(store.getState().activeStreamSessionIds).toEqual([]);
    expect(store.getState().isStreaming).toBe(false);
    expect(store.getState().sessionActivity).toMatchObject({
      level: "error",
      title: "历史读取超时",
      event: "session_history_load_failed",
    });
  });

  it("keeps the workspace interactive and reports an error when session creation fails", async () => {
    vi.useRealTimers();
    api.createSession.mockRejectedValue(new Error("backend offline"));
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

  it("sends DeepSeek thinking controls for the system default chat model", async () => {
    vi.useRealTimers();
    api.streamChat.mockResolvedValue({ terminalEvent: "done" });
    api.listSessions.mockResolvedValue([{
      id: "session:deepseek",
      title: "DeepSeek",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
    }]);
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:deepseek",
      modelProviderConfig: {
        provider: "deepseek",
        model: "deepseek-v4-pro",
        base_url: "https://api.deepseek.com/v1",
        credential_ref: "provider:deepseek:primary",
        api_key_configured: true,
        fallback_provider: "",
        fallback_model: "",
        fallback_base_url: "",
        fallback_credential_ref: "",
        fallback_api_key_configured: false,
        supported_providers: {},
        provider_catalog: {
          authority: "runtime.model_provider_catalog",
          default_provider: "deepseek",
          default_model: "deepseek-v4-pro",
          providers: {},
          credential_refs: [],
        },
        authority: "runtime.model_provider",
      },
      deepSeekThinkingEnabled: true,
    });
    const runtime = new WorkspaceRuntime(store);

    await runtime.actions.sendMessage("需要深度审查这一段");

    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[0]?.[0]?.model_selection).toEqual({
      selection_id: "system-default",
      provider: "deepseek",
      model: "deepseek-v4-pro",
      base_url: "https://api.deepseek.com/v1",
      credential_ref: "provider:deepseek:primary",
      thinking_mode: "enabled",
      reasoning_effort: "max",
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
          src: "/souls/generated/chat-turn.png",
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
      taskGraphRunMonitor: { runtime: { status: "running" } } as never,
      soulImageAssetConfig: {
        configured: true,
        base_url: "https://api.openai.com/v1",
        model: "gpt-image-2",
        api_key_present: true,
        public_dir: "D:/AI应用/langchain-agent/frontend/public/souls/generated",
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
    expect(store.getState().taskGraphRunMonitor).toBeNull();
    expect(store.getState().messages.at(-1)?.image?.src).toBe("/souls/generated/chat-turn.png");
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
      soulImageAssetConfig: {
        configured: true,
        base_url: "https://api.openai.com/v1",
        model: "gpt-image-2",
        api_key_present: true,
        public_dir: "D:/AI应用/langchain-agent/frontend/public/souls/generated",
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

  it("does not leak a selected task into ordinary main-chat turns", async () => {
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
    expect(api.streamChat.mock.calls[0]?.[0]?.task_selection).toBeUndefined();
    expect(api.streamChat.mock.calls[0]?.[0]?.runtime_mode).toBe("role");
  });

  it("keeps task selection after chat stream start events", async () => {
    vi.useRealTimers();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("harness_run_started", {
        task_run: {
          task_run_id: "turnrun:abc",
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
    expect(api.streamChat.mock.calls[0]?.[0]?.task_selection).toBeUndefined();
    expect(api.streamChat.mock.calls[1]?.[0]?.task_selection).toBeUndefined();
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
        task_run_id: "taskrun:abc",
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
        task_run_id: "taskrun:abc",
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
        task_run_id: "turnrun:abc",
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
      "正式任务已创建",
      "任务待办已建立",
      "任务已转入后台执行",
    ]);
    expect(assistant?.runtimeProgress?.at(-1)).toMatchObject({
      level: "waiting",
      statusText: "等待",
      taskRunId: "taskrun:abc",
    });
    expect(assistant?.stageStatus).toBe("任务已转入后台执行");
  });

  it("attaches tool runtime signals to the assistant task flow", () => {
    let transition = startStreamingTurn(getDefaultState(), "执行前端任务");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_loop_event", {
      event: {
        event_id: "rtevt:tool-request",
        task_run_id: "taskrun:abc",
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
        task_run_id: "taskrun:abc",
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
    expect(assistant?.runtimeProgress?.map((entry) => entry.kind)).toEqual(["tool", "tool"]);
    expect(assistant?.runtimeProgress?.[1]).toMatchObject({
      statusText: "已完成",
      toolName: "write_file",
      artifacts: [{ label: "产物", path: "docs/plan.md" }],
    });
  });

  it("does not attach permission gate checks to the assistant task flow", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "harness_loop_event", {
      event: {
        event_id: "rtevt:gate",
        task_run_id: "taskrun:abc",
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
    expect(assistant?.stageStatus).toBe("准备执行");
    expect(assistant?.runtimeProgress).toEqual([]);
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
    expect(assistant?.stageStatus).toBe("接收请求");
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

    await runtime.actions.selectSession("session:timeline");

    const assistant = store.getState().messages.find((message) => message.role === "assistant" && message.content === "任务已接管");
    expect(assistant?.runtimeAttachments?.[0]).toMatchObject({
      task_run_id: "taskrun:turn:session:timeline:1:abc",
      status: "completed",
    });
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
