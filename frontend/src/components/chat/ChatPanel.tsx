"use client";

import { useEffect, useMemo, useRef } from "react";

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
    pauseActiveTaskRun,
    resumeActiveTaskRun,
    stopActiveTaskRun,
    resendEditedMessage,
    activeStreamSessionIds,
    sessionActivity,
    taskGraphLiveMonitor,
    currentSessionId,
    workspaceInitializing,
    modelProviderConfig,
    soulImageAssetConfig,
    deepSeekThinkingEnabled,
    setDeepSeekThinkingEnabled,
    mainAgentAssemblyMode,
    setMainAgentAssemblyMode,
    selectedChatModelId,
    setSelectedChatModel,
    searchPolicy,
    toggleSearchPolicySource,
    taskSelection,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const activeTaskControl = useMemo(() => deriveActiveTaskControl(taskGraphLiveMonitor), [taskGraphLiveMonitor]);
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
              assistantName="助手"
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
          <ChatSearchPolicyControls
            onToggleSearchPolicy={toggleSearchPolicySource}
            searchPolicy={searchPolicy}
          />
        </div>
        <ChatInput
          disabled={workspaceInitializing}
          streaming={currentSessionStreaming}
          activeTaskControl={activeTaskControl}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          onPauseTask={pauseActiveTaskRun}
          onResumeTask={resumeActiveTaskRun}
          onStopTask={stopActiveTaskRun}
          mainAgentAssemblyMode={mainAgentAssemblyMode}
          modelProviderConfig={modelProviderConfig}
          soulImageAssetConfig={soulImageAssetConfig}
          onSelectMainAgentAssemblyMode={setMainAgentAssemblyMode}
          onSelectChatModel={setSelectedChatModel}
          selectedChatModelId={selectedChatModelId}
          deepSeekThinkingEnabled={deepSeekThinkingEnabled}
          onToggleDeepSeekThinking={setDeepSeekThinkingEnabled}
          taskSelection={taskSelection?.mode === "task_graph" ? null : taskSelection}
        />
      </div>
    </section>
  );
}

function deriveActiveTaskControl(monitor: Record<string, unknown> | null) {
  if (!monitor) {
    return null;
  }
  const taskRun = monitor.task_run && typeof monitor.task_run === "object" && !Array.isArray(monitor.task_run)
    ? monitor.task_run as Record<string, unknown>
    : {};
  const taskRunId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
  if (!taskRunId) {
    return null;
  }
  const executionRuntimeKind = String(monitor.execution_runtime_kind ?? taskRun.execution_runtime_kind ?? "").trim();
  if (executionRuntimeKind !== "single_agent_task") {
    return null;
  }
  const route = monitor.route && typeof monitor.route === "object" && !Array.isArray(monitor.route)
    ? monitor.route as Record<string, unknown>
    : {};
  if (String(route.kind ?? "").trim() === "task_graph_run") {
    return null;
  }
  const diagnostics = taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
    ? taskRun.diagnostics as Record<string, unknown>
    : {};
  if (String(diagnostics.origin_kind ?? "").trim() === "graph_node_assigned") {
    return null;
  }
  const status = String(monitor.status ?? taskRun.status ?? "").trim();
  const control = monitor.runtime_control && typeof monitor.runtime_control === "object" && !Array.isArray(monitor.runtime_control)
    ? monitor.runtime_control as Record<string, unknown>
    : Object.keys(diagnostics).length
      ? (diagnostics.runtime_control as Record<string, unknown> | undefined) ?? {}
      : {};
  const controlState = String(monitor.control_state ?? control.state ?? "").trim();
  if (["completed", "failed", "aborted"].includes(status)) {
    return null;
  }
  const canResume = status === "waiting_executor" && ["paused", "resume_requested", ""].includes(controlState);
  const canPause = ["created", "running"].includes(status) || controlState === "pause_requested";
  const canStop = ["created", "running", "waiting_executor", "waiting_approval", "blocked"].includes(status);
  return {
    taskRunId,
    status,
    controlState,
    canPause,
    canResume,
    canStop,
  };
}
