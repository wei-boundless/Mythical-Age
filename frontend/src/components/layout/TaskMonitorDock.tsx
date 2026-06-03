"use client";

import { Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock3, Minimize2, Network, PauseCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAppStore } from "@/lib/store";
import { monitorBucketItems, runtimeWorkProjectionFromMonitorItem } from "@/lib/runtimeWorkProjection";
import { monitorItemInstanceId } from "@/lib/runtime-monitor/resourceRefs";
import {
  isWaitingStatus,
  formatTime,
  monitorEventLabel,
  monitorProgressLabel,
  monitorStatusLabel,
  monitorTimeLabel,
  taskTitle,
} from "@/components/layout/runtimeMonitorFormat";
import { useRuntimeNowTicker } from "@/components/layout/runtimeNowTicker";

type RuntimeMonitorBucket = "running" | "waiting" | "completed" | "failed" | "diagnostics";

function statusIcon(status: string) {
  if (isWaitingStatus(status)) return <PauseCircle size={14} />;
  if (status === "completed" || status === "success") return <CheckCircle2 size={14} />;
  if (status === "failed" || status === "aborted") return <AlertTriangle size={14} />;
  return <Activity size={14} />;
}

export function TaskMonitorDock({ embedded = false }: { embedded?: boolean }) {
  const {
    globalRuntimeMonitor,
    globalRuntimeMonitorError,
    globalRuntimeMonitorLoading,
    globalRuntimeMonitorSelectedTaskRunId,
    globalRuntimeMonitorStreamStatus,
    openGlobalRuntimeMonitorTaskRun,
    refreshGlobalRuntimeMonitor,
  } = useAppStore();
  const [collapsed, setCollapsed] = useState(false);
  const [activeBucket, setActiveBucket] = useState<RuntimeMonitorBucket>("running");
  const runningRuns = useMemo(() => monitorBucketItems(globalRuntimeMonitor, "running"), [globalRuntimeMonitor]);
  const waitingRuns = useMemo(() => monitorBucketItems(globalRuntimeMonitor, "waiting"), [globalRuntimeMonitor]);
  const completedRuns = useMemo(() => monitorBucketItems(globalRuntimeMonitor, "completed"), [globalRuntimeMonitor]);
  const failedRuns = useMemo(() => monitorBucketItems(globalRuntimeMonitor, "failed"), [globalRuntimeMonitor]);
  const diagnosticsRuns = useMemo(() => monitorBucketItems(globalRuntimeMonitor, "diagnostics"), [globalRuntimeMonitor]);
  const bucketCounts = useMemo<Record<RuntimeMonitorBucket, number>>(() => ({
    running: runningRuns.length,
    waiting: waitingRuns.length,
    completed: completedRuns.length,
    failed: failedRuns.length,
    diagnostics: diagnosticsRuns.length,
  }), [completedRuns.length, diagnosticsRuns.length, failedRuns.length, runningRuns.length, waitingRuns.length]);
  const runs = activeBucket === "running"
    ? runningRuns
    : activeBucket === "waiting"
      ? waitingRuns
      : activeBucket === "completed"
        ? completedRuns
        : activeBucket === "failed"
          ? failedRuns
          : diagnosticsRuns;
  const allRuns = useMemo(() => [...runningRuns, ...waitingRuns, ...completedRuns, ...failedRuns, ...diagnosticsRuns], [completedRuns, diagnosticsRuns, failedRuns, runningRuns, waitingRuns]);
  const summary = globalRuntimeMonitor?.summary;
  const selectedRun = useMemo(
    () => allRuns.find((item) => item.task_run_id === globalRuntimeMonitorSelectedTaskRunId || monitorItemInstanceId(item) === globalRuntimeMonitorSelectedTaskRunId) ?? runs[0] ?? null,
    [allRuns, globalRuntimeMonitorSelectedTaskRunId, runs]
  );
  const hasActiveSignal = [...runningRuns, ...waitingRuns].some((item) => item.resource_class === "dynamic" || item.action_required || isWaitingStatus(item.status));
  const hasSignal = allRuns.length > 0;
  const nowSeconds = useRuntimeNowTicker(hasActiveSignal);
  const streamLabel = globalRuntimeMonitorStreamStatus === "connected"
    ? "事件流"
    : globalRuntimeMonitorStreamStatus === "connecting"
      ? "连接中"
      : globalRuntimeMonitorStreamStatus === "fallback"
        ? "后台同步"
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

  useEffect(() => {
    if (bucketCounts[activeBucket] > 0) return;
    const nextBucket = (["running", "waiting", "completed", "failed", "diagnostics"] as RuntimeMonitorBucket[])
      .find((bucket) => bucketCounts[bucket] > 0);
    if (nextBucket && nextBucket !== activeBucket) {
      setActiveBucket(nextBucket);
    }
  }, [activeBucket, bucketCounts]);

  const statusText = useMemo(() => {
    if (globalRuntimeMonitorLoading && !globalRuntimeMonitor) return "同步中";
    if (summary?.action_required) return "等待处理";
    if (summary?.running) return `${summary.running} 运行中`;
    if (summary?.waiting) return `${summary.waiting} 等待继续`;
    if (summary?.failed) return `${summary.failed} 失败`;
    if (summary?.diagnostics) return `${summary.diagnostics} 需诊断`;
    if (summary?.completed) return `${summary.completed} 完成`;
    return "待命";
  }, [globalRuntimeMonitor, globalRuntimeMonitorLoading, summary?.action_required, summary?.completed, summary?.diagnostics, summary?.failed, summary?.running, summary?.waiting]);

  return (
    <aside
      className={[
        collapsed ? "task-monitor-dock task-monitor-dock--collapsed" : "task-monitor-dock",
        embedded ? "task-monitor-dock--embedded" : "",
      ].filter(Boolean).join(" ")}
      aria-label="全局运行监控"
    >
      {embedded ? null : (
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
            <span>运行</span>
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
      )}

      {!embedded && collapsed ? (
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
              <span>运行监控</span>
              <strong>{statusText}</strong>
            </div>
            <small>
              {globalRuntimeMonitor?.updated_at
                ? `${streamLabel} · ${selectedRun ? monitorProgressLabel(selectedRun, monitorEventLabel(selectedRun.latest_event_type)) : `校准 ${formatTime(globalRuntimeMonitor.updated_at)}`}`
                : "持续处理和任务图运行会在这里显示。"}
            </small>
          </section>

          <section className="runtime-monitor-metrics" aria-label="处理统计">
            <button className={activeBucket === "running" ? "is-active" : ""} onClick={() => setActiveBucket("running")} type="button">
              <strong>{runningRuns.length}</strong><span>运行中</span>
            </button>
            <button className={activeBucket === "waiting" ? "is-active" : ""} onClick={() => setActiveBucket("waiting")} type="button">
              <strong>{waitingRuns.length}</strong><span>等待</span>
            </button>
            <button className={activeBucket === "completed" ? "is-active" : ""} onClick={() => setActiveBucket("completed")} type="button">
              <strong>{completedRuns.length}</strong><span>已完成</span>
            </button>
            <button className={activeBucket === "failed" ? "is-active" : ""} onClick={() => setActiveBucket("failed")} type="button">
              <strong>{failedRuns.length}</strong><span>失败</span>
            </button>
            <button className={activeBucket === "diagnostics" ? "is-active" : ""} onClick={() => setActiveBucket("diagnostics")} type="button">
              <strong>{diagnosticsRuns.length}</strong><span>诊断</span>
            </button>
          </section>

          {globalRuntimeMonitorError ? (
            <section className="task-monitor-alert task-monitor-alert--attention">
              <strong>监控同步暂不可用</strong>
              <span>{globalRuntimeMonitorError}</span>
            </section>
          ) : null}

          <section className="runtime-monitor-list" aria-label="运行任务列表">
            {runs.length ? runs.map((item) => {
              const itemInstanceId = monitorItemInstanceId(item);
              const active = itemInstanceId === (selectedRun ? monitorItemInstanceId(selectedRun) : "");
              const work = runtimeWorkProjectionFromMonitorItem(item);
              return (
                <button
                  className={active ? "runtime-monitor-row runtime-monitor-row--active" : "runtime-monitor-row"}
                  key={itemInstanceId}
                  onClick={() => openGlobalRuntimeMonitorTaskRun(itemInstanceId)}
                  type="button"
                >
                  <span className={`runtime-monitor-row__status runtime-monitor-row__status--${item.status}`}>
                    {statusIcon(item.status)}
                  </span>
                  <span className="runtime-monitor-row__main">
                    <strong>{work.title || taskTitle(item)}</strong>
                    <small>{monitorProgressLabel(item, work.displayTypeLabel)}</small>
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
                <strong>{activeBucket === "running" ? "当前没有运行任务" : activeBucket === "waiting" ? "暂无等待任务" : activeBucket === "completed" ? "暂无完成任务" : activeBucket === "failed" ? "暂无失败任务" : "暂无诊断任务"}</strong>
                <span>任务会按状态自动归入这里。</span>
              </div>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}
