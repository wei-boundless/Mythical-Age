"use client";

import { AlertTriangle, CheckCircle2, ClipboardList, Database, FileStack, Loader2, Monitor, RefreshCw } from "lucide-react";

import type {
  ArtifactRepositoryOverview,
  FormalMemoryOverview,
  RuntimeLoopTaskRunLiveMonitor,
  RuntimeLoopTaskRunSummary,
  TaskGraphRecord,
} from "@/lib/api";

import type { TaskGraphDraftV2 } from "../taskGraphDraftV2";
import { TaskRuntimeManagementPage } from "../TaskSystemPages";
import { TaskSystemField as Field, TaskSystemToolbarButton as ToolbarButton, taskSystemOptionLabel } from "../TaskSystemWorkbenchUi";

type RuntimeDomain = {
  title?: string;
};

function dictOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function recordFieldText(record: Record<string, unknown> | null | undefined, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = record?.[key];
    if (value !== null && value !== undefined && String(value).trim()) {
      return String(value);
    }
  }
  return fallback;
}

function getRuntimeTaskRunId(summary: RuntimeLoopTaskRunSummary | null | undefined) {
  return recordFieldText(dictOf(summary?.task_run), ["task_run_id", "id", "run_id"], "");
}

function formatRuntimeTime(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "-";
  }
  const millis = numeric > 1_000_000_000_000 ? numeric : numeric * 1000;
  return new Date(millis).toLocaleString();
}

function statusBadgeClass(status: string) {
  const normalized = status.toLowerCase();
  if (["completed", "committed", "pass", "passed", "ok", "success"].includes(normalized)) return "boundary-badge boundary-badge--ok";
  if (["failed", "error", "rejected", "stale"].includes(normalized)) return "boundary-badge boundary-badge--danger";
  if (["running", "active", "pending", "staging", "warning"].includes(normalized)) return "boundary-badge boundary-badge--warn";
  return "boundary-badge";
}

