"use client";

import { Activity, MessageSquareShare, PauseCircle, PlayCircle, RefreshCw, StopCircle } from "lucide-react";

import { useAppStore } from "@/lib/store";

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function textValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function firstMetricValue(...values: unknown[]) {
  for (const value of values) {
    if (Array.isArray(value)) return value.length;
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return 0;
}

function graphRunStatusLabel(status: string) {
  const normalized = status.toLowerCase();
  if (["running", "dispatching", "in_progress"].includes(normalized)) return "运行中";
  if (["paused", "suspended"].includes(normalized)) return "已暂停";
  if (["blocked", "waiting", "waiting_executor"].includes(normalized)) return "等待处理";
  if (["failed", "error"].includes(normalized)) return "失败";
  if (["completed", "done", "success"].includes(normalized)) return "已完成";
  if (["stopped", "cancelled", "canceled"].includes(normalized)) return "已停止";
  if (normalized === "bound") return "已绑定";
  return status || "未绑定";
}

function graphMonitorStatus(monitor: unknown, hasBinding: boolean) {
  const record = recordValue(monitor);
  const loopState = recordValue(record.graph_loop_state);
  const taskRun = recordValue(record.task_run);
  return textValue(loopState.status ?? record.status ?? record.graph_run_status ?? taskRun.status, hasBinding ? "bound" : "");
}

function graphMonitorMetrics(monitor: unknown) {
  const record = recordValue(monitor);
  const loopState = recordValue(record.graph_loop_state);
  const lifecycleCounts = recordValue(loopState.node_lifecycle_counts ?? loopState.lifecycle_counts ?? record.node_lifecycle_counts ?? record.node_counts);
  return {
    ready: firstMetricValue(record.ready_node_ids, lifecycleCounts.ready, record.ready_node_count),
    running: firstMetricValue(record.running_node_ids, lifecycleCounts.running, record.running_node_count),
    completed: firstMetricValue(record.completed_node_ids, lifecycleCounts.completed, lifecycleCounts.done, record.completed_node_count),
    failed: firstMetricValue(record.failed_node_ids, lifecycleCounts.failed, record.failed_node_count),
    blocked: firstMetricValue(record.blocked_node_ids, lifecycleCounts.blocked, record.blocked_node_count),
    workOrders: firstMetricValue(record.active_node_work_orders, record.active_work_orders, record.active_node_work_order_count),
  };
}

function classNames(...items: Array<string | false | undefined>) {
  return items.filter(Boolean).join(" ");
}

export function TaskGraphRunControlPanel({
  className,
  graphId = "",
  showDockButton = true,
  taskEnvironmentId = "",
  title = "图运行监控",
}: {
  className?: string;
  graphId?: string;
  showDockButton?: boolean;
  taskEnvironmentId?: string;
  title?: string;
}) {
  const {
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    pauseBoundTaskGraphRun,
    setTaskGraphRunInteractionOpen,
    stopBoundTaskGraphRun,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
  } = useAppStore();
  const targetGraphId = graphId.trim();
  const targetEnvironmentId = taskEnvironmentId.trim();
  const bindingGraphId = String(taskGraphMonitorBinding?.graph_id || "").trim();
  const bindingEnvironmentId = String(taskGraphMonitorBinding?.session_scope?.task_environment_id || "").trim();
  const graphMatches = !targetGraphId || !bindingGraphId || bindingGraphId === targetGraphId;
  const environmentMatches = !targetEnvironmentId || !bindingEnvironmentId || bindingEnvironmentId === targetEnvironmentId;
  const visibleBinding = taskGraphMonitorBinding && graphMatches && environmentMatches ? taskGraphMonitorBinding : null;
  const visibleMonitor = visibleBinding ? taskGraphBoundRunMonitor : null;
  const hasBinding = Boolean(visibleBinding);
  const status = graphRunStatusLabel(graphMonitorStatus(visibleMonitor, hasBinding));
  const metrics = graphMonitorMetrics(visibleMonitor);
  const monitorTitle = visibleBinding?.title || visibleBinding?.graph_id || (targetGraphId ? "当前图未绑定运行" : "尚未绑定图运行");
  const monitorRunId = visibleBinding?.graph_run_id || visibleBinding?.task_run_id || "";

  return (
    <section
      className={classNames("task-graph-run-control-panel", taskGraphMonitorError && hasBinding ? "task-graph-run-control-panel--error" : false, className)}
      aria-label={title}
    >
      <header className="task-graph-run-control-panel__head">
        <div>
          <Activity size={15} />
          <span>{title}</span>
        </div>
        <em>{status}</em>
      </header>
      <div className="task-graph-run-control-panel__target">
        <strong>{monitorTitle}</strong>
        <small>{monitorRunId || (targetGraphId ? targetGraphId : "绑定运行后显示 GraphRun")}</small>
      </div>
      <div className="task-graph-run-control-panel__metrics" aria-label="运行节点统计">
        <span>Ready <strong>{metrics.ready}</strong></span>
        <span>Running <strong>{metrics.running}</strong></span>
        <span>Done <strong>{metrics.completed}</strong></span>
        <span>Failed <strong>{metrics.failed}</strong></span>
        <span>Blocked <strong>{metrics.blocked}</strong></span>
        <span>WO <strong>{metrics.workOrders}</strong></span>
      </div>
      <div className="task-graph-run-control-panel__actions">
        <button disabled={!hasBinding || taskGraphMonitorLoading} onClick={() => void evaluateBoundTaskGraphMonitor()} type="button">
          <RefreshCw size={14} />
          <span>{taskGraphMonitorLoading ? "刷新中" : "刷新"}</span>
        </button>
        <button disabled={!hasBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void continueBoundTaskGraphRun()} type="button">
          <PlayCircle size={14} />
          <span>{taskGraphMonitorActionLoading ? "续跑中" : "续跑"}</span>
        </button>
        <button disabled={!hasBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void pauseBoundTaskGraphRun()} type="button">
          <PauseCircle size={14} />
          <span>{taskGraphMonitorActionLoading ? "暂停中" : "暂停"}</span>
        </button>
        <button disabled={!hasBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void stopBoundTaskGraphRun()} type="button">
          <StopCircle size={14} />
          <span>{taskGraphMonitorActionLoading ? "停止中" : "停止"}</span>
        </button>
        {showDockButton ? (
          <button disabled={!hasBinding} onClick={() => setTaskGraphRunInteractionOpen(true)} type="button">
            <MessageSquareShare size={14} />
            <span>浮窗</span>
          </button>
        ) : null}
      </div>
      {taskGraphMonitorError && hasBinding ? <p>{taskGraphMonitorError}</p> : null}
    </section>
  );
}
