"use client";

import { Activity, CheckCircle2, GripHorizontal, MessageSquare, Minimize2, Pause, PlayCircle, RefreshCw, RotateCcw, ShieldCheck, TriangleAlert, X } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { TaskGraphMonitorBinding } from "@/lib/store/types";
import type { TaskGraphMonitorDecision, TaskGraphRunMonitorView } from "@/lib/api";
import { buildTaskGraphBatchLifecycleSummary } from "./taskGraphRuntimeView";

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function interactionRequest(decision: TaskGraphMonitorDecision | null): Record<string, unknown> {
  return recordValue(decision?.run_interaction_request);
}

function numberValue(value: unknown) {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? next : 0;
}

function formatClock(seconds: number) {
  if (!seconds) return "暂无更新";
  return new Date(seconds * 1000).toLocaleTimeString();
}

function latestMonitorTime(monitor: TaskGraphRunMonitorView | null) {
  return Math.max(
    numberValue(monitor?.streaming?.latest_chunk_at),
    numberValue(monitor?.runtime?.updated_at),
    numberValue(monitor?.timeline?.updated_at),
    numberValue(monitor?.supervision?.latest_event_at),
  );
}

function compactId(value: string, left = 18, right = 8) {
  if (!value) return "";
  if (value.length <= left + right + 3) return value;
  return `${value.slice(0, left)}...${value.slice(-right)}`;
}

function optionIcon(controlAction: string, decision: string) {
  if (controlAction === "stop_task_run" || decision === "pause") return <Pause size={14} />;
  if (controlAction === "start_new_run" || decision === "start_new_run") return <RotateCcw size={14} />;
  if (controlAction === "acknowledge" || decision === "acknowledge") return <CheckCircle2 size={14} />;
  return <PlayCircle size={14} />;
}

function statusLabel(decision: TaskGraphMonitorDecision | null, loading: boolean) {
  if (loading) return "正在监测";
  if (!decision) return "等待监测";
  if (decision.action === "no_action") return "运行健康";
  if (decision.action === "request_user_decision" || decision.action === "request_human_review") return "等待用户确认";
  if (decision.severity === "critical" || decision.severity === "error") return "需要处理";
  return "有新提醒";
}

