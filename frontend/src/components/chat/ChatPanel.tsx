"use client";

import { useEffect, useRef } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { useAppStore } from "@/lib/store";

function tokenMetricLabel(tokenStats: {
  total_tokens: number;
} | null) {
  if (!tokenStats) {
    return "No metrics yet";
  }
  return `${tokenStats.total_tokens} tokens`;
}

export function ChatPanel() {
  const { messages, sendMessage, isStreaming, tokenStats, soulOptions, activeSoulKey } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col gap-4">
      <div className="panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-[36px] p-5">
        <div className="chat-panel-head mb-4 flex items-center justify-end">
          <div className="metric-pill mono chat-panel-metric">
            {tokenMetricLabel(tokenStats)}
          </div>
        </div>
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
              toolCalls={message.toolCalls}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <ChatInput disabled={isStreaming} onSend={sendMessage} />
    </section>
  );
}
