"use client";

import { AlertTriangle, CheckCircle2, Clock3, Database, FileText, Network } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CoordinationTopologyGraph } from "@/components/coordination/CoordinationTopologyGraph";
import { loadFile, type TaskGraphRunMonitorView } from "@/lib/api";
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

function artifactPath(item: Record<string, unknown>) {
  const raw = text(item.artifact_ref) || text(item.ref) || text(item.path);
  if (!raw) return "";
  return raw.startsWith("artifact:") ? raw.slice("artifact:".length) : raw;
}

function readablePreview(content: string, maxLength = 2400) {
  const normalized = content.replace(/\r\n/g, "\n").trim();
  if (!normalized) return "";
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength).trimEnd()}\n\n...`;
}

type ArtifactPreviewItem = {
  ref: string;
  path: string;
  producerNodeId: string;
  content: string;
  error: string;
};

function collectRecentArtifacts(
  artifacts: Array<Record<string, unknown>>,
  limit: number,
  filter?: (artifact: Record<string, unknown>) => boolean,
) {
  const seen = new Set<string>();
  const collected: Array<{ ref: string; path: string; producerNodeId: string }> = [];
  for (const artifact of [...artifacts].reverse()) {
    if (filter && !filter(artifact)) {
      continue;
    }
    const ref = artifactLabel(artifact);
    const path = artifactPath(artifact);
    const producerNodeId = text(artifact.producer_node_id);
    const key = path || ref;
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    if (!path) {
      continue;
    }
    collected.push({ ref, path, producerNodeId });
    if (collected.length >= limit) {
      break;
    }
  }
  return collected;
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
  const selectedNodeArtifacts = useMemo(() => {
    if (!selectedNode) {
      return [];
    }
    return collectRecentArtifacts(model.artifacts, 3, (artifact) => {
      const path = artifactPath(artifact);
      const producerNodeId = text(artifact.producer_node_id);
      return (
        producerNodeId === selectedNode.id
        || (!!path && selectedNode.artifactRefs.includes(`artifact:${path}`))
        || (!!path && selectedNode.artifactRefs.includes(path))
      );
    });
  }, [model.artifacts, selectedNode]);
  const recentArtifactFeed = useMemo(
    () => collectRecentArtifacts(model.artifacts, 6),
    [model.artifacts],
  );
  const [artifactPreviewState, setArtifactPreviewState] = useState<{
    loading: boolean;
    items: ArtifactPreviewItem[];
  }>({
    loading: false,
    items: [],
  });
  const [recentPreviewState, setRecentPreviewState] = useState<{
    loading: boolean;
    items: ArtifactPreviewItem[];
  }>({
    loading: false,
    items: [],
  });
  const progress = model.nodeCount ? Math.round((model.completedCount / model.nodeCount) * 100) : 0;

  useEffect(() => {
    let cancelled = false;
    const candidates = [...selectedNodeArtifacts];
    if (!candidates.length) {
      setArtifactPreviewState({ loading: false, items: [] });
      return () => {
        cancelled = true;
      };
    }
    setArtifactPreviewState((prev) => ({ ...prev, loading: true }));
    void Promise.all(
      candidates.map(async (artifact) => {
        try {
          const file = await loadFile(artifact.path);
          return {
            ...artifact,
            content: readablePreview(file.content),
            error: "",
          };
        } catch (error) {
          return {
            ...artifact,
            content: "",
            error: error instanceof Error ? error.message : "读取正文失败",
          };
        }
      })
    ).then((items) => {
      if (cancelled) {
        return;
      }
      setArtifactPreviewState({
        loading: false,
        items,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [selectedNodeArtifacts]);

  useEffect(() => {
    let cancelled = false;
    if (!recentArtifactFeed.length) {
      setRecentPreviewState({ loading: false, items: [] });
      return () => {
        cancelled = true;
      };
    }
    setRecentPreviewState((prev) => ({ ...prev, loading: true }));
    void Promise.all(
      recentArtifactFeed.map(async (artifact) => {
        try {
          const file = await loadFile(artifact.path);
          return {
            ...artifact,
            content: readablePreview(file.content, 1800),
            error: "",
          };
        } catch (error) {
          return {
            ...artifact,
            content: "",
            error: error instanceof Error ? error.message : "读取正文失败",
          };
        }
      }),
    ).then((items) => {
      if (cancelled) {
        return;
      }
      setRecentPreviewState({
        loading: false,
        items,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [recentArtifactFeed]);

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
            <span>时序 Clock</span>
            <strong>{model.timelineClockSeq || model.eventCount}</strong>
            <em>{model.timelineEventCount ? `${model.timelineEventCount} 个语义事件` : model.coordinationRunId || model.taskRunId}</em>
          </article>
          <article className="coordination-session__statuspill">
            <span>项目累计进度</span>
            <strong>{model.completedMetricTotal} / {model.targetMetricTotal || 0}</strong>
            <em>跨 run 已提交 {model.committedUnitCount} 个单元 · {model.progressMetricLabel}</em>
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
        <article className="coordination-overview-card">
          <span>监督状态</span>
          <strong>{model.projectRuntimeStatus || "watching"}</strong>
          <em>{model.blockerSummary || `剩余 ${model.remainingMetricTotal} ${model.progressMetricLabel}`}</em>
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
        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><Clock3 size={14} /> 时序账本</span>
            <strong>{model.timelineClockSeq ? `clock ${model.timelineClockSeq}` : "未建立"}</strong>
          </div>
          <div className="coordination-handoff-list">
            {model.timelineEvents.length ? (
              model.timelineEvents.slice(-8).reverse().map((event, index) => (
                <article className="coordination-handoff-item" key={`${text(event.event_id)}:${index}`}>
                  <div>
                    <strong>{text(event.event_type, "timeline_event")}</strong>
                    <span>
                      #{Number(event.clock_seq ?? 0)} · {Array.isArray(event.scope_path) ? event.scope_path.join(" / ") : text(event.scope_path, "run")}
                    </span>
                  </div>
                  <small>{text(event.node_id) || text(event.result_record_id) || text(event.checkpoint_ref) || text(event.status)}</small>
                </article>
              ))
            ) : (
              <p className="coordination-contract-empty">还没有语义时序事件。</p>
            )}
          </div>
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><Network size={14} /> 当前交接包</span>
            <strong>{text(model.dispatchContext.dispatch_event_id) ? "已装配" : "暂无派发"}</strong>
          </div>
          <div className="coordination-handoff-list">
            <article className="coordination-handoff-item">
              <div>
                <strong>Dispatch</strong>
                <span>{text(model.dispatchContext.dispatch_event_id, "未生成")}</span>
              </div>
              <small>clock {Number(model.dispatchContext.clock_seq ?? 0)} · {Array.isArray(model.dispatchContext.scope_path) ? model.dispatchContext.scope_path.join(" / ") : "run"}</small>
            </article>
            {[
              ["记忆快照", model.contextPackets.memory_snapshot],
              ["产物上下文", model.contextPackets.artifact_context_packet],
              ["返修包", model.contextPackets.revision_packet],
            ].map(([label, packet]) => {
              const body = packet && typeof packet === "object" && !Array.isArray(packet) ? packet as Record<string, unknown> : {};
              const packetId = text(body.packet_id) || text(body.snapshot_id) || text(body.revision_packet_id);
              return (
                <article className="coordination-handoff-item" key={String(label)}>
                  <div>
                    <strong>{String(label)}</strong>
                    <span>{packetId || "未命中"}</span>
                  </div>
                  <small>
                    {Array.isArray(body.artifact_refs)
                      ? `${body.artifact_refs.length} 个产物引用`
                      : Array.isArray(body.resolved_record_refs)
                        ? `${body.resolved_record_refs.length} 条记忆引用`
                        : text(body.review_verdict, "无附加包")}
                  </small>
                </article>
              );
            })}
          </div>
        </article>

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
            <span><FileText size={14} /> 实时正文流</span>
            <strong>
              {model.streamEnabled
                ? `${model.streamChunkCount} 片 / ${model.streamAccumulatedChars} 字`
                : "当前节点未启用"}
            </strong>
          </div>
          <div className="coordination-handoff-list">
            {model.streamEnabled ? (
              model.streamPreviewText ? (
                <article className="coordination-handoff-item">
                  <div>
                    <strong>{selectedNode?.title || "当前节点"}</strong>
                    <span>{model.streamLatestAt ? `最近更新 ${new Date(model.streamLatestAt * 1000).toLocaleTimeString()}` : "流式进行中"}</span>
                  </div>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 320,
                      overflowY: "auto",
                      margin: 0,
                    }}
                  >
                    {model.streamPreviewText}
                  </pre>
                </article>
              ) : (
                <p className="coordination-contract-empty">节点已启用流式，但还没有收到正文分片。</p>
              )
            ) : (
              <p className="coordination-contract-empty">这个节点当前不走实时正文流，完成后只显示正式产物。</p>
            )}
          </div>
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><FileText size={14} /> 节点正文</span>
            <strong>
              {selectedNode
                ? (artifactPreviewState.loading
                  ? "读取中"
                  : artifactPreviewState.items.length
                    ? `${artifactPreviewState.items.length} 份预览`
                    : "暂无正文")
                : "未选择节点"}
            </strong>
          </div>
          <div className="coordination-handoff-list">
            {!selectedNode ? (
              <p className="coordination-contract-empty">选中节点后，这里会显示该节点最新产物正文。</p>
            ) : artifactPreviewState.loading ? (
              <p className="coordination-contract-empty">正在读取该节点最新正文产物...</p>
            ) : artifactPreviewState.items.length ? (
              artifactPreviewState.items.map((item) => (
                <article className="coordination-handoff-item" key={item.ref || item.path}>
                  <div>
                    <strong>{item.ref || item.path}</strong>
                    <span>{item.producerNodeId || selectedNode.id}</span>
                  </div>
                  {item.error ? (
                    <small>{item.error}</small>
                  ) : (
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        maxHeight: 320,
                        overflowY: "auto",
                        margin: 0,
                      }}
                    >
                      {item.content || "文件为空。"}
                    </pre>
                  )}
                </article>
              ))
            ) : (
              <p className="coordination-contract-empty">该节点当前没有可预览的正文产物。</p>
            )}
          </div>
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><FileText size={14} /> 最近节点正文流</span>
            <strong>
              {recentPreviewState.loading
                ? "读取中"
                : recentPreviewState.items.length
                  ? `${recentPreviewState.items.length} 份保留`
                  : "暂无正文"}
            </strong>
          </div>
          <div className="coordination-handoff-list">
            {recentPreviewState.loading ? (
              <p className="coordination-contract-empty">正在读取最近节点正文...</p>
            ) : recentPreviewState.items.length ? (
              recentPreviewState.items.map((item) => (
                <article className="coordination-handoff-item" key={`recent:${item.ref || item.path}`}>
                  <div>
                    <strong>{item.ref || item.path}</strong>
                    <span>{item.producerNodeId || "unknown-node"}</span>
                  </div>
                  {item.error ? (
                    <small>{item.error}</small>
                  ) : (
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        maxHeight: 220,
                        overflowY: "auto",
                        margin: 0,
                      }}
                    >
                      {item.content || "文件为空。"}
                    </pre>
                  )}
                </article>
              ))
            ) : (
              <p className="coordination-contract-empty">最近还没有可保留的节点正文。</p>
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
