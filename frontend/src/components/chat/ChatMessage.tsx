"use client";

import { Check, Copy, Pencil, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import {
  isPublicTimelineBodyItem,
  looksLikeRawToolOutput,
  publicTimelineBodyText,
} from "@/components/chat/agentRunProjection";
import type { PublicChatTimelineItem, RetrievalResult, SessionRuntimeAttachment, SingleAgentTaskProjection, ToolCall } from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { isPublicTimelineControlItem, mergePublicTimelineItems, publicTimelineTerminalStateFromAnswer } from "@/lib/store/publicTimeline";
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
  const runtimePublicTimelineForMessage = taskProjections.length
    ? controlTimelineItems(runtimePublicTimelineDraft)
    : runtimePublicTimelineDraft;
  const basePublicTimelineItems = isUser
    ? []
    : mergedPublicTimelineItems(
      runtimeAttachments,
      runtimePublicTimelineForMessage,
      terminalState,
    );
  const hasBasePublicTimelineActivity = publicTimelineHasDisplayableActivity(basePublicTimelineItems, taskProjections);
  const hasFinalAnswerBoundary = Boolean(answerCanonicalState || answerPersistPolicy || answerChannel);
  const contentProjectedIntoTimeline = hasFinalAnswerBoundary && !streamingContent && !isUser && Boolean(baseDisplayContent.trim()) && hasBasePublicTimelineActivity;
  const publicTimelineItems = contentProjectedIntoTimeline
    ? mergePublicTimelineItems(
      withoutRedundantAssistantFinalBody(basePublicTimelineItems, baseDisplayContent),
      [assistantFinalSummaryTimelineItem(baseDisplayContent)],
      { terminalState },
    )
    : basePublicTimelineItems;
  const hasPublicTimelineActivity = publicTimelineHasDisplayableActivity(publicTimelineItems, taskProjections);
  const askUserQuestionContent = !isUser ? askUserQuestionFromPublicTimelineItems(publicTimelineItems) : "";
  const messageDisplayContent = isUser
    ? baseDisplayContent
    : contentProjectedIntoTimeline ? "" : baseDisplayContent || askUserQuestionContent;
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
      {!isUser && hasPublicTimelineActivity ? (
        <PublicTimelineActivity items={publicTimelineItems} taskProjections={taskProjections} />
      ) : null}
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
    attachment.task_projection
      ? []
      : Array.isArray(attachment.public_timeline) ? attachment.public_timeline : [],
  );
  return mergePublicTimelineItems(persisted, runtimePublicTimelineDraft, { terminalState });
}

function taskProjectionsFromRuntimeAttachments(attachments: SessionRuntimeAttachment[]): SingleAgentTaskProjection[] {
  return attachments.flatMap((attachment) =>
    attachment.task_projection ? [attachment.task_projection] : [],
  );
}

function controlTimelineItems(items: PublicChatTimelineItem[] | undefined) {
  return (items ?? []).filter(isPublicTimelineControlItem);
}

function askUserQuestionFromPublicTimelineItems(items: PublicChatTimelineItem[]) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (!isPublicTimelineControlItem(item)) {
      continue;
    }
    const title = normalizedAssistantComparisonText(item.title);
    const question = String(item.detail || item.text || "").trim();
    if (question && normalizedAssistantComparisonText(question) !== title) {
      return normalizeAskUserQuestionMarkdown(question);
    }
  }
  return "";
}

function normalizeAskUserQuestionMarkdown(value: string) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const withListBreaks = text.replace(/\s+(?=\d{1,2}\.\s+\S)/g, "\n");
  return withListBreaks.replace(/([^\n])\n(?=1\.\s+\S)/, "$1\n\n");
}

function assistantFinalSummaryTimelineItem(content: string): PublicChatTimelineItem {
  const text = content.trim();
  return {
    item_id: `assistant-final:${text.slice(0, 96)}`,
    kind: "final_summary",
    surface: "body",
    source_authority: "model",
    text,
    state: "done",
  };
}

function withoutRedundantAssistantFinalBody(items: PublicChatTimelineItem[], content: string) {
  return items.filter((item) => !isRedundantAssistantFinalBody(item, content));
}

function isRedundantAssistantFinalBody(item: PublicChatTimelineItem, content: string) {
  const kind = String(item.kind ?? "").trim();
  if (kind !== "final_summary" && kind !== "assistant_text") {
    return false;
  }
  if (!isPublicTimelineBodyItem(item)) {
    return false;
  }
  const itemText = normalizedAssistantComparisonText(publicTimelineBodyText(item));
  const contentText = normalizedAssistantComparisonText(content);
  if (!itemText || !contentText) {
    return false;
  }
  if (itemText === contentText) {
    return true;
  }
  const shortText = itemText.length <= contentText.length ? itemText : contentText;
  const longText = itemText.length <= contentText.length ? contentText : itemText;
  if (shortText.length < 80) {
    return false;
  }
  if (longText.includes(shortText)) {
    return true;
  }
  return commonPrefixLength(shortText, longText) / shortText.length >= 0.92;
}

function normalizedAssistantComparisonText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function commonPrefixLength(left: string, right: string) {
  const limit = Math.min(left.length, right.length);
  let index = 0;
  while (index < limit && left[index] === right[index]) {
    index += 1;
  }
  return index;
}

function assistantDisplayContent(
  content: string,
  metadata: Parameters<typeof shouldDisplayAssistantContent>[0],
) {
  const normalized = String(content || "").trim();
  if (!shouldDisplayAssistantContent(metadata)) {
    return "";
  }
  if (looksLikeRawToolOutput(normalized)) {
    return "";
  }
  return content;
}
