"use client";

import { Activity, ExternalLink, PauseCircle, PlayCircle, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import type { ContractSpec } from "@/lib/api";
import { useAppStore } from "@/lib/store";

import { TaskGraphActionRail } from "./TaskGraphActionRail";
import { TaskGraphCanvasPanel } from "./TaskGraphCanvasPanel";
import {
  createTaskGraphSemanticEdgeDraft,
  createTaskGraphSemanticNodeDraft,
  semanticEdgePatchForRelation,
  type TaskGraphSemanticNodeKind,
} from "./TaskGraphEditorActions";
import { TaskGraphSmartInspector } from "./TaskGraphSmartInspector";
import {
  graphEdgeSource,
  graphEdgeTarget,
  isTaskGraphPublishedState,
} from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import {
  taskGraphSemanticRelationLabel,
  type TaskGraphSemanticRelationId,
  type TaskGraphSemanticRelationPreset,
} from "./taskGraphSemanticRelations";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

type TaskGraphTopologyPageProps = Pick<
  TaskGraphWorkbenchProps,
  | "activeGraphEdges"
  | "activeGraphNodes"
  | "addTaskGraphSuccessorNode"
  | "addTaskGraphTaskNode"
  | "contractSpecs"
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
  | "semanticRelationPresets"
  | "setLinkingFromNodeId"
  | "setSelectedGraphEdgeId"
  | "setSelectedGraphNodeId"
  | "taskGraphDraftV2"
  | "updateTaskGraphDraft"
  | "updateTaskGraphEdge"
  | "updateTaskGraphNode"
> & {
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
};

type EdgeFlowFilter = "all" | "execution" | "memory" | "artifact" | "revision";

const EDGE_FLOW_FILTERS: Array<{ id: EdgeFlowFilter; title: string; description: string }> = [
  { id: "all", title: "全部", description: "所有关系" },
  { id: "execution", title: "执行", description: "交接控制" },
  { id: "memory", title: "记忆", description: "读写提交" },
  { id: "artifact", title: "产物", description: "引用传递" },
  { id: "revision", title: "返修", description: "审核回路" },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => stringValue(item)).filter(Boolean) : [];
}

function numberValue(value: unknown) {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? next : 0;
}

function nodeIdOf(node: Record<string, unknown>, index: number) {
  return stringValue(node.node_id ?? node.id, `node_${index + 1}`);
}

function edgeIdOf(edge: Record<string, unknown>, index: number) {
  const source = graphEdgeSource(edge);
  const target = graphEdgeTarget(edge);
  return stringValue(edge.edge_id ?? edge.id, source && target ? `${source}->${target}` : `edge_${index + 1}`);
}

function titleOfNode(node: Record<string, unknown>, index: number) {
  return stringValue(node.title ?? node.label ?? node.task_title, nodeIdOf(node, index));
}

function labelOfEdge(edge: Record<string, unknown>, semanticRelationPresets: TaskGraphSemanticRelationPreset[]) {
  const relationId = stringValue(asRecord(edge.metadata).semantic_relation_id);
  const edgeType = stringValue(edge.edge_type ?? edge.mode);
  const labels: Record<string, string> = {
    "writing.draft_to_review": "审核",
    "writing.review_revise_to_writer": "返修",
    "writing.revision_to_review": "复审",
    "memory.read_required": "读",
    "memory.write_candidate": "写候选",
    "memory.commit_after_review": "提交",
    memory_read: "读",
    memory_write_candidate: "写候选",
    memory_commit: "提交",
    review_feedback: "返修",
    handoff: "交接",
  };
  const relationLabel = relationId ? taskGraphSemanticRelationLabel(relationId, semanticRelationPresets).split(" · ")[0] : "";
  return stringValue(edge.label ?? relationLabel ?? labels[relationId] ?? labels[edgeType] ?? edgeType, "交接");
}

