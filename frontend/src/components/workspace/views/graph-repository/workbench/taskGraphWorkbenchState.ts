"use client";

import type { LucideIcon } from "lucide-react";
import { Boxes, FolderGit2, LayoutTemplate, RadioTower } from "lucide-react";

export type TaskGraphWorkbenchContext = "templates" | "graphs" | "editor" | "monitor";

export type TaskGraphWorkbenchCounts = {
  templates: number;
  graphs: number;
  instances: number;
};

export type TaskGraphWorkbenchTab = {
  context: TaskGraphWorkbenchContext;
  label: string;
  detail: string;
  icon: LucideIcon;
  kind: "resource" | "mode";
  countKey?: keyof TaskGraphWorkbenchCounts;
};

export const taskGraphWorkbenchTabs: TaskGraphWorkbenchTab[] = [
  { context: "templates", label: "模板库", detail: "资源入口", icon: LayoutTemplate, kind: "resource", countKey: "templates" },
  { context: "graphs", label: "图定义", detail: "定义管理", icon: FolderGit2, kind: "resource", countKey: "graphs" },
  { context: "editor", label: "编辑态", detail: "配置任务图", icon: Boxes, kind: "mode" },
  { context: "monitor", label: "监控态", detail: "运行项目", icon: RadioTower, kind: "mode", countKey: "instances" },
];

export type TaskGraphBreadcrumbSegment = {
  label: string;
  value: string;
};
