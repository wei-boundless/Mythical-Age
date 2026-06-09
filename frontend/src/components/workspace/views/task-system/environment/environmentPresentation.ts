import type { TaskSystemOverview } from "@/lib/api";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

export type TaskEnvironmentManagement = NonNullable<TaskSystemOverview["task_environment_management"]>;
export type TaskEnvironmentItem = TaskEnvironmentManagement["environments"][number];
export type EnvironmentScope = "workspace" | "builtin_template" | "system_internal" | "other";

const KNOWN_ENVIRONMENT_COPY: Record<string, { title: string; purpose: string }> = {
  "env.coding.vibe_workspace": {
    title: "Vibe 编码工作区",
    purpose: "加载受管项目工作区、沙盒、文件状态、Git 视图和验证产物",
  },
  "env.office.file_search": {
    title: "轻量办公文件检索",
    purpose: "加载文件服务、本地搜索和来源检索能力，不挂载代码执行工具",
  },
  "env.general.workspace": {
    title: "通用工作区",
    purpose: "加载轻量上下文和受控产物空间",
  },
};

function text(value: unknown, fallback = "") {
  if (value === null || value === undefined || Array.isArray(value) || typeof value === "object") return fallback;
  const normalized = String(value).trim();
  return normalized || fallback;
}

function listLength(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

export function taskEnvironmentScope(item: TaskEnvironmentItem | undefined | null): EnvironmentScope {
  if (!item) return "workspace";
  const scope = text(item.management_scope || item.record.management_scope);
  if (scope === "workspace" || scope === "builtin_template" || scope === "system_internal") return scope;
  const source = text(item.definition_source || item.record.definition_source);
  if (source === "builtin_default") return "builtin_template";
  return "other";
}

export function taskEnvironmentScopeLabel(scope: EnvironmentScope) {
  if (scope === "workspace") return "我的环境";
  if (scope === "builtin_template") return "内置方案";
  if (scope === "system_internal") return "内部环境";
  return "其他来源";
}

export function taskEnvironmentDisplayTitle(item: TaskEnvironmentItem | undefined | null) {
  if (!item) return "新任务环境";
  return taskEnvironmentDisplayName(
    item.record.environment_id,
    item.record.title || KNOWN_ENVIRONMENT_COPY[item.record.environment_id]?.title || "任务环境",
  );
}

export function taskEnvironmentPurpose(item: TaskEnvironmentItem | undefined | null) {
  if (!item) return "配置 Agent 可加载的资料、记忆、产物空间和执行边界";
  return KNOWN_ENVIRONMENT_COPY[item.record.environment_id]?.purpose
    || item.record.description
    || "配置 Agent 可加载的资料、记忆、产物空间和执行边界";
}

export function taskEnvironmentLoadSummary(item: TaskEnvironmentItem | undefined | null) {
  if (!item) return "尚未保存为可用环境";
  const fileManagement = item.file_management && typeof item.file_management === "object" ? item.file_management as Record<string, unknown> : {};
  const memorySpace = item.memory_space && typeof item.memory_space === "object" ? item.memory_space as Record<string, unknown> : {};
  const fileCount = listLength(fileManagement.file_profile_refs) + listLength(fileManagement.required_repository_kinds);
  const memoryCount = listLength(memorySpace.environment_memory_refs)
    + listLength(memorySpace.project_knowledge_refs)
    + listLength(memorySpace.shared_context_refs)
    + listLength(memorySpace.retrieval_index_refs);
  const promptCount = Array.isArray(item.environment_prompts) ? item.environment_prompts.length : 0;
  return `${fileCount} 类资料 · ${memoryCount} 组记忆 · ${promptCount} 条说明`;
}

export function userVisibleEnvironmentItems(items: TaskEnvironmentItem[], selectedEnvironmentId = "") {
  return items.filter((item) => {
    if (taskEnvironmentScope(item) !== "system_internal") return true;
    return item.record.environment_id === selectedEnvironmentId;
  });
}