function topologyNodeKind(node: Record<string, unknown>) {
  const nodeType = stringValue(node.node_type);
  const role = stringValue(node.role);
  const executionMode = stringValue(node.execution_mode);
  if (nodeType === "review_gate" || role === "reviewer" || Object.keys(asRecord(node.review_gate_policy)).length > 0) return "review_gate";
  if (executionMode === "manual_gate" || nodeType === "manual_gate" || role === "manual_gate") return "manual_gate";
  if (nodeType === "artifact_repository") return "artifact";
  if (nodeType === "memory_repository" || nodeType.endsWith("_ledger") || role === "resource") return "memory";
  if (role === "writer") return "writer";
  return nodeType || "executor";
}

function edgeFlowKind(edge: Record<string, unknown>): EdgeFlowFilter {
  const edgeType = stringValue(edge.edge_type ?? edge.mode);
  const relationId = stringValue(asRecord(edge.metadata).semantic_relation_id);
  if (edgeType.startsWith("memory_") || relationId.startsWith("memory.")) return "memory";
  if (edgeType.startsWith("artifact_") || Object.keys(asRecord(edge.artifact_ref_policy)).length > 0) return "artifact";
  if (["revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"].includes(edgeType) || relationId.includes("revise")) return "revision";
  return "execution";
}

function topologyEdgeKind(edge: Record<string, unknown>) {
  const edgeType = stringValue(edge.edge_type ?? edge.mode);
  if (edgeType === "memory_read") return "memory_read";
  if (edgeType === "memory_write_candidate" || edgeType === "memory_write") return "memory_write_candidate";
  if (edgeType === "memory_commit") return "memory_commit";
  if (edgeFlowKind(edge) === "artifact") return "artifact_context";
  if (edgeFlowKind(edge) === "revision") return "revision_request";
  if (edgeType === "control" || edgeType === "control_flow") return "control_flow";
  return "handoff";
}

function contractTitle(contract: ContractSpec) {
  return stringValue(contract.title_zh ?? contract.title_en ?? contract.contract_id, contract.contract_id);
}

function graphRunNodeStatusMap(loopState: Record<string, unknown>) {
  const statuses = new Map<string, string>();
  for (const nodeId of stringArray(loopState.ready_node_ids)) statuses.set(nodeId, "ready");
  for (const nodeId of stringArray(loopState.running_node_ids)) statuses.set(nodeId, "running");
  for (const nodeId of stringArray(loopState.completed_node_ids)) statuses.set(nodeId, "completed");
  for (const nodeId of stringArray(loopState.failed_node_ids)) statuses.set(nodeId, "failed");
  for (const nodeId of stringArray(loopState.blocked_node_ids)) statuses.set(nodeId, "blocked");
  return statuses;
}

function graphRunStatusLabel(status: string) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "created") return "已创建";
  if (status === "blocked") return "阻塞";
  return status || "等待运行";
}

function graphRunLatestTime(monitor: unknown) {
  const record = asRecord(monitor);
  const graphRun = asRecord(record.graph_run);
  const taskRun = asRecord(record.task_run);
  const events = Array.isArray(record.events) ? record.events : [];
  const latestEventAt = events.reduce((max, event) => Math.max(max, numberValue(asRecord(event).created_at)), 0);
  return Math.max(numberValue(graphRun.updated_at), numberValue(taskRun.updated_at), latestEventAt);
}

