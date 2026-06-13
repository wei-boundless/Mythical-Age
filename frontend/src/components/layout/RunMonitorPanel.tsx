"use client";

import { AlertTriangle, RefreshCw, RadioTower, Terminal } from "lucide-react";
import { useMemo } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { RunTaskLane } from "@/components/layout/RunTaskLane";
import type { RuntimeMonitorActionPayload } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { selectRunMonitorTaskLane } from "@/lib/run-monitor/selectors";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

export function RunMonitorPanel() {
  const confirm = useConfirmDialog();
  const {
    openRunMonitorSignal,
    openRuntimeLog,
    refreshRunMonitor,
    runMonitor,
    runMonitorAction,
    runMonitorActionLoading,
    runMonitorError,
    runMonitorLoading,
    runMonitorSelectedSignalId,
    runMonitorSelectedTaskRunId,
    runMonitorStreamStatus,
  } = useAppStore();
  const tasks = useMemo(() => selectRunMonitorTaskLane(runMonitor), [runMonitor]);
  const selectedSignal = useMemo(
    () => tasks.find((signal) =>
      signal.signal_id === runMonitorSelectedSignalId
      || signal.task_run_id === runMonitorSelectedTaskRunId
    ) ?? null,
    [runMonitorSelectedSignalId, runMonitorSelectedTaskRunId, tasks],
  );
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
        body: "停止请求会让当前任务在运行边界结束，不会清除已经产生的记录。",
        confirmLabel: "停止",
        tone: "warning",
      });
      if (!approved) return;
    }
    if (action === "close_runtime") {
      const approved = await confirm({
        title: "关闭运行",
        body: "关闭会终止该任务或图任务的运行状态，并保留记录供健康系统追踪和清理。",
        confirmLabel: "关闭运行",
        tone: "warning",
      });
      if (!approved) return;
    }
    await runMonitorAction(payload);
  }

  function openSignalLog(signal: RunMonitorSignal | null) {
    const runId = String(signal?.task_run_id || runMonitorSelectedTaskRunId || "").trim();
    if (!runId) return;
    openRuntimeLog({
      scope: "task_run",
      run_id: runId,
      title: signal?.title || "TaskRun",
      subtitle: signal?.line || runId,
    });
  }

  return (
    <section className="run-monitor-panel" aria-label="运行监控">
      <header className="run-monitor-panel__head">
        <div className="run-monitor-panel__headline">
          <span>运行</span>
          <strong>{headline}</strong>
        </div>
        <div className="run-monitor-panel__head-actions">
          <button
            aria-label="打开选中运行日志"
            disabled={!selectedSignal?.task_run_id && !runMonitorSelectedTaskRunId}
            onClick={() => openSignalLog(selectedSignal)}
            title="运行日志"
            type="button"
          >
            <Terminal size={15} />
          </button>
          <button aria-label="刷新运行状态" disabled={runMonitorLoading} onClick={() => void refreshRunMonitor()} type="button">
            <RefreshCw size={15} />
          </button>
        </div>
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

      <div className="run-monitor-panel__body">
        <RunTaskLane
          actionLoading={runMonitorActionLoading}
          onAction={(payload) => void handleAction(payload)}
          onOpen={openRunMonitorSignal}
          onOpenLog={openSignalLog}
          signals={tasks}
          loading={runMonitorLoading}
        />
      </div>
    </section>
  );
}