export function TaskGraphRunInteractionDock({
  actionLoading,
  binding,
  decision,
  error,
  monitor,
  monitorLoading,
  onClear,
  onEvaluate,
  onOpenChange,
  onSubmitDecision,
  open,
}: {
  actionLoading: boolean;
  binding: TaskGraphMonitorBinding | null;
  decision: TaskGraphMonitorDecision | null;
  error: string;
  monitor: TaskGraphRunMonitorView | null;
  monitorLoading: boolean;
  onClear: () => void;
  onEvaluate: () => void;
  onOpenChange: (open: boolean) => void;
  onSubmitDecision: (decision: string, controlAction: string, resumePayload?: Record<string, unknown>) => void;
  open: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  const [ready, setReady] = useState(false);
  const [position, setPosition] = useState({ x: 24, y: 120 });
  const [operatorNote, setOperatorNote] = useState("");
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const suppressClickRef = useRef(false);
  const autoOpenedRef = useRef("");
  const request = useMemo(() => interactionRequest(decision), [decision]);
  const monitorHumanWorkPacket = recordValue((monitor as unknown as Record<string, unknown> | null)?.current_human_work_packet);
  const humanWorkPacket = recordValue(request.human_work_packet ?? monitorHumanWorkPacket);
  const materialSections = useMemo(() => arrayValue(humanWorkPacket.material_sections), [humanWorkPacket]);
  const outputFormSchema = recordValue(humanWorkPacket.output_form_schema);
  const requestId = String(request.request_id || decision?.decision_id || "");
  const decisionOptions = useMemo(() => arrayValue(request.decision_options), [request]);
  const needsAttention = Boolean(decision && decision.action !== "no_action");
  const taskRunId = String(binding?.task_run_id ?? "").trim();
  const boundLabel = binding?.title || binding?.graph_id || (taskRunId ? compactId(taskRunId) : "未绑定 TaskRun");
  const activeNodeId = String(monitor?.runtime?.active_node_id || decision?.observed?.active_node_id || "");
  const runtimeStatus = String(monitor?.runtime?.status || decision?.observed?.runtime_status || (taskRunId ? "watching" : "idle"));
  const streamEnabled = monitor?.streaming?.enabled === true;
  const streamChunks = numberValue(monitor?.streaming?.chunk_count);
  const streamChars = numberValue(monitor?.streaming?.accumulated_chars);
  const streamPreview = String(monitor?.streaming?.preview_text || "");
  const latestAt = latestMonitorTime(monitor);
  const lastUpdatedLabel = formatClock(latestAt);
  const batchLifecycle = buildTaskGraphBatchLifecycleSummary(monitor?.batch_lifecycle);

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
    if (!needsAttention || !requestId || autoOpenedRef.current === requestId) {
      return;
    }
    autoOpenedRef.current = requestId;
    onOpenChange(true);
  }, [needsAttention, onOpenChange, requestId]);

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

  function submitOption(option: Record<string, unknown>, index: number) {
    const selectedDecision = String(option.decision || `decision_${index + 1}`);
    const controlAction = String(option.control_action || option.action || "");
    const resumePayload = {
      ...recordValue(option.resume_payload),
      ...(operatorNote.trim() ? { operator_note: operatorNote.trim() } : {}),
    };
    onSubmitDecision(selectedDecision, controlAction, resumePayload);
    setOperatorNote("");
  }

  if (!mounted) {
    return null;
  }

  if (!open && !needsAttention) {
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
        <span>{needsAttention ? "运行需要处理" : taskRunId ? "运行监控" : "监控待绑定"}</span>
      </button>
      <div className="task-graph-run-interaction-launcher__body">
        <strong>{activeNodeId || boundLabel}</strong>
        <span>{runtimeStatus} · {lastUpdatedLabel}</span>
        {streamEnabled ? <small>{streamChunks} 片 / {streamChars} 字</small> : null}
        {batchLifecycle.available ? <small>批次 {batchLifecycle.summary.committed_batch_count ?? 0}/{batchLifecycle.summary.batch_count ?? 0}</small> : null}
      </div>
      <GripHorizontal size={15} />
    </aside>
  );

  const dock = (
    <aside className="health-agent-dock task-graph-run-interaction-dock" style={{ left: position.x, opacity: ready ? 1 : 0, top: position.y }}>
      <header onPointerDown={beginDrag}>
        <div>
          <span>TaskGraph 运行交互</span>
          <strong>{statusLabel(decision, monitorLoading)}</strong>
          <em>{boundLabel}</em>
        </div>
        <div className="health-agent-dock__window-controls">
          <GripHorizontal size={15} />
          <button aria-label="折叠运行交互窗口" onClick={() => onOpenChange(false)} type="button">
            <Minimize2 size={16} />
          </button>
          <button aria-label="解除当前运行监控绑定" onClick={onClear} type="button">
            <X size={16} />
          </button>
        </div>
      </header>

      <div className="health-agent-dock__scope">
        <ShieldCheck size={15} />
        <span>这个浮窗绑定 TaskRun，而不是绑定当前聊天会话。切换普通会话不会中断监控；异常、阻塞和人工确认会在这里升级提醒。</span>
      </div>

      <section className="task-graph-run-interaction-status">
        <div>
          <span>当前节点</span>
          <strong>{activeNodeId || "-"}</strong>
        </div>
        <div>
          <span>运行态</span>
          <strong>{runtimeStatus}</strong>
        </div>
        <div>
          <span>最近更新</span>
          <strong>{lastUpdatedLabel}</strong>
        </div>
        <div>
          <span>实时正文</span>
          <strong>{streamEnabled ? `${streamChunks} / ${streamChars}` : "未启用"}</strong>
        </div>
        {batchLifecycle.available ? (
          <div>
            <span>批次进度</span>
            <strong>{batchLifecycle.summary.committed_batch_count ?? 0}/{batchLifecycle.summary.batch_count ?? 0}</strong>
          </div>
        ) : null}
        {batchLifecycle.available ? (
          <div>
            <span>执行实例</span>
            <strong>{batchLifecycle.summary.execution_instance_count ?? batchLifecycle.execution_instances.length}</strong>
          </div>
        ) : null}
      </section>

      <div className="health-agent-dock__messages">
        {error ? (
          <article className="health-agent-message task-graph-run-interaction-message--error">
            <strong>监控读取异常</strong>
            <span>{error}</span>
          </article>
        ) : null}
        {decision ? (
          <>
            <article className={`health-agent-message task-graph-run-interaction-message--${decision.severity || "info"}`}>
              <strong>{decision.summary || "监测节点已返回决策。"}</strong>
              <span>{decision.action} / {decision.reason}</span>
            </article>
            {Object.keys(request).length ? (
              <article className="health-agent-message">
                <strong>{String(recordValue(request.presentation).title || "运行交互请求")}</strong>
                <span>{String(request.summary || decision.summary || "请根据当前运行状态选择下一步。")}</span>
                <small>{String(request.interaction_kind || "run_interaction")}</small>
              </article>
            ) : null}
            {Object.keys(humanWorkPacket).length ? (
              <article className="health-agent-message task-graph-run-interaction-work-packet">
                <strong>{String(humanWorkPacket.title || "节点人工工作单")}</strong>
                <span>{String(humanWorkPacket.task_brief || "请按节点输入包和输出契约提交本节点结果。")}</span>
                <small>{String(humanWorkPacket.role_label || "人工执行者")}</small>
                <div className="task-graph-run-interaction-work-packet__grid">
                  {materialSections.map((section, index) => {
                    const items = arrayValue(section.items);
                    return (
                      <section key={`${String(section.section_id || "section")}_${index}`}>
                        <b>{String(section.title || section.section_id || "输入材料")}</b>
                        {items.length ? (
                          <ul>
                            {items.slice(0, 4).map((item, itemIndex) => (
                              <li key={`${String(item.input_key || "input")}_${itemIndex}`}>
                                <span>{String(item.input_key || "输入")}</span>
                                <small>{String(item.usage_instruction || item.content_preview || item.content_ref || "")}</small>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <small>暂无材料</small>
                        )}
                      </section>
                    );
                  })}
                </div>
                {Array.isArray(outputFormSchema.fields) && outputFormSchema.fields.length ? (
                  <small>需提交字段：{outputFormSchema.fields.map((field) => String(recordValue(field).label || recordValue(field).field_id || "")).filter(Boolean).join(" / ")}</small>
                ) : null}
              </article>
            ) : null}
            <details className="task-graph-runtime-spec-details">
              <summary>请求详情</summary>
              <pre>{JSON.stringify(Object.keys(request).length ? request : decision, null, 2)}</pre>
            </details>
          </>
        ) : (
          <article className="health-agent-message">
            <strong>{taskRunId ? "监控已常驻" : "尚未绑定运行"}</strong>
            <span>{taskRunId ? "你可以主动执行一次监测评估；普通轮询只刷新运行快照，不会反复写入监督决策。" : "在发布页创建运行或输入 TaskRun ID 后绑定监控。"}</span>
          </article>
        )}
        {streamEnabled && streamPreview ? (
          <article className="health-agent-message task-graph-run-interaction-stream">
            <strong><MessageSquare size={14} /> 实时正文流</strong>
            <small>最近更新 {lastUpdatedLabel}</small>
            <pre>{streamPreview}</pre>
          </article>
        ) : null}
        {batchLifecycle.available ? (
          <article className="health-agent-message task-graph-run-interaction-batches">
            <strong>批次生命周期</strong>
            <span>Ready {batchLifecycle.summary.ready_batch_count ?? 0} / Running {batchLifecycle.summary.running_batch_count ?? 0} / Committed {batchLifecycle.summary.committed_batch_count ?? 0} / Failed {batchLifecycle.summary.failed_batch_count ?? 0} / Instance {batchLifecycle.summary.execution_instance_count ?? batchLifecycle.execution_instances.length}</span>
            <div className="task-graph-batch-runtime-list">
              {batchLifecycle.batches.slice(0, 5).map((batch, index) => {
                const range = recordValue(batch.range);
                return (
                  <section className="task-graph-batch-runtime-row" key={`${String(batch.batch_id ?? "batch")}_${index}_dock`}>
                    <span className={`task-graph-batch-runtime-row__status task-graph-batch-runtime-row__status--${String(batch.status ?? "planned")}`}>
                      {String(batch.status ?? "planned")}
                    </span>
                    <div>
                      <strong>{String(batch.batch_id ?? `batch_${index + 1}`)}</strong>
                      <small>{String(batch.unit_kind ?? "unit")} · {String(range.start ?? "-")}-{String(range.end ?? "-")}</small>
                    </div>
                    <em>#{String(batch.sequence_index ?? index + 1)}</em>
                  </section>
                );
              })}
            </div>
          </article>
        ) : null}
      </div>

      <div className="health-agent-dock__actions">
        <button disabled={!taskRunId || monitorLoading} onClick={onEvaluate} type="button">
          <RefreshCw size={14} />
          执行监测
        </button>
        {decisionOptions.map((option, index) => {
          const selectedDecision = String(option.decision || `decision_${index + 1}`);
          const controlAction = String(option.control_action || option.action || "");
          return (
            <button disabled={actionLoading} key={`${selectedDecision}_${index}`} onClick={() => submitOption(option, index)} title={String(option.label || selectedDecision)} type="button">
              {optionIcon(controlAction, selectedDecision)}
              <span>{String(option.label || selectedDecision)}</span>
            </button>
          );
        })}
        {!decisionOptions.length && decision?.action === "no_action" ? (
          <button disabled title="无需处理" type="button">
            <CheckCircle2 size={14} />
            <span>无需处理</span>
          </button>
        ) : null}
      </div>

      <label className="health-agent-dock__input">
        <Activity size={15} />
        <input
          onChange={(event) => setOperatorNote(event.target.value)}
          placeholder="处理意见，可选"
          value={operatorNote}
        />
      </label>
    </aside>
  );

  return createPortal(open ? dock : launcher, document.body);
}
