"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock3, TimerReset } from "lucide-react";

import type { RuntimeMonitorActionPayload } from "@/lib/api";
import { RunMonitorActionMenu } from "@/components/layout/RunMonitorActionMenu";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

type RunActivityLaneProps = {
  signals: RunMonitorSignal[];
  loading: boolean;
  actionLoading: string;
  onAction: (payload: RuntimeMonitorActionPayload) => void;
  onOpen: (signalId: string) => void;
};

function signalIcon(signal: RunMonitorSignal) {
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
  return "同步";
}

export function RunActivityLane({ signals, loading, actionLoading, onAction, onOpen }: RunActivityLaneProps) {
  const current = signals.filter((signal) => signal.visibility?.lane === "current" || signal.is_running);
  const attention = signals.filter((signal) => (signal.visibility?.lane === "attention" || ["waiting", "attention", "stale", "failed"].includes(signal.state)) && !signal.is_running);
  const recent = signals.filter((signal) => signal.visibility?.lane === "recent" || signal.state === "completed");
  const visible = [...current.slice(0, 4), ...attention.slice(0, 4), ...recent.slice(0, 3)].slice(0, 8);
  const hidden = Math.max(0, signals.length - visible.length);
  return (
    <section className="run-monitor-lane" aria-label="运行活动">
      <header className="run-monitor-lane__head">
        <span>活动</span>
        {hidden ? <em>另有 {hidden} 条</em> : null}
      </header>
      <div className="run-monitor-activity">
        {visible.length ? visible.map((signal) => (
          <div
            className={`run-monitor-row run-monitor-row--${signal.state}`}
            key={signal.signal_id}
          >
            <span className="run-monitor-row__icon">{signalIcon(signal)}</span>
            <button className="run-monitor-row__body" onClick={() => onOpen(signal.signal_id)} type="button">
              <strong>{signal.title}</strong>
              <small>{signal.line}</small>
            </button>
            <span className="run-monitor-row__meta">
              <strong>{signalStateLabel(signal)}</strong>
              <small>{signal.detail}</small>
            </span>
            <RunMonitorActionMenu loadingAction={actionLoading} onAction={onAction} signal={signal} />
          </div>
        )) : (
          <div className="run-monitor-empty">
            <Clock3 size={17} />
            <strong>{loading ? "同步中" : "暂无活动"}</strong>
            <span>{loading ? "正在读取运行信号。" : "新的运行活动会出现在这里。"}</span>
          </div>
        )}
      </div>
    </section>
  );
}
