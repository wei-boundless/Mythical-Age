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
    summary: "给当前图节点绑定执行器、Agent、Projection 与运行场景权限引用。",
    checkpoints: ["执行器", "Agent 引用", "Projection"],
  },
  topology: {
    title: "快速拓扑",
    summary: "快速维护业务节点和基础交接边，复杂对象配置进入图工作台。",
    checkpoints: ["节点", "基础边", "快捷结构"],
  },
  modules: {
    title: "图工作台",
    summary: "左侧管理图层关系，中间编辑任务图画布，右侧配置选中对象的契约、时序和运行协议。",
    checkpoints: ["图层关系", "任务图画布", "对象编辑台"],
  },
  responsibility: {
    title: "节点认知包",
    summary: "把节点身份、输入包、输出契约和 Prompt 使用方式配成同一个执行视图。",
    checkpoints: ["身份投影", "输入包", "输出交接"],
  },
  timeline: {
    title: "拓扑时序控制",
    summary: "从主链、阶段、循环框、并发组和审核回退编译运行位置与执行许可。",
    checkpoints: ["主链", "循环展开", "执行许可"],
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
  onSendToChat,
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
  onSendToChat: () => void;
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
        onSendToChat={onSendToChat}
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
