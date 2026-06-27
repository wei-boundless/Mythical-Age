"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock3, ScrollText, TimerReset, Workflow } from "lucide-react";
import React from "react";

import type { RunMonitorActionPayload } from "@/lib/api";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";
import { publicRuntimeStatusLabel, publicRuntimeStatusText } from "@/lib/runtimeStatusText";

type RunTaskLaneProps = {
  signals: RunMonitorSignal[];
  loading: boolean;
  actionLoading: string;
  onAction: (payload: RunMonitorActionPayload) => void;
  onOpenLog?: (signal: RunMonitorSignal) => void;
  onOpen: (signalId: string) => void;
};

type RunTaskLaneAction = NonNullable<RunMonitorSignal["actions"]>[number];

const HIDDEN_ACTIONS = new Set(["open", "inspect"]);
const DANGER_ACTIONS = new Set(["delete_record"]);
const WARNING_ACTIONS = new Set(["close_runtime", "stop_task"]);

function signalIcon(signal: RunMonitorSignal) {
  const activityState = signalText(signal.activity_state);
  const state = signalText(signal.state);
  if (activityState === "failed" || activityState === "stale" || state === "failed" || state === "stale") return <AlertTriangle size={15} />;
  if (signal.work_kind === "graph_task") return <Workflow size={15} />;
  if (activityState === "completed" || activityState === "stopped") return <CheckCircle2 size={15} />;
  if (signal.is_running) return <Activity size={15} />;
  return <TimerReset size={15} />;
}

function signalStateLabel(signal: RunMonitorSignal) {
  const activityState = signalText(signal.activity_state);
  const state = signalText(signal.state);
  const lifecycle = signalText(signal.lifecycle);
  const bucket = signalText(signal.bucket);
  const activityLabel = publicRuntimeStatusText(signal.activity_label);
  const statusLabel = publicRuntimeStatusLabel(signal.status);
  if (activityState === "stale" || state === "stale" || lifecycle === "stale" || bucket === "diagnostics") return "等待检查";
  if (activityState === "failed" || state === "failed") return "失败";
  if (activityState === "waiting" || state === "waiting") return activityLabel || statusLabel || "等待继续";
  if (activityState === "paused") return activityLabel || "已暂停";
  if (activityState === "stopped") return activityLabel || statusLabel || "已停止";
  if (activityState === "completed" || state === "completed") return activityLabel || statusLabel || "完成";
  if (activityLabel) return activityLabel;
  if (statusLabel) return statusLabel;
  if (signal.is_running || state === "active" || state === "running" || activityState === "running") return "运行中";
  return "同步";
}

function signalSortRank(signal: RunMonitorSignal) {
  const activityState = signalText(signal.activity_state);
  const state = signalText(signal.state);
  const lifecycle = signalText(signal.lifecycle);
  const bucket = signalText(signal.bucket);
  if (activityState === "failed" || activityState === "stale" || state === "failed" || state === "stale" || lifecycle === "stale" || bucket === "diagnostics") return 0;
  if (signal.is_running || state === "active" || activityState === "running") return 1;
  if (activityState === "waiting" || activityState === "paused" || state === "waiting") return 2;
  return 3;
}

function signalVisualState(signal: RunMonitorSignal) {
  const activityState = signalText(signal.activity_state);
  const state = signalText(signal.state);
  const lifecycle = signalText(signal.lifecycle);
  const bucket = signalText(signal.bucket);
  if (activityState === "stale" || state === "stale" || lifecycle === "stale" || bucket === "diagnostics") return "stale";
  if (activityState === "failed" || state === "failed") return "failed";
  if (activityState === "waiting" || activityState === "paused" || state === "waiting") return "waiting";
  if (activityState === "completed" || activityState === "stopped" || state === "completed") return "completed";
  if (signal.is_running || activityState === "running" || state === "active" || state === "running") return "active";
  return state || "attention";
}

