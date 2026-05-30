"use client";

import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { RuntimeEvidencePanel } from "@/components/chat/RuntimeEvidencePanel";
import { RuntimeRunSummary } from "@/components/chat/RuntimeRunSummary";
import type { RetrievalResult, SessionRuntimeAttachment, ToolCall } from "@/lib/api";
import type { RuntimeProgressEntry } from "@/lib/store/types";

export function ChatMessage({
  id,
  role,
  content,
  image,
  stageStatus,
  runtimeProgress = [],
  runtimeAttachments = [],
  toolCalls,
  retrievals,
  assistantName = "河伯",
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
  const [failedImageSrc, setFailedImageSrc] = useState("");
  const imageUnavailable = Boolean(image?.src && failedImageSrc === image.src);

  return (
    <article
      className={`message-shell chat-message-shell ${
        isUser
          ? "message-shell--user chat-message-shell--user"
          : "message-shell--assistant chat-message-shell--assistant"
      }`}
    >
      <div className="chat-message-shell__head">
        <div className="chat-message-shell__identity">
          <div className={`message-emblem ${isUser ? "message-emblem--user" : ""}`}>
            {isUser ? "你" : assistantMark}
          </div>
          <p className="chat-message-shell__label">
            {isUser ? "用户" : assistantName}
          </p>
        </div>
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
      </div>
      {!isUser && <RetrievalCard results={retrievals} />}
      {!isUser && (runtimeAttachments.length || runtimeProgress.length) ? (
        <RuntimeRunSummary attachments={runtimeAttachments} entries={runtimeProgress} />
      ) : null}
      {!isUser && <RuntimeEvidencePanel toolCalls={toolCalls} />}
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
            {content || (runtimeProgress.length ? "" : "正在思考...")}
          </ReactMarkdown>
        )}
      </div>
    </article>
  );
}
