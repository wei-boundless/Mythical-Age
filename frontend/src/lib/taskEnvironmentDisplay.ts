export const FALLBACK_TASK_ENVIRONMENT_DISPLAY_NAMES: Record<string, string> = {
  "env.coding.vibe_workspace": "Vibe 编码工作区",
  "env.office.file_search": "轻量办公文件检索",
  "env.general.workspace": "通用工作区",
};

export function taskEnvironmentDisplayName(environmentId: string, fallback = "") {
  const normalizedId = String(environmentId || "").trim();
  const normalizedFallback = String(fallback || "").trim();
  return normalizedFallback || FALLBACK_TASK_ENVIRONMENT_DISPLAY_NAMES[normalizedId] || normalizedId;
}
