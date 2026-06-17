"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, GitBranch, MessageSquareShare, PauseCircle, PlayCircle, RefreshCw, Save, Send, TriangleAlert } from "lucide-react";

import {
  compileTaskSystemTaskGraphContract,
  getSessionHistory,
  getOrchestrationHarnessTrace,
  getPublishedTaskGraphHarnessConfig,
  startTaskGraphHarnessRun,
  submitGraphRunUntilIdle,
  taskGraphRunsFromTrace,
  type HarnessTaskRunTrace,
  type SessionHistory,
  type SessionScope,
  type TaskGraphContractPreview,
  type TaskGraphStandardView,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Notice } from "@/ui/Notice";
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

const GRAPH_TASK_WORKSPACE_VIEW = "graph_task";
const GRAPH_SESSION_ACTIVE_STATUSES = new Set(["running", "active", "waiting", "queued", "dispatching", "in_progress"]);

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

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function textValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function scopeKey(scope?: Partial<SessionScope>) {
  return [
    String(scope?.workspace_view || "").trim(),
    String(scope?.task_environment_id || "").trim(),
    String(scope?.project_id || "").trim(),
  ].join("|");
}

function compactMessageText(value: string, limit = 280) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}...`;
}

function nestedText(record: Record<string, unknown>, path: string[]) {
  let cursor: unknown = record;
  for (const key of path) {
    cursor = recordValue(cursor)[key];
  }
  return textValue(cursor);
}

function graphConfigProjectId(graphConfig: { environment?: Record<string, unknown>; diagnostics?: Record<string, unknown>; source_refs?: Record<string, unknown> } | null | undefined) {
  const diagnostics = recordValue(graphConfig?.diagnostics);
  const environment = recordValue(graphConfig?.environment);
  const sourceRefs = recordValue(graphConfig?.source_refs);
  return textValue(
    nestedText(environment, ["runtime_scope", "project_id"])
    || nestedText(diagnostics, ["runtime_scope", "project_id"])
    || diagnostics.project_id
    || sourceRefs.project_id,
  );
}

function graphConfigRequiresProject(graphConfig: { environment?: Record<string, unknown> } | null | undefined) {
  const environment = recordValue(graphConfig?.environment);
  const fileManagement = recordValue(environment.file_management);
  const storageSpace = recordValue(environment.storage_space);
  const projectPolicy = textValue(
    fileManagement.project_file_policy
    || storageSpace.workspace_policy
    || environment.project_file_policy,
  ).toLowerCase();
  if (projectPolicy && !["none", "disabled", "conversation_only"].includes(projectPolicy)) return true;
  return Array.isArray(fileManagement.required_repository_kinds) && fileManagement.required_repository_kinds.length > 0
    || Array.isArray(storageSpace.required_repository_kinds) && storageSpace.required_repository_kinds.length > 0;
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
    currentSessionId,
    evaluateBoundTaskGraphMonitor,
    pauseBoundTaskGraphRun,
    setTaskGraphRunInteractionOpen,
    setTaskGraphAutoAdvanceEnabled,
    stopBoundTaskGraphRun,
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
  const [runControlNotice, setRunControlNotice] = useState("");
  const [runSessionId, setRunSessionId] = useState("");
  const [graphRunId, setGraphRunId] = useState("");
  const [graphHarnessConfigId, setGraphHarnessConfigId] = useState("");
  const [resumeLoading, setResumeLoading] = useState(false);
  const [graphSessionHistory, setGraphSessionHistory] = useState<SessionHistory | null>(null);
  const [graphSessionLoading, setGraphSessionLoading] = useState(false);
  const [graphSessionError, setGraphSessionError] = useState("");
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
  const graphSessionId = textValue(taskGraphMonitorBinding?.session_id || runSessionId);
  const graphSessionScope: Partial<SessionScope> | undefined = graphSessionId
    ? {
        workspace_view: GRAPH_TASK_WORKSPACE_VIEW,
        task_environment_id: "",
        project_id: textValue(taskGraphMonitorBinding?.session_scope?.project_id || taskGraphMonitorBinding?.project_id),
      }
    : undefined;
  const graphSessionScopeKey = graphSessionId ? scopeKey(graphSessionScope) : "";
  const graphSessionMessages = (graphSessionHistory?.messages ?? []).slice(-8);
  const graphMonitorRecord = recordValue(taskGraphBoundRunMonitor);
  const graphRunActivity = textValue(
    graphMonitorRecord.activity_state
    || graphMonitorRecord.status
    || loopSummary.status
    || latestRunStatus,
  ).toLowerCase();
  const graphSessionAutoRefresh = Boolean(
    graphSessionId
    && (
      graphMonitorRecord.is_running === true
      || taskGraphMonitorLoading
      || taskGraphAutoAdvancePending
      || resumeLoading
      || runStartLoading
      || GRAPH_SESSION_ACTIVE_STATUSES.has(graphRunActivity)
    ),
  );
  const stopLoading = taskGraphMonitorActionLoading;
  const pauseLoading = taskGraphMonitorActionLoading;
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
  const hasControlTarget = Boolean(taskGraphMonitorBinding || graphRunId || taskGraphRuns.length);

  async function loadGraphSessionHistory() {
    if (!graphSessionId) {
      setGraphSessionHistory(null);
      setGraphSessionError("");
      return;
    }
    setGraphSessionLoading(true);
    setGraphSessionError("");
    try {
      setGraphSessionHistory(await getSessionHistory(graphSessionId, graphSessionScope));
    } catch (error) {
      setGraphSessionError(error instanceof Error ? error.message : "图任务会话读取失败");
    } finally {
      setGraphSessionLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    if (!graphSessionId) {
      setGraphSessionHistory(null);
      setGraphSessionError("");
      return;
    }
    setGraphSessionLoading(true);
    setGraphSessionError("");
    void getSessionHistory(graphSessionId, graphSessionScope)
      .then((history) => {
        if (!cancelled) setGraphSessionHistory(history);
      })
      .catch((error) => {
        if (!cancelled) setGraphSessionError(error instanceof Error ? error.message : "图任务会话读取失败");
      })
      .finally(() => {
        if (!cancelled) setGraphSessionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphSessionId, graphSessionScopeKey]);

  useEffect(() => {
    if (!graphSessionId || !graphSessionAutoRefresh) return undefined;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getSessionHistory(graphSessionId, graphSessionScope)
        .then((history) => {
          if (!cancelled) {
            setGraphSessionHistory(history);
            setGraphSessionError("");
          }
        })
        .catch((error) => {
          if (!cancelled) setGraphSessionError(error instanceof Error ? error.message : "图任务会话读取失败");
        });
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphSessionId, graphSessionScopeKey, graphSessionAutoRefresh]);
  function bindCurrentRunForControl() {
    const latestGraphRun = taskGraphRuns[0] ?? {};
    const targetTaskRunId = textValue(taskGraphMonitorBinding?.task_run_id || taskRunId);
    const targetGraphRunId = textValue(taskGraphMonitorBinding?.graph_run_id || graphRunId || latestGraphRun.graph_run_id);
    const targetConfigId = textValue(
      taskGraphMonitorBinding?.graph_harness_config_id
      || graphHarnessConfigId
      || latestGraphRun.config_id
      || latestGraphRun.graph_harness_config_id,
    );
    const targetSessionScope = {
      workspace_view: textValue(
        taskGraphMonitorBinding?.session_scope?.workspace_view
        || latestGraphRun.workspace_view
        || GRAPH_TASK_WORKSPACE_VIEW,
      ),
      task_environment_id: "",
      project_id: textValue(
        taskGraphMonitorBinding?.session_scope?.project_id
        || latestGraphRun.project_id,
      ),
    };
    if (!targetGraphRunId || !targetConfigId) {
      setRunTraceError("当前页面没有可控制的 GraphRun，请先创建运行、读取 Trace 或绑定监控。");
      return false;
    }
    setRunTraceError("");
    bindTaskGraphMonitorRun({
      task_run_id: targetTaskRunId || undefined,
      graph_run_id: targetGraphRunId,
      graph_harness_config_id: targetConfigId,
      graph_id: graphId,
      session_id: textValue(taskGraphMonitorBinding?.session_id || latestGraphRun.session_id || runSessionId) || undefined,
      project_id: targetSessionScope.project_id || undefined,
      session_scope: targetSessionScope,
      title: graphId,
    });
    return true;
  }

  async function pauseLatestRun() {
    if (!bindCurrentRunForControl()) return;
    setRunControlNotice("正在向 root TaskRun 发送暂停请求。");
    await pauseBoundTaskGraphRun();
    setRunControlNotice("暂停请求已发送，等待当前步骤到达运行边界。");
    if (taskRunId.trim()) {
      await loadRunTrace();
    }
  }

  async function stopLatestRun() {
    if (!bindCurrentRunForControl()) return;
    setRunControlNotice("正在向 root TaskRun 发送停止请求。");
    await stopBoundTaskGraphRun();
    setRunControlNotice("停止请求已发送，等待当前步骤到达运行边界。");
    if (taskRunId.trim()) {
      await loadRunTrace();
    }
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
      setRunControlNotice("运行追踪已刷新。");
    } catch (error) {
      setRunTrace(null);
      const message = error instanceof Error ? error.message : "运行追踪读取失败";
      setRunTraceError(message);
      setRunControlNotice(message);
    } finally {
      setRunTraceLoading(false);
    }
  }

  async function startRun() {
    if (!graphId) return;
    setRunStartLoading(true);
    setRunTraceError("");
    setRunControlNotice("正在读取已发布图配置。");
    try {
      const graphConfig = await getPublishedTaskGraphHarnessConfig(graphId);
      setRunControlNotice("正在解析图任务项目作用域。");
      const projectId = textValue(
        taskGraphMonitorBinding?.session_scope?.project_id
        || taskGraphMonitorBinding?.project_id
        || metadata?.project_id
        || nestedText(recordValue(metadata), ["runtime_scope", "project_id"])
        || graphConfigProjectId(graphConfig)
      );
      if (graphConfigRequiresProject(graphConfig) && !projectId) {
        throw new Error("当前图配置要求项目作用域，但前端没有解析到 project_id。");
      }
      const launchSessionId = textValue(currentSessionId);
      if (!launchSessionId) {
        throw new Error("启动图任务需要一个当前会话作为发起来源，但图任务实例会由后端单独创建。");
      }
      const sessionScope = {
        workspace_view: GRAPH_TASK_WORKSPACE_VIEW,
        task_environment_id: "",
        project_id: projectId,
      };
      setRunControlNotice("正在创建新的图运行并派发起点。");
      const result = await startTaskGraphHarnessRun(graphId, {
        session_id: launchSessionId,
        session_scope: sessionScope,
        initial_inputs: {
          runtime_scope: sessionScope,
        },
        include_trace: true,
        dispatch_ready: true,
        run_mode: "dispatch_only",
      });
      const sessionId = textValue(result.graph_session_id || result.graph_run?.session_id);
      if (!sessionId) {
        throw new Error("后端没有返回图任务实例会话。");
      }
      setRunSessionId(sessionId);
      setTaskRunId(result.task_run_id);
      setGraphRunId(result.graph_run_id);
      setGraphHarnessConfigId(result.graph_harness_config_id);
      setRunTrace(result.trace);
      bindTaskGraphMonitorRun({
        task_run_id: result.task_run_id,
        graph_run_id: result.graph_run_id,
        graph_harness_config_id: result.graph_harness_config_id,
        graph_id: graphId,
        session_id: sessionId,
        project_id: projectId || undefined,
        session_scope: sessionScope,
        title: graphId,
      });
      setRunControlNotice("新图运行已创建并绑定监控，可以手动续跑。");
      onRunBound?.();
    } catch (error) {
      setRunTrace(null);
      const message = error instanceof Error ? error.message : "运行创建失败";
      setRunTraceError(message);
      setRunControlNotice(message);
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
    setRunControlNotice("正在派发当前 GraphRun 的 ready 节点。");
    try {
      await submitGraphRunUntilIdle(targetGraphRunId, {
        graph_harness_config_id: targetConfigId,
        session_scope: taskGraphMonitorBinding?.session_scope,
        max_node_executions: 1,
        max_loop_iterations: 4,
        max_dispatches: 1,
        max_dispatch_requests: 1,
      });
      await loadRunTrace();
      setRunControlNotice("续跑请求已完成，运行追踪已刷新。");
    } catch (error) {
      const message = error instanceof Error ? error.message : "续跑失败";
      setRunTraceError(message);
      setRunControlNotice(message);
    } finally {
      setResumeLoading(false);
    }
  }

  function bindManualTaskRun() {
    const latestGraphRun = taskGraphRuns[0] ?? {};
    const targetGraphRunId = String(graphRunId || latestGraphRun.graph_run_id || "").trim();
    const targetConfigId = String(graphHarnessConfigId || latestGraphRun.config_id || latestGraphRun.graph_harness_config_id || "").trim();
    const targetSessionScope = {
      workspace_view: String(latestGraphRun.workspace_view || GRAPH_TASK_WORKSPACE_VIEW),
      task_environment_id: "",
      project_id: String(latestGraphRun.project_id || ""),
    };
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
      session_id: String(latestGraphRun.session_id || runSessionId || "").trim() || undefined,
      session_scope: targetSessionScope,
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

      <article className="boundary-card">
        <header>
          <strong>图任务会话</strong>
          <button disabled={!graphSessionId || graphSessionLoading} onClick={() => void loadGraphSessionHistory()} type="button">
            <RefreshCw size={14} />{graphSessionLoading ? "刷新中" : "刷新"}
          </button>
        </header>
        <div className="task-graph-runtime-summary">
          <span>Session <strong>{graphSessionId || "尚未创建"}</strong></span>
          <span>Scope <strong>{graphSessionScopeKey || "graph_task"}</strong></span>
        </div>
        {graphSessionError ? <Notice tone="error">{graphSessionError}</Notice> : null}
        {graphSessionMessages.length ? (
          <div className="task-graph-session-transcript" aria-label="图任务会话消息">
            {graphSessionMessages.map((message, index) => {
              const messageId = String(message.message_id || message.id || `${message.role}-${index}`);
              return (
                <div className="task-graph-session-transcript__item" key={messageId}>
                  <span>{message.role === "assistant" ? "Agent" : "User"}</span>
                  <p>{compactMessageText(message.content)}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <p>{graphSessionId ? "当前图任务会话还没有可展示的消息，节点运行进展可在监控区查看。" : "启动新的图运行后显示 graph session 的最近消息。"}</p>
        )}
      </article>

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
              <PlayCircle size={15} />{runStartLoading ? "正在启动" : "启动图运行"}
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!hasControlTarget || pauseLoading} onClick={() => void pauseLatestRun()}>
              <PauseCircle size={15} />{pauseLoading ? "暂停中" : "暂停"}
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!hasControlTarget || stopLoading} onClick={() => void stopLatestRun()}>
              <TriangleAlert size={15} />{stopLoading ? "停止中" : "停止"}
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!hasControlTarget || resumeLoading} onClick={() => void resumeLatestTaskGraphRun()}>
              <RefreshCw size={15} />{resumeLoading ? "续跑中" : "续跑一次"}
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskRunId || taskGraphMonitorLoading} onClick={bindManualTaskRun}>
              <MessageSquareShare size={15} />绑定监控
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading} onClick={() => void evaluateBoundTaskGraphMonitor()}>
              <TriangleAlert size={15} />监测评估
            </TaskSystemToolbarButton>
          </div>
          {runControlNotice ? (
            <div className={runTraceError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
              <strong>运行控制</strong>
              <span>{runControlNotice}</span>
            </div>
          ) : null}
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
            <strong>{standardViewStale ? "请先保存并刷新标准视图" : published ? (publishState === "run_bound" ? "当前图已绑定运行" : "可启动真实运行") : "发布后才能启动运行"}</strong>
            <span>启动会创建新的 TaskRun、TaskGraphRun、checkpoint、trace 和独立 graph_task 会话；已有运行可以通过 TaskRun ID 绑定监控。</span>
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
            <span>TaskRun ID</span>
            <input value={taskRunId} onChange={(event) => setTaskRunId(event.target.value)} placeholder="task_run_xxx" />
          </label>
        </div>
        <div className="boundary-actions">
          <TaskSystemToolbarButton disabled={!taskRunId.trim() || runTraceLoading} onClick={() => void loadRunTrace()}>
            <RefreshCw size={15} />读取 Trace
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!graphId || !published || !preflightReport.valid || runStartLoading} onClick={() => void startRun()}>
            <PlayCircle size={15} />{runStartLoading ? "正在启动" : "启动图运行"}
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!runTrace || resumeLoading} onClick={() => void resumeLatestTaskGraphRun()}>
            <PlayCircle size={15} />{resumeLoading ? "续跑中" : "续跑最近运行"}
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!hasControlTarget || pauseLoading} onClick={() => void pauseLatestRun()}>
            <PauseCircle size={15} />{pauseLoading ? "暂停中" : "暂停 root task"}
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!hasControlTarget || stopLoading} onClick={() => void stopLatestRun()}>
            <TriangleAlert size={15} />{stopLoading ? "停止中" : "停止 root task"}
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
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void pauseBoundTaskGraphRun()}>
            <PauseCircle size={15} />{taskGraphMonitorActionLoading ? "暂停中" : "暂停"}
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void continueBoundTaskGraphRun()}>
            <PlayCircle size={15} />{taskGraphMonitorActionLoading ? "续跑中" : "续跑一次"}
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void stopBoundTaskGraphRun()}>
            <TriangleAlert size={15} />{taskGraphMonitorActionLoading ? "停止中" : "停止"}
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
            <span>创建运行或输入 TaskRun ID 后点击绑定，浮窗会按 TaskRun 独立显示监控，不再跟随聊天会话。</span>
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
