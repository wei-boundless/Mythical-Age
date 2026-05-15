"use client";

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
>;

const ROLE_QUICK_ADDS = [
  { role: "coordinator", label: "协调" },
  { role: "writer", label: "写作" },
  { role: "reviewer", label: "评审" },
  { role: "memory", label: "记忆" },
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
  return String(edge.label ?? edge.mode ?? edge.edge_type ?? "handoff").trim();
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

export function TaskGraphTopologyPage({
  activeGraphEdges,
  activeGraphNodes,
  addTaskGraphNode,
  addTaskGraphRoleNode,
  addTaskGraphSuccessorNode,
  addTaskGraphTaskNode,
  handleTopologyNodeClick,
  linkingFromNodeId,
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
}: TaskGraphTopologyPageProps) {
  const published = isTaskGraphPublishedState(taskGraphDraftV2.publish_state);
  const graphNodes = activeGraphNodes.map((node, index) => {
    const nodeId = nodeIdOf(node, index);
    return {
      id: nodeId,
      title: titleOfNode(node, index),
      agentLabel: String(node.role ?? node.node_type ?? "").trim(),
      role: String(node.role ?? "").trim(),
      nodeKind: String(node.node_type ?? "").trim(),
      status: nodeId === taskGraphDraftV2.entry_node_id ? "ready" : nodeId === taskGraphDraftV2.output_node_id ? "waiting" : "idle",
    };
  });
  const graphEdges = activeGraphEdges.map((edge, index) => ({
    id: edgeIdOf(edge, index),
    from: graphEdgeSource(edge),
    to: graphEdgeTarget(edge),
    label: labelOfEdge(edge),
    status: "idle",
  })).filter((edge) => edge.from && edge.to);
  const selectedNodeId = String(selectedGraphNode?.node_id ?? selectedGraphNodeId ?? "");
  const selectedEdgeId = selectedGraphEdgeId;
  const selectedNodeCanMutate = Boolean(selectedNodeId && !published);
  const selectedEdgeCanMutate = Boolean(selectedEdgeId && !published);

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
        </section>

        <section className="task-graph-topology-panel">
          <header className="task-graph-topology-panel__head">
            <Route size={16} />
            <strong>任务节点</strong>
          </header>
          <div className="task-graph-topology-task-list">
            {selectedDomainTasks.length ? selectedDomainTasks.map((task) => (
              <button disabled={published} key={task.task_id} onClick={() => addTaskGraphTaskNode(task)} type="button">
                <span>{task.task_title || task.task_id}</span>
                <small>{task.task_id}</small>
              </button>
            )) : (
              <p>当前任务域暂无可绑定任务。</p>
            )}
          </div>
        </section>
      </aside>

      <main className="task-graph-topology-canvas-shell">
        <header className="task-graph-topology-canvas-head">
          <div>
            <span>Topology</span>
            <strong>{taskGraphDraftV2.title}</strong>
          </div>
          <div className="task-graph-topology-metrics" aria-label="拓扑计数">
            <span>{activeGraphNodes.length} 节点</span>
            <span>{activeGraphEdges.length} 边</span>
            <span>{taskGraphDraftV2.entry_node_id || "无入口"} {"->"} {taskGraphDraftV2.output_node_id || "无出口"}</span>
          </div>
        </header>
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
            }}
            onSelectNode={(nodeId) => handleTopologyNodeClick(nodeId)}
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
            <strong>{selectedNodeTitle(selectedGraphNode)}</strong>
            <small>{selectedNodeId || "无"}</small>
          </div>
          <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
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
          <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
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