export function TaskRuntimeLibraryPage({
  artifactOverview,
  artifactStatusCounts,
  formalOverview,
  monitorForSelectedRun,
  onOpenMonitor,
  onOpenWorkbench,
  onRefresh,
  onTaskRunIdChange,
  runtimeBoundTaskRunId,
  runtimeError,
  runtimeLoading,
  runtimeRunsForSelectedGraph,
  runtimeTaskRunId,
  selectedDomain,
  selectedRuntimeRunRecord,
  selectedRuntimeSummary,
  selectedTaskGraph,
  taskGraphDraft,
}: {
  artifactOverview: ArtifactRepositoryOverview | null;
  artifactStatusCounts: Record<string, number>;
  formalOverview: FormalMemoryOverview | null;
  monitorForSelectedRun: RuntimeLoopTaskRunLiveMonitor | null;
  onOpenMonitor: () => void;
  onOpenWorkbench: () => void;
  onRefresh: () => void;
  onTaskRunIdChange: (taskRunId: string) => void;
  runtimeBoundTaskRunId: string;
  runtimeError?: string;
  runtimeLoading: boolean;
  runtimeRunsForSelectedGraph: RuntimeLoopTaskRunSummary[];
  runtimeTaskRunId: string;
  selectedDomain: RuntimeDomain | null;
  selectedRuntimeRunRecord: Record<string, unknown>;
  selectedRuntimeSummary: RuntimeLoopTaskRunSummary | null;
  selectedTaskGraph: TaskGraphRecord | null;
  taskGraphDraft: TaskGraphDraftV2;
}) {
  return (
    <TaskRuntimeManagementPage>
      <header className="task-management-titlebar">
        <div>
          <span>运行管理</span>
          <h3>运行库</h3>
          <p>运行数据以显式 task_run_id 隔离。这里查看正式记忆库、产物库和当前运行状态，不配置任务图结构。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={runtimeLoading} onClick={onRefresh}>
            {runtimeLoading ? <Loader2 size={15} /> : <RefreshCw size={15} />}刷新运行库
          </ToolbarButton>
          <ToolbarButton disabled={!runtimeBoundTaskRunId} onClick={onOpenMonitor}>
            <Monitor size={15} />打开常驻监控窗
          </ToolbarButton>
          <ToolbarButton disabled={!selectedTaskGraph} onClick={onOpenWorkbench}>进入发布与运行</ToolbarButton>
        </div>
      </header>
      {runtimeError ? (
        <div className="boundary-notice boundary-notice--error">
          <AlertTriangle size={16} />
          {runtimeError}
        </div>
      ) : null}
      <section className="boundary-card">
        <header>
          <strong>运行实例焦点</strong>
          <span>{runtimeTaskRunId.trim() ? "按 task_run_id 隔离" : "全局概览"}</span>
        </header>
        <div className="boundary-form">
          <Field label="task_run_id" wide>
            <input
              onChange={(event) => onTaskRunIdChange(event.target.value)}
              placeholder="输入 task_run_id；留空时仅作全局概览，不能判断单次运行隔离"
              value={runtimeTaskRunId}
            />
          </Field>
          <Field label="当前会话运行实例">
            <select onChange={(event) => onTaskRunIdChange(event.target.value)} value={runtimeTaskRunId}>
              <option value="">全局概览，不筛选 task_run_id</option>
              {runtimeRunsForSelectedGraph.map((item, index) => {
                const id = getRuntimeTaskRunId(item) || `run_${index}`;
                const run = dictOf(item.task_run);
                const status = recordFieldText(run, ["status", "runtime_status"], "unknown");
                const label = `${id} · ${status} · ${item.latest_event_type || "no_event"}`;
                return <option key={id} value={id}>{label}</option>;
              })}
            </select>
          </Field>
          <Field label="常驻监控绑定">
            <input readOnly value={runtimeBoundTaskRunId || "未绑定常驻监控运行"} />
          </Field>
        </div>
        <div className={runtimeTaskRunId.trim() ? "boundary-notice" : "boundary-notice boundary-notice--error"}>
          {runtimeTaskRunId.trim() ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {runtimeTaskRunId.trim()
            ? `当前正式记忆库和产物库查询只读取 task_run_id=${runtimeTaskRunId.trim()} 的运行数据。`
            : "当前为全局概览，只能看总量和最近记录，不能据此判断某一次任务是否隔离。"}
        </div>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong>当前任务图</strong><span>{selectedTaskGraph?.graph_id || "未选择"}</span></header>
          <div className="boundary-kv">
            <p><span>任务域</span><strong>{selectedDomain?.title || "-"}</strong></p>
            <p><span>图</span><strong>{selectedTaskGraph?.title || "-"}</strong></p>
            <p><span>发布状态</span><strong>{String(selectedTaskGraph?.publish_state || taskGraphDraft.publish_state || "draft")}</strong></p>
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>运行状态</strong><span>{monitorForSelectedRun?.status || recordFieldText(selectedRuntimeRunRecord, ["status", "runtime_status"], "未选择")}</span></header>
          <div className="boundary-kv">
            <p><span>task_run_id</span><strong>{runtimeTaskRunId.trim() || "未筛选"}</strong></p>
            <p><span>最新事件</span><strong>{selectedRuntimeSummary?.latest_event_type || "-"}</strong></p>
            <p><span>事件数量</span><strong>{selectedRuntimeSummary?.event_count ?? "-"}</strong></p>
            <p><span>更新时间</span><strong>{formatRuntimeTime(monitorForSelectedRun?.updated_at ?? selectedRuntimeRunRecord.updated_at)}</strong></p>
          </div>
        </article>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong><Database size={15} />正式记忆库</strong><span>{formalOverview?.record_count ?? 0} records</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>仓库</span><strong>{formalOverview?.repository_count ?? 0}</strong></div>
            <div className="boundary-readiness"><span>集合</span><strong>{formalOverview?.collection_count ?? 0}</strong></div>
            <div className="boundary-readiness"><span>记录</span><strong>{formalOverview?.record_count ?? 0}</strong></div>
            <div className="boundary-readiness"><span>版本</span><strong>{formalOverview?.version_count ?? 0}</strong></div>
            <div className="boundary-readiness"><span>读取日志</span><strong>{formalOverview?.read_log_count ?? 0}</strong></div>
          </div>
          <div className="boundary-list boundary-list--scroll">
            {(formalOverview?.records ?? []).slice(0, 8).map((record) => (
              <article className="boundary-list-row boundary-list-row--stacked" key={record.record_id}>
                <div>
                  <strong>{record.record_key || record.record_id}</strong>
                  <span className={statusBadgeClass(record.status)}>{taskSystemOptionLabel(record.status || "unknown")}</span>
                </div>
                <span>{record.repository_id} / {record.collection_id}</span>
                <span>{record.record_kind || "record"} · head {record.head_version_id || "-"} · 更新 {record.updated_at || "-"}</span>
              </article>
            ))}
            {!(formalOverview?.records ?? []).length ? (
              <div className="boundary-empty">当前筛选下没有正式记忆记录。</div>
            ) : null}
          </div>
        </article>
        <article className="boundary-card">
          <header><strong><FileStack size={15} />产物库</strong><span>{artifactOverview?.artifact_count ?? 0} artifacts</span></header>
          <div className="boundary-metric-grid">
            <div className="boundary-readiness"><span>仓库</span><strong>{artifactOverview?.repository_count ?? 0}</strong></div>
            <div className="boundary-readiness"><span>产物</span><strong>{artifactOverview?.artifact_count ?? 0}</strong></div>
            {Object.entries(artifactStatusCounts).slice(0, 4).map(([status, count]) => (
              <div className="boundary-readiness" key={status}><span>{taskSystemOptionLabel(status)}</span><strong>{count}</strong></div>
            ))}
          </div>
          <div className="boundary-list boundary-list--scroll">
            {(artifactOverview?.artifacts ?? []).slice(0, 8).map((artifact) => (
              <article className="boundary-list-row boundary-list-row--stacked" key={artifact.artifact_id}>
                <div>
                  <strong>{artifact.artifact_ref || artifact.artifact_id}</strong>
                  <span className={statusBadgeClass(artifact.status)}>{taskSystemOptionLabel(artifact.status || "unknown")}</span>
                </div>
                <span>{artifact.repository_id} / {artifact.collection_id}</span>
                <span>{artifact.path || "未记录路径"}</span>
              </article>
            ))}
            {!(artifactOverview?.artifacts ?? []).length ? (
              <div className="boundary-empty">当前筛选下没有产物记录。</div>
            ) : null}
          </div>
        </article>
      </section>
      <section className="boundary-card">
        <header><strong><ClipboardList size={15} />运行库边界</strong><span>这里只查看运行结果</span></header>
        <div className="boundary-kv">
          <p><span>正式记忆库配置</span><strong>图工作台 / 资源流 / 记忆仓库节点与 memory_* 边</strong></p>
          <p><span>产物库配置</span><strong>图工作台 / 资源流 / 产物仓库节点与 artifact_* 边</strong></p>
          <p><span>Agent 接收范围</span><strong>编排资源 / 运行档案</strong></p>
          <p><span>运行查看</span><strong>运行管理 / 常驻监控窗 / 发布运行页</strong></p>
        </div>
      </section>
    </TaskRuntimeManagementPage>
  );
}
