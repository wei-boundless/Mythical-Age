"use client";

import { GitBranch } from "lucide-react";

import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { buildTaskGraphNameRegistryPayload, taskGraphDisplayName, taskGraphNameRegistry } from "./taskGraphNameRegistry";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphNode } from "./taskGraphTypes";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function TaskGraphBlueprintPage({
  activeGraphNodes,
  taskGraphDraft,
  onOpenTemplateChooser,
  updateTaskGraph,
  updateRuntimePolicy,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  onOpenTemplateChooser: () => void;
  updateTaskGraph: (patch: Partial<TaskGraphDraftV2>) => void;
  updateRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const nodeOptions = activeGraphNodes
    .map((node) => String(node.node_id ?? "").trim())
    .filter(Boolean);
  const metadata = asRecord(taskGraphDraft.metadata);
  const nameRegistry = taskGraphNameRegistry(metadata);
  const phaseDefinitions = Array.isArray(metadata.phase_definitions)
    ? metadata.phase_definitions.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const nodeTitle = (node: Record<string, unknown>) => taskGraphDisplayName(String(node.node_id ?? ""), node, metadata, "节点");
  const syncNameRegistry = () => {
    updateTaskGraph({
      metadata: {
        ...metadata,
        name_registry: buildTaskGraphNameRegistryPayload({
          graphId: taskGraphDraft.graph_id,
          graphTitle: taskGraphDraft.title,
          nodes: activeGraphNodes,
          phases: phaseDefinitions,
        }),
      },
    });
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>图工作台</span>
        <strong>图级配置</strong>
        <small>定义任务图身份、边界节点和全局运行语义；节点、边和图模块协议在对象编辑台维护。</small>
        <TaskSystemToolbarButton onClick={onOpenTemplateChooser}>
          <GitBranch size={14} />切换蓝图模板
        </TaskSystemToolbarButton>
      </header>
      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>图身份</strong></header>
          <div className="boundary-form">
            <TaskSystemField label="任务图标题">
              <input
                onChange={(event) => updateTaskGraph({ title: event.target.value })}
                value={taskGraphDraft.title}
              />
            </TaskSystemField>
            <TaskSystemField label="图 ID">
              <input readOnly value={taskGraphDraft.graph_id} />
            </TaskSystemField>
            <TaskSystemField label="协同任务 ID">
              <input readOnly value={taskGraphDraft.graph_id} />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="图类型"
              onChange={(value) => updateTaskGraph({ graph_kind: value as TaskGraphDraftV2["graph_kind"] })}
              options={["single_agent", "multi_agent", "coordination"]}
              value={taskGraphDraft.graph_kind}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="协作模式"
              onChange={(value) => updateRuntimePolicy({ coordination_mode: value })}
              options={["review_merge", "pipeline", "parallel_review"]}
              value={taskGraphDraft.runtime_policy.coordination_mode}
            />
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>边界节点</strong></header>
          <div className="boundary-form">
            <TaskSystemSelectField
              formatOption={(value) => {
                const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === value);
                return node ? `${nodeTitle(node)} · ${value}` : value;
              }}
              label="入口节点"
              onChange={(value) => updateTaskGraph({ entry_node_id: value })}
              options={nodeOptions}
              value={taskGraphDraft.entry_node_id}
            />
            <TaskSystemSelectField
              formatOption={(value) => {
                const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === value);
                return node ? `${nodeTitle(node)} · ${value}` : value;
              }}
              label="出口节点"
              onChange={(value) => updateTaskGraph({ output_node_id: value })}
              options={nodeOptions}
              value={taskGraphDraft.output_node_id}
            />
          </div>
          <div className="task-graph-note">
            <strong>说明</strong>
            <span>入口/出口现在按 TaskGraph 一等字段编辑，并在迁移期同步镜像到旧草稿。</span>
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>图级运行边界</strong></header>
          <div className="boundary-form">
            <TaskSystemField label="Agent 组">
              <input
                onChange={(event) => updateRuntimePolicy({ agent_group_id: event.target.value })}
                value={taskGraphDraft.runtime_policy.agent_group_id}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="人工接管策略"
              onChange={(value) => updateRuntimePolicy({ human_gate_mode: value })}
              options={["manual_required", "auto_continue", "non_blocking", "disabled"]}
              value={String(taskGraphDraft.runtime_policy.human_gate_mode ?? "manual_required")}
            />
          </div>
          <div className="task-graph-note">
            <strong>资源与上下文不在蓝图页细配</strong>
            <span>蓝图页只保留图身份、边界节点、协作模式和人工接管边界。共享上下文、记忆读写、产物上下文都应进入节点、边、资源和时序对象页配置。</span>
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>中文名注册</strong><span>{nameRegistry.length} 项</span></header>
          <div className="task-graph-note">
            <strong>中文名是图级标准元数据</strong>
            <span>拓扑图、节点列表、阶段图块和预检都优先读取 name_registry，不再由各页面各自猜测显示名。</span>
          </div>
          <TaskSystemToolbarButton onClick={syncNameRegistry} variant="primary">
            同步中文名注册
          </TaskSystemToolbarButton>
          <div className="task-graph-standard-list">
            {nameRegistry.slice(0, 12).map((entry) => (
              <article className="task-graph-standard-list__item" key={`${entry.object_type}:${entry.object_id}`}>
                <strong>{entry.display_name_zh}</strong>
                <span>{entry.object_id}</span>
                <em>{entry.object_type}</em>
              </article>
            ))}
            {!nameRegistry.length ? (
              <div className="task-graph-note">
                <strong>尚未建立中文名注册</strong>
                <span>点击同步后会把图、节点、阶段写入 metadata.name_registry。</span>
              </div>
            ) : null}
          </div>
        </article>
      </section>
      <section className="boundary-card">
        <header><strong>当前节点概览</strong></header>
        <div className="task-graph-simple-table" role="table" aria-label="节点列表">
          <div className="task-graph-simple-table__head" role="row">
            <span role="columnheader">节点</span>
            <span role="columnheader">角色</span>
            <span role="columnheader">Agent</span>
            <span role="columnheader">绑定任务</span>
          </div>
          {activeGraphNodes.map((node, index) => (
            <div className="task-graph-simple-table__row" key={String(node.node_id ?? `node_${index}`)} role="row">
              <span role="cell">{nodeTitle(node)}</span>
              <span role="cell">{String(node.role ?? node.work_posture ?? "-")}</span>
              <span role="cell">{String(node.agent_id ?? "-")}</span>
              <span role="cell">{String((node as TaskGraphNode).task_id ?? "-")}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
