"use client";

import { GitBranch } from "lucide-react";

import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphNode } from "./taskGraphTypes";

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

export function TaskGraphBlueprintPage({
  activeGraphNodes,
  taskGraphDraft,
  onOpenTemplateChooser,
  updateTaskGraph,
  updateRuntimePolicy,
  updateContextPolicy,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  onOpenTemplateChooser: () => void;
  updateTaskGraph: (patch: Partial<TaskGraphDraftV2>) => void;
  updateRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
  updateContextPolicy: (patch: Partial<TaskGraphDraftV2["context_policy"]>) => void;
}) {
  const nodeOptions = activeGraphNodes
    .map((node) => String(node.node_id ?? "").trim())
    .filter(Boolean);

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>任务蓝图</strong>
        <small>定义任务图身份、边界节点和全局运行语义。</small>
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
          <header><strong>全局策略</strong></header>
          <div className="boundary-form">
            <TaskSystemField label="共享上下文策略">
              <input
                onChange={(event) => updateContextPolicy({ shared_context_policy: event.target.value })}
                value={taskGraphDraft.context_policy.shared_context_policy}
              />
            </TaskSystemField>
            <TaskSystemField label="记忆共享策略">
              <input
                onChange={(event) => updateContextPolicy({ memory_sharing_policy: event.target.value })}
                value={taskGraphDraft.context_policy.memory_sharing_policy}
              />
            </TaskSystemField>
            <TaskSystemField label="交接策略">
              <input
                onChange={(event) => updateContextPolicy({ handoff_policy: event.target.value })}
                value={String(taskGraphDraft.context_policy.handoff_policy ?? "")}
              />
            </TaskSystemField>
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
            <strong>人工接管由任务图装配决定</strong>
            <span>选择“人工确认后继续”时，人工门控会阻塞运行；选择“自动继续”或“非阻塞记录”时，运行时不会因为人工接管停住。</span>
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
