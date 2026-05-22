"use client";

import Image from "next/image";
import { useEffect, useMemo, useRef } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionActivityBar } from "@/components/chat/SessionActivityBar";
import { CHAT_VISUAL_MODE_LABELS, SOUL_CHAT_VISUAL_MODES, isSoulChatVisualMode, type ChatVisualMode } from "@/lib/chatVisualModes";
import { useAppStore } from "@/lib/store";

type ChatPanelProps = {
  visualMode?: ChatVisualMode;
  onVisualModeChange?: (mode: ChatVisualMode) => void;
};

export function ChatPanel({ visualMode = "default", onVisualModeChange }: ChatPanelProps) {
  const {
    messages,
    sendMessage,
    stopCurrentStream,
    resendEditedMessage,
    activeStreamSessionIds,
    sessionActivity,
    currentSessionId,
    activeSoulKey,
    soulOptions,
    modelProviderConfig,
    soulImageAssetConfig,
    selectedChatModelId,
    setSelectedChatModel,
    searchPolicy,
    toggleSearchPolicySource,
    taskSelection,
    setTaskSelection,
  } = useAppStore();
  const endRef = useRef<HTMLDivElement | null>(null);
  const currentSessionStreaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const visualSoulKey = isSoulChatVisualMode(visualMode) ? visualMode : activeSoulKey ?? "hebo";
  const visualSoul = soulOptions.find((soul) => soul.key === visualSoulKey) ?? soulOptions[0] ?? null;
  const visualModes: ChatVisualMode[] = ["hebo", ...SOUL_CHAT_VISUAL_MODES.filter((mode) => mode !== "hebo")];
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
          <span>主会话</span>
          {onVisualModeChange ? (
            <div className="chat-visual-switch" aria-label="主会话外观模式">
              {visualModes.map((mode) => (
                <button
                  className={visualMode === mode ? "chat-visual-switch__item chat-visual-switch__item--active" : "chat-visual-switch__item"}
                  key={mode}
                  onClick={() => onVisualModeChange(mode)}
                  type="button"
                >
                  {CHAT_VISUAL_MODE_LABELS[mode]}
                </button>
              ))}
            </div>
          ) : null}
        </header>

        <div className="chat-thread__messages flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {!messages.length ? (
            <div className={isSoulChatVisualMode(visualMode) ? "chat-thread__empty chat-thread__empty--soul" : "chat-thread__empty"}>
              {isSoulChatVisualMode(visualMode) && visualSoul ? (
                <Image alt={`${visualSoul.name}立绘`} height={288} src={visualSoul.portraitPath} unoptimized width={240} />
              ) : null}
              <div>
                <strong>{visualSoul ? `${visualSoul.name}，等待你的下一句话。` : "等待你的下一句话。"}</strong>
                <span>可以直接开始对话，也可以把任务交给当前会话。</span>
              </div>
            </div>
          ) : null}

          {messages.map((message) => (
            <ChatMessage
              assistantName={visualSoul?.name ?? "助手"}
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
        <SessionActivityBar activity={sessionActivity} active={currentSessionStreaming} />
        <ChatInput
          disabled={currentSessionStreaming}
          onSend={sendMessage}
          onStop={stopCurrentStream}
          onClearTaskSelection={() => setTaskSelection(null)}
          modelProviderConfig={modelProviderConfig}
          soulImageAssetConfig={soulImageAssetConfig}
          onToggleSearchPolicy={toggleSearchPolicySource}
          onSelectChatModel={setSelectedChatModel}
          searchPolicy={searchPolicy}
          selectedChatModelId={selectedChatModelId}
          taskSelection={taskSelection}
        />
      </div>
    </section>
  );
}
