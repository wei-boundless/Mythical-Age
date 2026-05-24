export const BUILTIN_RUNTIME_MODE_IDS = ["role", "standard", "professional", "custom"] as const;
export type BuiltinRuntimeModeId = (typeof BUILTIN_RUNTIME_MODE_IDS)[number];

export type RuntimeModeConfig = {
  mode: string;
  label: string;
  interaction_mode?: string;
  runtime_lane?: string;
  runtime_lanes?: string[];
  recipe_id?: string;
  projection_strength?: string;
  execution_strategy?: string;
  builtin?: boolean;
  editable?: boolean;
  description?: string;
};

const BUILTIN_MODE_SET = new Set<string>(BUILTIN_RUNTIME_MODE_IDS);

export const BUILTIN_RUNTIME_MODES: RuntimeModeConfig[] = [
  {
    mode: "role",
    label: "角色模式",
    interaction_mode: "role_mode",
    runtime_lane: "role_interaction",
    recipe_id: "runtime.recipe.role_interaction",
    projection_strength: "primary",
    builtin: true,
    editable: false,
  },
  {
    mode: "standard",
    label: "标准模式",
    interaction_mode: "standard_mode",
    runtime_lane: "standard_task",
    recipe_id: "runtime.recipe.standard_task",
    projection_strength: "companion",
    builtin: true,
    editable: false,
  },
  {
    mode: "professional",
    label: "专家模式",
    interaction_mode: "professional_mode",
    runtime_lane: "professional_task",
    recipe_id: "runtime.recipe.professional_task",
    projection_strength: "style_only",
    execution_strategy: "professional_task_run",
    builtin: true,
    editable: false,
  },
  {
    mode: "custom",
    label: "自定义模式",
    interaction_mode: "custom_mode",
    runtime_lanes: [],
    recipe_id: "runtime.recipe.custom",
    projection_strength: "manual",
    builtin: true,
    editable: true,
  },
];

export function dedupeRuntimeValues(values: unknown): string[] {
  const rawValues = typeof values === "string" ? [values] : Array.isArray(values) ? values : [];
  return Array.from(new Set(rawValues.map((item) => String(item || "").trim()).filter(Boolean)));
}

export function runtimeModeCatalogFrom(rawCatalog: unknown): RuntimeModeConfig[] {
  const byId = new Map<string, RuntimeModeConfig>();
  for (const mode of BUILTIN_RUNTIME_MODES) {
    byId.set(mode.mode, { ...mode });
  }
  for (const item of arrayOfRecords(rawCatalog)) {
    const mode = normalizeModeRecord(item);
    if (BUILTIN_MODE_SET.has(mode.mode)) byId.set(mode.mode, { ...(byId.get(mode.mode) ?? {}), ...mode });
  }
  return Array.from(byId.values());
}

export function normalizeRuntimeModes(values: unknown, catalog: RuntimeModeConfig[], fallback = "custom"): string[] {
  const known = new Set(catalog.map((mode) => mode.mode).filter(Boolean));
  const modes = dedupeRuntimeValues(values).filter((mode) => known.has(mode));
  if (modes.length) return modes;
  return known.has(fallback) ? [fallback] : Array.from(known).slice(0, 1);
}

export function normalizeRuntimeModesWithLanes(values: unknown, runtimeLanes: unknown): string[] {
  const knownModes = new Set(BUILTIN_RUNTIME_MODES.map((mode) => mode.mode));
  const explicitModes = dedupeRuntimeValues(values).filter((mode) => knownModes.has(mode));
  if (explicitModes.length) return explicitModes;
  const laneValues = dedupeRuntimeValues(runtimeLanes);
  const modesFromLanes = runtimeModesForLanes(runtimeLanes, BUILTIN_RUNTIME_MODES);
  if (modesFromLanes.length) {
    const coveredLanes = new Set(runtimeLanesForModes(modesFromLanes, BUILTIN_RUNTIME_MODES));
    const hasManualLanes = laneValues.some((lane) => !coveredLanes.has(lane));
    return hasManualLanes && !modesFromLanes.includes("custom") ? [...modesFromLanes, "custom"] : modesFromLanes;
  }
  return ["custom"];
}

