"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock3, TimerReset } from "lucide-react";

import type { RunMonitorSignal } from "@/lib/run-monitor/types";

type RunActivityLaneProps = {
  signals: RunMonitorSignal[];
  loading: boolean;
  onOpen: (signalId: string) => void;
};

function signalIcon(signal: RunMonitorSignal) {
  if (signal.state === "active") return <Activity size={15} />;
  if (signal.state === "failed" || signal.state === "stale") return <AlertTriangle size={15} />;
  if (signal.state === "completed") return <CheckCircle2 size={15} />;
  return <TimerReset size={15} />;
}

function signalStateLabel(signal: RunMonitorSignal) {
  if (signal.state === "active") return "运行中";
  if (signal.state === "waiting") return "等待";
  if (signal.state === "stale") return "诊断";
  if (signal.state === "failed") return "失败";
  if (signal.state === "completed") return "完成";
  return "同步";
}

export function RunActivityLane({ signals, loading, onOpen }: RunActivityLaneProps) {
  const visible = signals.slice(0, 5);
  const hidden = Math.max(0, signals.length - visible.length);
  return (
    <section className="run-monitor-lane" aria-label="运行活动">
      <header className="run-monitor-lane__head">
        <span>活动</span>
        {hidden ? <em>另有 {hidden} 条</em> : null}
      </header>
      <div className="run-monitor-activity">
        {visible.length ? visible.map((signal) => (
          <button
            className={`run-monitor-row run-monitor-row--${signal.state}`}
            key={signal.signal_id}
            onClick={() => onOpen(signal.signal_id)}
            type="button"
          >
            <span className="run-monitor-row__icon">{signalIcon(signal)}</span>
            <span className="run-monitor-row__body">
              <strong>{signal.title}</strong>
              <small>{signal.line}</small>
            </span>
            <span className="run-monitor-row__meta">
              <strong>{signalStateLabel(signal)}</strong>
              <small>{signal.detail}</small>
            </span>
          </button>
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
