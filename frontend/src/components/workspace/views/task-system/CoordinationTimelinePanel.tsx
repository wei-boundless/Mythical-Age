"use client";

import { GitBranch, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo, useState, type Dispatch, type SetStateAction } from "react";

import {
  TaskSystemField,
  taskSystemDisplayLabel,
  taskSystemOptionLabel,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  buildTimelinePhases,
  buildTimelinePreflightIssues,
  coordinationLifecyclePolicy,
  coordinationPhaseDefinitions,
  coordinationTimelinePolicy,
  DEFAULT_PHASE_ID,
  nodeBlocksPhaseExit,
  nodeIdOf,
  nodeLoopPolicy,
  nodeMainChain,
  nodePhaseId,
  nodeReviewGatePolicy,
  nodeSequenceIndex,
  nodeTimelineGroupId,
  nodeTitle,
  type TaskGraphPhaseDefinition,
} from "@/components/workspace/views/task-system/taskGraphTimeline";

type CoordinationDraftLike = {
  coordination_task_id: string;
  title: string;
  coordination_mode: string;
  coordinator_agent_id: string;
  task_family?: string;
  domain_id?: string;
  agent_group_id?: string;
  participant_agent_ids: string[];
  topology_template_id: string;
  shared_context_policy: string;
  memory_sharing_policy: string;
  handoff_policy: string;
  conflict_resolution_policy: string;
  output_merge_policy: string;
  stop_conditions: string[];
  subtask_refs: string[];
  graph_nodes: Array<Record<string, unknown>>;
  graph_edges: Array<Record<string, unknown>>;
  communication_modes: string[];
  enabled: boolean;
  metadata?: Record<string, unknown>;
  stop_conditions_text: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function boolValue(value: unknown, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === undefined || value === null || value === "") return fallback;
  return String(value).toLowerCase() === "true";
}

function phaseTitle(phase: TaskGraphPhaseDefinition) {
  return phase.title || phase.phase_id || "未命名阶段";
}

function nextPhaseId(phases: TaskGraphPhaseDefinition[]) {
  const index = phases.length + 1;
  return `phase.custom_${String(index).padStart(2, "0")}`;
}

function nodeOptions(nodes: Array<Record<string, unknown>>) {
  return ["", ...nodes.map((node, index) => nodeIdOf(node, index))];
}

function formatNodeOption(nodes: Array<Record<string, unknown>>) {
  return (nodeId: string) => {
    if (!nodeId) return "不绑定";
    const node = nodes.find((item, index) => nodeIdOf(item, index) === nodeId);
    return node ? `${nodeTitle(node)} · ${nodeId}` : nodeId;
  };
}

function updateMetadataPhase(
  coordinationDraft: CoordinationDraftLike,
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>,
  updater: (phases: TaskGraphPhaseDefinition[]) => TaskGraphPhaseDefinition[],
) {
  const currentMetadata = asRecord(coordinationDraft.metadata);
  const currentPhases = coordinationPhaseDefinitions(currentMetadata, coordinationDraft.graph_nodes ?? []);
  const nextPhases = updater(currentPhases);
  setCoordinationDraft((current) => ({
    ...current,
    metadata: {
      ...(current.metadata ?? {}),
      lifecycle_policy: coordinationLifecyclePolicy(asRecord(current.metadata)),
      timeline_policy: coordinationTimelinePolicy(asRecord(current.metadata)),
      phase_definitions: nextPhases,
    },
  }));
}

