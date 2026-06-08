"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock3, TimerReset, Workflow } from "lucide-react";

import type { RuntimeMonitorActionPayload } from "@/lib/api";
import { RunMonitorActionMenu } from "@/components/layout/RunMonitorActionMenu";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

type RunTaskLaneProps = {
  signals: RunMonitorSignal[];
  loading: boolean;
  actionLoading: string;
  onAction: (payload: RuntimeMonitorActionPayload) => void;
  onOpen: (signalId: string) => void;
};

function signalIcon(signal: RunMonitorSignal) {
  if (signal.work_kind === "graph_task") return <Workflow size={15} />;
  if (signal.is_running) return <Activity size={15} />;
  if (signal.activity_state === "failed" || signal.activity_state === "stale") return <AlertTriangle size={15} />;
  if (signal.activity_state === "completed" || signal.activity_state === "stopped") return <CheckCircle2 size={15} />;
  return <TimerReset size={15} />;
}

function signalStateLabel(signal: RunMonitorSignal) {
  if (signal.activity_label) return signal.activity_label;
  if (signal.is_running) return "运行中";
  if (signal.activity_state === "waiting") return "等待继续";
  if (signal.activity_state === "paused") return "已暂停";
  if (signal.activity_state === "stale") return "等待检查";
  if (signal.activity_state === "failed") return "失败";
  if (signal.activity_state === "stopped") return "已停止";
  if (signal.activity_state === "completed") return "完成";
  if (signal.state === "active" || signal.state === "running") return "运行中";
  if (signal.state === "stale") return "等待检查";
  if (signal.state === "failed") return "失败";
  return "同步";
}

function signalSortRank(signal: RunMonitorSignal) {
  if (signal.is_running || signal.state === "active" || signal.activity_state === "running") return 0;
  if (signal.activity_state === "waiting" || signal.activity_state === "paused" || signal.state === "waiting") return 1;
  if (signal.activity_state === "failed" || signal.activity_state === "stale" || signal.state === "failed" || signal.state === "stale") return 2;
  return 3;
}

function signalOpenId(signal: RunMonitorSignal) {
  return signal.signal_id || signal.task_instance_id || signal.task_run_id || signal.graph_run_id || "";
}

export function RunTaskLane({ signals, loading, actionLoading, onAction, onOpen }: RunTaskLaneProps) {
  const ordered = [...signals].sort((left, right) => signalSortRank(left) - signalSortRank(right));
  const visible = ordered.slice(0, 8);
  const hidden = Math.max(0, ordered.length - visible.length);
  return (
    <section className="run-monitor-lane" aria-label="运行任务">
      <header className="run-monitor-lane__head">
        <span>任务</span>
        {hidden ? <em>另有 {hidden} 条</em> : null}
      </header>
      <div className="run-monitor-tasks">
        {visible.length ? visible.map((signal) => (
          <div
            className={`run-monitor-task run-monitor-task--${signal.state}`}
            key={signalOpenId(signal)}
          >
            <span className="run-monitor-task__icon">{signalIcon(signal)}</span>
            <button className="run-monitor-task__body" disabled={!signalOpenId(signal)} onClick={() => onOpen(signalOpenId(signal))} type="button">
              <strong>{signal.title}</strong>
              <small>{signal.line}</small>
            </button>
            <span className="run-monitor-task__meta">
              <strong>{signalStateLabel(signal)}</strong>
              <small>{signal.detail}</small>
            </span>
            <RunMonitorActionMenu loadingAction={actionLoading} onAction={onAction} signal={signal} />
          </div>
        )) : (
          <div className="run-monitor-empty">
            <Clock3 size={17} />
            <strong>{loading ? "同步中" : "暂无任务"}</strong>
            <span>{loading ? "正在读取运行信号。" : "运行中的任务会出现在这里。"}</span>
          </div>
        )}
      </div>
    </section>
  );
}
