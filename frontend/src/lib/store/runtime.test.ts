import { beforeEach, describe, expect, it, vi } from "vitest";

import { createStore, getDefaultState } from "./core";
import { WorkspaceRuntime } from "./runtime";

const api = vi.hoisted(() => ({
  getTaskGraphRunMonitor: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  continueOrchestrationCurrentStage: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  evaluateTaskGraphRunMonitor: vi.fn(),
  getCoordinationRunTaskGraphMonitor: vi.fn(),
  getGlobalRuntimeMonitor: vi.fn(),
  getRuntimeMonitorEventStreamUrl: vi.fn(() => "http://127.0.0.1:8002/api/orchestration/runtime-loop/monitor-events"),
  getModelProviderConfig: vi.fn(),
  getSoulImageAssetConfig: vi.fn(),
  getWorkspaceContext: vi.fn(),
  getTaskGraphRunMonitor: api.getTaskGraphRunMonitor,
  getTaskGraphRunMonitorDecisions: vi.fn(),
  getOrchestrationRuntimeLoopTaskRunLiveMonitor: vi.fn(),
  getOrchestrationRuntimeLoopSessionLiveMonitor: vi.fn(),
  getRagMode: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessionTokens: vi.fn(),
  listSessions: vi.fn(),
  listSkills: vi.fn(),
  loadFile: vi.fn(),
  renameSession: vi.fn(),
  resolveRuntimeLoopTaskRunApproval: vi.fn(),
  resumeOrchestrationTaskGraphRun: vi.fn(),
  saveFile: vi.fn(),
  setRagMode: vi.fn(),
  stopOrchestrationTaskRun: vi.fn(),
  streamChat: vi.fn(),
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
});