export function CoordinationTimelinePanel({
  nodes,
  edges,
  coordinationDraft,
  setCoordinationDraft,
  selectedNodeId,
  setSelectedNodeId,
  updateCoordinationNode,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  coordinationDraft: CoordinationDraftLike;
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>;
  selectedNodeId: string;
  setSelectedNodeId: (value: string) => void;
  updateCoordinationNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const metadata = asRecord(coordinationDraft.metadata);
  const phases = useMemo(() => buildTimelinePhases({ nodes, metadata }), [metadata, nodes]);
  const phaseDefinitions = useMemo(() => coordinationPhaseDefinitions(metadata, nodes), [metadata, nodes]);
  const lifecyclePolicy = coordinationLifecyclePolicy(metadata);
  const timelinePolicy = coordinationTimelinePolicy(metadata);
  const timelineIssues = useMemo(() => buildTimelinePreflightIssues(nodes, edges, metadata), [edges, metadata, nodes]);
  const [selectedPhaseId, setSelectedPhaseId] = useState(phaseDefinitions[0]?.phase_id ?? DEFAULT_PHASE_ID);
  const selectedPhase = phaseDefinitions.find((phase) => phase.phase_id === selectedPhaseId) ?? phaseDefinitions[0] ?? { phase_id: DEFAULT_PHASE_ID, title: "未分配阶段" };
  const selectedNode = nodes.find((node, index) => nodeIdOf(node, index) === selectedNodeId) ?? null;
  const phaseNodeOptions = nodeOptions(nodes);
  const phaseNodeLabel = formatNodeOption(nodes);

  function patchPhase(phaseId: string, patch: Partial<TaskGraphPhaseDefinition>) {
    updateMetadataPhase(coordinationDraft, setCoordinationDraft, (current) =>
      current.map((phase) => phase.phase_id === phaseId ? { ...phase, ...patch } : phase),
    );
  }

  function addPhase() {
    const phaseId = nextPhaseId(phaseDefinitions);
    updateMetadataPhase(coordinationDraft, setCoordinationDraft, (current) => [
      ...current,
      {
        phase_id: phaseId,
        title: `新阶段 ${current.length + 1}`,
        exit_policy: { kind: "review_gate_passed" },
      },
    ]);
    setSelectedPhaseId(phaseId);
  }

  function removePhase(phaseId: string) {
    updateMetadataPhase(coordinationDraft, setCoordinationDraft, (current) => current.filter((phase) => phase.phase_id !== phaseId));
    if (selectedPhaseId === phaseId) {
      setSelectedPhaseId(phaseDefinitions.find((phase) => phase.phase_id !== phaseId)?.phase_id ?? DEFAULT_PHASE_ID);
    }
  }

  function patchSelectedNode(patch: Record<string, unknown>) {
    if (!selectedNodeId) return;
    updateCoordinationNode(selectedNodeId, patch);
  }

  return (
    <section className="coordination-timeline-workbench">
      <aside className="coordination-timeline-rail">
        <section className="boundary-inspector-block">
          <header>
            <strong>生命周期</strong>
            <span>{taskSystemOptionLabel(String(lifecyclePolicy.lifecycle_id ?? "default"))}</span>
          </header>
          <div className="boundary-kv">
            <p><span>主链模式</span><strong>{taskSystemDisplayLabel(lifecyclePolicy.main_chain_mode ?? "phase_sequence")}</strong></p>
            <p><span>排序策略</span><strong>{taskSystemDisplayLabel(timelinePolicy.ordering ?? "phase_then_sequence_index")}</strong></p>
            <p><span>阶段退出</span><strong>{taskSystemDisplayLabel(timelinePolicy.phase_exit_policy ?? "all_blocking_nodes_complete")}</strong></p>
          </div>
          <TaskSystemToolbarButton onClick={addPhase}><Plus size={14} />新增阶段</TaskSystemToolbarButton>
        </section>

        <section className="boundary-inspector-block">
          <header>
            <strong>阶段目录</strong>
            <span>{phaseDefinitions.length}</span>
          </header>
          <div className="boundary-list boundary-list--scroll coordination-timeline-phase-list">
            {phaseDefinitions.map((phase) => (
              <button
                className={phase.phase_id === selectedPhaseId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
                key={phase.phase_id}
                onClick={() => setSelectedPhaseId(phase.phase_id)}
                type="button"
              >
                <strong>{phaseTitle(phase)}</strong>
                <span>{phase.phase_id}</span>
                <small>{phase.review_gate_node_id ? "审核门已配置" : "未配置审核门"}</small>
              </button>
            ))}
          </div>
        </section>
      </aside>

      <main className="coordination-timeline-main">
        <section className="coordination-timeline-board">
          <header className="coordination-timeline-board__head">
            <div className="boundary-identity-stack">
              <span>时序编排</span>
              <strong>按成果成熟度推进阶段</strong>
            </div>
            <div className="boundary-actions">
              <span className={timelineIssues.some((item) => item.severity === "error") ? "boundary-badge boundary-badge--danger" : "boundary-badge boundary-badge--ok"}>
                {timelineIssues.length ? `${timelineIssues.length} 个时序问题` : "时序预检通过"}
              </span>
            </div>
          </header>

          <div className="coordination-timeline-phase-stack">
            {phases.map(({ phase, steps, nodes: phaseNodes }) => (
              <article className={phase.phase_id === selectedPhaseId ? "coordination-timeline-phase coordination-timeline-phase--active" : "coordination-timeline-phase"} key={phase.phase_id}>
                <header>
                  <button onClick={() => setSelectedPhaseId(phase.phase_id)} type="button">
                    <strong>{phaseTitle(phase)}</strong>
                    <span>{phase.phase_id}</span>
                  </button>
                  <div className="coordination-timeline-phase__meta">
                    <span>{phaseNodes.length} 节点</span>
                    {phase.review_gate_node_id ? <span><ShieldCheck size={13} />审核门</span> : null}
                  </div>
                </header>
                <div className="coordination-timeline-step-list">
                  {steps.map((step) => (
                    <section className="coordination-timeline-step" key={`${phase.phase_id}-${step.step_key}`}>
                      <div className="coordination-timeline-step__label">
                        <strong>T{step.sequence_index}</strong>
                        <span>{step.timeline_group_id || "顺序点"}</span>
                      </div>
                      <div className="coordination-timeline-node-row">
                        {step.nodes.map((node, index) => {
                          const nodeId = nodeIdOf(node, index);
                          const reviewPolicy = nodeReviewGatePolicy(node);
                          const isSelected = selectedNodeId === nodeId;
                          return (
                            <button
                              className={isSelected ? "coordination-timeline-node coordination-timeline-node--active" : "coordination-timeline-node"}
                              key={nodeId}
                              onClick={() => setSelectedNodeId(nodeId)}
                              type="button"
                            >
                              <strong>{nodeTitle(node, index)}</strong>
                              <span>{String(node.agent_id ?? "未绑定 Agent")}</span>
                              <small>
                                {nodeMainChain(node) ? "主链" : "旁链"}
                                {nodeBlocksPhaseExit(node) ? " / 阻塞退出" : ""}
                                {boolValue(reviewPolicy.is_review_gate) ? " / 审核门" : ""}
                              </small>
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                  {!steps.length ? <div className="boundary-empty">这个阶段还没有节点。请在右侧把节点分配到该阶段。</div> : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>

      <aside className="coordination-timeline-inspector">
        <section className="boundary-inspector-block">
          <header>
            <strong>阶段检查器</strong>
            <span>{selectedPhase.phase_id}</span>
          </header>
          <TaskSystemField label="阶段标题">
            <input value={selectedPhase.title ?? ""} onChange={(event) => patchPhase(selectedPhase.phase_id, { title: event.target.value })} />
          </TaskSystemField>
          <TaskSystemField label="阶段 ID">
            <input value={selectedPhase.phase_id} readOnly />
          </TaskSystemField>
          <TaskSystemSelectField label="入口节点" options={phaseNodeOptions} value={selectedPhase.entry_node_id ?? ""} onChange={(value) => patchPhase(selectedPhase.phase_id, { entry_node_id: value })} formatOption={phaseNodeLabel} />
          <TaskSystemSelectField label="出口节点" options={phaseNodeOptions} value={selectedPhase.exit_node_id ?? ""} onChange={(value) => patchPhase(selectedPhase.phase_id, { exit_node_id: value })} formatOption={phaseNodeLabel} />
          <TaskSystemSelectField label="审核门" options={phaseNodeOptions} value={selectedPhase.review_gate_node_id ?? ""} onChange={(value) => patchPhase(selectedPhase.phase_id, { review_gate_node_id: value })} formatOption={phaseNodeLabel} />
          <TaskSystemSelectField label="记忆写入" options={phaseNodeOptions} value={selectedPhase.memory_commit_node_id ?? ""} onChange={(value) => patchPhase(selectedPhase.phase_id, { memory_commit_node_id: value })} formatOption={phaseNodeLabel} />
          {selectedPhase.phase_id !== DEFAULT_PHASE_ID ? (
            <TaskSystemToolbarButton onClick={() => removePhase(selectedPhase.phase_id)}><Trash2 size={14} />删除阶段</TaskSystemToolbarButton>
          ) : null}
        </section>

        <section className="boundary-inspector-block">
          <header>
            <strong>节点时序</strong>
            <span>{selectedNode ? nodeIdOf(selectedNode) : "未选"}</span>
          </header>
          {selectedNode ? (
            <>
              <div className="boundary-kv">
                <p><span>节点</span><strong>{nodeTitle(selectedNode)}</strong></p>
                <p><span>当前阶段</span><strong>{nodePhaseId(selectedNode)}</strong></p>
              </div>
              <TaskSystemSelectField label="所属阶段" options={phaseDefinitions.map((phase) => phase.phase_id)} value={nodePhaseId(selectedNode)} onChange={(value) => patchSelectedNode({ phase_id: value })} formatOption={(value) => phaseDefinitions.find((phase) => phase.phase_id === value)?.title || value} />
              <TaskSystemField label="时序点">
                <input min={1} type="number" value={nodeSequenceIndex(selectedNode)} onChange={(event) => patchSelectedNode({ sequence_index: Number(event.target.value || 1) })} />
              </TaskSystemField>
              <TaskSystemField label="并行组">
                <input placeholder="例如 chapter.review" value={nodeTimelineGroupId(selectedNode)} onChange={(event) => patchSelectedNode({ timeline_group_id: event.target.value })} />
              </TaskSystemField>
              <label className="boundary-check">
                <input checked={nodeMainChain(selectedNode)} onChange={(event) => patchSelectedNode({ main_chain: event.target.checked })} type="checkbox" />
                主链节点
              </label>
              <label className="boundary-check">
                <input checked={nodeBlocksPhaseExit(selectedNode)} onChange={(event) => patchSelectedNode({ blocks_phase_exit: event.target.checked })} type="checkbox" />
                阻塞阶段退出
              </label>
              <TaskSystemField label="完成策略">
                <input value={String(selectedNode.completion_policy ?? asRecord(selectedNode.metadata).completion_policy ?? "")} onChange={(event) => patchSelectedNode({ completion_policy: event.target.value })} placeholder="contract_output_ready" />
              </TaskSystemField>
              <section className="boundary-inspector-subblock">
                <header><strong>审核门</strong><span>阶段裁决</span></header>
                <label className="boundary-check">
                  <input
                    checked={boolValue(nodeReviewGatePolicy(selectedNode).is_review_gate)}
                    onChange={(event) => patchSelectedNode({
                      review_gate_policy: {
                        ...nodeReviewGatePolicy(selectedNode),
                        is_review_gate: event.target.checked,
                      },
                    })}
                    type="checkbox"
                  />
                  作为阶段审核门
                </label>
                <TaskSystemField label="通过线">
                  <input
                    min={0}
                    max={100}
                    type="number"
                    value={Number(nodeReviewGatePolicy(selectedNode).pass_score ?? 85)}
                    onChange={(event) => patchSelectedNode({
                      review_gate_policy: {
                        ...nodeReviewGatePolicy(selectedNode),
                        pass_score: Number(event.target.value || 0),
                      },
                    })}
                  />
                </TaskSystemField>
                <TaskSystemSelectField label="通过后" options={phaseNodeOptions} value={String(nodeReviewGatePolicy(selectedNode).on_pass ?? "")} onChange={(value) => patchSelectedNode({ review_gate_policy: { ...nodeReviewGatePolicy(selectedNode), on_pass: value } })} formatOption={phaseNodeLabel} />
                <TaskSystemSelectField label="失败后" options={phaseNodeOptions} value={String(nodeReviewGatePolicy(selectedNode).on_fail ?? "")} onChange={(value) => patchSelectedNode({ review_gate_policy: { ...nodeReviewGatePolicy(selectedNode), on_fail: value } })} formatOption={phaseNodeLabel} />
                <TaskSystemSelectField label="严重偏差" options={phaseNodeOptions} value={String(nodeReviewGatePolicy(selectedNode).on_severe_drift ?? "")} onChange={(value) => patchSelectedNode({ review_gate_policy: { ...nodeReviewGatePolicy(selectedNode), on_severe_drift: value } })} formatOption={phaseNodeLabel} />
              </section>
              <section className="boundary-inspector-subblock">
                <header><strong>循环</strong><span>重试与退出</span></header>
                <TaskSystemField label="最大尝试">
                  <input
                    min={0}
                    type="number"
                    value={Number(nodeLoopPolicy(selectedNode).max_attempts ?? 0)}
                    onChange={(event) => patchSelectedNode({
                      loop_policy: {
                        ...nodeLoopPolicy(selectedNode),
                        max_attempts: Number(event.target.value || 0),
                      },
                    })}
                  />
                </TaskSystemField>
                <TaskSystemField label="退出条件">
                  <input
                    value={String(nodeLoopPolicy(selectedNode).exit_condition ?? "")}
                    onChange={(event) => patchSelectedNode({
                      loop_policy: {
                        ...nodeLoopPolicy(selectedNode),
                        exit_condition: event.target.value,
                      },
                    })}
                  />
                </TaskSystemField>
              </section>
            </>
          ) : (
            <div className="boundary-empty">选择一个节点后，可以配置它在阶段中的时序、审核门和循环策略。</div>
          )}
        </section>

        <section className="boundary-inspector-block">
          <header>
            <strong>时序预检</strong>
            <span>{timelineIssues.length}</span>
          </header>
          <div className="coordination-timeline-issue-list">
            {timelineIssues.map((issue, index) => (
              <article className={`coordination-timeline-issue coordination-timeline-issue--${issue.severity}`} key={`${issue.code}-${index}`}>
                <strong>{issue.message}</strong>
                <span>{issue.phase_id || issue.node_id || issue.edge_id || issue.code}</span>
              </article>
            ))}
            {!timelineIssues.length ? <div className="boundary-empty">时序配置暂未发现问题。</div> : null}
          </div>
        </section>
      </aside>
    </section>
  );
}
