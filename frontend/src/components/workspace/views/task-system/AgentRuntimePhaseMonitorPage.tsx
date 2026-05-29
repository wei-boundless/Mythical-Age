"use client";

import { Activity, CheckCircle2, ClipboardCheck, DatabaseZap, RefreshCw, ShieldAlert } from "lucide-react";

import type { HarnessTaskRunLiveMonitor, HarnessTaskRunSummary } from "@/lib/api";

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

function taskRunId(summary: HarnessTaskRunSummary | null | undefined) {
  return text(asRecord(summary).task_run_id, "");
}

function agentRuntimePhaseSummary(monitor: HarnessTaskRunLiveMonitor | null) {
  return asRecord(monitor?.agent_runtime_phase_summary);
}

export function AgentRuntimePhaseMonitorPage({
  monitorForSelectedRun,
  onRefresh,
  onTaskRunIdChange,
  runtimeLoading,
  runtimeRunsForSelectedGraph,
  runtimeTaskRunId,
  selectedRuntimeSummary,
}: {
  monitorForSelectedRun: HarnessTaskRunLiveMonitor | null;
  onRefresh: () => void;
  onTaskRunIdChange: (taskRunId: string) => void;
  runtimeLoading: boolean;
  runtimeRunsForSelectedGraph: HarnessTaskRunSummary[];
  runtimeTaskRunId: string;
  selectedRuntimeSummary: HarnessTaskRunSummary | null;
}) {
  const summary = agentRuntimePhaseSummary(monitorForSelectedRun);
  const planning = asRecord(summary.planning);
  const progress = asRecord(summary.progress);
  const ledger = asRecord(summary.tool_observation_ledger);
  const ledgerSummary = asRecord(ledger.summary);
  const latestRecord = asRecord(ledger.latest_record);
  const verification = asRecord(summary.verification);
  const checks = asRecord(verification.checks);
  const blocker = asRecord(summary.blocker);
  const completionJudgment = asRecord(summary.completion_judgment);
  const unsatisfied = asArray(completionJudgment.unsatisfied_obligations).map((item) => text(item, "")).filter(Boolean);
  const latestEvent = asRecord(summary.latest_event);
  const selectedRunId = runtimeTaskRunId.trim();

  return (
    <TaskRuntimeManagementPage>
      <header className="task-management-titlebar">
        <div>
          <span>AgentRuntime</span>
          <h3>阶段监控</h3>
          <p>这里只看 AgentRuntime 的计划阶段、收口验证、执行义务和工具观察账本。任务图结构与资源目录在各自页面维护。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={runtimeLoading} onClick={onRefresh}>
            <RefreshCw size={15} />{runtimeLoading ? "刷新中" : "刷新阶段监控"}
          </ToolbarButton>
        </div>
      </header>
      <section className="boundary-card">
        <header><strong>运行实例</strong><span>{selectedRunId || "未选择"}</span></header>
        <div className="boundary-form">
          <Field label="task_run_id" wide>
            <input
              onChange={(event) => onTaskRunIdChange(event.target.value)}
              placeholder="输入 AgentRuntime task_run_id"
              value={runtimeTaskRunId}
            />
          </Field>
          <Field label="可选运行">
            <select onChange={(event) => onTaskRunIdChange(event.target.value)} value={runtimeTaskRunId}>
              <option value="">选择最近 TaskRun</option>
              {runtimeRunsForSelectedGraph.map((item, index) => {
                const id = taskRunId(item) || `run_${index + 1}`;
                const status = text(asRecord(item).status, "unknown");
                return <option key={id} value={id}>{id} · {status} · {item.execution_runtime_kind || "runtime"}</option>;
              })}
            </select>
          </Field>
        </div>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong><Activity size={15} />阶段状态</strong><span>{text(summary.state, "not_available")}</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>State</span><strong>{text(summary.state, "未载入")}</strong></div>
            <div className="boundary-readiness"><span>Plan</span><strong>{text(planning.status, "not_required")}</strong></div>
            <div className="boundary-readiness"><span>Verification</span><strong>{text(verification.status, "not_run")}</strong></div>
            <div className="boundary-readiness"><span>Unsatisfied</span><strong>{unsatisfied.length}</strong></div>
          </div>
          <div className={blocker.kind ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
            <strong>{blocker.kind ? text(blocker.kind) : "当前没有阻塞原因"}</strong>
            <span>{blocker.kind ? text(blocker.summary) : text(latestEvent.event_type, "等待运行事件")}</span>
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
          <header><strong><ClipboardCheck size={15} />执行义务</strong><span>{text(summary.interaction_mode, "unknown")}</span></header>
          <div className="boundary-kv">
            <p><span>runtime_control</span><strong>{text(summary.runtime_control, "-")}</strong></p>
            <p><span>planning</span><strong>{text(planning.status, "-")}</strong></p>
            <p><span>ledger_ref</span><strong>{text(ledger.ledger_id, "-")}</strong></p>
            <p><span>step_count</span><strong>{numberText(progress.step_count)}</strong></p>
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
                    <span>completion_judgment.unsatisfied_obligations</span>
                    <small>运行必须补充真实观察或明确证据边界，不能靠 final answer 文本越过。</small>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="task-graph-note">
              <strong><CheckCircle2 size={15} />执行义务未报告缺口</strong>
              <span>{selectedRuntimeSummary ? "当前选择的运行没有未满足义务。" : "选择一个 TaskRun 后可查看完整状态。"}</span>
            </div>
          )}
        </article>
      </section>
    </TaskRuntimeManagementPage>
  );
}
