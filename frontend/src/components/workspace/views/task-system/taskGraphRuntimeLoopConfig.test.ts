import { describe, expect, it } from "vitest";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { emptyTaskGraphDraftV2 } from "./taskGraphDraftV2";
import {
  buildTaskGraphRuntimeLoopInputPatch,
  resolvedTaskGraphRuntimeLoopInitialInputs,
} from "./taskGraphRuntimeLoopConfig";

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
    metadata: {
      runtime_loop_policy: {
        enabled: true,
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
    },
  };
}

describe("taskGraphRuntimeLoopConfig", () => {
  it("stores graph-level batch size into runtime loop policy and unit batch contract summary", () => {
    const patch = buildTaskGraphRuntimeLoopInputPatch(draft(), "units_per_batch", 8);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;
    const unitBatch = patch.contract_bindings?.unit_batch as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.units_per_batch).toBe(8);
    expect(initialInputs.target_group_count).toBe(5);
    expect(initialInputs.units_per_group).toBe(10);
    expect(initialInputs.target_unit_count).toBe(50);
    expect(initialInputs.group_target_measure).toBe(200);
    expect(initialInputs.target_measure_units).toBe(1000);
    expect(initialInputs.chapters_per_round).toBeUndefined();
    expect(initialInputs.chapter_batch_size).toBeUndefined();
    expect(unitBatch.batch_size).toBe(8);
    expect(unitBatch.requested_count).toBe(50);
    expect(unitBatch.unit_kind).toBe("record");
    expect(unitBatch.source).toBe("metadata.runtime_loop_policy.initial_inputs");
    expect(lengthBudget.enabled).toBe(true);
    expect(lengthBudget.measurement_mode).toBe("text_units");
    expect(lengthBudget.unit_kind).toBe("record");
    expect(lengthBudget.batch_unit_count).toBe(8);
    expect(lengthBudget.target_units).toBe(160);
    expect((lengthBudget.repair_policy as Record<string, unknown>).mode).toBe("expand_or_split");
  });

  it("uses generic one-unit defaults when no graph contract exists", () => {
    const minimal = {
      ...emptyTaskGraphDraftV2(),
      metadata: {
        runtime_loop_policy: {
          initial_inputs: {
            units_per_batch: 5,
          },
        },
      },
    };

    expect(resolvedTaskGraphRuntimeLoopInitialInputs(emptyTaskGraphDraftV2())).toMatchObject({
      target_group_count: 1,
      units_per_group: 1,
      target_unit_count: 1,
      units_per_batch: 1,
      unit_target_measure: 0,
      group_target_measure: 0,
      target_measure_units: 0,
    });

    const patch = buildTaskGraphRuntimeLoopInputPatch(minimal, "units_per_batch", 8);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;

    expect(initialInputs.target_unit_count).toBe(1);
    expect(initialInputs.target_measure_units).toBe(0);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).batch_size).toBe(8);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).requested_count).toBe(1);
    expect(patch.contract_bindings?.runtime).toBeUndefined();
  });

  it("recalculates dependent scale fields when units per group changes", () => {
    const patch = buildTaskGraphRuntimeLoopInputPatch(draft(), "units_per_group", 8);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;
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

  it("migrates legacy chapter loop inputs into generic fields without writing them back", () => {
    const legacy = {
      ...emptyTaskGraphDraftV2(),
      contract_bindings: {
        unit_batch: {
          unit_kind: "chapter",
          requested_count: 500,
          batch_size: 10,
        },
      },
      metadata: {
        runtime_loop_policy: {
          initial_inputs: {
            target_volumes: 5,
            chapters_per_volume: 100,
            target_chapters: 500,
            chapters_per_round: 10,
            chapter_batch_size: 10,
            chapter_target_words: 2000,
            volume_target_words: 200000,
            target_words: 1000000,
          },
        },
      },
    };

    const resolved = resolvedTaskGraphRuntimeLoopInitialInputs(legacy);
    expect(resolved).toMatchObject({
      target_group_count: 5,
      units_per_group: 100,
      target_unit_count: 500,
      units_per_batch: 10,
      unit_target_measure: 2000,
      group_target_measure: 200000,
      target_measure_units: 1000000,
    });

    const patch = buildTaskGraphRuntimeLoopInputPatch(legacy, "units_per_batch", 8);
    const initialInputs = (patch.metadata?.runtime_loop_policy as Record<string, unknown>).initial_inputs as Record<string, unknown>;
    expect(initialInputs.chapters_per_round).toBeUndefined();
    expect(initialInputs.chapter_batch_size).toBeUndefined();
    expect(initialInputs.units_per_batch).toBe(8);
  });
});
