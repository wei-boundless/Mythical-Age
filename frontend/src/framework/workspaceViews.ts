import { Database, HeartPulse, LayoutGrid, MessageSquare, Network, Settings, Workflow, type LucideIcon } from "lucide-react";

import type { WorkspaceView } from "@/lib/store/types";

export const WORKSPACE_VIEW_VALUES = [
  "chat",
  "creative",
  "memory",
  "health-system",
  "capability-system",
  "task-system",
  "orchestration",
  "code-environment",
  "system-config",
] as const satisfies readonly WorkspaceView[];

export const WORKSPACE_QUERY_VIEW_VALUES = WORKSPACE_VIEW_VALUES;

export const WORKSPACE_QUERY_VIEWS: ReadonlySet<WorkspaceView> = new Set(WORKSPACE_QUERY_VIEW_VALUES);

export const WORKSPACE_TONES: ReadonlySet<string> = new Set(["water", "leaf", "gold", "ember", "lumen"]);

export const TASK_ENVIRONMENT_VIEWS: ReadonlySet<WorkspaceView> = new Set(["chat", "code-environment"]);

export type SystemNavItem = {
  icon: LucideIcon;
  label: string;
  view: WorkspaceView;
};

export const SYSTEM_NAV_ITEMS = [
  { view: "chat", label: "工作台", icon: MessageSquare },
  { view: "creative", label: "图任务", icon: Workflow },
  { view: "memory", label: "记忆", icon: Database },
  { view: "task-system", label: "任务系统", icon: Workflow },
  { view: "orchestration", label: "编排", icon: Network },
  { view: "capability-system", label: "能力", icon: LayoutGrid },
  { view: "health-system", label: "健康", icon: HeartPulse },
  { view: "system-config", label: "配置", icon: Settings },
] as const satisfies readonly SystemNavItem[];

export function isWorkspaceView(value: string | null | undefined): value is WorkspaceView {
  return typeof value === "string" && WORKSPACE_QUERY_VIEWS.has(value as WorkspaceView);
}

export function isWorkspaceQueryView(value: string | null | undefined): value is WorkspaceView {
  return isWorkspaceView(value);
}

export function shouldShowTaskGraphRunInteractionDock(view: WorkspaceView) {
  return view === "task-system" || view === "creative";
}
