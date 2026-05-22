"use client";

import type { ReactNode } from "react";

import type { TaskGraphExecutionPackage } from "@/lib/api";

import { TaskGraphExecutionDock } from "./TaskGraphExecutionDock";
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
    summary: "给当前图模块绑定执行器、Agent、Projection 与运行场景权限引用。",
    checkpoints: ["执行器", "Agent 引用", "Projection"],
  },
  topology: {
    title: "Graph Builder",
    summary: "维护当前任务图唯一可运行结构：canonical nodes、edges、入口、出口和图模块占位。",
    checkpoints: ["canonical 节点", "canonical 边", "入口/出口"],
  },
  modules: {
    title: "Compiled View",
    summary: "查看后端标准视图、端口映射和图模块展开；这里用于诊断，不作为第二套运行图真相。",
    checkpoints: ["标准视图", "端口诊断", "图模块展开"],
  },
  responsibility: {
    title: "节点认知包",
    summary: "把节点身份、输入包、输出契约和 Prompt 使用方式配成同一个执行视图。",
    checkpoints: ["身份投影", "输入包", "输出交接"],
  },
  timeline: {
    title: "生命周期诊断",
    summary: "查看阶段、循环和旧坐标如何进入诊断；节点 ready/blocked 仍由显式依赖边和运行边界决定。",
    checkpoints: ["生命周期坐标", "循环", "运行诊断"],
  },
  memory: {
    title: "资源流",
    summary: "用仓库节点、collection、读写边、selector 和提交条件控制节点上下文。",
    checkpoints: ["仓库结构", "读写边", "Snapshot"],
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
    title: "发布闭环",
    summary: "执行预检、保存、发布、运行绑定和监控诊断，确认配置能被 runtime 消费。",
    checkpoints: ["预检", "发布", "监控"],
  },
};

export function TaskGraphStudioShell({
  activeLayer,
  children,
  coordinatorAgentId,
  dirty,
  edgeCount,
  editorFocus,
  executionPackage,
  executionPackageError,
  executionPackageLoading,
  graphId,
  issueCount,
  nodeCount,
  onCompileExecutionPackage,
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
  executionPackage: TaskGraphExecutionPackage | null;
  executionPackageError?: string;
  executionPackageLoading: boolean;
  graphId: string;
  issueCount: number;
  nodeCount: number;
  onCompileExecutionPackage: () => void;
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
          <section className="task-graph-layer-strip" aria-label="当前编辑层级">
            <div>
              <span>{activeLayerMeta?.metric || "图层"}</span>
              <strong>{layerContext.title}</strong>
              <small>{layerContext.summary}</small>
            </div>
            <ul>
              {layerContext.checkpoints.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          {children}
        </main>
      </div>
      <TaskGraphExecutionDock
        activeLayer={activeLayer}
        dirty={dirty}
        editorFocus={editorFocus}
        error={executionPackageError}
        executionPackage={executionPackage}
        graphId={graphId}
        loading={executionPackageLoading}
        onCompile={onCompileExecutionPackage}
      />
      <TaskGraphIssueBar dirty={dirty} issueCount={issueCount} publishState={publishState} valid={valid} />
    </section>
  );
}
