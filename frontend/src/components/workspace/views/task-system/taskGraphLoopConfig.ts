import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

const DEFAULT_TARGET_GROUP_COUNT = 1;
const DEFAULT_UNITS_PER_GROUP = 1;
const DEFAULT_UNITS_PER_BATCH = 1;
const DEFAULT_UNIT_TARGET_MEASURE = 0;
const DEFAULT_GROUP_TARGET_MEASURE = DEFAULT_UNITS_PER_GROUP * DEFAULT_UNIT_TARGET_MEASURE;
const DEFAULT_TARGET_MEASURE_UNITS = DEFAULT_TARGET_GROUP_COUNT * DEFAULT_GROUP_TARGET_MEASURE;
const DEFAULT_LOOP_FRAME_ID = "loop.default";
const LOOP_INITIAL_INPUT_SOURCE = "graph.loop_frames.initial_inputs";

export function taskGraphLoopRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function taskGraphLoopNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function taskGraphLoopInitialInputs(graphDraft: TaskGraphDraftV2) {
  return taskGraphLoopFrames(graphDraft).reduce<Record<string, unknown>>(
    (acc, frame) => ({ ...acc, ...taskGraphLoopRecord(frame.initial_inputs) }),
    {},
  );
}

export function taskGraphLoopFrames(graphDraft: TaskGraphDraftV2) {
  return Array.isArray(graphDraft.loop_frames) ? graphDraft.loop_frames.map(taskGraphLoopRecord) : [];
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
    defaults.target_group_count,
  ) ?? defaults.target_group_count;
  const unitsPerGroup = firstPositiveGraphLoopNumber(
    loopInputs.units_per_group,
    unitBatch.units_per_group,
    defaults.units_per_group,
  ) ?? defaults.units_per_group;
  const unitsPerBatch = firstPositiveGraphLoopNumber(
    loopInputs.units_per_batch,
    unitBatch.units_per_batch,
    unitBatch.batch_size,
    defaults.units_per_batch,
  ) ?? defaults.units_per_batch;
  const unitTargetMeasure = firstNonNegativeGraphLoopNumber(
    loopInputs.unit_target_measure,
    unitBatch.unit_target_measure,
    defaults.unit_target_measure,
  ) ?? defaults.unit_target_measure;
  const groupTargetMeasure = firstNonNegativeGraphLoopNumber(
    loopInputs.group_target_measure,
    unitBatch.group_target_measure,
    unitsPerGroup * unitTargetMeasure,
  ) ?? unitsPerGroup * unitTargetMeasure;
  const targetMeasureUnits = firstNonNegativeGraphLoopNumber(
    loopInputs.target_measure_units,
    unitBatch.target_measure_units,
    targetGroupCount * groupTargetMeasure,
  ) ?? targetGroupCount * groupTargetMeasure;
  const targetUnitCount = firstPositiveGraphLoopNumber(
    loopInputs.target_unit_count,
    unitBatch.target_unit_count,
    unitBatch.requested_count,
    targetGroupCount * unitsPerGroup,
  ) ?? targetGroupCount * unitsPerGroup;

  return {
    ...defaults,
    ...loopInputs,
    target_group_count: targetGroupCount,
    units_per_group: unitsPerGroup,
    target_unit_count: targetUnitCount,
    units_per_batch: unitsPerBatch,
    unit_target_measure: unitTargetMeasure,
    group_target_measure: groupTargetMeasure,
    target_measure_units: targetMeasureUnits,
  };
}

function defaultTaskGraphLoopFrame(initialInputs: Record<string, unknown>): Record<string, unknown> {
  return {
    frame_id: DEFAULT_LOOP_FRAME_ID,
    scope_id: DEFAULT_LOOP_FRAME_ID,
    title: "默认循环",
    kind: "bounded_metric_iteration",
    initial_inputs: initialInputs,
  };
}

function taskGraphLoopFramesWithInitialInputs(
  graphDraft: TaskGraphDraftV2,
  initialInputs: Record<string, unknown>,
): Array<Record<string, unknown>> {
  const frames = taskGraphLoopFrames(graphDraft);
  if (!frames.length) return [defaultTaskGraphLoopFrame(initialInputs)];
  return frames.map((frame, index) => {
    const frameId = String(frame.frame_id ?? frame.scope_id ?? (index === 0 ? DEFAULT_LOOP_FRAME_ID : `loop.${index + 1}`)).trim();
    return {
      ...frame,
      frame_id: frameId || DEFAULT_LOOP_FRAME_ID,
      scope_id: String(frame.scope_id ?? frameId ?? DEFAULT_LOOP_FRAME_ID).trim() || DEFAULT_LOOP_FRAME_ID,
      initial_inputs: initialInputs,
    };
  });
}

export function buildTaskGraphLoopInputPatch(
  graphDraft: TaskGraphDraftV2,
  key: string,
  value: unknown,
): Partial<TaskGraphDraftV2> {
  const normalizedKey = key;
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
  const nextLoopFrames = taskGraphLoopFramesWithInitialInputs(graphDraft, initialInputs);
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
    target_unit_count: initialInputs.target_unit_count,
    units_per_batch: unitsPerBatch,
    unit_target_measure: unitTargetMeasure,
    group_target_measure: groupTargetMeasure,
    target_measure_units: targetMeasureUnits,
    source: LOOP_INITIAL_INPUT_SOURCE,
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
    source: LOOP_INITIAL_INPUT_SOURCE,
  };
  const nextContractBindings = writePath(contractBindings, ["unit_batch"], unitBatchPatch);
  return {
    loop_frames: nextLoopFrames,
    contract_bindings: shouldWriteLengthBudget
      ? writePath(nextContractBindings, ["runtime", "length_budget"], lengthBudgetPatch)
      : nextContractBindings,
  };
}