function signalText(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function signalSubtitle(signal: RunMonitorSignal, stateLabel: string) {
  const stateText = stateLabel.trim().toLowerCase();
  const parts = [signal.line, signal.detail]
    .map(publicRuntimeStatusText)
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .filter((value) => value.toLowerCase() !== stateText);
  return parts.join(" / ");
}

function signalTitle(signal: RunMonitorSignal) {
  return publicRuntimeStatusText(signal.title) || "运行任务";
}

function signalOpenId(signal: RunMonitorSignal) {
  return signal.signal_id || signal.task_instance_id || signal.task_run_id || signal.graph_run_id || "";
}

function visibleTaskLaneActions(signal: RunMonitorSignal): RunTaskLaneAction[] {
  return (signal.actions ?? []).filter((item) => item.enabled && !HIDDEN_ACTIONS.has(item.action));
}

export function RunTaskLane({ signals, loading, actionLoading, onAction, onOpen, onOpenLog }: RunTaskLaneProps) {
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
        {visible.length ? visible.map((signal) => {
          const actions = visibleTaskLaneActions(signal);
          const hasLogAction = Boolean(onOpenLog && signal.task_run_id);
          const stateLabel = signalStateLabel(signal);
          const subtitle = signalSubtitle(signal, stateLabel);
          return (
            <div
              className={`run-monitor-task run-monitor-task--${signalVisualState(signal)}${actions.length || hasLogAction ? " run-monitor-task--has-actions" : ""}`}
              key={signalOpenId(signal)}
            >
              <span className="run-monitor-task__icon">{signalIcon(signal)}</span>
              <button className="run-monitor-task__body" disabled={!signalOpenId(signal)} onClick={() => onOpen(signalOpenId(signal))} type="button">
                <span className="run-monitor-task__title-line">
                  <strong>{signalTitle(signal)}</strong>
                  <span className="run-monitor-task__state-badge">{stateLabel}</span>
                </span>
                {subtitle ? <small>{subtitle}</small> : null}
              </button>
              <RunTaskLaneActions
                actions={actions}
                loadingAction={actionLoading}
                onAction={onAction}
                onOpenLog={onOpenLog}
                signal={signal}
              />
            </div>
          );
        }) : (
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

function RunTaskLaneActions({
  actions,
  loadingAction,
  onAction,
  onOpenLog,
  signal,
}: {
  actions: RunTaskLaneAction[];
  loadingAction: string;
  onAction: (payload: RunMonitorActionPayload) => void;
  onOpenLog?: (signal: RunMonitorSignal) => void;
  signal: RunMonitorSignal;
}) {
  if (!actions.length && !(onOpenLog && signal.task_run_id)) return null;
  const signalId = signal.signal_id || signal.task_instance_id || signal.task_run_id;
  return (
    <div className="run-monitor-task__actions" aria-label="运行操作">
      {onOpenLog && signal.task_run_id ? (
        <button
          className="run-monitor-task__action"
          aria-label="打开运行日志"
          onClick={(event) => {
            event.stopPropagation();
            onOpenLog(signal);
          }}
          title="打开运行日志"
          type="button"
        >
          <ScrollText size={13} />
          <span>日志</span>
        </button>
      ) : null}
      {actions.map((action) => (
        <button
          className={runTaskLaneActionClassName(action.action)}
          disabled={Boolean(loadingAction)}
          key={action.action}
          onClick={(event) => {
            event.stopPropagation();
            onAction({
              action: action.action,
              signal_id: signalId,
              task_run_id: signal.task_run_id,
              graph_run_id: signal.graph_run_id || signal.graph_ref?.graph_run_id || "",
            });
          }}
          type="button"
        >
          {loadingAction === action.action ? "处理中" : action.label}
        </button>
      ))}
    </div>
  );
}

function runTaskLaneActionClassName(action: string) {
  if (DANGER_ACTIONS.has(action)) {
    return "run-monitor-task__action run-monitor-task__action--danger";
  }
  if (WARNING_ACTIONS.has(action)) {
    return "run-monitor-task__action run-monitor-task__action--warning";
  }
  return "run-monitor-task__action";
}
