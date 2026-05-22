import { beforeEach, describe, expect, it, vi } from "vitest";

import { createStore, getDefaultState } from "./core";
import { WorkspaceRuntime } from "./runtime";
import type { StoreState } from "./types";

const api = vi.hoisted(() => ({
  getGlobalRuntimeMonitor: vi.fn(),
  getOrchestrationRuntimeLoopSessionLiveMonitor: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessionTokens: vi.fn(),
  getTaskGraphRunMonitor: vi.fn(),
  listSessions: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  continueOrchestrationCurrentStage: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  evaluateTaskGraphRunMonitor: vi.fn(),
  getCoordinationRunTaskGraphMonitor: vi.fn(),
  getGlobalRuntimeMonitor: api.getGlobalRuntimeMonitor,
  getRuntimeMonitorEventStreamUrl: vi.fn(() => "http://127.0.0.1:8002/api/orchestration/runtime-loop/monitor-events"),
  getModelProviderConfig: vi.fn(),
  getSoulImageAssetConfig: vi.fn(),
  getWorkspaceContext: vi.fn(),
  getTaskGraphRunMonitor: api.getTaskGraphRunMonitor,
  getTaskGraphRunMonitorDecisions: vi.fn(),
  getOrchestrationRuntimeLoopTaskRunLiveMonitor: vi.fn(),
  getOrchestrationRuntimeLoopSessionLiveMonitor: api.getOrchestrationRuntimeLoopSessionLiveMonitor,
  getRagMode: vi.fn(),
  getSessionHistory: api.getSessionHistory,
  getSessionTokens: api.getSessionTokens,
  listSessions: api.listSessions,
  listSkills: vi.fn(),
  loadFile: vi.fn(),
  renameSession: vi.fn(),
  resolveRuntimeLoopTaskRunApproval: vi.fn(),
  resumeOrchestrationTaskGraphRun: vi.fn(),
  saveFile: vi.fn(),
  setRagMode: vi.fn(),
  stopOrchestrationTaskRun: vi.fn(),
  streamChat: api.streamChat,
  switchSoulSystemSeed: vi.fn(),
  taskGraphRunIdFromLiveMonitor: vi.fn(),
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

describe("WorkspaceRuntime task graph monitor polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.getOrchestrationRuntimeLoopSessionLiveMonitor.mockReset();
    api.getOrchestrationRuntimeLoopSessionLiveMonitor.mockResolvedValue({ monitor: null });
    api.getSessionHistory.mockReset();
    api.getSessionHistory.mockResolvedValue({ messages: [] });
    api.getSessionTokens.mockReset();
    api.getSessionTokens.mockResolvedValue(null);
    api.getTaskGraphRunMonitor.mockReset();
    api.getTaskGraphRunMonitor.mockResolvedValue({
      authority: "task_graph.run_monitor",
      task_run_id: "taskrun:bound",
      coordination_run_id: "coordrun:bound",
      graph: { graph_id: "graph:test", title: "Test", node_count: 1, edge_count: 0 },
      runtime: { status: "running", active_node_id: "draft", event_count: 1, updated_at: 1 },
      topology: { nodes: [], edges: [] },
      state: {},
      artifacts: [],
      memory_operations: [],
      stage_results: [],
      health: { valid: true, issues: [] },
    });
    api.listSessions.mockReset();
    api.listSessions.mockResolvedValue([]);
    api.streamChat.mockReset();
    api.streamChat.mockImplementation(async (_payload, handlers) => {
      handlers.onEvent("done", { content: "done" });
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

  it("keeps polling a bound TaskGraph run when the interaction dock is closed", async () => {
    const store = createStore(getDefaultState());
    const runtime = new WorkspaceRuntime(store);

    runtime.actions.bindTaskGraphMonitorRun({
      task_run_id: "taskrun:bound",
      graph_id: "graph:test",
    });
    await vi.runOnlyPendingTimersAsync();
    runtime.actions.setTaskGraphRunInteractionOpen(false);
    await vi.advanceTimersByTimeAsync(1200);

    expect(api.getTaskGraphRunMonitor).toHaveBeenCalledTimes(3);
    expect(store.getState().taskGraphMonitorBinding?.task_run_id).toBe("taskrun:bound");
    expect(store.getState().taskGraphBoundRunMonitor?.runtime?.active_node_id).toBe("draft");
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
    const monitor = {
      authority: "runtime_live_monitor.global",
      summary: { total: 3, running: 3, waiting: 0, completed: 0, failed: 0 },
      task_runs: [
        {
          task_run_id: "taskrun:agent",
          session_id: "session",
          task_id: "taskinst:turn:session:world_design",
          title: "world_design",
          status: "running",
          terminal_reason: "",
          created_at: 1,
          updated_at: 1,
          elapsed_seconds: 1,
          latest_event_type: "executor_started",
          latest_event_at: 1,
          event_count: 1,
          coordination_run_id: "",
          coordination_status: "",
          graph_id: "",
          active_node_id: "",
          project_id: "",
          project_title: "",
          project_runtime_status: null,
          has_coordination: false,
        },
        {
          task_run_id: "taskrun:module",
          session_id: "session",
          task_id: "task_graph.graph_module.graph.writing.modular_novel.design_init",
          title: "design_init",
          status: "running",
          terminal_reason: "",
          created_at: 1,
          updated_at: 1,
          elapsed_seconds: 1,
          latest_event_type: "handoff_envelope_created",
          latest_event_at: 1,
          event_count: 1,
          coordination_run_id: "coordrun:module",
          coordination_status: "running",
          graph_id: "graph.writing.modular_novel.design_init",
          active_node_id: "world_design",
          project_id: "project",
          project_title: "洪荒时代",
          project_runtime_status: null,
          has_coordination: true,
        },
        {
          task_run_id: "taskrun:master",
          session_id: "session",
          task_id: "graph.writing.modular_novel.master",
          title: "洪荒时代",
          status: "running",
          terminal_reason: "",
          created_at: 1,
          updated_at: 1,
          elapsed_seconds: 1,
          latest_event_type: "coordination_graph_module_imported_run_started",
          latest_event_at: 1,
          event_count: 1,
          coordination_run_id: "coordrun:master",
          coordination_status: "running",
          graph_id: "graph.writing.modular_novel.master",
          active_node_id: "graph_module.design_init",
          project_id: "project",
          project_title: "洪荒时代",
          project_runtime_status: null,
          has_coordination: true,
        },
      ],
      updated_at: 1,
    };

    runtimeHarness.applyGlobalRuntimeMonitorSnapshot(monitor, { detailTaskRunId: "taskrun:agent" });

    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("taskrun:master");

    runtimeHarness.selectGlobalRuntimeMonitorTaskRun("taskrun:module");

    expect(store.getState().globalRuntimeMonitorSelectedTaskRunId).toBe("");
  });

  it("sends DeepSeek thinking controls for the system default chat model", async () => {
    vi.useRealTimers();
    api.streamChat.mockResolvedValue(undefined);
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
    });
    const store = createStore<StoreState>({
      ...getDefaultState(),
      currentSessionId: "session:image",
      selectedChatModelId: "openai::gpt-image-2",
      selectedChatMode: "image",
      taskGraphLiveMonitor: { status: "running", has_coordination: true } as never,
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

    expect(api.getOrchestrationRuntimeLoopSessionLiveMonitor).not.toHaveBeenCalled();
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
});
