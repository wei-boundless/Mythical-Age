"use client";

import { AlertTriangle, Loader2, MessageSquare, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatMessage } from "@/components/chat/ChatMessage";
import { getSessionHistory, getSessionRuntimeProjection, type SessionScope } from "@/lib/api";
import { hydrateSessionRuntimeProjection } from "@/lib/store/runtime/projectionHydration";
import type { Message, StoreState } from "@/lib/store/types";
import { toUiMessages } from "@/lib/store/utils";
import { cn } from "@/ui/classNames";

const SESSION_PROJECTION_REFRESH_MS = 3500;

export type SessionProjectionTarget = {
  sessionId: string;
  scope?: Partial<SessionScope>;
  title?: string;
  subtitle?: string;
  source?: string;
};

type ProjectionLoadState = {
  messages: Message[];
  activeProjectionsByKey: StoreState["activeProjectionsByKey"];
  authority: string;
  attachmentCount: number;
  loadedAt: number;
  source: "runtime_projection" | "history";
};

export function sessionProjectionPageKey(target: SessionProjectionTarget) {
  return [
    "session-projection",
    target.sessionId.trim(),
    stableScopeKey(target.scope),
    String(target.source || "").trim(),
  ].join(":");
}

export function sessionProjectionPageTitle(target: SessionProjectionTarget) {
  const title = String(target.title || "").trim();
  if (title) return title.length > 28 ? `${title.slice(0, 28)}...` : title;
  return compactSessionId(target.sessionId);
}

