export const KNOWN_TASK_ENVIRONMENT_DISPLAY_NAMES: Record<string, string> = {
  "env.coding.vibe_workspace": "Vibe 编码工作区",
  "env.creation.writing": "创意写作",
  "env.development.sandbox": "开发沙盒",
  "env.development.readonly": "代码审查环境",
  "env.document.processing": "文档处理环境",
  "env.general.workspace": "通用工作区",
  "env.research.web": "网络调研环境",
};

export function taskEnvironmentDisplayName(environmentId: string, fallback = "") {
  const normalizedId = String(environmentId || "").trim();
  const normalizedFallback = String(fallback || "").trim();
  return KNOWN_TASK_ENVIRONMENT_DISPLAY_NAMES[normalizedId] || normalizedFallback || normalizedId;
}
