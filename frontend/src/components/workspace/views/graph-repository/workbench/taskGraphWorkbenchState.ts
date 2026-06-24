"use client";

import type { LucideIcon } from "lucide-react";
import { Boxes, FolderGit2, LayoutTemplate, PlaySquare, RadioTower } from "lucide-react";

export type TaskGraphWorkbenchContext = "templates" | "graphs" | "editor" | "instances" | "runtime";

export type TaskGraphWorkbenchCounts = {
  templates: number;
  graphs: number;
  instances: number;
  runs: number;
};

export type TaskGraphWorkbenchTab = {
  context: TaskGraphWorkbenchContext;
  label: string;
  detail: string;
  icon: LucideIcon;
  countKey?: keyof TaskGraphWorkbenchCounts;
};

export const taskGraphWorkbenchTabs: TaskGraphWorkbenchTab[] = [
  { context: "templates", label: "模板库", detail: "配置种子", icon: LayoutTemplate, countKey: "templates" },
  { context: "graphs", label: "图定义", detail: "保存与发布", icon: FolderGit2, countKey: "graphs" },
  { context: "editor", label: "编辑器", detail: "画布底板", icon: Boxes },
  { context: "instances", label: "实例", detail: "运行空间", icon: PlaySquare, countKey: "instances" },
  { context: "runtime", label: "运行投影", detail: "多 Agent 观察", icon: RadioTower, countKey: "runs" },
];

export type TaskGraphBreadcrumbSegment = {
  label: string;
  value: string;
};
