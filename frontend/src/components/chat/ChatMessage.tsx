"use client";

import { Check, Copy, Pencil, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { looksLikeRawToolOutput } from "@/components/chat/agentRunProjection";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { PublicChatTimelineItem, RetrievalResult, SessionRuntimeAttachment, SingleAgentTaskProjection, ToolCall } from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { mergePublicTimelineItems, publicTimelineTerminalStateFromAnswer } from "@/lib/projection/timeline";
import type { RuntimeProgressEntry } from "@/lib/store/types";
import { useNaturalizedStreamText } from "./useNaturalizedStreamText";

export function ChatMessage({
  id,
  role,
  content,
  image,
  runtimeAttachments = [],
  runtimePublicTimelineDraft,
  answerChannel,
  answerCanonicalState,
  answerPersistPolicy,
  answerSource,
  answerLeakFlags,
  streamingContent = false,
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
  runtimePublicTimelineDraft?: PublicChatTimelineItem[];
  answerChannel?: string;
  answerCanonicalState?: string;
  answerPersistPolicy?: string;
  answerFinalizationPolicy?: string;
  answerFallbackReason?: string;
  answerSelectedChannel?: string;
  answerSelectedSource?: string;
  answerLeakFlags?: string[];
  answerSource?: string;
  streamingContent?: boolean;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  canEdit?: boolean;
  onResendEdit?: (messageId: string, value: string) => Promise<void>;
}) {
  const isUser = role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);
  const [submittingEdit, setSubmittingEdit] = useState(false);
  const [editError, setEditError] = useState("");
  const [copiedReply, setCopiedReply] = useState(false);
  const [failedImageSrc, setFailedImageSrc] = useState("");
  const imageUnavailable = Boolean(image?.src && failedImageSrc === image.src);
  const baseDisplayContent = isUser
    ? content
    : assistantDisplayContent(content, {
      answerChannel,
      answerCanonicalState,
      answerPersistPolicy,
      answerSource,
      answerLeakFlags,
    });
  const terminalState = publicTimelineTerminalStateFromAnswer({ answerCanonicalState, answerChannel });
  const taskProjections = isUser
    ? []
    : taskProjectionsFromRuntimeAttachments(runtimeAttachments);
  const basePublicTimelineItems = isUser
    ? []
    : mergedPublicTimelineItems(
      runtimeAttachments,
      runtimePublicTimelineDraft,
      terminalState,
    );
  const publicTimelineItems = basePublicTimelineItems;
  const hasPublicTimelineActivity = publicTimelineHasDisplayableActivity(publicTimelineItems, taskProjections);
  const messageDisplayContent = isUser
    ? baseDisplayContent
    : baseDisplayContent;
  const naturalizedMessageDisplayContent = useNaturalizedStreamText(
    messageDisplayContent,
    !isUser && streamingContent && Boolean(messageDisplayContent),
  );
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || Boolean(naturalizedMessageDisplayContent.trim());
  const copyableReplyText = !isUser && shouldRenderContent ? naturalizedMessageDisplayContent.trim() : "";
  const draftValue = draft.trim();
  const sendEditDisabled = submittingEdit || !canEdit || !draftValue;
  const submitEdit = async () => {
    if (sendEditDisabled) {
      return;
    }
    if (!onResendEdit) {
      setEditError("当前消息没有可用的改写发送处理器。");
      return;
    }
    setSubmittingEdit(true);
    setEditError("");
    try {
      await onResendEdit(id, draftValue);
      setEditing(false);
    } catch (error) {
      setEditError(editFailureMessage(error));
    } finally {
      setSubmittingEdit(false);
    }
  };
  useEffect(() => {
    if (!canEdit && editing) {
      setEditing(false);
      setEditError("");
      setSubmittingEdit(false);
    }
  }, [canEdit, editing]);
  const copyReply = async () => {
    if (!copyableReplyText) {
      return;
    }
    await writeClipboardText(copyableReplyText);
    setCopiedReply(true);
    window.setTimeout(() => setCopiedReply(false), 1200);
  };

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
            setEditError("");
            setSubmittingEdit(false);
            setEditing(true);
          }}
          title="编辑"
          type="button"
        >
          <Pencil size={13} />
        </button>
      ) : null}
      {!isUser && <RetrievalCard results={retrievals} />}
      {shouldRenderContent ? (
        <div className={isUser ? "chat-message-shell__content whitespace-pre-wrap leading-7" : "chat-message-shell__content markdown"}>
          {!isUser && copyableReplyText ? (
            <button
              aria-label={copiedReply ? "已复制回复" : "复制回复"}
              className="message-copy-button"
              onClick={() => void copyReply()}
              title={copiedReply ? "已复制" : "复制回复"}
              type="button"
            >
              {copiedReply ? <Check size={13} /> : <Copy size={13} />}
            </button>
          ) : null}
          {isUser && editing ? (
            <div className="message-edit-form">
              <textarea
                className="message-edit-form__textarea"
                onChange={(event) => {
                  setDraft(event.target.value);
                  setEditError("");
                }}
                value={draft}
              />
              {editError ? (
                <small className="message-edit-form__error" role="alert">
                  {editError}
                </small>
              ) : null}
              <div className="message-edit-form__actions">
                <button
                  className="message-edit-form__button"
                  disabled={submittingEdit}
                  onClick={() => {
                    setEditError("");
                    setEditing(false);
                  }}
                  type="button"
                >
                  <X size={14} />
                  取消
                </button>
                <button
                  className="message-edit-form__button message-edit-form__button--primary"
                  disabled={sendEditDisabled}
                  onClick={() => void submitEdit()}
                  type="button"
                >
                  <Check size={14} />
                  {submittingEdit ? "发送中" : "发送"}
                </button>
              </div>
            </div>
          ) : isUser ? (
            content
          ) : image?.src && !imageUnavailable ? (
            <figure className="chat-image-message">
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
              {naturalizedMessageDisplayContent}
            </ReactMarkdown>
          )}
        </div>
      ) : null}
      {!isUser && hasPublicTimelineActivity ? (
        <PublicTimelineActivity items={publicTimelineItems} taskProjections={taskProjections} />
      ) : null}
    </article>
  );
}

function editFailureMessage(error: unknown) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || "改写没有发送成功。";
}

async function writeClipboardText(text: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function mergedPublicTimelineItems(
  attachments: SessionRuntimeAttachment[],
  runtimePublicTimelineDraft: PublicChatTimelineItem[] | undefined,
  terminalState: ReturnType<typeof publicTimelineTerminalStateFromAnswer> = "",
) {
  const persisted = attachments.flatMap((attachment) =>
    Array.isArray(attachment.public_timeline)
      ? attachment.public_timeline
      : [],
  );
  return mergePublicTimelineItems(persisted, runtimePublicTimelineDraft, { terminalState });
}

function taskProjectionsFromRuntimeAttachments(attachments: SessionRuntimeAttachment[]): SingleAgentTaskProjection[] {
  return attachments.flatMap((attachment) =>
    attachment.task_projection ? [attachment.task_projection] : [],
  );
}

function assistantDisplayContent(
  content: string,
  metadata: Parameters<typeof shouldDisplayAssistantContent>[0],
) {
  const normalized = String(content || "").trim();
  if (!shouldDisplayAssistantContent(metadata)) {
    return "";
  }
  if (isInternalControlProtocolText(normalized)) {
    return "";
  }
  if (looksLikeRawToolOutput(normalized)) {
    return "";
  }
  return content;
}
