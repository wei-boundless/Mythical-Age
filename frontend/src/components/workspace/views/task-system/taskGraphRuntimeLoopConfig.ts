import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

const DEFAULT_TARGET_VOLUMES = 5;
const DEFAULT_CHAPTERS_PER_VOLUME = 100;
const DEFAULT_CHAPTERS_PER_ROUND = 10;
const DEFAULT_CHAPTER_TARGET_WORDS = 2000;
const DEFAULT_VOLUME_TARGET_WORDS = DEFAULT_CHAPTERS_PER_VOLUME * DEFAULT_CHAPTER_TARGET_WORDS;
const DEFAULT_TARGET_WORDS = DEFAULT_TARGET_VOLUMES * DEFAULT_VOLUME_TARGET_WORDS;

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

export function defaultTaskGraphRuntimeLoopInitialInputs() {
  return {
    target_volumes: DEFAULT_TARGET_VOLUMES,
    chapters_per_volume: DEFAULT_CHAPTERS_PER_VOLUME,
    target_chapters: DEFAULT_TARGET_VOLUMES * DEFAULT_CHAPTERS_PER_VOLUME,
    chapters_per_round: DEFAULT_CHAPTERS_PER_ROUND,
    chapter_batch_size: DEFAULT_CHAPTERS_PER_ROUND,
    chapter_target_words: DEFAULT_CHAPTER_TARGET_WORDS,
    volume_target_words: DEFAULT_VOLUME_TARGET_WORDS,
    target_words: DEFAULT_TARGET_WORDS,
  };
}

export function resolvedTaskGraphRuntimeLoopInitialInputs(graphDraft: TaskGraphDraftV2) {
  const unitBatch = taskGraphRuntimeLoopRecord(taskGraphRuntimeLoopRecord(graphDraft.contract_bindings).unit_batch);
  const loopInputs = taskGraphRuntimeLoopInitialInputs(graphDraft);
  const defaults = defaultTaskGraphRuntimeLoopInitialInputs();
  const targetVolumes = firstPositiveRuntimeLoopNumber(
    loopInputs.target_volumes,
    unitBatch.target_volumes,
    defaults.target_volumes,
  ) ?? defaults.target_volumes;
  const chaptersPerVolume = firstPositiveRuntimeLoopNumber(
    loopInputs.chapters_per_volume,
    unitBatch.chapters_per_volume,
    defaults.chapters_per_volume,
  ) ?? defaults.chapters_per_volume;
  const chaptersPerRound = firstPositiveRuntimeLoopNumber(
    loopInputs.chapters_per_round,
    loopInputs.chapter_batch_size,
    unitBatch.batch_size,
    defaults.chapters_per_round,
  ) ?? defaults.chapters_per_round;
  const chapterTargetWords = firstPositiveRuntimeLoopNumber(
    loopInputs.chapter_target_words,
    unitBatch.chapter_target_words,
    defaults.chapter_target_words,
  ) ?? defaults.chapter_target_words;
  const volumeTargetWords = firstPositiveRuntimeLoopNumber(
    loopInputs.volume_target_words,
    unitBatch.volume_target_words,
    chaptersPerVolume * chapterTargetWords,
  ) ?? chaptersPerVolume * chapterTargetWords;
  const targetWords = firstPositiveRuntimeLoopNumber(
    loopInputs.target_words,
    targetVolumes * volumeTargetWords,
  ) ?? targetVolumes * volumeTargetWords;
  const targetChapters = firstPositiveRuntimeLoopNumber(
    loopInputs.target_chapters,
    unitBatch.requested_count,
    targetVolumes * chaptersPerVolume,
  ) ?? targetVolumes * chaptersPerVolume;

  return {
    ...defaults,
    ...loopInputs,
    target_volumes: targetVolumes,
    chapters_per_volume: chaptersPerVolume,
    target_chapters: targetChapters,
    chapters_per_round: chaptersPerRound,
    chapter_batch_size: firstPositiveRuntimeLoopNumber(loopInputs.chapter_batch_size, chaptersPerRound) ?? chaptersPerRound,
    chapter_target_words: chapterTargetWords,
    volume_target_words: volumeTargetWords,
    target_words: targetWords,
  };
}

