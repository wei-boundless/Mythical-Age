"use client";

import { Check, Pencil, X } from "lucide-react";
import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { hasPublicRunActivity, PublicRunActivity } from "@/components/chat/PublicRunActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import type { RetrievalResult, SessionRuntimeAttachment, ToolCall } from "@/lib/api";
import type { RuntimeProgressEntry } from "@/lib/store/types";

export function ChatMessage({
  id,
  role,
  content,
  image,
  runtimeAttachments = [],
  answerChannel,
  answerSource,
  retrievals,
  canEdit = false,
  onResendEdit
}: {
  id: string;
  role: "user" | "assistant";
  content: string;
  image?: {
    src: string;
    alt?: string;
    caption?: string;
  } | null;
  stageStatus?: string;
  runtimeProgress?: RuntimeProgressEntry[];
  runtimeAttachments?: SessionRuntimeAttachment[];
  answerChannel?: string;
  answerSource?: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  canEdit?: boolean;
  onResendEdit?: (messageId: string, value: string) => Promise<void>;
}) {
  const isUser = role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);
  const [failedImageSrc, setFailedImageSrc] = useState("");
  const imageUnavailable = Boolean(image?.src && failedImageSrc === image.src);
  const displayContent = isUser ? content : assistantDisplayContent({ content, answerChannel, answerSource });
  const hasRunActivity = !isUser && hasPublicRunActivity(runtimeAttachments, displayContent);
  const taskControlReceipt = !isUser && isTaskControlReceipt({ content, answerChannel, answerSource });
  const hideTaskControlReceipt = taskControlReceipt && hasRunActivity;
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || (!hideTaskControlReceipt && (Boolean(displayContent.trim()) || !hasRunActivity));

  return (
    <article
      className={`message-shell chat-message-shell ${
        isUser
          ? "message-shell--user chat-message-shell--user"
          : "message-shell--assistant chat-message-shell--assistant"
      }`}
    >
      {isUser && canEdit ? (
        <button
          aria-label="编辑消息"
          className="message-edit-button"
          onClick={() => {
            setDraft(content);
            setEditing(true);
          }}
          title="编辑"
          type="button"
        >
          <Pencil size={13} />
        </button>
      ) : null}
      {!isUser && <RetrievalCard results={retrievals} />}
      {hasRunActivity ? (
        <PublicRunActivity attachments={runtimeAttachments} assistantContent={displayContent} />
      ) : null}
      {shouldRenderContent ? (
        <div className={isUser ? "chat-message-shell__content whitespace-pre-wrap leading-7" : "chat-message-shell__content markdown"}>
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
          ) : image?.src && !imageUnavailable ? (
            <figure className="chat-image-message">
              {/* Generated local assets are final files served from public/. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                alt={image.alt || "生成图像"}
                loading="lazy"
                onError={() => setFailedImageSrc(image.src)}
                src={image.src}
              />
              {image.caption ? <figcaption>{image.caption}</figcaption> : null}
            </figure>
          ) : imageUnavailable ? (
            <div className="chat-image-message chat-image-message--missing">
              <p>图像文件不可用。</p>
              <span>{image?.src}</span>
            </div>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {displayContent || "正在思考..."}
            </ReactMarkdown>
          )}
        </div>
      ) : null}
    </article>
  );
}

function assistantDisplayContent({
  content,
  answerChannel,
  answerSource,
}: {
  content: string;
  answerChannel?: string;
  answerSource?: string;
}) {
  const normalized = String(content || "").trim();
  const source = String(answerSource || "");
  const legacyToolLoop =
    source.includes("single_agent_turn.tool_loop")
    || normalized.includes("本轮工具观察次数已达到上限")
    || normalized.includes("连续检查了几次仍没有形成可靠结论");
  if (!legacyToolLoop) {
    return content;
  }
  if (String(answerChannel || "") === "blocked" || source.includes("tool_loop")) {
    return "我刚才连续检查了几次，但没有拿到足够的新信息。现在应该基于已有事实收口说明，或等你指定要重点核查的位置。";
  }
  return content;
}

function isTaskControlReceipt({
  content,
  answerChannel,
  answerSource,
}: {
  content: string;
  answerChannel?: string;
  answerSource?: string;
}) {
  const channel = String(answerChannel || "").trim();
  if (channel === "task_control") {
    return true;
  }
  const source = String(answerSource || "");
  if (source.includes("task_lifecycle") || source.includes("explicit_contract_task")) {
    return true;
  }
  const normalized = String(content || "").trim();
  return (
    normalized.startsWith("我会按这个目标推进")
    || normalized.startsWith("我会按这个合同继续推进")
    || normalized.startsWith("后续进展会汇总在当前会话")
  );
}
