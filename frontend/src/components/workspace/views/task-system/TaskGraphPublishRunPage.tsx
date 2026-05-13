"use client";

import { useState } from "react";
import { CheckCircle2, MessageSquareShare, PlayCircle, RefreshCw, Save, Send, TriangleAlert } from "lucide-react";

import {
  compileTaskSystemTaskGraphRuntimeSpec,
  getOrchestrationRuntimeLoopTrace,
  resumeOrchestrationCoordinationRun,
  startTaskGraphRuntimeLoopRun,
  type CoordinationGraphSpec,
  type RuntimeLoopTaskRunTrace,
} from "@/lib/api";
import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join(" / ") : "";
}

function runtimeIssueTitle(issue: Record<string, unknown>, index: number) {
  return String(issue.code ?? issue.message ?? `issue_${index + 1}`);
}

function repairActionLabel(issue: TaskGraphPreflightIssue) {
  if (issue.source === "frontend.preflight.prompt_semantics") return "生成职责 Prompt";
  if (issue.source === "frontend.preflight.contract" && issue.scope === "edge") return "补默认载荷契约";
  if (issue.source === "frontend.preflight.memory_handoff") return "补摘要交接";
  if (issue.source === "frontend.preflight.timeline" && issue.scope === "phase") return "补阶段定义";
  return "";
}

