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
import { cleanPublicTimelineText, mergePublicTimelineItems, publicTimelineTerminalStateFromAnswer } from "@/lib/projection/timeline";
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
  const publicTimelineItemsWithoutRedundantBody = !isUser && baseDisplayContent.trim()
    ? withoutRedundantAssistantFinalBody(basePublicTimelineItems, baseDisplayContent)
    : basePublicTimelineItems;
  const timelineBodyContent = !isUser
    ? assistantBodyFromPublicTimelineItems(publicTimelineItemsWithoutRedundantBody)
    : "";
  const resolvedDisplayContent = combineAssistantDisplayContent(baseDisplayContent, timelineBodyContent);
  const publicTimelineItems = !isUser
    ? withoutAssistantBodyItems(publicTimelineItemsWithoutRedundantBody)
    : basePublicTimelineItems;
  const hasPublicTimelineActivity = publicTimelineHasDisplayableActivity(publicTimelineItems, taskProjections);
  const messageDisplayContent = isUser
    ? baseDisplayContent
    : resolvedDisplayContent;
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

function withoutRedundantAssistantFinalBody(items: PublicChatTimelineItem[], content: string) {
  return items.filter((item) => !isRedundantAssistantFinalBody(item, content));
}

function withoutAssistantBodyItems(items: PublicChatTimelineItem[]) {
  return items.filter((item) => !isStrictAssistantBodyItem(item));
}

function combineAssistantDisplayContent(baseContent: string, timelineBodyContent: string) {
  const base = String(baseContent || "");
  const timeline = String(timelineBodyContent || "").trim();
  if (!timeline) return base;
  if (!base.trim()) return timelineBodyContent;
  const baseTrimmed = base.trim();
  if (isRedundantAssistantText(timeline, base)) {
    return normalizedAssistantComparisonText(timeline).length > normalizedAssistantComparisonText(base).length
      ? timelineBodyContent
      : base;
  }
  if (normalizedAssistantComparisonText(timeline).startsWith(normalizedAssistantComparisonText(baseTrimmed))) {
    return timelineBodyContent;
  }
  if (normalizedAssistantComparisonText(baseTrimmed).startsWith(normalizedAssistantComparisonText(timeline))) {
    return base;
  }
  return `${timelineBodyContent.trimEnd()}\n\n${baseTrimmed}`;
}

function assistantBodyFromPublicTimelineItems(items: PublicChatTimelineItem[]) {
  const bodyLines = items
    .filter((item) => isStrictAssistantBodyItem(item))
    .map((item) => strictAssistantBodyText(item))
    .map((text) => String(text || "").trim())
    .filter((text) => text && !looksLikeRawToolOutput(text));
  return dedupeConsecutiveBodyLines(bodyLines).join("\n\n");
}

function dedupeConsecutiveBodyLines(lines: string[]) {
  const result: string[] = [];
  for (const line of lines) {
    const previous = result[result.length - 1] ?? "";
    if (isRedundantAssistantText(line, previous)) {
      continue;
    }
    result.push(line);
  }
  return result;
}

function isRedundantAssistantFinalBody(item: PublicChatTimelineItem, content: string) {
  const kind = String(item.kind ?? "").trim();
  if (!["assistant_text", "final_answer", "final_summary", "model_body_final", "observation_report"].includes(kind)) {
    return false;
  }
  if (!isStrictAssistantBodyItem(item)) {
    return false;
  }
  return isRedundantAssistantText(strictAssistantBodyText(item), content);
}

function isStrictAssistantBodyItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText(item.slot).toLowerCase();
  const surface = cleanPublicTimelineText(item.surface).toLowerCase();
  const authority = cleanPublicTimelineText(item.source_authority).toLowerCase();
  return slot === "body" && surface === "assistant_body" && authority === "model";
}

function strictAssistantBodyText(item: PublicChatTimelineItem | null | undefined) {
  if (!isStrictAssistantBodyItem(item)) return "";
  for (const candidate of [item?.text, item?.detail, item?.observation, item?.public_summary, item?.implication]) {
    const text = cleanAssistantBodyText(candidate);
    if (text && !looksLikeRawToolOutput(text)) return text;
  }
  return "";
}

function cleanAssistantBodyText(value: unknown) {
  return String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/g, ""))
    .join("\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isRedundantAssistantText(candidate: unknown, content: string) {
  const candidateText = normalizedAssistantComparisonText(candidate);
  const contentText = normalizedAssistantComparisonText(content);
  if (!candidateText || !contentText) {
    return false;
  }
  if (candidateText === contentText) {
    return true;
  }
  const shortText = candidateText.length <= contentText.length ? candidateText : contentText;
  const longText = candidateText.length <= contentText.length ? contentText : candidateText;
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
  if (isInternalControlProtocolText(normalized)) {
    return "";
  }
  if (looksLikeRawToolOutput(normalized)) {
    return "";
  }
  return content;
}