export function normalizeDefaultRuntimeMode(value: unknown, enabledModes: string[]): string {
  const mode = String(value || "").trim();
  const executableModes = enabledModes.filter((item) => item !== "custom");
  if (mode && mode !== "custom" && executableModes.includes(mode)) return mode;
  if (mode === "custom" && !executableModes.length && enabledModes.includes("custom")) return "custom";
  if (executableModes.length) return executableModes[0];
  if (enabledModes.includes("custom")) return "custom";
  return enabledModes[0] || "";
}

export function deriveAllowedRuntimeLanes(enabledModes: unknown, existingRuntimeLanes: unknown): string[] {
  return Array.from(new Set([
    ...runtimeLanesForModes(enabledModes, BUILTIN_RUNTIME_MODES),
    ...manualRuntimeLanes(existingRuntimeLanes, enabledModes),
  ]));
}

export function manualRuntimeLanes(runtimeLanes: unknown, enabledModes: unknown = []): string[] {
  if (!dedupeRuntimeValues(enabledModes).includes("custom")) return [];
  const modeLaneSet = new Set(runtimeLanesForModes(enabledModes, BUILTIN_RUNTIME_MODES));
  return dedupeRuntimeValues(runtimeLanes).filter((lane) => !modeLaneSet.has(lane));
}

export function runtimeLanesForModes(enabledModes: unknown, catalog: RuntimeModeConfig[]): string[] {
  const modeSet = new Set(dedupeRuntimeValues(enabledModes));
  const lanes: string[] = [];
  for (const mode of catalog) {
    if (!modeSet.has(mode.mode)) continue;
    lanes.push(...runtimeLanesForMode(mode));
  }
  return Array.from(new Set(lanes));
}

export function runtimeLanesForMode(mode: RuntimeModeConfig): string[] {
  const lanes = [
    ...dedupeRuntimeValues(mode.runtime_lanes),
    String(mode.runtime_lane || "").trim(),
  ];
  return Array.from(new Set(lanes.filter(Boolean)));
}

export function runtimeModesForLanes(runtimeLanes: unknown, catalog: RuntimeModeConfig[]): string[] {
  const laneSet = new Set(dedupeRuntimeValues(runtimeLanes));
  if (!laneSet.size) return [];
  return catalog
    .filter((mode) => runtimeLanesForMode(mode).some((lane) => laneSet.has(lane)))
    .map((mode) => mode.mode);
}

function normalizeModeRecord(record: Record<string, unknown>): RuntimeModeConfig {
  const mode = String(record.mode || record.id || "").trim();
  const runtimeLanes = dedupeRuntimeValues(record.runtime_lanes).length
    ? dedupeRuntimeValues(record.runtime_lanes)
    : dedupeRuntimeValues(record.allowed_runtime_lanes);
  const runtimeLane = String(record.runtime_lane || "").trim();
  return {
    mode,
    label: String(record.label || record.title || mode || "自定义模式").trim(),
    interaction_mode: String(record.interaction_mode || "").trim() || undefined,
    runtime_lane: runtimeLane || undefined,
    runtime_lanes: runtimeLanes.length ? runtimeLanes : runtimeLane ? [runtimeLane] : [],
    recipe_id: String(record.recipe_id || "").trim() || undefined,
    projection_strength: String(record.projection_strength || "").trim() || undefined,
    execution_strategy: String(record.execution_strategy || "").trim() || undefined,
    builtin: Boolean(record.builtin ?? BUILTIN_MODE_SET.has(mode)),
    editable: Boolean(record.editable ?? (!BUILTIN_MODE_SET.has(mode) || mode === "custom")),
    description: String(record.description || "").trim() || undefined,
  };
}

function arrayOfRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
