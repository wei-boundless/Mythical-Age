"use client";

import { Check, Copy, Pencil, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { PublicChatTimelineItem, RetrievalResult, SessionRuntimeAttachment, SingleAgentTaskProjection, ToolCall } from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { cleanPublicTimelineText, isPublicTimelineStatusBarItem, mergePublicTimelineItems, publicTimelineTerminalStateFromAnswer } from "@/lib/projection/timeline";
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
  const taskProjections = isUser
    ? []
    : taskProjectionsFromRuntimeAttachments(runtimeAttachments);
  const messageDisplayContent = baseDisplayContent;
  const answerTerminalState = !isUser && messageDisplayContent.trim()
    ? publicTimelineTerminalStateFromAnswer({ answerCanonicalState, answerChannel })
    : "";
  const terminalState = combinedPublicTimelineTerminalState(
    answerTerminalState,
    runtimeAttachments,
    runtimePublicTimelineDraft,
  );
  const basePublicTimelineItems = isUser
    ? []
    : mergedPublicTimelineItems(
      runtimeAttachments,
      runtimePublicTimelineDraft,
      terminalState,
    );
  const publicTimelineItems = isUser
    ? []
    : terminalScopedPublicTimelineItems(
      basePublicTimelineItems,
      runtimeAttachments,
      terminalState,
      {
        hasDisplayContent: Boolean(messageDisplayContent.trim()),
        streamingContent,
      },
    );
  const compactCompletedTools = Boolean(messageDisplayContent.trim()) || Boolean(terminalState);
  const suppressPublicTimelineActivity = shouldSuppressPublicTimelineAfterFinalAnswer({
    displayContent: messageDisplayContent,
    hasActiveTaskProjection: hasActiveTaskProjection(taskProjections),
    isUser,
    streamingContent,
    terminalState,
  });
  const hasPublicTimelineActivity = !suppressPublicTimelineActivity
    && publicTimelineHasDisplayableActivity(publicTimelineItems, taskProjections, { compactCompletedTools });
  const naturalizedMessageDisplayContent = useNaturalizedStreamText(
    messageDisplayContent,
    !isUser && streamingContent && Boolean(messageDisplayContent),
  );
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || Boolean(naturalizedMessageDisplayContent.trim());
  const showThinkingPlaceholder =
    !isUser
    && streamingContent
    && !shouldRenderContent
    && !hasPublicTimelineActivity;
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
      {showThinkingPlaceholder ? (
        <div className="chat-message-shell__thinking-placeholder" aria-live="polite">
          <span>正在思考</span>
        </div>
      ) : null}
      {!isUser && hasPublicTimelineActivity ? (
        <PublicTimelineActivity
          compactCompletedTools={compactCompletedTools}
          items={publicTimelineItems}
          taskProjections={taskProjections}
        />
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

function terminalScopedPublicTimelineItems(
  items: PublicChatTimelineItem[],
  attachments: SessionRuntimeAttachment[],
  terminalState: ReturnType<typeof publicTimelineTerminalStateFromAnswer>,
  options: { hasDisplayContent: boolean; streamingContent: boolean },
) {
  if (!terminalState || options.streamingContent) {
    return items;
  }
  if (options.hasDisplayContent) {
    return [];
  }
  const statusItems = items.filter(isPublicTimelineStatusBarItem);
  if (statusItems.length) {
    return statusItems;
  }
  const controlStatus = items.find(isTerminalControlStatusItem);
  if (controlStatus) {
    return [asTerminalStatusItem(controlStatus, terminalState)];
  }
  return [];
}

function isTerminalControlStatusItem(item: PublicChatTimelineItem) {
  const kind = cleanPublicTimelineText(item.kind).toLowerCase();
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  return slot === "control"
    && ["error_notice", "control_state", "status_update"].includes(kind)
    && ["error", "failed", "blocked", "missing", "stopped"].includes(state);
}

function asTerminalStatusItem(
  item: PublicChatTimelineItem,
  terminalState: ReturnType<typeof publicTimelineTerminalStateFromAnswer>,
): PublicChatTimelineItem {
  const state = terminalState === "stopped" ? "stopped" : terminalState === "done" ? "done" : "error";
  return {
    ...item,
    item_id: cleanPublicTimelineText(item.item_id) || `terminal:${state}`,
    kind: "status_update",
    slot: "status",
    surface: "status_bar",
    state,
    phase: "done",
    stream_state: "done",
  };
}

function shouldSuppressPublicTimelineAfterFinalAnswer({
  displayContent,
  hasActiveTaskProjection,
  isUser,
  streamingContent,
  terminalState,
}: {
  displayContent: string;
  hasActiveTaskProjection: boolean;
  isUser: boolean;
  streamingContent: boolean;
  terminalState: ReturnType<typeof publicTimelineTerminalStateFromAnswer>;
}) {
  if (hasActiveTaskProjection) {
    return false;
  }
  return !isUser
    && !streamingContent
    && ["done", "error", "stopped"].includes(terminalState)
    && Boolean(displayContent.trim());
}

function hasActiveTaskProjection(taskProjections: SingleAgentTaskProjection[]) {
  return taskProjections.some((projection) => isNonCloseoutRuntimeState(compactTerminalValue(projection.status)));
}

function combinedPublicTimelineTerminalState(
  answerState: ReturnType<typeof publicTimelineTerminalStateFromAnswer>,
  attachments: SessionRuntimeAttachment[],
  timelineDraft: PublicChatTimelineItem[] | undefined,
): ReturnType<typeof publicTimelineTerminalStateFromAnswer> {
  return answerState || runtimeAttachmentsTerminalState(attachments) || publicTimelineDraftTerminalState(timelineDraft);
}

function runtimeAttachmentsTerminalState(
  attachments: SessionRuntimeAttachment[],
): ReturnType<typeof publicTimelineTerminalStateFromAnswer> {
  let hasDone = false;
  for (const attachment of attachments) {
    const state = compactTerminalValue(attachment.status || attachment.lifecycle);
    const reason = compactTerminalValue(attachment.terminal_reason);
    const projectionState = compactTerminalValue(attachment.task_projection?.status);
    const effectiveState = projectionState || state;
    const hasExplicitTerminal = Boolean(reason) || isTerminalRuntimeLifecycle(attachment.lifecycle) || isTerminalRuntimeState(projectionState);
    if (isNonCloseoutRuntimeReason(reason) || isNonCloseoutRuntimeState(effectiveState)) {
      continue;
    }
    if (!hasExplicitTerminal) {
      continue;
    }
    if (["error", "failed", "blocked", "missing"].includes(state) || ["error", "failed", "blocked", "missing"].includes(projectionState)) {
      return "error";
    }
    if (
      ["stopped", "aborted", "cancelled", "canceled", "user_aborted"].includes(state)
      || ["stopped", "aborted", "cancelled", "canceled", "user_aborted"].includes(reason)
      || ["stopped", "aborted", "cancelled", "canceled", "user_aborted"].includes(projectionState)
    ) {
      return "stopped";
    }
    if (["completed", "complete", "done", "success"].includes(state) || ["completed", "complete", "done", "success"].includes(projectionState)) {
      hasDone = true;
    }
  }
  return hasDone ? "done" : "";
}

function isTerminalRuntimeLifecycle(value: unknown) {
  return isTerminalRuntimeState(compactTerminalValue(value));
}

function isTerminalRuntimeState(value: string) {
  return ["completed", "complete", "done", "success", "error", "failed", "blocked", "missing", "stopped", "aborted", "cancelled", "canceled", "user_aborted"].includes(value);
}

function isNonCloseoutRuntimeReason(value: string) {
  return [
    "task_executor_scheduled",
    "waiting_executor",
    "waiting_user",
    "waiting_approval",
    "waiting_safe_boundary",
    "append_instruction_to_active_work",
    "continue_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
  ].includes(value);
}

function isNonCloseoutRuntimeState(value: string) {
  return ["", "running", "working", "queued", "waiting", "paused", "partial"].includes(value);
}

function publicTimelineDraftTerminalState(
  items: PublicChatTimelineItem[] | undefined,
): ReturnType<typeof publicTimelineTerminalStateFromAnswer> {
  for (const item of items ?? []) {
    if (!isPublicTimelineStatusBarItem(item)) {
      continue;
    }
    const state = compactTerminalValue(item.state);
    const phase = compactTerminalValue(item.phase);
    const streamState = compactTerminalValue(item.stream_state);
    const terminalMarker = phase === "done" || streamState === "done";
    if (!terminalMarker) {
      continue;
    }
    if (["error", "failed", "blocked", "missing"].includes(state)) {
      return "error";
    }
    if (["stopped", "aborted", "cancelled", "canceled", "user_aborted"].includes(state)) {
      return "stopped";
    }
    if (["completed", "complete", "done", "success"].includes(state)) {
      return "done";
    }
  }
  return "";
}

function compactTerminalValue(value: unknown) {
  return cleanPublicTimelineText(value).toLowerCase();
}

function assistantDisplayContent(
  content: string,
  metadata: Parameters<typeof shouldDisplayAssistantContent>[0],
) {
  const normalized = String(content || "").trim();
  const answerChannel = cleanPublicTimelineText(metadata.answerChannel).toLowerCase();
  const answerSource = cleanPublicTimelineText(metadata.answerSource).toLowerCase();
  if (answerChannel === "blocked" && answerSource === "harness.single_agent_turn.tool_loop") {
    return "";
  }
  if (!shouldDisplayAssistantContent(metadata)) {
    return "";
  }
  if (isInternalControlProtocolText(normalized)) {
    return "";
  }
  return content;
}
