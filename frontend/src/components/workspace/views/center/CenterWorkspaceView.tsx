"use client";

import { ArrowUp, Circle, GitBranch, Network, Sparkles, Workflow } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { CoordinationTopologyGraph, type CoordinationTopologyEdge, type CoordinationTopologyNode } from "@/components/coordination/CoordinationTopologyGraph";
import {
  getTaskSystemOverview,
  getTaskSystemTaskGraph,
  getTaskGraphRunMonitor,
  startTaskGraphHarnessRun,
  type TaskGraphRecord,
  type TaskGraphRunMonitorView,
  type TaskSystemOverview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

import {
  buildCenterWorkspaceTaskGraphInitialInputs,
  centerWorkspaceTaskGraphSessionId,
  centerWorkspaceTaskEnvironmentId,
  centerWorkspaceTaskEnvironmentLabelFromOverview,
  listCenterWorkspaceTaskGraphs,
  resolveCenterWorkspaceSelectedGraphId,
  type CenterWorkspaceLayer,
} from "./centerWorkspaceHelpers";

const GRAPH_PANEL_WIDTH_KEY = "centerWorkspace.taskGraph.leftPanelRatio";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function CenterWorkspaceView() {
  const {
    bindTaskGraphMonitorRun,
    currentSessionId,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphMonitorBinding,
  } = useAppStore();
  const [layer, setLayer] = useState<CenterWorkspaceLayer>("chat");
  const [overview, setOverview] = useState<TaskSystemOverview | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [overviewError, setOverviewError] = useState("");
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [selectedGraphDetail, setSelectedGraphDetail] = useState<TaskGraphRecord | null>(null);
  const [selectedGraphDetailError, setSelectedGraphDetailError] = useState("");
  const [taskMessage, setTaskMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [runMonitor, setRunMonitor] = useState<TaskGraphRunMonitorView | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [graphPanelRatio, setGraphPanelRatio] = useState(0.68);
  const graphBodyRef = useRef<HTMLDivElement | null>(null);

  const taskGraphs = useMemo(() => listCenterWorkspaceTaskGraphs(overview), [overview]);
  const taskEnvironmentIds = useMemo(() => {
    const ids = taskGraphs.map((graph) => centerWorkspaceTaskEnvironmentId(graph));
    return Array.from(new Set(ids));
  }, [taskGraphs]);
  const selectedGraph = useMemo(() => {
    if (!taskGraphs.length) return null;
    const overviewGraph = taskGraphs.find((graph) => graph.graph_id === selectedGraphId) ?? taskGraphs[0] ?? null;
    if (selectedGraphDetail && selectedGraphDetail.graph_id === overviewGraph?.graph_id) {
      return { ...overviewGraph, ...selectedGraphDetail };
    }
    return overviewGraph;
  }, [selectedGraphDetail, selectedGraphId, taskGraphs]);
  const selectedGraphRequestId = useMemo(() => {
    const explicitGraphId = String(selectedGraphId || "").trim();
    if (explicitGraphId) return explicitGraphId;
    return String(taskGraphs[0]?.graph_id || "").trim();
  }, [selectedGraphId, taskGraphs]);
  const selectedTaskEnvironmentId = selectedGraph ? centerWorkspaceTaskEnvironmentId(selectedGraph) : taskEnvironmentIds[0] || "env.general.workspace";
  const selectedEnvironmentGraphs = useMemo(
    () => taskGraphs.filter((graph) => centerWorkspaceTaskEnvironmentId(graph) === selectedTaskEnvironmentId),
    [selectedTaskEnvironmentId, taskGraphs],
  );
  const boundTaskRunId = String(taskGraphMonitorBinding?.task_run_id ?? "").trim();
  const activeMonitor = useMemo(() => {
    const boundGraphId = String(taskGraphMonitorBinding?.graph_id ?? "").trim();
    const liveMonitorGraphId = String(taskGraphBoundRunMonitor?.graph?.graph_id ?? "").trim();
    const runMonitorGraphId = String(runMonitor?.graph?.graph_id ?? "").trim();
    const selectedGraphGraphId = String(selectedGraph?.graph_id ?? "").trim();
    const matchesSelection = !selectedGraphGraphId
      || runMonitorGraphId === selectedGraphGraphId
      || liveMonitorGraphId === selectedGraphGraphId
      || (!selectedGraphGraphId && Boolean(boundGraphId));
    if (runMonitor && matchesSelection) {
      return runMonitor;
    }
    if (taskGraphBoundRunMonitor && (!selectedGraphGraphId || liveMonitorGraphId === selectedGraphGraphId || !boundGraphId || boundGraphId === selectedGraphGraphId)) {
      return taskGraphBoundRunMonitor;
    }
    return null;
  }, [runMonitor, selectedGraph?.graph_id, taskGraphBoundRunMonitor, taskGraphMonitorBinding?.graph_id]);
  const graphDefinitionNodes = useMemo(() => {
    const graphRecord = selectedGraph as (TaskGraphRecord & { graph_nodes?: unknown[] }) | null;
    if (graphRecord?.nodes?.length) return graphRecord.nodes;
    return Array.isArray(graphRecord?.graph_nodes) ? graphRecord.graph_nodes : [];
  }, [selectedGraph]);
  const graphDefinitionEdges = useMemo(() => {
    const graphRecord = selectedGraph as (TaskGraphRecord & { graph_edges?: unknown[] }) | null;
    if (graphRecord?.edges?.length) return graphRecord.edges;
    return Array.isArray(graphRecord?.graph_edges) ? graphRecord.graph_edges : [];
  }, [selectedGraph]);
  const topologyLoading = Boolean(
    selectedGraph
    && !selectedGraphDetail
    && ((selectedGraph.node_count ?? 0) > 0 || (selectedGraph.edge_count ?? 0) > 0)
  );
  const hasTopology = Boolean(activeMonitor || graphDefinitionNodes.length);
  const topologyNodes = useMemo<CoordinationTopologyNode[]>(() => {
    const sourceNodes = activeMonitor?.topology?.nodes?.length
      ? activeMonitor.topology.nodes
      : graphDefinitionNodes;
    return sourceNodes.map((node) => ({
      id: textValue(recordValue(node).node_id),
      title: textValue(recordValue(node).title, textValue(recordValue(node).node_id)),
      agentLabel: textValue(recordValue(node).agent_id || recordValue(node).agent_group_id),
      role: textValue(recordValue(node).role || recordValue(node).task_id || recordValue(node).node_type),
      nodeKind: textValue(recordValue(node).node_type),
      status: textValue(recordValue(node).status) || (textValue(recordValue(node).node_id) === selectedGraph?.entry_node_id ? "ready" : "idle"),
    }));
  }, [activeMonitor?.topology?.nodes, graphDefinitionNodes, selectedGraph?.entry_node_id]);
  const topologyEdges = useMemo<CoordinationTopologyEdge[]>(() => {
    const sourceEdges = activeMonitor?.topology?.edges?.length
      ? activeMonitor.topology.edges
      : graphDefinitionEdges;
    return sourceEdges.map((edge) => ({
      id: textValue(recordValue(edge).edge_id),
      from: textValue(recordValue(edge).source_node_id),
      to: textValue(recordValue(edge).target_node_id),
      label: textValue(recordValue(edge).contract_id || recordValue(edge).payload_contract_id || recordValue(edge).edge_type),
      edgeKind: textValue(recordValue(edge).edge_type),
      status: textValue(recordValue(edge).status, "idle"),
    }));
  }, [activeMonitor?.topology?.edges, graphDefinitionEdges]);
  const informationItems = useMemo(() => buildCenterWorkspaceInformationItems(activeMonitor), [activeMonitor]);
  const activeNodeId = textValue(activeMonitor?.runtime?.active_node_id, selectedGraph?.entry_node_id || "");
  const focusedNodeId = selectedNodeId || activeNodeId;

  useEffect(() => {
    const saved = Number(window.localStorage.getItem(GRAPH_PANEL_WIDTH_KEY));
    if (Number.isFinite(saved) && saved > 0) {
      setGraphPanelRatio(clamp(saved, 0.45, 0.82));
    }
  }, []);

  useEffect(() => {
    if (!focusedNodeId) return;
    const element = document.getElementById(`center-node-output-${cssId(focusedNodeId)}`);
    element?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusedNodeId]);

  function handleGraphPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    const container = graphBodyRef.current;
    if (!container) return;
    event.preventDefault();
    const startX = event.clientX;
    const startRatio = graphPanelRatio;
    let latestRatio = startRatio;
    const rect = container.getBoundingClientRect();
    const pointerId = event.pointerId;
    event.currentTarget.setPointerCapture(pointerId);
    const move = (moveEvent: PointerEvent) => {
      const nextRatio = clamp(startRatio + (moveEvent.clientX - startX) / Math.max(1, rect.width), 0.45, 0.82);
      latestRatio = nextRatio;
      setGraphPanelRatio(nextRatio);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.localStorage.setItem(GRAPH_PANEL_WIDTH_KEY, String(latestRatio));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  useEffect(() => {
    let cancelled = false;
    setLoadingOverview(true);
    setOverviewError("");
    void getTaskSystemOverview()
      .then((value) => {
        if (cancelled) {
          return;
        }
        setOverview(value);
        setSelectedGraphId((current) => resolveCenterWorkspaceSelectedGraphId(value, current));
      })
      .catch((error) => {
        if (!cancelled) {
          setOverviewError(error instanceof Error ? error.message : "任务图列表读取失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingOverview(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const graphId = selectedGraphRequestId;
    if (!graphId) {
      setSelectedGraphDetail(null);
      setSelectedGraphDetailError("");
      return;
    }
    let cancelled = false;
    setSelectedGraphDetailError("");
    void getTaskSystemTaskGraph(graphId)
      .then((graph) => {
        if (!cancelled) {
          setSelectedGraphDetail(graph);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSelectedGraphDetail(null);
          setSelectedGraphDetailError(error instanceof Error ? error.message : "任务图详情读取失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedGraphRequestId]);

  useEffect(() => {
    if (!boundTaskRunId || layer !== "task-graph") {
      return;
    }
    let cancelled = false;
    async function refreshMonitor() {
      const monitor = await getTaskGraphRunMonitor(boundTaskRunId).catch(() => null);
      if (!cancelled && monitor) {
        setRunMonitor(monitor);
      }
    }
    void refreshMonitor();
    const timer = window.setInterval(() => {
      void refreshMonitor();
    }, 1800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [boundTaskRunId, layer]);

  async function handleStartGraph(message: string) {
    const graphId = selectedGraph?.graph_id.trim();
    if (!graphId) {
      setStartError("请先选择一个任务图。");
      return;
    }
    setStarting(true);
    setStartError("");
    try {
      const initialInputs = buildCenterWorkspaceTaskGraphInitialInputs(message, selectedGraph);
      const sessionId = centerWorkspaceTaskGraphSessionId(currentSessionId);
      const result = await startTaskGraphHarnessRun(graphId, {
        session_id: sessionId,
        initial_inputs: initialInputs,
        include_trace: true,
        execute_initial_stage: true,
      });
      const monitor = await getTaskGraphRunMonitor(result.task_run_id).catch(() => null);
      setRunMonitor(monitor);
      bindTaskGraphMonitorRun({
        task_run_id: result.task_run_id,
        coordination_run_id: result.coordination_run_id,
        graph_id: graphId,
        session_id: sessionId,
        title: selectedGraph?.title || graphId,
      });
      setTaskMessage("");
      setTaskGraphRunInteractionOpen(true);
    } catch (error) {
      setStartError(error instanceof Error ? error.message : "任务图启动失败");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="center-workspace" aria-label="中心工作区">
      <header className="center-workspace__tabs" aria-label="中心层级切换">
        <button
          className={layer === "chat" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
          onClick={() => setLayer("chat")}
          type="button"
        >
          <Sparkles size={14} />
          <span>会话层</span>
        </button>
        <button
          className={layer === "task-graph" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
          onClick={() => setLayer("task-graph")}
          type="button"
        >
          <Workflow size={14} />
          <span>图任务层</span>
        </button>
      </header>

      {layer === "chat" ? (
        <div className="center-workspace__chat">
          <ChatPanel />
        </div>
      ) : (
        <div className="center-workspace__graph-layer">
          <div
            className="center-workspace__graph-body"
            ref={graphBodyRef}
            style={{ gridTemplateColumns: `minmax(0, ${graphPanelRatio}fr) 8px minmax(160px, ${1 - graphPanelRatio}fr)` }}
          >
            <section className="center-workspace__structure" aria-label="任务结构">
              <header className="center-workspace__panel-head">
                <div>
                  <span>任务结构</span>
                  <strong>{selectedGraph ? (selectedGraph.title || selectedGraph.graph_id) : "未选择任务"}</strong>
                </div>
                <div className="center-workspace__panel-meta">
                  <span>{loadingOverview ? "读取中" : `${taskGraphs.length} 个任务`}</span>
                  <span>{boundTaskRunId ? "运行已绑定" : "等待启动"}</span>
                </div>
              </header>

              {selectedGraph ? (
                <section className="center-workspace__structure-summary">
                  <span><GitBranch size={13} /> {selectedGraph.node_count ?? selectedGraph.nodes?.length ?? 0} 节点 / {selectedGraph.edge_count ?? selectedGraph.edges?.length ?? 0} 边</span>
                  <span><Circle size={13} /> {selectedGraph.publish_state} · {selectedGraph.enabled ? "可用" : "停用"}</span>
                  <span><Workflow size={13} /> {centerWorkspaceTaskEnvironmentLabelFromOverview(overview, centerWorkspaceTaskEnvironmentId(selectedGraph))}</span>
                </section>
              ) : null}

              {overviewError ? <div className="center-workspace__notice center-workspace__notice--error">{overviewError}</div> : null}
              {startError ? <div className="center-workspace__notice center-workspace__notice--error">{startError}</div> : null}
              {selectedGraphDetailError ? <div className="center-workspace__notice center-workspace__notice--error">{selectedGraphDetailError}</div> : null}

              <div className="center-workspace__structure-canvas">
                {loadingOverview || topologyLoading ? (
                  <div className="center-workspace__empty">
                    <Network size={18} />
                    <strong>正在读取任务结构</strong>
                    <span>任务图详情加载后会显示当前拓扑。</span>
                  </div>
                ) : hasTopology ? (
                  <div className="center-workspace__topology-canvas">
                    <CoordinationTopologyGraph
                      currentNodeId={activeNodeId}
                      enablePan
                      edges={topologyEdges}
                      emptyDescription="当前具体任务没有可渲染的节点和边。"
                      emptyTitle="当前任务没有拓扑"
                      nodes={topologyNodes}
                      onSelectNode={(nodeId) => setSelectedNodeId(nodeId)}
                      selectedNodeId={focusedNodeId}
                      viewportPadding={32}
                    />
                  </div>
                ) : (
                  <div className="center-workspace__empty">
                    <Network size={18} />
                    <strong>没有可用任务</strong>
                    <span>后端任务列表为空，或者当前工作区还没有加载到可启动对象。</span>
                  </div>
                )}
              </div>

              <div className="center-workspace__selected-graph-id">{selectedGraph ? selectedGraph.graph_id : "未绑定任务图"}</div>
            </section>

            <div
              aria-label="调整拓扑和节点输出宽度"
              className="center-workspace__graph-resize"
              onPointerDown={handleGraphPanelResize}
              role="separator"
            />

            <section className="center-workspace__monitor" aria-label="任务图运行视图">
              <header className="center-workspace__panel-head center-workspace__panel-head--monitor">
                <div>
                  <span>节点输出</span>
                  <strong>{activeMonitor ? "实时监控" : "等待运行"}</strong>
                </div>
              <div className="center-workspace__panel-meta">
                  <span>{activeMonitor ? "实时" : "未启动"}</span>
                  <span>{informationItems.length ? `${informationItems.length} 条` : "无记录"}</span>
                </div>
              </header>
              <div className="center-workspace__info-stream">
                {informationItems.length ? informationItems.map((item) => (
                  <article
                    className={[
                      `center-workspace__info-item center-workspace__info-item--${item.level}`,
                      item.nodeId && item.nodeId === focusedNodeId ? "center-workspace__info-item--selected" : "",
                    ].filter(Boolean).join(" ")}
                    id={item.nodeId ? `center-node-output-${cssId(item.nodeId)}` : undefined}
                    key={item.id}
                    onClick={() => item.nodeId ? setSelectedNodeId(item.nodeId) : undefined}
                  >
                    <span>{item.label}</span>
                    <strong>{item.title}</strong>
                    {item.body ? <p>{item.body}</p> : null}
                  </article>
                )) : (
                  <div className="center-workspace__monitor-empty">
                    <Network size={20} />
                    <strong>{selectedGraph ? "等待运行输出" : "先选择一个任务"}</strong>
                    <span>{selectedGraph ? "运行后这里显示各节点的输出、结果引用和产物。" : "先在底部选择任务环境和具体任务。"}</span>
                  </div>
                )}
              </div>
            </section>
          </div>

          <form
            className="center-workspace__composer chat-input-panel chat-input-panel--inline"
            onSubmit={(event) => {
              event.preventDefault();
              const nextValue = taskMessage.trim();
              if (!nextValue || starting) {
                return;
              }
              void handleStartGraph(nextValue);
            }}
          >
            <div className="chat-input-panel__composer">
              <textarea
                className="chat-input-panel__textarea"
                disabled={starting || !selectedGraph}
                onChange={(event) => setTaskMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (starting || !selectedGraph) {
                    return;
                  }
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                    event.preventDefault();
                    const nextValue = taskMessage.trim();
                    if (!nextValue) {
                      return;
                    }
                    void handleStartGraph(nextValue);
                  }
                }}
                placeholder="输入图任务目标，Cmd/Ctrl + Enter 发送"
                value={taskMessage}
              />
            </div>
            <div className="center-workspace__composer-footer">
              <div className="center-workspace__composer-target" aria-label="任务选择">
                <label>
                  <span>任务环境</span>
                  <select
                    disabled={starting || loadingOverview || !taskEnvironmentIds.length}
                    onChange={(event) => {
                      const nextEnvironmentId = event.target.value;
                      const nextGraph = taskGraphs.find((graph) => centerWorkspaceTaskEnvironmentId(graph) === nextEnvironmentId);
                      setSelectedGraphId(nextGraph?.graph_id || "");
                    }}
                    value={selectedTaskEnvironmentId}
                  >
                    {taskEnvironmentIds.map((environmentId) => (
                      <option key={environmentId} value={environmentId}>{centerWorkspaceTaskEnvironmentLabelFromOverview(overview, environmentId)}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>具体任务</span>
                  <select
                    disabled={starting || loadingOverview || !selectedEnvironmentGraphs.length}
                    onChange={(event) => setSelectedGraphId(event.target.value)}
                    value={selectedGraph?.graph_id || ""}
                  >
                    {selectedEnvironmentGraphs.map((graph) => (
                      <option key={graph.graph_id} value={graph.graph_id}>{graph.title || graph.graph_id}</option>
                    ))}
                  </select>
                </label>
              </div>
              <button
                aria-label="发送图任务"
                className="chat-send-button disabled:cursor-not-allowed disabled:opacity-50"
                disabled={starting || !selectedGraph || !taskMessage.trim()}
                type="submit"
              >
                <ArrowUp size={18} />
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}

type CenterWorkspaceInformationItem = {
  id: string;
  label: string;
  title: string;
  body: string;
  level: "normal" | "warning" | "error" | "success";
  nodeId?: string;
};

function buildCenterWorkspaceInformationItems(monitor: TaskGraphRunMonitorView | null): CenterWorkspaceInformationItem[] {
  if (!monitor) return [];
  const items: CenterWorkspaceInformationItem[] = [];
  const failure = recordValue(monitor.runtime?.failure);
  const failureMessage = textValue(failure.message);
  if (failureMessage) {
    items.push({
      id: "failure",
      label: "错误",
      title: textValue(failure.code) || "运行异常",
      body: failureMessage,
      level: "error",
      nodeId: textValue(failure.stage_id || failure.step_id),
    });
  }
  const resultsByNode = new Map((monitor.stage_results || []).map((result) => [textValue(result.node_id), recordValue(result)]));
  const artifactsByNode = new Map<string, string[]>();
  for (const artifact of monitor.artifacts || []) {
    const producerNodeId = textValue(artifact.producer_node_id);
    const artifactRef = textValue(artifact.artifact_ref || artifact.path || artifact.ref);
    if (!producerNodeId || !artifactRef) continue;
    artifactsByNode.set(producerNodeId, [...(artifactsByNode.get(producerNodeId) || []), artifactRef]);
  }
  const timelineResultByNode = new Map<string, Record<string, unknown>>();
  for (const record of monitor.timeline_result_records || []) {
    const item = recordValue(record);
    const nodeId = textValue(item.node_id || item.stage_id || item.producer_node_id);
    if (nodeId) timelineResultByNode.set(nodeId, item);
  }
  const activeNodeId = textValue(monitor.runtime?.active_node_id);
  const streamPreview = textValue(monitor.streaming?.preview_text);
  for (const node of monitor.topology?.nodes || []) {
    const nodeId = textValue(node.node_id);
    if (!nodeId) continue;
    const result = resultsByNode.get(nodeId) || {};
    const timelineResult = timelineResultByNode.get(nodeId) || recordValue(result.timeline_result_record);
    const artifactRefs = [
      ...arrayTextValue(result.artifact_refs),
      ...(artifactsByNode.get(nodeId) || []),
    ];
    const workingMemoryRefs = arrayTextValue(result.working_memory_refs);
    const taskResultRef = textValue(result.task_result_ref || result.agent_run_result_ref || timelineResult.result_ref || timelineResult.artifact_ref);
    const accepted = result.accepted === true || timelineResult.accepted === true;
    const status = textValue(node.status || result.status, nodeId === activeNodeId ? "running" : "pending");
    const bodyParts = [
      nodeId === activeNodeId && streamPreview ? streamPreview : "",
      taskResultRef ? `结果 ${taskResultRef}` : "",
      artifactRefs.length ? `产物 ${artifactRefs.slice(-3).join(", ")}` : "",
      workingMemoryRefs.length ? `记忆 ${workingMemoryRefs.slice(-3).join(", ")}` : "",
    ].filter(Boolean);
    items.push({
      id: `node:${nodeId}`,
      label: "节点",
      title: textValue(node.title, nodeId),
      body: bodyParts.join("\n"),
      level: status === "failed" ? "error" : accepted || status === "completed" ? "success" : status === "running" ? "warning" : "normal",
      nodeId,
    });
  }
  return items.slice(0, 12);
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function textValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function arrayTextValue(value: unknown) {
  return Array.isArray(value) ? value.map((item) => textValue(item)).filter(Boolean) : [];
}

function cssId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "_");
}
