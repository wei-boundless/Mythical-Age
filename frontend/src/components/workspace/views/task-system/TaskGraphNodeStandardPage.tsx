"use client";

import { useMemo } from "react";

import type { TaskGraphStandardView } from "@/lib/api";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function nodeIdOf(node: Record<string, unknown>, index = 0) {
  return stringValue(node.node_id ?? node.id, `node_${index + 1}`);
}

function nodeTitle(node: Record<string, unknown>, index = 0) {
  return stringValue(node.title ?? node.label ?? node.task_title, nodeIdOf(node, index));
}

function standardNodeById(standardView: TaskGraphStandardView | null) {
  return new Map((standardView?.nodes ?? []).map((node) => [node.node_id, node]));
}

function issueCountForNode(standardView: TaskGraphStandardView | null, nodeId: string) {
  return (standardView?.issues ?? []).filter((issue) => issue.node_id === nodeId).length;
}

export function TaskGraphNodeStandardPage({
  activeGraphNodes,
  selectedGraphNode,
  selectedGraphNodeId,
  standardView,
  editorFocus,
  onEditorFocus,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphNodeId: string;
  standardView: TaskGraphStandardView | null;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const standardNodes = useMemo(() => standardNodeById(standardView), [standardView]);
  const focusNodeId = selectedGraphNodeId || activeGraphNodes[0]?.node_id || "";
  const currentNode = selectedGraphNode ?? activeGraphNodes.find((node, index) => nodeIdOf(node, index) === focusNodeId) ?? null;
  const currentNodeId = currentNode ? nodeIdOf(currentNode) : "";
  const standardNode = currentNodeId ? standardNodes.get(currentNodeId) ?? null : null;
  const executor = asRecord(standardNode?.executor);
  const contracts = asRecord(standardNode?.contracts);
  const runtime = asRecord(standardNode?.runtime);
  const artifacts = asRecord(standardNode?.artifacts);
  const loop = asRecord(standardNode?.loop);

  return (
    <section className="task-graph-cognition-workbench">
      <aside className="task-graph-cognition-workbench__nav boundary-card">
        <header><strong>节点对象</strong><span>{activeGraphNodes.length} nodes</span></header>
        <div className="task-graph-cognition-phase-list">
          {activeGraphNodes.map((node, index) => {
            const nodeId = nodeIdOf(node, index);
            const active = nodeId === currentNodeId;
            return (
              <button
                className={active ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                key={nodeId}
                onClick={() => onEditorFocus?.({ layer: "responsibility", facet: "node_standard", node_id: nodeId })}
                type="button"
              >
                <strong>{nodeTitle(node, index)}</strong>
                <span>{nodeId}</span>
                <em>{stringValue(node.node_type, "agent_role")} / {stringValue(node.phase_id, "phase.unassigned")} / {issueCountForNode(standardView, nodeId)} issues</em>
              </button>
            );
          })}
        </div>
      </aside>

      <div className="task-graph-cognition-workbench__main">
        <article className="boundary-card">
          <header><strong>节点标准对象</strong><span>{currentNodeId || "未选择节点"}</span></header>
          {currentNode && currentNodeId ? (
            <div className="boundary-form">
              <TaskSystemField label="节点标题">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { title: event.target.value })}
                  value={nodeTitle(currentNode)}
                />
              </TaskSystemField>
              <TaskSystemField label="节点 ID">
                <input disabled value={currentNodeId} />
              </TaskSystemField>
              <TaskSystemSelectField
                label="节点类型"
                onChange={(value) => updateTaskGraphNode(currentNodeId, { node_type: value })}
                options={["agent_role", "review_gate", "loop_frame", "memory_repository", "artifact_repository", "thread_ledger", "issue_ledger", "runtime_state_store", "manual_gate"]}
                value={stringValue(currentNode.node_type, "agent_role")}
              />
              <TaskSystemField label="任务引用">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { task_id: event.target.value })}
                  value={stringValue(currentNode.task_id)}
                />
              </TaskSystemField>
              <TaskSystemField label="Agent ID">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { agent_id: event.target.value })}
                  value={stringValue(currentNode.agent_id)}
                />
              </TaskSystemField>
              <TaskSystemField label="Projection ID">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { projection_id: event.target.value })}
                  value={stringValue(currentNode.projection_id)}
                />
              </TaskSystemField>
              <TaskSystemField label="阶段">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { phase_id: event.target.value })}
                  value={stringValue(currentNode.phase_id)}
                />
              </TaskSystemField>
              <TaskSystemSelectField
                label="执行模式"
                onChange={(value) => updateTaskGraphNode(currentNodeId, { execution_mode: value })}
                options={["sync", "async", "parallel", "background", "barrier", "manual_gate"]}
                value={stringValue(currentNode.execution_mode, "sync")}
              />
              <TaskSystemSelectField
                label="等待策略"
                onChange={(value) => updateTaskGraphNode(currentNodeId, { wait_policy: value })}
                options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "manual_release"]}
                value={stringValue(currentNode.wait_policy, "wait_all_upstream_completed")}
              />
              <TaskSystemSelectField
                label="汇合策略"
                onChange={(value) => updateTaskGraphNode(currentNodeId, { join_policy: value })}
                options={["all_success", "any_success", "allow_partial_with_issues", "coordinator_decides", "fail_on_any_error"]}
                value={stringValue(currentNode.join_policy, "all_success")}
              />
              <TaskSystemField label="产物目标">
                <input
                  onChange={(event) => updateTaskGraphNode(currentNodeId, { artifact_target: event.target.value })}
                  value={stringValue(currentNode.artifact_target)}
                />
              </TaskSystemField>
              <div className="task-graph-note">
                <strong>节点不声明隐式执行链</strong>
                <span>节点页只维护身份、执行者、运行策略和产物目标；执行因果、阻塞和汇合应通过 canonical 边、barrier/manual_gate 节点及等待/汇合策略表达。</span>
              </div>
            </div>
          ) : (
            <div className="task-graph-note">
              <strong>未选择节点</strong>
              <span>节点对象页负责节点身份、执行者、运行和产物目标，不直接承担复杂资源边配置。</span>
            </div>
          )}
        </article>
      </div>

      <aside className="task-graph-cognition-workbench__aside">
        <article className="boundary-card">
          <header><strong>标准对象投影</strong><span>{standardNode?.node_id || "未加载"}</span></header>
          {standardNode ? (
            <>
              <div className="task-graph-mini-kv">
                <p><span>执行者</span><strong>{stringValue(executor.agent_id || executor.agent_group_id, "未绑定")}</strong></p>
                <p><span>节点契约</span><strong>{stringValue(contracts.node_contract_id, "未绑定")}</strong></p>
                <p><span>输入契约</span><strong>{stringValue(contracts.input_contract_id, "未绑定")}</strong></p>
                <p><span>输出契约</span><strong>{stringValue(contracts.output_contract_id, "未绑定")}</strong></p>
                <p><span>运行模式</span><strong>{stringValue(runtime.execution_mode, "sync")}</strong></p>
                <p><span>产物目标</span><strong>{stringValue(artifacts.artifact_target || artifacts.output_path, "未设置")}</strong></p>
              </div>
              <div className="task-graph-note">
                <strong>循环与运行语义</strong>
                <span>{loop.loop_kind ? `loop=${stringValue(loop.loop_kind)}` : `wait=${stringValue(runtime.wait_policy, "wait_all_upstream_completed")} / join=${stringValue(runtime.join_policy, "all_success")}`}</span>
              </div>
            </>
          ) : (
            <div className="task-graph-note">
              <strong>标准视图尚未对齐到该节点</strong>
              <span>保存或刷新标准对象视图后，这里会显示后端编译出来的节点标准对象投影。</span>
            </div>
          )}
        </article>
        {editorFocus?.issue_id ? (
          <article className="boundary-card">
            <header><strong>当前诊断焦点</strong></header>
            <div className="task-graph-note">
              <strong>{editorFocus.issue_id}</strong>
              <span>当前节点对象页已经按焦点节点打开，优先核对执行者、契约、运行语义和产物目标。</span>
            </div>
          </article>
        ) : null}
      </aside>
    </section>
  );
}
