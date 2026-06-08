export const KNOWN_TASK_ENVIRONMENT_DISPLAY_NAMES: Record<string, string> = {
  "env.coding.vibe_workspace": "Vibe 编码工作区",
  "env.creation.writing": "创意写作",
  "env.development.sandbox": "开发沙盒",
  "env.office.document_processing": "办公文档处理",
  "env.office.data_analysis": "办公数据分析",
  "env.office.general_workspace": "办公通用工作区",
  "env.general.workspace": "通用工作区",
  "env.research.evidence_workspace": "研究证据工作区",
};

export function taskEnvironmentDisplayName(environmentId: string, fallback = "") {
  const normalizedId = String(environmentId || "").trim();
  const normalizedFallback = String(fallback || "").trim();
  return KNOWN_TASK_ENVIRONMENT_DISPLAY_NAMES[normalizedId] || normalizedFallback || normalizedId;
}
