"use client";

import { useState } from "react";
import { CheckCircle2, MessageSquareShare, PlayCircle, RefreshCw, Save, Send, TriangleAlert } from "lucide-react";

import {
  buildTaskSystemTaskGraphExecutionPackage,
  compileTaskSystemTaskGraphContractManifest,
  getOrchestrationHarnessTrace,
  taskGraphRunIdOf,
  taskGraphRunsFromTrace,
  latestTaskGraphRunFromTrace,
  resumeOrchestrationTaskGraphRun,
  startTaskGraphHarnessRun,
  stopOrchestrationTaskRun,
  type HarnessTaskRunTrace,
  type TaskGraphRuntimeSpec,
  type TaskGraphStandardView,
  type ContractManifest,
  type TaskGraphExecutionPackage,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { TaskGraphExecutionPackagePanel } from "./TaskGraphExecutionPackagePanel";
import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { focusForPreflightIssue, focusTargetLabel } from "./taskGraphEditorFocus";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";
import {
  batchLifecycleFromTrace,
  buildTaskGraphBatchLifecycleSummary,
  buildTaskGraphSchedulerSummary,
  schedulerStateFromTrace,
} from "./taskGraphRuntimeView";

function repairActionLabel(issue: TaskGraphPreflightIssue) {
  if (issue.source === "frontend.preflight.prompt_semantics") return "补全职责字段";
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
  if (issue.source.includes("prompt") || issue.source.includes("cognition")) return "职责与输入包";
  if (issue.source.includes("memory") || issue.source.includes("artifact") || issue.source.includes("commit_visibility")) return "资源流";
  if (issue.source.includes("timeline") || issue.source.includes("revision")) return "生命周期诊断";
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
  standardViewStale = false,
  onPublish,
  onSave,
  onFocusIssue,
  onRunBound,
  onRepairIssue,
  publishState,
  saving,
  sharedContractManifest,
  sharedExecutionPackage,
  sharedRuntimeSpec,
  sharedRuntimeSpecError,
  onSharedExecutionPackageChange,
  onSharedRuntimeSpecErrorChange,
}: {
  dirty: boolean;
  edges: Array<Record<string, unknown>>;
  editorIssueCount: number;
  editorValid: boolean;
  graphId: string;
  metadata?: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  standardView?: TaskGraphStandardView | null;
  standardViewStale?: boolean;
  onPublish: () => void;
  onSave: () => void;
  onFocusIssue?: (issue: TaskGraphPreflightIssue) => void;
  onRunBound?: () => void;
  onRepairIssue?: (issue: TaskGraphPreflightIssue) => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  sharedContractManifest?: ContractManifest | null;
  sharedExecutionPackage?: TaskGraphExecutionPackage | null;
  sharedRuntimeSpec?: TaskGraphRuntimeSpec | null;
  sharedRuntimeSpecError?: string;
  onSharedExecutionPackageChange?: (value: TaskGraphExecutionPackage | null) => void;
  onSharedRuntimeSpecErrorChange?: (value: string) => void;
}) {
  const {
    bindTaskGraphMonitorRun,
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    refreshAndContinueBoundTaskGraphRun,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphMonitorBinding,
    taskGraphMonitorDecision,
    taskGraphMonitorDecisions,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
  } = useAppStore();
  const [localRuntimeSpec, setLocalRuntimeSpec] = useState<TaskGraphRuntimeSpec | null>(null);
  const [localContractManifest, setLocalContractManifest] = useState<ContractManifest | null>(null);
  const [localExecutionPackage, setLocalExecutionPackage] = useState<TaskGraphExecutionPackage | null>(null);
  const [localRuntimeSpecError, setLocalRuntimeSpecError] = useState("");
  const [runtimeSpecLoading, setRuntimeSpecLoading] = useState(false);
  const [taskRunId, setTaskRunId] = useState("");
  const [runTrace, setRunTrace] = useState<HarnessTaskRunTrace | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runStartLoading, setRunStartLoading] = useState(false);
  const [runSessionId, setRunSessionId] = useState("session:task_graph_studio");
  const [resumeLoading, setResumeLoading] = useState(false);
  const [stopLoading, setStopLoading] = useState(false);
  const published = isTaskGraphPublishedState(publishState);
  const runtimeSpec = sharedRuntimeSpec ?? localRuntimeSpec;
  const contractManifest = sharedContractManifest ?? localContractManifest;
  const executionPackage = sharedExecutionPackage ?? localExecutionPackage;
  const runtimeSpecError = sharedRuntimeSpecError ?? localRuntimeSpecError;
  const latestRunStatus = String(runTrace?.task_run?.status ?? "").trim();
  const taskGraphRuns = taskGraphRunsFromTrace(runTrace);
  const runStatusLabel = latestRunStatus || (publishState === "run_bound" ? "bound" : published ? "ready" : "draft");
  const schedulerSummary = buildTaskGraphSchedulerSummary(schedulerStateFromTrace(runTrace));
  const batchLifecycleSummary = buildTaskGraphBatchLifecycleSummary(batchLifecycleFromTrace(runTrace));
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
  const boundBatchLifecycleSummary = buildTaskGraphBatchLifecycleSummary(taskGraphBoundRunMonitor?.batch_lifecycle);
  async function compileRuntimeSpec() {
    if (!graphId) return;
    if (dirty || standardViewStale) {
      const message = "当前草稿或标准视图已过期，请先保存并刷新标准视图后再编译执行包。";
      setLocalExecutionPackage(null);
      setLocalRuntimeSpec(null);
      setLocalContractManifest(null);
      setLocalRuntimeSpecError(message);
      onSharedExecutionPackageChange?.(null);
      onSharedRuntimeSpecErrorChange?.(message);
      return;
    }
    setRuntimeSpecLoading(true);
    setLocalRuntimeSpecError("");
    onSharedRuntimeSpecErrorChange?.("");
    try {
      const nextPackage = await buildTaskSystemTaskGraphExecutionPackage(graphId);
      setLocalExecutionPackage(nextPackage);
      setLocalRuntimeSpec(nextPackage.runtime_spec);
      setLocalContractManifest(nextPackage.contract_manifest);
      onSharedExecutionPackageChange?.(nextPackage);
    } catch (error) {
      const message = error instanceof Error ? error.message : "执行包编译失败";
      setLocalExecutionPackage(null);
      setLocalRuntimeSpec(null);
      setLocalContractManifest(null);
      setLocalRuntimeSpecError(message);
      onSharedExecutionPackageChange?.(null);
      onSharedRuntimeSpecErrorChange?.(message);
    } finally {
      setRuntimeSpecLoading(false);
    }
  }

  async function loadRunTrace() {
    if (!taskRunId.trim()) return;
    setRunTraceLoading(true);
    setRunTraceError("");
    try {
      setRunTrace(await getOrchestrationHarnessTrace(taskRunId.trim(), { includePayloads: false, includeModelMessages: false }));
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
      const result = await startTaskGraphHarnessRun(graphId, {
        session_id: runSessionId.trim() || "session:task_graph_studio",
        include_trace: true,
      });
      setTaskRunId(result.task_run_id);
      setLocalRuntimeSpec(result.runtime_spec);
      setLocalContractManifest(await compileTaskSystemTaskGraphContractManifest(graphId));
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
        message: "图工作台手动停止运行",
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
        <span>图工作台</span>
        <strong>预检与运行</strong>
        <small>把草稿保存、发布、创建运行和监控绑定收束成一个闭环。</small>
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
            <TaskSystemToolbarButton disabled={!preflightReport.valid || standardViewStale || saving === "task-graph"} onClick={onPublish} variant="primary">
              <Send size={15} />发布可运行
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!graphId || dirty || standardViewStale || runtimeSpecLoading} onClick={() => void compileRuntimeSpec()}>
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
            <p><span>标准视图</span><strong>{standardViewStale ? "已过期" : standardView ? "当前" : "未载入"}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>{standardViewStale ? "请先保存并刷新标准视图" : published ? (publishState === "run_bound" ? "当前图已绑定运行" : "可创建真实运行") : "发布后才能创建运行"}</strong>
            <span>创建运行会调用后端 TaskGraph 运行入口，生成真实 TaskRun、TaskGraphRun、checkpoint 和 trace。</span>
          </div>
        </article>
      </section>

      <TaskGraphExecutionPackagePanel
        contractManifest={contractManifest}
        executionPackage={executionPackage}
        runtimeSpec={runtimeSpec}
        runtimeSpecError={runtimeSpecError}
      />

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
                  <strong>观察到的活跃坐标：{schedulerSummary.active_phase_ids.join(" / ") || "-"}</strong>
                  <span>调度权威来自显式边与等待策略；顺序坐标仅作运行观察：{Object.entries(schedulerSummary.active_sequence_by_phase).map(([phase, value]) => `${phase}=S${value}`).join(" / ") || "-"}</span>
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
            {batchLifecycleSummary.available ? (
              <section className="task-graph-runtime-spec-panel">
                <header><strong>批次生命周期</strong><span>{batchLifecycleSummary.mode || "active"}</span></header>
                <div className="task-graph-mini-kv">
                  <p><span>Plan</span><strong>{batchLifecycleSummary.summary.plan_count ?? batchLifecycleSummary.plans.length}</strong></p>
                  <p><span>Batch</span><strong>{batchLifecycleSummary.summary.batch_count ?? batchLifecycleSummary.batches.length}</strong></p>
                  <p><span>Ready</span><strong>{batchLifecycleSummary.summary.ready_batch_count ?? batchLifecycleSummary.ready_batch_ids.length}</strong></p>
                  <p><span>Running</span><strong>{batchLifecycleSummary.summary.running_batch_count ?? batchLifecycleSummary.running_batch_ids.length}</strong></p>
                  <p><span>Committed</span><strong>{batchLifecycleSummary.summary.committed_batch_count ?? batchLifecycleSummary.committed_batch_ids.length}</strong></p>
                  <p><span>Failed</span><strong>{batchLifecycleSummary.summary.failed_batch_count ?? batchLifecycleSummary.failed_batch_ids.length}</strong></p>
                  <p><span>Merge Ready</span><strong>{batchLifecycleSummary.summary.merge_ready_count ?? 0}</strong></p>
                  <p><span>Instance</span><strong>{batchLifecycleSummary.summary.execution_instance_count ?? batchLifecycleSummary.execution_instances.length}</strong></p>
                  <p><span>Active Exec</span><strong>{Object.values(batchLifecycleSummary.active_execution_by_node).filter(Boolean).length}</strong></p>
                </div>
                <div className="task-graph-batch-runtime-list">
                  {batchLifecycleSummary.batches.slice(0, 8).map((batch, index) => {
                    const range = typeof batch.range === "object" && batch.range !== null ? batch.range as Record<string, unknown> : {};
                    return (
                      <article className="task-graph-batch-runtime-row" key={`${String(batch.batch_id ?? "batch")}_${index}`}>
                        <span className={`task-graph-batch-runtime-row__status task-graph-batch-runtime-row__status--${String(batch.status ?? "planned")}`}>
                          {String(batch.status ?? "planned")}
                        </span>
                        <div>
                          <strong>{String(batch.batch_id ?? `batch_${index + 1}`)}</strong>
                          <small>{String(batch.node_id ?? "-")} · {String(batch.unit_kind ?? "unit")} · {String(range.start ?? "-")}-{String(range.end ?? "-")}</small>
                        </div>
                        <em>#{String(batch.sequence_index ?? index + 1)}</em>
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}
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
            <span>{runTraceError || "输入已有 TaskRun ID 后，可以读取真实 harness trace 和 checkpoint。"}</span>
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
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading} onClick={() => void continueBoundTaskGraphRun()}>
            <PlayCircle size={15} />续跑当前阶段
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading} onClick={() => void refreshAndContinueBoundTaskGraphRun()}>
            <RefreshCw size={15} />刷新快照续跑
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
              <p><span>批次</span><strong>{boundBatchLifecycleSummary.available ? `${boundBatchLifecycleSummary.summary.committed_batch_count ?? 0}/${boundBatchLifecycleSummary.summary.batch_count ?? 0}` : "未配置"}</strong></p>
              <p><span>Merge</span><strong>{boundBatchLifecycleSummary.available ? String(boundBatchLifecycleSummary.summary.merge_ready_count ?? 0) : "-"}</strong></p>
              <p><span>实例</span><strong>{boundBatchLifecycleSummary.available ? String(boundBatchLifecycleSummary.summary.execution_instance_count ?? boundBatchLifecycleSummary.execution_instances.length) : "-"}</strong></p>
              <p><span>活跃实例</span><strong>{boundBatchLifecycleSummary.available ? String(Object.values(boundBatchLifecycleSummary.active_execution_by_node).filter(Boolean).length) : "-"}</strong></p>
            </div>
            {boundBatchLifecycleSummary.available ? (
              <div className="task-graph-batch-runtime-list">
                {boundBatchLifecycleSummary.batches.slice(0, 6).map((batch, index) => {
                  const range = typeof batch.range === "object" && batch.range !== null ? batch.range as Record<string, unknown> : {};
                  return (
                    <article className="task-graph-batch-runtime-row" key={`${String(batch.batch_id ?? "batch")}_${index}_bound`}>
                      <span className={`task-graph-batch-runtime-row__status task-graph-batch-runtime-row__status--${String(batch.status ?? "planned")}`}>
                        {String(batch.status ?? "planned")}
                      </span>
                      <div>
                        <strong>{String(batch.batch_id ?? `batch_${index + 1}`)}</strong>
                        <small>{String(batch.unit_kind ?? "unit")} · {String(range.start ?? "-")}-{String(range.end ?? "-")}</small>
                      </div>
                      <em>#{String(batch.sequence_index ?? index + 1)}</em>
                    </article>
                  );
                })}
              </div>
            ) : null}
            {boundTemporalViolations.length ? (
              <div className="task-graph-preflight-list">
                {boundTemporalViolations.slice(0, 4).map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${issue.code}:${issue.target_id}:${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${issue.severity || "error"}`}>
                      {issue.severity || "error"}
                    </span>
                    <div>
                      <strong>{issue.code || "temporal_violation"}</strong>
                      <span>{issue.message || "节点运行不在当前显式依赖和执行许可窗口内。"}</span>
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
