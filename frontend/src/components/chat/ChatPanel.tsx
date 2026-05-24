"use client";

import { useEffect, useMemo, useRef } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
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
    taskOrderProjection,
    taskOrderProjectionConsumed,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
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
              runtimeProgress={message.runtimeProgress}
              stageStatus={message.stageStatus}
              toolCalls={message.toolCalls}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-panel-footer min-w-0">
        <SessionActivityBar activity={sessionActivity} active={currentSessionStreaming} />
        <ChatInput
          disabled={workspaceInitializing || currentSessionStreaming}
          streaming={currentSessionStreaming}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          mainAgentAssemblyMode={mainAgentAssemblyMode}
          modelProviderConfig={modelProviderConfig}
          soulImageAssetConfig={soulImageAssetConfig}
          onSelectMainAgentAssemblyMode={setMainAgentAssemblyMode}
          onToggleSearchPolicy={toggleSearchPolicySource}
          onSelectChatModel={setSelectedChatModel}
          searchPolicy={searchPolicy}
          selectedChatModelId={selectedChatModelId}
          deepSeekThinkingEnabled={deepSeekThinkingEnabled}
          onToggleDeepSeekThinking={setDeepSeekThinkingEnabled}
          taskSelection={taskSelection?.mode === "coordination" ? null : taskSelection}
          taskOrderProjection={taskOrderProjectionConsumed ? null : taskOrderProjection}
        />
      </div>
    </section>
  );
}