export function SessionProjectionPanel({
  onClose,
  target,
}: {
  onClose: () => void;
  target: SessionProjectionTarget;
}) {
  const sessionId = target.sessionId.trim();
  const scopeKey = stableScopeKey(target.scope);
  const requestRef = useRef(0);
  const [state, setState] = useState<ProjectionLoadState | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const refreshProjection = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!sessionId) return;
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    if (options.silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    setNotice("");
    try {
      const projection = await getSessionRuntimeProjection(sessionId, target.scope);
      if (requestRef.current !== requestId) return;
      const hydrated = hydrateSessionRuntimeProjection({
        messages: toUiMessages(projection.messages),
        activeProjectionsByKey: {},
      }, projection.runtime_attachments);
      setState({
        messages: hydrated.messages,
        activeProjectionsByKey: hydrated.activeProjectionsByKey,
        authority: projection.authority || "",
        attachmentCount: projection.runtime_attachments?.length ?? 0,
        loadedAt: Date.now(),
        source: "runtime_projection",
      });
    } catch (projectionError) {
      try {
        const history = await getSessionHistory(sessionId, target.scope);
        if (requestRef.current !== requestId) return;
        setState({
          messages: toUiMessages(history.messages),
          activeProjectionsByKey: {},
          authority: "",
          attachmentCount: 0,
          loadedAt: Date.now(),
          source: "history",
        });
        setNotice(readableError(projectionError, "运行投影暂不可用，已显示会话历史。"));
      } catch (historyError) {
        if (requestRef.current !== requestId) return;
        setError(readableError(historyError, "Session 投影读取失败。"));
      }
    } finally {
      if (requestRef.current === requestId) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [sessionId, scopeKey, target.scope]);

  useEffect(() => {
    void refreshProjection();
  }, [refreshProjection]);

  useEffect(() => {
    if (!sessionId) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void refreshProjection({ silent: true });
    }, SESSION_PROJECTION_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refreshProjection, sessionId]);

  const messages = useMemo(
    () => messagesWithActiveProjectionViews(state?.messages ?? [], state?.activeProjectionsByKey ?? {}),
    [state?.activeProjectionsByKey, state?.messages],
  );
  const title = String(target.title || "").trim() || "Session 投影";
  const subtitle = String(target.subtitle || "").trim() || sessionId;
  const scopeItems = scopeSummaryItems(target.scope);

  return (
    <section className="session-projection-panel" aria-label="Session 投影页">
      <header className="session-projection-panel__head">
        <div className="session-projection-panel__title">
          <span>
            <MessageSquare size={14} />
            <em>{target.source === "graph-node" ? "节点会话投影" : "Session 投影"}</em>
          </span>
          <strong>{title}</strong>
          <small title={subtitle}>{subtitle}</small>
        </div>
        <div className="session-projection-panel__actions">
          <span className={cn("session-projection-panel__status", refreshing && "session-projection-panel__status--active")}>
            {loading ? "读取中" : state?.source === "history" ? "History" : "Projection"}
          </span>
          <button
            aria-label="刷新 Session 投影"
            disabled={loading || refreshing}
            onClick={() => void refreshProjection()}
            title="刷新"
            type="button"
          >
            {loading || refreshing ? <Loader2 className="session-projection-panel__spin" size={14} /> : <RefreshCw size={14} />}
          </button>
          <button aria-label="关闭 Session 投影" onClick={onClose} title="关闭" type="button">
            <X size={14} />
          </button>
        </div>
      </header>

      <div className="session-projection-panel__meta">
        <span title={sessionId}>{compactSessionId(sessionId)}</span>
        {scopeItems.map((item) => (
          <span key={item} title={item}>{item}</span>
        ))}
        <span>{messages.length} 条消息</span>
        <span>{state?.attachmentCount ?? 0} 个投影包</span>
        {state?.loadedAt ? <span>{formatTime(state.loadedAt)}</span> : null}
      </div>

      {notice ? (
        <div className="session-projection-panel__notice">
          <AlertTriangle size={14} />
          <span>{notice}</span>
        </div>
      ) : null}
      {error ? (
        <div className="session-projection-panel__error" role="alert">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="session-projection-panel__body" aria-busy={loading && !state}>
        {loading && !state ? (
          <div className="session-projection-panel__empty">
            <Loader2 className="session-projection-panel__spin" size={18} />
            <span>正在读取投影。</span>
          </div>
        ) : messages.length ? (
          <div className="session-projection-panel__messages">
            {messages.map((message) => (
              <ChatMessage
                answerCanonicalState={message.answerCanonicalState}
                answerChannel={message.answerChannel}
                answerFallbackReason={message.answerFallbackReason}
                answerFinalizationPolicy={message.answerFinalizationPolicy}
                answerLeakFlags={message.answerLeakFlags}
                answerPersistPolicy={message.answerPersistPolicy}
                answerSelectedChannel={message.answerSelectedChannel}
                answerSelectedSource={message.answerSelectedSource}
                answerSource={message.answerSource}
                attachments={message.attachments}
                closeoutSummary={message.closeoutSummary}
                content={message.content}
                id={message.id}
                image={message.image}
                key={message.id}
                projectionView={message.projectionView}
                retrievals={message.retrievals}
                role={message.role}
                streamingContent={false}
                toolCalls={message.toolCalls}
              />
            ))}
          </div>
        ) : (
          <div className="session-projection-panel__empty">
            <MessageSquare size={18} />
            <span>这个 Session 暂无可显示内容。</span>
          </div>
        )}
      </div>
    </section>
  );
}

function messagesWithActiveProjectionViews(
  messages: Message[],
  activeProjectionsByKey: StoreState["activeProjectionsByKey"],
) {
  return messages.map((message) => {
    const key = message.projectionKeyString ?? "";
    const projection = key ? activeProjectionsByKey[key] : undefined;
    const projectionView = projection?.view ?? message.projectionView;
    if (!projectionView || projectionView === message.projectionView) {
      return message;
    }
    return { ...message, projectionView };
  });
}

function stableScopeKey(scope?: Partial<SessionScope>) {
  if (!scope) return "main";
  return JSON.stringify(Object.keys(scope).sort().map((key) => [key, scope[key as keyof SessionScope] ?? ""]));
}

function scopeSummaryItems(scope?: Partial<SessionScope>) {
  if (!scope) return [];
  return [
    scope.workspace_view ? `view:${scope.workspace_view}` : "",
    scope.task_environment_id ? `env:${scope.task_environment_id}` : "",
    scope.project_id ? `project:${compactSessionId(scope.project_id)}` : "",
  ].filter(Boolean);
}

function compactSessionId(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "session";
  if (normalized.length <= 22) return normalized;
  return `${normalized.slice(0, 10)}...${normalized.slice(-8)}`;
}

function formatTime(timestamp: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

function readableError(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || fallback;
}
