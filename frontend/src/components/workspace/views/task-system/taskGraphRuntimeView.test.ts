import { describe, expect, it } from "vitest";

import { buildTaskGraphSchedulerSummary, schedulerStateFromTrace } from "./taskGraphRuntimeView";

describe("taskGraphRuntimeView", () => {
  it("extracts scheduler state from coordination run diagnostics", () => {
    const raw = {
      authority: "task_system.task_graph_scheduler_state",
      graph_id: "graph.test",
      mode: "shadow",
      ready_node_ids: ["draft"],
      blocked_node_ids: ["review"],
      running_node_ids: [],
      completed_node_ids: ["plan"],
      failed_node_ids: [],
      phase_states: [{ phase_id: "phase.write", status: "active", node_ids: ["draft", "review"] }],
      node_states: [],
      edge_states: [],
      diagnostics: {
        active_phase_ids: ["phase.write"],
        active_sequence_by_phase: { "phase.write": 2 },
        phase_count: 1,
        node_count: 3,
        edge_count: 2,
      },
    };
    const state = schedulerStateFromTrace({
      coordination_runs: [
        {
          diagnostics: {
            task_graph_scheduler_state: raw,
          },
        },
      ],
    });
    const summary = buildTaskGraphSchedulerSummary(state);

    expect(summary.available).toBe(true);
    expect(summary.graph_id).toBe("graph.test");
    expect(summary.ready_node_ids).toEqual(["draft"]);
    expect(summary.blocked_node_ids).toEqual(["review"]);
    expect(summary.active_phase_ids).toEqual(["phase.write"]);
    expect(summary.active_sequence_by_phase).toEqual({ "phase.write": 2 });
  });

  it("extracts nested scheduler state and lets top-level diagnostics override it", () => {
    const nested = {
      authority: "task_system.task_graph_scheduler_state",
      graph_id: "graph.nested",
      mode: "shadow",
      ready_node_ids: ["outline"],
      diagnostics: { active_phase_ids: ["phase.plan"] },
    };
    const topLevel = {
      authority: "task_system.task_graph_scheduler_state",
      graph_id: "graph.top",
      mode: "shadow",
      ready_node_ids: ["draft"],
      diagnostics: { active_phase_ids: ["phase.write"] },
    };

    const state = schedulerStateFromTrace({
      coordination_runs: [
        {
          diagnostics: {
            langgraph_runtime_state: {
              task_graph_scheduler_state: nested,
            },
            task_graph_scheduler_state: topLevel,
          },
        },
      ],
    });
    const summary = buildTaskGraphSchedulerSummary(state);

    expect(summary.graph_id).toBe("graph.top");
    expect(summary.ready_node_ids).toEqual(["draft"]);
    expect(summary.active_phase_ids).toEqual(["phase.write"]);
  });

  it("falls back to unavailable summary for missing scheduler state", () => {
    const summary = buildTaskGraphSchedulerSummary({});

    expect(summary.available).toBe(false);
    expect(summary.ready_node_ids).toEqual([]);
    expect(summary.phase_count).toBe(0);
  });
});
