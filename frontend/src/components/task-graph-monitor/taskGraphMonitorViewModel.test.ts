import { describe, expect, it } from "vitest";

import type { TaskGraphRunMonitorView } from "@/lib/api";
import { buildTaskGraphMonitorViewModel } from "./taskGraphMonitorViewModel";

function monitorView(): TaskGraphRunMonitorView {
  return {
    authority: "task_graph.run_monitor",
    source: "coordination_run",
    session_id: "session:test",
    task_run_id: "taskrun:test",
    coordination_run_id: "coordrun:test",
    graph: {
      graph_id: "graph.writing.simple",
      title: "写作组简易长篇小说任务图",
      node_count: 3,
      edge_count: 2,
    },
    runtime: {
      status: "running",
      terminal_status: "",
      terminal_reason: "",
      failure: {
        message: "",
        detail: "",
        code: "",
        provider: "",
        model: "",
        source: "",
        step_id: "",
        observation_ref: "",
      },
      active_node_id: "outline",
      active_task_ref: "task:outline",
      last_event_offset: 12,
      event_count: 14,
      checkpoint_ref: "ckpt:coord",
      checkpoint_updated_at: 1,
      task_checkpoint_ref: "ckpt:task",
      updated_at: 2,
    },
    topology: {
      nodes: [
        { node_id: "world", title: "世界观", node_type: "task", task_id: "task:world", agent_id: "agent:world", phase_id: "", sequence_index: 1, status: "completed", artifact_refs: [], last_result_ref: "" },
        { node_id: "outline", title: "大纲", node_type: "task", task_id: "task:outline", agent_id: "agent:outline", phase_id: "", sequence_index: 2, status: "running", artifact_refs: [], last_result_ref: "" },
        { node_id: "memory", title: "记忆库", node_type: "memory", task_id: "", agent_id: "memory", phase_id: "", sequence_index: 3, status: "ready", artifact_refs: [], last_result_ref: "" },
      ],
      edges: [
        { edge_id: "edge:world-outline", source_node_id: "world", target_node_id: "outline", edge_type: "handoff", payload_contract_id: "contract:world-outline", status: "running" },
        { edge_id: "edge:outline-memory", source_node_id: "outline", target_node_id: "memory", edge_type: "memory_write", payload_contract_id: "contract:outline-memory", status: "ready" },
      ],
    },
    state: {
      node_statuses: { world: "completed", outline: "running", memory: "ready" },
      edge_statuses: {},
      ready_node_ids: ["memory"],
      running_node_ids: ["outline"],
      completed_node_ids: ["world"],
      failed_node_ids: [],
      blocked_node_ids: [],
      waiting_node_ids: [],
    },
    artifacts: [],
    memory_operations: [
      { operation: "read", node_id: "outline", status: "completed", refs: ["wm:world"] },
    ],
    stage_results: [],
    current_stage_execution_request: {},
    health: { valid: true, issues: [] },
  };
}

describe("buildTaskGraphMonitorViewModel", () => {
  it("renders only realtime communication edges from canonical monitor", () => {
    const model = buildTaskGraphMonitorViewModel(monitorView());

    expect(model.hasSignal).toBe(true);
    expect(model.graphId).toBe("graph.writing.simple");
    expect(model.nodes.map((node) => node.id)).toEqual(["world", "outline", "memory"]);
    expect(model.edges.map((edge) => `${edge.from}->${edge.to}`)).toEqual([
      "world->outline",
    ]);
    expect(model.activeNodeId).toBe("outline");
    expect(model.memoryOperations[0].refs).toEqual(["wm:world"]);
  });

  it("surfaces project progress and supervision metadata", () => {
    const monitor = monitorView();
    monitor.project = {
      project_id: "project:honghuang",
      project_title: "洪荒时代",
      graph_id: "graph.writing.simple",
    };
    monitor.progress = {
      metric_label: "words",
      target_metric_total: 1000000,
      completed_metric_total: 12000,
      committed_unit_count: 3,
      last_committed_unit_index: 3,
      remaining_metric_total: 988000,
    };
    monitor.supervision = {
      project_runtime_status: "watching",
      active_run_status: "running",
      latest_artifact_root: "output/novel_artifacts/simple_novel/runs/demo",
      latest_event_at: 100,
      last_effective_output_at: 98,
      latest_record: { repair_action: "none" },
      record_count: 2,
    };

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.projectId).toBe("project:honghuang");
    expect(model.completedMetricTotal).toBe(12000);
    expect(model.remainingMetricTotal).toBe(988000);
    expect(model.projectRuntimeStatus).toBe("watching");
  });

  it("keeps completed static topology edges out of the realtime canvas", () => {
    const monitor = monitorView();
    monitor.topology.edges = monitor.topology.edges.map((edge) => ({ ...edge, status: "completed" }));

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.edgeCount).toBe(2);
    expect(model.edges).toEqual([]);
  });

  it("keeps blocked non-working topology edges out of the realtime canvas", () => {
    const monitor = monitorView();
    monitor.topology.edges = monitor.topology.edges.map((edge) => ({ ...edge, status: "blocked" }));

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.edgeCount).toBe(2);
    expect(model.edges).toEqual([]);
  });

  it("does not synthesize fallback edges when monitor has no valid topology edges", () => {
    const monitor = monitorView();
    monitor.topology.edges = [
      { edge_id: "bad", source_node_id: "world", target_node_id: "missing", edge_type: "handoff", payload_contract_id: "", status: "idle" },
    ];

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.edges).toEqual([]);
    expect(model.edgeCount).toBe(2);
  });

  it("surfaces failure diagnostics from monitor runtime payload", () => {
    const monitor = monitorView();
    monitor.runtime.status = "failed";
    monitor.runtime.terminal_reason = "executor_failed";
    monitor.runtime.failure = {
      message: "模型配置有误，请检查提供商和密钥设置。",
      detail: "401 Unauthorized from upstream provider",
      code: "configuration",
      provider: "deepseek",
      model: "deepseek-v4-pro",
      source: "runtime_directive_executor",
      step_id: "understand_request",
      observation_ref: "rtobs:test",
    };

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.failureMessage).toBe("模型配置有误，请检查提供商和密钥设置。");
    expect(model.failureDetail).toContain("401 Unauthorized");
    expect(model.failureProvider).toBe("deepseek");
  });

  it("surfaces temporal execution boundary fields", () => {
    const monitor = monitorView();
    monitor.temporal = {
      active_node_id: "outline",
      active_activation_id: "activation:outline:001",
      active_execution_permit_id: "permit:outline:001",
      active_request_id: "request:outline:001",
      boundary_valid: true,
      authority: "task_graph.temporal_monitor_view",
      violations: [
        {
          severity: "error",
          code: "node_running_without_execution_permit",
          message: "节点运行没有执行许可。",
          target_id: "writer",
        },
      ],
    };

    const model = buildTaskGraphMonitorViewModel(monitor);

    expect(model.temporalActiveNodeId).toBe("outline");
    expect(model.temporalActiveActivationId).toBe("activation:outline:001");
    expect(model.temporalActiveExecutionPermitId).toBe("permit:outline:001");
    expect(model.temporalActiveRequestId).toBe("request:outline:001");
    expect(model.temporalBoundaryValid).toBe(true);
    expect(model.temporalViolations[0]).toMatchObject({
      code: "node_running_without_execution_permit",
      targetId: "writer",
    });
  });
});
