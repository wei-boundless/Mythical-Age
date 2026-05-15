"use client";

import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { ThoughtChain } from "@/components/chat/ThoughtChain";
import type { RetrievalResult, ToolCall } from "@/lib/api";

export function ChatMessage({
  id,
  role,
  content,
  stageStatus,
  toolCalls,
  retrievals,
  assistantName = "河伯",
  canEdit = false,
  onResendEdit
}: {
  id: string;
  role: "user" | "assistant";
  content: string;
  stageStatus?: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  assistantName?: string;
  canEdit?: boolean;
  onResendEdit?: (messageId: string, value: string) => Promise<void>;
}) {
  const isUser = role === "user";
  const assistantMark = assistantName.slice(0, 1) || "灵";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);

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
        {isUser && canEdit ? (
          <button
            className="message-edit-button"
            onClick={() => {
              setDraft(content);
              setEditing(true);
            }}
            type="button"
          >
            <Pencil size={14} />
            编辑
          </button>
        ) : null}
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
        {isUser && editing ? (
          <div className="message-edit-form">
            <textarea
              className="message-edit-form__textarea"
              onChange={(event) => setDraft(event.target.value)}
              value={draft}
            />
            <div className="message-edit-form__actions">
              <button
                className="message-edit-form__button"
                onClick={() => setEditing(false)}
                type="button"
              >
                <X size={14} />
                取消
              </button>
              <button
                className="message-edit-form__button message-edit-form__button--primary"
                disabled={!draft.trim() || draft.trim() === content.trim()}
                onClick={() => {
                  const nextValue = draft.trim();
                  if (!nextValue || !onResendEdit) {
                    return;
                  }
                  setEditing(false);
                  void onResendEdit(id, nextValue);
                }}
                type="button"
              >
                <Check size={14} />
                发送
              </button>
            </div>
          </div>
        ) : isUser ? (
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
