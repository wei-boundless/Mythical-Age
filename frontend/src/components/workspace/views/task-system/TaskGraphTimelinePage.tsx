"use client";

import { useEffect, useState } from "react";

import { PhaseLifecycleEditor } from "./PhaseLifecycleEditor";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { buildTimelinePhases, buildTimelinePreflightIssues, coordinationPhaseDefinitions } from "./taskGraphTimeline";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";

type TimelineFacet = "phases" | "sequence" | "loops" | "revision";

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
  editorFocus,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  editorFocus?: TaskGraphEditorFocus;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const [facet, setFacet] = useState<TimelineFacet>("phases");
  useEffect(() => {
    if (editorFocus?.layer !== "timeline") return;
    if (editorFocus.facet === "revision") setFacet("revision");
    if (editorFocus.facet === "phase") setFacet("phases");
    if (editorFocus.facet === "clock") setFacet("sequence");
  }, [editorFocus?.facet, editorFocus?.layer]);
  const metadata = asRecord(taskGraphDraft.metadata);
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

  const reviewNodes = activeGraphNodes.filter((node) => asRecord(node.review_gate_policy).is_review_gate === true || node.node_type === "review_gate");
  const loopNodes = activeGraphNodes.filter((node) => Object.keys(asRecord(node.loop_policy)).length > 0 || String(node.node_type ?? "") === "loop_frame");
  const revisionEdges = activeGraphEdges.filter((edge) => {
    const metadata = asRecord(edge.metadata);
    return String(edge.edge_type ?? edge.mode ?? "") === "revision_request" || String(metadata.verdict ?? "") === "revise";
  });
  const temporalEdges = activeGraphEdges.filter((edge) => {
    const metadata = asRecord(edge.metadata);
    return String(edge.edge_type ?? edge.mode ?? "") === "temporal_dependency" || String(metadata.dependency_role ?? "").includes("temporal");
  });

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>时序与循环</strong>
        <small>定义阶段、并行、审核门、返修和阶段退出条件。</small>
      </header>

      <section className="task-graph-facet-switch" aria-label="时序配置分面">
        {[
          ["phases", "阶段主数据", "phase / exit / gate"],
          ["sequence", "调度约束", "sequence / wait / join"],
          ["loops", "循环框", "loop frame / iteration"],
          ["revision", "审核回退", "revise / fail / carry"],
        ].map(([id, title, desc]) => (
          <button className={facet === id ? "active" : ""} key={id} onClick={() => setFacet(id as TimelineFacet)} type="button">
            <strong>{title}</strong>
            <span>{desc}</span>
          </button>
        ))}
      </section>

      {editorFocus?.layer === "timeline" && editorFocus.issue_id ? (
        <div className="task-graph-note">
          <strong>来自发布诊断：{editorFocus.issue_id}</strong>
          <span>{editorFocus.edge_id ? `边 ${editorFocus.edge_id}` : editorFocus.node_id ? `节点 ${editorFocus.node_id}` : "请检查当前分面的时序配置。"} </span>
        </div>
      ) : null}

      {facet === "phases" ? (
        <>
          <section className="task-graph-form-grid">
            <article className="boundary-card">
              <header><strong>阶段主数据</strong></header>
              <div className="boundary-form">
                <TaskSystemField label="阶段列表">
                  <textarea
                    onChange={(event) => {
                      const phaseIds = splitList(event.target.value);
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
              <div className="task-graph-note">
                <strong>阶段是时序容器</strong>
                <span>阶段和循环框定义 scope，运行时由 TimelineLedger 分配 clock；节点只是事件参与者。</span>
              </div>
            </article>

            <article className="boundary-card task-graph-layer-explainer">
              <header><strong>生命周期语义</strong></header>
              <div className="task-graph-mini-kv">
                <p><span>节点</span><strong>{activeGraphNodes.length}</strong></p>
                <p><span>阻塞出口</span><strong>{activeGraphNodes.filter((node) => node.blocks_phase_exit !== false).length}</strong></p>
                <p><span>审核门</span><strong>{reviewNodes.length}</strong></p>
                <p><span>时序问题</span><strong>{timelineIssues.length}</strong></p>
              </div>
            </article>
          </section>

          <PhaseLifecycleEditor
            activeGraphNodes={activeGraphNodes}
            phases={phases}
            onUpdatePhase={updatePhaseDefinition}
          />
        </>
      ) : null}

      {facet === "sequence" ? (
        <section className="boundary-card">
          <header><strong>节点调度约束</strong><span>{temporalEdges.length} 条显式时序边</span></header>
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
                  <TaskSystemSelectField
                    formatOption={taskSystemOptionLabel}
                    label="等待策略"
                    onChange={(value) => updateTaskGraphNode(nodeId, { wait_policy: value })}
                    options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "manual_release"]}
                    value={String(node.wait_policy ?? "wait_all_upstream_completed")}
                  />
                  <TaskSystemSelectField
                    formatOption={taskSystemOptionLabel}
                    label="汇合策略"
                    onChange={(value) => updateTaskGraphNode(nodeId, { join_policy: value })}
                    options={["all_success", "any_success", "allow_partial_with_issues", "coordinator_decides", "fail_on_any_error"]}
                    value={String(node.join_policy ?? "all_success")}
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
      ) : null}

      {facet === "loops" ? (
        <section className="boundary-card">
          <header><strong>循环框</strong><span>静态 loop frame，运行时展开 iteration instance</span></header>
          <div className="task-graph-node-policy-list">
            {(loopNodes.length ? loopNodes : activeGraphNodes).map((node, index) => {
              const nodeId = String(node.node_id ?? "");
              const loopPolicy = asRecord(node.loop_policy);
              return (
                <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={nodeId || `loop_${index}`}>
                  <div className="task-graph-node-policy-row__identity">
                    <strong>{nodeTitle(node)}</strong>
                    <span>{nodeId || "未命名节点"}</span>
                  </div>
                  <TaskSystemSelectField
                    label="循环模式"
                    onChange={(value) => updateTaskGraphNode(nodeId, { loop_policy: { ...loopPolicy, loop_kind: value } })}
                    options={["none", "fixed_iteration", "until_gate_passed", "while_target_not_met", "manual_release"]}
                    value={String(loopPolicy.loop_kind ?? (Object.keys(loopPolicy).length ? "while_target_not_met" : "none"))}
                  />
                  <TaskSystemField label="迭代变量">
                    <input
                      onChange={(event) => updateTaskGraphNode(nodeId, { loop_policy: { ...loopPolicy, loop_variable: event.target.value } })}
                      placeholder="iteration_index"
                      value={String(loopPolicy.loop_variable ?? "")}
                    />
                  </TaskSystemField>
                  <TaskSystemField label="退出条件">
                    <input
                      onChange={(event) => updateTaskGraphNode(nodeId, { loop_policy: { ...loopPolicy, exit_condition: event.target.value } })}
                      placeholder="target_reached / gate_passed"
                      value={String(loopPolicy.exit_condition ?? "")}
                    />
                  </TaskSystemField>
                  <TaskSystemSelectField
                    label="记忆快照"
                    onChange={(value) => updateTaskGraphNode(nodeId, { loop_policy: { ...loopPolicy, memory_snapshot_policy: value } })}
                    options={["snapshot_before_iteration", "latest_committed_before_iteration", "manual_snapshot"]}
                    value={String(loopPolicy.memory_snapshot_policy ?? "latest_committed_before_iteration")}
                  />
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {facet === "revision" ? (
        <section className="boundary-card">
          <header><strong>审核回退路由</strong><span>{revisionEdges.length} 条 revise 路由</span></header>
          <div className="task-graph-node-policy-list">
            {(reviewNodes.length ? reviewNodes : activeGraphNodes.filter((node) => String(node.node_type ?? "").includes("review"))).map((node, index) => {
              const nodeId = String(node.node_id ?? "");
              const reviewGatePolicy = asRecord(node.review_gate_policy);
              const revisionPolicy = asRecord(node.revision_context_policy);
              return (
                <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={nodeId || `review_${index}`}>
                  <div className="task-graph-node-policy-row__identity">
                    <strong>{nodeTitle(node)}</strong>
                    <span>{nodeId || "审核节点"}</span>
                  </div>
                  <TaskSystemField label="返修目标">
                    <input
                      onChange={(event) => updateTaskGraphNode(nodeId, { review_gate_policy: { ...reviewGatePolicy, revision_stage_id: event.target.value } })}
                      placeholder="author_node_id"
                      value={String(reviewGatePolicy.revision_stage_id ?? reviewGatePolicy.on_revise ?? "")}
                    />
                  </TaskSystemField>
                  <TaskSystemField label="通过目标">
                    <input
                      onChange={(event) => updateTaskGraphNode(nodeId, { review_gate_policy: { ...reviewGatePolicy, pass_stage_id: event.target.value } })}
                      placeholder="next_commit_node_id"
                      value={String(reviewGatePolicy.pass_stage_id ?? "")}
                    />
                  </TaskSystemField>
                  <TaskSystemField label="携带 refs">
                    <textarea
                      onChange={(event) => updateTaskGraphNode(nodeId, {
                        revision_context_policy: {
                          ...revisionPolicy,
                          carry_input_keys: splitList(event.target.value),
                        },
                      })}
                      placeholder={"previous_review_ref\nprevious_candidate_ref"}
                      value={Array.isArray(revisionPolicy.carry_input_keys) ? revisionPolicy.carry_input_keys.join("\n") : ""}
                    />
                  </TaskSystemField>
                  <TaskSystemSelectField
                    label="失败策略"
                    onChange={(value) => updateTaskGraphNode(nodeId, { review_gate_policy: { ...reviewGatePolicy, fail_policy: value } })}
                    options={["fail_closed", "human_gate", "coordinator_decides"]}
                    value={String(reviewGatePolicy.fail_policy ?? "fail_closed")}
                  />
                </article>
              );
            })}
          </div>
        </section>
      ) : null}
    </section>
  );
}
