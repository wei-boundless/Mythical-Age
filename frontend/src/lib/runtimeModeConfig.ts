export type RuntimeModeConfig = {
  mode: string;
  label: string;
  interaction_mode?: string;
  recipe_id?: string;
  projection_strength?: string;
  builtin?: boolean;
  editable?: boolean;
  description?: string;
};

export const FALLBACK_RUNTIME_MODE: RuntimeModeConfig = {
  mode: "custom",
  label: "自定义模式",
  interaction_mode: "custom_mode",
  recipe_id: "runtime.recipe.custom",
  projection_strength: "manual",
  builtin: true,
  editable: true,
};

export function dedupeRuntimeValues(values: unknown): string[] {
  const rawValues = typeof values === "string" ? [values] : Array.isArray(values) ? values : [];
  return Array.from(new Set(rawValues.map((item) => String(item || "").trim()).filter(Boolean)));
}

export function runtimeModeCatalogFrom(rawCatalog: unknown): RuntimeModeConfig[] {
  const byId = new Map<string, RuntimeModeConfig>();
  for (const item of arrayOfRecords(rawCatalog)) {
    const mode = normalizeModeRecord(item);
    if (mode.mode) byId.set(mode.mode, { ...(byId.get(mode.mode) ?? {}), ...mode });
  }
  const modes = Array.from(byId.values());
  return modes.length ? modes : [{ ...FALLBACK_RUNTIME_MODE }];
}

export function normalizeRuntimeModes(values: unknown, catalog: RuntimeModeConfig[], fallback = "custom"): string[] {
  const known = new Set(catalog.map((mode) => mode.mode).filter(Boolean));
  const modes = dedupeRuntimeValues(values).filter((mode) => known.has(mode));
  if (modes.length) return modes;
  return known.has(fallback) ? [fallback] : Array.from(known).slice(0, 1);
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

function normalizeModeRecord(record: Record<string, unknown>): RuntimeModeConfig {
  const mode = String(record.mode || record.id || "").trim();
  return {
    mode,
    label: String(record.label || record.title || mode || "自定义模式").trim(),
    interaction_mode: String(record.interaction_mode || "").trim() || undefined,
    recipe_id: String(record.recipe_id || "").trim() || undefined,
    projection_strength: String(record.projection_strength || "").trim() || undefined,
    builtin: Boolean(record.builtin ?? false),
    editable: Boolean(record.editable ?? mode === "custom"),
    description: String(record.description || "").trim() || undefined,
  };
}

function arrayOfRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
