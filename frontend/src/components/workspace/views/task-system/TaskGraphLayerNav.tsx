"use client";

import type { LucideIcon } from "lucide-react";
import { FileSearch, GitBranch, PlayCircle } from "lucide-react";

export type TaskGraphStudioLayerId =
  | "blueprint"
  | "agents"
  | "topology"
  | "modules"
  | "responsibility"
  | "timeline"
  | "memory"
  | "risk"
  | "contracts"
  | "publish";

export type TaskGraphStudioLayer = {
  id: TaskGraphStudioLayerId;
  title: string;
  description: string;
  metric: string;
  icon: LucideIcon;
};

export const TASK_GRAPH_STUDIO_LAYERS: TaskGraphStudioLayer[] = [
  {
    id: "topology",
    title: "编辑工作台",
    description: "用语义动作创建节点、关系、记忆和产物配置。",
    metric: "编辑",
    icon: GitBranch,
  },
  {
    id: "modules",
    title: "检查修复",
    description: "按问题定位对象，自动修复可推导的缺失项。",
    metric: "预检",
    icon: FileSearch,
  },
  {
    id: "publish",
    title: "发布运行",
    description: "保存、编译图契约、启动运行并绑定监控。",
    metric: "运行",
    icon: PlayCircle,
  },
];

function workspaceLayerFor(activeLayer: TaskGraphStudioLayerId): TaskGraphStudioLayerId {
  if (activeLayer === "publish") return "publish";
  if (activeLayer === "topology" || activeLayer === "blueprint") return "topology";
  return "modules";
}

export function TaskGraphLayerNav({
  activeLayer,
  layers = TASK_GRAPH_STUDIO_LAYERS,
  onChange,
}: {
  activeLayer: TaskGraphStudioLayerId;
  layers?: TaskGraphStudioLayer[];
  onChange: (layer: TaskGraphStudioLayerId) => void;
}) {
  const activeWorkspace = workspaceLayerFor(activeLayer);
  return (
    <nav className="task-graph-layer-nav task-graph-layer-nav--workspaces" aria-label="任务图工作区">
      {layers.map((layer) => {
        const Icon = layer.icon;
        return (
          <button
            aria-current={activeWorkspace === layer.id ? "page" : undefined}
            className={activeWorkspace === layer.id ? "task-graph-layer-card task-graph-layer-card--active" : "task-graph-layer-card"}
            key={layer.id}
            onClick={() => onChange(layer.id)}
            title={`${layer.title} · ${layer.description}`}
            type="button"
          >
            <Icon aria-hidden="true" size={16} />
            <span>
              <strong>{layer.title}</strong>
              <small>{layer.description}</small>
            </span>
            <i className="task-graph-layer-card__state task-graph-layer-card__state--ready">{layer.metric}</i>
          </button>
        );
      })}
    </nav>
  );
}
