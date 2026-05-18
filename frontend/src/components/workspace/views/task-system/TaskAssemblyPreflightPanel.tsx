"use client";

import { Eye, Loader2, Network, PackageCheck, RefreshCw, Save, Send } from "lucide-react";
import { useMemo, useState } from "react";

import {
  TaskSystemToolbarButton,
  taskSystemOptionLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { buildTimelinePreflightIssues } from "@/components/workspace/views/task-system/taskGraphTimeline";
import {
  buildTaskSystemTaskGraphNodeRuntimeAssembly,
  compileTaskSystemTaskGraphContractManifest,
  type ContractManifest,
  type RuntimeAssembly,
  type SpecificTaskRecord,
  type TaskGraphRecord,
  type TaskGraphRuntimeSpec,
  type TaskSystemOverview,
} from "@/lib/api";

type PreflightLoadState =
  | ""
  | "all"
  | "task-graph-manifest"
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

function agentLabel(agentId: string, a2aCatalog: NonNullable<TaskSystemOverview["task_graph_management"]>["a2a"] | null | undefined) {
  const agent = a2aCatalog?.agent_cards?.find((item) => String(item.agent_id ?? "") === agentId);
  const name = String(agent?.agent_name ?? agent?.display_name ?? "").trim();
  return name ? `${name} · ${agentId}` : agentId || "未绑定 Agent";
}

function jsonPreview(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function recordOf(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function boolValue(value: unknown, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === undefined || value === null || value === "") return fallback;
  return String(value).toLowerCase() === "true";
}

function buildDispatchPreflightIssues(nodes: Array<Record<string, unknown>>, edges: Array<Record<string, unknown>>) {
  const issues: Array<{ code: string; message: string; severity: string; node_id?: string; edge_id?: string }> = [];
  const incomingCount = new Map<string, number>();
  const outgoingCount = new Map<string, number>();
  for (const edge of edges) {
    const source = String(edge.source_node_id ?? edge.from ?? edge.source ?? "");
    const target = String(edge.target_node_id ?? edge.to ?? edge.target ?? "");
    if (source) outgoingCount.set(source, (outgoingCount.get(source) ?? 0) + 1);
    if (target) incomingCount.set(target, (incomingCount.get(target) ?? 0) + 1);
  }
  for (const node of nodes) {
    const nodeId = String(node.node_id ?? node.id ?? "");
    const mode = String(node.execution_mode ?? "sync");
    const backgroundPolicy = recordOf(node.background_policy);
    const notificationPolicy = recordOf(node.notification_policy);
    const humanGatePolicy = recordOf(node.human_gate_policy);
    if (mode === "parallel" && !String(node.dispatch_group ?? "").trim()) {
      issues.push({ code: "parallel_node_dispatch_group_missing", message: "并行节点缺少 dispatch_group。", severity: "error", node_id: nodeId });
    }
    if (mode === "background") {
      if (!boolValue(backgroundPolicy.enabled)) {
        issues.push({ code: "background_node_policy_disabled", message: "后台节点必须显式启用 background_policy.enabled。", severity: "error", node_id: nodeId });
      }
      if (Number(backgroundPolicy.max_runtime_seconds ?? 0) <= 0) {
        issues.push({ code: "background_node_timeout_missing", message: "后台节点必须配置 max_runtime_seconds。", severity: "error", node_id: nodeId });
      }
      if (!Object.keys(notificationPolicy).length) {
        issues.push({ code: "background_node_notification_policy_missing", message: "后台节点必须配置 notification_policy。", severity: "error", node_id: nodeId });
      }
    }
    if (mode === "barrier" && (incomingCount.get(nodeId) ?? 0) <= 0) {
      issues.push({ code: "barrier_node_missing_upstream", message: "汇合节点必须存在上游边。", severity: "error", node_id: nodeId });
    }
    if (mode === "manual_gate" && !Object.keys(humanGatePolicy).length) {
      issues.push({ code: "manual_gate_policy_missing", message: "人工门控节点必须配置 human_gate_policy。", severity: "error", node_id: nodeId });
    }
    if (mode === "parallel" && (outgoingCount.get(nodeId) ?? 0) <= 0) {
      issues.push({ code: "parallel_node_join_path_missing", message: "并行节点必须有下游汇合或后续处理路径。", severity: "warning", node_id: nodeId });
    }
  }
  for (const edge of edges) {
    const edgeId = String(edge.edge_id ?? edge.id ?? "");
    if (String(edge.wait_policy ?? "") === "wait_handoff_ack" && !boolValue(edge.ack_required, true)) {
      issues.push({ code: "edge_ack_required_conflict", message: "等待 handoff ack 的边不能关闭 ack_required。", severity: "error", edge_id: edgeId });
    }
    if (String(edge.result_delivery_policy ?? "contract_payload_and_refs") === "contract_payload_and_refs" && !String(edge.payload_contract_id ?? edge.contract_id ?? "").trim()) {
      issues.push({ code: "edge_result_contract_missing", message: "契约载荷投递边必须配置 payload contract。", severity: "error", edge_id: edgeId });
    }
  }
  return issues;
}

export function TaskAssemblyPreflightPanel({
  selectedTask,
  selectedTaskGraph,
  selectedGraphSpec,
  taskGraphMetadata,
  selectedNodeId,
  setSelectedNodeId,
  a2aCatalog,
  editorValid,
  editorIssueCount,
  editorPublished,
  topologyDirty,
  saveTaskGraphStack,
  saving,
  onBackToGraph,
}: {
  selectedTask: SpecificTaskRecord | null;
  selectedTaskGraph: TaskGraphRecord | null;
  selectedGraphSpec: TaskGraphRuntimeSpec;
  taskGraphMetadata?: Record<string, unknown>;
  selectedNodeId: string;
  setSelectedNodeId: (nodeId: string) => void;
  a2aCatalog: NonNullable<TaskSystemOverview["task_graph_management"]>["a2a"] | null | undefined;
  editorValid: boolean;
  editorIssueCount: number;
  editorPublished: boolean;
  topologyDirty: boolean;
  saveTaskGraphStack: (published?: boolean) => Promise<void>;
  saving: string;
  onBackToGraph: () => void;
}) {
  const [loading, setLoading] = useState<PreflightLoadState>("");
  const [error, setError] = useState("");
  const [taskGraphManifest, setTaskGraphManifest] = useState<ContractManifest | null>(null);
  const [nodeAssembly, setNodeAssembly] = useState<RuntimeAssembly | null>(null);

  const graphNodes = useMemo(() => selectedGraphSpec.nodes ?? [], [selectedGraphSpec.nodes]);
  const graphEdges = useMemo(() => selectedGraphSpec.edges ?? [], [selectedGraphSpec.edges]);
  const currentNodeId = graphNodes.length ? selectedNodeId || nodeIdOf(graphNodes[0], 0) : "";
  const selectedNode = graphNodes.find((node, index) => nodeIdOf(node, index) === currentNodeId) ?? null;
  const graphIssues = useMemo(() => selectedGraphSpec.issues ?? [], [selectedGraphSpec.issues]);
  const dispatchIssues = useMemo(() => buildDispatchPreflightIssues(graphNodes, graphEdges), [graphEdges, graphNodes]);
  const timelineIssues = useMemo(() => buildTimelinePreflightIssues(graphNodes, graphEdges, taskGraphMetadata), [taskGraphMetadata, graphEdges, graphNodes]);
  const allPreflightIssues = useMemo(() => [...graphIssues, ...dispatchIssues, ...timelineIssues], [dispatchIssues, graphIssues, timelineIssues]);

  async function runTaskGraphManifest() {
    if (!selectedTaskGraph?.graph_id) return null;
    const payload = await compileTaskSystemTaskGraphContractManifest(selectedTaskGraph.graph_id);
    setTaskGraphManifest(payload);
    return payload;
  }

  async function runNodeAssembly() {
    if (!selectedTaskGraph?.graph_id || !currentNodeId) return null;
    const payload = await buildTaskSystemTaskGraphNodeRuntimeAssembly(selectedTaskGraph.graph_id, currentNodeId);
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
      await runTaskGraphManifest();
      await runNodeAssembly();
    });
  }

  const taskGraphReady = Boolean(selectedTaskGraph?.graph_id);
  const nodeReady = Boolean(taskGraphReady && currentNodeId);
  const graphTaskRefs = Array.isArray(selectedGraphSpec.subtask_refs) ? selectedGraphSpec.subtask_refs : [];

  return (
    <section className="boundary-layer-stack task-assembly-preflight">
      <section className="boundary-card boundary-card--summary">
        <header>
          <div className="boundary-identity-stack">
            <span>装配预检 / 通用任务图</span>
            <strong>{selectedTaskGraph?.title || selectedTask?.task_title || "任务图草稿"}</strong>
            <small>{graphNodes.length} 节点 / {graphEdges.length} 边</small>
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton onClick={onBackToGraph}><Network size={15} />返回任务图</TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={Boolean(loading)} onClick={() => void refreshAll()}>
              {loading === "all" ? <Loader2 size={15} /> : <RefreshCw size={15} />}刷新预检
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "task-graph"} onClick={() => { void saveTaskGraphStack(false); }}><Save size={15} />保存草稿</TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "task-graph" || !editorValid} onClick={() => { void saveTaskGraphStack(true); }} variant="primary"><Send size={15} />发布可运行</TaskSystemToolbarButton>
          </div>
        </header>
        {error ? <div className="boundary-alert boundary-alert--error">{error}</div> : null}
        <div className="boundary-metric-grid">
          <ReadinessTile label="图结构" value={editorValid ? "通过" : `${editorIssueCount} 个问题`} ready={editorValid} />
          <ReadinessTile label="调度策略" value={dispatchIssues.length ? `${dispatchIssues.length} 个问题` : "通过"} ready={!dispatchIssues.length} />
          <ReadinessTile label="时序编排" value={timelineIssues.length ? `${timelineIssues.length} 个问题` : "通过"} ready={!timelineIssues.some((issue) => issue.severity === "error")} />
          <ReadinessTile label="拓扑草稿" value={topologyDirty ? "未同步" : "已同步"} ready={!topologyDirty} />
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
            <TaskSystemToolbarButton disabled={!taskGraphReady || Boolean(loading)} onClick={() => void runAction("task-graph-manifest", runTaskGraphManifest)}>
              {loading === "task-graph-manifest" ? <Loader2 size={14} /> : <Eye size={14} />}任务图清单
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={!nodeReady || Boolean(loading)} onClick={() => void runAction("node-assembly", runNodeAssembly)}>
              {loading === "node-assembly" ? <Loader2 size={14} /> : <PackageCheck size={14} />}节点装配
            </TaskSystemToolbarButton>
          </div>
          <div className="boundary-kv">
            <p><span>引用任务定义</span><strong>{graphTaskRefs.length ? graphTaskRefs.join(" / ") : selectedTask?.task_title || "无"}</strong></p>
            <p><span>任务图</span><strong>{selectedTaskGraph?.graph_id || "未选择"}</strong></p>
            <p><span>当前节点</span><strong>{currentNodeId || "未选择"}</strong></p>
            <p><span>任务图契约清单</span><strong>{taskGraphManifest ? `${manifestRefCount(taskGraphManifest)} 引用 / ${taskGraphManifest.issues.length} 问题` : "未生成"}</strong></p>
            <p><span>节点装配</span><strong>{nodeAssembly?.assembly_id || "未生成"}</strong></p>
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
          <header><strong>预检问题</strong><span>{allPreflightIssues.length}</span></header>
          <div className="boundary-task-table">
            {allPreflightIssues.map((issue, index) => (
              <article key={`${String(issue.code ?? "issue")}-${index}`}>
                <strong>{String(issue.message ?? issue.code ?? "校验问题")}</strong>
                <span>{taskSystemOptionLabel(String(issue.severity ?? "warning"))}</span>
                <small>{String(issue.node_id ?? issue.edge_id ?? "")}</small>
              </article>
            ))}
            {!allPreflightIssues.length ? <div className="boundary-empty">调度与图结构暂未发现问题。</div> : null}
          </div>
        </section>

        <section className="boundary-card">
          <header><strong>装配 JSON 快照</strong><span>清单 / 装配</span></header>
          <textarea
            className="task-assembly-preflight__json"
            readOnly
            value={jsonPreview({
              taskGraphManifest,
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
