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
    graph_id: "graph.writing.modular_novel.chapter_cycle",
    title: "章节批次创作任务图",
    contract_bindings: {
      unit_batch: {
        unit_kind: "chapter",
        requested_count: 500,
        batch_size: 10,
      },
    },
    metadata: {
      runtime_loop_policy: {
        enabled: true,
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
    expect(initialInputs.target_volumes).toBe(5);
    expect(initialInputs.chapters_per_volume).toBe(100);
    expect(initialInputs.target_chapters).toBe(500);
    expect(initialInputs.volume_target_words).toBe(200000);
    expect(initialInputs.target_words).toBe(1000000);
    expect(unitBatch.batch_size).toBe(8);
    expect(unitBatch.requested_count).toBe(500);
    expect(unitBatch.source).toBe("metadata.runtime_loop_policy.initial_inputs");
    expect(lengthBudget.enabled).toBe(true);
    expect(lengthBudget.measurement_mode).toBe("text_units");
    expect(lengthBudget.unit_kind).toBe("volume");
    expect(lengthBudget.batch_unit_count).toBe(100);
    expect(lengthBudget.target_units).toBe(200000);
    expect((lengthBudget.repair_policy as Record<string, unknown>).mode).toBe("expand_or_split");
  });

  it("uses the million-word modular novel defaults when no graph contract exists", () => {
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

    expect(resolvedTaskGraphRuntimeLoopInitialInputs(emptyTaskGraphDraftV2())).toMatchObject({
      target_volumes: 5,
      chapters_per_volume: 100,
      target_chapters: 500,
      chapters_per_round: 10,
      volume_target_words: 200000,
      target_words: 1000000,
    });

    const patch = buildTaskGraphRuntimeLoopInputPatch(minimal, "chapters_per_round", 8);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.target_chapters).toBe(500);
    expect(initialInputs.target_words).toBe(1000000);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).batch_size).toBe(8);
    expect((patch.contract_bindings?.unit_batch as Record<string, unknown>).requested_count).toBe(500);
    expect(lengthBudget.target_units).toBe(200000);
    expect(lengthBudget.batch_unit_count).toBe(100);
  });

  it("recalculates dependent scale fields when chapters per volume changes", () => {
    const patch = buildTaskGraphRuntimeLoopInputPatch(draft(), "chapters_per_volume", 80);
    const runtimeLoopPolicy = patch.metadata?.runtime_loop_policy as Record<string, unknown>;
    const initialInputs = runtimeLoopPolicy.initial_inputs as Record<string, unknown>;
    const unitBatch = patch.contract_bindings?.unit_batch as Record<string, unknown>;
    const runtime = patch.contract_bindings?.runtime as Record<string, unknown>;
    const lengthBudget = runtime.length_budget as Record<string, unknown>;

    expect(initialInputs.chapters_per_volume).toBe(80);
    expect(initialInputs.target_chapters).toBe(400);
    expect(initialInputs.volume_target_words).toBe(160000);
    expect(initialInputs.target_words).toBe(800000);
    expect(unitBatch.requested_count).toBe(400);
    expect(unitBatch.volume_target_words).toBe(160000);
    expect(lengthBudget.target_units).toBe(160000);
  });
});
