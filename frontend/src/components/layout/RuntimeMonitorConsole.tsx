"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock3, RefreshCw, RadioTower, TimerReset } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getRuntimeMonitorConsole, type RuntimeMonitorConsole as RuntimeMonitorConsolePayload, type RuntimeMonitorConsoleSignal } from "@/lib/api";
import { useAppStore } from "@/lib/store";

function signalIcon(signal: RuntimeMonitorConsoleSignal) {
  if (signal.state === "active") return <Activity size={15} />;
  if (signal.state === "failed" || signal.state === "stale") return <AlertTriangle size={15} />;
  if (signal.state === "completed") return <CheckCircle2 size={15} />;
  if (signal.state === "waiting") return <TimerReset size={15} />;
  return <RadioTower size={15} />;
}

function signalStateLabel(signal: RuntimeMonitorConsoleSignal) {
  if (signal.state === "active") return "运行中";
  if (signal.state === "waiting") return "等待";
  if (signal.state === "stale") return "诊断";
  if (signal.state === "failed") return "失败";
  if (signal.state === "completed") return "完成";
  return "同步";
}

function pickSignals(consoleMonitor: RuntimeMonitorConsolePayload | null) {
  if (!consoleMonitor) return [];
  if (consoleMonitor.primary.length) return consoleMonitor.primary;
  if (consoleMonitor.attention.length) return consoleMonitor.attention;
  return consoleMonitor.signals;
}

function timestampLabel(updatedAt: number) {
  if (!updatedAt) return "";
  return new Date(updatedAt * 1000).toLocaleTimeString();
}

export function RuntimeMonitorConsole() {
  const { openGlobalRuntimeMonitorTaskRun } = useAppStore();
  const [monitor, setMonitor] = useState<RuntimeMonitorConsolePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const signals = useMemo(() => pickSignals(monitor), [monitor]);
  const headline = monitor?.summary.active
    ? `${monitor.summary.active} 运行中`
    : monitor?.summary.waiting
      ? `${monitor.summary.waiting} 等待继续`
      : monitor?.summary.attention
        ? `${monitor.summary.attention} 需关注`
        : monitor?.summary.recent
          ? `${monitor.summary.recent} 最近完成`
          : "待命";

  async function refresh() {
    setLoading(true);
    try {
      const next = await getRuntimeMonitorConsole(40);
      setMonitor(next);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "监控读取失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const tick = async () => {
      try {
        const next = await getRuntimeMonitorConsole(40);
        if (!cancelled) {
          setMonitor(next);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "监控读取失败");
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(tick, 2500);
        }
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, []);

  return (
    <section className="runtime-monitor-console" aria-label="运行监控">
      <header className="runtime-monitor-console__head">
        <div>
          <span>运行监控</span>
          <strong>{headline}</strong>
        </div>
        <button aria-label="刷新运行监控" disabled={loading} onClick={() => void refresh()} type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="runtime-monitor-console__counts" aria-label="监控统计">
        <span><strong>{monitor?.summary.active ?? 0}</strong>运行</span>
        <span><strong>{monitor?.summary.waiting ?? 0}</strong>等待</span>
        <span><strong>{monitor?.summary.attention ?? 0}</strong>关注</span>
        <span><strong>{monitor?.summary.failed ?? 0}</strong>失败</span>
      </div>

      {error ? (
        <div className="runtime-monitor-console__notice">
          <AlertTriangle size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="runtime-monitor-console__stream" aria-label="运行活动流">
        {signals.length ? signals.map((signal) => (
          <button
            className={`runtime-monitor-console-row runtime-monitor-console-row--${signal.state}`}
            key={signal.signal_id}
            onClick={() => openGlobalRuntimeMonitorTaskRun(signal.task_instance_id || signal.task_run_id || signal.signal_id)}
            type="button"
          >
            <span className="runtime-monitor-console-row__icon">{signalIcon(signal)}</span>
            <span className="runtime-monitor-console-row__body">
              <strong>{signal.title}</strong>
              <small>{signal.line}</small>
            </span>
            <span className="runtime-monitor-console-row__meta">
              <strong>{signalStateLabel(signal)}</strong>
              <small>{signal.detail || timestampLabel(signal.timestamps.updated_at || monitor?.updated_at || 0)}</small>
            </span>
          </button>
        )) : (
          <div className="runtime-monitor-console__empty">
            <Clock3 size={18} />
            <strong>{loading ? "同步中" : "暂无运行任务"}</strong>
            <span>{loading ? "正在读取运行信号。" : "新的任务开始后会出现在这里。"}</span>
          </div>
        )}
      </div>
    </section>
  );
}
