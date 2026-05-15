"use client";

import { AlertTriangle, CheckCircle2, Database, FileText, Network } from "lucide-react";
import { useMemo, useState } from "react";

import { CoordinationTopologyGraph } from "@/components/coordination/CoordinationTopologyGraph";
import type { TaskGraphRunMonitorView } from "@/lib/api";
import {
  buildTaskGraphMonitorViewModel,
  taskGraphMonitorStatusLabel,
} from "./taskGraphMonitorViewModel";

function text(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function artifactLabel(item: Record<string, unknown>) {
  return text(item.artifact_ref) || text(item.ref) || text(item.path) || "未命名产物";
}

export function TaskGraphRunMonitorPanel({
  monitor,
}: {
  monitor?: TaskGraphRunMonitorView | null;
}) {
  const model = useMemo(() => buildTaskGraphMonitorViewModel(monitor), [monitor]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const selectedNode = model.nodes.find((node) => node.id === selectedNodeId)
    ?? model.nodes.find((node) => node.id === model.activeNodeId)
    ?? model.nodes[0]
    ?? null;
  const selectedEdge = model.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const scopedMemoryOperations = selectedEdge
    ? model.memoryOperations.filter((operation) => operation.edgeId === selectedEdge.id)
    : selectedNode
      ? model.memoryOperations.filter((operation) => operation.nodeId === selectedNode.id)
      : model.memoryOperations;
  const progress = model.nodeCount ? Math.round((model.completedCount / model.nodeCount) * 100) : 0;

  if (!model.hasSignal) {
    return (
      <div className="coordination-session-empty">
        <Network size={22} />
        <strong>当前还没有任务图运行</strong>
      </div>
    );
  }

  return (
    <div className="coordination-session">
      <header className="coordination-session__head">
        <div className="coordination-session__heading">
          <span>实时任务图监控</span>
          <h2>{model.title}</h2>
        </div>
        <div className="coordination-session__statusbar" aria-label="当前任务图运行状态">
          <article className="coordination-session__statuspill coordination-session__statuspill--active">
            <span>运行状态</span>
            <strong>{taskGraphMonitorStatusLabel(model.status)}</strong>
            <em>{model.graphId || "未绑定图"}</em>
          </article>
          <article className="coordination-session__statuspill">
            <span>拓扑</span>
            <strong>{model.nodeCount} 节点 / {model.edgeCount} 边</strong>
            <em>{progress}% 完成</em>
          </article>
          <article className="coordination-session__statuspill">
            <span>当前节点</span>
            <strong>{selectedNode?.title || "等待节点"}</strong>
            <em>{selectedNode ? taskGraphMonitorStatusLabel(selectedNode.status) : "待启动"}</em>
          </article>
          <article className="coordination-session__statuspill">
            <span>事件</span>
            <strong>{model.eventCount}</strong>
            <em>{model.coordinationRunId || model.taskRunId}</em>
          </article>
        </div>
      </header>

      <section className="coordination-overview-strip" aria-label="运行总览">
        <article className="coordination-overview-card coordination-overview-card--active">
          <span>当前节点</span>
          <strong>{selectedNode?.title || "等待启动"}</strong>
          <em>{selectedNode ? taskGraphMonitorStatusLabel(selectedNode.status) : "待启动"}</em>
        </article>
        <article className="coordination-overview-card">
          <span>总节点</span>
          <strong>{model.nodeCount}</strong>
          <em>运行中 {model.runningCount} · 完成 {model.completedCount}</em>
        </article>
        <article className="coordination-overview-card">
          <span>风险</span>
          <strong>{model.failedCount + model.blockedCount}</strong>
          <em>{model.healthValid ? "健康检查通过" : `${model.healthIssues.length} 个问题`}</em>
        </article>
      </section>

      {model.failureMessage ? (
        <section className="coordination-output-board" aria-label="失败诊断">
          <article className="coordination-output-card coordination-contract-card">
            <div className="coordination-output-card__head">
              <span><AlertTriangle size={14} /> 失败诊断</span>
              <strong>{model.failureCode || model.terminalReason || "executor_failed"}</strong>
            </div>
            <div className="coordination-handoff-list">
              <article className="coordination-handoff-item">
                <div>
                  <strong>错误信息</strong>
                  <span>{model.failureMessage}</span>
                </div>
              </article>
              <article className="coordination-handoff-item">
                <div>
                  <strong>模型</strong>
                  <span>{model.failureProvider || "unknown"} / {model.failureModel || "unknown"}</span>
                </div>
              </article>
              <article className="coordination-handoff-item">
                <div>
                  <strong>失败步骤</strong>
                  <span>{model.failureStepId || "unknown"}</span>
                </div>
              </article>
              {model.failureDetail ? (
                <article className="coordination-handoff-item">
                  <div>
                    <strong>原始细节</strong>
                    <small>{model.failureDetail}</small>
                  </div>
                </article>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}

      <section className="coordination-topology-shell" aria-label="任务图运行拓扑">
        <div className="coordination-topology-shell__head">
          <span>权威拓扑</span>
          <p className="coordination-topology-shell__hint">节点和边只来自后端 TaskGraph 运行监控视图，前端不再根据阶段列表补图。</p>
        </div>
        <div className="coordination-topology-viewport">
          <CoordinationTopologyGraph
            currentNodeId={model.activeNodeId}
            edges={model.edges}
            emptyDescription="后端权威监控视图没有返回可渲染的边，请查看健康检查。"
            emptyTitle="任务图拓扑为空"
            nodes={model.nodes}
            onSelectEdge={(edgeId) => {
              setSelectedEdgeId(edgeId);
              setSelectedNodeId("");
            }}
            onSelectNode={(nodeId) => {
              setSelectedNodeId(nodeId);
              setSelectedEdgeId("");
            }}
            selectedEdgeId={selectedEdgeId}
            selectedNodeId={selectedNodeId || model.activeNodeId}
          />
        </div>
      </section>

      <section className="coordination-output-board">
        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span>{selectedEdge ? "选中边" : "选中节点"}</span>
            <strong>{selectedEdge ? selectedEdge.id : selectedNode?.id || "未选择"}</strong>
          </div>
          <div className="coordination-handoff-list">
            {selectedEdge ? (
              <>
                <article className="coordination-handoff-item"><div><strong>来源</strong><span>{selectedEdge.from}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>目标</strong><span>{selectedEdge.to}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>契约</strong><span>{selectedEdge.contractId || "未标注"}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>状态</strong><span>{taskGraphMonitorStatusLabel(selectedEdge.status)}</span></div></article>
              </>
            ) : selectedNode ? (
              <>
                <article className="coordination-handoff-item"><div><strong>节点</strong><span>{selectedNode.title}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>Agent</strong><span>{selectedNode.agentLabel}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>任务</strong><span>{selectedNode.taskId || "未标注"}</span></div></article>
                <article className="coordination-handoff-item"><div><strong>状态</strong><span>{taskGraphMonitorStatusLabel(selectedNode.status)}</span></div></article>
              </>
            ) : null}
          </div>
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><Database size={14} /> 记忆读写</span>
            <strong>{scopedMemoryOperations.length ? `${scopedMemoryOperations.length} 个操作` : "暂无操作"}</strong>
          </div>
          <div className="coordination-handoff-list">
            {scopedMemoryOperations.length ? (
              scopedMemoryOperations.slice(-8).map((operation) => (
                <article className="coordination-handoff-item" key={operation.key}>
                  <div>
                    <strong>{operation.operation || "memory"}</strong>
                    <span>{operation.nodeId || operation.edgeId || "graph"} · {taskGraphMonitorStatusLabel(operation.status)}</span>
                  </div>
                  <small>{operation.refs.join(", ") || "无引用"}</small>
                </article>
              ))
            ) : (
              <p className="coordination-contract-empty">当前范围没有记忆操作。</p>
            )}
          </div>
        </article>
      </section>

      <section className="coordination-output-board">
        <article className="coordination-output-card coordination-output-card--artifacts">
          <div className="coordination-output-card__head">
            <span><FileText size={14} /> 产物</span>
            <strong>{model.artifacts.length ? `${model.artifacts.length} 个引用` : "暂无产物"}</strong>
          </div>
          <div className="coordination-output-list">
            {model.artifacts.length ? (
              model.artifacts.slice(-8).map((artifact, index) => (
                <article className="coordination-output-item coordination-output-item--artifact" key={`${artifactLabel(artifact)}:${index}`}>
                  <div className="coordination-output-item__meta">
                    <strong>{artifactLabel(artifact)}</strong>
                    <span>{text(artifact.producer_node_id, "未标注节点")}</span>
                  </div>
                </article>
              ))
            ) : (
              <p>暂无产物引用。</p>
            )}
          </div>
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span>{model.healthValid ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />} 健康检查</span>
            <strong>{model.healthValid ? "通过" : `${model.healthIssues.length} 个问题`}</strong>
          </div>
          <div className="coordination-handoff-list">
            {model.healthIssues.length ? (
              model.healthIssues.map((issue) => (
                <article className="coordination-handoff-item" key={`${issue.code}:${issue.targetId}`}>
                  <div>
                    <strong>{issue.code}</strong>
                    <span>{issue.severity} · {issue.targetId}</span>
                  </div>
                  <small>{issue.message}</small>
                </article>
              ))
            ) : (
              <p className="coordination-contract-empty">拓扑、运行态与边端点检查通过。</p>
            )}
          </div>
        </article>
      </section>
    </div>
  );
}