export function TaskGraphPublishRunPage({
  dirty,
  edges,
  editorIssueCount,
  editorValid,
  graphId,
  metadata,
  nodes,
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
  onPublish: () => void;
  onSave: () => void;
  onSendToChat: () => void;
  onFocusIssue?: (issue: TaskGraphPreflightIssue) => void;
  onRunBound?: () => void;
  onRepairIssue?: (issue: TaskGraphPreflightIssue) => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
}) {
  const [runtimeSpec, setRuntimeSpec] = useState<CoordinationGraphSpec | null>(null);
  const [runtimeSpecError, setRuntimeSpecError] = useState("");
  const [runtimeSpecLoading, setRuntimeSpecLoading] = useState(false);
  const [taskRunId, setTaskRunId] = useState("");
  const [runTrace, setRunTrace] = useState<RuntimeLoopTaskRunTrace | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runStartLoading, setRunStartLoading] = useState(false);
  const [runSessionId, setRunSessionId] = useState("session:task_graph_studio");
  const [resumeLoading, setResumeLoading] = useState(false);
  const published = isTaskGraphPublishedState(publishState);
  const latestRunStatus = String(runTrace?.task_run?.status ?? "").trim();
  const runStatusLabel = latestRunStatus || (publishState === "run_bound" ? "bound" : published ? "ready" : "draft");
  const preflightReport = buildTaskGraphPreflightReport({
    dirty,
    editorIssueCount,
    editorValid,
    metadata,
    nodes,
    edges,
    runtimeSpec,
  });

  async function compileRuntimeSpec() {
    if (!graphId) return;
    setRuntimeSpecLoading(true);
    setRuntimeSpecError("");
    try {
      setRuntimeSpec(await compileTaskSystemTaskGraphRuntimeSpec(graphId));
    } catch (error) {
      setRuntimeSpec(null);
      setRuntimeSpecError(error instanceof Error ? error.message : "运行规范编译失败");
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
      setRunTrace(result.trace);
      onRunBound?.();
    } catch (error) {
      setRunTrace(null);
      setRunTraceError(error instanceof Error ? error.message : "运行创建失败");
    } finally {
      setRunStartLoading(false);
    }
  }

  async function resumeLatestCoordinationRun() {
    const coordinationRunId = String(runTrace?.coordination_runs?.[0]?.coordination_run_id ?? runTrace?.coordination_runs?.[0]?.run_id ?? "");
    if (!coordinationRunId) {
      setRunTraceError("当前 trace 没有可续跑的 coordination run。");
      return;
    }
    setResumeLoading(true);
    setRunTraceError("");
    try {
      await resumeOrchestrationCoordinationRun(coordinationRunId, { source: "task_graph_studio", task_graph_id: graphId });
      await loadRunTrace();
    } catch (error) {
      setRunTraceError(error instanceof Error ? error.message : "续跑失败");
    } finally {
      setResumeLoading(false);
    }
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
            <TaskSystemToolbarButton disabled={saving === "coordination"} onClick={onSave}>
              <Save size={15} />保存草稿
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!preflightReport.valid || saving === "coordination"} onClick={onPublish} variant="primary">
              <Send size={15} />发布可运行
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={onSendToChat}>
              <MessageSquareShare size={15} />带入会话
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!graphId || runtimeSpecLoading} onClick={() => void compileRuntimeSpec()}>
              <RefreshCw size={15} />编译运行规范
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton
              disabled={!graphId || !published || !preflightReport.valid || runStartLoading}
              onClick={() => void startRun()}
              variant="primary"
            >
              <PlayCircle size={15} />创建运行
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
            <span>创建运行会调用后端 TaskGraph 运行入口，生成真实 TaskRun、CoordinationRun、checkpoint 和 trace。</span>
          </div>
        </article>
      </section>

      <section className="boundary-card">
        <header><strong>运行规范</strong></header>
        {runtimeSpec ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>来源</span><strong>{String(runtimeSpec.diagnostics?.source ?? "runtime_spec")}</strong></p>
              <p><span>节点</span><strong>{runtimeSpec.nodes.length}</strong></p>
              <p><span>有效</span><strong>{runtimeSpec.valid ? "通过" : "待修复"}</strong></p>
              <p><span>起点</span><strong>{listText(runtimeSpec.start_node_ids) || "-"}</strong></p>
              <p><span>终点</span><strong>{listText(runtimeSpec.terminal_node_ids) || "-"}</strong></p>
              <p><span>通信</span><strong>{listText(runtimeSpec.communication_modes) || "-"}</strong></p>
            </div>
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
              <summary>Diagnostics</summary>
              <pre>{JSON.stringify(runtimeSpec.diagnostics ?? {}, null, 2)}</pre>
            </details>
          </div>
        ) : (
          <div className={runtimeSpecError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
            <strong>{runtimeSpecError ? "运行规范不可用" : "尚未编译运行规范"}</strong>
            <span>{runtimeSpecError || "点击“编译运行规范”后，平台会从 TaskGraphDefinition 直接生成 runtime spec。"}</span>
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
          <TaskSystemToolbarButton disabled={!runTrace || resumeLoading} onClick={() => void resumeLatestCoordinationRun()}>
            <PlayCircle size={15} />续跑最近协调运行
          </TaskSystemToolbarButton>
        </div>
        {runTrace ? (
          <div className="task-graph-runtime-spec-panel">
            <div className="task-graph-mini-kv">
              <p><span>TaskRun</span><strong>{String(runTrace.task_run?.task_run_id ?? runTrace.task_run?.run_id ?? taskRunId)}</strong></p>
              <p><span>状态</span><strong>{String(runTrace.task_run?.status ?? "unknown")}</strong></p>
              <p><span>Coordination</span><strong>{runTrace.coordination_runs.length}</strong></p>
              <p><span>事件</span><strong>{runTrace.event_count}</strong></p>
              <p><span>Checkpoint</span><strong>{runTrace.latest_checkpoint ? "存在" : "无"}</strong></p>
            </div>
            <details className="task-graph-runtime-spec-details">
              <summary>Trace JSON</summary>
              <pre>{JSON.stringify({
                task_run: runTrace.task_run,
                latest_checkpoint: runTrace.latest_checkpoint,
                coordination_runs: runTrace.coordination_runs,
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
        <header><strong>预检问题</strong><span>{preflightReport.error_count} 阻塞 / {preflightReport.warning_count} 警告 / {preflightReport.info_count} 提示</span></header>
        {preflightReport.issues.length ? (
          <div className="task-graph-preflight-list">
            {preflightReport.issues.map((issue) => {
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
                    </div>
                    <em>{issue.scope}{issue.target_id ? `:${issue.target_id}` : ""}</em>
                    <small>{issue.source}</small>
                  </button>
                  {repairLabel ? <button className="boundary-chip" onClick={() => onRepairIssue?.(issue)} type="button"><span>{repairLabel}</span></button> : null}
                </article>
              );
            })}
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
