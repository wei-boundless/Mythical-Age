import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

const DEFAULT_TARGET_GROUP_COUNT = 1;
const DEFAULT_UNITS_PER_GROUP = 1;
const DEFAULT_UNITS_PER_BATCH = 1;
const DEFAULT_UNIT_TARGET_MEASURE = 0;
const DEFAULT_GROUP_TARGET_MEASURE = DEFAULT_UNITS_PER_GROUP * DEFAULT_UNIT_TARGET_MEASURE;
const DEFAULT_TARGET_MEASURE_UNITS = DEFAULT_TARGET_GROUP_COUNT * DEFAULT_GROUP_TARGET_MEASURE;

const LEGACY_RUNTIME_LOOP_INPUT_KEYS = new Set([
  "target_volumes",
  "chapters_per_volume",
  "target_chapters",
  "chapters_per_round",
  "chapter_batch_size",
  "chapter_target_words",
  "volume_target_words",
  "target_words",
]);

const LEGACY_RUNTIME_LOOP_KEY_MAP: Record<string, string> = {
  target_volumes: "target_group_count",
  chapters_per_volume: "units_per_group",
  target_chapters: "target_unit_count",
  chapters_per_round: "units_per_batch",
  chapter_batch_size: "units_per_batch",
  chapter_target_words: "unit_target_measure",
  volume_target_words: "group_target_measure",
  target_words: "target_measure_units",
};

export function taskGraphLoopRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function taskGraphLoopNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function taskGraphLoopInitialInputs(graphDraft: TaskGraphDraftV2) {
  return taskGraphLoopRecord(taskGraphLoopRecord(graphDraft.metadata.graph_loop_policy).initial_inputs);
}

export function taskGraphLoopFrames(graphDraft: TaskGraphDraftV2) {
  const frames = taskGraphLoopRecord(graphDraft.metadata.graph_loop_policy).frames;
  return Array.isArray(frames) ? frames.map(taskGraphLoopRecord) : [];
}

function writePath(source: Record<string, unknown>, path: string[], value: unknown): Record<string, unknown> {
  const [head, ...rest] = path;
  if (!head) return source;
  if (!rest.length) return { ...source, [head]: value };
  return {
    ...source,
    [head]: writePath(taskGraphLoopRecord(source[head]), rest, value),
  };
}

function positiveGraphLoopNumber(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function firstPositiveGraphLoopNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = positiveGraphLoopNumber(value);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

function firstNonNegativeGraphLoopNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  return undefined;
}

function stripLegacyGraphLoopInputs(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => !LEGACY_RUNTIME_LOOP_INPUT_KEYS.has(key)),
  );
}

export function defaultTaskGraphLoopInitialInputs() {
  return {
    target_group_count: DEFAULT_TARGET_GROUP_COUNT,
    units_per_group: DEFAULT_UNITS_PER_GROUP,
    target_unit_count: DEFAULT_TARGET_GROUP_COUNT * DEFAULT_UNITS_PER_GROUP,
    units_per_batch: DEFAULT_UNITS_PER_BATCH,
    unit_target_measure: DEFAULT_UNIT_TARGET_MEASURE,
    group_target_measure: DEFAULT_GROUP_TARGET_MEASURE,
    target_measure_units: DEFAULT_TARGET_MEASURE_UNITS,
  };
}

