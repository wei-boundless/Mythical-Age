"use client";

import { useMemo, useState } from "react";
import {
  ArrowRightLeft,
  GitBranch,
  Link2,
  MousePointer2,
  Plus,
  Route,
  Trash2,
  UserPlus,
} from "lucide-react";

import { CoordinationTopologyGraph as TaskGraphTopologyCanvas } from "@/components/coordination/CoordinationTopologyGraph";

import { graphEdgeSource, graphEdgeTarget, isTaskGraphPublishedState } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { buildTaskGraphMemoryModel } from "./taskGraphMemoryMatrix";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

type TaskGraphTopologyPageProps = Pick<
  TaskGraphWorkbenchProps,
  | "activeGraphEdges"
  | "activeGraphNodes"
  | "addTaskGraphNode"
  | "addTaskGraphRoleNode"
  | "addTaskGraphSuccessorNode"
  | "addTaskGraphTaskNode"
  | "handleTopologyNodeClick"
  | "linkingFromNodeId"
  | "removeTaskGraphEdge"
  | "removeTaskGraphNode"
  | "reverseTaskGraphEdge"
  | "selectedDomainTasks"
  | "selectedGraphEdge"
  | "selectedGraphEdgeId"
  | "selectedGraphNode"
  | "selectedGraphNodeId"
  | "setLinkingFromNodeId"
  | "setSelectedGraphEdgeId"
  | "setSelectedGraphNodeId"
  | "taskGraphDraftV2"
> & {
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  onOpenMemoryLayer?: () => void;
};

type EdgeFlowFilter = "all" | "execution" | "memory" | "artifact" | "revision";

const ROLE_QUICK_ADDS = [
  { role: "coordinator", label: "协调器" },
  { role: "executor", label: "执行节点" },
  { role: "reviewer", label: "审核节点" },
];

const RESOURCE_QUICK_ADDS = [
  { role: "memory_repository", label: "记忆库" },
  { role: "artifact_repository", label: "产物库" },
  { role: "thread_ledger", label: "线程账本" },
  { role: "issue_ledger", label: "问题台账" },
];

const EDGE_FLOW_FILTERS: Array<{ id: EdgeFlowFilter; title: string; description: string }> = [
  { id: "all", title: "全部", description: "所有结构边" },
  { id: "execution", title: "执行流", description: "控制与交接" },
  { id: "memory", title: "记忆流", description: "read/write/commit" },
  { id: "artifact", title: "产物流", description: "artifact context" },
  { id: "revision", title: "返修流", description: "review/revision" },
];

function nodeIdOf(node: Record<string, unknown>, index: number) {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
}

function edgeIdOf(edge: Record<string, unknown>, index: number) {
  const fallback = graphEdgeSource(edge) && graphEdgeTarget(edge)
    ? `${graphEdgeSource(edge)}->${graphEdgeTarget(edge)}`
    : `edge_${index + 1}`;
  return String(edge.edge_id ?? edge.id ?? fallback).trim();
}

function titleOfNode(node: Record<string, unknown>, index: number) {
  return String(node.title ?? node.label ?? node.task_title ?? nodeIdOf(node, index)).trim();
}

function labelOfEdge(edge: Record<string, unknown>) {
  const edgeType = String(edge.edge_type ?? edge.mode ?? "").trim();
  const labels: Record<string, string> = {
    memory_read: "读",
    memory_write_candidate: "写候选",
    memory_write: "写候选",
    memory_commit: "提交",
    memory_handoff: "记忆交接",
  };
  return String(edge.label ?? labels[edgeType] ?? edgeType ?? "handoff").trim();
}

