"use client";

import { ArrowUp, Network, Sparkles, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { TaskGraphRunMonitorPanel } from "@/components/task-graph-monitor/TaskGraphRunMonitorPanel";
import {
  getTaskSystemOverview,
  getTaskGraphRunMonitor,
  startTaskGraphRuntimeLoopRun,
  type TaskGraphRunMonitorView,
  type TaskSystemOverview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

import {
  buildCenterWorkspaceTaskGraphInitialInputs,
  centerWorkspaceGraphLabel,
  centerWorkspaceGraphSubtitle,
  centerWorkspaceTaskGraphSessionId,
  listCenterWorkspaceTaskGraphs,
  resolveCenterWorkspaceSelectedGraphId,
  type CenterWorkspaceLayer,
} from "./centerWorkspaceHelpers";

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
  const [taskMessage, setTaskMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [runMonitor, setRunMonitor] = useState<TaskGraphRunMonitorView | null>(null);

  const taskGraphs = useMemo(() => listCenterWorkspaceTaskGraphs(overview), [overview]);
  const selectedGraph = useMemo(() => {
    if (!taskGraphs.length) return null;
    return taskGraphs.find((graph) => graph.graph_id === selectedGraphId) ?? taskGraphs[0] ?? null;
  }, [selectedGraphId, taskGraphs]);
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
      const result = await startTaskGraphRuntimeLoopRun(graphId, {
        session_id: sessionId,
        initial_inputs: initialInputs,
        require_published: true,
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
          <div className="center-workspace__graph-body">
            <section className="center-workspace__launchpad" aria-label="任务图选择">
              <header className="center-workspace__launchpad-head">
                <div>
                  <span>当前任务图</span>
                  <strong>{selectedGraph ? (selectedGraph.title || selectedGraph.graph_id) : "选择任务图"}</strong>
                </div>
                <div className="center-workspace__launchpad-meta">
                  <span>{loadingOverview ? "读取中" : `${taskGraphs.length} 个任务图`}</span>
                  <span>{boundTaskRunId ? `已绑定 ${boundTaskRunId}` : "尚未绑定运行"}</span>
                </div>
              </header>

              {overviewError ? <div className="center-workspace__notice center-workspace__notice--error">{overviewError}</div> : null}
              {startError ? <div className="center-workspace__notice center-workspace__notice--error">{startError}</div> : null}

              <div className="center-workspace__graph-list">
                {loadingOverview ? (
                  <div className="center-workspace__empty">
                    <Network size={18} />
                    <strong>正在读取任务图</strong>
                    <span>任务图列表加载完成后，可以直接发送任务目标。</span>
                  </div>
                ) : taskGraphs.length ? taskGraphs.map((graph) => {
                  const active = graph.graph_id === selectedGraph?.graph_id;
                  return (
                    <button
                      className={active ? "center-workspace__graph-card center-workspace__graph-card--active" : "center-workspace__graph-card"}
                      key={graph.graph_id}
                      onClick={() => setSelectedGraphId(graph.graph_id)}
                      type="button"
                    >
                      <strong>{centerWorkspaceGraphLabel(graph)}</strong>
                      <span>{centerWorkspaceGraphSubtitle(graph)}</span>
                      <small>{graph.node_count ?? graph.nodes?.length ?? 0} 节点 · {graph.edge_count ?? graph.edges?.length ?? 0} 边</small>
                    </button>
                  );
                }) : (
                  <div className="center-workspace__empty">
                    <Network size={18} />
                    <strong>没有可用任务图</strong>
                    <span>后端任务图列表为空，或者当前工作区还没有加载到可启动对象。</span>
                  </div>
                )}
              </div>

              {selectedGraph ? (
                <section className="center-workspace__summary">
                  <article>
                    <span>当前图</span>
                    <strong>{selectedGraph.title || selectedGraph.graph_id}</strong>
                    <em>{selectedGraph.graph_id}</em>
                  </article>
                  <article>
                    <span>发布状态</span>
                    <strong>{selectedGraph.publish_state}</strong>
                    <em>{selectedGraph.enabled ? "可用" : "停用"}</em>
                  </article>
                  <article>
                    <span>拓扑</span>
                    <strong>{selectedGraph.node_count ?? selectedGraph.nodes?.length ?? 0} / {selectedGraph.edge_count ?? selectedGraph.edges?.length ?? 0}</strong>
                    <em>节点 / 边</em>
                  </article>
                </section>
              ) : null}
            </section>

            <section className="center-workspace__monitor" aria-label="任务图运行视图">
              {activeMonitor ? (
                <TaskGraphRunMonitorPanel monitor={activeMonitor} />
              ) : (
                <div className="center-workspace__monitor-empty">
                  <Network size={20} />
                  <strong>{selectedGraph ? "等待任务图运行监控" : "先选择一个任务图"}</strong>
                  <span>{selectedGraph ? "在下方输入任务目标并发送，当前任务图会自动初始化运行。" : "左侧选择一个任务图，然后输入任务目标。"}</span>
                </div>
              )}
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
              <div className="center-workspace__composer-target">
                <Workflow size={14} />
                <span>{selectedGraph ? `发送到 ${selectedGraph.title || selectedGraph.graph_id}` : "未选择任务图"}</span>
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
