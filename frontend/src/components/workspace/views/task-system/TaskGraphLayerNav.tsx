"use client";

import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  BrainCircuit,
  CheckCircle2,
  FileCheck2,
  GitBranch,
  Network,
  PlayCircle,
  Route,
} from "lucide-react";

export type TaskGraphStudioLayerId =
  | "blueprint"
  | "agents"
  | "topology"
  | "responsibility"
  | "timeline"
  | "memory"
  | "contracts"
  | "publish";

export type TaskGraphStudioLayer = {
  id: TaskGraphStudioLayerId;
  title: string;
  description: string;
  metric: string;
  state: "ready" | "draft" | "blocked";
  icon: LucideIcon;
};

export const TASK_GRAPH_STUDIO_LAYERS: TaskGraphStudioLayer[] = [
  {
    id: "blueprint",
    title: "任务蓝图",
    description: "身份、入口、出口、运行模式",
    metric: "图级",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "agents",
    title: "Agent 编组",
    description: "协调者、参与者、职责边界",
    metric: "角色",
    state: "draft",
    icon: Network,
  },
  {
    id: "topology",
    title: "拓扑编排",
    description: "节点、边、画布和快速结构",
    metric: "画布",
    state: "ready",
    icon: GitBranch,
  },
  {
    id: "responsibility",
    title: "职责与交接",
    description: "节点职责、边交接契约",
    metric: "语义",
    state: "draft",
    icon: Route,
  },
  {
    id: "timeline",
    title: "时序与循环",
    description: "阶段、并行、审核门、返修",
    metric: "生命周期",
    state: "draft",
    icon: PlayCircle,
  },
  {
    id: "memory",
    title: "记忆与产物",
    description: "上下文、工作记忆、产物落盘",
    metric: "边界",
    state: "draft",
    icon: BrainCircuit,
  },
  {
    id: "contracts",
    title: "契约与质量门",
    description: "输入输出、载荷、审核标准",
    metric: "质量",
    state: "draft",
    icon: FileCheck2,
  },
  {
    id: "publish",
    title: "预检与运行",
    description: "保存、预检、发布、监控",
    metric: "闭环",
    state: "draft",
    icon: CheckCircle2,
  },
];

export function TaskGraphLayerNav({
  activeLayer,
  layers = TASK_GRAPH_STUDIO_LAYERS,
  onChange,
}: {
  activeLayer: TaskGraphStudioLayerId;
  layers?: TaskGraphStudioLayer[];
  onChange: (layer: TaskGraphStudioLayerId) => void;
}) {
  return (
    <nav className="task-graph-layer-nav" aria-label="多 Agent 任务图层级">
      {layers.map((layer) => {
        const Icon = layer.icon;
        return (
          <button
            aria-current={activeLayer === layer.id ? "page" : undefined}
            className={activeLayer === layer.id ? "task-graph-layer-card task-graph-layer-card--active" : "task-graph-layer-card"}
            key={layer.id}
            onClick={() => onChange(layer.id)}
            type="button"
          >
            <Icon aria-hidden="true" size={16} />
            <span>
              <strong>{layer.title}</strong>
              <small>{layer.description}</small>
            </span>
            <em className={`task-graph-layer-card__state task-graph-layer-card__state--${layer.state}`}>{layer.metric}</em>
          </button>
        );
      })}
    </nav>
  );
}
