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

type TimelineFacet = "semantics" | "phases" | "coordinates" | "edges" | "loops" | "revision";

const NODE_SEMANTIC_ROLE_OPTIONS = ["producer", "validator", "approver", "publisher", "aggregator", "router", "resource", "monitor"];
const EDGE_SEMANTIC_ROLE_OPTIONS = ["activation", "data_input", "validation_input", "approval_input", "publish_input", "resource_read", "resource_write", "reference", "retry", "failure_route"];

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

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
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
  const [facet, setFacet] = useState<TimelineFacet>("semantics");
  useEffect(() => {
    if (editorFocus?.layer !== "timeline") return;
    if (editorFocus.facet === "revision") setFacet("revision");
    if (editorFocus.facet === "phase") setFacet("phases");
    if (editorFocus.facet === "edge_temporal") setFacet("edges");
    if (editorFocus.facet === "clock") setFacet("coordinates");
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
  const runtimeSemantics = asRecord(standardTimelineModel.runtimeSemantics);
  const runtimeSemanticsSummary = asRecord(runtimeSemantics.summary);
  const runtimeStepPolicy = asRecord(runtimeSemantics.step_policy);
  const nodeSemantics = recordArray(runtimeSemantics.node_semantics);
  const edgeSemantics = recordArray(runtimeSemantics.edge_semantics);
  const runtimeSemanticsDiagnostics = recordArray(runtimeSemantics.diagnostics);
  const legacyFields = recordArray(runtimeSemantics.legacy_fields);
  const artifactLifecycleStateCount = Array.isArray(runtimeSemantics.artifact_lifecycle_states) ? runtimeSemantics.artifact_lifecycle_states.length : 0;
  const semanticRoleByNodeId = new Map(nodeSemantics.map((item) => [String(item.node_id ?? ""), String(item.semantic_role ?? "")]));
  const semanticRoleByEdgeId = new Map(edgeSemantics.map((item) => [String(item.edge_id ?? ""), String(item.semantic_role ?? "")]));

  const patchNodeRuntimeSemanticRole = (node: Record<string, unknown>, nextRole: string) => {
    const targetNodeId = nodeId(node);
    if (!targetNodeId) return;
    updateTaskGraphNode(targetNodeId, {
      metadata: {
        ...asRecord(node.metadata),
        runtime_semantic_role: nextRole,
      },
    });
  };

  const patchEdgeRuntimeSemanticRole = (edge: Record<string, unknown>, edgeId: string, nextRole: string) => {
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...asRecord(edge.metadata),
        runtime_semantic_role: nextRole,
      },
    });
  };

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
        <span>图工作台</span>
        <strong>生命周期与运行语义</strong>
        <small>用通用语义解释节点职责、边职责、生命周期坐标和运行记录；step 只属于运行监控。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card task-graph-layer-explainer">
          <header><strong>结构摘要</strong><span>由拓扑编译，不是业务模板</span></header>
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
          <header><strong>运行语义</strong><span>{String(runtimeSemantics.authority ?? "等待编译")}</span></header>
          <div className="task-graph-note">
            <strong>图编辑器不编辑 step</strong>
            <span>step 是运行时 dispatch wave 和 checkpoint 边界；编辑器编辑节点、边、资源、生命周期坐标和通用语义。</span>
          </div>
          <div className="task-graph-note">
            <strong>旧时序字段只做坐标</strong>
            <span>phase 和 sequence 可以帮助展示与迁移，但通用依赖关系应由显式边和边语义表达。</span>
          </div>
        </article>
      </section>

      <section className="task-graph-standard-board" aria-label="时序标准对象摘要">
        <article className="boundary-card task-graph-standard-card">
          <header><strong>标准生命周期对象</strong><span>{standardViewLoading ? "编译中" : `${standardTimelineModel.phases.length} phases`}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>入口节点</span><strong>{standardTimelineModel.entryNodeId || "-"}</strong></p>
            <p><span>出口节点</span><strong>{standardTimelineModel.outputNodeId || "-"}</strong></p>
            <p><span>时序边</span><strong>{standardTimelineModel.temporalEdges.length}</strong></p>
            <p><span>标准图块</span><strong>{standardTimelineModel.timelineBlocks.length}</strong></p>
            <p><span>循环框</span><strong>{standardTimelineModel.loopFrames.length}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>生命周期来自拓扑编译</strong>
            <span>这里显示后端对 phase、loop frame 和 temporal edge 的编译结果；运行 step 在运行监控页查看。</span>
          </div>
        </article>
        <article className="boundary-card task-graph-standard-card">
          <header><strong>运行语义摘要</strong><span>{String(runtimeSemanticsSummary.diagnostic_count ?? 0)} diagnostics</span></header>
          <div className="task-graph-mini-kv">
            <p><span>节点语义</span><strong>{String(runtimeSemanticsSummary.node_count ?? nodeSemantics.length)}</strong></p>
            <p><span>边语义</span><strong>{String(runtimeSemanticsSummary.edge_count ?? edgeSemantics.length)}</strong></p>
            <p><span>旧字段</span><strong>{String(runtimeSemanticsSummary.legacy_field_count ?? legacyFields.length)}</strong></p>
            <p><span>Step 可编辑</span><strong>{runtimeStepPolicy.editor_visible ? "是" : "否"}</strong></p>
            <p><span>诊断问题</span><strong>{standardTimelineModel.issueCount}</strong></p>
          </div>
        </article>
      </section>

      <section className="task-graph-facet-switch" aria-label="时序配置分面">
        {[
          ["semantics", "运行语义", "node role / edge role"],
          ["phases", "主链阶段", "phase / exit / gate"],
          ["coordinates", "激活坐标", "phase / legacy sequence"],
          ["edges", "边生命周期", "trigger / visibility / ack"],
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

      {facet === "semantics" ? (
        <>
          <section className="boundary-card">
            <header><strong>通用运行语义</strong><span>{String(runtimeSemantics.authority ?? "未编译")}</span></header>
            <div className="task-graph-note">
              <strong>这是底层图协议，不是领域模板</strong>
              <span>节点职责、边职责和产物生命周期使用通用词；具体行业模板只能映射这些语义，不能改变底层协议。</span>
            </div>
            <div className="task-graph-mini-kv">
              <p><span>节点语义</span><strong>{nodeSemantics.length}</strong></p>
              <p><span>边语义</span><strong>{edgeSemantics.length}</strong></p>
              <p><span>产物状态</span><strong>{artifactLifecycleStateCount}</strong></p>
              <p><span>旧字段</span><strong>{legacyFields.length}</strong></p>
              <p><span>Step 可编辑</span><strong>{runtimeStepPolicy.editor_visible ? "是" : "否"}</strong></p>
            </div>
          </section>
          <div className="task-graph-form-grid">
            <article className="boundary-card task-graph-layer-explainer">
              <header><strong>节点职责</strong><span>{nodeSemantics.length} nodes</span></header>
              <div className="task-graph-node-policy-list">
                {activeGraphNodes.map((node, index) => {
                  const currentNodeId = nodeId(node);
                  const metadata = asRecord(node.metadata);
                  const role = String(metadata.runtime_semantic_role ?? semanticRoleByNodeId.get(currentNodeId) ?? "producer");
                  return (
                  <article className="task-graph-node-policy-row" key={currentNodeId || `node_semantic_${index}`}>
                    <div className="task-graph-node-policy-row__identity">
                      <strong>{nodeTitle(node)}</strong>
                      <span>{currentNodeId || "未命名节点"}</span>
                    </div>
                    <TaskSystemSelectField
                      label="通用职责"
                      onChange={(value) => patchNodeRuntimeSemanticRole(node, value)}
                      options={NODE_SEMANTIC_ROLE_OPTIONS}
                      value={role}
                    />
                  </article>
                  );
                })}
              </div>
            </article>
            <article className="boundary-card task-graph-layer-explainer">
              <header><strong>边职责</strong><span>{edgeSemantics.length} edges</span></header>
              <div className="task-graph-node-policy-list">
                {activeGraphEdges.map((edge, index) => {
                  const edgeId = String(edge.edge_id ?? edge.id ?? `${String(edge.source_node_id ?? edge.from ?? "source")}-${String(edge.target_node_id ?? edge.to ?? "target")}-${index}`);
                  const metadata = asRecord(edge.metadata);
                  const role = String(metadata.runtime_semantic_role ?? semanticRoleByEdgeId.get(edgeId) ?? "data_input");
                  return (
                  <article className="task-graph-node-policy-row" key={edgeId}>
                    <div className="task-graph-node-policy-row__identity">
                      <strong>{String(edge.source_node_id ?? edge.from ?? "")} {"->"} {String(edge.target_node_id ?? edge.to ?? "")}</strong>
                      <span>{edgeId}</span>
                    </div>
                    <TaskSystemSelectField
                      label="通用职责"
                      onChange={(value) => patchEdgeRuntimeSemanticRole(edge, edgeId, value)}
                      options={EDGE_SEMANTIC_ROLE_OPTIONS}
                      value={role}
                    />
                  </article>
                  );
                })}
              </div>
            </article>
          </div>
          {runtimeSemanticsDiagnostics.length ? (
            <div className="task-graph-preflight-list">
              {runtimeSemanticsDiagnostics.slice(0, 8).map((issue, index) => (
                <article className="task-graph-preflight-row" key={`${String(issue.code ?? "runtime_semantics")}_${index}`}>
                  <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "warning")}`}>
                    {String(issue.severity ?? "warning")}
                  </span>
                  <div>
                    <strong>{String(issue.code ?? "runtime_semantics")}</strong>
                    <span>{String(issue.message ?? "")}</span>
                    <small>{String(issue.scope ?? "graph")} / {String(issue.ref_id ?? "-")} / {String(issue.field ?? "-")}</small>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </>
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
                <span>阶段定义生命周期 scope；它不应该替代显式边，也不应该被当成运行 step。</span>
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
          <header><strong>边生命周期语义</strong><span>{activeGraphEdges.length} 条边</span></header>
          <div className="task-graph-note">
            <strong>边不是执行端，但边决定依赖和可见性</strong>
            <span>这里声明上游结果何时触发下游、何时可见、是否需要确认，以及失败后如何传播。</span>
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

      {facet === "coordinates" ? (
        <section className="boundary-card">
          <header><strong>节点激活坐标</strong><span>{temporalEdges.length} 条显式时序边</span></header>
          <div className="task-graph-note">
            <strong>phase/sequence 是旧运行坐标，不是通用因果关系</strong>
            <span>新图应通过显式边、边职责和产物状态表达启动条件；这里保留旧坐标用于迁移、展示和现有 scheduler 兼容。</span>
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
                  <TaskSystemField label="旧顺序坐标">
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
