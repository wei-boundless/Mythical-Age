"use client";

import { useEffect, useMemo, useRef } from "react";
import { Gauge } from "lucide-react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { hasPublicRunActivity } from "@/components/chat/PublicRunActivity";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import type { PublicChatTimelineItem } from "@/lib/api";
import { sessionSummaryIsRunning } from "@/lib/sessionTaskPresentation";
import { useAppStore } from "@/lib/store";
import { mergePublicTimelineItems, publicTimelineItemText, publicTimelineTerminalStateFromAnswer } from "@/lib/store/publicTimeline";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import type { Message, TokenStats } from "@/lib/store/types";

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
    pauseActiveTaskRun,
    resumeActiveTaskRun,
    conversationActiveEnvironment,
    workspaceInitializing,
    modelProviderConfig,
    imageAssetConfig,
    permissionMode,
    supportedPermissionModes,
    setPermissionMode,
    chatThinkingMode,
    setChatThinkingMode,
    selectedChatModelId,
    setSelectedChatModel,
    sessions,
    tokenStats,
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
  const canResumeSingleAgentTask = Boolean(
    isSingleAgentTaskMonitor
    && !currentSessionReceivingStream
    && taskGraphLiveMonitor?.is_resumable === true,
  );
  const canInterruptSingleAgentTask = Boolean(
    canControlSingleAgentTask
    && !currentSessionReceivingStream
    && taskGraphLiveMonitor?.is_interruptible === true
  );
  const chatPrimaryTaskAction = canResumeSingleAgentTask
    ? {
        kind: "resume" as const,
        onAction: resumeActiveTaskRun,
      }
    : canInterruptSingleAgentTask
      ? {
          kind: "interrupt" as const,
          onAction: pauseActiveTaskRun,
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

          {messages.map((message) => (
            <ChatMessage
              canEdit={!currentSessionActive && message.id === lastEditableUserMessageId}
              content={message.content}
              image={message.image}
              id={message.id}
              key={message.id}
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
              retrievals={message.retrievals}
              role={message.role}
              runtimePublicTimelineDraft={message.runtimePublicTimelineDraft}
              runtimeAttachments={message.runtimeAttachments}
              runtimeProgress={message.runtimeProgress}
              stageStatus={message.stageStatus}
              toolCalls={message.toolCalls}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-panel-footer min-w-0">
        <div className="chat-panel-status-row">
          {suppressFooterActivity ? null : <SessionActivityBar activity={sessionActivity} active={currentSessionActive} />}
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
          onSelectThinkingMode={setChatThinkingMode}
        />
      </div>
    </section>
  );
}

export function shouldSuppressSessionActivityBar(messages: Message[], _active: boolean) {
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  if (!latestAssistant) return false;
  const persisted = (latestAssistant.runtimeAttachments ?? []).flatMap((attachment) =>
    Array.isArray(attachment.public_timeline) ? attachment.public_timeline : [],
  );
  const publicTimeline = mergePublicTimelineItems(
    persisted,
    latestAssistant.runtimePublicTimelineDraft,
    {
      terminalState: publicTimelineTerminalStateFromAnswer({
        answerCanonicalState: latestAssistant.answerCanonicalState,
        answerChannel: latestAssistant.answerChannel,
      }),
    },
  );
  if (!latestAssistant.content.trim() && publicTimeline.some(isMessageLevelAssistantFeedback)) {
    return true;
  }
  if (latestAssistant.content.trim() && latestAssistant.answerChannel === "active_work_control") {
    return true;
  }
  return hasPublicRunActivity(publicTimeline, latestAssistant.content);
}

function isMessageLevelAssistantFeedback(item: PublicChatTimelineItem) {
  const kind = String(item.kind || "").trim();
  return (kind === "assistant_text" || kind === "opening_judgment") && Boolean(publicTimelineItemText(item));
}

function SessionTokenMeter({ tokenStats }: { tokenStats: TokenStats | null }) {
  const presentation = sessionContextPressurePresentation(tokenStats);
  if (!presentation) {
    return null;
  }
  return (
    <div className={`chat-token-meter chat-token-meter--${presentation.levelClass}`} title={presentation.title}>
      <Gauge size={14} />
      <span>{presentation.label}</span>
      <strong>{presentation.pressurePercentText}</strong>
      {presentation.remainingTokenText ? <em>{presentation.remainingTokenText}</em> : null}
    </div>
  );
}

export function sessionContextPressurePresentation(tokenStats: TokenStats | null) {
  if (!tokenStats) {
    return {
      label: "上下文同步中",
      usedPercent: 0,
      remainingPercent: 0,
      pressurePercentText: "--",
      remainingPercentText: "--",
      remainingTokens: 0,
      remainingTokenText: "",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    };
  }
  const contextMeter = tokenStats.context_meter;
  const pressureLevel = String(contextMeter?.pressure_level || tokenStats.history_pressure_level || "normal").trim() || "normal";
  const levelClass = tokenPressureClass(pressureLevel);
  const usedPercent = percentFromRatio(currentSessionContextRatio(tokenStats));
  const remainingPercent = currentSessionRemainingPercent(tokenStats, usedPercent);
  const remainingTokens = currentSessionRemainingTokens(tokenStats);
  const didCompact = Boolean(tokenStats.history_did_compact || tokenStats.history_did_microcompact || tokenStats.history_did_full_compact);
  const label = didCompact
    ? "已压缩"
    : pressureLevel === "full_compact"
      ? "需要压缩"
      : pressureLevel === "microcompact"
        ? "接近压缩"
        : pressureLevel === "warning"
          ? "压力偏高"
          : "上下文压力";
  const pressurePercentText = `${usedPercent}%`;
  const remainingPercentText = `${remainingPercent}%`;
  const remainingTokenText = remainingTokens > 0 ? `距压缩 ${formatTokenCount(remainingTokens)}` : "";
  const title = [
    `当前 session 上下文压力 ${pressurePercentText}`,
    `距离自动压缩阈值剩余 ${remainingPercentText}`,
    remainingTokenText ? `距压缩 ${formatExactTokenCount(remainingTokens)} tokens` : "",
  ].filter(Boolean).join("；");
  return {
    label,
    usedPercent,
    remainingPercent,
    pressurePercentText,
    remainingPercentText,
    remainingTokens,
    remainingTokenText,
    title,
    levelClass,
  };
}

function tokenPressureClass(value: string) {
  const normalized = value.replace(/[^a-z0-9_-]/gi, "_").toLowerCase();
  return normalized || "normal";
}

function percentFromRatio(value: unknown) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
}

function currentSessionContextRatio(tokenStats: TokenStats) {
  const rawSessionPressureRatio = tokenStats.session_context_pressure?.pressure_ratio;
  const sessionPressureRatio = Number(rawSessionPressureRatio);
  if (rawSessionPressureRatio !== undefined && rawSessionPressureRatio !== null && Number.isFinite(sessionPressureRatio)) {
    return sessionPressureRatio;
  }
  const rawCompactionRatio = tokenStats.context_meter?.compaction_pressure_ratio;
  const compactionRatio = Number(rawCompactionRatio);
  if (rawCompactionRatio !== undefined && rawCompactionRatio !== null && Number.isFinite(compactionRatio)) {
    return compactionRatio;
  }
  const rawContextRatio = tokenStats.context_meter?.current_context_ratio;
  const contextRatio = Number(rawContextRatio);
  if (rawContextRatio !== undefined && rawContextRatio !== null && Number.isFinite(contextRatio)) {
    return contextRatio;
  }
  return Number(tokenStats.history_usage_ratio || 0);
}

function currentSessionRemainingPercent(tokenStats: TokenStats, usedPercent: number) {
  const rawSessionRemainingRatio = tokenStats.session_context_pressure?.remaining_ratio;
  const sessionRemainingRatio = Number(rawSessionRemainingRatio);
  if (rawSessionRemainingRatio !== undefined && rawSessionRemainingRatio !== null && Number.isFinite(sessionRemainingRatio)) {
    return percentFromRatio(sessionRemainingRatio);
  }
  const rawRemainingRatio = tokenStats.context_meter?.compaction_remaining_ratio;
  const remainingRatio = Number(rawRemainingRatio);
  if (rawRemainingRatio !== undefined && rawRemainingRatio !== null && Number.isFinite(remainingRatio)) {
    return percentFromRatio(remainingRatio);
  }
  return Math.max(0, 100 - usedPercent);
}

function currentSessionRemainingTokens(tokenStats: TokenStats) {
  const rawSessionRemaining = tokenStats.session_context_pressure?.remaining_tokens;
  const sessionRemaining = Number(rawSessionRemaining);
  if (rawSessionRemaining !== undefined && rawSessionRemaining !== null && Number.isFinite(sessionRemaining)) {
    return Math.max(0, Math.round(sessionRemaining));
  }
  const rawCompactionRemaining = tokenStats.context_meter?.compaction_remaining_tokens;
  const compactionRemaining = Number(rawCompactionRemaining);
  if (rawCompactionRemaining !== undefined && rawCompactionRemaining !== null && Number.isFinite(compactionRemaining)) {
    return Math.max(0, Math.round(compactionRemaining));
  }
  const replacementThresholdTokens = Number(tokenStats.context_meter?.replacement_threshold_tokens || 0);
  const currentContextTokens = Number(tokenStats.context_meter?.current_context_tokens || 0);
  if (Number.isFinite(replacementThresholdTokens) && replacementThresholdTokens > 0 && Number.isFinite(currentContextTokens)) {
    return Math.max(0, Math.round(replacementThresholdTokens - currentContextTokens));
  }
  const historyRemainingTokens = Number(tokenStats.history_remaining_tokens || 0);
  return Number.isFinite(historyRemainingTokens) ? Math.max(0, Math.round(historyRemainingTokens)) : 0;
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

