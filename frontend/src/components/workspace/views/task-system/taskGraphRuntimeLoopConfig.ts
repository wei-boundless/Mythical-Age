import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

export function taskGraphRuntimeLoopRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function taskGraphRuntimeLoopNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function taskGraphRuntimeLoopInitialInputs(graphDraft: TaskGraphDraftV2) {
  return taskGraphRuntimeLoopRecord(taskGraphRuntimeLoopRecord(graphDraft.metadata.runtime_loop_policy).initial_inputs);
}

export function taskGraphRuntimeLoopFrames(graphDraft: TaskGraphDraftV2) {
  const frames = taskGraphRuntimeLoopRecord(graphDraft.metadata.runtime_loop_policy).frames;
  return Array.isArray(frames) ? frames.map(taskGraphRuntimeLoopRecord) : [];
}

function writePath(source: Record<string, unknown>, path: string[], value: unknown): Record<string, unknown> {
  const [head, ...rest] = path;
  if (!head) return source;
  if (!rest.length) return { ...source, [head]: value };
  return {
    ...source,
    [head]: writePath(taskGraphRuntimeLoopRecord(source[head]), rest, value),
  };
}

function positiveRuntimeLoopNumber(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function firstPositiveRuntimeLoopNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = positiveRuntimeLoopNumber(value);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

export function buildTaskGraphRuntimeLoopInputPatch(
  graphDraft: TaskGraphDraftV2,
  key: string,
  value: unknown,
): Partial<TaskGraphDraftV2> {
  const metadata = taskGraphRuntimeLoopRecord(graphDraft.metadata);
  const runtimeLoopPolicy = taskGraphRuntimeLoopRecord(metadata.runtime_loop_policy);
  const initialInputs = {
    ...taskGraphRuntimeLoopRecord(runtimeLoopPolicy.initial_inputs),
    [key]: value,
  };
  if (key === "chapters_per_round") {
    initialInputs.chapter_batch_size = value;
  }
  if (key === "chapter_batch_size") {
    initialInputs.chapters_per_round = value;
  }
  const nextMetadata = {
    ...metadata,
    runtime_loop_policy: {
      ...runtimeLoopPolicy,
      enabled: runtimeLoopPolicy.enabled ?? true,
      initial_inputs: initialInputs,
    },
  };
  const contractBindings = taskGraphRuntimeLoopRecord(graphDraft.contract_bindings);
  const currentUnitBatch = taskGraphRuntimeLoopRecord(contractBindings.unit_batch);
  const currentLengthBudget = taskGraphRuntimeLoopRecord(taskGraphRuntimeLoopRecord(contractBindings.runtime).length_budget);
  const currentLengthBudgetRepairPolicy = taskGraphRuntimeLoopRecord(currentLengthBudget.repair_policy);
  const currentLengthBudgetAcceptancePolicy = taskGraphRuntimeLoopRecord(currentLengthBudget.acceptance_policy);
  const batchUnitCount = firstPositiveRuntimeLoopNumber(initialInputs.chapters_per_round, initialInputs.chapter_batch_size);
  const targetUnits = firstPositiveRuntimeLoopNumber(
    initialInputs.target_words,
    initialInputs.volume_target_words,
    batchUnitCount && positiveRuntimeLoopNumber(initialInputs.chapter_target_words)
      ? batchUnitCount * Number(initialInputs.chapter_target_words)
      : undefined,
  );
  const resolvedTargetUnits = targetUnits ?? positiveRuntimeLoopNumber(currentLengthBudget.target_units);
  const resolvedBatchUnitCount = batchUnitCount ?? positiveRuntimeLoopNumber(currentLengthBudget.batch_unit_count);
  const currentLengthBudgetConfigured = currentLengthBudget.enabled === true
    || firstPositiveRuntimeLoopNumber(
      currentLengthBudget.target_units,
      currentLengthBudget.min_units,
      currentLengthBudget.max_units,
    ) !== undefined;
  const shouldWriteLengthBudget = currentLengthBudgetConfigured || resolvedTargetUnits !== undefined;
  const unitBatchPatch: Record<string, unknown> = {
    ...currentUnitBatch,
    unit_kind: currentUnitBatch.unit_kind || "chapter",
    unit_label_zh: currentUnitBatch.unit_label_zh || "章节",
    requested_count: initialInputs.target_chapters ?? initialInputs.chapters_per_volume,
    batch_size: initialInputs.chapters_per_round ?? initialInputs.chapter_batch_size,
    target_volumes: initialInputs.target_volumes,
    chapters_per_volume: initialInputs.chapters_per_volume,
    chapter_target_words: initialInputs.chapter_target_words,
    volume_target_words: initialInputs.volume_target_words,
    source: "metadata.runtime_loop_policy.initial_inputs",
  };
  const lengthBudgetPatch: Record<string, unknown> = {
    ...currentLengthBudget,
    enabled: currentLengthBudget.enabled ?? (resolvedTargetUnits !== undefined ? true : undefined),
    budget_scope: currentLengthBudget.budget_scope || "graph",
    measurement_mode: currentLengthBudget.measurement_mode || "text_units",
    unit_kind: currentLengthBudget.unit_kind || "chapter",
    unit_label_zh: currentLengthBudget.unit_label_zh || "章节",
    batch_unit_count: resolvedBatchUnitCount,
    target_units: resolvedTargetUnits,
    min_units: currentLengthBudget.min_units ?? (resolvedTargetUnits ? Math.floor(resolvedTargetUnits * 0.8) : undefined),
    max_units: currentLengthBudget.max_units ?? (resolvedTargetUnits ? Math.ceil(resolvedTargetUnits * 1.2) : undefined),
    repair_policy: {
      ...currentLengthBudgetRepairPolicy,
      mode: String(currentLengthBudgetRepairPolicy.mode ?? "expand_or_split") || "expand_or_split",
      max_repair_rounds: taskGraphRuntimeLoopNumber(currentLengthBudgetRepairPolicy.max_repair_rounds, 2),
    },
    acceptance_policy: {
      ...currentLengthBudgetAcceptancePolicy,
      require_continuity: currentLengthBudgetAcceptancePolicy.require_continuity ?? true,
      require_formal_headings: currentLengthBudgetAcceptancePolicy.require_formal_headings ?? true,
    },
    source: "metadata.runtime_loop_policy.initial_inputs",
  };
  const nextContractBindings = writePath(contractBindings, ["unit_batch"], unitBatchPatch);
  return {
    metadata: nextMetadata,
    contract_bindings: shouldWriteLengthBudget
      ? writePath(nextContractBindings, ["runtime", "length_budget"], lengthBudgetPatch)
      : nextContractBindings,
  };
}
