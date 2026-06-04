"use client";

import { AlertTriangle, RefreshCw, RadioTower } from "lucide-react";
import { useMemo } from "react";

import { RunActivityLane } from "@/components/layout/RunActivityLane";
import { RunProjectLane } from "@/components/layout/RunProjectLane";
import { useAppStore } from "@/lib/store";
import { selectRunMonitorActivityLane, selectRunMonitorProjectLane } from "@/lib/run-monitor/selectors";

export function RunMonitorPanel() {
  const {
    openRunMonitorSignal,
    refreshRunMonitor,
    runMonitor,
    runMonitorError,
    runMonitorLoading,
    runMonitorStreamStatus,
  } = useAppStore();
  const activity = useMemo(() => selectRunMonitorActivityLane(runMonitor), [runMonitor]);
  const projects = useMemo(() => selectRunMonitorProjectLane(runMonitor), [runMonitor]);
  const summary = runMonitor?.summary;
  const headline = summary?.active
    ? `${summary.active} 运行中`
    : summary?.projects
      ? `${summary.projects} 个项目`
      : summary?.attention
        ? `${summary.attention} 需关注`
        : "待命";
  const streamLabel = runMonitorStreamStatus === "connected"
    ? "实时"
    : runMonitorStreamStatus === "connecting"
      ? "连接中"
      : runMonitorStreamStatus === "fallback"
        ? "轮询"
        : "离线";

  return (
    <section className="run-monitor-panel" aria-label="运行监控">
      <header className="run-monitor-panel__head">
        <div>
          <span>运行</span>
          <strong>{headline}</strong>
        </div>
        <button aria-label="刷新运行状态" disabled={runMonitorLoading} onClick={() => void refreshRunMonitor()} type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="run-monitor-panel__status" aria-label="运行状态">
        <span><RadioTower size={13} />{streamLabel}</span>
        <span><strong>{summary?.active ?? 0}</strong>运行</span>
        <span><strong>{summary?.waiting ?? 0}</strong>等待</span>
        <span><strong>{summary?.attention ?? 0}</strong>关注</span>
      </div>

      {runMonitorError ? (
        <div className="run-monitor-panel__notice">
          <AlertTriangle size={15} />
          <span>{runMonitorError}</span>
        </div>
      ) : null}

      <RunProjectLane projects={projects} onOpen={openRunMonitorSignal} />
      <RunActivityLane signals={activity} loading={runMonitorLoading} onOpen={openRunMonitorSignal} />
    </section>
  );
}
