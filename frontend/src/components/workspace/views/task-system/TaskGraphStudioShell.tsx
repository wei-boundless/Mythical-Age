"use client";

import type { ReactNode } from "react";

import { TaskGraphIssueBar } from "./TaskGraphIssueBar";
import { TASK_GRAPH_STUDIO_LAYERS, TaskGraphLayerNav, type TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphTopBar } from "./TaskGraphTopBar";
import type { TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";

const LAYER_CONTEXT: Record<TaskGraphStudioLayerId, { title: string; summary: string; checkpoints: string[] }> = {
  blueprint: {
    title: "图级配置",
    summary: "定义任务图身份、边界、入口出口和全局运行策略。",
    checkpoints: ["入口/出口", "运行模式", "上下文策略"],
  },
  agents: {
    title: "节点装配",
    summary: "给当前图模块绑定执行器、Agent、运行档案与模型能力需求。",
    checkpoints: ["执行器", "Agent 引用", "运行档案"],
  },
  topology: {
    title: "拓扑编辑",
    summary: "维护当前任务图唯一可运行结构：规范节点、边、入口、出口和图模块占位。",
    checkpoints: ["canonical 节点", "canonical 边", "入口/出口"],
  },
  modules: {
    title: "图契约",
    summary: "查看 TaskGraphDefinition 编译后的 GraphHarnessConfig、调度视图和图模块展开；这里只读诊断，不作为第二套运行图真相。",
    checkpoints: ["GraphHarnessConfig", "调度视图", "图模块展开"],
  },
  responsibility: {
    title: "节点认知包",
    summary: "把节点身份、输入包、输出契约和 Prompt 使用方式配成同一个执行视图。",
    checkpoints: ["角色 Prompt", "输入包", "输出交接"],
  },
  timeline: {
    title: "阶段与循环",
    summary: "维护阶段、时序坐标、循环、审核返修和批次推进配置。",
    checkpoints: ["阶段", "循环", "返修"],
  },
  memory: {
    title: "资源流",
    summary: "用仓库节点、collection、读写边、selector 和提交条件控制节点上下文。",
    checkpoints: ["仓库结构", "读写边", "Checkpoint"],
  },
  risk: {
    title: "风险治理",
    summary: "把长线程续接、问题闭环和上下文边界风险从资源流中拆成独立治理层。",
    checkpoints: ["线程账本", "问题台账", "边界风险"],
  },
  contracts: {
    title: "质量边界",
    summary: "管理输入输出契约、载荷契约、质量门和失败策略。",
    checkpoints: ["输入输出", "审核门", "失败策略"],
  },
  publish: {
    title: "发布运行",
    summary: "完成预检、发布 GraphHarnessConfig、启动 GraphRun 并绑定监控。",
    checkpoints: ["预检", "发布", "运行"],
  },
};

export function TaskGraphStudioShell({
  activeLayer,
  children,
  coordinatorAgentId,
  dirty,
  edgeCount,
  editorFocus,
  graphId,
  issueCount,
  nodeCount,
  onLayerChange,
  onPublish,
  onSave,
  publishState,
  saving,
  title,
  valid,
  workspaceSlot,
}: {
  activeLayer: TaskGraphStudioLayerId;
  children: ReactNode;
  coordinatorAgentId: string;
  dirty: boolean;
  edgeCount: number;
  editorFocus: TaskGraphEditorFocus;
  graphId: string;
  issueCount: number;
  nodeCount: number;
  onLayerChange: (layer: TaskGraphStudioLayerId) => void;
  onPublish: () => void;
  onSave: () => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  title: string;
  valid: boolean;
  workspaceSlot?: ReactNode;
}) {
  const activeLayerMeta = TASK_GRAPH_STUDIO_LAYERS.find((layer) => layer.id === activeLayer);
  const layerContext = LAYER_CONTEXT[activeLayer];
  return (
    <section className={workspaceSlot ? "task-graph-studio-shell task-graph-studio-shell--with-workspace" : "task-graph-studio-shell"} aria-label="多 Agent 持续任务编排平台">
      <TaskGraphTopBar
        coordinatorAgentId={coordinatorAgentId}
        edgeCount={edgeCount}
        graphId={graphId}
        issueCount={issueCount}
        nodeCount={nodeCount}
        onPublish={onPublish}
        onSave={onSave}
        publishState={publishState}
        saving={saving}
        title={title}
        valid={valid}
      />
      {workspaceSlot ? (
        <section className="task-graph-studio-workspace-strip" aria-label="任务图工作集">
          {workspaceSlot}
        </section>
      ) : null}
      <div className="task-graph-studio-shell__body">
        <TaskGraphLayerNav activeLayer={activeLayer} onChange={onLayerChange} />
        <main className="task-graph-studio-shell__page">
          <section className="task-graph-layer-strip task-graph-editor-context" aria-label="当前编辑层级">
            <div>
              <span>{activeLayerMeta?.metric || "图层"}</span>
              <strong>{layerContext.title}</strong>
              <small>{layerContext.summary}</small>
            </div>
            <ul aria-label="当前层检查点">
              {layerContext.checkpoints.map((checkpoint) => (
                <li key={checkpoint}>{checkpoint}</li>
              ))}
            </ul>
          </section>
          {children}
        </main>
      </div>
      <TaskGraphIssueBar dirty={dirty} issueCount={issueCount} publishState={publishState} valid={valid} />
    </section>
  );
}
