"use client";

import { Boxes, CheckCircle2, FileWarning, GitBranch, Loader2, Network, RefreshCw } from "lucide-react";

import type { TaskGraphContractPreview } from "@/lib/api";

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
      ?? recordValue(runtimeRef, "graph_harness_config_id")
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

function findTraceForFocus(preview: TaskGraphContractPreview | null, focus: TaskGraphEditorFocus) {
  const traces = preview?.object_trace_index ?? [];
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
  graphContract,
  graphId,
  loading,
  onCompile,
}: {
  activeLayer: TaskGraphStudioLayerId;
  dirty: boolean;
  editorFocus: TaskGraphEditorFocus;
  error?: string;
  graphContract: TaskGraphContractPreview | null;
  graphId: string;
  loading: boolean;
  onCompile: () => void;
}) {
  const trace = findTraceForFocus(graphContract, editorFocus);
  const scheduler = graphContract?.scheduler_view;
  const compositionCount = Number(graphContract?.summary?.composition_source_count ?? graphContract?.composition_sources?.length ?? 0);
  const splitPlanCount = Number(graphContract?.summary?.split_plan_count ?? graphContract?.split_plans?.length ?? 0);
  const dependencyCount = Number(graphContract?.summary?.dependency_edge_count ?? scheduler?.dependency_edges.length ?? 0);
  const executableCount = Number(graphContract?.summary?.executable_node_count ?? scheduler?.executable_node_ids.length ?? 0);
  const traceCount = graphContract?.object_trace_index?.length ?? 0;
  const issueCount = graphContract?.issues.length ?? 0;
  const ready = graphContract?.valid === true;
  const blocked = Boolean(error || graphContract?.valid === false);
  const statusClass = ready
    ? "task-graph-execution-dock__state task-graph-execution-dock__state--ok"
    : blocked
      ? "task-graph-execution-dock__state task-graph-execution-dock__state--danger"
      : "task-graph-execution-dock__state";

  return (
    <section className="task-graph-execution-dock" aria-label="图契约追踪">
      <div className="task-graph-execution-dock__identity">
        <GitBranch aria-hidden="true" size={15} />
        <div>
          <span>图契约追踪</span>
          <strong>{graphContract?.contract_id || graphId || "未选择任务图"}</strong>
          <small>{error || (dirty ? "图已修改，请保存后重新编译图契约。" : `当前层 ${activeLayer} / ${focusTargetLabel(editorFocus)}`)}</small>
        </div>
      </div>
      <div className="task-graph-execution-dock__metrics">
        <span className={statusClass}>{ready ? <CheckCircle2 size={14} /> : <FileWarning size={14} />}{ready ? "契约可运行" : blocked ? "契约待修复" : "未编译"}</span>
        <span><Boxes size={14} />Executable {executableCount}</span>
        <span><Network size={14} />Dependency {dependencyCount}</span>
        <span>Composition {compositionCount}</span>
        <span>Split {splitPlanCount}</span>
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
            <small>编译图契约后可从图对象追到 GraphHarnessConfig / scheduler。</small>
          </>
        )}
      </div>
      <button className="task-graph-execution-dock__compile" disabled={loading || !graphId} onClick={onCompile} type="button">
        {loading ? <Loader2 aria-hidden="true" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
        <span>{loading ? "编译中" : "编译图契约"}</span>
      </button>
    </section>
  );
}
