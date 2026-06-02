"use client";

import { useEffect, useMemo, useRef } from "react";
import { Play, Square, X } from "lucide-react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatSearchPolicyControls } from "@/components/chat/ChatSearchPolicyControls";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { useAppStore } from "@/lib/store";

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
    resumeActiveTaskRun,
    chatTaskEnvironmentBinding,
    clearChatTaskEnvironmentBinding,
    workspaceInitializing,
    modelProviderConfig,
    imageAssetConfig,
    chatThinkingMode,
    setChatThinkingMode,
    selectedChatModelId,
    setSelectedChatModel,
    searchPolicy,
    toggleSearchPolicySource,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const canClearTaskEnvironmentBinding = Boolean(chatTaskEnvironmentBinding && chatTaskEnvironmentBinding.source !== "workspace-mode");
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
  const canStopSingleAgentTask = Boolean(
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
      || monitorControlState === "paused"
      || monitorControlState === "pause_requested"
    ),
  );
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
              retrievals={message.retrievals}
              role={message.role}
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
          {canStopSingleAgentTask ? (
            <button
              className="chat-runtime-action chat-runtime-action--stop"
              onClick={() => {
                void stopActiveTaskRun();
              }}
              type="button"
            >
              <Square size={13} />
              停止任务
            </button>
          ) : null}
          {canResumeSingleAgentTask ? (
            <button
              className="chat-runtime-action"
              onClick={() => {
                void resumeActiveTaskRun();
              }}
              type="button"
            >
              <Play size={13} />
              继续
            </button>
          ) : null}
          {chatTaskEnvironmentBinding ? (
            <div className="chat-task-environment-binding" title={chatTaskEnvironmentBinding.task_environment_id}>
              <span>环境</span>
              <strong>{chatTaskEnvironmentBinding.environment_label || chatTaskEnvironmentBinding.task_environment_id}</strong>
              {canClearTaskEnvironmentBinding ? (
                <button aria-label="解除任务环境绑定" onClick={clearChatTaskEnvironmentBinding} type="button">
                  <X size={13} />
                </button>
              ) : null}
            </div>
          ) : null}
          <ChatSearchPolicyControls
            onToggleSearchPolicy={toggleSearchPolicySource}
            searchPolicy={searchPolicy}
          />
        </div>
        <ChatInput
          disabled={workspaceInitializing}
          streaming={currentSessionStreaming}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          modelProviderConfig={modelProviderConfig}
          imageAssetConfig={imageAssetConfig}
          onSelectChatModel={setSelectedChatModel}
          selectedChatModelId={selectedChatModelId}
          chatThinkingMode={chatThinkingMode}
          onSelectThinkingMode={setChatThinkingMode}
        />
      </div>
    </section>
  );
}

