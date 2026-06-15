"use client";

import { useEffect, useMemo, useRef } from "react";
import { Gauge } from "lucide-react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { VSCodeStatusPanel } from "@/features/vscode-connection/VSCodeStatusPanel";
import { sessionSummaryIsRunning } from "@/lib/sessionTaskPresentation";
import { useAppStore } from "@/lib/store";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import type { ChatStreamConnectionStatus, Message, TokenStats } from "@/lib/store/types";

export function ChatPanel() {
  const {
    messages,
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    activeStreamSessionIds,
    sessionActivity,
    currentSessionId,
    taskGraphLiveMonitor,
    stopActiveTaskRun,
    conversationActiveEnvironment,
    workspaceInitializing,
    modelProviderConfig,
    imageAssetConfig,
    permissionMode,
    supportedPermissionModes,
    setPermissionMode,
    chatThinkingMode,
    setChatThinkingMode,
    chatStreamDisplayEnabled,
    setChatStreamDisplayEnabled,
    openRuntimeLog,
    selectedChatModelId,
    setSelectedChatModel,
    sessions,
    tokenStats,
    chatStreamConnectionStatus,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) ?? null,
    [currentSessionId, sessions],
  );
  const currentSessionReceivingStream = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const currentTaskIsRunning = currentSession ? sessionSummaryIsRunning(currentSession) : false;
  const currentSessionActive = currentSessionReceivingStream || currentTaskIsRunning;
  const suppressFooterActivity = shouldSuppressSessionActivityBar(messages, currentSessionActive);
  const messageRenderKeys = useMemo(() => chatMessageRenderKeys(messages), [messages]);
  const liveAssistantMessageId = useMemo(() => {
    if (!currentSessionReceivingStream) {
      return "";
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "assistant") {
        return message.id;
      }
    }
    return "";
  }, [currentSessionReceivingStream, messages]);
  const monitorRecord = taskGraphLiveMonitor as Record<string, unknown> | null;
  const monitorTaskRun = taskGraphLiveMonitor?.task_run ?? {};
  const monitorRuntimeControl = taskGraphLiveMonitor?.runtime_control ?? {};
  const monitorRoute = monitorRecord?.route && typeof monitorRecord.route === "object" && !Array.isArray(monitorRecord.route)
    ? monitorRecord.route as Record<string, unknown>
    : {};
  const monitorRuntimeKind = String(
    taskGraphLiveMonitor?.execution_runtime_kind
    ?? monitorTaskRun.execution_runtime_kind
    ?? "",
  ).trim();
  const monitorStatus = String(taskGraphLiveMonitor?.status ?? monitorTaskRun.status ?? "").trim();
  const monitorControlState = String(taskGraphLiveMonitor?.control_state ?? monitorRuntimeControl.state ?? "").trim();
  const singleAgentTaskRunId = String(monitorTaskRun.task_run_id ?? taskGraphLiveMonitor?.task_run_id ?? "").trim();
  const isSingleAgentTaskMonitor = Boolean(
    taskGraphLiveMonitor
    && monitorRuntimeKind === "single_agent_task"
    && String(monitorRoute.kind ?? "").trim() !== "task_graph_run",
  );
  const terminalTaskStatuses = new Set(["completed", "done", "failed", "error", "cancelled", "canceled", "stopped", "aborted", "user_aborted"]);
  const terminalControlStates = new Set(["stopped", "aborted", "user_aborted"]);
  const canControlSingleAgentTask = Boolean(
    isSingleAgentTaskMonitor
    && singleAgentTaskRunId
    && !terminalTaskStatuses.has(monitorStatus)
    && !terminalControlStates.has(monitorControlState)
    && monitorControlState !== "stop_requested"
  );
  const canStopSingleAgentTask = Boolean(
    canControlSingleAgentTask
    && !currentSessionReceivingStream
    && taskGraphLiveMonitor?.is_interruptible === true
  );
  const chatPrimaryTaskAction = canStopSingleAgentTask
    ? {
        kind: "stop_task" as const,
        onAction: stopActiveTaskRun,
      }
    : null;
  const lastEditableUserMessageId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "user" && message.sourceIndex !== undefined) {
        return message.id;
      }
    }
    return null;
  }, [messages]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <section className="chat-panel-shell grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden">
      <div className="chat-thread flex min-h-0 min-w-0 flex-col overflow-hidden">
        <div className="chat-thread__messages flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {!messages.length ? (
            <div className="chat-thread__empty">
              <div>
                <strong>等待你的下一句话。</strong>
                <span>可以直接开始对话，也可以把任务交给当前会话。</span>
              </div>
            </div>
          ) : null}

          {messages.map((message, index) => (
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
              mainChatSurface={message.mainChatSurface}
              onOpenRuntimeLog={runtimeLogOpenHandler(message, openRuntimeLog)}
              publicProjection={message.publicProjection}
              retrievals={message.retrievals}
              role={message.role}
              runtimeDisplayState={message.runtimeDisplayState}
              runtimeLogRef={message.runtimeLogRef}
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
          taskPrimaryAction={chatPrimaryTaskAction}
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
  openRuntimeLog: ReturnType<typeof useAppStore>["openRuntimeLog"],
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
  if (latestAssistant.publicProjection?.bodyText.trim()) {
    return true;
  }
  if (latestAssistant.closeoutSummary?.trim()) {
    return true;
  }
  if (active) {
    return true;
  }
  return Boolean(
    latestAssistant.publicProjection?.currentAction
    || latestAssistant.publicProjection?.pinned.length
    || latestAssistant.publicProjection?.finalResults.length
    || latestAssistant.publicProjection?.status.length
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
