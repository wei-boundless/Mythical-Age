"use client";

import { MessageSquare, MessagesSquare, Network, Workflow } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { CoordinationRunPanel, hasCoordinationSignal } from "@/components/chat/CoordinationRunPanel";
import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { useAppStore } from "@/lib/store";

type ChatPage = "conversation" | "monitor";
type MonitorMode = "flow" | "communication";

function tokenMetricLabel(tokenStats: {
  total_tokens: number;
} | null) {
  if (!tokenStats) {
    return "No metrics yet";
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
  const [monitorMode, setMonitorMode] = useState<MonitorMode>("flow");
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
      setMonitorMode("flow");
    }
  }, [isStreaming, coordinationActive]);

  useEffect(() => {
    const justActivated = coordinationActive && !coordinationWasActiveRef.current;
    if (justActivated) {
      setActivePage("monitor");
      setMonitorMode("flow");
    }
    coordinationWasActiveRef.current = coordinationActive;
  }, [coordinationActive]);

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col gap-4">
      <div className="panel chat-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-[36px] p-5">
        <div className="chat-panel-head mb-4">
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
              <div className="chat-empty-state grid gap-6 rounded-[30px] p-8 xl:grid-cols-[280px_minmax(0,1fr)]">
                <div className="chat-empty-state__portrait flex items-center justify-center">
                  {activeSoul ? <SoulPortrait compact soul={activeSoul} /> : null}
                </div>
                <div className="chat-empty-state__copy flex flex-col justify-center">
                  <p className="chat-empty-state__eyebrow">Ready</p>
                  <h3 className="chat-empty-state__title mt-2">
                    {activeSoul ? `${activeSoul.name}，正等待您的询问。` : "正等待您的询问。"}
                  </h3>
                  <p className="chat-empty-state__text mt-3 max-w-2xl">
                    帷幕已启，直接写下你的问题即可。
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
              <div className="chat-monitor-stage__switch" aria-label="协调监控视图">
                <button
                  className={monitorMode === "flow" ? "chat-monitor-stage__switch-item chat-monitor-stage__switch-item--active" : "chat-monitor-stage__switch-item"}
                  onClick={() => setMonitorMode("flow")}
                  type="button"
                >
                  <Workflow size={16} />
                  流程
                </button>
                <button
                  className={monitorMode === "communication" ? "chat-monitor-stage__switch-item chat-monitor-stage__switch-item--active" : "chat-monitor-stage__switch-item"}
                  onClick={() => setMonitorMode("communication")}
                  type="button"
                >
                  <MessagesSquare size={16} />
                  通信
                </button>
              </div>
              <CoordinationRunPanel mode={monitorMode} snapshot={orchestrationSnapshot} />
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
