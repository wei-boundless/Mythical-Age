import { describe, expect, it } from "vitest";

import { applyRuntimeMonitorSnapshot, createRuntimeMonitorState, selectRuntimeMonitorTaskInstance } from "./reducer";

function item(patch: Record<string, unknown>) {
  return {
    task_run_id: "taskrun:test",
    task_instance_id: "taskrun:test",
    root_task_run_id: "taskrun:test",
    kind: "agent_run",
    session_id: "session:test",
    task_id: "task:turn:session:test:1",
    execution_runtime_kind: "single_agent_task",
    title: "持续处理",
    status: "running",
    terminal_reason: "",
    lifecycle: "running",
    bucket: "running",
    resource_class: "dynamic",
    started_at: 1,
    duration_seconds: 1,
    elapsed_seconds: 1,
    latest_event_type: "step_summary_recorded",
    latest_event_at: 2,
    event_count: 1,
    graph_id: "",
    active_node_id: "",
    project_id: "",
    project_title: "",
    project_runtime_status: null,
    has_graph_run: false,
    route: { kind: "agent_runtime_run" },
    ...patch,
  };
}

function monitor(items: Array<ReturnType<typeof item>>, revision = "rtmon:10:test") {
  const buckets = {
    running: items.filter((candidate) => candidate.bucket === "running"),
    completed: items.filter((candidate) => candidate.bucket === "completed"),
    failed: items.filter((candidate) => candidate.bucket === "failed"),
    diagnostics: items.filter((candidate) => candidate.bucket === "diagnostics"),
  };
  return {
    authority: "runtime_monitor.v1",
    scope: "global",
    revision,
    summary: {
      total: items.length,
      running: buckets.running.length,
      completed: buckets.completed.length,
      failed: buckets.failed.length,
      diagnostics: buckets.diagnostics.length,
    },
    buckets,
    items,
    task_runs: items,
    updated_at: 10,
  };
}

describe("runtime monitor reducer", () => {
  it("uses task_instance_id as the selection and instance-cache key", () => {
    const graphItem = item({
      task_run_id: "taskrun:graph-root",
      task_instance_id: "grun:graph",
      root_task_run_id: "taskrun:graph-root",
      kind: "task_graph",
      graph_run_id: "grun:graph",
      graph_harness_config_id: "ghcfg:graph",
      graph_id: "graph:test",
      graph_status: { graph_lifecycle: "running", active_node_id: "draft" },
      route: { kind: "task_graph_run" },
    });

    const state = applyRuntimeMonitorSnapshot(createRuntimeMonitorState(), monitor([graphItem]));

    expect(state.selectedTaskInstanceId).toBe("grun:graph");
    expect(state.selectedTaskRunId).toBe("taskrun:graph-root");
    expect(state.instancesById["grun:graph"]?.graphStatus).toMatchObject({ active_node_id: "draft" });
  });

  it("keeps node runtimes inside the graph task instance instead of top-level rows", () => {
    const graphItem = item({
      task_run_id: "taskrun:graph-root",
      task_instance_id: "grun:graph",
      kind: "task_graph",
      graph_run_id: "grun:graph",
      child_runtime_refs: [{ task_run_id: "gtask:node", node_id: "draft" }],
      route: { kind: "task_graph_run" },
    });
    const state = applyRuntimeMonitorSnapshot(createRuntimeMonitorState(), monitor([graphItem]));

    expect(Object.keys(state.instancesById)).toEqual(["grun:graph"]);
    expect(state.instancesById["grun:graph"]?.childRuntimeRefs).toEqual([{ task_run_id: "gtask:node", node_id: "draft" }]);
  });

  it("selects by task run id but stores the canonical task instance id", () => {
    const graphItem = item({
      task_run_id: "taskrun:graph-root",
      task_instance_id: "grun:graph",
      kind: "task_graph",
      graph_run_id: "grun:graph",
      route: { kind: "task_graph_run" },
    });
    const state = applyRuntimeMonitorSnapshot(createRuntimeMonitorState(), monitor([graphItem]));
    const selected = selectRuntimeMonitorTaskInstance(state, "taskrun:graph-root");

    expect(selected.selectedTaskInstanceId).toBe("grun:graph");
    expect(selected.selectedTaskRunId).toBe("taskrun:graph-root");
  });
});
