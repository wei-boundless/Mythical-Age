"use client";

import { useEffect, useMemo, useRef } from "react";
import { Gauge } from "lucide-react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { VSCodeStatusPanel } from "@/features/vscode-connection/VSCodeStatusPanel";
import { sessionSummaryIsRunning } from "@/lib/sessionTaskPresentation";
import { useAppStoreActions, useAppStoreSelector } from "@/lib/store";
import { shallowEqual } from "@/lib/store/hooks";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import type { HarnessTaskRunLiveMonitor } from "@/lib/api";
import type { ActiveTurnSnapshot, ChatStreamConnectionStatus, Message, StoreActions, StoreState, TokenStats } from "@/lib/store/types";

export function ChatPanel() {
  const {
    messages,
    activeProjectionsByKey,
    activeStreamSessionIds,
    sessionActivity,
    currentSessionId,
    conversationActiveEnvironment,
    workspaceInitializing,
    modelProviderConfig,
    imageAssetConfig,
    permissionMode,
    supportedPermissionModes,
    chatThinkingMode,
    chatStreamDisplayEnabled,
    selectedChatModelId,
    sessions,
    tokenStats,
    chatStreamConnectionStatus,
    activeTurnSnapshot,
    taskGraphLiveMonitor,
  } = useAppStoreSelector((state) => ({
    messages: state.messages,
    activeProjectionsByKey: state.activeProjectionsByKey,
    activeStreamSessionIds: state.activeStreamSessionIds,
    sessionActivity: state.sessionActivity,
    currentSessionId: state.currentSessionId,
    conversationActiveEnvironment: state.conversationActiveEnvironment,
    workspaceInitializing: state.workspaceInitializing,
    modelProviderConfig: state.modelProviderConfig,
    imageAssetConfig: state.imageAssetConfig,
    permissionMode: state.permissionMode,
    supportedPermissionModes: state.supportedPermissionModes,
    chatThinkingMode: state.chatThinkingMode,
    chatStreamDisplayEnabled: state.chatStreamDisplayEnabled,
    selectedChatModelId: state.selectedChatModelId,
    sessions: state.sessions,
    tokenStats: state.tokenStats,
    chatStreamConnectionStatus: state.chatStreamConnectionStatus,
    activeTurnSnapshot: state.activeTurnSnapshot,
    taskGraphLiveMonitor: state.taskGraphLiveMonitor,
  }), shallowEqual);
  const {
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    setPermissionMode,
    setChatThinkingMode,
    setChatStreamDisplayEnabled,
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
            {conversationActiveEnvironment ? (
              <div className="chat-task-environment-binding" title={conversationActiveEnvironment.task_environment_id}>
                <span>环境</span>
                <strong>
                  {taskEnvironmentDisplayName(
                    conversationActiveEnvironment.task_environment_id,
                    conversationActiveEnvironment.environment_label,
                  )}
                </strong>
              </div>
            ) : null}
            <ChatStreamStatusBadge
              status={chatStreamConnectionStatus}
              streaming={currentSessionReceivingStream}
            />
            <VSCodeStatusPanel
              sessionId={currentSessionId}
              projectBinding={currentSession?.conversation_state?.project_binding ?? null}
            />
          </div>
          <SessionTokenMeter tokenStats={tokenStats} />
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
          chatStreamDisplayEnabled={chatStreamDisplayEnabled}
          onSelectThinkingMode={setChatThinkingMode}
          onSelectStreamDisplayEnabled={setChatStreamDisplayEnabled}
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

function ChatStreamStatusBadge({
  status,
  streaming,
}: {
  status: ChatStreamConnectionStatus;
  streaming: boolean;
}) {
  const presentation = chatStreamStatusPresentation(status, streaming);
  if (!presentation) {
    return null;
  }
  return (
    <div
      className={`chat-stream-status chat-stream-status--${presentation.state}`}
      title={presentation.title}
    >
      <span className="chat-stream-status__dot" />
      <span>{presentation.label}</span>
      {presentation.detail ? <strong>{presentation.detail}</strong> : null}
    </div>
  );
}

function chatStreamStatusPresentation(status: ChatStreamConnectionStatus, streaming: boolean) {
  const state = status.state === "idle" && streaming ? "streaming" : status.state;
  if (state === "idle") {
    return null;
  }
  if (state === "reconnecting") {
    const attempt = status.attempt
      ? `第 ${status.attempt} 次`
      : "";
    return {
      state,
      label: "输出流",
      detail: attempt ? `重连中 ${attempt}` : "重连中",
      title: status.reason ? `输出流连接中断，正在重连：${status.reason}` : "输出流连接中断，正在重连。",
    };
  }
  if (state === "failed") {
    return {
      state,
      label: "输出流",
      detail: "已断开",
      title: status.reason ? `输出流已断开：${status.reason}` : "输出流已断开。",
    };
  }
  if (state === "stopped") {
    return {
      state,
      label: "输出流",
      detail: "已停止",
      title: status.reason ? `输出流已停止：${status.reason}` : "输出流已停止。",
    };
  }
  if (state === "reconnected") {
    return {
      state,
      label: "输出流",
      detail: "已恢复",
      title: "输出流已恢复，继续接收事件。",
    };
  }
  return {
    state,
    label: "输出流",
    detail: "正常",
    title: "正在接收输出流事件。",
  };
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
    <div className={`chat-token-meter chat-token-meter--${presentation.levelClass}`} title={presentation.title}>
      <Gauge size={14} />
      <span>{presentation.label}</span>
      <strong>{presentation.tokenRatioText}</strong>
      <span>{presentation.thresholdPercentText}</span>
    </div>
  );
}

export function sessionContextMeterPresentation(tokenStats: TokenStats | null) {
  if (!tokenStats) {
    return {
      label: "上下文",
      usedPercent: 0,
      thresholdPercentText: "--",
      tokenRatioText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    };
  }
  const contextMeter = tokenStats.context_meter;
  if (!contextMeter) {
    return {
      label: "上下文",
      usedPercent: 0,
      thresholdPercentText: "--",
      tokenRatioText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    };
  }
  const currentTokens = currentContextTokens(tokenStats);
  const contextWindowTokens = currentContextWindowTokens(tokenStats);
  const thresholdTokens = compactionThresholdTokens(tokenStats);
  const thresholdRatio = currentContextThresholdRatio(currentTokens, thresholdTokens);
  const usedPercent = percentFromRatio(thresholdRatio);
  const thresholdPercentText = thresholdTokens > 0 ? `${usedPercent}%` : "--";
  const levelClass = contextThresholdLevelClass(thresholdRatio);
  const remainingTokens = Math.max(0, thresholdTokens - currentTokens);
  const tokenRatioText = thresholdTokens > 0
    ? `${formatTokenCount(currentTokens)}/${formatTokenCount(thresholdTokens)}`
    : formatTokenCount(currentTokens);
  const title = [
    `当前上下文 ${formatExactTokenCount(currentTokens)} tokens`,
    thresholdTokens > 0 ? `自动压缩阈值 ${formatExactTokenCount(thresholdTokens)} tokens` : "",
    thresholdTokens > 0 ? `阈值占比 ${thresholdPercentText}` : "",
    contextWindowTokens > 0 ? `模型窗口 ${formatExactTokenCount(contextWindowTokens)} tokens` : "",
    thresholdTokens > 0 ? `距自动压缩还剩 ${formatExactTokenCount(remainingTokens)} tokens` : "",
  ].filter(Boolean).join("；");
  return {
    label: "上下文",
    usedPercent,
    thresholdPercentText,
    tokenRatioText,
    title,
    levelClass,
  };
}

function percentFromRatio(value: unknown) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
}

function currentContextTokens(tokenStats: TokenStats) {
  const value = Number(tokenStats.context_meter?.current_context_tokens ?? 0);
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
