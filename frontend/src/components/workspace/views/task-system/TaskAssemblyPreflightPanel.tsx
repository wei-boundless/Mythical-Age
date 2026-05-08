"use client";

import { Eye, Loader2, Network, PackageCheck, RefreshCw, Save, Send } from "lucide-react";
import { useMemo, useState } from "react";

import {
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  buildTaskSystemNodeRuntimeAssembly,
  buildTaskSystemWorkflowRuntimeAssembly,
  compileTaskSystemCoordinationContractManifest,
  compileTaskSystemWorkflowContractManifest,
  type ContractManifest,
  type CoordinationGraphSpec,
  type CoordinationTask,
  type RuntimeAssembly,
  type SpecificTaskRecord,
  type TaskSystemOverview,
} from "@/lib/api";

type PreflightLoadState =
  | ""
  | "all"
  | "workflow-manifest"
  | "workflow-assembly"
  | "coordination-manifest"
  | "node-assembly";

function manifestRefCount(manifest: ContractManifest | null) {
  if (!manifest) return 0;
  return manifest.global_contracts.length
    + manifest.workflow_contracts.length
    + manifest.node_contracts.length
    + manifest.edge_handoff_contracts.length
    + manifest.runtime_contracts.length
    + manifest.acceptance_contracts.length;
}

