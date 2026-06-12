"use client";

import { RefreshCw } from "lucide-react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import type { RuntimeMonitorActionPayload } from "@/lib/api";
import { selectRunMonitorTaskLane } from "@/lib/run-monitor/selectors";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";
import { useAppStore } from "@/lib/store";

export type RunManagementSubpage = "queue" | "records" | "cleanup";

const HIDDEN_ACTIONS = new Set(["open", "inspect", "resume_task"]);
const DANGER_ACTIONS = new Set(["delete_record"]);
const WARNING_ACTIONS = new Set(["close_runtime", "stop_task"]);

export function RunManagementWorkbench({ activePage }: { activePage: RunManagementSubpage }) {
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
  } = useAppStore();
  const lanes = runMonitor?.management?.lanes;
  const queue = [
    ...(lanes?.current ?? []),
    ...(lanes?.attention ?? []),
  ].filter((signal) => signal.work_kind !== "graph_task");
  const recent = lanes?.recent ?? [];
  const hidden = lanes?.hidden ?? [];
  const fallbackTasks = selectRunMonitorTaskLane(runMonitor);
  const queueRows = queue.length ? queue : fallbackTasks.filter((signal) => signal.state !== "completed");
  const recordRows = [...recent, ...hidden];

  async function handleAction(payload: RuntimeMonitorActionPayload) {
    if (payload.action === "delete_record") {
      const approved = await confirm({
        title: "删除运行记录",
        body: "删除会移除该任务的运行记录、事件和相关账本。只想隐藏时请选择清出。",
        confirmLabel: "删除记录",
        tone: "danger",
      });
      if (!approved) return;
    }
    if (payload.action === "stop_task") {
      const approved = await confirm({
        title: "停止运行",
        body: "停止会让任务在运行边界收口，已产生的记录仍会保留。",
        confirmLabel: "停止",
        tone: "warning",
      });
      if (!approved) return;
    }
    if (payload.action === "close_runtime") {
      const approved = await confirm({
        title: "关闭运行",
        body: "关闭会终止该任务的运行状态，并保留记录供健康系统追踪和清理。",
        confirmLabel: "关闭运行",
        tone: "warning",
      });
      if (!approved) return;
    }
    await runMonitorAction(payload);
  }

  function openSignalLog(signal: RunMonitorSignal) {
    const runId = String(signal.task_run_id || "").trim();
    if (!runId) return;
    openRuntimeLog({
      scope: "task_run",
      run_id: runId,
      title: signal.title || "TaskRun",
      subtitle: signal.line || runId,
    });
  }

  return (
    <section className="run-management-workbench">
      <header className="run-management-workbench__head">
        <div>
          <strong>{titleForPage(activePage)}</strong>
          <span>{subtitleForPage(activePage)}</span>
        </div>
        <button disabled={runMonitorLoading} onClick={() => void refreshRunMonitor()} type="button">
          <RefreshCw size={15} />刷新
        </button>
      </header>

      {runMonitorError ? <p className="run-management-workbench__error">{runMonitorError}</p> : null}

      {activePage === "queue" ? (
        <RunManagementRows
          actionLoading={runMonitorActionLoading}
          emptyText="当前没有需要管理的运行队列。"
          onAction={(payload) => void handleAction(payload)}
          onOpenLog={openSignalLog}
          onOpen={openRunMonitorSignal}
          rows={queueRows}
        />
      ) : null}

      {activePage === "records" ? (
        <RunManagementRows
          actionLoading={runMonitorActionLoading}
          emptyText="当前没有已清出或最近完成的运行记录。"
          onAction={(payload) => void handleAction(payload)}
          onOpenLog={openSignalLog}
          onOpen={openRunMonitorSignal}
          rows={recordRows}
        />
      ) : null}

      {activePage === "cleanup" ? (
        <div className="run-management-cleanup">
          <strong>清理预览</strong>
          <span>批量维护仍由健康系统权威执行；这里先接入监控动作和记录可见性，批量 prune 在后续阶段接入健康维护 preflight。</span>
          <RunManagementRows
            actionLoading={runMonitorActionLoading}
            emptyText="暂无可预览清理的记录。"
            onAction={(payload) => void handleAction(payload)}
            onOpenLog={openSignalLog}
            onOpen={openRunMonitorSignal}
            rows={recordRows.filter((signal) => (signal.actions ?? []).some((action) => action.action.includes("delete") && action.enabled))}
          />
        </div>
      ) : null}
    </section>
  );
}

