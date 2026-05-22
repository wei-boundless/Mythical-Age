"use client";

import { Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock3, Minimize2, Network, PauseCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { TaskGraphRunMonitorPanel } from "@/components/task-graph-monitor/TaskGraphRunMonitorPanel";
import type { GlobalRuntimeMonitorItem } from "@/lib/api";
import { useAppStore } from "@/lib/store";

const ACTIVE_STATUSES = new Set(["created", "running", "waiting_approval", "blocked"]);
const WAITING_STATUSES = new Set(["waiting_approval", "blocked"]);

function statusLabel(status: string) {
  if (status === "running" || status === "created") return "进行中";
  if (status === "waiting_approval") return "等待审批";
  if (status === "blocked") return "受阻";
  if (status === "completed" || status === "success") return "已完成";
  if (status === "failed") return "失败";
  if (status === "aborted") return "已停止";
  return status || "未知";
}

function statusIcon(status: string) {
  if (WAITING_STATUSES.has(status)) return <PauseCircle size={14} />;
  if (status === "completed" || status === "success") return <CheckCircle2 size={14} />;
  if (status === "failed" || status === "aborted") return <AlertTriangle size={14} />;
  return <Activity size={14} />;
}

function formatDuration(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function formatTime(timestamp: number) {
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleTimeString();
}

function taskTitle(item: GlobalRuntimeMonitorItem) {
  return item.project_title || item.title || item.task_id || item.task_run_id;
}

export function TaskMonitorDock() {
  const {
    globalRuntimeMonitor,
    globalRuntimeMonitorError,
    globalRuntimeMonitorLoading,
    globalRuntimeMonitorSelectedGraphMonitor,
    globalRuntimeMonitorSelectedLiveMonitor,
    globalRuntimeMonitorSelectedTaskRunId,
    refreshGlobalRuntimeMonitor,
    selectGlobalRuntimeMonitorTaskRun,
  } = useAppStore();
  const [collapsed, setCollapsed] = useState(false);
  const tasks = useMemo(() => globalRuntimeMonitor?.task_runs ?? [], [globalRuntimeMonitor?.task_runs]);
  const summary = globalRuntimeMonitor?.summary ?? { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 };
  const selectedTask = useMemo(
    () => tasks.find((item) => item.task_run_id === globalRuntimeMonitorSelectedTaskRunId) ?? tasks[0] ?? null,
    [globalRuntimeMonitorSelectedTaskRunId, tasks]
  );
  const hasActiveSignal = tasks.some((item) => ACTIVE_STATUSES.has(item.status));
  const hasSignal = tasks.length > 0;

  useEffect(() => {
    const collapseQuery = window.matchMedia("(max-width: 1260px)");
    if (collapseQuery.matches) {
      setCollapsed(true);
    }
    const collapseOnNarrow = (event: MediaQueryListEvent) => {
      if (event.matches) {
        setCollapsed(true);
      }
    };
    collapseQuery.addEventListener("change", collapseOnNarrow);
    return () => collapseQuery.removeEventListener("change", collapseOnNarrow);
  }, []);

  const statusText = useMemo(() => {
    if (globalRuntimeMonitorLoading && !globalRuntimeMonitor) return "同步中";
    if (summary.waiting) return "等待处理";
    if (summary.running) return `${summary.running} 运行中`;
    if (summary.total) return `${summary.total} 个任务`;
    return "待命";
  }, [globalRuntimeMonitor, globalRuntimeMonitorLoading, summary.running, summary.total, summary.waiting]);

  return (
    <aside className={collapsed ? "task-monitor-dock task-monitor-dock--collapsed" : "task-monitor-dock"} aria-label="全局运行监控">
      <header className="task-monitor-dock__head">
        <button
          aria-label={collapsed ? "展开运行监控" : "折叠运行监控"}
          className="task-monitor-dock__collapse"
          onClick={() => setCollapsed((current) => !current)}
          type="button"
        >
          {collapsed ? <ChevronRight size={17} /> : <Minimize2 size={16} />}
        </button>
        <div className="task-monitor-dock__title">
          <Activity size={16} />
          <span>监控</span>
        </div>
        {!collapsed ? (
          <button
            aria-label="刷新运行监控"
            className="task-monitor-dock__open"
            disabled={globalRuntimeMonitorLoading}
            onClick={() => void refreshGlobalRuntimeMonitor()}
            type="button"
          >
            <RefreshCw size={15} />
          </button>
        ) : null}
      </header>

      {collapsed ? (
        <button
          className={hasActiveSignal ? "task-monitor-dock__rail task-monitor-dock__rail--active" : "task-monitor-dock__rail"}
          onClick={() => setCollapsed(false)}
          type="button"
        >
          <Network size={18} />
          <span>{statusText}</span>
        </button>
      ) : (
        <div className="task-monitor-dock__body">
          <section className={hasSignal ? "task-monitor-summary task-monitor-summary--active" : "task-monitor-summary"}>
            <div>
              <span>全局任务</span>
              <strong>{statusText}</strong>
            </div>
            <small>
              {globalRuntimeMonitor?.updated_at
                ? `最近刷新 ${formatTime(globalRuntimeMonitor.updated_at)}`
                : "任务开始后，这里显示全局运行信息。"}
            </small>
          </section>

          <section className="runtime-monitor-metrics" aria-label="任务运行统计">
            <article><strong>{summary.running}</strong><span>进行中</span></article>
            <article><strong>{summary.waiting}</strong><span>等待</span></article>
            <article><strong>{summary.completed}</strong><span>完成</span></article>
            <article><strong>{summary.total}</strong><span>总数</span></article>
          </section>

          {globalRuntimeMonitorError ? (
            <section className="task-monitor-alert task-monitor-alert--error">
              <strong>监控读取异常</strong>
              <span>{globalRuntimeMonitorError}</span>
            </section>
          ) : null}

          <section className="runtime-monitor-list" aria-label="运行任务列表">
            {tasks.length ? tasks.map((item) => {
              const active = item.task_run_id === selectedTask?.task_run_id;
              return (
                <button
                  className={active ? "runtime-monitor-row runtime-monitor-row--active" : "runtime-monitor-row"}
                  key={item.task_run_id}
                  onClick={() => selectGlobalRuntimeMonitorTaskRun(item.task_run_id)}
                  type="button"
                >
                  <span className={`runtime-monitor-row__status runtime-monitor-row__status--${item.status}`}>
                    {statusIcon(item.status)}
                  </span>
                  <span className="runtime-monitor-row__main">
                    <strong>{taskTitle(item)}</strong>
                    <small>{item.graph_id || item.coordination_run_id || item.task_run_id}</small>
                  </span>
                  <span className="runtime-monitor-row__meta">
                    <strong>{statusLabel(item.status)}</strong>
                    <small>{formatDuration(item.elapsed_seconds)}</small>
                  </span>
                </button>
              );
            }) : (
              <div className="runtime-monitor-empty">
                <Clock3 size={18} />
                <strong>当前没有运行任务</strong>
                <span>Agent 开始执行后，会按任务显示实时状态。</span>
              </div>
            )}
          </section>

          <section className="runtime-monitor-detail" aria-label="选中任务详细监控">
            {selectedTask ? (
              <header className="runtime-monitor-detail__head">
                <div>
                  <span>{statusLabel(selectedTask.status)}</span>
                  <strong>{taskTitle(selectedTask)}</strong>
                </div>
                <small>{selectedTask.event_count} events · 更新 {formatTime(selectedTask.latest_event_at || selectedTask.updated_at)}</small>
              </header>
            ) : null}

            {globalRuntimeMonitorSelectedGraphMonitor ? (
              <TaskGraphRunMonitorPanel monitor={globalRuntimeMonitorSelectedGraphMonitor} />
            ) : globalRuntimeMonitorSelectedLiveMonitor ? (
              <div className="runtime-monitor-lite-detail">
                <article><span>TaskRun</span><strong>{String(globalRuntimeMonitorSelectedLiveMonitor.task_run?.task_run_id ?? selectedTask?.task_run_id ?? "")}</strong></article>
                <article><span>状态</span><strong>{statusLabel(globalRuntimeMonitorSelectedLiveMonitor.status)}</strong></article>
                <article><span>终止原因</span><strong>{globalRuntimeMonitorSelectedLiveMonitor.terminal_reason || "-"}</strong></article>
                <article><span>Checkpoint</span><strong>{String(globalRuntimeMonitorSelectedLiveMonitor.latest_checkpoint?.checkpoint_id ?? "-")}</strong></article>
              </div>
            ) : selectedTask ? (
              <div className="runtime-monitor-empty">
                <RefreshCw size={18} />
                <strong>正在读取详情</strong>
              </div>
            ) : null}
          </section>
        </div>
      )}
    </aside>
  );
}