function nodeIdOf(node: Record<string, unknown>, index: number) {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`);
}

function nodeTitle(node: Record<string, unknown>, index: number) {
  return String(node.title ?? node.label ?? node.task_title ?? nodeIdOf(node, index));
}

function agentLabel(agentId: string, a2aCatalog: TaskSystemOverview["coordination_management"]["a2a"] | null | undefined) {
  const agent = a2aCatalog?.agent_cards?.find((item) => String(item.agent_id ?? "") === agentId);
  const name = String(agent?.agent_name ?? agent?.display_name ?? "").trim();
  return name ? `${name} · ${agentId}` : agentId || "未绑定 Agent";
}

function jsonPreview(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export function TaskAssemblyPreflightPanel({
  selectedTask,
  selectedCoordination,
  selectedGraphSpec,
  selectedNodeId,
  setSelectedNodeId,
  a2aCatalog,
  editorValid,
  editorIssueCount,
  editorPublished,
  topologyDirty,
  saveTopologyDraftIntoCoordination,
  saveCoordinationStack,
  saving,
  onBackToGraph,
}: {
  selectedTask: SpecificTaskRecord | null;
  selectedCoordination: CoordinationTask | null;
  selectedGraphSpec: CoordinationGraphSpec;
  selectedNodeId: string;
  setSelectedNodeId: (nodeId: string) => void;
  a2aCatalog: TaskSystemOverview["coordination_management"]["a2a"] | null | undefined;
  editorValid: boolean;
  editorIssueCount: number;
  editorPublished: boolean;
  topologyDirty: boolean;
  saveTopologyDraftIntoCoordination: () => void;
  saveCoordinationStack: (published?: boolean) => Promise<void>;
  saving: string;
  onBackToGraph: () => void;
}) {
  const [loading, setLoading] = useState<PreflightLoadState>("");
  const [error, setError] = useState("");
  const [workflowManifest, setWorkflowManifest] = useState<ContractManifest | null>(null);
  const [coordinationManifest, setCoordinationManifest] = useState<ContractManifest | null>(null);
  const [workflowAssembly, setWorkflowAssembly] = useState<RuntimeAssembly | null>(null);
  const [nodeAssembly, setNodeAssembly] = useState<RuntimeAssembly | null>(null);

  const graphNodes = useMemo(() => selectedGraphSpec.nodes ?? [], [selectedGraphSpec.nodes]);
  const currentNodeId = graphNodes.length ? selectedNodeId || nodeIdOf(graphNodes[0], 0) : "";
  const selectedNode = graphNodes.find((node, index) => nodeIdOf(node, index) === currentNodeId) ?? null;
  const graphIssues = selectedGraphSpec.issues ?? [];

  async function runWorkflowManifest() {
    if (!selectedTask?.default_workflow_id || !selectedTask.task_id) return null;
    const payload = await compileTaskSystemWorkflowContractManifest(selectedTask.default_workflow_id, selectedTask.task_id);
    setWorkflowManifest(payload);
    return payload;
  }

  async function runWorkflowAssembly() {
    if (!selectedTask?.default_workflow_id || !selectedTask.task_id) return null;
    const payload = await buildTaskSystemWorkflowRuntimeAssembly(selectedTask.default_workflow_id, selectedTask.task_id);
    setWorkflowAssembly(payload);
    return payload;
  }

  async function runCoordinationManifest() {
    if (!selectedCoordination?.coordination_task_id) return null;
    const payload = await compileTaskSystemCoordinationContractManifest(selectedCoordination.coordination_task_id);
    setCoordinationManifest(payload);
    return payload;
  }

  async function runNodeAssembly() {
    if (!selectedCoordination?.coordination_task_id || !currentNodeId) return null;
    const payload = await buildTaskSystemNodeRuntimeAssembly(selectedCoordination.coordination_task_id, currentNodeId);
    setNodeAssembly(payload);
    return payload;
  }

  async function runAction(state: PreflightLoadState, action: () => Promise<unknown>) {
    setLoading(state);
    setError("");
    try {
      await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "装配预检失败");
    } finally {
      setLoading("");
    }
  }

  async function refreshAll() {
    await runAction("all", async () => {
      await runWorkflowManifest();
      await runWorkflowAssembly();
      await runCoordinationManifest();
      await runNodeAssembly();
    });
  }

  const workflowReady = Boolean(selectedTask?.task_id && selectedTask.default_workflow_id);
  const coordinationReady = Boolean(selectedCoordination?.coordination_task_id);
  const nodeReady = Boolean(coordinationReady && currentNodeId);

  return (
    <section className="boundary-layer-stack task-assembly-preflight">
      <section className="boundary-card boundary-card--summary">
        <header>
          <div className="boundary-identity-stack">
            <span>装配预检 / 通用任务图</span>
            <strong>{selectedCoordination?.title || selectedTask?.task_title || "任务图草稿"}</strong>
            <small>{graphNodes.length} 节点 / {selectedGraphSpec.edges?.length ?? 0} 边</small>
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton onClick={onBackToGraph}><Network size={15} />返回任务图</TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={Boolean(loading)} onClick={() => void refreshAll()}>
              {loading === "all" ? <Loader2 size={15} /> : <RefreshCw size={15} />}刷新预检
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={saveTopologyDraftIntoCoordination}><Save size={15} />保存拓扑</TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "coordination"} onClick={() => { void saveCoordinationStack(false); }}><Save size={15} />保存草稿</TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "coordination" || !editorValid} onClick={() => { void saveCoordinationStack(true); }} variant="primary"><Send size={15} />发布可运行</TaskSystemToolbarButton>
          </div>
        </header>
        {error ? <div className="boundary-alert boundary-alert--error">{error}</div> : null}
        <div className="boundary-metric-grid">
          <ReadinessTile label="图结构" value={editorValid ? "通过" : `${editorIssueCount} 个问题`} ready={editorValid} />
          <ReadinessTile label="拓扑草稿" value={topologyDirty ? "未同步" : "已同步"} ready={!topologyDirty} />
          <ReadinessTile label="单任务装配" value={workflowReady ? "可预检" : "缺 workflow"} ready={workflowReady} />
          <ReadinessTile label="节点装配" value={nodeReady ? currentNodeId : "未选节点"} ready={nodeReady} />
          <ReadinessTile label="发布状态" value={editorPublished ? "已发布" : "草稿"} ready={editorPublished} />
          <ReadinessTile label="A2A 通信" value={`${a2aCatalog?.transport || "JSONRPC"} · ${a2aCatalog?.protocol_version || "0.3.0"}`} ready={Boolean(a2aCatalog?.protocol_locked)} />
        </div>
      </section>

      <section className="task-assembly-preflight__grid">
        <section className="boundary-card">
          <header>
            <strong>编译与装配入口</strong>
            <span>{loading ? "运行中" : "待检查"}</span>
          </header>
          <div className="boundary-actions boundary-actions--wrap">
            <TaskSystemToolbarButton disabled={!workflowReady || Boolean(loading)} onClick={() => void runAction("workflow-manifest", runWorkflowManifest)}>
              {loading === "workflow-manifest" ? <Loader2 size={14} /> : <Eye size={14} />}单任务 Manifest
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!workflowReady || Boolean(loading)} onClick={() => void runAction("workflow-assembly", runWorkflowAssembly)}>
              {loading === "workflow-assembly" ? <Loader2 size={14} /> : <PackageCheck size={14} />}单任务 Assembly
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!coordinationReady || Boolean(loading)} onClick={() => void runAction("coordination-manifest", runCoordinationManifest)}>
              {loading === "coordination-manifest" ? <Loader2 size={14} /> : <Eye size={14} />}协调 Manifest
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!nodeReady || Boolean(loading)} onClick={() => void runAction("node-assembly", runNodeAssembly)}>
              {loading === "node-assembly" ? <Loader2 size={14} /> : <PackageCheck size={14} />}节点 Assembly
            </TaskSystemToolbarButton>
          </div>
          <div className="boundary-kv">
            <p><span>单任务</span><strong>{selectedTask?.task_title || "未选择"}</strong></p>
            <p><span>Workflow</span><strong>{selectedTask?.default_workflow_id || "未绑定"}</strong></p>
            <p><span>协调任务</span><strong>{selectedCoordination?.coordination_task_id || "未选择"}</strong></p>
            <p><span>当前节点</span><strong>{currentNodeId || "未选择"}</strong></p>
            <p><span>Workflow Manifest</span><strong>{workflowManifest ? `${manifestRefCount(workflowManifest)} 引用 / ${workflowManifest.issues.length} 问题` : "未生成"}</strong></p>
            <p><span>Coordination Manifest</span><strong>{coordinationManifest ? `${manifestRefCount(coordinationManifest)} 引用 / ${coordinationManifest.issues.length} 问题` : "未生成"}</strong></p>
            <p><span>单任务 Assembly</span><strong>{workflowAssembly?.assembly_id || "未生成"}</strong></p>
            <p><span>节点 Assembly</span><strong>{nodeAssembly?.assembly_id || "未生成"}</strong></p>
          </div>
        </section>

        <section className="boundary-card">
          <header>
            <strong>节点装配目录</strong>
            <span>{graphNodes.length} 个节点</span>
          </header>
          <div className="boundary-list boundary-list--scroll">
            {graphNodes.map((node, index) => {
              const nodeId = nodeIdOf(node, index);
              const active = nodeId === currentNodeId;
              return (
                <button className={active ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"} key={nodeId} onClick={() => setSelectedNodeId(nodeId)} type="button">
                  <strong>{nodeTitle(node, index)}</strong>
                  <span>{agentLabel(String(node.agent_id ?? ""), a2aCatalog)}</span>
                  <small>{nodeId}</small>
                </button>
              );
            })}
            {!graphNodes.length ? <div className="boundary-empty">当前任务图还没有节点。</div> : null}
          </div>
        </section>
      </section>

      <section className="task-assembly-preflight__grid task-assembly-preflight__grid--wide">
        <section className="boundary-card">
          <header><strong>图结构问题</strong><span>{graphIssues.length}</span></header>
          <div className="boundary-task-table">
            {graphIssues.map((issue, index) => (
              <article key={`${String(issue.code ?? "issue")}-${index}`}>
                <strong>{String(issue.message ?? issue.code ?? "校验问题")}</strong>
                <span>{String(issue.severity ?? "warning")}</span>
                <small>{String(issue.node_id ?? issue.edge_id ?? "")}</small>
              </article>
            ))}
            {!graphIssues.length ? <div className="boundary-empty">图结构暂未发现问题。</div> : null}
          </div>
        </section>

        <section className="boundary-card">
          <header><strong>装配 JSON 快照</strong><span>Manifest / Assembly</span></header>
          <textarea
            className="task-assembly-preflight__json"
            readOnly
            value={jsonPreview({
              workflowManifest,
              workflowAssembly,
              coordinationManifest,
              nodeAssembly,
              selectedNode,
            })}
          />
        </section>
      </section>
    </section>
  );
}

function ReadinessTile({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "已就绪" : "待处理"}</small>
    </article>
  );
}
