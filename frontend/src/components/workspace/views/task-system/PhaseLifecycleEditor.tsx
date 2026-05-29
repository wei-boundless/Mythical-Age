"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import type { TaskGraphTimelinePhase } from "./taskGraphTimeline";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeOptionLabel(nodeId: string, nodes: Array<Record<string, unknown>>) {
  if (!nodeId) return "不绑定";
  const node = nodes.find((item) => String(item.node_id ?? "") === nodeId);
  return node ? `${String(node.title ?? node.label ?? node.node_id)} · ${nodeId}` : nodeId;
}

export function PhaseLifecycleEditor({
  activeGraphNodes,
  phases,
  onUpdatePhase,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  phases: TaskGraphTimelinePhase[];
  onUpdatePhase: (phaseId: string, patch: Record<string, unknown>) => void;
}) {
  const nodeOptions = ["", ...activeGraphNodes.map((node) => String(node.node_id ?? "")).filter(Boolean)];

  return (
    <section className="boundary-card">
      <header>
        <strong>阶段生命周期</strong>
        <span>{phases.length} 个阶段</span>
      </header>
      <div className="task-graph-phase-grid">
        {phases.map(({ phase, nodes, node_coordinates, issues }) => {
          const exitPolicy = asRecord(phase.exit_policy);
          const loop = asRecord(phase.loop);
          return (
            <article className="task-graph-phase-card" key={phase.phase_id}>
              <header>
                <div className="boundary-identity-stack">
                  <span>{phase.phase_id}</span>
                  <strong>{phase.title || phase.phase_id}</strong>
                </div>
                <em>{nodes.length} 节点</em>
              </header>
              <div className="task-graph-mini-kv">
                <p><span>问题</span><strong>{issues.length}</strong></p>
                <p><span>坐标</span><strong>{node_coordinates.length}</strong></p>
                <p><span>审核门</span><strong>{phase.review_gate_node_id || "未绑定"}</strong></p>
                <p><span>循环</span><strong>{Object.keys(loop).length ? "已配置" : "未配置"}</strong></p>
              </div>
              <div className="boundary-form">
                <TaskSystemField label="阶段标题">
                  <input value={phase.title || ""} onChange={(event) => onUpdatePhase(phase.phase_id, { title: event.target.value })} />
                </TaskSystemField>
                <TaskSystemSelectField
                  formatOption={(value) => nodeOptionLabel(value, activeGraphNodes)}
                  label="入口节点"
                  onChange={(value) => onUpdatePhase(phase.phase_id, { entry_node_id: value || undefined })}
                  options={nodeOptions}
                  value={phase.entry_node_id ?? ""}
                />
                <TaskSystemSelectField
                  formatOption={(value) => nodeOptionLabel(value, activeGraphNodes)}
                  label="出口节点"
                  onChange={(value) => onUpdatePhase(phase.phase_id, { exit_node_id: value || undefined })}
                  options={nodeOptions}
                  value={phase.exit_node_id ?? ""}
                />
                <TaskSystemSelectField
                  formatOption={(value) => nodeOptionLabel(value, activeGraphNodes)}
                  label="审核门节点"
                  onChange={(value) => onUpdatePhase(phase.phase_id, { review_gate_node_id: value || undefined })}
                  options={nodeOptions}
                  value={phase.review_gate_node_id ?? ""}
                />
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="阶段退出"
                  onChange={(value) => onUpdatePhase(phase.phase_id, { exit_policy: { ...exitPolicy, kind: value } })}
                  options={["all_blocking_nodes_complete", "review_gate_passed", "manual_release", "artifact_ready"]}
                  value={String(exitPolicy.kind ?? "all_blocking_nodes_complete")}
                />
                <TaskSystemField label="最大循环次数">
                  <input
                    min={0}
                    onChange={(event) => onUpdatePhase(phase.phase_id, { loop: { ...loop, max_attempts: Number(event.target.value || 0) } })}
                    type="number"
                    value={Number(loop.max_attempts ?? 0)}
                  />
                </TaskSystemField>
                <TaskSystemField label="循环退出条件">
                  <input
                    onChange={(event) => onUpdatePhase(phase.phase_id, { loop: { ...loop, exit_condition: event.target.value } })}
                    placeholder="review_gate_passed"
                    value={String(loop.exit_condition ?? "")}
                  />
                </TaskSystemField>
              </div>
              {issues.length ? (
                <div className="task-graph-phase-issues">
                  {issues.map((issue) => (
                    <span key={`${issue.code}-${issue.node_id ?? issue.phase_id ?? ""}`}>{issue.message}</span>
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
