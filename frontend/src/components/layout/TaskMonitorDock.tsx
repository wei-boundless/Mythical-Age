"use client";

import { Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock3, Minimize2, Network, PauseCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAppStore } from "@/lib/store";
import { summarizeTopLevelTaskGraphMonitor, topLevelTaskGraphMonitorItems } from "../../lib/runtimeMonitorLayering";
import {
  isWaitingStatus,
  formatTime,
  monitorStatusLabel,
  monitorTimeLabel,
  taskTitle,
} from "@/components/layout/runtimeMonitorFormat";
import { useRuntimeNowTicker } from "@/components/layout/runtimeNowTicker";

function statusIcon(status: string) {
  if (isWaitingStatus(status)) return <PauseCircle size={14} />;
  if (status === "completed" || status === "success") return <CheckCircle2 size={14} />;
  if (status === "failed" || status === "aborted") return <AlertTriangle size={14} />;
  return <Activity size={14} />;
}

export function TaskMonitorDock({
  embedded = false,
  onOpenTaskDetail,
}: {
  embedded?: boolean;
  onOpenTaskDetail?: () => void;
}) {
  const {
    globalRuntimeMonitor,
    globalRuntimeMonitorError,
    globalRuntimeMonitorLoading,
    globalRuntimeMonitorSelectedTaskRunId,
    globalRuntimeMonitorStreamStatus,
    refreshGlobalRuntimeMonitor,
    selectGlobalRuntimeMonitorTaskRun,
  } = useAppStore();
  const [collapsed, setCollapsed] = useState(false);
  const tasks = useMemo(() => topLevelTaskGraphMonitorItems(globalRuntimeMonitor), [globalRuntimeMonitor]);
  const summary = useMemo(() => summarizeTopLevelTaskGraphMonitor(tasks), [tasks]);
  const selectedTask = useMemo(
    () => tasks.find((item) => item.task_run_id === globalRuntimeMonitorSelectedTaskRunId) ?? tasks[0] ?? null,
    [globalRuntimeMonitorSelectedTaskRunId, tasks]
  );
  const hasActiveSignal = tasks.some((item) => item.is_live || item.display_bucket === "live");
  const hasSignal = tasks.length > 0;
  const nowSeconds = useRuntimeNowTicker(hasActiveSignal);
  const streamLabel = globalRuntimeMonitorStreamStatus === "connected"
    ? "事件流"
    : globalRuntimeMonitorStreamStatus === "connecting"
      ? "连接中"
      : globalRuntimeMonitorStreamStatus === "fallback"
        ? "快照兜底"
        : "未连接";

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
    if (summary.stale) return `${summary.stale} 个停滞`;
    if (summary.recent) return `${summary.recent} 个刚结束`;
    if (summary.total) return `${summary.total} 个任务图`;
    return "待命";
  }, [globalRuntimeMonitor, globalRuntimeMonitorLoading, summary.recent, summary.running, summary.stale, summary.total, summary.waiting]);

  return (
    <aside
      className={[
        collapsed ? "task-monitor-dock task-monitor-dock--collapsed" : "task-monitor-dock",
        embedded ? "task-monitor-dock--embedded" : "",
      ].filter(Boolean).join(" ")}
      aria-label="全局运行监控"
    >
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
              <span>任务图监控</span>
              <strong>{statusText}</strong>
            </div>
            <small>
              {globalRuntimeMonitor?.updated_at
                ? `${streamLabel} · ${selectedTask?.latest_event_type || `校准 ${formatTime(globalRuntimeMonitor.updated_at)}`}`
                : "任务图开始后，这里显示顶层运行信息。"}
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

          <section className="runtime-monitor-list" aria-label="运行任务图列表">
            {tasks.length ? tasks.map((item) => {
              const active = item.task_run_id === selectedTask?.task_run_id;
              return (
                <button
                  className={active ? "runtime-monitor-row runtime-monitor-row--active" : "runtime-monitor-row"}
                  key={item.task_run_id}
                  onClick={() => {
                    selectGlobalRuntimeMonitorTaskRun(item.task_run_id);
                    onOpenTaskDetail?.();
                  }}
                  type="button"
                >
                  <span className={`runtime-monitor-row__status runtime-monitor-row__status--${item.status}`}>
                    {statusIcon(item.status)}
                  </span>
                  <span className="runtime-monitor-row__main">
                    <strong>{taskTitle(item)}</strong>
                    <small>任务图</small>
                  </span>
                  <span className="runtime-monitor-row__meta">
                    <strong>{monitorStatusLabel(item)}</strong>
                    <small>{monitorTimeLabel(item, nowSeconds)}</small>
                  </span>
                </button>
              );
            }) : (
              <div className="runtime-monitor-empty">
                <Clock3 size={18} />
                <strong>当前没有运行任务图</strong>
                <span>启动任务图后，这里只显示顶层任务图；节点和 Agent 进程在详情里查看。</span>
              </div>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}