function topologyNodeKind(node: Record<string, unknown>) {
  const nodeType = String(node.node_type ?? "").trim();
  const role = String(node.role ?? "").trim();
  const executionMode = String(node.execution_mode ?? "").trim();
  if (nodeType === "review_gate" || String(node.review_gate_policy ?? "") === "review_gate" || role === "review_gate") return "review_gate";
  if (nodeType === "loop" || nodeType === "loop_controller" || Object.keys(asRecord(node.loop_policy)).length > 0) return "loop";
  if (executionMode === "manual_gate" || nodeType === "manual_gate" || role === "manual_gate") return "manual_gate";
  if (
    role === "memory"
    || nodeType === "memory_repository"
    || nodeType === "memory_resource"
    || nodeType === "working_memory_store"
    || nodeType === "thread_ledger"
    || nodeType === "progress_ledger"
    || nodeType === "issue_ledger"
    || String(node.node_id ?? "").startsWith("memory.")
  ) {
    return "memory";
  }
  if (nodeType === "artifact_repository") return "artifact";
  if (nodeType === "thread_ledger" || nodeType === "progress_ledger" || nodeType === "issue_ledger") return "ledger";
  return nodeType || "executor";
}

function isResourceNode(node: Record<string, unknown> | null) {
  const nodeType = String(node?.node_type ?? "");
  return ["memory_repository", "artifact_repository", "thread_ledger", "progress_ledger", "issue_ledger", "working_memory_store", "memory_resource"].includes(nodeType)
    || String(node?.work_posture ?? "") === "resource";
}

function selectedNodeTitle(node: Record<string, unknown> | null) {
  if (!node) return "未选择";
  return String(node.title ?? node.label ?? node.task_title ?? node.node_id ?? "").trim() || "未命名节点";
}

