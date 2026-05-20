"use client";

import { useState } from "react";
import { CheckCircle2, MessageSquareShare, PlayCircle, RefreshCw, Save, Send, TriangleAlert } from "lucide-react";

import {
  buildTaskSystemTaskGraphExecutionPackage,
  compileTaskSystemTaskGraphContractManifest,
  getOrchestrationRuntimeLoopTrace,
  taskGraphRunIdOf,
  taskGraphRunsFromTrace,
  latestTaskGraphRunFromTrace,
  resumeOrchestrationTaskGraphRun,
  startTaskGraphRuntimeLoopRun,
  stopOrchestrationTaskRun,
  type RuntimeLoopTaskRunTrace,
  type TaskGraphRuntimeSpec,
  type TaskGraphStandardView,
  type ContractManifest,
  type TaskGraphExecutionPackage,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { focusForPreflightIssue, focusTargetLabel } from "./taskGraphEditorFocus";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";
import { buildTaskGraphSchedulerSummary, schedulerStateFromTrace } from "./taskGraphRuntimeView";

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join(" / ") : "";
}

function runtimeIssueTitle(issue: Record<string, unknown>, index: number) {
  return String(issue.code ?? issue.message ?? `issue_${index + 1}`);
}

function recordValue(record: Record<string, unknown> | null | undefined, key: string) {
  return record && typeof record === "object" ? record[key] : undefined;
}

function recordArrayValue(record: Record<string, unknown> | null | undefined, key: string) {
  const value = recordValue(record, key);
  return Array.isArray(value) ? value : [];
}

function recordNumberValue(record: Record<string, unknown> | null | undefined, key: string) {
  const value = recordValue(record, key);
  return typeof value === "number" ? value : Number(value || 0);
}

function repairActionLabel(issue: TaskGraphPreflightIssue) {
  if (issue.source === "frontend.preflight.prompt_semantics") return "补全职责字段";
  if (issue.source === "frontend.preflight.projection_binding") return "迁移到投影";
  if (issue.source === "frontend.preflight.cognition_packet") return "补输入说明";
  if (issue.source === "frontend.preflight.contract" && issue.scope === "edge") return "补默认载荷契约";
  if (issue.source === "frontend.preflight.memory_handoff") return "补摘要交接";
  if (issue.source === "frontend.preflight.memory_selector") return "配置 Selector";
  if (issue.source === "frontend.preflight.memory_commit_path") return "补提交路径";
  if (issue.source === "frontend.preflight.revision_packet") return "补返修包";
  if (issue.source === "frontend.preflight.artifact") return "配置产物目标";
  if (issue.source === "frontend.preflight.human_gate") return "配置人工工作单";
  if (issue.source === "frontend.preflight.timeline" && issue.scope === "phase") return "补阶段定义";
  return "";
}

function preflightIssueGroup(issue: TaskGraphPreflightIssue) {
  if (issue.source.includes("projection") || issue.source.includes("prompt") || issue.source.includes("cognition")) return "职责与输入包";
  if (issue.source.includes("memory") || issue.source.includes("artifact") || issue.source.includes("commit_visibility")) return "资源流";
  if (issue.source.includes("timeline") || issue.source.includes("revision")) return "拓扑时序";
  if (issue.source.includes("human_gate") || issue.source.includes("manual")) return "人工执行";
  if (issue.source.includes("contract") || issue.source.includes("review_gate")) return "契约与质量门";
  if (issue.source.includes("runtime") || issue.source.includes("scheduler")) return "运行装配";
  return "图结构";
}

function preflightIssueFocusLabel(issue: TaskGraphPreflightIssue) {
  return focusTargetLabel(focusForPreflightIssue(issue));
}