export function resolvedTaskGraphLoopInitialInputs(graphDraft: TaskGraphDraftV2) {
  const unitBatch = taskGraphLoopRecord(taskGraphLoopRecord(graphDraft.contract_bindings).unit_batch);
  const loopInputs = taskGraphLoopInitialInputs(graphDraft);
  const defaults = defaultTaskGraphLoopInitialInputs();
  const targetGroupCount = firstPositiveGraphLoopNumber(
    loopInputs.target_group_count,
    unitBatch.target_group_count,
    loopInputs.target_volumes,
    unitBatch.target_volumes,
    defaults.target_group_count,
  ) ?? defaults.target_group_count;
  const unitsPerGroup = firstPositiveGraphLoopNumber(
    loopInputs.units_per_group,
    unitBatch.units_per_group,
    loopInputs.chapters_per_volume,
    unitBatch.chapters_per_volume,
    defaults.units_per_group,
  ) ?? defaults.units_per_group;
  const unitsPerBatch = firstPositiveGraphLoopNumber(
    loopInputs.units_per_batch,
    loopInputs.chapters_per_round,
    loopInputs.chapter_batch_size,
    unitBatch.batch_size,
    defaults.units_per_batch,
  ) ?? defaults.units_per_batch;
  const unitTargetMeasure = firstNonNegativeGraphLoopNumber(
    loopInputs.unit_target_measure,
    loopInputs.chapter_target_words,
    unitBatch.chapter_target_words,
    defaults.unit_target_measure,
  ) ?? defaults.unit_target_measure;
  const groupTargetMeasure = firstNonNegativeGraphLoopNumber(
    loopInputs.group_target_measure,
    loopInputs.volume_target_words,
    unitBatch.volume_target_words,
    unitsPerGroup * unitTargetMeasure,
  ) ?? unitsPerGroup * unitTargetMeasure;
  const targetMeasureUnits = firstNonNegativeGraphLoopNumber(
    loopInputs.target_measure_units,
    loopInputs.target_words,
    targetGroupCount * groupTargetMeasure,
  ) ?? targetGroupCount * groupTargetMeasure;
  const targetUnitCount = firstPositiveGraphLoopNumber(
    loopInputs.target_unit_count,
    loopInputs.target_chapters,
    unitBatch.requested_count,
    targetGroupCount * unitsPerGroup,
  ) ?? targetGroupCount * unitsPerGroup;

  return {
    ...defaults,
    ...stripLegacyGraphLoopInputs(loopInputs),
    target_group_count: targetGroupCount,
    units_per_group: unitsPerGroup,
    target_unit_count: targetUnitCount,
    units_per_batch: unitsPerBatch,
    unit_target_measure: unitTargetMeasure,
    group_target_measure: groupTargetMeasure,
    target_measure_units: targetMeasureUnits,
    legacy_input_key_map: Object.fromEntries(
      Object.entries(LEGACY_RUNTIME_LOOP_KEY_MAP).filter(([legacyKey]) => loopInputs[legacyKey] !== undefined),
    ),
  };
}