function selectedEdgeTitle(edge: Record<string, unknown> | null) {
  if (!edge) return "未选择";
  const source = graphEdgeSource(edge);
  const target = graphEdgeTarget(edge);
  return source && target ? `${source} -> ${target}` : String(edge.edge_id ?? edge.id ?? "边");
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function edgeFlowKind(edge: Record<string, unknown>): EdgeFlowFilter {
  const edgeType = String(edge.edge_type ?? edge.mode ?? "").trim();
  const metadata = asRecord(edge.metadata);
  if (edgeType.startsWith("memory_")) return "memory";
  if (edgeType.startsWith("artifact_") || Object.keys(asRecord(edge.artifact_ref_policy)).length > 0 || String(metadata.context_mode ?? "").includes("artifact")) return "artifact";
  if (["revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"].includes(edgeType) || String(metadata.verdict ?? "") === "revise") return "revision";
  return "execution";
}

function topologyEdgeKind(edge: Record<string, unknown>) {
  const edgeType = String(edge.edge_type ?? edge.mode ?? "").trim();
  if (edgeType === "memory_read") return "memory_read";
  if (edgeType === "memory_write_candidate" || edgeType === "memory_write") return "memory_write_candidate";
  if (edgeType === "memory_commit") return "memory_commit";
  if (edgeType.startsWith("artifact_") || Object.keys(asRecord(edge.artifact_ref_policy)).length > 0) return "artifact_context";
  if (edgeFlowKind(edge) === "revision") return "revision_request";
  if (edgeType === "control" || edgeType === "control_flow") return "control_flow";
  return "handoff";
}

function nodeKindLabel(kind: string) {
  const labels: Record<string, string> = {
    executor: "执行节点",
    review_gate: "审核门",
    loop: "循环控制",
    manual_gate: "人工门控",
    memory: "记忆仓库",
    artifact: "产物仓库",
    ledger: "账本",
  };
  return labels[kind] ?? kind;
}

function selectedEdgeControlSummary(edge: Record<string, unknown> | null) {
  if (!edge) return "";
  const edgeType = String(edge.edge_type ?? edge.mode ?? "").trim();
  const metadata = asRecord(edge.metadata);
  if (edgeType === "memory_read") return "资源读取边：把仓库记录装配进目标节点输入包，不直接激活下游执行节点。";
  if (edgeType === "memory_write_candidate" || edgeType === "memory_write") return "候选写入边：源节点产出候选版本，是否可见取决于后续提交边。";
  if (edgeType === "memory_commit") return "提交边：把候选版本转为已提交记录，并按提交可见性进入后续节点。";
  if (edgeType.startsWith("artifact_") || Object.keys(asRecord(edge.artifact_ref_policy)).length > 0) return "产物上下文边：传递产物引用或展开策略，不替代控制流。";
  if (["revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"].includes(edgeType) || String(metadata.verdict ?? "") === "revise") return "返修边：把审核结论和原始产物交回指定节点，形成受控回退。";
  if (edgeType === "temporal_dependency" || String(metadata.dependency_role ?? "").includes("temporal")) return "显式时序边：补充拓扑因果约束，由编译器纳入执行许可判断。";
  return "交接边：把上游契约化输出交给下游节点，是否阻塞由 wait/join 策略决定。";
}

export function TaskGraphTopologyPage({
  activeGraphEdges,
  activeGraphNodes,
  addTaskGraphNode,
  addTaskGraphRoleNode,
  addTaskGraphSuccessorNode,
  addTaskGraphTaskNode,
  editorFocus,
  handleTopologyNodeClick,
  linkingFromNodeId,
  onEditorFocus,
  removeTaskGraphEdge,
  removeTaskGraphNode,
  reverseTaskGraphEdge,
  selectedDomainTasks,
  selectedGraphEdge,
  selectedGraphEdgeId,
  selectedGraphNode,
  selectedGraphNodeId,
  setLinkingFromNodeId,
  setSelectedGraphEdgeId,
  setSelectedGraphNodeId,
  taskGraphDraftV2,
  onOpenMemoryLayer,
}: TaskGraphTopologyPageProps) {
  const [edgeFlowFilter, setEdgeFlowFilter] = useState<EdgeFlowFilter>("all");
  const published = isTaskGraphPublishedState(taskGraphDraftV2.publish_state);
  const graphMetadata = asRecord(taskGraphDraftV2.metadata);
  const memoryModel = useMemo(
    () => buildTaskGraphMemoryModel({ nodes: activeGraphNodes, edges: activeGraphEdges }),
    [activeGraphNodes, activeGraphEdges],
  );
  const graphNodes = activeGraphNodes.map((node, index) => {
    const nodeId = nodeIdOf(node, index);
    return {
      id: nodeId,
      title: taskGraphDisplayName(nodeId, node, graphMetadata, titleOfNode(node, index)),
      agentLabel: String(node.role ?? node.node_type ?? "").trim(),
      role: String(node.role ?? "").trim(),
      nodeKind: topologyNodeKind(node),
      status: nodeId === taskGraphDraftV2.entry_node_id ? "ready" : nodeId === taskGraphDraftV2.output_node_id ? "waiting" : "idle",
    };
  });
  const visibleGraphEdges = activeGraphEdges
    .map((edge, index) => ({ edge, index }))
    .filter(({ edge }) => edgeFlowFilter === "all" || edgeFlowKind(edge) === edgeFlowFilter);
  const graphEdges = visibleGraphEdges.map(({ edge, index }) => ({
    id: edgeIdOf(edge, index),
    from: graphEdgeSource(edge),
    to: graphEdgeTarget(edge),
    label: labelOfEdge(edge),
    edgeKind: topologyEdgeKind(edge),
    status: "idle",
  })).filter((edge) => edge.from && edge.to);
  const selectedNodeId = String(selectedGraphNode?.node_id ?? selectedGraphNodeId ?? "");
  const selectedEdgeId = selectedGraphEdgeId;
  const selectedNodeCanMutate = Boolean(selectedNodeId && !published);
  const selectedEdgeCanMutate = Boolean(selectedEdgeId && !published);
  const selectedNodeKind = selectedGraphNode ? topologyNodeKind(selectedGraphNode) : "";
  const selectedEdgeKind = selectedGraphEdge ? topologyEdgeKind(selectedGraphEdge) : "";
  const selectedEdgeFlow = selectedGraphEdge ? edgeFlowKind(selectedGraphEdge) : "";
  const incomingSelectedEdgeCount = selectedNodeId ? activeGraphEdges.filter((edge) => graphEdgeTarget(edge) === selectedNodeId).length : 0;
  const outgoingSelectedEdgeCount = selectedNodeId ? activeGraphEdges.filter((edge) => graphEdgeSource(edge) === selectedNodeId).length : 0;
  const selectedRepository = selectedNodeId ? memoryModel.repositories.find((repository) => repository.nodeId === selectedNodeId) ?? null : null;
  const selectedRepositoryReadCount = selectedRepository ? memoryModel.memoryEdges.filter((edge) => edge.repositoryNodeId === selectedRepository.nodeId && edge.operation === "read").length : 0;
  const selectedRepositoryWriteCount = selectedRepository ? memoryModel.memoryEdges.filter((edge) => edge.repositoryNodeId === selectedRepository.nodeId && edge.operation === "write_candidate").length : 0;
  const selectedRepositoryCommitCount = selectedRepository ? memoryModel.memoryEdges.filter((edge) => edge.repositoryNodeId === selectedRepository.nodeId && edge.operation === "commit").length : 0;
  const selectedEdgeSummary = selectedEdgeControlSummary(selectedGraphEdge);

  return (
    <section className="task-graph-topology-page" aria-label="TaskGraph 拓扑编排">
      <aside className="task-graph-topology-rail" aria-label="拓扑结构工具">
        <section className="task-graph-topology-panel">
          <header className="task-graph-topology-panel__head">
            <GitBranch size={16} />
            <strong>结构</strong>
          </header>
          <div className="task-graph-topology-actions">
            <button disabled={published} onClick={addTaskGraphNode} type="button">
              <Plus size={15} />
              <span>节点</span>
            </button>
            {ROLE_QUICK_ADDS.map((item) => (
              <button disabled={published} key={item.role} onClick={() => addTaskGraphRoleNode(item.role)} type="button">
                <UserPlus size={15} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>
          <span className="task-graph-topology-action-label">资源节点</span>
          <div className="task-graph-topology-actions">
            {RESOURCE_QUICK_ADDS.map((item) => (
              <button disabled={published} key={item.role} onClick={() => addTaskGraphRoleNode(item.role)} type="button">
                <Plus size={15} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="task-graph-topology-panel">
          <header className="task-graph-topology-panel__head">
            <Route size={16} />
            <strong>任务定义模板</strong>
          </header>
          <div className="task-graph-topology-task-list">
            {selectedDomainTasks.length ? selectedDomainTasks.map((task) => (
              <button disabled={published} key={task.task_id} onClick={() => addTaskGraphTaskNode(task)} type="button">
                <span>{task.task_title || task.task_id}</span>
                <small>{task.task_id}</small>
              </button>
            )) : (
              <p>当前任务域暂无可引用的具体任务定义。</p>
            )}
          </div>
        </section>
      </aside>

      <main className="task-graph-topology-canvas-shell">
        <header className="task-graph-topology-canvas-head">
          <div>
            <span>规范拓扑编辑</span>
            <strong>{taskGraphDraftV2.title}</strong>
          </div>
          <div className="task-graph-topology-metrics" aria-label="拓扑计数">
            <span>{activeGraphNodes.length} 节点</span>
            <span>{graphEdges.length}/{activeGraphEdges.length} 边</span>
            <span>{taskGraphDraftV2.entry_node_id || "无入口"} {"->"} {taskGraphDraftV2.output_node_id || "无出口"}</span>
          </div>
        </header>
        <section className="task-graph-topology-layer-filter" aria-label="拓扑图层过滤">
          {EDGE_FLOW_FILTERS.map((filter) => (
            <button
              className={edgeFlowFilter === filter.id ? "active" : ""}
              key={filter.id}
              onClick={() => setEdgeFlowFilter(filter.id)}
              type="button"
            >
              <strong>{filter.title}</strong>
              <span>{filter.description}</span>
            </button>
          ))}
        </section>
        <div className="coordination-topology-viewport coordination-topology-viewport--builder task-graph-topology-viewport">
          <TaskGraphTopologyCanvas
            edges={graphEdges}
            emptyDescription="先添加节点，随后从节点工具建立连接。"
            emptyTitle="当前任务图还没有拓扑节点"
            linkingFromNodeId={linkingFromNodeId}
            nodes={graphNodes}
            onSelectEdge={(edgeId) => {
              setSelectedGraphEdgeId(edgeId);
              setSelectedGraphNodeId("");
              onEditorFocus?.({ layer: "topology", facet: "edge", edge_id: edgeId });
            }}
            onSelectNode={(nodeId) => {
              handleTopologyNodeClick(nodeId);
              onEditorFocus?.({ layer: "topology", facet: "node", node_id: nodeId });
            }}
            renderEdgeTools={(edge) => (
              <>
                <button disabled={published} onClick={() => reverseTaskGraphEdge(edge.id)} title="反转边" type="button">
                  <ArrowRightLeft size={13} />
                </button>
                <button disabled={published} onClick={() => removeTaskGraphEdge(edge.id)} title="删除边" type="button">
                  <Trash2 size={13} />
                </button>
              </>
            )}
            renderNodeTools={(node) => (
              <>
                <button disabled={published} onClick={() => setLinkingFromNodeId(node.id)} title="从此节点连线" type="button">
                  <Link2 size={13} />
                </button>
                <button disabled={published} onClick={() => addTaskGraphSuccessorNode(node.id)} title="添加后继节点" type="button">
                  <Plus size={13} />
                </button>
              </>
            )}
            selectedEdgeId={selectedEdgeId}
            selectedNodeId={selectedNodeId}
          />
        </div>
      </main>

      <aside className="task-graph-topology-inspector" aria-label="拓扑选择详情">
        <section className="task-graph-topology-panel">
          <header className="task-graph-topology-panel__head">
            <MousePointer2 size={16} />
            <strong>选择</strong>
          </header>
          <div className="task-graph-topology-selection">
            <span>节点</span>
            <strong>{selectedGraphNode ? taskGraphDisplayName(selectedNodeId, selectedGraphNode, graphMetadata, selectedNodeTitle(selectedGraphNode)) : selectedNodeTitle(selectedGraphNode)}</strong>
            <small>{selectedNodeId || "无"}</small>
          </div>
          {selectedGraphNode ? (
            <div className="task-graph-topology-resource-summary">
              <p><span>类型</span><strong>{nodeKindLabel(selectedNodeKind)}</strong></p>
              <p><span>生命周期</span><strong>{String(selectedGraphNode.phase_id ?? "未分配")}</strong></p>
              <p><span>执行模式</span><strong>{String(selectedGraphNode.execution_mode ?? "sync")}</strong></p>
              <p><span>等待策略</span><strong>{String(selectedGraphNode.wait_policy ?? "wait_all")}</strong></p>
              <p><span>入边</span><strong>{incomingSelectedEdgeCount}</strong></p>
              <p><span>出边</span><strong>{outgoingSelectedEdgeCount}</strong></p>
            </div>
          ) : null}
          {isResourceNode(selectedGraphNode) ? (
            <div className="task-graph-topology-resource-summary">
              <p><span>读取</span><strong>{selectedRepositoryReadCount}</strong></p>
              <p><span>写候选</span><strong>{selectedRepositoryWriteCount}</strong></p>
              <p><span>提交</span><strong>{selectedRepositoryCommitCount}</strong></p>
              <p><span>集合</span><strong>{selectedRepository?.collections.length ?? 0}</strong></p>
            </div>
          ) : null}
          <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
            {isResourceNode(selectedGraphNode) ? (
              <button
                disabled={!selectedNodeId}
                onClick={() => {
                  if (onEditorFocus) {
                    onEditorFocus({ layer: "memory", facet: "repositories", node_id: selectedNodeId, repository_id: selectedRepository?.nodeId ?? selectedNodeId });
                  } else {
                    onOpenMemoryLayer?.();
                  }
                }}
                type="button"
              >
                <GitBranch size={15} />
                <span>配置仓库结构</span>
              </button>
            ) : null}
            {!isResourceNode(selectedGraphNode) ? (
              <button disabled={!selectedNodeId} onClick={() => onEditorFocus?.({ layer: "responsibility", facet: "cognition", node_id: selectedNodeId })} type="button">
                <Route size={15} />
                <span>查看执行认知包</span>
              </button>
            ) : null}
            <button disabled={!selectedNodeId} onClick={() => onEditorFocus?.({ layer: "timeline", facet: "clock", node_id: selectedNodeId })} type="button">
              <GitBranch size={15} />
              <span>查看生命周期诊断</span>
            </button>
            <button disabled={!selectedNodeCanMutate} onClick={() => setLinkingFromNodeId(selectedNodeId)} type="button">
              <Link2 size={15} />
              <span>设为连线起点</span>
            </button>
            <button disabled={!selectedNodeCanMutate} onClick={() => addTaskGraphSuccessorNode(selectedNodeId)} type="button">
              <Plus size={15} />
              <span>添加后继</span>
            </button>
            <button disabled={!selectedNodeCanMutate} onClick={() => removeTaskGraphNode(selectedNodeId)} type="button">
              <Trash2 size={15} />
              <span>删除节点</span>
            </button>
          </div>
        </section>

        <section className="task-graph-topology-panel">
          <header className="task-graph-topology-panel__head">
            <GitBranch size={16} />
            <strong>边</strong>
          </header>
          <div className="task-graph-topology-selection">
            <span>连接</span>
            <strong>{selectedEdgeTitle(selectedGraphEdge)}</strong>
            <small>{selectedEdgeId || "无"}</small>
          </div>
          {selectedGraphEdge ? (
            <div className="task-graph-topology-resource-summary">
              <p><span>类型</span><strong>{selectedEdgeKind}</strong></p>
              <p><span>图层</span><strong>{selectedEdgeFlow}</strong></p>
              <p><span>起点</span><strong>{graphEdgeSource(selectedGraphEdge)}</strong></p>
              <p><span>终点</span><strong>{graphEdgeTarget(selectedGraphEdge)}</strong></p>
            </div>
          ) : null}
          {selectedEdgeSummary ? (
            <div className="task-graph-note">
              <strong>边的控制含义</strong>
              <span>{selectedEdgeSummary}</span>
            </div>
          ) : null}
          <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
            {selectedEdgeFlow === "memory" ? (
              <button disabled={!selectedEdgeId} onClick={() => onEditorFocus?.({ layer: "memory", facet: "selector", edge_id: selectedEdgeId })} type="button">
                <GitBranch size={15} />
                <span>配置 Selector</span>
              </button>
            ) : null}
            {selectedEdgeFlow === "artifact" ? (
              <button disabled={!selectedEdgeId} onClick={() => onEditorFocus?.({ layer: "memory", facet: "artifact_context", edge_id: selectedEdgeId })} type="button">
                <GitBranch size={15} />
                <span>配置产物上下文</span>
              </button>
            ) : null}
            {selectedEdgeFlow === "revision" ? (
              <button disabled={!selectedEdgeId} onClick={() => onEditorFocus?.({ layer: "timeline", facet: "revision", edge_id: selectedEdgeId })} type="button">
                <GitBranch size={15} />
                <span>配置返修交接</span>
              </button>
            ) : null}
            {selectedEdgeId ? (
              <button disabled={!selectedEdgeId} onClick={() => onEditorFocus?.({ layer: "contracts", facet: "payload", edge_id: selectedEdgeId })} type="button">
                <GitBranch size={15} />
                <span>配置载荷契约</span>
              </button>
            ) : null}
            <button disabled={!selectedEdgeCanMutate} onClick={() => reverseTaskGraphEdge(selectedEdgeId)} type="button">
              <ArrowRightLeft size={15} />
              <span>反转方向</span>
            </button>
            <button disabled={!selectedEdgeCanMutate} onClick={() => removeTaskGraphEdge(selectedEdgeId)} type="button">
              <Trash2 size={15} />
              <span>删除边</span>
            </button>
          </div>
        </section>
      </aside>
    </section>
  );
}
