"use client";

import { useEffect, useState } from "react";

import type { TaskGraphStandardView } from "@/lib/api";

import { PhaseLifecycleEditor } from "./PhaseLifecycleEditor";
import { buildTaskGraphTimelineStandardModel } from "./taskGraphStandardView";
import { formatRuntimeSupportOption, runtimeOptionIsUnsupported } from "./taskGraphRuntimeSupport";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { buildTimelinePhases, buildTimelinePreflightIssues, coordinationPhaseDefinitions, coordinationTimelineBlocks } from "./taskGraphTimeline";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";

type TimelineFacet = "phases" | "sequence" | "edges" | "loops" | "revision";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function nodeId(node: Record<string, unknown>) {
  return String(node.node_id ?? node.id ?? "").trim();
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
  standardView,
  standardViewLoading,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
  updateTaskGraphEdge,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  editorFocus?: TaskGraphEditorFocus;
  standardView: TaskGraphStandardView | null;
  standardViewLoading?: boolean;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  const [facet, setFacet] = useState<TimelineFacet>("phases");
  useEffect(() => {
    if (editorFocus?.layer !== "timeline") return;
    if (editorFocus.facet === "revision") setFacet("revision");
    if (editorFocus.facet === "phase") setFacet("phases");
    if (editorFocus.facet === "edge_temporal") setFacet("edges");
    if (editorFocus.facet === "clock") setFacet("sequence");
  }, [editorFocus?.facet, editorFocus?.layer]);
  const metadata = asRecord(taskGraphDraft.metadata);
  const phaseDefinitions = coordinationPhaseDefinitions(metadata, activeGraphNodes);
  const timelineBlocks = coordinationTimelineBlocks(metadata);
  const timelineIssues = buildTimelinePreflightIssues(activeGraphNodes, activeGraphEdges, metadata);
  const standardTimelineModel = buildTaskGraphTimelineStandardModel(standardView);
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
  const mainChainNodes = activeGraphNodes.filter((node) => node.main_chain === true || nodeId(node) === taskGraphDraft.entry_node_id || nodeId(node) === taskGraphDraft.output_node_id);
  const asyncNodes = activeGraphNodes.filter((node) => ["async", "background", "parallel"].includes(String(node.execution_mode ?? "")));
  const revisionEdges = activeGraphEdges.filter((edge) => {
    const metadata = asRecord(edge.metadata);
    return String(edge.edge_type ?? edge.mode ?? "") === "revision_request" || String(metadata.verdict ?? "") === "revise";
  });
  const temporalEdges = activeGraphEdges.filter((edge) => {
    const metadata = asRecord(edge.metadata);
    return String(edge.edge_type ?? edge.mode ?? "") === "temporal_dependency" || String(metadata.dependency_role ?? "").includes("temporal") || Object.keys(asRecord(metadata.temporal_semantics)).length > 0;
  });

  const patchEdgeTemporalSemantics = (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => {
    const currentMetadata = asRecord(edge.metadata);
    updateTaskGraphEdge(edgeId, {
      edge_type: String(edge.edge_type ?? edge.mode ?? "") || "temporal_dependency",
      metadata: {
        ...currentMetadata,
        dependency_role: String(currentMetadata.dependency_role ?? "temporal_handoff"),
        temporal_semantics: {
          ...asRecord(currentMetadata.temporal_semantics),
          ...patch,
        },
      },
    });
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>拓扑时序控制</strong>
        <small>从主链、阶段、循环框、并发组和控制边编译节点激活窗口与执行许可。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card task-graph-layer-explainer">
          <header><strong>控制模型摘要</strong><span>由拓扑派生，不是业务数据库</span></header>
          <div className="task-graph-mini-kv">
            <p><span>阶段</span><strong>{phaseDefinitions.length}</strong></p>
            <p><span>阶段图块</span><strong>{timelineBlocks.length}</strong></p>
            <p><span>主链节点</span><strong>{mainChainNodes.length || "自动识别"}</strong></p>
            <p><span>循环框</span><strong>{loopNodes.length}</strong></p>
            <p><span>异步/并发</span><strong>{asyncNodes.length}</strong></p>
            <p><span>审核门</span><strong>{reviewNodes.length}</strong></p>
            <p><span>显式时序边</span><strong>{temporalEdges.length}</strong></p>
          </div>
        </article>
        <article className="boundary-card task-graph-layer-explainer">
          <header><strong>运行语义</strong><span>TaskGraph temporal coordinate</span></header>
          <div className="task-graph-note">
            <strong>节点激活窗口决定谁此刻能运行</strong>
            <span>调度器只会给当前合法窗口签发 execution permit；节点返回时必须带回 activation 和 permit，否则监控会把它视为越界运行。</span>
          </div>
          <div className="task-graph-note">
            <strong>循环框是静态模板，迭代坐标运行时展开</strong>
            <span>循环体内部仍按 step / wait / join 分层；LangGraph step 只是执行机制，不能替代 TaskGraph 的时序坐标。</span>
          </div>
        </article>
      </section>

      <section className="task-graph-standard-board" aria-label="时序标准对象摘要">
        <article className="boundary-card task-graph-standard-card">
          <header><strong>标准时序对象</strong><span>{standardViewLoading ? "编译中" : `${standardTimelineModel.phases.length} phases`}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>入口节点</span><strong>{standardTimelineModel.entryNodeId || "-"}</strong></p>
            <p><span>出口节点</span><strong>{standardTimelineModel.outputNodeId || "-"}</strong></p>
            <p><span>显式时序边</span><strong>{standardTimelineModel.temporalEdges.length}</strong></p>
            <p><span>标准图块</span><strong>{standardTimelineModel.timelineBlocks.length}</strong></p>
            <p><span>循环框</span><strong>{standardTimelineModel.loopFrames.length}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>时序来自拓扑编译</strong>
            <span>这里显示后端对主链、phase、loop frame 和 temporal edge 的编译结果，不是业务计划表，也不是运行数据库。</span>
          </div>
        </article>
        <article className="boundary-card task-graph-standard-card">
          <header><strong>运行提醒</strong><span>{standardTimelineModel.issueCount} issues</span></header>
          <div className="task-graph-mini-kv">
            <p><span>异步节点</span><strong>{standardTimelineModel.asyncNodeCount}</strong></p>
            <p><span>Phase 数</span><strong>{standardTimelineModel.phases.length}</strong></p>
            <p><span>图块数</span><strong>{standardTimelineModel.timelineBlocks.length}</strong></p>
            <p><span>Loop frame</span><strong>{standardTimelineModel.loopFrames.length}</strong></p>
            <p><span>诊断问题</span><strong>{standardTimelineModel.issueCount}</strong></p>
          </div>
        </article>
      </section>

      <section className="task-graph-facet-switch" aria-label="时序配置分面">
        {[
          ["phases", "主链阶段", "phase / exit / gate"],
          ["sequence", "执行许可条件", "sequence / wait / join"],
          ["edges", "边时序语义", "trigger / visibility / ack"],
          ["loops", "循环框", "static frame / runtime iteration"],
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
                <span>阶段和循环框定义拓扑 scope；运行时控制层打开节点窗口并签发执行许可，clock ledger 只记录已经发生的事件顺序。</span>
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

      {facet === "edges" ? (
        <section className="boundary-card">
          <header><strong>边时序语义</strong><span>{activeGraphEdges.length} 条边</span></header>
          <div className="task-graph-note">
            <strong>边不是执行端，但边必须有关系时序</strong>
            <span>这里声明上游结果何时触发下游、何时可见、是否需要确认、如何传播，以及是否允许跨阶段。</span>
          </div>
          <div className="task-graph-node-policy-list">
            {activeGraphEdges.map((edge, index) => {
              const edgeId = String(edge.edge_id ?? edge.id ?? `${String(edge.source_node_id ?? edge.from ?? "source")}-${String(edge.target_node_id ?? edge.to ?? "target")}-${index}`);
              const edgeMetadata = asRecord(edge.metadata);
              const temporal = asRecord(edgeMetadata.temporal_semantics);
              return (
                <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={edgeId}>
                  <div className="task-graph-node-policy-row__identity">
                    <strong>{String(edge.source_node_id ?? edge.from ?? "")} {"->"} {String(edge.target_node_id ?? edge.to ?? "")}</strong>
                    <span>{edgeId}</span>
                  </div>
                  <TaskSystemSelectField
                    formatOption={formatRuntimeSupportOption("trigger_timing")}
                    isOptionDisabled={(value) => runtimeOptionIsUnsupported("trigger_timing", value)}
                    label="触发时序"
                    onChange={(value) => patchEdgeTemporalSemantics(edge, edgeId, { trigger_timing: value })}
                    options={["after_source_success", "after_required_contracts", "manual_release", "phase_entry", "phase_exit"]}
                    value={String(temporal.trigger_timing ?? "after_source_success")}
                  />
                  <TaskSystemSelectField
                    formatOption={formatRuntimeSupportOption("visibility_timing")}
                    isOptionDisabled={(value) => runtimeOptionIsUnsupported("visibility_timing", value)}
                    label="可见时序"
                    onChange={(value) => patchEdgeTemporalSemantics(edge, edgeId, { visibility_timing: value })}
                    options={["same_clock", "next_clock", "after_commit", "next_iteration", "manual_release"]}
                    value={String(temporal.visibility_timing ?? "after_commit")}
                  />
                  <TaskSystemSelectField
                    formatOption={formatRuntimeSupportOption("acknowledgement_timing")}
                    isOptionDisabled={(value) => runtimeOptionIsUnsupported("acknowledgement_timing", value)}
                    label="确认时序"
                    onChange={(value) => patchEdgeTemporalSemantics(edge, edgeId, { acknowledgement_timing: value })}
                    options={["no_ack", "explicit_ack", "ack_before_downstream", "ack_before_phase_exit"]}
                    value={String(temporal.acknowledgement_timing ?? "explicit_ack")}
                  />
                  <TaskSystemSelectField
                    formatOption={formatRuntimeSupportOption("propagation_timing")}
                    isOptionDisabled={(value) => runtimeOptionIsUnsupported("propagation_timing", value)}
                    label="传播时序"
                    onChange={(value) => patchEdgeTemporalSemantics(edge, edgeId, { propagation_timing: value })}
                    options={["immediate", "buffer_until_commit", "summary_only", "refs_only", "blocked_on_failure"]}
                    value={String(temporal.propagation_timing ?? "buffer_until_commit")}
                  />
                  <TaskSystemSelectField
                    formatOption={formatRuntimeSupportOption("phase_timing")}
                    isOptionDisabled={(value) => runtimeOptionIsUnsupported("phase_timing", value)}
                    label="阶段时序"
                    onChange={(value) => patchEdgeTemporalSemantics(edge, edgeId, { phase_timing: value })}
                    options={["within_phase", "cross_phase_handoff", "blocks_phase_exit", "revision_return", "non_blocking_feedback"]}
                    value={String(temporal.phase_timing ?? "within_phase")}
                  />
                  <TaskSystemField label="说明" wide>
                    <textarea
                      onChange={(event) => patchEdgeTemporalSemantics(edge, edgeId, { temporal_note: event.target.value })}
                      placeholder="说明这条边在时序上的交接规则，尤其是跨阶段、回退、提交可见性。"
                      value={String(temporal.temporal_note ?? "")}
                    />
                  </TaskSystemField>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {facet === "sequence" ? (
        <section className="boundary-card">
          <header><strong>节点执行许可条件</strong><span>{temporalEdges.length} 条显式时序边</span></header>
          <div className="task-graph-note">
            <strong>一个节点是否能启动，由拓扑位置和上游交接共同决定</strong>
            <span>sequence、wait、join、phase 和显式时序边共同决定 permit 是否可签发；边本身不是一个时序点，但边的交接完成会改变下游节点是否满足条件。</span>
          </div>
          {standardTimelineModel.phases.length ? (
            <div className="task-graph-standard-list">
              {standardTimelineModel.phases.map((phase) => {
                const phaseId = String(phase.phase_id ?? phase.id ?? "phase");
                return (
                  <article className="task-graph-standard-list__item" key={phaseId}>
                    <strong>{phaseId}</strong>
                    <span>{standardTimelineModel.phaseNodeCounts[phaseId] ?? 0} nodes</span>
                  </article>
                );
              })}
            </div>
          ) : null}
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
