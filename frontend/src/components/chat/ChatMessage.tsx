"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { ThoughtChain } from "@/components/chat/ThoughtChain";
import type { RetrievalResult, ToolCall } from "@/lib/api";

export function ChatMessage({
  role,
  content,
  stageStatus,
  toolCalls,
  retrievals,
  assistantName = "河伯"
}: {
  role: "user" | "assistant";
  content: string;
  stageStatus?: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  assistantName?: string;
}) {
  const isUser = role === "user";
  const assistantMark = assistantName.slice(0, 1) || "灵";

  return (
    <article
      className={`message-shell archive-message-shell max-w-[94%] rounded-[30px] px-5 py-4 ${
        isUser
          ? "message-shell--user ml-auto text-white"
          : "message-shell--assistant mr-auto text-[var(--color-text)]"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={`message-emblem ${isUser ? "message-emblem--user" : ""}`}>
            {isUser ? "你" : assistantMark}
          </div>
          <div>
            <p className="archive-message-shell__label text-sm font-medium">
              {isUser ? "用户" : assistantName}
            </p>
            <p className="archive-message-shell__eyebrow text-xs uppercase tracking-[0.24em] text-[var(--color-text-soft)]">
              {isUser ? "User" : "Current Style"}
            </p>
          </div>
        </div>
      </div>
      {!isUser && stageStatus ? (
        <div className="message-stage-status mb-4" aria-label={`当前阶段：${stageStatus}`}>
          <span className="message-stage-status__dot" />
          <span>阶段：{stageStatus}</span>
        </div>
      ) : null}
      {!isUser && <RetrievalCard results={retrievals} />}
      {!isUser && <ThoughtChain toolCalls={toolCalls} />}
      <div className={isUser ? "whitespace-pre-wrap leading-7" : "markdown"}>
        {isUser ? (
          content
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content || "正在思考..."}
          </ReactMarkdown>
        )}
      </div>
    </article>
  );
}