export function buildTaskGraphRuntimeLoopInputPatch(
  graphDraft: TaskGraphDraftV2,
  key: string,
  value: unknown,
): Partial<TaskGraphDraftV2> {
  const metadata = taskGraphRuntimeLoopRecord(graphDraft.metadata);
  const runtimeLoopPolicy = taskGraphRuntimeLoopRecord(metadata.runtime_loop_policy);
  const initialInputs = {
    ...resolvedTaskGraphRuntimeLoopInitialInputs(graphDraft),
    [key]: value,
  };
  if (key === "chapters_per_round") {
    initialInputs.chapter_batch_size = value;
  }
  if (key === "chapter_batch_size") {
    initialInputs.chapters_per_round = value;
  }
  const targetVolumes = firstPositiveRuntimeLoopNumber(initialInputs.target_volumes) ?? DEFAULT_TARGET_VOLUMES;
  const chaptersPerVolume = firstPositiveRuntimeLoopNumber(initialInputs.chapters_per_volume) ?? DEFAULT_CHAPTERS_PER_VOLUME;
  const chaptersPerRound = firstPositiveRuntimeLoopNumber(initialInputs.chapters_per_round, initialInputs.chapter_batch_size) ?? DEFAULT_CHAPTERS_PER_ROUND;
  const chapterTargetWords = firstPositiveRuntimeLoopNumber(initialInputs.chapter_target_words) ?? DEFAULT_CHAPTER_TARGET_WORDS;
  const volumeTargetWords = key === "volume_target_words"
    ? firstPositiveRuntimeLoopNumber(initialInputs.volume_target_words, chaptersPerVolume * chapterTargetWords) ?? chaptersPerVolume * chapterTargetWords
    : chaptersPerVolume * chapterTargetWords;
  const targetWords = key === "target_words"
    ? firstPositiveRuntimeLoopNumber(initialInputs.target_words, targetVolumes * volumeTargetWords) ?? targetVolumes * volumeTargetWords
    : targetVolumes * volumeTargetWords;
  initialInputs.target_volumes = targetVolumes;
  initialInputs.chapters_per_volume = chaptersPerVolume;
  initialInputs.chapters_per_round = chaptersPerRound;
  initialInputs.chapter_batch_size = chaptersPerRound;
  initialInputs.chapter_target_words = chapterTargetWords;
  initialInputs.volume_target_words = volumeTargetWords;
  initialInputs.target_words = targetWords;
  initialInputs.target_chapters = targetVolumes * chaptersPerVolume;
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
  const scaleInputKeys = new Set([
    "target_volumes",
    "chapters_per_volume",
    "chapters_per_round",
    "chapter_batch_size",
    "chapter_target_words",
    "volume_target_words",
    "target_words",
  ]);
  const shouldRecalculateScale = scaleInputKeys.has(key);
  const batchUnitCount = chaptersPerRound;
  const currentBudgetScope = String(currentLengthBudget.budget_scope ?? "").trim();
  const resolvedBudgetScope = currentBudgetScope || "volume";
  const batchTargetUnits = chaptersPerRound * chapterTargetWords;
  const budgetScopeTargetUnits = resolvedBudgetScope === "batch"
    ? batchTargetUnits
    : resolvedBudgetScope === "volume"
      ? volumeTargetWords
      : targetWords;
  const targetUnits = shouldRecalculateScale
    ? budgetScopeTargetUnits
    : firstPositiveRuntimeLoopNumber(currentLengthBudget.target_units, budgetScopeTargetUnits);
  const resolvedTargetUnits = targetUnits ?? positiveRuntimeLoopNumber(currentLengthBudget.target_units);
  const resolvedBatchUnitCount = positiveRuntimeLoopNumber(currentLengthBudget.batch_unit_count)
    ?? (resolvedBudgetScope === "volume" ? chaptersPerVolume : batchUnitCount);
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
    requested_count: initialInputs.target_chapters,
    batch_size: chaptersPerRound,
    target_volumes: targetVolumes,
    chapters_per_volume: chaptersPerVolume,
    chapter_target_words: chapterTargetWords,
    volume_target_words: volumeTargetWords,
    source: "metadata.runtime_loop_policy.initial_inputs",
  };
  const lengthBudgetPatch: Record<string, unknown> = {
    ...currentLengthBudget,
    enabled: currentLengthBudget.enabled ?? (resolvedTargetUnits !== undefined ? true : undefined),
    budget_scope: resolvedBudgetScope,
    measurement_mode: currentLengthBudget.measurement_mode || "text_units",
    unit_kind: currentLengthBudget.unit_kind || (resolvedBudgetScope === "volume" ? "volume" : "chapter"),
    unit_label_zh: currentLengthBudget.unit_label_zh || (resolvedBudgetScope === "volume" ? "卷" : "章节"),
    batch_unit_count: resolvedBatchUnitCount,
    target_units: resolvedTargetUnits,
    min_units: shouldRecalculateScale ? (resolvedTargetUnits ? Math.floor(resolvedTargetUnits * 0.8) : undefined) : currentLengthBudget.min_units ?? (resolvedTargetUnits ? Math.floor(resolvedTargetUnits * 0.8) : undefined),
    max_units: shouldRecalculateScale ? (resolvedTargetUnits ? Math.ceil(resolvedTargetUnits * 1.2) : undefined) : currentLengthBudget.max_units ?? (resolvedTargetUnits ? Math.ceil(resolvedTargetUnits * 1.2) : undefined),
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