function RunManagementRows({
  actionLoading,
  emptyText,
  onAction,
  onOpenLog,
  onOpen,
  rows,
}: {
  actionLoading: string;
  emptyText: string;
  onAction: (payload: RuntimeMonitorActionPayload) => void;
  onOpenLog: (signal: RunMonitorSignal) => void;
  onOpen: (signalId: string) => void;
  rows: RunMonitorSignal[];
}) {
  if (!rows.length) {
    return <p className="run-management-empty">{emptyText}</p>;
  }
  return (
    <div className="run-management-table">
      <div className="run-management-table__head" aria-hidden="true">
        <span>运行</span>
        <span>状态</span>
        <span>操作</span>
      </div>
      {rows.map((signal) => (
        <div className="run-management-row" key={signal.signal_id || signal.task_run_id || signal.graph_run_id}>
          <button className="run-management-row__main" onClick={() => onOpen(signal.signal_id)} type="button">
            <strong>{signal.title}</strong>
            <span>{signal.line}</span>
          </button>
          <div className="run-management-row__state">
            <strong>{stateLabel(signal)}</strong>
            <span>{signal.detail}</span>
          </div>
          <RunManagementActions loadingAction={actionLoading} onAction={onAction} onOpenLog={onOpenLog} signal={signal} />
        </div>
      ))}
    </div>
  );
}

function RunManagementActions({
  loadingAction,
  onAction,
  onOpenLog,
  signal,
}: {
  loadingAction: string;
  onAction: (payload: RuntimeMonitorActionPayload) => void;
  onOpenLog: (signal: RunMonitorSignal) => void;
  signal: RunMonitorSignal;
}) {
  const actions = (signal.actions ?? []).filter((item) => item.enabled && !HIDDEN_ACTIONS.has(item.action));
  const hasLogAction = Boolean(signal.task_run_id);
  if (!actions.length && !hasLogAction) {
    return <div className="run-management-row__actions" aria-label="无可用操作" />;
  }
  const signalId = signal.signal_id || signal.task_instance_id || signal.task_run_id;
  return (
    <div className="run-management-row__actions" aria-label="运行操作">
      {hasLogAction ? (
        <button className="run-management-row__action" onClick={() => onOpenLog(signal)} type="button">
          日志
        </button>
      ) : null}
      {actions.map((action) => (
        <button
          className={actionButtonClassName(action.action)}
          disabled={Boolean(loadingAction) && loadingAction !== action.action}
          key={action.action}
          onClick={() => {
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

function titleForPage(page: RunManagementSubpage) {
  if (page === "records") return "历史记录";
  if (page === "cleanup") return "清理预览";
  return "工作队列";
}

function subtitleForPage(page: RunManagementSubpage) {
  if (page === "records") return "查看最近完成和已清出监控台的运行记录";
  if (page === "cleanup") return "只展示可预览的删除候选，真实删除仍由后端保护";
  return "当前运行、等待、停滞和失败任务";
}

function stateLabel(signal: RunMonitorSignal) {
  if (signal.visibility?.hidden) return "已清出";
  if (signal.activity_label) return signal.activity_label;
  if (signal.state === "active") return "运行中";
  if (signal.state === "waiting") return "等待";
  if (signal.state === "stale") return "需诊断";
  if (signal.state === "failed") return "失败";
  if (signal.state === "completed") return "完成";
  return "已同步";
}

function actionButtonClassName(action: string) {
  if (DANGER_ACTIONS.has(action)) {
    return "run-management-row__action run-management-row__action--danger";
  }
  if (WARNING_ACTIONS.has(action)) {
    return "run-management-row__action run-management-row__action--warning";
  }
  return "run-management-row__action";
}
