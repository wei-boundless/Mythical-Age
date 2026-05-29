import { describe, expect, it } from "vitest";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { emptyTaskGraphDraftV2 } from "./taskGraphDraftV2";
import {
  buildTaskGraphLoopInputPatch,
  resolvedTaskGraphLoopInitialInputs,
} from "./taskGraphLoopConfig";

function draft(): TaskGraphDraftV2 {
  return {
    ...emptyTaskGraphDraftV2(),
    graph_id: "graph.generic.batch_cycle",
    title: "通用批次任务图",
    contract_bindings: {
      unit_batch: {
        unit_kind: "record",
        unit_label_zh: "记录",
        requested_count: 50,
        batch_size: 5,
      },
    },
    loop_frames: [
      {
        frame_id: "loop.records",
        scope_id: "loop.records",
        title: "记录批次循环",
        kind: "bounded_metric_iteration",
        entry_node_id: "produce",
        router_node_id: "router",
        continue_node_id: "produce",
        exit_node_id: "exit",
        initial_inputs: {
          target_group_count: 5,
          units_per_group: 10,
          target_unit_count: 50,
          units_per_batch: 5,
          unit_target_measure: 20,
          group_target_measure: 200,
          target_measure_units: 1000,
        },
      },
    ],
  };
}

function firstFrameInputs(patch: Partial<TaskGraphDraftV2>) {
  return patch.loop_frames?.[0]?.initial_inputs as Record<string, unknown>;
}

describe("taskGraphLoopConfig", () => {
  it("stores graph-level batch size into loop_frames and unit batch contract summary", () => {
    const patch = buildTaskGraphLoopInputPatch(draft(), "units_per_batch", 8);
    const initialInputs = firstFrameInputs(patch);
    const unitBatch = patch.contract_bindings?.unit_batch as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.units_per_batch).toBe(8);
    expect(initialInputs.target_group_count).toBe(5);
    expect(initialInputs.units_per_group).toBe(10);
    expect(initialInputs.target_unit_count).toBe(50);
    expect(initialInputs.group_target_measure).toBe(200);
    expect(initialInputs.target_measure_units).toBe(1000);
    expect(unitBatch.batch_size).toBe(8);
    expect(unitBatch.requested_count).toBe(50);
    expect(unitBatch.target_unit_count).toBe(50);
    expect(unitBatch.unit_kind).toBe("record");
    expect(unitBatch.source).toBe("graph.loop_frames.initial_inputs");
    expect(lengthBudget.enabled).toBe(true);
    expect(lengthBudget.measurement_mode).toBe("text_units");
    expect(lengthBudget.unit_kind).toBe("record");
    expect(lengthBudget.batch_unit_count).toBe(8);
    expect(lengthBudget.target_units).toBe(160);
    expect((lengthBudget.repair_policy as Record<string, unknown>).mode).toBe("expand_or_split");
  });

  it("uses generic one-unit defaults when no graph loop frame exists", () => {
    const minimal = {
      ...emptyTaskGraphDraftV2(),
      loop_frames: [
        {
          frame_id: "loop.units",
          initial_inputs: {
            units_per_batch: 5,
          },
        },
      ],
    };

    expect(resolvedTaskGraphLoopInitialInputs(emptyTaskGraphDraftV2())).toMatchObject({
      target_group_count: 1,
      units_per_group: 1,
      target_unit_count: 1,
      units_per_batch: 1,
      unit_target_measure: 0,
      group_target_measure: 0,
      target_measure_units: 0,
    });

    const patch = buildTaskGraphLoopInputPatch(minimal, "units_per_batch", 8);
    const initialInputs = firstFrameInputs(patch);

    expect(initialInputs.target_unit_count).toBe(1);
    expect(initialInputs.target_measure_units).toBe(0);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).batch_size).toBe(8);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).requested_count).toBe(1);
    expect(patch.contract_bindings?.runtime).toBeUndefined();
  });

  it("recalculates dependent scale fields when units per group changes", () => {
    const patch = buildTaskGraphLoopInputPatch(draft(), "units_per_group", 8);
    const initialInputs = firstFrameInputs(patch);
    const unitBatch = patch.contract_bindings?.unit_batch as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.units_per_group).toBe(8);
    expect(initialInputs.target_unit_count).toBe(40);
    expect(initialInputs.group_target_measure).toBe(160);
    expect(initialInputs.target_measure_units).toBe(800);
    expect(unitBatch.requested_count).toBe(40);
    expect(unitBatch.group_target_measure).toBe(160);
    expect(lengthBudget.target_units).toBe(100);
  });

  it("creates a formal loop frame when the draft has no loop frame yet", () => {
    const emptyLoop = {
      ...emptyTaskGraphDraftV2(),
    };

    const resolved = resolvedTaskGraphLoopInitialInputs(emptyLoop);
    expect(resolved.target_group_count).toBe(1);
    expect(resolved.units_per_batch).toBe(1);

    const patch = buildTaskGraphLoopInputPatch(emptyLoop, "units_per_batch", 8);
    expect(patch.metadata).toBeUndefined();
    expect(patch.loop_frames?.[0]?.frame_id).toBe("loop.default");
    expect(firstFrameInputs(patch).units_per_batch).toBe(8);
  });
});
