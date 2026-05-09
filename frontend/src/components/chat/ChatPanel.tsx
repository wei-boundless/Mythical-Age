"use client";

import { MessageSquare, Network } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { CoordinationRunPanel, hasCoordinationSignal } from "@/components/chat/CoordinationRunPanel";
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
    isStreaming,
    tokenStats,
    orchestrationSnapshot,
    soulOptions,
    activeSoulKey,
    searchPolicy,
    toggleSearchPolicySource,
    taskSelection,
    setTaskSelection,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const coordinationWasActiveRef = useRef(false);
  const [activePage, setActivePage] = useState<ChatPage>("conversation");
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;
  const coordinationActive = hasCoordinationSignal(orchestrationSnapshot);

  useEffect(() => {
    if (activePage === "conversation") {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, activePage]);

  useEffect(() => {
    if (isStreaming && coordinationActive) {
      setActivePage("monitor");
    }
  }, [isStreaming, coordinationActive]);

  useEffect(() => {
    const justActivated = coordinationActive && !coordinationWasActiveRef.current;
    if (justActivated) {
      setActivePage("monitor");
    }
    coordinationWasActiveRef.current = coordinationActive;
  }, [coordinationActive]);

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
              协调监控
              {coordinationActive ? <span className="chat-page-tabs__signal" /> : null}
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
                    直接输入问题、任务或协调指令即可开始。
                  </p>
                </div>
              </div>
            )}

            {messages.map((message) => (
              <ChatMessage
                assistantName={activeSoul?.name ?? "河伯"}
                content={message.content}
                key={message.id}
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
              <CoordinationRunPanel snapshot={orchestrationSnapshot} />
            </div>
          </div>
        )}
      </div>

      <ChatInput
        disabled={isStreaming}
        onSend={sendMessage}
        onClearTaskSelection={() => setTaskSelection(null)}
        onToggleSearchPolicy={toggleSearchPolicySource}
        searchPolicy={searchPolicy}
        taskSelection={taskSelection}
      />
    </section>
  );
}
