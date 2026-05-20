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
  category: "foundation" | "structure" | "runtime" | "quality";
  metric: string;
  state: "ready" | "draft" | "blocked";
  icon: LucideIcon;
};

export const TASK_GRAPH_STUDIO_LAYERS: TaskGraphStudioLayer[] = [
  {
    id: "blueprint",
    title: "图级配置",
    description: "身份、入口、出口、运行模式",
    category: "foundation",
    metric: "图级",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "agents",
    title: "节点装配",
    description: "执行器、Agent、Projection 引用",
    category: "foundation",
    metric: "装配",
    state: "draft",
    icon: Network,
  },
  {
    id: "topology",
    title: "快速拓扑",
    description: "节点、边和快捷结构",
    category: "structure",
    metric: "画布",
    state: "ready",
    icon: GitBranch,
  },
  {
    id: "modules",
    title: "图工作台",
    description: "图层、画布、对象编辑台",
    category: "structure",
    metric: "图化",
    state: "ready",
    icon: Boxes,
  },
  {
    id: "responsibility",
    title: "节点认知包",
    description: "身份、输入包、输出交接",
    category: "structure",
    metric: "语义",
    state: "draft",
    icon: Route,
  },
  {
    id: "timeline",
    title: "拓扑时序",
    description: "主链、阶段、循环、许可",
    category: "runtime",
    metric: "生命周期",
    state: "draft",
    icon: PlayCircle,
  },
  {
    id: "memory",
    title: "资源流",
    description: "仓库、读写边、Snapshot",
    category: "runtime",
    metric: "资源",
    state: "draft",
    icon: BrainCircuit,
  },
  {
    id: "risk",
    title: "风险治理",
    description: "线程账本、问题台账、边界风险",
    category: "quality",
    metric: "治理",
    state: "draft",
    icon: ShieldAlert,
  },
  {
    id: "contracts",
    title: "契约与质量门",
    description: "输入输出、载荷、审核标准",
    category: "quality",
    metric: "质量",
    state: "draft",
    icon: FileCheck2,
  },
  {
    id: "publish",
    title: "预检与运行",
    description: "保存、预检、发布、监控",
    category: "quality",
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
  { id: "foundation", title: "基础", description: "图身份、节点装配、运行入口" },
  { id: "structure", title: "结构", description: "执行拓扑和语义交接" },
  { id: "runtime", title: "运行", description: "时序、循环、记忆、产物" },
  { id: "quality", title: "质量", description: "契约、预检、发布" },
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
  const layersByGroup = new Map<TaskGraphStudioLayer["category"], TaskGraphStudioLayer[]>();
  for (const layer of layers) {
    layersByGroup.set(layer.category, [...(layersByGroup.get(layer.category) ?? []), layer]);
  }
  return (
    <nav className="task-graph-layer-nav" aria-label="多 Agent 任务图层级">
      {LAYER_GROUPS.map((group) => {
        const groupLayers = layersByGroup.get(group.id) ?? [];
        if (!groupLayers.length) return null;
        return (
          <section className="task-graph-layer-group" key={group.id}>
            <header>
              <strong>{group.title}</strong>
              <span>{group.description}</span>
            </header>
            <div className="task-graph-layer-group__grid">
              {groupLayers.map((layer) => {
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
            </div>
          </section>
        );
      })}
    </nav>
  );
}

