"use client";

import { useEffect, useMemo, useRef, type CSSProperties } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { sessionSummaryIsRunning } from "@/lib/sessionTaskPresentation";
import { useAppStoreActions, useAppStoreSelector } from "@/lib/store";
import { shallowEqual } from "@/lib/store/hooks";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import type { HarnessTaskRunLiveMonitor } from "@/lib/api";
import type { ActiveTurnSnapshot, Message, StoreActions, StoreState, TokenStats } from "@/lib/store/types";

export function ChatPanel() {
  const {
    messages,
    activeProjectionsByKey,
    activeStreamSessionIds,
    sessionActivity,
    currentSessionId,
    workspaceInitializing,
    modelProviderConfig,
    imageAssetConfig,
    permissionMode,
    supportedPermissionModes,
    chatThinkingMode,
    selectedChatModelId,
    sessions,
    tokenStats,
    activeTurnSnapshot,
    taskGraphLiveMonitor,
  } = useAppStoreSelector((state) => ({
    messages: state.messages,
    activeProjectionsByKey: state.activeProjectionsByKey,
    activeStreamSessionIds: state.activeStreamSessionIds,
    sessionActivity: state.sessionActivity,
    currentSessionId: state.currentSessionId,
    workspaceInitializing: state.workspaceInitializing,
    modelProviderConfig: state.modelProviderConfig,
    imageAssetConfig: state.imageAssetConfig,
    permissionMode: state.permissionMode,
    supportedPermissionModes: state.supportedPermissionModes,
    chatThinkingMode: state.chatThinkingMode,
    selectedChatModelId: state.selectedChatModelId,
    sessions: state.sessions,
    tokenStats: state.tokenStats,
    activeTurnSnapshot: state.activeTurnSnapshot,
    taskGraphLiveMonitor: state.taskGraphLiveMonitor,
  }), shallowEqual);
  const {
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    setPermissionMode,
    setChatThinkingMode,
    openRuntimeLog,
    setSelectedChatModel,
  } = useAppStoreActions();
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) ?? null,
    [currentSessionId, sessions],
  );
  const currentSessionReceivingStream = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const currentTaskIsRunning = Boolean(currentSession && sessionSummaryIsRunning(currentSession))
    || chatTaskMonitorIsActive(taskGraphLiveMonitor);
  const currentSessionActive = currentSessionReceivingStream || currentTaskIsRunning;
  const projectedMessages = useMemo(
    () => messagesWithActiveProjectionViews(messages, activeProjectionsByKey),
    [activeProjectionsByKey, messages],
  );
  const suppressFooterActivity = shouldSuppressSessionActivityBar(projectedMessages, currentSessionActive);
  const messageRenderKeys = useMemo(() => chatMessageRenderKeys(projectedMessages), [projectedMessages]);
  const liveAssistantMessageId = useMemo(() => liveAssistantMessageIdForMessages(projectedMessages, {
    activeTurnSnapshot,
    currentSessionReceivingStream,
    currentTaskIsRunning,
    taskGraphLiveMonitor,
  }), [activeTurnSnapshot, currentSessionReceivingStream, currentTaskIsRunning, projectedMessages, taskGraphLiveMonitor]);
  const lastEditableUserMessageId = useMemo(() => {
    for (let index = projectedMessages.length - 1; index >= 0; index -= 1) {
      const message = projectedMessages[index];
      if (message.role === "user" && message.sourceIndex !== undefined) {
        return message.id;
      }
    }
    return null;
  }, [projectedMessages]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const scheduleFrame = typeof window.requestAnimationFrame === "function"
      ? window.requestAnimationFrame.bind(window)
      : (callback: FrameRequestCallback) => window.setTimeout(() => callback(Date.now()), 16);
    const cancelFrame = typeof window.cancelAnimationFrame === "function"
      ? window.cancelAnimationFrame.bind(window)
      : window.clearTimeout.bind(window);
    if (scrollFrameRef.current !== null) {
      cancelFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = scheduleFrame(() => {
      scrollFrameRef.current = null;
      endRef.current?.scrollIntoView({ behavior: currentSessionReceivingStream ? "auto" : "smooth" });
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [projectedMessages, currentSessionReceivingStream]);

  return (
    <section className="chat-panel-shell grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden">
      <div className="chat-thread flex min-h-0 min-w-0 flex-col overflow-hidden">
        <div className="chat-thread__messages flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {!projectedMessages.length ? (
            <div className="chat-thread__empty">
              <div>
                <strong>等待你的下一句话。</strong>
                <span>可以直接开始对话，也可以把任务交给当前会话。</span>
              </div>
            </div>
          ) : null}

          {projectedMessages.map((message, index) => (
            <ChatMessage
              canEdit={!currentSessionActive && message.id === lastEditableUserMessageId}
              content={message.content}
              image={message.image}
              attachments={message.attachments}
              id={message.id}
              key={messageRenderKeys[index] ?? message.id}
              onResendEdit={resendEditedMessage}
              answerChannel={message.answerChannel}
              answerCanonicalState={message.answerCanonicalState}
              answerFallbackReason={message.answerFallbackReason}
              answerFinalizationPolicy={message.answerFinalizationPolicy}
              answerLeakFlags={message.answerLeakFlags}
              answerPersistPolicy={message.answerPersistPolicy}
              answerSelectedChannel={message.answerSelectedChannel}
              answerSelectedSource={message.answerSelectedSource}
              answerSource={message.answerSource}
              closeoutSummary={message.closeoutSummary}
              onOpenRuntimeLog={runtimeLogOpenHandler(message, openRuntimeLog)}
              projectionView={message.projectionView}
              retrievals={message.retrievals}
              role={message.role}
              runtimeLogRef={message.runtimeLogRef}
              sourceTaskRunId={message.sourceTaskRunId}
              sourceTurnRunId={message.sourceTurnRunId}
              streamingContent={message.id === liveAssistantMessageId}
              toolEventCount={message.toolEventCount}
              toolCalls={message.toolCalls}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-panel-footer min-w-0">
        <div className="chat-panel-status-row">
          {suppressFooterActivity ? null : <SessionActivityBar activity={sessionActivity} active={currentSessionActive} />}
          <div className="chat-panel-status-row__right">
            <SessionTokenMeter tokenStats={tokenStats} />
          </div>
        </div>
        <ChatInput
          disabled={workspaceInitializing}
          streaming={currentSessionReceivingStream}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          modelProviderConfig={modelProviderConfig}
          imageAssetConfig={imageAssetConfig}
          permissionMode={permissionMode}
          supportedPermissionModes={supportedPermissionModes}
          onSelectPermissionMode={setPermissionMode}
          onSelectChatModel={setSelectedChatModel}
          selectedChatModelId={selectedChatModelId}
          chatThinkingMode={chatThinkingMode}
          onSelectThinkingMode={setChatThinkingMode}
        />
      </div>
    </section>
  );
}

function runtimeLogOpenHandler(
  message: Message,
  openRuntimeLog: StoreActions["openRuntimeLog"],
) {
  const taskRunId = String(message.sourceTaskRunId || "").trim();
  if (taskRunId) {
    return () => openRuntimeLog({
      scope: "task_run",
      run_id: taskRunId,
      title: "执行日志",
      subtitle: runtimeLogSubtitle(message),
    });
  }
  const turnRunId = String(message.sourceTurnRunId || "").trim();
  if (turnRunId) {
    return () => openRuntimeLog({
      scope: "turn_run",
      run_id: turnRunId,
      title: "执行日志",
      subtitle: runtimeLogSubtitle(message),
    });
  }
  return undefined;
}

function runtimeLogSubtitle(message: Message) {
  const count = Number(message.toolEventCount ?? 0);
  if (Number.isFinite(count) && count > 0) {
    return `${count} 次工具调用`;
  }
  return String(message.runtimeLogRef || "完整运行轨迹").trim();
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

export function shouldSuppressSessionActivityBar(messages: Message[], active: boolean) {
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  if (!latestAssistant) return false;
  const visibleAssistantContent = shouldDisplayAssistantContent({
    answerCanonicalState: latestAssistant.answerCanonicalState,
    answerChannel: latestAssistant.answerChannel,
    answerPersistPolicy: latestAssistant.answerPersistPolicy,
    answerSource: latestAssistant.answerSource,
    answerLeakFlags: latestAssistant.answerLeakFlags,
  }) && latestAssistant.content.trim();
  if (visibleAssistantContent) {
    return true;
  }
  if (latestAssistant.projectionView?.canonicalContent.trim()) {
    return true;
  }
  if (latestAssistant.closeoutSummary?.trim()) {
    return true;
  }
  if (active) {
    return true;
  }
  return Boolean(
    latestAssistant.projectionView?.blocks.some((block) => block.kind !== "body_segment" && block.kind !== "log_entry")
  );
}

export function chatMessageRenderKeys(messages: Pick<Message, "id" | "role" | "sourceIndex">[]) {
  const seen = new Map<string, number>();
  return messages.map((message, index) => {
    const base = String(message.id || `${message.role}:${message.sourceIndex ?? index}`).trim() || `${message.role}:${index}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return count ? `${base}:duplicate-${count}` : base;
  });
}

type LiveAssistantSelectionOptions = {
  activeTurnSnapshot?: ActiveTurnSnapshot | null;
  currentSessionReceivingStream: boolean;
  currentTaskIsRunning: boolean;
  taskGraphLiveMonitor?: HarnessTaskRunLiveMonitor | null;
};

type LiveAssistantBinding = {
  streamRunId: string;
  taskRunId: string;
  turnId: string;
  turnRunId: string;
};

export function liveAssistantMessageIdForMessages(
  messages: Message[],
  options: LiveAssistantSelectionOptions,
) {
  if (!options.currentSessionReceivingStream && !options.currentTaskIsRunning) {
    return "";
  }
  const binding = liveAssistantBindingFromState(options.activeTurnSnapshot, options.taskGraphLiveMonitor);
  if (hasLiveAssistantBinding(binding)) {
    return matchingLiveAssistantMessageId(messages, binding);
  }
  if (!options.currentSessionReceivingStream) {
    return "";
  }
  return latestAssistantMessageId(messages);
}

function liveAssistantBindingFromState(
  activeTurnSnapshot: ActiveTurnSnapshot | null | undefined,
  taskGraphLiveMonitor: HarnessTaskRunLiveMonitor | null | undefined,
): LiveAssistantBinding {
  const monitorBinding = liveAssistantBindingFromMonitor(taskGraphLiveMonitor);
  return {
    streamRunId: monitorBinding.streamRunId,
    taskRunId: textValue(activeTurnSnapshot?.task_run_id) || monitorBinding.taskRunId,
    turnId: textValue(activeTurnSnapshot?.turn_id) || monitorBinding.turnId,
    turnRunId: textValue(activeTurnSnapshot?.turn_run_id) || monitorBinding.turnRunId,
  };
}

function liveAssistantBindingFromMonitor(
  taskGraphLiveMonitor: HarnessTaskRunLiveMonitor | null | undefined,
): LiveAssistantBinding {
  const monitor = recordValue(taskGraphLiveMonitor);
  if (!liveMonitorCanBindAssistant(monitor)) {
    return emptyLiveAssistantBinding();
  }
  const taskRun = recordValue(monitor.task_run);
  const activeTurnSnapshot = recordValue(monitor.active_turn_snapshot);
  return {
    streamRunId: textValue(activeTurnSnapshot.stream_run_id)
      || textValue(monitor.stream_run_id)
      || textValue(monitor.streamRunId),
    taskRunId: textValue(activeTurnSnapshot.bound_task_run_id)
      || textValue(activeTurnSnapshot.task_run_id)
      || textValue(taskRun.task_run_id)
      || textValue(monitor.task_run_id)
      || textValue(monitor.runtime_task_run_id),
    turnId: textValue(activeTurnSnapshot.turn_id)
      || textValue(monitor.latest_interaction_turn_id)
      || textValue(monitor.turn_id),
    turnRunId: textValue(activeTurnSnapshot.turn_run_id)
      || textValue(monitor.turn_run_id),
  };
}

function liveMonitorCanBindAssistant(monitor: Record<string, unknown>) {
  if (!Object.keys(monitor).length) {
    return false;
  }
  const lifecycle = textValue(monitor.lifecycle).toLowerCase();
  const bucket = textValue(monitor.bucket).toLowerCase();
  if (monitor.stale === true || lifecycle === "stale" || bucket === "diagnostics") {
    return false;
  }
  const taskRun = recordValue(monitor.task_run);
  const status = (textValue(monitor.status) || textValue(taskRun.status)).toLowerCase();
  const activityState = textValue(monitor.activity_state).toLowerCase();
  if (monitor.is_live === false && !LIVE_MONITOR_BINDING_STATES.has(status) && !LIVE_MONITOR_BINDING_STATES.has(activityState)) {
    return false;
  }
  return true;
}

const LIVE_MONITOR_BINDING_STATES = new Set([
  "created",
  "running",
  "waiting",
  "waiting_executor",
  "waiting_approval",
  "waiting_safe_boundary",
]);

export function chatTaskMonitorIsActive(taskGraphLiveMonitor: HarnessTaskRunLiveMonitor | null | undefined) {
  const monitor = recordValue(taskGraphLiveMonitor);
  if (!liveMonitorCanBindAssistant(monitor)) {
    return false;
  }
  const taskRun = recordValue(monitor.task_run);
  const status = (textValue(monitor.status) || textValue(taskRun.status)).toLowerCase();
  const activityState = textValue(monitor.activity_state).toLowerCase();
  return LIVE_MONITOR_BINDING_STATES.has(status)
    || LIVE_MONITOR_BINDING_STATES.has(activityState)
    || monitor.is_running === true
    || monitor.is_waiting === true;
}

function emptyLiveAssistantBinding(): LiveAssistantBinding {
  return {
    streamRunId: "",
    taskRunId: "",
    turnId: "",
    turnRunId: "",
  };
}

function matchingLiveAssistantMessageId(messages: Message[], binding: LiveAssistantBinding) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== "assistant") {
      continue;
    }
    if (binding.streamRunId && (message.sourceStreamRunId === binding.streamRunId || message.sourceRunId === binding.streamRunId)) {
      return message.id;
    }
    if (binding.turnRunId && message.sourceTurnRunId === binding.turnRunId) {
      return message.id;
    }
    if (binding.taskRunId && message.sourceTaskRunId === binding.taskRunId) {
      return message.id;
    }
    if (binding.turnId && message.sourceTurnId === binding.turnId) {
      return message.id;
    }
  }
  return "";
}

function latestAssistantMessageId(messages: Message[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant") {
      return message.id;
    }
  }
  return "";
}

function hasLiveAssistantBinding(binding: LiveAssistantBinding) {
  return Boolean(binding.streamRunId || binding.taskRunId || binding.turnId || binding.turnRunId);
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown) {
  return String(value ?? "").trim();
}

function SessionTokenMeter({ tokenStats }: { tokenStats: TokenStats | null }) {
  const presentation = sessionContextMeterPresentation(tokenStats);
  if (!presentation) {
    return null;
  }
  return (
    <div
      aria-label={`压缩触发窗口 ${presentation.usedTokenText} / ${presentation.thresholdTokenText}`}
      className={`chat-token-meter chat-token-meter--${presentation.levelClass}`}
      style={{ "--chat-token-meter-used": `${presentation.usedPercent}%` } as CSSProperties}
      title={presentation.title}
    >
      <strong>{presentation.usedTokenText}</strong>
      <span className="chat-token-meter__separator" aria-hidden="true">/</span>
      <strong>{presentation.thresholdTokenText}</strong>
    </div>
  );
}

export function sessionContextMeterPresentation(tokenStats: TokenStats | null) {
  if (!tokenStats) {
    return {
      usedPercent: 0,
      usedTokenText: "--",
      thresholdTokenText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    };
  }
  const contextMeter = tokenStats.context_meter;
  if (!contextMeter) {
    return {
      usedPercent: 0,
      usedTokenText: "--",
      thresholdTokenText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    };
  }
  const displayTokens = compactionTriggerWindowTokens(tokenStats);
  const contextWindowTokens = currentContextWindowTokens(tokenStats);
  const thresholdTokens = compactionThresholdTokens(tokenStats);
  const thresholdRatio = currentContextThresholdRatio(displayTokens, thresholdTokens);
  const usedPercent = percentFromRatio(thresholdRatio);
  const thresholdPercentText = thresholdTokens > 0 ? `${usedPercent}%` : "--";
  const levelClass = contextThresholdLevelClass(thresholdRatio);
  const remainingTokens = Math.max(0, thresholdTokens - displayTokens);
  const usedTokenText = formatTokenCount(displayTokens);
  const thresholdTokenText = thresholdTokens > 0 ? formatTokenCount(thresholdTokens) : "--";
  const title = [
    `压缩触发窗口 ${formatExactTokenCount(displayTokens)} tokens`,
    thresholdTokens > 0 ? `自动压缩阈值 ${formatExactTokenCount(thresholdTokens)} tokens` : "",
    thresholdTokens > 0 ? `阈值占比 ${thresholdPercentText}` : "",
    contextWindowTokens > 0 ? `模型窗口 ${formatExactTokenCount(contextWindowTokens)} tokens` : "",
    thresholdTokens > 0 ? `距自动压缩还剩 ${formatExactTokenCount(remainingTokens)} tokens` : "",
  ].filter(Boolean).join("；");
  return {
    usedPercent,
    usedTokenText,
    thresholdTokenText,
    title,
    levelClass,
  };
}

function percentFromRatio(value: unknown) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
}

function compactionTriggerWindowTokens(tokenStats: TokenStats) {
  const value = Number(tokenStats.context_meter?.compaction_pressure_tokens ?? tokenStats.context_meter?.current_context_tokens ?? 0);
  return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function currentContextWindowTokens(tokenStats: TokenStats) {
  const value = Number(tokenStats.context_meter?.context_window_tokens ?? 0);
  return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function compactionThresholdTokens(tokenStats: TokenStats) {
  const value = Number(tokenStats.context_meter?.replacement_threshold_tokens ?? 0);
  return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function currentContextThresholdRatio(currentTokens: number, thresholdTokens: number) {
  if (thresholdTokens > 0) {
    return currentTokens / thresholdTokens;
  }
  return 0;
}

function contextThresholdLevelClass(thresholdRatio: number) {
  if (thresholdRatio >= 1) {
    return "over_threshold";
  }
  if (thresholdRatio >= 0.85) {
    return "near_threshold";
  }
  return "normal";
}

function formatTokenCount(value: unknown) {
  const number = Math.max(0, Math.round(Number(value || 0)));
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return String(number);
}

function formatExactTokenCount(value: unknown) {
  return Math.max(0, Math.round(Number(value || 0))).toLocaleString("en-US");
}
