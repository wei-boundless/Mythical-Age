"use client";

import { Activity, CheckCircle2, GripHorizontal, Minimize2, PlayCircle, RefreshCw, TriangleAlert, X } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { GraphRunMonitorView } from "@/lib/api";
import type { TaskGraphMonitorBinding } from "@/lib/store/types";

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

function numberValue(value: unknown) {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? next : 0;
}

function textValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function formatClock(seconds: number) {
  if (!seconds) return "暂无更新";
  return new Date(seconds * 1000).toLocaleTimeString();
}

function compactId(value: string, left = 18, right = 8) {
  if (!value) return "";
  if (value.length <= left + right + 3) return value;
  return `${value.slice(0, left)}...${value.slice(-right)}`;
}

function latestMonitorTime(monitor: GraphRunMonitorView | null) {
  const graphRun = recordValue(monitor?.graph_run);
  const taskRun = recordValue(monitor?.task_run);
  const events = Array.isArray(monitor?.events) ? monitor.events : [];
  const latestEventAt = events.reduce((max, event) => Math.max(max, numberValue(recordValue(event).created_at)), 0);
  return Math.max(numberValue(graphRun.updated_at), numberValue(taskRun.updated_at), latestEventAt);
}

function configNodes(monitor: GraphRunMonitorView | null) {
  return recordArray(recordValue(monitor?.graph_harness_config).nodes);
}

function loopState(monitor: GraphRunMonitorView | null) {
  return recordValue(monitor?.graph_loop_state);
}

function runtimeMonitor(monitor: GraphRunMonitorView | null) {
  return recordValue(monitor?.task_run_monitor || monitor?.runtime_monitor);
}

function nodeStatusMap(state: Record<string, unknown>) {
  const statuses = new Map<string, string>();
  for (const nodeId of stringArray(state.ready_node_ids)) statuses.set(nodeId, "ready");
  for (const nodeId of stringArray(state.running_node_ids)) statuses.set(nodeId, "running");
  for (const nodeId of stringArray(state.completed_node_ids)) statuses.set(nodeId, "completed");
  for (const nodeId of stringArray(state.failed_node_ids)) statuses.set(nodeId, "failed");
  for (const nodeId of stringArray(state.blocked_node_ids)) statuses.set(nodeId, "blocked");
  return statuses;
}

function statusLabel(status: string, loading: boolean) {
  if (loading) return "正在刷新";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "created") return "已创建";
  if (status === "blocked") return "阻塞";
  return status || "等待绑定";
}

