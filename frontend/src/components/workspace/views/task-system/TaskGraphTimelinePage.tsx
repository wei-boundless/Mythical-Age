"use client";

import { PhaseLifecycleEditor } from "./PhaseLifecycleEditor";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { buildTimelinePhases, buildTimelinePreflightIssues, coordinationPhaseDefinitions } from "./taskGraphTimeline";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

export function TaskGraphTimelinePage({
  activeGraphNodes,
  activeGraphEdges,
  taskGraphDraft,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const metadata = asRecord(taskGraphDraft.metadata);
  const timelinePolicy = asRecord(metadata.timeline_policy);
  const phaseDefinitions = coordinationPhaseDefinitions(metadata, activeGraphNodes);
  const timelineIssues = buildTimelinePreflightIssues(activeGraphNodes, activeGraphEdges, metadata);
  const issueByPhase = new Map<string, typeof timelineIssues>();
  for (const issue of timelineIssues) {
    const phaseId = String(issue.phase_id ?? "");
    if (!phaseId) continue;
    issueByPhase.set(phaseId, [...(issueByPhase.get(phaseId) ?? []), issue]);
  }
  const phases = buildTimelinePhases({ nodes: activeGraphNodes, metadata }).map((phase) => ({
    ...phase,
    issues: [...phase.issues, ...(issueByPhase.get(phase.phase.phase_id) ?? [])],
  }));

  const updateTimelinePolicy = (patch: Record<string, unknown>) => {
    updateTaskGraphMetadata({
      timeline_policy: {
        ...timelinePolicy,
        ...patch,
      },
    });
  };

  const updatePhaseDefinition = (phaseId: string, patch: Record<string, unknown>) => {
    const currentPhases = coordinationPhaseDefinitions(metadata, activeGraphNodes);
    const nextPhases = currentPhases.map((phase) => {
      if (phase.phase_id !== phaseId) return phase;
      return {
        ...phase,
        ...patch,
      };
    });
    const hasPhase = nextPhases.some((phase) => phase.phase_id === phaseId);
    updateTaskGraphMetadata({
      phase_definitions: hasPhase ? nextPhases : [...nextPhases, { phase_id: phaseId, title: phaseId, ...patch }],
    });
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>时序与循环</strong>
        <small>定义阶段、并行、审核门、返修和阶段退出条件。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>图级时序策略</strong></header>
          <div className="boundary-form">
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="调度模式"
              onChange={(value) => updateTimelinePolicy({ scheduling_mode: value })}
              options={["phase_sequence", "phase_then_sequence_index", "parallel"]}
              value={String(timelinePolicy.scheduling_mode ?? "phase_then_sequence_index")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="阶段退出条件"
              onChange={(value) => updateTimelinePolicy({ phase_exit_condition: value })}
              options={["all_blocking_nodes_complete", "review_gate_passed", "manual_release"]}
              value={String(timelinePolicy.phase_exit_condition ?? "all_blocking_nodes_complete")}
            />
            <TaskSystemField label="最大循环次数">
              <input
                min={0}
                onChange={(event) => updateTimelinePolicy({ max_loop_attempts: Number(event.target.value || 0) })}
                type="number"
                value={Number(timelinePolicy.max_loop_attempts ?? 2)}
              />
            </TaskSystemField>
            <TaskSystemField label="阶段列表">
              <textarea
                onChange={(event) => {
                  const phaseIds = splitList(event.target.value);
                  updateTimelinePolicy({ phase_ids: phaseIds });
                  const currentDefinitions = coordinationPhaseDefinitions(metadata, activeGraphNodes);
                  const byId = new Map(currentDefinitions.map((phase) => [phase.phase_id, phase]));
                  updateTaskGraphMetadata({
                    phase_definitions: phaseIds.map((phaseId) => byId.get(phaseId) ?? { phase_id: phaseId, title: phaseId.replace(/^phase\./, "") }),
                  });
                }}
                placeholder={"planning\nexecution\nreview"}
                value={phaseDefinitions.map((phase) => phase.phase_id).join("\n")}
              />
            </TaskSystemField>
          </div>
        </article>

        <article className="boundary-card task-graph-layer-explainer">
          <header><strong>生命周期语义</strong></header>
          <div className="task-graph-note">
            <strong>审核门不是普通节点备注</strong>
            <span>审核门要表达“是否允许进入下一阶段”。返修目标和退出条件应该在时序层显式可见。</span>
          </div>
          <div className="task-graph-mini-kv">
            <p><span>节点</span><strong>{activeGraphNodes.length}</strong></p>
            <p><span>阻塞出口</span><strong>{activeGraphNodes.filter((node) => node.blocks_phase_exit !== false).length}</strong></p>
            <p><span>审核门</span><strong>{activeGraphNodes.filter((node) => asRecord(node.review_gate_policy).is_review_gate === true || node.node_type === "review_gate").length}</strong></p>
            <p><span>时序问题</span><strong>{timelineIssues.length}</strong></p>
          </div>
        </article>
      </section>

      <PhaseLifecycleEditor
        activeGraphNodes={activeGraphNodes}
        phases={phases}
        onUpdatePhase={updatePhaseDefinition}
      />

      <section className="boundary-card">
        <header><strong>节点时序表</strong></header>
        <div className="task-graph-node-policy-list">
          {activeGraphNodes.map((node, index) => {
            const nodeId = String(node.node_id ?? "");
            const reviewGatePolicy = asRecord(node.review_gate_policy);
            return (
              <article className="task-graph-node-policy-row" key={nodeId || `node_${index}`}>
                <div className="task-graph-node-policy-row__identity">
                  <strong>{nodeTitle(node)}</strong>
                  <span>{nodeId}</span>
                </div>
                <TaskSystemField label="阶段">
                  <input
                    onChange={(event) => updateTaskGraphNode(nodeId, { phase_id: event.target.value })}
                    value={String(node.phase_id ?? "")}
                  />
                </TaskSystemField>
                <TaskSystemField label="顺序">
                  <input
                    min={0}
                    onChange={(event) => updateTaskGraphNode(nodeId, { sequence_index: Number(event.target.value || 0) })}
                    type="number"
                    value={Number(node.sequence_index ?? index + 1)}
                  />
                </TaskSystemField>
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="执行模式"
                  onChange={(value) => updateTaskGraphNode(nodeId, { execution_mode: value })}
                  options={["sync", "async", "parallel", "background", "barrier", "manual_gate"]}
                  value={String(node.execution_mode ?? "sync")}
                />
                <label className="boundary-check">
                  <input
                    checked={booleanValue(node.blocks_phase_exit, true)}
                    onChange={(event) => updateTaskGraphNode(nodeId, { blocks_phase_exit: event.target.checked })}
                    type="checkbox"
                  />
                  阻塞阶段出口
                </label>
                <label className="boundary-check">
                  <input
                    checked={reviewGatePolicy.is_review_gate === true || node.node_type === "review_gate"}
                    onChange={(event) => updateTaskGraphNode(nodeId, {
                      node_type: event.target.checked ? "review_gate" : String(node.node_type ?? "agent_role"),
                      review_gate_policy: {
                        ...reviewGatePolicy,
                        is_review_gate: event.target.checked,
                      },
                    })}
                    type="checkbox"
                  />
                  审核门
                </label>
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}
