"use client";

import { useEffect, useMemo, useRef } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { useAppStore } from "@/lib/store";

export function ChatPanel() {
  const {
    messages,
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    activeStreamSessionIds,
    currentSessionId,
    searchPolicy,
    toggleSearchPolicySource,
    taskSelection,
    setTaskSelection,
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
        <header className="chat-thread__head">
          <span>对话</span>
        </header>

        <div className="chat-thread__messages flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {!messages.length && <p className="chat-thread__empty">暂无聊天</p>}

          {messages.map((message) => (
            <ChatMessage
              assistantName="助手"
              canEdit={!currentSessionStreaming && message.id === lastEditableUserMessageId}
              content={message.content}
              id={message.id}
              key={message.id}
              onResendEdit={resendEditedMessage}
              retrievals={message.retrievals}
              role={message.role}
              stageStatus={message.stageStatus}
              toolCalls={message.toolCalls}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-panel-footer min-w-0">
        <ChatInput
          disabled={currentSessionStreaming}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          onClearTaskSelection={() => setTaskSelection(null)}
          onToggleSearchPolicy={toggleSearchPolicySource}
          searchPolicy={searchPolicy}
          taskSelection={taskSelection}
        />
      </div>
    </section>
  );
}