export function TaskGraphRunInteractionDock({
  actionLoading,
  binding,
  error,
  monitor,
  monitorLoading,
  onClear,
  onContinue,
  onEvaluate,
  onOpenChange,
  open,
}: {
  actionLoading: boolean;
  binding: TaskGraphMonitorBinding | null;
  error: string;
  monitor: GraphRunMonitorView | null;
  monitorLoading: boolean;
  onClear: () => void;
  onContinue: () => void;
  onEvaluate: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  const [ready, setReady] = useState(false);
  const [position, setPosition] = useState({ x: 24, y: 120 });
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const suppressClickRef = useRef(false);

  const state = useMemo(() => loopState(monitor), [monitor]);
  const nodes = useMemo(() => configNodes(monitor), [monitor]);
  const statuses = useMemo(() => nodeStatusMap(state), [state]);
  const readyNodeIds = stringArray(state.ready_node_ids);
  const runningNodeIds = stringArray(state.running_node_ids);
  const completedNodeIds = stringArray(state.completed_node_ids);
  const failedNodeIds = stringArray(state.failed_node_ids);
  const blockedNodeIds = stringArray(state.blocked_node_ids);
  const activeOrders = Array.isArray(monitor?.active_node_work_orders) ? monitor.active_node_work_orders : [];
  const taskRunMonitor = useMemo(() => runtimeMonitor(monitor), [monitor]);
  const graphRunId = textValue(binding?.graph_run_id || monitor?.graph_run_id);
  const graphHarnessConfigId = textValue(binding?.graph_harness_config_id || state.config_id);
  const taskRunId = textValue(binding?.task_run_id || taskRunMonitor.task_run_id || recordValue(monitor?.task_run).task_run_id);
  const graphId = textValue(binding?.graph_id || state.graph_id || recordValue(monitor?.graph_run).graph_id);
  const runtimeStatus = textValue(taskRunMonitor.lifecycle || taskRunMonitor.status || state.status || recordValue(monitor?.graph_run).status);
  const boundLabel = binding?.title || graphId || (graphRunId ? compactId(graphRunId) : "未绑定 GraphRun");
  const latestAt = latestMonitorTime(monitor);
  const lastUpdatedLabel = formatClock(latestAt);
  const needsAttention = failedNodeIds.length > 0 || blockedNodeIds.length > 0 || Boolean(error);

  function getBoxSize(isOpen = open) {
    return {
      width: isOpen ? Math.min(430, window.innerWidth - 16) : 196,
      height: isOpen ? Math.min(620, window.innerHeight - 16) : 56,
    };
  }

  function clampPosition(next: { x: number; y: number }, isOpen = open) {
    const { width, height } = getBoxSize(isOpen);
    return {
      x: Math.max(8, Math.min(window.innerWidth - width - 8, next.x)),
      y: Math.max(8, Math.min(window.innerHeight - height - 8, next.y)),
    };
  }

  useEffect(() => {
    setMounted(true);
    try {
      const saved = window.localStorage.getItem("task-graph-run-interaction-dock-position");
      if (saved) {
        const parsed = JSON.parse(saved) as { x?: number; y?: number };
        if (Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) {
          setPosition(clampPosition({ x: Number(parsed.x), y: Number(parsed.y) }, false));
          setReady(true);
          return;
        }
      }
    } catch {
      // Local position is convenience state only.
    }
    setPosition(clampPosition({ x: Math.max(24, window.innerWidth - 560), y: 124 }, false));
    setReady(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready) return;
    setPosition((current) => clampPosition(current, open));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready]);

  useEffect(() => {
    if (!ready) return;
    try {
      window.localStorage.setItem("task-graph-run-interaction-dock-position", JSON.stringify(position));
    } catch {
      // Dragging should still work when storage is unavailable.
    }
  }, [position, ready]);

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const drag = dragRef.current;
      if (!drag || event.pointerId !== drag.pointerId) return;
      const deltaX = event.clientX - drag.startX;
      const deltaY = event.clientY - drag.startY;
      if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
        drag.moved = true;
      }
      setPosition(clampPosition({ x: drag.originX + deltaX, y: drag.originY + deltaY }));
    }

    function handlePointerUp(event: PointerEvent) {
      const drag = dragRef.current;
      if (drag?.pointerId !== event.pointerId) return;
      suppressClickRef.current = drag.moved;
      dragRef.current = null;
      if (!open && !drag.moved) {
        onOpenChange(true);
      }
      window.setTimeout(() => {
        suppressClickRef.current = false;
      }, 0);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onOpenChange]);

  useEffect(() => {
    function handleResize() {
      setPosition((current) => clampPosition(current));
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function beginDrag(event: ReactPointerEvent) {
    if (open && (event.target as HTMLElement).closest("button, input, summary")) {
      return;
    }
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
      moved: false,
    };
  }

  if (!mounted || (!open && !binding && !monitor)) {
    return null;
  }

  const launcher = (
    <aside
      className={needsAttention ? "health-agent-launcher task-graph-run-interaction-launcher task-graph-run-interaction-launcher--attention" : "health-agent-launcher task-graph-run-interaction-launcher"}
      onPointerDown={beginDrag}
      style={{ left: position.x, opacity: ready ? 1 : 0, top: position.y }}
    >
      <button
        onClick={() => {
          if (!suppressClickRef.current) {
            onOpenChange(true);
          }
        }}
        type="button"
      >
        {needsAttention ? <TriangleAlert size={18} /> : <Activity size={18} />}
        <span>{needsAttention ? "图运行需处理" : graphRunId ? "图运行监控" : "监控待绑定"}</span>
      </button>
      <div className="task-graph-run-interaction-launcher__body">
        <strong>{boundLabel}</strong>
        <span>{runtimeStatus || "idle"} · {lastUpdatedLabel}</span>
        <small>Ready {readyNodeIds.length} / Running {runningNodeIds.length}</small>
      </div>
      <GripHorizontal size={15} />
    </aside>
  );

  const dock = (
    <aside className="health-agent-dock task-graph-run-interaction-dock" style={{ left: position.x, opacity: ready ? 1 : 0, top: position.y }}>
      <header onPointerDown={beginDrag}>
        <div>
          <span>GraphRun 监控</span>
          <strong>{statusLabel(runtimeStatus, monitorLoading)}</strong>
          <em>{boundLabel}</em>
        </div>
        <div className="health-agent-dock__window-controls">
          <GripHorizontal size={15} />
          <button aria-label="折叠图运行监控窗口" onClick={() => onOpenChange(false)} type="button">
            <Minimize2 size={16} />
          </button>
          <button aria-label="解除当前图运行监控绑定" onClick={onClear} type="button">
            <X size={16} />
          </button>
        </div>
      </header>

      <div className="health-agent-dock__scope">
        <CheckCircle2 size={15} />
        <span>这个窗口只绑定 GraphRun。它展示 GraphLoop 状态和 work order，不生成监督决策，也不接管任务语义。</span>
      </div>

      <section className="task-graph-run-interaction-status">
        <div><span>Ready</span><strong>{readyNodeIds.length}</strong></div>
        <div><span>Running</span><strong>{runningNodeIds.length}</strong></div>
        <div><span>Done</span><strong>{completedNodeIds.length}</strong></div>
        <div><span>Failed</span><strong>{failedNodeIds.length}</strong></div>
        <div><span>Blocked</span><strong>{blockedNodeIds.length}</strong></div>
        <div><span>WorkOrder</span><strong>{monitor?.active_node_work_order_count ?? activeOrders.length}</strong></div>
        <div><span>事件</span><strong>{monitor?.event_count ?? 0}</strong></div>
        <div><span>最近更新</span><strong>{lastUpdatedLabel}</strong></div>
      </section>

      <div className="health-agent-dock__messages">
        {error ? (
          <article className="health-agent-message task-graph-run-interaction-message--error">
            <strong>监控读取异常</strong>
            <span>{error}</span>
          </article>
        ) : null}

        <article className="health-agent-message">
          <strong>{graphRunId ? compactId(graphRunId) : "尚未绑定 GraphRun"}</strong>
          <span>{graphHarnessConfigId ? `图契约 ${compactId(graphHarnessConfigId)}` : "需要 graph_harness_config_id 才能读取监控和派发 ready 节点。"}</span>
          {taskRunId ? <small>TaskRun {compactId(taskRunId)}</small> : null}
        </article>

        {activeOrders.length ? (
          <article className="health-agent-message task-graph-run-interaction-work-packet">
            <strong>活动 Work Order</strong>
            <div className="task-graph-run-interaction-work-packet__grid">
              {activeOrders.slice(0, 4).map((order, index) => {
                const payload = recordValue(order);
                const nodeId = textValue(payload.node_id);
                return (
                  <section key={`${textValue(payload.work_order_id, "work_order")}_${index}`}>
                    <b>{nodeId || `order_${index + 1}`}</b>
                    <small>{textValue(payload.work_kind || payload.executor_type, "agent")}</small>
                    <small>{compactId(textValue(payload.work_order_id))}</small>
                  </section>
                );
              })}
            </div>
          </article>
        ) : null}

        {nodes.length ? (
          <article className="health-agent-message">
            <strong>节点状态</strong>
            <div className="task-graph-batch-runtime-list">
              {nodes.slice(0, 8).map((node, index) => {
                const nodeId = textValue(node.node_id || node.id);
                const status = statuses.get(nodeId) || textValue(recordValue(state.node_states)[nodeId], "idle");
                return (
                  <section className="task-graph-batch-runtime-row" key={`${nodeId || "node"}_${index}_dock`}>
                    <span className={`task-graph-batch-runtime-row__status task-graph-batch-runtime-row__status--${status || "idle"}`}>
                      {status || "idle"}
                    </span>
                    <div>
                      <strong>{textValue(node.title, nodeId || `node_${index + 1}`)}</strong>
                      <small>{nodeId || "-"}</small>
                    </div>
                    <em>#{index + 1}</em>
                  </section>
                );
              })}
            </div>
          </article>
        ) : null}

        {monitor?.events?.length ? (
          <details className="task-graph-runtime-spec-details">
            <summary>最近事件</summary>
            <pre>{JSON.stringify(monitor.events.slice(-8), null, 2)}</pre>
          </details>
        ) : null}
      </div>

      <div className="health-agent-dock__actions">
        <button disabled={!graphRunId || !graphHarnessConfigId || monitorLoading} onClick={onEvaluate} type="button">
          <RefreshCw size={14} />
          刷新
        </button>
        <button disabled={!graphRunId || !graphHarnessConfigId || actionLoading} onClick={onContinue} type="button">
          <PlayCircle size={14} />
          派发 Ready
        </button>
      </div>
    </aside>
  );

  return createPortal(open ? dock : launcher, document.body);
}
