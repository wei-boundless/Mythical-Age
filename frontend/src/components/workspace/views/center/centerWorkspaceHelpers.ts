import type { TaskGraphRecord, TaskSystemOverview } from "@/lib/api";
import { recommendedTaskGraphId, sortTaskGraphsForWorkbench } from "../task-system/taskGraphSelection";

export type CenterWorkspaceLayer = "chat" | "task-graph";

function text(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function normalizeCenterWorkspaceTaskEnvironmentId(value: unknown) {
  const raw = text(value);
  if (!raw) return "";
  return raw.startsWith("env.") ? raw : "";
}

export function centerWorkspaceTaskEnvironmentId(graph: TaskGraphRecord | null | undefined) {
  const metadata = recordOf(graph?.metadata);
  const runtimePolicy = recordOf(graph?.runtime_policy);
  const contextPolicy = recordOf(graph?.context_policy);
  return normalizeCenterWorkspaceTaskEnvironmentId(
    metadata.task_environment_id
    ?? metadata.environment_id
    ?? runtimePolicy.task_environment_id
    ?? runtimePolicy.environment_id
    ?? contextPolicy.task_environment_id
    ?? contextPolicy.environment_id,
  );
}

export function centerWorkspaceTaskEnvironmentLabel(environmentId: string) {
  return environmentId;
}

export function centerWorkspaceTaskEnvironmentLabelFromOverview(
  overview: TaskSystemOverview | null | undefined,
  environmentId: string,
) {
  const record = overview?.task_environment_management?.records?.find((item) => item.environment_id === environmentId);
  return record?.title ? `${record.title} · ${environmentId}` : centerWorkspaceTaskEnvironmentLabel(environmentId);
}

export function listCenterWorkspaceTaskGraphs(overview: TaskSystemOverview | null | undefined) {
  return sortTaskGraphsForWorkbench(overview?.task_graph_management?.task_graphs ?? [])
    .filter((graph) => centerWorkspaceTaskEnvironmentId(graph));
}

export function resolveCenterWorkspaceSelectedGraphId(overview: TaskSystemOverview | null | undefined, currentGraphId = "") {
  const graphs = listCenterWorkspaceTaskGraphs(overview);
  const current = text(currentGraphId);
  if (current && graphs.some((graph) => graph.graph_id === current)) {
    return current;
  }
  return recommendedTaskGraphId(graphs);
}

export function buildCenterWorkspaceTaskGraphInitialInputs(message: string, graph: TaskGraphRecord | null | undefined) {
  const userGoal = text(message);
  if (!userGoal) {
    throw new Error("请输入任务目标。");
  }
  const title = centerWorkspaceTaskTitle(userGoal);
  return {
    user_goal: userGoal,
    original_user_request: userGoal,
    natural_request: userGoal,
    project_brief: userGoal,
    title,
    project_title: title,
    task_graph_title: text(graph?.title, graph?.graph_id ?? ""),
  };
}

export function centerWorkspaceGraphLabel(graph: TaskGraphRecord) {
  return `${text(graph.title, graph.graph_id)} · ${text(graph.graph_id)}`;
}

export function centerWorkspaceGraphSubtitle(graph: TaskGraphRecord) {
  const parts = [centerWorkspaceTaskEnvironmentId(graph), text(graph.publish_state, "draft")].filter(Boolean);
  return parts.join(" / ");
}

function centerWorkspaceTaskTitle(message: string) {
  const firstLine = text(message).split(/\r?\n/)[0]?.trim() ?? "";
  return firstLine.slice(0, 64) || "图任务";
}
