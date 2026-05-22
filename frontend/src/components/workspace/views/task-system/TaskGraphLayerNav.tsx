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
  ShieldAlert,
} from "lucide-react";

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
  category: "builder" | "execution" | "resources" | "validation";
  metric: string;
  state: "ready" | "draft" | "blocked";
  icon: LucideIcon;
};

export const TASK_GRAPH_STUDIO_LAYERS: TaskGraphStudioLayer[] = [
  {
    id: "blueprint",
    title: "图级配置",
    description: "身份、入口、出口、全局策略",
    category: "builder",
    metric: "图级",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "topology",
    title: "Graph Builder",
    description: "唯一可运行结构：节点、边、入口、出口",
    category: "builder",
    metric: "主编辑",
    state: "ready",
    icon: GitBranch,
  },
  {
    id: "modules",
    title: "Compiled View",
    description: "标准视图、端口、图模块展开诊断",
    category: "validation",
    metric: "只读/诊断",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "agents",
    title: "执行者",
    description: "Agent、Projection、运行档案",
    category: "execution",
    metric: "装配",
    state: "draft",
    icon: Network,
  },
  {
    id: "responsibility",
    title: "节点契约",
    description: "输入包、输出契约、Prompt 使用边界",
    category: "execution",
    metric: "语义",
    state: "draft",
    icon: Route,
  },
  {
    id: "timeline",
    title: "生命周期诊断",
    description: "阶段、循环、坐标，只作观察与迁移",
    category: "validation",
    metric: "诊断",
    state: "draft",
    icon: PlayCircle,
  },
  {
    id: "memory",
    title: "资源流",
    description: "仓库、读写边、Snapshot",
    category: "resources",
    metric: "资源",
    state: "draft",
    icon: BrainCircuit,
  },
  {
    id: "risk",
    title: "风险治理",
    description: "线程账本、问题台账、边界风险",
    category: "resources",
    metric: "治理",
    state: "draft",
    icon: ShieldAlert,
  },
  {
    id: "contracts",
    title: "契约与质量门",
    description: "输入输出、载荷、审核标准",
    category: "validation",
    metric: "质量",
    state: "draft",
    icon: FileCheck2,
  },
  {
    id: "publish",
    title: "预检与运行",
    description: "保存、预检、发布、监控",
    category: "validation",
    metric: "闭环",
    state: "draft",
    icon: CheckCircle2,
  },
];

const LAYER_GROUPS: Array<{
  id: TaskGraphStudioLayer["category"];
  title: string;
  description: string;
}> = [
  { id: "builder", title: "主图", description: "canonical 草稿结构" },
  { id: "execution", title: "执行", description: "节点身份与执行契约" },
  { id: "resources", title: "资源", description: "记忆、产物、治理账本" },
  { id: "validation", title: "验证", description: "编译视图、生命周期、发布" },
];

const LAYER_GROUP_LABELS = LAYER_GROUPS.reduce<Record<TaskGraphStudioLayer["category"], string>>((acc, group) => {
  acc[group.id] = group.title;
  return acc;
}, {
  builder: "主图",
  execution: "执行",
  resources: "资源",
  validation: "验证",
});

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
    <nav className="task-graph-layer-nav task-graph-editor-rail" aria-label="多 Agent 任务图层级">
      {layers.map((layer) => {
        const Icon = layer.icon;
        return (
          <button
            aria-current={activeLayer === layer.id ? "page" : undefined}
            className={activeLayer === layer.id ? "task-graph-editor-rail__item task-graph-editor-rail__item--active" : "task-graph-editor-rail__item"}
            key={layer.id}
            onClick={() => onChange(layer.id)}
            title={`${layer.title} · ${layer.description}`}
            type="button"
          >
            <Icon aria-hidden="true" size={16} />
            <strong>{layer.title}</strong>
            <span>{LAYER_GROUP_LABELS[layer.category]}</span>
          </button>
        );
      })}
    </nav>
  );
}