export function TaskGraphPublishRunPage({
  dirty,
  edges,
  editorIssueCount,
  editorValid,
  graphId,
  metadata,
  nodes,
  standardView,
  onPublish,
  onSave,
  onSendToChat,
  onFocusIssue,
  onRunBound,
  onRepairIssue,
  publishState,
  saving,
}: {
  dirty: boolean;
  edges: Array<Record<string, unknown>>;
  editorIssueCount: number;
  editorValid: boolean;
  graphId: string;
  metadata?: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  standardView?: TaskGraphStandardView | null;
  onPublish: () => void;
  onSave: () => void;
  onSendToChat: () => void;
  onFocusIssue?: (issue: TaskGraphPreflightIssue) => void;
  onRunBound?: () => void;
  onRepairIssue?: (issue: TaskGraphPreflightIssue) => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
}) {
  const {
    bindTaskGraphMonitorRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphMonitorBinding,
    taskGraphMonitorDecision,
    taskGraphMonitorDecisions,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
  } = useAppStore();
  const [runtimeSpec, setRuntimeSpec] = useState<TaskGraphRuntimeSpec | null>(null);
  const [contractManifest, setContractManifest] = useState<ContractManifest | null>(null);
  const [executionPackage, setExecutionPackage] = useState<TaskGraphExecutionPackage | null>(null);
  const [runtimeSpecError, setRuntimeSpecError] = useState("");
  const [runtimeSpecLoading, setRuntimeSpecLoading] = useState(false);
  const [taskRunId, setTaskRunId] = useState("");
  const [runTrace, setRunTrace] = useState<RuntimeLoopTaskRunTrace | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runStartLoading, setRunStartLoading] = useState(false);
  const [runSessionId, setRunSessionId] = useState("session:task_graph_studio");
  const [resumeLoading, setResumeLoading] = useState(false);
  const [stopLoading, setStopLoading] = useState(false);
  const published = isTaskGraphPublishedState(publishState);
  const latestRunStatus = String(runTrace?.task_run?.status ?? "").trim();
  const taskGraphRuns = taskGraphRunsFromTrace(runTrace);
  const runStatusLabel = latestRunStatus || (publishState === "run_bound" ? "bound" : published ? "ready" : "draft");
  const schedulerSummary = buildTaskGraphSchedulerSummary(schedulerStateFromTrace(runTrace));
  const preflightReport = buildTaskGraphPreflightReport({
    dirty,
    editorIssueCount,
    editorValid,
    metadata,
    nodes,
    edges,
    runtimeSpec,
    standardView,
  });
  const preflightGroups = Array.from(
    preflightReport.issues.reduce((groups, issue) => {
      const group = preflightIssueGroup(issue);
      groups.set(group, [...(groups.get(group) ?? []), issue]);
      return groups;
    }, new Map<string, TaskGraphPreflightIssue[]>()),
  );
  const boundTemporal = taskGraphBoundRunMonitor?.temporal;
  const boundTemporalViolations = boundTemporal?.violations ?? [];
  const graphUnitExecutionPlans = executionPackage?.graph_unit_execution_plans ?? [];
  const objectTraceIndex = executionPackage?.object_trace_index ?? [];

  async function compileRuntimeSpec() {
    if (!graphId) return;
    setRuntimeSpecLoading(true);
    setRuntimeSpecError("");
    try {
      const nextPackage = await buildTaskSystemTaskGraphExecutionPackage(graphId);
      setExecutionPackage(nextPackage);
      setRuntimeSpec(nextPackage.runtime_spec);
      setContractManifest(nextPackage.contract_manifest);
    } catch (error) {
      setExecutionPackage(null);
      setRuntimeSpec(null);
      setContractManifest(null);
      setRuntimeSpecError(error instanceof Error ? error.message : "执行包编译失败");
    } finally {
      setRuntimeSpecLoading(false);
    }
  }

  async function loadRunTrace() {
    if (!taskRunId.trim()) return;
    setRunTraceLoading(true);
    setRunTraceError("");
    try {
      setRunTrace(await getOrchestrationRuntimeLoopTrace(taskRunId.trim(), { includePayloads: false, includeModelMessages: false }));
    } catch (error) {
      setRunTrace(null);
      setRunTraceError(error instanceof Error ? error.message : "运行追踪读取失败");
    } finally {
      setRunTraceLoading(false);
    }
  }

  async function startRun() {
    if (!graphId) return;
    setRunStartLoading(true);
    setRunTraceError("");
    try {
      const result = await startTaskGraphRuntimeLoopRun(graphId, {
        session_id: runSessionId.trim() || "session:task_graph_studio",
        include_trace: true,
        require_published: true,
      });
      setTaskRunId(result.task_run_id);
      setRuntimeSpec(result.runtime_spec);
      setContractManifest(await compileTaskSystemTaskGraphContractManifest(graphId));
      setRunTrace(result.trace);
      bindTaskGraphMonitorRun({
        task_run_id: result.task_run_id,
        coordination_run_id: result.coordination_run_id,
        graph_id: graphId,
        session_id: runSessionId.trim() || "session:task_graph_studio",
        title: graphId,
      });
      onRunBound?.();
    } catch (error) {
      setRunTrace(null);
      setRunTraceError(error instanceof Error ? error.message : "运行创建失败");
    } finally {
      setRunStartLoading(false);
    }
  }

  async function resumeLatestTaskGraphRun() {
    const latestTaskGraphRun = latestTaskGraphRunFromTrace(runTrace);
    const taskGraphRunId = taskGraphRunIdOf(latestTaskGraphRun);
    if (!taskGraphRunId) {
      setRunTraceError("当前 trace 没有可续跑的任务图运行。");
      return;
    }
    setResumeLoading(true);
    setRunTraceError("");
    try {
      await resumeOrchestrationTaskGraphRun(taskGraphRunId, { source: "task_graph_studio", task_graph_id: graphId });
      await loadRunTrace();
    } catch (error) {
      setRunTraceError(error instanceof Error ? error.message : "续跑失败");
    } finally {
      setResumeLoading(false);
    }
  }

  async function stopLatestRun() {
    if (!taskRunId.trim()) {
      setRunTraceError("当前没有可停止的 TaskRun。");
      return;
    }
    setStopLoading(true);
    setRunTraceError("");
    try {
      await stopOrchestrationTaskRun(taskRunId.trim(), {
        reason: "user_aborted",
        message: "TaskGraph Studio 手动停止运行",
        coordination_run_id: taskGraphRunIdOf(latestTaskGraphRunFromTrace(runTrace)),
      });
      await loadRunTrace();
    } catch (error) {
      setRunTraceError(error instanceof Error ? error.message : "停止失败");
    } finally {
      setStopLoading(false);
    }
  }

  function bindManualTaskRun() {
    if (!taskRunId.trim()) {
      setRunTraceError("请先输入 TaskRun ID。");
      return;
    }
    setRunTraceError("");
    bindTaskGraphMonitorRun({
      task_run_id: taskRunId.trim(),
      coordination_run_id: taskGraphRunIdOf(latestTaskGraphRunFromTrace(runTrace)),
      graph_id: graphId,
      session_id: runSessionId.trim() || undefined,
      title: graphId,
    });
  }

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>预检与运行</strong>
        <small>把草稿保存、发布、带入会话和运行准备收束成一个闭环。</small>
      </header>

      <section className="task-graph-publish-strip">
        <article className={preflightReport.valid ? "task-graph-publish-step task-graph-publish-step--ok" : "task-graph-publish-step task-graph-publish-step--warn"}>
          {preflightReport.valid ? <CheckCircle2 aria-hidden="true" size={18} /> : <TriangleAlert aria-hidden="true" size={18} />}
          <span>预检</span>
          <strong>{preflightReport.valid ? "当前可发布" : `${preflightReport.error_count} 个阻塞`}</strong>
        </article>
        <article className={published ? "task-graph-publish-step task-graph-publish-step--ok" : "task-graph-publish-step"}>
          <Send aria-hidden="true" size={18} />
          <span>发布</span>
          <strong>{taskGraphPublishStateLabel(publishState)}</strong>
        </article>
        <article className={publishState === "run_bound" || latestRunStatus ? "task-graph-publish-step task-graph-publish-step--ok" : "task-graph-publish-step"}>
          <PlayCircle aria-hidden="true" size={18} />
          <span>运行</span>
          <strong>{latestRunStatus ? latestRunStatus : publishState === "run_bound" ? "已绑定运行" : published ? "可创建运行" : "等待发布"}</strong>
        </article>
      </section>

      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>发布动作</strong></header>
          <div className="boundary-actions">
            <TaskSystemToolbarButton disabled={saving === "task-graph"} onClick={onSave}>
              <Save size={15} />保存草稿
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!preflightReport.valid || saving === "task-graph"} onClick={onPublish} variant="primary">
              <Send size={15} />发布可运行
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={onSendToChat}>
              <MessageSquareShare size={15} />带入会话
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!graphId || runtimeSpecLoading} onClick={() => void compileRuntimeSpec()}>
              <RefreshCw size={15} />编译执行包
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton
              disabled={!graphId || !published || !preflightReport.valid || runStartLoading}
              onClick={() => void startRun()}
              variant="primary"
            >
              <PlayCircle size={15} />创建运行
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskRunId || stopLoading} onClick={() => void stopLatestRun()}>
              <TriangleAlert size={15} />停止运行
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskRunId || resumeLoading} onClick={() => void resumeLatestTaskGraphRun()}>
              <RefreshCw size={15} />断点重连
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskRunId || taskGraphMonitorLoading} onClick={bindManualTaskRun}>
              <MessageSquareShare size={15} />绑定监控
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading} onClick={() => void evaluateBoundTaskGraphMonitor()}>
              <TriangleAlert size={15} />监测评估
            </TaskSystemToolbarButton>
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>运行准备</strong></header>
          <div className="task-graph-mini-kv">
            <p><span>节点</span><strong>{nodes.length}</strong></p>
            <p><span>边</span><strong>{edges.length}</strong></p>
            <p><span>图状态</span><strong>{taskGraphPublishStateLabel(publishState)}</strong></p>
            <p><span>运行态</span><strong>{runStatusLabel}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>{published ? (publishState === "run_bound" ? "当前图已绑定运行" : "可创建真实运行") : "发布后才能创建运行"}</strong>
            <span>创建运行会调用后端 TaskGraph 运行入口，生成真实 TaskRun、TaskGraphRun、checkpoint 和 trace。</span>
          </div>
        </article>
      </section>

      <section className="boundary-card">
        <header><strong>发布执行包</strong><span>ContractManifest / RuntimeSpec / GraphUnit</span></header>
        {executionPackage ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>执行包</span><strong>{executionPackage.valid ? "通过" : "待修复"}</strong></p>
              <p><span>Assembly</span><strong>{executionPackage.node_runtime_assemblies.length}</strong></p>
              <p><span>GraphUnit</span><strong>{executionPackage.graph_units.length}</strong></p>
              <p><span>图节点契约</span><strong>{String(executionPackage.summary.graph_unit_handoff_contract_count ?? 0)}</strong></p>
              <p><span>子图计划</span><strong>{graphUnitExecutionPlans.length}</strong></p>
              <p><span>对象追溯</span><strong>{String(executionPackage.summary.object_trace_count ?? objectTraceIndex.length)}</strong></p>
              <p><span>Scheduler Ready</span><strong>{String(executionPackage.summary.scheduler_ready_count ?? 0)}</strong></p>
              <p><span>Scheduler Blocked</span><strong>{String(executionPackage.summary.scheduler_blocked_count ?? 0)}</strong></p>
              <p><span>总问题</span><strong>{executionPackage.issues.length}</strong></p>
            </div>
            <div className="task-graph-note">
              <strong>{executionPackage.package_id}</strong>
              <span>这是一份发布前真实执行包：standard view、manifest、runtime spec、scheduler shadow 与节点 assembly 来自同一份后端编译结果。</span>
            </div>
            {executionPackage.node_runtime_assemblies.length ? (
              <div className="task-graph-preflight-list">
                {executionPackage.node_runtime_assemblies.slice(0, 6).map((assembly) => (
                  <article className="task-graph-preflight-row" key={String(assembly.assembly_id)}>
                    <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">assembly</span>
                    <div>
                      <strong>{assembly.node_id || assembly.task_ref || assembly.assembly_id}</strong>
                      <span>context {assembly.context_sections.length} / output {assembly.output_contracts.length} / handoff {(assembly.handoff_packets ?? []).length}</span>
                    </div>
                    <em>{assembly.agent_id || "-"}</em>
                    <small>{assembly.projection_id || assembly.runtime_lane || "runtime_assembly"}</small>
                  </article>
                ))}
              </div>
            ) : null}
            {objectTraceIndex.length ? (
              <section className="task-graph-runtime-spec-panel">
                <header><strong>对象追溯索引</strong><span>Graph object {"->"} runtime facts</span></header>
                <div className="task-graph-preflight-list">
                  {objectTraceIndex.slice(0, 8).map((item, index) => {
                    const runtimeRef = recordValue(item, "runtime_ref") as Record<string, unknown> | null | undefined;
                    const manifestRef = recordValue(item, "manifest_ref") as Record<string, unknown> | null | undefined;
                    const schedulerRef = recordValue(item, "scheduler_ref") as Record<string, unknown> | null | undefined;
                    return (
                      <article className="task-graph-preflight-row" key={`${String(recordValue(item, "object_type") ?? "object")}_${String(recordValue(item, "object_id") ?? index)}`}>
                        <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">
                          {String(recordValue(item, "object_type") ?? "object")}
                        </span>
                        <div>
                          <strong>{String(recordValue(item, "title") ?? recordValue(item, "object_id") ?? "未命名对象")}</strong>
                          <span>
                            runtime {String(recordValue(runtimeRef, "node_id") ?? recordValue(runtimeRef, "edge_id") ?? recordValue(runtimeRef, "runtime_node_id") ?? recordValue(runtimeRef, "runtime_spec_graph_id") ?? "-")} /
                            manifest {String(recordValue(manifestRef, "node_contract_id") ?? recordValue(manifestRef, "edge_contract_id") ?? recordValue(manifestRef, "handoff_contract_id") ?? recordValue(manifestRef, "manifest_id") ?? "-")}
                          </span>
                        </div>
                        <em>{String(recordValue(schedulerRef, "status") ?? recordValue(item, "status") ?? "-")}</em>
                        <small>{String(recordValue(item, "source_path") ?? "")}</small>
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}
            {graphUnitExecutionPlans.length ? (
              <section className="task-graph-runtime-spec-panel">
                <header><strong>GraphUnit 子图执行计划</strong><span>Parent node / Child package preview</span></header>
                <div className="task-graph-preflight-list">
                  {graphUnitExecutionPlans.map((plan, index) => {
                    const childGraph = recordValue(plan, "child_graph") as Record<string, unknown> | null | undefined;
                    const runtimeSummary = recordValue(plan, "child_runtime_spec_summary") as Record<string, unknown> | null | undefined;
                    const manifestSummary = recordValue(plan, "child_contract_manifest_summary") as Record<string, unknown> | null | undefined;
                    const schedulerSummary = recordValue(plan, "child_scheduler_summary") as Record<string, unknown> | null | undefined;
                    const assemblySummary = recordValue(plan, "child_node_runtime_assembly_summary") as Record<string, unknown> | null | undefined;
                    const planIssues = recordArrayValue(plan, "issues");
                    const valid = recordValue(plan, "valid") !== false && !planIssues.some((issue) => String((issue as Record<string, unknown>).severity ?? "error") === "error");
                    return (
                      <article className="task-graph-preflight-row task-graph-preflight-row--stacked" key={`${String(recordValue(plan, "plan_id") ?? index)}`}>
                        <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${valid ? "info" : "error"}`}>
                          {valid ? "ready" : "blocked"}
                        </span>
                        <div>
                          <strong>{String(recordValue(childGraph, "title") ?? recordValue(plan, "linked_graph_id") ?? "未绑定子图")}</strong>
                          <span>
                            父节点 {String(recordValue(plan, "runtime_node_id") ?? "-")} / 子图 {String(recordValue(plan, "linked_graph_id") ?? "-")} / 版本 {String(recordValue(plan, "version_ref") ?? "未锚定")}
                          </span>
                          <small>
                            Runtime {recordNumberValue(runtimeSummary, "node_count")} 节点 / {recordNumberValue(runtimeSummary, "edge_count")} 边；
                            Manifest {recordNumberValue(manifestSummary, "node_contract_count")} 节点契约 / {recordNumberValue(manifestSummary, "edge_handoff_contract_count")} 边契约；
                            Scheduler ready {recordArrayValue(schedulerSummary, "ready_node_ids").length} / blocked {recordArrayValue(schedulerSummary, "blocked_node_ids").length}；
                            Assembly {recordNumberValue(assemblySummary, "assembly_count")}
                          </small>
                          {planIssues.length ? (
                            <small>{planIssues.map((issue) => String((issue as Record<string, unknown>).code ?? "graph_unit_issue")).join(" / ")}</small>
                          ) : null}
                        </div>
                        <em>{String(recordValue(plan, "handoff_contract_id") ?? "无交接契约")}</em>
                        <small>{String(recordValue(plan, "isolation_policy") ?? "isolated_per_nested_run")}</small>
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
        {contractManifest ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>Manifest</span><strong>{contractManifest.valid ? "通过" : "待修复"}</strong></p>
              <p><span>图契约</span><strong>{Object.keys(contractManifest.graph_contract_bindings ?? {}).length}</strong></p>
              <p><span>节点契约</span><strong>{contractManifest.node_contracts.length}</strong></p>
              <p><span>边契约</span><strong>{contractManifest.edge_handoff_contracts.length}</strong></p>
              <p><span>图节点契约</span><strong>{(contractManifest.graph_unit_handoff_contracts ?? []).length}</strong></p>
              <p><span>问题</span><strong>{contractManifest.issues.length}</strong></p>
            </div>
            {(contractManifest.graph_unit_handoff_contracts ?? []).length ? (
              <div className="task-graph-preflight-list">
                {(contractManifest.graph_unit_handoff_contracts ?? []).slice(0, 6).map((item, index) => (
                  <article className="task-graph-preflight-row" key={`${String(recordValue(item, "plan_id") ?? index)}_graph_unit_handoff`}>
                    <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">graph_unit</span>
                    <div>
                      <strong>{String(recordValue(item, "linked_graph_id") ?? "未绑定子图")}</strong>
                      <span>
                        {String(recordValue(item, "runtime_node_id") ?? "-")} / {String(recordValue(item, "input_port_id") ?? "input.default")} {"->"} {String(recordValue(item, "output_port_id") ?? "output.default")}
                      </span>
                    </div>
                    <em>{String(recordValue(item, "handoff_contract_id") ?? "无交接契约")}</em>
                    <small>graph_unit_handoff</small>
                  </article>
                ))}
              </div>
            ) : null}
            {contractManifest.issues.length ? (
              <div className="task-graph-preflight-list">
                {contractManifest.issues.slice(0, 8).map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${issue.code}_${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "error")}`}>
                      {String(issue.severity ?? "error")}
                    </span>
                    <div>
                      <strong>{issue.code}</strong>
                      <span>{issue.message}</span>
                    </div>
                    <em>{issue.node_id || issue.edge_id || issue.source_ref}</em>
                    <small>contract_manifest</small>
                  </article>
                ))}
              </div>
            ) : (
              <div className="task-graph-note">
                <strong>契约清单没有阻塞问题</strong>
                <span>图、节点、边的 contract_bindings 已经进入发布前清单。</span>
              </div>
            )}
          </div>
        ) : null}
        {runtimeSpec ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>来源</span><strong>{String(runtimeSpec.diagnostics?.source ?? "runtime_spec")}</strong></p>
              <p><span>节点</span><strong>{runtimeSpec.nodes.length}</strong></p>
              <p><span>有效</span><strong>{runtimeSpec.valid ? "通过" : "待修复"}</strong></p>
              <p><span>起点</span><strong>{listText(runtimeSpec.start_node_ids) || "-"}</strong></p>
              <p><span>终点</span><strong>{listText(runtimeSpec.terminal_node_ids) || "-"}</strong></p>
              <p><span>通信</span><strong>{listText(runtimeSpec.communication_modes) || "-"}</strong></p>
              <p><span>GraphUnit</span><strong>{(runtimeSpec.nested_runtime_plans ?? runtimeSpec.graph_units ?? []).length}</strong></p>
            </div>
            {(runtimeSpec.nested_runtime_plans ?? runtimeSpec.graph_units ?? []).length ? (
              <div className="task-graph-preflight-list">
                {(runtimeSpec.nested_runtime_plans ?? runtimeSpec.graph_units ?? []).map((plan, index) => (
                  <article className="task-graph-preflight-row" key={`${String(plan.plan_id ?? plan.runtime_node_id ?? index)}`}>
                    <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">graph_unit</span>
                    <div>
                      <strong>{String(plan.linked_graph_id ?? "未绑定子图")}</strong>
                      <span>{String(plan.plan_id ?? "")} / {String(plan.version_ref ?? "未锚定版本")}</span>
                    </div>
                    <em>{String(plan.runtime_node_id ?? plan.unit_id ?? "")}</em>
                    <small>{String(plan.handoff_contract_id ?? "无交接契约")}</small>
                  </article>
                ))}
              </div>
            ) : null}
            {runtimeSpec.issues.length ? (
              <div className="task-graph-preflight-list">
                {runtimeSpec.issues.map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${runtimeIssueTitle(issue, index)}_${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "error")}`}>
                      {String(issue.severity ?? "error")}
                    </span>
                    <div>
                      <strong>{runtimeIssueTitle(issue, index)}</strong>
                      <span>{String(issue.message ?? "运行规范问题")}</span>
                    </div>
                    <em>{String(issue.node_id ?? issue.edge_id ?? "runtime")}</em>
                    <small>backend.runtime_spec</small>
                  </article>
                ))}
              </div>
            ) : (
              <div className="task-graph-note">
                <strong>运行规范没有阻塞问题</strong>
                <span>后端 direct compiler 已经返回可运行的 runtime spec。</span>
              </div>
            )}
            <details className="task-graph-runtime-spec-details">
              <summary>RuntimeSpec Diagnostics</summary>
              <pre>{JSON.stringify(runtimeSpec.diagnostics ?? {}, null, 2)}</pre>
            </details>
            {contractManifest ? (
              <details className="task-graph-runtime-spec-details">
                <summary>ContractManifest</summary>
                <pre>{JSON.stringify(contractManifest, null, 2)}</pre>
              </details>
            ) : null}
          </div>
        ) : (
          <div className={runtimeSpecError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
            <strong>{runtimeSpecError ? "运行规范不可用" : "尚未编译运行规范"}</strong>
            <span>{runtimeSpecError || "点击“编译执行包”后，平台会从 TaskGraphDefinition 生成 ContractManifest 与 RuntimeSpec。"}</span>
          </div>
        )}
      </section>

      <section className="boundary-card">
        <header><strong>运行追踪与续跑</strong><span>Trace / Checkpoint / Resume</span></header>
        <div className="boundary-form">
          <label>
            <span>Session ID</span>
            <input value={runSessionId} onChange={(event) => setRunSessionId(event.target.value)} placeholder="session:task_graph_studio" />
          </label>
          <label>
            <span>TaskRun ID</span>
            <input value={taskRunId} onChange={(event) => setTaskRunId(event.target.value)} placeholder="task_run_xxx" />
          </label>
        </div>
        <div className="boundary-actions">
          <TaskSystemToolbarButton disabled={!taskRunId.trim() || runTraceLoading} onClick={() => void loadRunTrace()}>
            <RefreshCw size={15} />读取 Trace
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!graphId || !published || !preflightReport.valid || runStartLoading} onClick={() => void startRun()}>
            <PlayCircle size={15} />创建新运行
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!runTrace || resumeLoading} onClick={() => void resumeLatestTaskGraphRun()}>
            <PlayCircle size={15} />续跑最近任务图运行
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskRunId.trim()} onClick={bindManualTaskRun}>
            <MessageSquareShare size={15} />绑定常驻监控
          </TaskSystemToolbarButton>
        </div>
        {runTrace ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>TaskRun</span><strong>{String(runTrace.task_run?.task_run_id ?? runTrace.task_run?.run_id ?? taskRunId)}</strong></p>
              <p><span>状态</span><strong>{String(runTrace.task_run?.status ?? "unknown")}</strong></p>
              <p><span>TaskGraphRun</span><strong>{taskGraphRuns.length}</strong></p>
              <p><span>事件</span><strong>{runTrace.event_count}</strong></p>
              <p><span>Checkpoint</span><strong>{runTrace.latest_checkpoint ? "存在" : "无"}</strong></p>
            </div>
            {schedulerSummary.available ? (
              <section className="task-graph-runtime-spec-panel">
                <header><strong>TaskGraph 调度视图</strong><span>{schedulerSummary.mode || "shadow"}</span></header>
                <div className="task-graph-mini-kv">
                  <p><span>Phase</span><strong>{schedulerSummary.phase_count}</strong></p>
                  <p><span>Ready</span><strong>{schedulerSummary.ready_node_ids.length}</strong></p>
                  <p><span>Blocked</span><strong>{schedulerSummary.blocked_node_ids.length}</strong></p>
                  <p><span>Running</span><strong>{schedulerSummary.running_node_ids.length}</strong></p>
                  <p><span>Done</span><strong>{schedulerSummary.completed_node_ids.length}</strong></p>
                  <p><span>Terminal</span><strong>{schedulerSummary.terminal_status || "-"}</strong></p>
                </div>
                <div className="task-graph-note">
                  <strong>当前 active phase：{schedulerSummary.active_phase_ids.join(" / ") || "-"}</strong>
                  <span>当前阶段顺序：{Object.entries(schedulerSummary.active_sequence_by_phase).map(([phase, value]) => `${phase}=S${value}`).join(" / ") || "-"}</span>
                </div>
                <div className="task-graph-preflight-list">
                  {schedulerSummary.phase_states.slice(0, 6).map((phase) => (
                    <article className="task-graph-preflight-row" key={String(phase.phase_id ?? phase.id)}>
                      <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">
                        {String(phase.status ?? "phase")}
                      </span>
                      <div>
                        <strong>{String(phase.phase_id ?? "phase")}</strong>
                        <span>ready {Array.isArray(phase.ready_node_ids) ? phase.ready_node_ids.length : 0} / blocked {Array.isArray(phase.blocked_node_ids) ? phase.blocked_node_ids.length : 0}</span>
                      </div>
                      <em>{Array.isArray(phase.node_ids) ? phase.node_ids.length : 0} nodes</em>
                      <small>scheduler.phase</small>
                    </article>
                  ))}
                </div>
              </section>
            ) : (
              <div className="task-graph-note">
                <strong>尚无 TaskGraph 调度视图</strong>
                <span>新运行会在任务图运行 diagnostics 中写入 shadow scheduler state，用于观察 phase、node 和 edge 的调度判断。</span>
              </div>
            )}
            <details className="task-graph-runtime-spec-details">
              <summary>Trace JSON</summary>
              <pre>{JSON.stringify({
                task_run: runTrace.task_run,
                latest_checkpoint: runTrace.latest_checkpoint,
                task_graph_runs: taskGraphRuns,
              }, null, 2)}</pre>
            </details>
          </div>
        ) : (
          <div className={runTraceError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
            <strong>{runTraceError ? "运行追踪不可用" : "尚未读取运行追踪"}</strong>
            <span>{runTraceError || "输入已有 TaskRun ID 后，可以读取真实 runtime-loop trace 和 checkpoint。"}</span>
          </div>
        )}
      </section>

      <section className="boundary-card">
        <header><strong>运行交互窗口</strong><span>runtime_monitor / run control</span></header>
        <div className="boundary-actions">
          <TaskSystemToolbarButton disabled={!taskRunId.trim()} onClick={bindManualTaskRun}>
            <MessageSquareShare size={15} />绑定当前 TaskRun
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading} onClick={() => void evaluateBoundTaskGraphMonitor()}>
            <TriangleAlert size={15} />执行一次监测
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding} onClick={() => setTaskGraphRunInteractionOpen(true)}>
            <MessageSquareShare size={15} />打开交互窗口
          </TaskSystemToolbarButton>
        </div>
        {taskGraphMonitorBinding ? (
          <div className="task-graph-note">
            <strong>已绑定常驻监控：{taskGraphMonitorBinding.title || taskGraphMonitorBinding.graph_id || "TaskGraph Run"}</strong>
            <span>{taskGraphMonitorBinding.task_run_id}</span>
          </div>
        ) : (
          <div className="task-graph-note">
            <strong>尚未绑定常驻监控</strong>
            <span>创建运行或输入 TaskRun ID 后点击绑定，浮窗会按 TaskRun 独立轮询，不再跟随聊天会话。</span>
          </div>
        )}
        {taskGraphBoundRunMonitor ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>状态</span><strong>{taskGraphBoundRunMonitor.runtime?.status || "unknown"}</strong></p>
              <p><span>当前节点</span><strong>{taskGraphBoundRunMonitor.runtime?.active_node_id || "-"}</strong></p>
              <p><span>Activation</span><strong>{boundTemporal?.active_activation_id || "-"}</strong></p>
              <p><span>执行许可</span><strong>{boundTemporal?.active_execution_permit_id || "-"}</strong></p>
              <p><span>边界</span><strong>{boundTemporal?.boundary_valid ? "有效" : "未闭合"}</strong></p>
              <p><span>时序违规</span><strong>{boundTemporalViolations.length}</strong></p>
              <p><span>事件</span><strong>{taskGraphBoundRunMonitor.runtime?.event_count ?? 0}</strong></p>
              <p><span>流式</span><strong>{taskGraphBoundRunMonitor.streaming?.enabled ? `${taskGraphBoundRunMonitor.streaming.chunk_count} 片 / ${taskGraphBoundRunMonitor.streaming.accumulated_chars} 字` : "未启用"}</strong></p>
            </div>
            {boundTemporalViolations.length ? (
              <div className="task-graph-preflight-list">
                {boundTemporalViolations.slice(0, 4).map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${issue.code}:${issue.target_id}:${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${issue.severity || "error"}`}>
                      {issue.severity || "error"}
                    </span>
                    <div>
                      <strong>{issue.code || "temporal_violation"}</strong>
                      <span>{issue.message || "节点运行不在当前拓扑时序许可窗口内。"}</span>
                    </div>
                    <em>{issue.target_id || boundTemporal?.active_node_id || "runtime"}</em>
                    <small>monitor.temporal</small>
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {taskGraphMonitorDecision ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>Action</span><strong>{taskGraphMonitorDecision.action}</strong></p>
              <p><span>Reason</span><strong>{taskGraphMonitorDecision.reason}</strong></p>
              <p><span>Severity</span><strong>{taskGraphMonitorDecision.severity}</strong></p>
              <p><span>Monitor</span><strong>{taskGraphMonitorDecision.monitor_node_id || "runtime_monitor"}</strong></p>
            </div>
            <div className={taskGraphMonitorDecision.action === "no_action" ? "task-graph-note" : "task-graph-note task-graph-note--danger"}>
              <strong>{taskGraphMonitorDecision.summary}</strong>
              <span>需要处理时会在常驻浮窗内展示统一运行交互请求。</span>
            </div>
            <details className="task-graph-runtime-spec-details">
              <summary>Monitor Decision</summary>
              <pre>{JSON.stringify(taskGraphMonitorDecision, null, 2)}</pre>
            </details>
          </div>
        ) : (
          <div className="task-graph-note">
            <strong>尚未执行监测评估</strong>
            <span>{taskGraphMonitorError || "点击“执行一次监测”会读取后端 task_graph.run_monitor 快照，并写入 SupervisionRecord。"}</span>
          </div>
        )}
        {taskGraphMonitorDecisions.length ? (
          <div className="task-graph-preflight-list">
            {taskGraphMonitorDecisions.slice(-5).reverse().map((decision) => (
              <article className="task-graph-preflight-row" key={decision.decision_id}>
                <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${decision.severity || "info"}`}>
                  {decision.severity || "info"}
                </span>
                <div>
                  <strong>{decision.action} / {decision.reason}</strong>
                  <span>{decision.summary}</span>
                </div>
                <em>{decision.monitor_node_id || "runtime_monitor"}</em>
                <small>{new Date(Number(decision.created_at || 0) * 1000).toLocaleTimeString()}</small>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      <section className="boundary-card">
        <header><strong>预检问题</strong><span>{preflightReport.error_count} 阻塞 / {preflightReport.warning_count} 警告 / {preflightReport.info_count} 提示</span></header>
        {preflightReport.issues.length ? (
          <div className="task-graph-preflight-groups">
            {preflightGroups.map(([group, groupIssues]) => (
              <section className="task-graph-preflight-group" key={group}>
                <header>
                  <strong>{group}</strong>
                  <span>{groupIssues.filter((issue) => issue.severity === "error").length} 阻塞 / {groupIssues.length} 总数</span>
                </header>
                <div className="task-graph-preflight-list">
                  {groupIssues.map((issue) => {
                    const repairLabel = repairActionLabel(issue);
                    return (
                      <article className="task-graph-preflight-row" key={issue.issue_id}>
                        <button className="task-graph-preflight-row__main" onClick={() => onFocusIssue?.(issue)} type="button">
                          <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${issue.severity}`}>
                            {issue.severity}
                          </span>
                          <div>
                            <strong>{issue.title}</strong>
                            <span>{issue.detail}</span>
                            <small>修复位置：{preflightIssueFocusLabel(issue)}</small>
                          </div>
                          <em>{issue.scope}{issue.target_id ? `:${issue.target_id}` : ""}</em>
                          <small>{issue.source}</small>
                        </button>
                        {repairLabel ? <button className="boundary-chip" onClick={() => onRepairIssue?.(issue)} type="button"><span>{repairLabel}</span></button> : null}
                      </article>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="task-graph-note">
            <strong>没有发现结构阻塞</strong>
            <span>当前图可以保存并发布。发布后仍需要由后端运行装配确认 runtime spec。</span>
          </div>
        )}
      </section>
    </section>
  );
}