export function buildTaskGraphLoopInputPatch(
  graphDraft: TaskGraphDraftV2,
  key: string,
  value: unknown,
): Partial<TaskGraphDraftV2> {
  const metadata = taskGraphLoopRecord(graphDraft.metadata);
  const graphLoopPolicy = taskGraphLoopRecord(metadata.graph_loop_policy);
  const normalizedKey = LEGACY_RUNTIME_LOOP_KEY_MAP[key] ?? key;
  const initialInputs: Record<string, unknown> = {
    ...resolvedTaskGraphLoopInitialInputs(graphDraft),
    [normalizedKey]: value,
  };
  const targetGroupCount = firstPositiveGraphLoopNumber(initialInputs.target_group_count) ?? DEFAULT_TARGET_GROUP_COUNT;
  const unitsPerGroup = firstPositiveGraphLoopNumber(initialInputs.units_per_group) ?? DEFAULT_UNITS_PER_GROUP;
  const unitsPerBatch = firstPositiveGraphLoopNumber(initialInputs.units_per_batch) ?? DEFAULT_UNITS_PER_BATCH;
  const unitTargetMeasure = firstNonNegativeGraphLoopNumber(initialInputs.unit_target_measure) ?? DEFAULT_UNIT_TARGET_MEASURE;
  const groupTargetMeasure = normalizedKey === "group_target_measure"
    ? firstNonNegativeGraphLoopNumber(initialInputs.group_target_measure, unitsPerGroup * unitTargetMeasure) ?? unitsPerGroup * unitTargetMeasure
    : unitsPerGroup * unitTargetMeasure;
  const targetMeasureUnits = normalizedKey === "target_measure_units"
    ? firstNonNegativeGraphLoopNumber(initialInputs.target_measure_units, targetGroupCount * groupTargetMeasure) ?? targetGroupCount * groupTargetMeasure
    : targetGroupCount * groupTargetMeasure;
  initialInputs.target_group_count = targetGroupCount;
  initialInputs.units_per_group = unitsPerGroup;
  initialInputs.units_per_batch = unitsPerBatch;
  initialInputs.unit_target_measure = unitTargetMeasure;
  initialInputs.group_target_measure = groupTargetMeasure;
  initialInputs.target_measure_units = targetMeasureUnits;
  initialInputs.target_unit_count = targetGroupCount * unitsPerGroup;
  delete initialInputs.legacy_input_key_map;
  const nextMetadata = {
    ...metadata,
    graph_loop_policy: {
      ...graphLoopPolicy,
      enabled: graphLoopPolicy.enabled ?? true,
      initial_inputs: stripLegacyGraphLoopInputs(initialInputs),
    },
  };
  const contractBindings = taskGraphLoopRecord(graphDraft.contract_bindings);
  const currentUnitBatch = taskGraphLoopRecord(contractBindings.unit_batch);
  const currentLengthBudget = taskGraphLoopRecord(taskGraphLoopRecord(contractBindings.runtime).length_budget);
  const currentLengthBudgetRepairPolicy = taskGraphLoopRecord(currentLengthBudget.repair_policy);
  const currentLengthBudgetAcceptancePolicy = taskGraphLoopRecord(currentLengthBudget.acceptance_policy);
  const scaleInputKeys = new Set([
    "target_group_count",
    "units_per_group",
    "units_per_batch",
    "unit_target_measure",
    "group_target_measure",
    "target_measure_units",
  ]);
  const shouldRecalculateScale = scaleInputKeys.has(normalizedKey);
  const batchUnitCount = unitsPerBatch;
  const currentBudgetScope = String(currentLengthBudget.budget_scope ?? "").trim();
  const resolvedBudgetScope = (currentBudgetScope === "volume" ? "group" : currentBudgetScope) || "batch";
  const batchTargetUnits = unitsPerBatch * unitTargetMeasure;
  const budgetScopeTargetUnits = resolvedBudgetScope === "batch"
    ? batchTargetUnits
    : resolvedBudgetScope === "group"
      ? groupTargetMeasure
      : targetMeasureUnits;
  const positiveBudgetScopeTargetUnits = positiveGraphLoopNumber(budgetScopeTargetUnits);
  const targetUnits = shouldRecalculateScale
    ? positiveBudgetScopeTargetUnits
    : firstPositiveGraphLoopNumber(currentLengthBudget.target_units, positiveBudgetScopeTargetUnits);
  const resolvedTargetUnits = targetUnits ?? positiveGraphLoopNumber(currentLengthBudget.target_units);
  const resolvedBatchUnitCount = positiveGraphLoopNumber(currentLengthBudget.batch_unit_count)
    ?? (resolvedBudgetScope === "group" ? unitsPerGroup : batchUnitCount);
  const currentLengthBudgetConfigured = currentLengthBudget.enabled === true
    || firstPositiveGraphLoopNumber(
      currentLengthBudget.target_units,
      currentLengthBudget.min_units,
      currentLengthBudget.max_units,
    ) !== undefined;
  const shouldWriteLengthBudget = currentLengthBudgetConfigured || resolvedTargetUnits !== undefined;
  const unitBatchPatch: Record<string, unknown> = {
    ...currentUnitBatch,
    unit_kind: currentUnitBatch.unit_kind || "unit",
    unit_label_zh: currentUnitBatch.unit_label_zh || "单元",
    requested_count: initialInputs.target_unit_count,
    batch_size: unitsPerBatch,
    target_group_count: targetGroupCount,
    units_per_group: unitsPerGroup,
    unit_target_measure: unitTargetMeasure,
    group_target_measure: groupTargetMeasure,
    source: "metadata.graph_loop_policy.initial_inputs",
  };
  const lengthBudgetPatch: Record<string, unknown> = {
    ...currentLengthBudget,
    enabled: currentLengthBudget.enabled ?? (resolvedTargetUnits !== undefined ? true : undefined),
    budget_scope: resolvedBudgetScope,
    measurement_mode: currentLengthBudget.measurement_mode || "text_units",
    unit_kind: currentLengthBudget.unit_kind || currentUnitBatch.unit_kind || (resolvedBudgetScope === "group" ? "group" : "unit"),
    unit_label_zh: currentLengthBudget.unit_label_zh || currentUnitBatch.unit_label_zh || (resolvedBudgetScope === "group" ? "组" : "单元"),
    batch_unit_count: resolvedBatchUnitCount,
    target_units: resolvedTargetUnits,
    min_units: shouldRecalculateScale ? (resolvedTargetUnits ? Math.floor(resolvedTargetUnits * 0.8) : undefined) : currentLengthBudget.min_units ?? (resolvedTargetUnits ? Math.floor(resolvedTargetUnits * 0.8) : undefined),
    max_units: shouldRecalculateScale ? (resolvedTargetUnits ? Math.ceil(resolvedTargetUnits * 1.2) : undefined) : currentLengthBudget.max_units ?? (resolvedTargetUnits ? Math.ceil(resolvedTargetUnits * 1.2) : undefined),
    repair_policy: {
      ...currentLengthBudgetRepairPolicy,
      mode: String(currentLengthBudgetRepairPolicy.mode ?? "expand_or_split") || "expand_or_split",
      max_repair_rounds: taskGraphLoopNumber(currentLengthBudgetRepairPolicy.max_repair_rounds, 2),
    },
    acceptance_policy: {
      ...currentLengthBudgetAcceptancePolicy,
      require_continuity: currentLengthBudgetAcceptancePolicy.require_continuity ?? true,
      require_formal_headings: currentLengthBudgetAcceptancePolicy.require_formal_headings ?? true,
    },
    source: "metadata.graph_loop_policy.initial_inputs",
  };
  const nextContractBindings = writePath(contractBindings, ["unit_batch"], unitBatchPatch);
  return {
    metadata: nextMetadata,
    contract_bindings: shouldWriteLengthBudget
      ? writePath(nextContractBindings, ["runtime", "length_budget"], lengthBudgetPatch)
      : nextContractBindings,
  };
}
