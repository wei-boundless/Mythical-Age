"use client";

import { useState } from "react";
import { CheckCircle2, GitBranch, MessageSquareShare, PauseCircle, PlayCircle, RefreshCw, Save, Send, TriangleAlert } from "lucide-react";

import {
  compileTaskSystemTaskGraphContract,
  getOrchestrationHarnessTrace,
  runGraphRunUntilIdle,
  startTaskGraphHarnessRun,
  taskGraphRunsFromTrace,
  type HarnessTaskRunTrace,
  type TaskGraphContractPreview,
  type TaskGraphStandardView,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { TaskGraphContractPreviewPanel } from "./TaskGraphContractPreviewPanel";
import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { focusForPreflightIssue, focusTargetLabel } from "./taskGraphEditorFocus";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";
import { buildTaskGraphLoopPlanStandardModel } from "./taskGraphStandardView";
import {
  batchLifecycleFromTrace,
  buildTaskGraphBatchLifecycleSummary,
  buildTaskGraphLoopSummary,
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
  if (issue.source.includes("runtime") || issue.source.includes("scheduler") || issue.source.includes("loop_plan")) return "运行装配";
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
  sharedGraphContract,
  sharedGraphContractError,
  onSharedGraphContractChange,
  onSharedGraphContractErrorChange,
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
  sharedGraphContract?: TaskGraphContractPreview | null;
  sharedGraphContractError?: string;
  onSharedGraphContractChange?: (value: TaskGraphContractPreview | null) => void;
  onSharedGraphContractErrorChange?: (value: string) => void;
}) {
  const {
    bindTaskGraphMonitorRun,
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    setTaskGraphAutoAdvanceEnabled,
    taskGraphAutoAdvanceEnabled,
    taskGraphAutoAdvancePending,
    taskGraphBoundRunMonitor,
    taskGraphMonitorBinding,
    taskGraphMonitorError,
    taskGraphMonitorActionLoading,
    taskGraphMonitorLoading,
  } = useAppStore();
  const [localGraphContract, setLocalGraphContract] = useState<TaskGraphContractPreview | null>(null);
  const [localGraphContractError, setLocalGraphContractError] = useState("");
  const [graphContractLoading, setGraphContractLoading] = useState(false);
  const [taskRunId, setTaskRunId] = useState("");
  const [runTrace, setRunTrace] = useState<HarnessTaskRunTrace | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runStartLoading, setRunStartLoading] = useState(false);
  const [runSessionId, setRunSessionId] = useState("session:task_graph_studio");
  const [graphRunId, setGraphRunId] = useState("");
  const [graphHarnessConfigId, setGraphHarnessConfigId] = useState("");
  const [resumeLoading, setResumeLoading] = useState(false);
  const published = isTaskGraphPublishedState(publishState);
  const graphContract = sharedGraphContract ?? localGraphContract;
  const graphContractError = sharedGraphContractError ?? localGraphContractError;
  const latestRunStatus = String(runTrace?.task_run?.status ?? "").trim();
  const runStatusLabel = latestRunStatus || (publishState === "run_bound" ? "bound" : published ? "ready" : "draft");
  const loopSummary = buildTaskGraphLoopSummary(taskGraphBoundRunMonitor?.graph_loop_state);
  const taskGraphRuns = taskGraphRunsFromTrace(runTrace);
  const schedulerSummary = buildTaskGraphSchedulerSummary(schedulerStateFromTrace(runTrace));
  const batchLifecycleSummary = buildTaskGraphBatchLifecycleSummary(batchLifecycleFromTrace(runTrace));
  const boundBatchLifecycleSummary = buildTaskGraphBatchLifecycleSummary(taskGraphBoundRunMonitor?.graph_loop_state?.batch_lifecycle);
  const loopPlan = buildTaskGraphLoopPlanStandardModel(standardView ?? null);
  const stopLoading = false;
  const preflightReport = buildTaskGraphPreflightReport({
    dirty,
    editorIssueCount,
    editorValid,
    metadata,
    nodes,
    edges,
    graphContract,
    standardView,
  });
  const preflightGroups = Array.from(
    preflightReport.issues.reduce((groups, issue) => {
      const group = preflightIssueGroup(issue);
      groups.set(group, [...(groups.get(group) ?? []), issue]);
      return groups;
    }, new Map<string, TaskGraphPreflightIssue[]>()),
  );
  async function stopLatestRun() {
    setRunTraceError("停止运行入口暂未接入新 GraphRun 链路。");
  }
  async function compileGraphContract() {
    if (!graphId) return;
    if (dirty || standardViewStale) {
      const message = "当前草稿或标准视图已过期，请先保存并刷新标准视图后再编译图契约。";
      setLocalGraphContract(null);
      setLocalGraphContractError(message);
      onSharedGraphContractChange?.(null);
      onSharedGraphContractErrorChange?.(message);
      return;
    }
    setGraphContractLoading(true);
    setLocalGraphContractError("");
    onSharedGraphContractErrorChange?.("");
    try {
      const nextContract = await compileTaskSystemTaskGraphContract(graphId);
      setLocalGraphContract(nextContract);
      onSharedGraphContractChange?.(nextContract);
    } catch (error) {
      const message = error instanceof Error ? error.message : "图契约编译失败";
      setLocalGraphContract(null);
      setLocalGraphContractError(message);
      onSharedGraphContractChange?.(null);
      onSharedGraphContractErrorChange?.(message);
    } finally {
      setGraphContractLoading(false);
    }
  }

  async function loadRunTrace() {
    if (!taskRunId.trim()) return;
    setRunTraceLoading(true);
    setRunTraceError("");
    try {
      const trace = await getOrchestrationHarnessTrace(taskRunId.trim(), { includePayloads: false, includeModelMessages: false, eventLimit: 160 });
      const latestGraphRun = taskGraphRunsFromTrace(trace)[0] ?? {};
      const nextGraphRunId = String(latestGraphRun.graph_run_id ?? "").trim();
      const nextConfigId = String(latestGraphRun.config_id ?? latestGraphRun.graph_harness_config_id ?? "").trim();
      if (nextGraphRunId) {
        setGraphRunId(nextGraphRunId);
      }
      if (nextConfigId) {
        setGraphHarnessConfigId(nextConfigId);
      }
      setRunTrace(trace);
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
        dispatch_ready: true,
        run_mode: "auto_run",
      });
      setTaskRunId(result.task_run_id);
      setGraphRunId(result.graph_run_id);
      setGraphHarnessConfigId(result.graph_harness_config_id);
      setRunTrace(result.trace);
      bindTaskGraphMonitorRun({
        task_run_id: result.task_run_id,
        graph_run_id: result.graph_run_id,
        graph_harness_config_id: result.graph_harness_config_id,
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
    const targetGraphRunId = String(taskGraphMonitorBinding?.graph_run_id || graphRunId).trim();
    const targetConfigId = String(taskGraphMonitorBinding?.graph_harness_config_id || graphHarnessConfigId).trim();
    if (!targetGraphRunId) {
      setRunTraceError("当前没有可派发的 GraphRun。");
      return;
    }
    if (!targetConfigId) {
      setRunTraceError("当前运行缺少 graph_harness_config_id，无法派发 ready 节点。");
      return;
    }
    setResumeLoading(true);
    setRunTraceError("");
    try {
      await runGraphRunUntilIdle(targetGraphRunId, {
        graph_harness_config_id: targetConfigId,
        max_dispatch_requests: 1,
      });
      await loadRunTrace();
    } catch (error) {
      setRunTraceError(error instanceof Error ? error.message : "续跑失败");
    } finally {
      setResumeLoading(false);
    }
  }

  function bindManualTaskRun() {
    const latestGraphRun = taskGraphRuns[0] ?? {};
    const targetGraphRunId = String(graphRunId || latestGraphRun.graph_run_id || "").trim();
    const targetConfigId = String(graphHarnessConfigId || latestGraphRun.config_id || latestGraphRun.graph_harness_config_id || "").trim();
    if (!targetGraphRunId || !targetConfigId) {
      setRunTraceError("请先读取包含 GraphRun 的 TaskRun trace，或创建一个新的图运行。");
      return;
    }
    setRunTraceError("");
    bindTaskGraphMonitorRun({
      task_run_id: taskRunId.trim() || undefined,
      graph_run_id: targetGraphRunId,
      graph_harness_config_id: targetConfigId,
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
            <TaskSystemToolbarButton disabled={!graphId || dirty || standardViewStale || graphContractLoading} onClick={() => void compileGraphContract()}>
              <RefreshCw size={15} />编译图契约
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

      <TaskGraphContractPreviewPanel preview={graphContract} previewError={graphContractError} />

      <section className="boundary-card">
        <header><strong>拓扑编译计划</strong><span>Topology / LoopPlan</span></header>
        {loopPlan.available ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>可执行节点</span><strong>{loopPlan.summary.executableNodeCount}</strong></p>
              <p><span>调度依赖边</span><strong>{loopPlan.summary.dependencyEdgeCount}</strong></p>
              <p><span>上下文边</span><strong>{loopPlan.summary.contextEdgeCount}</strong></p>
              <p><span>提交边</span><strong>{loopPlan.summary.commitEdgeCount}</strong></p>
              <p><span>返修边</span><strong>{loopPlan.summary.revisionEdgeCount}</strong></p>
              <p><span>循环 Frame</span><strong>{loopPlan.summary.loopFrameCount}</strong></p>
            </div>
            <div className="task-graph-note">
              <strong>Ready 起点：{loopPlan.initialReadyNodeIds.join(" / ") || "-"}</strong>
              <span>Start {loopPlan.startNodeIds.join(" / ") || "-"} · Terminal {loopPlan.terminalNodeIds.join(" / ") || "-"}</span>
            </div>
            {loopPlan.loopFrames.length ? (
              <div className="task-graph-preflight-list">
                {loopPlan.loopFrames.slice(0, 4).map((frame) => (
                  <article className="task-graph-preflight-row" key={frame.frame_id || frame.scope_id || `${frame.entry_node_id}_${frame.exit_node_id}`}>
                    <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">
                      loop
                    </span>
                    <div>
                      <strong>{frame.frame_id || frame.scope_id || "loop.frame"}</strong>
                      <span>{frame.entry_node_id || "-"} {"->"} {frame.router_node_id || "-"} {"->"} {frame.exit_node_id || "-"}</span>
                    </div>
                    <em>continue {frame.continue_node_id || "-"}</em>
                    <small>{frame.kind || "loop_frame"}</small>
                  </article>
                ))}
              </div>
            ) : (
              <div className="task-graph-note">
                <strong>没有显式循环 frame</strong>
                <span>当前拓扑会按调度依赖推进；返修边只作为条件返修协议，不等同于普通依赖环。</span>
              </div>
            )}
            <div className="task-graph-preflight-list">
              {loopPlan.previewEdges.map((edge) => (
                <article className="task-graph-preflight-row" key={`${edge.runtime_role}_${edge.edge_id}`}>
                  <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">
                    {edge.runtime_role || edge.scheduler_role || "edge"}
                  </span>
                  <div>
                    <strong>{edge.edge_id}</strong>
                    <span>{edge.source_node_id} {"->"} {edge.target_node_id}</span>
                  </div>
                  <em>{edge.edge_type}</em>
                  <small>{edge.scheduler_role || edge.semantic_role || "-"}</small>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <div className="task-graph-note task-graph-note--danger">
            <strong>LoopPlan 暂不可用</strong>
            <span>{loopPlan.issues[0]?.message ? String(loopPlan.issues[0].message) : "请先保存并刷新标准视图，确认后端 GraphHarnessConfig 能够编译。"}</span>
          </div>
        )}
        <div className="boundary-actions">
          <span className="boundary-chip"><GitBranch size={14} /> 后端编译预览</span>
        </div>
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
              <p><span>GraphRun</span><strong>{taskGraphRuns.length}</strong></p>
              <p><span>事件</span><strong>{runTrace.event_count}</strong></p>
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
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void continueBoundTaskGraphRun()}>
            <PlayCircle size={15} />手动续跑一次
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton
            disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading}
            onClick={() => setTaskGraphAutoAdvanceEnabled(!taskGraphAutoAdvanceEnabled)}
            variant={taskGraphAutoAdvanceEnabled ? "primary" : undefined}
          >
            {taskGraphAutoAdvanceEnabled ? <PauseCircle size={15} /> : <PlayCircle size={15} />}
            {taskGraphAutoAdvanceEnabled ? "自动推进中" : "切到自动推进"}
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
        <div className={taskGraphAutoAdvanceEnabled ? "task-graph-auto-advance task-graph-auto-advance--enabled" : "task-graph-auto-advance"}>
          <strong>{taskGraphAutoAdvanceEnabled ? "自动推进已开启" : "手动推进模式"}</strong>
          <span>
            {taskGraphAutoAdvancePending
              ? "监控已观察到可派发节点，延时保护后会自动续跑一次。"
              : taskGraphAutoAdvanceEnabled
                ? "监控只在 ready 节点存在且没有活动 WorkOrder 时触发续跑。"
                : "当前不会自动派发 ready 节点，需要点击续跑当前阶段。"}
          </span>
        </div>
        {taskGraphBoundRunMonitor ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>GraphRun</span><strong>{taskGraphBoundRunMonitor.graph_run_id || "-"}</strong></p>
              <p><span>状态</span><strong>{loopSummary.status || "unknown"}</strong></p>
              <p><span>Ready</span><strong>{loopSummary.ready_node_ids.length}</strong></p>
              <p><span>Active</span><strong>{loopSummary.active_node_ids.length}</strong></p>
              <p><span>Completed</span><strong>{loopSummary.completed_node_ids.length}</strong></p>
              <p><span>Failed</span><strong>{loopSummary.failed_node_ids.length}</strong></p>
              <p><span>事件</span><strong>{taskGraphBoundRunMonitor.event_count ?? loopSummary.event_count}</strong></p>
              <p><span>WorkOrder</span><strong>{taskGraphBoundRunMonitor.active_node_work_order_count ?? loopSummary.active_node_work_order_count}</strong></p>
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
          </div>
        ) : null}
        <div className={taskGraphMonitorError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
          <strong>{taskGraphMonitorError ? "监控刷新失败" : "GraphRun 监控已接入基础快照"}</strong>
          <span>{taskGraphMonitorError || "当前页面先展示新 GraphRun 的 loop state 与 active work orders；完整监督决策面板后续重做。"}</span>
        </div>
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
            <span>当前图可以保存并发布。发布前可以编译图契约，确认 GraphRuntime 与 GraphLoop 可识别。</span>
          </div>
        )}
      </section>
    </section>
  );
}
