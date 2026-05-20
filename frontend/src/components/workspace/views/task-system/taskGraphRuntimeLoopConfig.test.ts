import { describe, expect, it } from "vitest";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { emptyTaskGraphDraftV2 } from "./taskGraphDraftV2";
import { buildTaskGraphRuntimeLoopInputPatch } from "./taskGraphRuntimeLoopConfig";

function draft(): TaskGraphDraftV2 {
  return {
    ...emptyTaskGraphDraftV2(),
    graph_id: "graph.writing.modular_novel.chapter_cycle",
    title: "章节批次创作任务图",
    contract_bindings: {
      unit_batch: {
        unit_kind: "chapter",
        requested_count: 50,
        batch_size: 10,
      },
    },
    metadata: {
      runtime_loop_policy: {
        enabled: true,
        initial_inputs: {
          target_volumes: 1,
          chapters_per_volume: 50,
          target_chapters: 50,
          chapters_per_round: 10,
          chapter_batch_size: 10,
          chapter_target_words: 2000,
          volume_target_words: 100000,
          target_words: 100000,
        },
      },
    },
  };
}

describe("taskGraphRuntimeLoopConfig", () => {
  it("stores graph-level batch size into runtime loop policy and unit batch contract summary", () => {
    const patch = buildTaskGraphRuntimeLoopInputPatch(draft(), "chapters_per_round", 8);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;
    const unitBatch = patch.contract_bindings?.unit_batch as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.chapters_per_round).toBe(8);
    expect(initialInputs.chapter_batch_size).toBe(8);
    expect(unitBatch.batch_size).toBe(8);
    expect(unitBatch.requested_count).toBe(50);
    expect(unitBatch.source).toBe("metadata.runtime_loop_policy.initial_inputs");
    expect(lengthBudget.enabled).toBe(true);
    expect(lengthBudget.measurement_mode).toBe("text_units");
    expect(lengthBudget.unit_kind).toBe("chapter");
    expect(lengthBudget.batch_unit_count).toBe(8);
    expect(lengthBudget.target_units).toBe(100000);
    expect((lengthBudget.repair_policy as Record<string, unknown>).mode).toBe("expand_or_split");
  });

  it("does not create a length budget when only batch count exists", () => {
    const minimal = {
      ...emptyTaskGraphDraftV2(),
      metadata: {
        runtime_loop_policy: {
          initial_inputs: {
            chapters_per_round: 10,
          },
        },
      },
    };

    const patch = buildTaskGraphRuntimeLoopInputPatch(minimal, "chapters_per_round", 8);
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown> | undefined;

    expect(runtime?.length_budget).toBeUndefined();
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).batch_size).toBe(8);
  });
});
