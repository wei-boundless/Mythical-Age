"use client";

import { AlertTriangle, RefreshCw, RadioTower } from "lucide-react";
import { useMemo } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { RunActivityLane } from "@/components/layout/RunActivityLane";
import { RunProjectLane } from "@/components/layout/RunProjectLane";
import type { RuntimeMonitorActionPayload } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { selectRunMonitorActivityLane, selectRunMonitorProjectLane } from "@/lib/run-monitor/selectors";

export function RunMonitorPanel() {
  const confirm = useConfirmDialog();
  const {
    openRunMonitorSignal,
    refreshRunMonitor,
    runMonitor,
    runMonitorAction,
    runMonitorActionLoading,
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

  async function handleAction(payload: RuntimeMonitorActionPayload) {
    const action = String(payload.action || "").trim();
    if (action === "delete_record") {
      const approved = await confirm({
        title: "删除运行记录",
        body: "这会删除该任务的运行记录、事件和相关账本。清出监控台不需要删除记录。",
        confirmLabel: "删除记录",
        tone: "danger",
      });
      if (!approved) return;
    }
    if (action === "stop_task") {
      const approved = await confirm({
        title: "停止当前运行",
        body: "停止请求会让当前任务在运行边界收口，不会清除已经产生的记录。",
        confirmLabel: "停止",
        tone: "warning",
      });
      if (!approved) return;
    }
    await runMonitorAction(payload);
  }

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

      <RunProjectLane actionLoading={runMonitorActionLoading} onAction={(payload) => void handleAction(payload)} projects={projects} onOpen={openRunMonitorSignal} />
      <RunActivityLane actionLoading={runMonitorActionLoading} onAction={(payload) => void handleAction(payload)} signals={activity} loading={runMonitorLoading} onOpen={openRunMonitorSignal} />
    </section>
  );
}
