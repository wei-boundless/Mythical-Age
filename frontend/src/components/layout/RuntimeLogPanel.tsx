"use client";

import {
  Activity,
  AlertTriangle,
  FileJson,
  RadioTower,
  RefreshCw,
  Terminal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getRuntimeLogEventStreamUrl,
  type HarnessTraceEvent,
  type RuntimeLogScope,
  type RuntimeLogStreamPayload,
} from "@/lib/api";
import {
  applyRuntimeLogPayload,
  createRuntimeLogState,
  parseRuntimeLogStreamPayload,
} from "@/lib/runtime-log/reducer";

const RUNTIME_LOG_LIMIT = 240;

export type RuntimeLogTarget = {
  scope: RuntimeLogScope;
  runId: string;
  title?: string;
  subtitle?: string;
};

type RuntimeLogPanelProps = {
  target: RuntimeLogTarget;
  onClose: () => void;
};

type RuntimeLogConnectionStatus = "connecting" | "connected" | "reconnecting" | "closed";

export function RuntimeLogPanel({ target, onClose }: RuntimeLogPanelProps) {
  const [state, setState] = useState(() => createRuntimeLogState(target.scope, target.runId));
  const [status, setStatus] = useState<RuntimeLogConnectionStatus>("connecting");
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [connectionRevision, setConnectionRevision] = useState(0);

  useEffect(() => {
    setState(createRuntimeLogState(target.scope, target.runId));
    setSelectedKey("");
    setError("");
    setStatus("connecting");
  }, [target.scope, target.runId, connectionRevision]);

  const applyPayload = useCallback((payload: RuntimeLogStreamPayload | null) => {
    if (!payload) return;
    setState((previous) => applyRuntimeLogPayload(previous, payload, { maxEvents: RUNTIME_LOG_LIMIT }));
    if (payload.source === "event" && payload.event) {
      setSelectedKey((current) => current || runtimeLogEventKey(payload.event as HarnessTraceEvent));
    }
    if (payload.source === "snapshot" || payload.source === "event" || payload.source === "heartbeat") {
      setStatus("connected");
    }
    if (payload.source === "gap" && payload.gap && !payload.gap.recovered) {
      setError(`日志流缺口：${payload.gap.expected_after_offset} -> ${payload.gap.observed_offset}`);
    } else if (payload.source !== "gap") {
      setError("");
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    if (typeof EventSource === "undefined") {
      setStatus("closed");
      setError("当前浏览器不支持 EventSource。");
      return undefined;
    }
    const source = new EventSource(
      getRuntimeLogEventStreamUrl(target.scope, target.runId, {
        limit: RUNTIME_LOG_LIMIT,
        includePayloads: true,
      }),
    );
    source.onopen = () => {
      setStatus("connected");
      setError("");
    };
    source.onerror = () => {
      setStatus("reconnecting");
      setError("日志流连接中断，正在重连。");
    };
    const handleMessage = (event: MessageEvent) => {
      try {
        applyPayload(parseRuntimeLogStreamPayload(String(event.data || "")));
      } catch (parseError) {
        setError(parseError instanceof Error ? parseError.message : "日志事件解析失败");
      }
    };
    source.addEventListener("runtime_log_snapshot", handleMessage);
    source.addEventListener("runtime_log_event", handleMessage);
    source.addEventListener("runtime_log_gap", handleMessage);
    source.addEventListener("runtime_log_heartbeat", handleMessage);
    return () => {
      source.close();
      setStatus("closed");
    };
  }, [applyPayload, connectionRevision, target.runId, target.scope]);

  const selectedEvent = useMemo(() => {
    if (!state.events.length) return null;
    return state.events.find((event) => runtimeLogEventKey(event) === selectedKey) ?? state.events[state.events.length - 1] ?? null;
  }, [selectedKey, state.events]);

  useEffect(() => {
    if (!state.events.length) {
      setSelectedKey("");
      return;
    }
    if (!selectedKey || !state.events.some((event) => runtimeLogEventKey(event) === selectedKey)) {
      setSelectedKey(runtimeLogEventKey(state.events[state.events.length - 1]));
    }
  }, [selectedKey, state.events]);

  const statusLabel = runtimeLogStatusLabel(status);
  const scopeLabel = target.scope === "turn_run" ? "TurnRun" : "TaskRun";
  const detailJson = selectedEvent ? runtimeLogDetailJson(selectedEvent) : "";

  return (
    <section className="runtime-log-panel" aria-label="运行日志">
      <header className="runtime-log-panel__head">
        <div className="runtime-log-panel__title">
          <span><Terminal size={13} />Runtime Log</span>
          <strong>{target.title || scopeLabel}</strong>
          <small>{target.subtitle || target.runId}</small>
        </div>
        <div className="runtime-log-panel__actions">
          <span className={`runtime-log-panel__stream runtime-log-panel__stream--${status}`}>
            <RadioTower size={13} />{statusLabel}
          </span>
          <button aria-label="重新连接运行日志" onClick={() => setConnectionRevision((value) => value + 1)} type="button">
            <RefreshCw size={14} />
          </button>
          <button aria-label="关闭运行日志" onClick={onClose} type="button">
            <X size={14} />
          </button>
        </div>
      </header>

      <div className="runtime-log-panel__metrics" aria-label="日志指标">
        <span><Activity size={13} />{state.events.length} 事件</span>
        <span>Offset {state.lastOffset >= 0 ? state.lastOffset : "-"}</span>
        {state.droppedEventCount ? <span>保留最近 {RUNTIME_LOG_LIMIT}</span> : null}
        {state.gap ? <span className="runtime-log-panel__gap">Gap {state.gap.expected_after_offset}:{state.gap.observed_offset}</span> : null}
      </div>

      {error ? (
        <div className="runtime-log-panel__notice">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="runtime-log-panel__body">
        <div className="runtime-log-panel__events" aria-label="运行日志事件">
          {state.events.length ? state.events.map((event) => {
            const key = runtimeLogEventKey(event);
            const selected = key === runtimeLogEventKey(selectedEvent);
            return (
              <button
                aria-pressed={selected}
                className={selected ? "runtime-log-event runtime-log-event--selected" : "runtime-log-event"}
                key={key}
                onClick={() => setSelectedKey(key)}
                type="button"
              >
                <span className="runtime-log-event__offset">{event.offset}</span>
                <span className="runtime-log-event__body">
                  <strong>{event.event_type || "runtime_event"}</strong>
                  <small>{runtimeLogEventSummary(event)}</small>
                </span>
                <span className="runtime-log-event__time">{formatRuntimeLogTime(event.created_at)}</span>
              </button>
            );
          }) : (
            <div className="runtime-log-panel__empty">
              <FileJson size={16} />
              <strong>{status === "connected" ? "暂无事件" : "连接中"}</strong>
              <span>{target.runId}</span>
            </div>
          )}
        </div>

        <aside className="runtime-log-panel__detail" aria-label="日志详情">
          {selectedEvent ? (
            <>
              <header>
                <div>
                  <span>Payload</span>
                  <strong>{selectedEvent.event_type}</strong>
                </div>
                <em>#{selectedEvent.offset}</em>
              </header>
              <pre>{detailJson}</pre>
            </>
          ) : (
            <div className="runtime-log-panel__detail-empty">
              <span>Payload</span>
              <strong>-</strong>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function runtimeLogEventKey(event: HarnessTraceEvent | null) {
  if (!event) return "";
  const eventId = String(event.event_id || "").trim();
  if (eventId) return eventId;
  return `${event.offset}:${event.event_type}`;
}

function runtimeLogStatusLabel(status: RuntimeLogConnectionStatus) {
  if (status === "connected") return "实时";
  if (status === "reconnecting") return "重连";
  if (status === "closed") return "离线";
  return "连接";
}

function runtimeLogEventSummary(event: HarnessTraceEvent) {
  const summary = objectValue(event.payload_summary);
  const payload = objectValue(event.payload);
  const refs = objectValue(event.refs);
  const candidates = [
    summary.summary,
    summary.message,
    summary.status,
    summary.phase,
    payload.summary,
    payload.message,
    payload.status,
    payload.phase,
    refs.node_id,
    refs.tool_name,
  ];
  const text = candidates.map((item) => String(item ?? "").trim()).find(Boolean);
  if (text) return truncateRuntimeLogText(text, 140);
  const keys = Object.keys(summary).length ? Object.keys(summary) : Object.keys(refs);
  if (keys.length) return truncateRuntimeLogText(keys.slice(0, 5).join(" / "), 140);
  return event.event_id || event.run_id || "-";
}

function runtimeLogDetailJson(event: HarnessTraceEvent) {
  return JSON.stringify({
    event_id: event.event_id,
    event_type: event.event_type,
    offset: event.offset,
    created_at: event.created_at,
    refs: event.refs ?? {},
    payload_summary: event.payload_summary ?? {},
    payload: event.payload ?? {},
  }, null, 2);
}

function objectValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function truncateRuntimeLogText(value: string, limit: number) {
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit - 1))}...`;
}

function formatRuntimeLogTime(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "-";
  const timestamp = number > 1_000_000_000_000 ? number : number * 1000;
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
