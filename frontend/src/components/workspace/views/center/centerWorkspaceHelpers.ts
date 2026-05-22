import type { TaskGraphRecord, TaskSystemOverview } from "@/lib/api";
import { recommendedTaskGraphId, sortTaskGraphsForWorkbench } from "../task-system/taskGraphSelection";

export type CenterWorkspaceLayer = "chat" | "task-graph";
const FALLBACK_TASK_GRAPH_SESSION_ID = "task_graph_studio";

function text(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

export function listCenterWorkspaceTaskGraphs(overview: TaskSystemOverview | null | undefined) {
  return sortTaskGraphsForWorkbench(overview?.task_graph_management?.task_graphs ?? []);
}

export function resolveCenterWorkspaceSelectedGraphId(overview: TaskSystemOverview | null | undefined, currentGraphId = "") {
  const graphs = listCenterWorkspaceTaskGraphs(overview);
  const current = text(currentGraphId);
  if (current && graphs.some((graph) => graph.graph_id === current)) {
    return current;
  }
  return recommendedTaskGraphId(graphs);
}

export function centerWorkspaceTaskGraphSessionId(sessionId: string | null | undefined) {
  const normalized = text(sessionId).replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 80);
  return normalized || FALLBACK_TASK_GRAPH_SESSION_ID;
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
  const parts = [text(graph.domain_id), text(graph.task_family), text(graph.publish_state, "draft")].filter(Boolean);
  return parts.join(" / ");
}

function centerWorkspaceTaskTitle(message: string) {
  const firstLine = text(message).split(/\r?\n/)[0]?.trim() ?? "";
  return firstLine.slice(0, 64) || "图任务";
}
