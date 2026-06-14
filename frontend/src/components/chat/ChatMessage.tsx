"use client";

import { Check, Copy, Pencil, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { MessagePublicProjection, PublicChatTimelineItem, PublicProjectionItem, RetrievalResult, ToolCall } from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";
import { useNaturalizedStreamText } from "./useNaturalizedStreamText";

export function ChatMessage({
  id,
  role,
  content,
  image,
  publicProjection,
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
  publicProjection?: MessagePublicProjection;
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
  const projectionBodyText = publicProjection?.bodyText && !isInternalControlProtocolText(publicProjection.bodyText)
    ? publicProjection.bodyText
    : "";
  const baseDisplayContent = isUser
    ? content
    : projectionBodyText || assistantDisplayContent(content, {
      answerChannel,
      answerCanonicalState,
      answerPersistPolicy,
      answerSource,
      answerLeakFlags,
    });
  const messageDisplayContent = baseDisplayContent;
  const publicTimelineItems = isUser
    ? []
    : publicTimelineItemsFromProjection(publicProjection);
  const hasPublicTimelineActivity = publicTimelineHasDisplayableActivity(publicTimelineItems);
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
  const renderMessageContent = (key = "message-content") => shouldRenderContent ? (
    <div
      className={isUser ? "chat-message-shell__content whitespace-pre-wrap leading-7" : "chat-message-shell__content markdown"}
      key={key}
    >
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
  ) : null;
  const orderedMessageBlocks = isUser
    ? []
    : orderedProjectionMessageBlocks({
      bodyEventOffset: publicProjection?.bodyEventOffset,
      hasBody: shouldRenderContent,
      timelineItems: publicTimelineItems,
    });

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
      {isUser ? renderMessageContent() : orderedMessageBlocks.map((block) => (
        block.kind === "body"
          ? renderMessageContent(block.key)
          : (
            <PublicTimelineActivity
              ariaLabel="执行轨迹"
              items={block.items}
              key={block.key}
            />
          )
      ))}
      {showThinkingPlaceholder ? (
        <div className="chat-message-shell__thinking-placeholder" aria-live="polite">
          <span>正在思考</span>
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

type ProjectionMessageBlock =
  | { kind: "body"; key: string; offset: number }
  | { kind: "activity"; key: string; offset: number; items: PublicChatTimelineItem[] };

function orderedProjectionMessageBlocks({
  bodyEventOffset,
  hasBody,
  timelineItems,
}: {
  bodyEventOffset?: number;
  hasBody: boolean;
  timelineItems: PublicChatTimelineItem[];
}): ProjectionMessageBlock[] {
  const entries: ProjectionMessageBlock[] = [];
  if (hasBody) {
    entries.push({
      kind: "body",
      key: "projection-body",
      offset: Number.isFinite(Number(bodyEventOffset)) ? Number(bodyEventOffset) : Number.MAX_SAFE_INTEGER,
    });
  }
  for (const item of timelineItems) {
    entries.push({
      kind: "activity",
      key: `activity:${item.item_id || item.source_event_id || item.event_offset || entries.length}`,
      offset: Number.isFinite(Number(item.event_offset)) ? Number(item.event_offset) : 0,
      items: [item],
    });
  }
  const sorted = entries.sort((left, right) => {
    if (left.offset !== right.offset) return left.offset - right.offset;
    if (left.kind !== right.kind) return left.kind === "activity" ? -1 : 1;
    return left.key.localeCompare(right.key);
  });
  const grouped: ProjectionMessageBlock[] = [];
  for (const entry of sorted) {
    const previous = grouped[grouped.length - 1];
    if (entry.kind === "activity" && previous?.kind === "activity") {
      previous.items.push(...entry.items);
      continue;
    }
    grouped.push(entry);
  }
  return grouped;
}

function publicTimelineItemsFromProjection(projection: MessagePublicProjection | undefined): PublicChatTimelineItem[] {
  if (!projection) return [];
  const timeline = projection.timeline?.length
    ? projection.timeline
    : [
      projection.currentAction,
      ...(projection.status ?? []),
      ...(projection.pinned ?? []),
      ...(projection.finalResults ?? []),
      ...(projection.trace ?? []),
    ].filter((item): item is PublicProjectionItem => Boolean(item));
  return timeline
    .map(projectionItemToTimelineItem)
    .filter((item): item is PublicChatTimelineItem => Boolean(item))
    .sort((left, right) =>
      Number(left.event_offset ?? 0) - Number(right.event_offset ?? 0)
      || String(left.item_id || "").localeCompare(String(right.item_id || ""))
    );
}

function projectionItemToTimelineItem(item: PublicProjectionItem): PublicChatTimelineItem | null {
  if (!isProjectionTimelineItem(item)) return null;
  const toolOwned = Boolean(item.toolCallId || item.toolName);
  const title = projectionTimelineTitle(item);
  if (!title) return null;
  return {
    item_id: item.itemId,
    kind: toolOwned ? "work_action" : "status_update",
    slot: toolOwned ? "tool" : "status",
    surface: toolOwned ? "tool_window" : "timeline",
    source_authority: item.sourceAuthority,
    title,
    text: title,
    detail: item.detail,
    state: item.state,
    phase: item.state === "running" || item.state === "waiting" ? "running" : "done",
    stream_state: item.state === "running" || item.state === "waiting" ? "streaming" : "done",
    tool_call_id: item.toolCallId,
    tool_name: item.toolName,
    action_kind: item.actionKind,
    subject_label: item.subjectLabel,
    collapsed: item.collapsed,
    trace_refs: item.traceRefs,
    artifacts: item.artifactRefs,
    event_offset: item.eventOffset,
    source_event_id: item.sourceEventId,
    tool_window: toolOwned ? {
      tool_label: item.toolName,
      status: projectionToolStatusLabel(item),
      target: item.subjectLabel,
      sections: [
        item.detail ? { label: "详情", text: item.detail } : null,
        item.subjectLabel && item.subjectLabel !== item.detail ? { label: "目标", text: item.subjectLabel } : null,
      ].filter((section): section is { label: string; text: string } => Boolean(section?.text)),
    } : undefined,
    public_summary: item.detail || item.text || item.title,
  };
}

function isProjectionTimelineItem(item: PublicProjectionItem) {
  if (item.toolCallId || item.toolName) return true;
  const visibility = cleanText(item.mainVisibility).toLowerCase();
  if (visibility === "hidden") return false;
  return Boolean(cleanText(item.title || item.text || item.detail));
}

function projectionTimelineTitle(item: PublicProjectionItem) {
  const explicit = cleanText(item.title || item.text);
  if (explicit) return explicit;
  const tool = cleanText(item.toolName) || "tool";
  if (!item.toolCallId && !item.toolName) return "";
  const sourceEventType = cleanText(item.sourceEventType).toLowerCase();
  const state = cleanText(item.state).toLowerCase();
  if (sourceEventType === "tool_permission_decided") return "工具权限已确认";
  if (sourceEventType === "tool_item_started") return `正在执行 ${tool}`;
  if (sourceEventType === "tool_item_completed") {
    return ["failed", "error", "blocked"].includes(state) ? `${tool} 执行失败` : `${tool} 执行完成`;
  }
  if (state === "running") return `正在执行 ${tool}`;
  if (state === "waiting") return `等待 ${tool}`;
  if (["failed", "error", "blocked"].includes(state)) return `${tool} 执行失败`;
  return `${tool} 执行完成`;
}

function projectionToolStatusLabel(item: PublicProjectionItem) {
  const state = cleanText(item.state).toLowerCase();
  if (state === "running") return "running";
  if (state === "waiting") return "waiting";
  if (["failed", "error", "blocked"].includes(state)) return "failed";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  return state || undefined;
}

function assistantDisplayContent(
  content: string,
  metadata: Parameters<typeof shouldDisplayAssistantContent>[0],
) {
  const normalized = String(content || "").trim();
  const answerChannel = cleanText(metadata.answerChannel).toLowerCase();
  const answerSource = cleanText(metadata.answerSource).toLowerCase();
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

function cleanText(value: unknown) {
  return String(value ?? "").trim();
}
