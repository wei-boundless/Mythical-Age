"use client";

import { MessageSquare, Network } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { TaskGraphRunMonitorPanel } from "@/components/task-graph-monitor/TaskGraphRunMonitorPanel";
import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { useAppStore } from "@/lib/store";

type ChatPage = "conversation" | "monitor";

function tokenMetricLabel(tokenStats: {
  total_tokens: number;
} | null) {
  if (!tokenStats) {
    return "暂无指标";
  }
  return `${tokenStats.total_tokens} tokens`;
}

export function ChatPanel() {
  const {
    messages,
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    activeStreamSessionIds,
    currentSessionId,
    tokenStats,
    taskGraphLiveMonitor,
    taskGraphRunMonitor,
    soulOptions,
    activeSoulKey,
    searchPolicy,
    toggleSearchPolicySource,
    taskSelection,
    setTaskSelection,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const [activePage, setActivePage] = useState<ChatPage>("conversation");
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const taskGraphActive = Boolean(taskSelection?.mode === "coordination" || taskGraphRunMonitor || taskGraphLiveMonitor?.has_coordination);
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
    if (activePage === "conversation") {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, activePage]);

  useEffect(() => {
    if (taskSelection?.mode === "coordination") {
      setActivePage("monitor");
      return;
    }
    if (!taskSelection && !taskGraphActive) {
      setActivePage("conversation");
    }
  }, [taskGraphActive, taskSelection]);

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col gap-4">
      <div className="panel chat-panel chat-panel--workbench flex min-h-0 flex-1 flex-col overflow-hidden rounded-[18px] p-3">
        <div className="chat-panel-head mb-3">
          <div className="chat-page-tabs" aria-label="主会话页面">
            <button
              className={activePage === "conversation" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
              onClick={() => setActivePage("conversation")}
              type="button"
            >
              <MessageSquare size={16} />
              会话
            </button>
            <button
              className={activePage === "monitor" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
              onClick={() => setActivePage("monitor")}
              type="button"
            >
              <Network size={16} />
              任务图监控
              {taskGraphActive ? <span className="chat-page-tabs__signal" /> : null}
            </button>
          </div>
          <div className="metric-pill mono chat-panel-metric">
            {tokenMetricLabel(tokenStats)}
          </div>
        </div>

        {activePage === "conversation" ? (
          <div className="flex-1 space-y-4 overflow-y-auto pr-2">
            {!messages.length && (
              <div className="chat-empty-state chat-empty-state--full grid gap-4 rounded-[16px] p-4 xl:grid-cols-[164px_minmax(0,1fr)]">
                <div className="chat-empty-state__portrait flex items-center justify-center">
                  {activeSoul ? <SoulPortrait compact soul={activeSoul} /> : null}
                </div>
                <div className="chat-empty-state__copy flex flex-col justify-center">
                  <p className="chat-empty-state__eyebrow">会话</p>
                  <h3 className="chat-empty-state__title mt-2">
                    {activeSoul ? `${activeSoul.name}，正等待您的询问。` : "正等待您的询问。"}
                  </h3>
                  <p className="chat-empty-state__text mt-3 max-w-2xl">
                    直接输入问题、任务或协调任务指令即可开始。
                  </p>
                </div>
              </div>
            )}

            {messages.map((message) => (
              <ChatMessage
                assistantName={activeSoul?.name ?? "河伯"}
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
        ) : (
          <div className="chat-run-page">
            <div className="chat-monitor-stage">
              <TaskGraphRunMonitorPanel monitor={taskGraphRunMonitor} />
            </div>
          </div>
        )}
      </div>

      <ChatInput
        disabled={currentSessionStreaming}
        onSend={sendMessage}
        onStop={stopCurrentStream}
        onClearTaskSelection={() => setTaskSelection(null)}
        onToggleSearchPolicy={toggleSearchPolicySource}
        searchPolicy={searchPolicy}
        taskSelection={taskSelection}
    />
  </section>
);
}
