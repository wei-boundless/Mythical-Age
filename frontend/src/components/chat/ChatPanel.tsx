"use client";

import { useEffect, useMemo, useRef } from "react";
import { Gauge } from "lucide-react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { useAppStore } from "@/lib/store";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import type { TokenStats } from "@/lib/store/types";

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
    tokenStats,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
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
    && !currentSessionStreaming
    && (
      monitorStatus === "waiting_executor"
      || monitorStatus === "waiting_approval"
      || monitorStatus === "blocked"
      || monitorControlState === "paused"
      || monitorControlState === "pause_requested"
    ),
  );
  const canInterruptSingleAgentTask = Boolean(
    canControlSingleAgentTask
    && !currentSessionStreaming
    && monitorStatus !== "waiting_executor"
    && monitorControlState !== "paused"
    && monitorControlState !== "pause_requested"
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
              canEdit={!currentSessionStreaming && message.id === lastEditableUserMessageId}
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
          <SessionActivityBar activity={sessionActivity} active={currentSessionStreaming} />
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
          streaming={currentSessionStreaming}
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

function SessionTokenMeter({ tokenStats }: { tokenStats: TokenStats | null }) {
  if (!tokenStats) {
    return null;
  }
  const currentContextTokens = currentContextTokenCount(tokenStats);
  const cumulativeTokens = cumulativeTranscriptTokenCount(tokenStats);
  const compressionSavedTokens = compressionSavedTokenCount(tokenStats);
  const contextWindowTokens = Number(tokenStats.context_meter?.context_window_tokens || 0);
  const usagePercent = percentFromRatio(contextUsageRatio(tokenStats));
  const remainingPercent = percentFromRatio(tokenStats.history_remaining_ratio);
  const pressureLevel = String(tokenStats.context_meter?.pressure_level || tokenStats.history_pressure_level || "normal").trim() || "normal";
  const title = [
    contextWindowTokens > 0
      ? `当前上下文 ${formatTokenCount(currentContextTokens)}/${formatTokenCount(contextWindowTokens)} tokens`
      : `当前上下文 ${formatTokenCount(currentContextTokens)} tokens`,
    `累计原始会话 ${formatTokenCount(cumulativeTokens)} tokens`,
    tokenStats.cumulative_transcript_message_count ? `累计消息 ${tokenStats.cumulative_transcript_message_count} 条` : "",
    `会话总计 ${formatTokenCount(tokenStats.total_tokens)} tokens`,
    `消息 ${formatTokenCount(tokenStats.message_tokens)}`,
    `系统 ${formatTokenCount(tokenStats.system_tokens)}`,
    `当前运行历史 ${formatTokenCount(tokenStats.raw_history_tokens)} tokens`,
    `有效历史 ${formatTokenCount(tokenStats.history_tokens)}/${formatTokenCount(tokenStats.history_budget_tokens)}`,
    compressionSavedTokens > 0 ? `压缩节省 ${formatTokenCount(compressionSavedTokens)} tokens` : "",
    tokenStats.compression_ratio !== undefined ? `压缩后占累计 ${percentFromRatio(tokenStats.compression_ratio)}%` : "",
    `已用 ${usagePercent}%`,
    `余量 ${remainingPercent}%`,
    tokenStats.history_did_compact ? "本次预览会压缩当前运行历史" : "",
  ].filter(Boolean).join("；");
  return (
    <div className={`chat-token-meter chat-token-meter--${tokenPressureClass(pressureLevel)}`} title={title}>
      <Gauge size={14} />
      <span>上下文</span>
      <strong>{usagePercent}%</strong>
      <em>当前 {formatTokenCount(currentContextTokens)} · 累计 {formatTokenCount(cumulativeTokens)}</em>
    </div>
  );
}

function tokenPressureClass(value: string) {
  const normalized = value.replace(/[^a-z0-9_-]/gi, "_").toLowerCase();
  return normalized || "normal";
}

function formatTokenCount(value: unknown) {
  const number = Math.max(0, Math.round(Number(value || 0)));
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return String(number);
}

function percentFromRatio(value: unknown) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
}

function contextUsageRatio(tokenStats: TokenStats) {
  const rawContextRatio = tokenStats.context_meter?.current_context_ratio;
  const contextRatio = Number(rawContextRatio);
  if (rawContextRatio !== undefined && rawContextRatio !== null && Number.isFinite(contextRatio)) {
    return contextRatio;
  }
  return Number(tokenStats.history_usage_ratio || 0);
}

function currentContextTokenCount(tokenStats: TokenStats) {
  const rawCurrent = tokenStats.context_meter?.current_context_tokens;
  const current = Number(rawCurrent);
  if (rawCurrent !== undefined && rawCurrent !== null && Number.isFinite(current)) {
    return current;
  }
  return Number(tokenStats.total_tokens || 0);
}

function cumulativeTranscriptTokenCount(tokenStats: TokenStats) {
  const rawCumulative = tokenStats.cumulative_transcript_tokens;
  const cumulative = Number(rawCumulative);
  if (rawCumulative !== undefined && rawCumulative !== null && Number.isFinite(cumulative)) {
    return cumulative;
  }
  return Math.max(Number(tokenStats.raw_history_tokens || 0), Number(tokenStats.total_tokens || 0));
}

function compressionSavedTokenCount(tokenStats: TokenStats) {
  const rawSaved = tokenStats.compression_saved_tokens;
  const saved = Number(rawSaved);
  if (rawSaved !== undefined && rawSaved !== null && Number.isFinite(saved)) {
    return Math.max(0, saved);
  }
  return Math.max(cumulativeTranscriptTokenCount(tokenStats) - Number(tokenStats.history_tokens || 0), 0);
}

