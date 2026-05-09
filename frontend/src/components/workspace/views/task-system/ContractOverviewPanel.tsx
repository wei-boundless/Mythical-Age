"use client";

import { Eye, Loader2, PackageCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { TaskSystemToolbarButton, taskSystemOptionLabel } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  buildTaskSystemTaskGraphNodeRuntimeAssembly,
  buildTaskSystemWorkflowRuntimeAssembly,
  compileTaskSystemTaskGraphContractManifest,
  compileTaskSystemWorkflowContractManifest,
  type ContractManifest,
  type ContractSpec,
  type RuntimeAssembly,
  type SpecificTaskRecord,
  type TaskGraphRecord,
} from "@/lib/api";

function kindLabel(value: string) {
  const labels: Record<string, string> = {
    global_task: "全局任务",
    workflow: "单任务工作流",
    workflow_step: "工作流步骤",
    node_execution: "节点执行",
    edge_handoff: "边交接",
    final_output: "最终输出",
    acceptance: "验收",
    runtime: "运行",
    failure: "失败",
    human_gate: "人工门控",
  };
  return labels[value] ?? taskSystemOptionLabel(value);
}

function refCount(manifest: ContractManifest | null) {
  if (!manifest) return 0;
  return manifest.global_contracts.length
    + manifest.workflow_contracts.length
    + manifest.node_contracts.length
    + manifest.edge_handoff_contracts.length
    + manifest.runtime_contracts.length
    + manifest.acceptance_contracts.length;
}

export function ContractOverviewPanel({
  contractSpecs,
  selectedTask,
  selectedCoordination,
  selectedNodeId,
}: {
  contractSpecs: ContractSpec[];
  selectedTask: SpecificTaskRecord | null;
  selectedCoordination: TaskGraphRecord | null;
  selectedNodeId: string;
}) {
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [workflowManifest, setWorkflowManifest] = useState<ContractManifest | null>(null);
  const [coordinationManifest, setCoordinationManifest] = useState<ContractManifest | null>(null);
  const [assembly, setAssembly] = useState<RuntimeAssembly | null>(null);

  const byKind = useMemo(() => {
    const counts = new Map<string, number>();
    contractSpecs.forEach((spec) => counts.set(spec.contract_kind, (counts.get(spec.contract_kind) ?? 0) + 1));
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [contractSpecs]);

  async function previewWorkflowManifest() {
    if (!selectedTask?.default_workflow_id || !selectedTask.task_id) return;
    setLoading("workflow-manifest");
    setError("");
    try {
      setWorkflowManifest(await compileTaskSystemWorkflowContractManifest(selectedTask.default_workflow_id, selectedTask.task_id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Workflow 契约预检失败");
    } finally {
      setLoading("");
    }
  }

  async function previewWorkflowAssembly() {
    if (!selectedTask?.default_workflow_id || !selectedTask.task_id) return;
    setLoading("workflow-assembly");
    setError("");
    try {
      setAssembly(await buildTaskSystemWorkflowRuntimeAssembly(selectedTask.default_workflow_id, selectedTask.task_id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Workflow RuntimeAssembly 预览失败");
    } finally {
      setLoading("");
    }
  }

  async function previewCoordinationManifest() {
    if (!selectedCoordination?.graph_id) return;
    setLoading("coordination-manifest");
    setError("");
    try {
      setCoordinationManifest(await compileTaskSystemTaskGraphContractManifest(selectedCoordination.graph_id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务图契约预检失败");
    } finally {
      setLoading("");
    }
  }

  async function previewNodeAssembly() {
    if (!selectedCoordination?.graph_id || !selectedNodeId) return;
    setLoading("node-assembly");
    setError("");
    try {
      setAssembly(await buildTaskSystemTaskGraphNodeRuntimeAssembly(selectedCoordination.graph_id, selectedNodeId));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "节点 RuntimeAssembly 预览失败");
    } finally {
      setLoading("");
    }
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>契约汇总</strong>
          <span>{contractSpecs.length} 个契约规格</span>
        </header>
        <div className="boundary-metric-grid">
          {byKind.map(([kind, count]) => (
            <article className="boundary-readiness boundary-readiness--ready" key={kind}>
              <span>{kindLabel(kind)}</span>
              <strong>{count}</strong>
              <small>已归类</small>
            </article>
          ))}
          {!byKind.length ? <div className="boundary-empty">契约库为空，先到契约库建立通用契约规格。</div> : null}
        </div>
        <div className="boundary-task-table">
          {contractSpecs.slice(0, 10).map((spec) => (
            <article key={spec.contract_id}>
              <strong>{contractSpecTitle(spec)}</strong>
              <span>{kindLabel(spec.contract_kind)}</span>
            </article>
          ))}
        </div>
      </div>

      <aside className="boundary-card">
        <header><strong>运行前预检</strong></header>
        {error ? <div className="boundary-alert boundary-alert--error">{error}</div> : null}
        <div className="boundary-actions">
          <TaskSystemToolbarButton disabled={!selectedTask || Boolean(loading)} onClick={() => void previewWorkflowManifest()}>
            {loading === "workflow-manifest" ? <Loader2 size={14} /> : <Eye size={14} />}单任务清单
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!selectedTask || Boolean(loading)} onClick={() => void previewWorkflowAssembly()}>
            {loading === "workflow-assembly" ? <Loader2 size={14} /> : <PackageCheck size={14} />}单任务装配
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!selectedCoordination || Boolean(loading)} onClick={() => void previewCoordinationManifest()}>
            {loading === "coordination-manifest" ? <Loader2 size={14} /> : <Eye size={14} />}任务图清单
          </TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={!selectedCoordination || !selectedNodeId || Boolean(loading)} onClick={() => void previewNodeAssembly()}>
            {loading === "node-assembly" ? <Loader2 size={14} /> : <PackageCheck size={14} />}节点装配
          </TaskSystemToolbarButton>
        </div>
        <div className="boundary-kv">
          <p><span>单任务</span><strong>{selectedTask?.task_title || "未选择"}</strong></p>
          <p><span>任务图</span><strong>{selectedCoordination?.title || "未选择"}</strong></p>
          <p><span>选中节点</span><strong>{selectedNodeId || "未选择"}</strong></p>
          <p><span>单任务契约清单</span><strong>{workflowManifest ? `${refCount(workflowManifest)} 引用 / ${workflowManifest.issues.length} 问题` : "未生成"}</strong></p>
          <p><span>任务图契约清单</span><strong>{coordinationManifest ? `${refCount(coordinationManifest)} 引用 / ${coordinationManifest.issues.length} 问题` : "未生成"}</strong></p>
          <p><span>运行装配</span><strong>{assembly?.assembly_id || "未生成"}</strong></p>
        </div>
      </aside>

      <aside className="boundary-card">
        <header><strong>预览详情</strong></header>
        <textarea
          readOnly
          value={JSON.stringify({ workflowManifest, coordinationManifest, assembly }, null, 2)}
        />
      </aside>
    </section>
  );
}
