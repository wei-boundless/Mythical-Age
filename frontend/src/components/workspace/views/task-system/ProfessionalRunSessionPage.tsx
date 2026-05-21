"use client";

import { Activity, CheckCircle2, ClipboardCheck, DatabaseZap, RefreshCw, ShieldAlert } from "lucide-react";

import type { RuntimeLoopTaskRunLiveMonitor, RuntimeLoopTaskRunSummary } from "@/lib/api";

import { TaskRuntimeManagementPage } from "./TaskSystemPages";
import { TaskSystemField as Field, TaskSystemToolbarButton as ToolbarButton } from "./TaskSystemWorkbenchUi";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "-") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function numberText(value: unknown) {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? String(next) : "0";
}

function taskRunId(summary: RuntimeLoopTaskRunSummary | null | undefined) {
  return text(asRecord(summary?.task_run).task_run_id, "");
}

function professionalSummary(monitor: RuntimeLoopTaskRunLiveMonitor | null) {
  return asRecord(monitor?.professional_task_summary);
}

export function ProfessionalRunSessionPage({
  monitorForSelectedRun,
  onRefresh,
  onTaskRunIdChange,
  runtimeLoading,
  runtimeRunsForSelectedGraph,
  runtimeTaskRunId,
  selectedRuntimeSummary,
}: {
  monitorForSelectedRun: RuntimeLoopTaskRunLiveMonitor | null;
  onRefresh: () => void;
  onTaskRunIdChange: (taskRunId: string) => void;
  runtimeLoading: boolean;
  runtimeRunsForSelectedGraph: RuntimeLoopTaskRunSummary[];
  runtimeTaskRunId: string;
  selectedRuntimeSummary: RuntimeLoopTaskRunSummary | null;
}) {
  const summary = professionalSummary(monitorForSelectedRun);
  const runState = asRecord(summary.professional_run_state);
  const session = asRecord(summary.professional_run_session);
  const ledger = asRecord(summary.tool_observation_ledger);
  const ledgerSummary = asRecord(ledger.summary);
  const latestRecord = asRecord(ledger.latest_record);
  const verification = asRecord(summary.verification);
  const checks = asRecord(verification.checks);
  const blocker = asRecord(summary.blocker);
  const unsatisfied = asArray(runState.unsatisfied_obligations).map((item) => text(item, "")).filter(Boolean);
  const transition = asRecord(runState.latest_transition);
  const selectedRunId = runtimeTaskRunId.trim();

  return (
    <TaskRuntimeManagementPage>
      <header className="task-management-titlebar">
        <div>
          <span>专业运行</span>
          <h3>长任务会话</h3>
          <p>这里只看 professional run session、状态机、执行义务和工具观察账本。任务图结构与资源目录在各自页面维护。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={runtimeLoading} onClick={onRefresh}>
            <RefreshCw size={15} />{runtimeLoading ? "刷新中" : "刷新专业运行"}
          </ToolbarButton>
        </div>
      </header>
      <section className="boundary-card">
        <header><strong>运行实例</strong><span>{selectedRunId || "未选择"}</span></header>
        <div className="boundary-form">
          <Field label="task_run_id" wide>
            <input
              onChange={(event) => onTaskRunIdChange(event.target.value)}
              placeholder="输入 professional task_run_id"
              value={runtimeTaskRunId}
            />
          </Field>
          <Field label="可选运行">
            <select onChange={(event) => onTaskRunIdChange(event.target.value)} value={runtimeTaskRunId}>
              <option value="">选择最近 TaskRun</option>
              {runtimeRunsForSelectedGraph.map((item, index) => {
                const id = taskRunId(item) || `run_${index + 1}`;
                const status = text(asRecord(item.task_run).status, "unknown");
                return <option key={id} value={id}>{id} · {status} · {item.latest_event_type || "no_event"}</option>;
              })}
            </select>
          </Field>
        </div>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong><Activity size={15} />状态机</strong><span>{text(runState.state, "not_available")}</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>State</span><strong>{text(runState.state, "未载入")}</strong></div>
            <div className="boundary-readiness"><span>Transitions</span><strong>{numberText(runState.transition_count)}</strong></div>
            <div className="boundary-readiness"><span>Verification</span><strong>{text(verification.status, "not_run")}</strong></div>
            <div className="boundary-readiness"><span>Unsatisfied</span><strong>{unsatisfied.length}</strong></div>
          </div>
          <div className={blocker.kind ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
            <strong>{blocker.kind ? text(blocker.kind) : "当前没有阻塞原因"}</strong>
            <span>{blocker.kind ? text(blocker.summary) : text(transition.reason, "等待状态转移记录")}</span>
          </div>
        </article>
        <article className="boundary-card">
          <header><strong><DatabaseZap size={15} />工具观察账本</strong><span>{text(ledger.ledger_id, "no_ledger")}</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>Records</span><strong>{numberText(ledgerSummary.record_count)}</strong></div>
            <div className="boundary-readiness"><span>Read</span><strong>{numberText(ledgerSummary.read_count)}</strong></div>
            <div className="boundary-readiness"><span>Write</span><strong>{numberText(ledgerSummary.write_count)}</strong></div>
            <div className="boundary-readiness"><span>Verify</span><strong>{numberText(ledgerSummary.verification_count)}</strong></div>
          </div>
          <div className="task-graph-note">
            <strong>{text(latestRecord.tool_name, "暂无工具观察")}</strong>
            <span>{text(latestRecord.result_preview, "没有最近观察结果")}</span>
          </div>
        </article>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong><ClipboardCheck size={15} />执行义务</strong><span>{text(session.interaction_mode, text(summary.interaction_mode, "unknown"))}</span></header>
          <div className="boundary-kv">
            <p><span>session_id</span><strong>{text(session.session_id, "-")}</strong></p>
            <p><span>state_ref</span><strong>{text(session.state_ref, "-")}</strong></p>
            <p><span>ledger_ref</span><strong>{text(session.tool_observation_ledger_ref, "-")}</strong></p>
            <p><span>write_observation</span><strong>{numberText(checks.write_observation_count)}</strong></p>
            <p><span>verification_command</span><strong>{numberText(checks.verification_command_count)}</strong></p>
          </div>
        </article>
        <article className="boundary-card">
          <header><strong><ShieldAlert size={15} />未满足项</strong><span>{unsatisfied.length}</span></header>
          {unsatisfied.length ? (
            <div className="task-resource-authority-list">
              {unsatisfied.map((item) => (
                <article className="task-resource-authority-row task-resource-authority-row--hard" key={item}>
                  <div className="task-resource-authority-row__icon"><ShieldAlert size={16} /></div>
                  <div>
                    <strong>{item}</strong>
                    <span>professional_run_state.unsatisfied_obligations</span>
                    <small>运行必须返修或补充观察，不能靠 final answer 文本越过。</small>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="task-graph-note">
              <strong><CheckCircle2 size={15} />执行义务未报告缺口</strong>
              <span>{selectedRuntimeSummary ? "当前选择的运行没有未满足义务。" : "选择一个专业 TaskRun 后可查看完整状态。"}</span>
            </div>
          )}
        </article>
      </section>
    </TaskRuntimeManagementPage>
  );
}
