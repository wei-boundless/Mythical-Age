"use client";

import { Boxes, CheckCircle2, FileWarning, GitBranch, Loader2, Network, RefreshCw } from "lucide-react";

import type { TaskGraphExecutionPackage } from "@/lib/api";

import { focusTargetLabel, type TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";

function recordValue(record: Record<string, unknown> | null | undefined, key: string) {
  return record && typeof record === "object" ? record[key] : undefined;
}

function traceObjectId(item: Record<string, unknown>) {
  return String(recordValue(item, "object_id") ?? recordValue(item, "source_id") ?? "").trim();
}

function traceObjectType(item: Record<string, unknown>) {
  return String(recordValue(item, "object_type") ?? recordValue(item, "source_type") ?? "object").trim();
}

function traceRuntimeLabel(item: Record<string, unknown>) {
  const runtimeRef = recordValue(item, "runtime_ref") as Record<string, unknown> | null | undefined;
  const manifestRef = recordValue(item, "manifest_ref") as Record<string, unknown> | null | undefined;
  const schedulerRef = recordValue(item, "scheduler_ref") as Record<string, unknown> | null | undefined;
  const runtimeId = String(
    recordValue(runtimeRef, "node_id")
      ?? recordValue(runtimeRef, "edge_id")
      ?? recordValue(runtimeRef, "runtime_node_id")
      ?? recordValue(runtimeRef, "runtime_spec_graph_id")
      ?? "-",
  );
  const manifestId = String(
    recordValue(manifestRef, "node_contract_id")
      ?? recordValue(manifestRef, "edge_contract_id")
      ?? recordValue(manifestRef, "handoff_contract_id")
      ?? recordValue(manifestRef, "manifest_id")
      ?? "-",
  );
  const schedulerStatus = String(recordValue(schedulerRef, "status") ?? recordValue(item, "status") ?? "-");
  return `runtime ${runtimeId} / manifest ${manifestId} / scheduler ${schedulerStatus}`;
}

function targetIdsFromFocus(focus: TaskGraphEditorFocus) {
  return [
    focus.node_id,
    focus.edge_id,
    focus.repository_id,
    focus.collection_id,
    focus.issue_id,
  ].map((item) => String(item ?? "").trim()).filter(Boolean);
}

function findTraceForFocus(executionPackage: TaskGraphExecutionPackage | null, focus: TaskGraphEditorFocus) {
  const traces = executionPackage?.object_trace_index ?? [];
  const ids = targetIdsFromFocus(focus);
  if (!ids.length) {
    return traces.find((item) => traceObjectType(item) === "graph") ?? traces[0] ?? null;
  }
  return traces.find((item) => ids.includes(traceObjectId(item))) ?? null;
}

export function TaskGraphExecutionDock({
  activeLayer,
  dirty,
  editorFocus,
  error,
  executionPackage,
  graphId,
  loading,
  onCompile,
}: {
  activeLayer: TaskGraphStudioLayerId;
  dirty: boolean;
  editorFocus: TaskGraphEditorFocus;
  error?: string;
  executionPackage: TaskGraphExecutionPackage | null;
  graphId: string;
  loading: boolean;
  onCompile: () => void;
}) {
  const trace = findTraceForFocus(executionPackage, editorFocus);
  const graphUnitCount = executionPackage?.graph_units.length ?? 0;
  const splitPlanCount = Number(executionPackage?.summary?.split_plan_count ?? executionPackage?.split_plans?.length ?? 0);
  const splitLifecycleCount = Number(executionPackage?.summary?.split_batch_lifecycle_plan_count ?? 0);
  const assemblyCount = executionPackage?.node_runtime_assemblies.length ?? 0;
  const traceCount = executionPackage?.object_trace_index?.length ?? 0;
  const issueCount = executionPackage?.issues.length ?? 0;
  const ready = executionPackage?.valid === true;
  const blocked = Boolean(error || executionPackage?.valid === false);
  const statusClass = ready
    ? "task-graph-execution-dock__state task-graph-execution-dock__state--ok"
    : blocked
      ? "task-graph-execution-dock__state task-graph-execution-dock__state--danger"
      : "task-graph-execution-dock__state";

  return (
    <section className="task-graph-execution-dock" aria-label="执行包追踪">
      <div className="task-graph-execution-dock__identity">
        <GitBranch aria-hidden="true" size={15} />
        <div>
          <span>执行包追踪</span>
          <strong>{executionPackage?.package_id || graphId || "未选择任务图"}</strong>
          <small>{error || (dirty ? "图已修改，请保存后重新编译执行包。" : `当前层 ${activeLayer} / ${focusTargetLabel(editorFocus)}`)}</small>
        </div>
      </div>
      <div className="task-graph-execution-dock__metrics">
        <span className={statusClass}>{ready ? <CheckCircle2 size={14} /> : <FileWarning size={14} />}{ready ? "执行包通过" : blocked ? "执行包待修复" : "未编译"}</span>
        <span><Boxes size={14} />Assembly {assemblyCount}</span>
        <span><Network size={14} />GraphUnit {graphUnitCount}</span>
        <span>Split {splitPlanCount}</span>
        <span>Lifecycle {splitLifecycleCount}</span>
        <span>Trace {traceCount}</span>
        <span>Issues {issueCount}</span>
      </div>
      <div className="task-graph-execution-dock__trace">
        {trace ? (
          <>
            <span>{traceObjectType(trace)}</span>
            <strong>{String(recordValue(trace, "title") ?? traceObjectId(trace) ?? "当前对象")}</strong>
            <small>{traceRuntimeLabel(trace)}</small>
          </>
        ) : (
          <>
            <span>object trace</span>
            <strong>尚无当前对象追溯</strong>
            <small>编译执行包后可从图对象追到 runtime / manifest / scheduler。</small>
          </>
        )}
      </div>
      <button className="task-graph-execution-dock__compile" disabled={loading || !graphId} onClick={onCompile} type="button">
        {loading ? <Loader2 aria-hidden="true" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
        <span>{loading ? "编译中" : "编译执行包"}</span>
      </button>
    </section>
  );
}
