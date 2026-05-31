"use client";

import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  BrainCircuit,
  CalendarClock,
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
    title: "拓扑编辑",
    description: "唯一可运行结构：节点、边、入口、出口",
    category: "builder",
    metric: "主编辑",
    state: "ready",
    icon: GitBranch,
  },
  {
    id: "modules",
    title: "图契约",
    description: "编译后的图契约、调度视图、图模块展开结果",
    category: "validation",
    metric: "契约",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "agents",
    title: "执行者",
    description: "Agent、运行档案、模型需求",
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
    title: "阶段与循环",
    description: "阶段、循环、审核返修、批次推进",
    category: "validation",
    metric: "生命周期",
    state: "draft",
    icon: CalendarClock,
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
    title: "发布运行",
    description: "预检、发布、启动、监控",
    category: "validation",
    metric: "运行",
    state: "draft",
    icon: PlayCircle,
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
      {LAYER_GROUPS.map((group) => {
        const groupedLayers = layers.filter((layer) => layer.category === group.id);
        if (!groupedLayers.length) {
          return null;
        }
        return (
          <section className="task-graph-layer-group" key={group.id}>
            <header>
              <strong>{group.title}</strong>
              <span>{group.description}</span>
            </header>
            <div className="task-graph-layer-group__grid">
              {groupedLayers.map((layer) => {
                const Icon = layer.icon;
                return (
                  <button
                    aria-current={activeLayer === layer.id ? "page" : undefined}
                    className={activeLayer === layer.id ? "task-graph-layer-card task-graph-layer-card--active" : "task-graph-layer-card"}
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
                    <i className={`task-graph-layer-card__state task-graph-layer-card__state--${layer.state}`}>
                      {layer.metric}
                    </i>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </nav>
  );
}