export function TaskGraphTopologyPage({
  activeGraphEdges,
  activeGraphNodes,
  addTaskGraphSuccessorNode,
  addTaskGraphTaskNode,
  contractSpecs,
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
  semanticRelationPresets,
  setLinkingFromNodeId,
  setSelectedGraphEdgeId,
  setSelectedGraphNodeId,
  taskGraphDraftV2,
  updateTaskGraphDraft,
  updateTaskGraphEdge,
  updateTaskGraphNode,
}: TaskGraphTopologyPageProps) {
  const {
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    pauseBoundTaskGraphRun,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
  } = useAppStore();
  const [edgeFlowFilter, setEdgeFlowFilter] = useState<EdgeFlowFilter>("all");
  const published = isTaskGraphPublishedState(taskGraphDraftV2.publish_state);
  const graphMetadata = asRecord(taskGraphDraftV2.metadata);
  const monitorGraphId = stringValue(
    taskGraphMonitorBinding?.graph_id
    || asRecord(taskGraphBoundRunMonitor?.graph_run).graph_id
    || asRecord(taskGraphBoundRunMonitor?.graph_harness_config).graph_id,
  );
  const monitorAppliesToDraft = Boolean(
    taskGraphMonitorBinding
    && (!monitorGraphId || monitorGraphId === taskGraphDraftV2.graph_id),
  );
  const visibleMonitor = monitorAppliesToDraft ? taskGraphBoundRunMonitor : null;
  const visibleBinding = monitorAppliesToDraft ? taskGraphMonitorBinding : null;
  const graphRunLoopState = asRecord(visibleMonitor?.graph_loop_state);
  const runtimeMonitor = asRecord(visibleMonitor?.task_run_monitor || visibleMonitor?.runtime_monitor);
  const graphRunStatus = stringValue(runtimeMonitor.lifecycle || runtimeMonitor.status || graphRunLoopState.status || asRecord(visibleMonitor?.graph_run).status);
  const graphRunStatuses = useMemo(() => graphRunNodeStatusMap(graphRunLoopState), [graphRunLoopState]);
  const readyNodeIds = stringArray(graphRunLoopState.ready_node_ids);
  const runningNodeIds = stringArray(graphRunLoopState.running_node_ids);
  const completedNodeIds = stringArray(graphRunLoopState.completed_node_ids);
  const failedNodeIds = stringArray(graphRunLoopState.failed_node_ids);
  const blockedNodeIds = stringArray(graphRunLoopState.blocked_node_ids);
  const activeWorkOrders = Array.isArray(visibleMonitor?.active_node_work_orders) ? visibleMonitor.active_node_work_orders : [];
  const latestAt = graphRunLatestTime(visibleMonitor);
  const latestLabel = latestAt ? new Date(latestAt * 1000).toLocaleTimeString() : "暂无更新";
  const selectedNodeId = stringValue(selectedGraphNode?.node_id ?? selectedGraphNodeId);
  const selectedEdgeId = selectedGraphEdgeId;
  const contractOptions = contractSpecs.map((item) => item.contract_id);
  const formatContract = (contractId: string) => {
    const contract = contractSpecs.find((item) => item.contract_id === contractId);
    return contract ? `${contractTitle(contract)} · ${contract.contract_id}` : contractId || "未绑定契约";
  };

  const visibleGraphEdges = activeGraphEdges
    .map((edge, index) => ({ edge, index }))
    .filter(({ edge }) => edgeFlowFilter === "all" || edgeFlowKind(edge) === edgeFlowFilter);

  const graphNodes = useMemo(() => activeGraphNodes.map((node, index) => {
    const nodeId = nodeIdOf(node, index);
    return {
      id: nodeId,
      title: taskGraphDisplayName(nodeId, node, graphMetadata, titleOfNode(node, index)),
      agentLabel: stringValue(node.role ?? node.node_type),
      role: stringValue(node.role),
      nodeKind: topologyNodeKind(node),
      status: graphRunStatuses.get(nodeId) || (nodeId === taskGraphDraftV2.entry_node_id ? "ready" : nodeId === taskGraphDraftV2.output_node_id ? "waiting" : "idle"),
    };
  }), [activeGraphNodes, graphMetadata, graphRunStatuses, taskGraphDraftV2.entry_node_id, taskGraphDraftV2.output_node_id]);

  const graphEdges = visibleGraphEdges.map(({ edge, index }) => ({
    id: edgeIdOf(edge, index),
    from: graphEdgeSource(edge),
    to: graphEdgeTarget(edge),
    label: labelOfEdge(edge, semanticRelationPresets),
    edgeKind: topologyEdgeKind(edge),
    status: "idle",
  })).filter((edge) => edge.from && edge.to);

  const selectNode = (nodeId: string) => {
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
    onEditorFocus?.({ layer: "topology", facet: "node", node_id: nodeId, edge_id: undefined });
  };

  const selectEdge = (edgeId: string) => {
    setSelectedGraphEdgeId(edgeId);
    setSelectedGraphNodeId("");
    onEditorFocus?.({ layer: "topology", facet: "edge", edge_id: edgeId, node_id: undefined });
  };

  const addSemanticNode = (kind: TaskGraphSemanticNodeKind) => {
    const node = createTaskGraphSemanticNodeDraft(kind, activeGraphNodes);
    updateTaskGraphDraft({
      nodes: [...(taskGraphDraftV2.nodes ?? []), node] as typeof taskGraphDraftV2.nodes,
    });
    selectNode(String(node.node_id));
  };

  const applyRelation = (relationId: TaskGraphSemanticRelationId) => {
    if (selectedGraphEdge && selectedEdgeId) {
      updateTaskGraphEdge(selectedEdgeId, semanticEdgePatchForRelation(selectedGraphEdge, relationId, semanticRelationPresets));
      selectEdge(selectedEdgeId);
      return;
    }
    if (!linkingFromNodeId && selectedNodeId) {
      setLinkingFromNodeId(selectedNodeId);
      return;
    }
    const sourceNodeId = linkingFromNodeId;
    const targetNodeId = selectedNodeId;
    if (!sourceNodeId || !targetNodeId || sourceNodeId === targetNodeId) return;
    const existing = activeGraphEdges.find((edge, index) => {
      const edgeId = edgeIdOf(edge, index);
      return graphEdgeSource(edge) === sourceNodeId && graphEdgeTarget(edge) === targetNodeId && edgeId;
    });
    if (existing) {
      const edgeId = edgeIdOf(existing, activeGraphEdges.indexOf(existing));
      updateTaskGraphEdge(edgeId, semanticEdgePatchForRelation(existing, relationId, semanticRelationPresets));
      selectEdge(edgeId);
      setLinkingFromNodeId("");
      return;
    }
    const edge = createTaskGraphSemanticEdgeDraft({
      existingEdges: activeGraphEdges,
      relationId,
      semanticRelations: semanticRelationPresets,
      sourceNodeId,
      targetNodeId,
    });
    updateTaskGraphDraft({
      edges: [...(taskGraphDraftV2.edges ?? []), edge] as typeof taskGraphDraftV2.edges,
    });
    selectEdge(String(edge.edge_id));
    setLinkingFromNodeId("");
  };

  return (
    <section className="task-graph-topology-page task-graph-topology-page--semantic" aria-label="任务图语义化编辑台">
      <TaskGraphActionRail
        canCreateRelation={Boolean(selectedGraphEdgeId || selectedNodeId)}
        disabled={published}
        linkingFromNodeId={linkingFromNodeId}
        onAddNode={addSemanticNode}
        onAddTaskNode={addTaskGraphTaskNode}
        onApplyRelation={applyRelation}
        semanticRelationPresets={semanticRelationPresets}
        selectedDomainTasks={selectedDomainTasks}
        selectedNodeId={selectedNodeId}
      />

      <section className="task-graph-canvas-stack">
        <section className="task-graph-topology-layer-filter" aria-label="关系过滤">
          {EDGE_FLOW_FILTERS.map((filter) => (
            <button
              aria-pressed={edgeFlowFilter === filter.id}
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
        {visibleBinding || visibleMonitor ? (
          <section className={taskGraphMonitorError ? "task-graph-inline-monitor task-graph-inline-monitor--error" : "task-graph-inline-monitor"} aria-label="图运行监控">
            <div className="task-graph-inline-monitor__status">
              <Activity size={14} />
              <strong>{graphRunStatusLabel(graphRunStatus)}</strong>
              <span>{visibleBinding?.title || visibleBinding?.graph_id || taskGraphDraftV2.title}</span>
              <em>{latestLabel}</em>
            </div>
            <div className="task-graph-inline-monitor__metrics" aria-label="运行态节点统计">
              <span>Ready {readyNodeIds.length}</span>
              <span>Running {runningNodeIds.length}</span>
              <span>Done {completedNodeIds.length}</span>
              <span>Failed {failedNodeIds.length}</span>
              <span>Blocked {blockedNodeIds.length}</span>
              <span>WO {visibleMonitor?.active_node_work_order_count ?? activeWorkOrders.length}</span>
            </div>
            <div className="task-graph-inline-monitor__actions">
              <button disabled={!visibleBinding || taskGraphMonitorLoading} onClick={() => void evaluateBoundTaskGraphMonitor()} title="刷新 GraphRun 监控" type="button">
                <RefreshCw size={13} />
              </button>
              <button disabled={!visibleBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void continueBoundTaskGraphRun()} title="派发 Ready 节点" type="button">
                <PlayCircle size={13} />
              </button>
              <button disabled={!visibleBinding || taskGraphMonitorLoading || taskGraphMonitorActionLoading} onClick={() => void pauseBoundTaskGraphRun()} title="暂停 root TaskRun" type="button">
                <PauseCircle size={13} />
              </button>
              <button disabled={!visibleBinding} onClick={() => setTaskGraphRunInteractionOpen(true)} title="打开监控浮窗" type="button">
                <ExternalLink size={13} />
              </button>
            </div>
            {taskGraphMonitorError ? <p>{taskGraphMonitorError}</p> : null}
          </section>
        ) : null}
        <TaskGraphCanvasPanel
          disabled={published}
          edgeCount={activeGraphEdges.length}
          edges={graphEdges}
          entryNodeId={taskGraphDraftV2.entry_node_id}
          filteredEdgeCount={graphEdges.length}
          linkingFromNodeId={linkingFromNodeId}
          nodes={graphNodes}
          onAddSuccessor={addTaskGraphSuccessorNode}
          onRemoveEdge={removeTaskGraphEdge}
          onReverseEdge={reverseTaskGraphEdge}
          onSelectEdge={selectEdge}
          onSelectNode={(nodeId) => {
            handleTopologyNodeClick(nodeId);
            onEditorFocus?.({ layer: "topology", facet: "node", node_id: nodeId });
          }}
          onSetLinkingFrom={setLinkingFromNodeId}
          outputNodeId={taskGraphDraftV2.output_node_id}
          selectedEdgeId={selectedEdgeId}
          selectedNodeId={selectedNodeId}
          title={taskGraphDraftV2.title}
        />
      </section>

      <TaskGraphSmartInspector
        contractOptions={contractOptions}
        disabled={published}
        formatContract={formatContract}
        graphMetadata={graphMetadata}
        onAddSuccessor={addTaskGraphSuccessorNode}
        onApplyRelation={applyRelation}
        onRemoveEdge={removeTaskGraphEdge}
        onRemoveNode={removeTaskGraphNode}
        onReverseEdge={reverseTaskGraphEdge}
        onSetLinkingFrom={setLinkingFromNodeId}
        onUpdateEdge={updateTaskGraphEdge}
        onUpdateNode={updateTaskGraphNode}
        semanticRelationPresets={semanticRelationPresets}
        selectedEdge={selectedGraphEdge}
        selectedEdgeId={selectedEdgeId}
        selectedNode={selectedGraphNode}
        selectedNodeId={selectedNodeId}
      />
    </section>
  );
}
