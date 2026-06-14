"use client";

import { Check, Copy, Pencil, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type {
  MessagePublicProjection,
  PublicChatTimelineItem,
  PublicProjectionBodyBlock,
  PublicProjectionItem,
  RetrievalResult,
  ToolCall,
} from "@/lib/api";
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
  const projectionBodyBlocks = (publicProjection?.bodyBlocks ?? [])
    .filter((block) => block.text && !isInternalControlProtocolText(block.text));
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
  const renderMessageContent = (key = "message-content", bodyText?: string, showCopy = true) => {
    const displayText = bodyText ?? naturalizedMessageDisplayContent;
    const explicitBodyText = bodyText !== undefined;
    const renderableContent =
      isUser
      || (!explicitBodyText && Boolean(image?.src))
      || (!explicitBodyText && imageUnavailable)
      || Boolean(displayText.trim());
    return renderableContent ? (
    <div
      className={isUser ? "chat-message-shell__content whitespace-pre-wrap leading-7" : "chat-message-shell__content markdown"}
      key={key}
    >
      {!isUser && showCopy && copyableReplyText ? (
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
      ) : !explicitBodyText && image?.src && !imageUnavailable ? (
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
      ) : !explicitBodyText && imageUnavailable ? (
        <div className="chat-image-message chat-image-message--missing">
          <p>图像文件不可用。</p>
          <span>{image?.src}</span>
        </div>
      ) : (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {displayText}
        </ReactMarkdown>
      )}
    </div>
    ) : null;
  };
  const orderedMessageBlocks = isUser
    ? []
    : orderedProjectionMessageBlocks({
      bodyBlocks: projectionBodyBlocks,
      hasBody: shouldRenderContent,
      fallbackBodyText: naturalizedMessageDisplayContent,
      timelineItems: publicTimelineItems,
    });
  const firstBodyBlockKey = orderedMessageBlocks.find((block) => block.kind === "body")?.key ?? "";

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
          ? renderMessageContent(block.key, block.text, block.key === firstBodyBlockKey)
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
  | { kind: "body"; key: string; offset: number; text: string }
  | { kind: "activity"; key: string; offset: number; items: PublicChatTimelineItem[] };

function orderedProjectionMessageBlocks({
  bodyBlocks,
  fallbackBodyText,
  hasBody,
  timelineItems,
}: {
  bodyBlocks: PublicProjectionBodyBlock[];
  fallbackBodyText: string;
  hasBody: boolean;
  timelineItems: PublicChatTimelineItem[];
}): ProjectionMessageBlock[] {
  const entries: ProjectionMessageBlock[] = [];
  if (bodyBlocks.length > 0) {
    for (const block of bodyBlocks) {
      entries.push({
        kind: "body",
        key: block.blockId,
        offset: Number.isFinite(Number(block.firstOffset)) ? Number(block.firstOffset) : Number.MAX_SAFE_INTEGER,
        text: block.text,
      });
    }
  } else if (hasBody) {
    entries.push({
      kind: "body",
      key: "projection-body",
      offset: Number.MAX_SAFE_INTEGER,
      text: fallbackBodyText,
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
  if (projectionHasClosedBody(projection)) return [];
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

function projectionHasClosedBody(projection: MessagePublicProjection) {
  const bodyState = cleanText(projection.bodyState).toLowerCase();
  return Boolean(cleanText(projection.bodyText)) && ["finalized", "committed"].includes(bodyState);
}

function projectionItemToTimelineItem(item: PublicProjectionItem): PublicChatTimelineItem | null {
  if (!isProjectionTimelineItem(item)) return null;
  const toolOwned = Boolean(item.toolCallId || item.toolName);
  const toolWindow = toolOwned && projectionItemNeedsToolWindow(item);
  const title = projectionTimelineTitle(item);
  const toolLabel = projectionToolLabel(item.toolName);
  const detail = normalizeProjectionToolTitle(cleanText(item.detail), item);
  if (!title) return null;
  return {
    item_id: item.itemId,
    kind: toolOwned ? (toolWindow ? "work_action" : "tool_activity") : "status_update",
    slot: toolOwned ? "tool" : "status",
    surface: toolWindow ? "tool_window" : "timeline",
    source_authority: item.sourceAuthority,
    event_family: item.eventFamily,
    channel: item.channel,
    lossless: item.lossless,
    title,
    text: title,
    detail,
    state: item.state,
    phase: item.state === "running" || item.state === "waiting" ? "running" : "done",
    stream_state: item.state === "running" || item.state === "waiting" ? "streaming" : "done",
    tool_call_id: item.toolCallId,
    tool_lifecycle_id: item.toolLifecycleId,
    tool_name: toolLabel || item.toolName,
    action_kind: item.actionKind,
    subject_label: item.subjectLabel,
    collapsed: item.collapsed,
    trace_refs: item.traceRefs,
    artifacts: item.artifactRefs,
    event_offset: item.eventOffset,
    updated_event_offset: item.updatedEventOffset,
    source_event_id: item.sourceEventId,
    source_event_type: item.sourceEventType,
    tool_window: toolWindow ? {
      tool_label: toolLabel || item.toolName,
      status: projectionToolStatusLabel(item),
      target: item.subjectLabel,
      sections: [
        detail ? { label: "详情", text: detail } : null,
        item.subjectLabel && item.subjectLabel !== detail ? { label: "目标", text: item.subjectLabel } : null,
      ].filter((section): section is { label: string; text: string } => Boolean(section?.text)),
    } : undefined,
    public_summary: detail || title,
  };
}

function projectionItemNeedsToolWindow(item: PublicProjectionItem) {
  const state = cleanText(item.state).toLowerCase();
  const visibility = cleanText(item.mainVisibility).toLowerCase();
  const retention = cleanText(item.retention).toLowerCase();
  const sourceEventType = cleanText(item.sourceEventType).toLowerCase();
  if (["failed", "error", "blocked", "missing"].includes(state)) return true;
  if (visibility === "pinned" || retention === "pinned_until_resolved") return true;
  if (sourceEventType === "tool_permission_decided" && state !== "done") return true;
  if ((item.artifactRefs?.length ?? 0) > 0) return true;
  return false;
}

function isProjectionTimelineItem(item: PublicProjectionItem) {
  if (item.toolCallId || item.toolName) return true;
  const visibility = cleanText(item.mainVisibility).toLowerCase();
  if (visibility === "hidden") return false;
  return Boolean(cleanText(item.title || item.text || item.detail));
}

function projectionTimelineTitle(item: PublicProjectionItem) {
  const explicit = cleanText(item.title || item.text);
  if (explicit) return normalizeProjectionToolTitle(explicit, item);
  const tool = projectionToolLabel(item.toolName) || "工具";
  if (!item.toolCallId && !item.toolName) return "";
  const sourceEventType = cleanText(item.sourceEventType).toLowerCase();
  const state = cleanText(item.state).toLowerCase();
  if (sourceEventType === "tool_permission_decided") return "工具权限已确认";
  if (sourceEventType === "tool_item_started") return `正在${tool}`;
  if (sourceEventType === "tool_item_completed") {
    return ["failed", "error", "blocked"].includes(state) ? `${tool}失败` : `${tool}完成`;
  }
  if (state === "running") return `正在${tool}`;
  if (state === "waiting") return `等待${tool}`;
  if (["failed", "error", "blocked"].includes(state)) return `${tool}失败`;
  return `${tool}完成`;
}

function projectionToolStatusLabel(item: PublicProjectionItem) {
  const state = cleanText(item.state).toLowerCase();
  if (state === "running") return "运行中";
  if (state === "waiting") return "等待中";
  if (["done", "complete", "completed", "success", "passed"].includes(state)) return "已完成";
  if (["failed", "error", "blocked", "missing"].includes(state)) return "失败";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "已停止";
  return state || undefined;
}

function normalizeProjectionToolTitle(title: string, item: PublicProjectionItem) {
  const rawToolName = cleanText(item.toolName);
  const toolLabel = projectionToolLabel(rawToolName);
  if (!rawToolName || !toolLabel || rawToolName === toolLabel) return title;
  const escaped = rawToolName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return title.replace(new RegExp(`^${escaped}\\s*[:：]\\s*`, "i"), `${toolLabel}：`);
}

function projectionToolLabel(toolName: unknown) {
  const normalized = cleanText(toolName).toLowerCase();
  const labels: Record<string, string> = {
    glob_paths: "匹配路径",
    list_dir: "列出目录",
    path_exists: "检查路径",
    read_file: "读取文件",
    read_files: "读取文件",
    read_path: "读取文件",
    search_files: "搜索文件",
    search_text: "搜索文本",
    stat_path: "检查路径",
    write_file: "写入文件",
    edit_file: "更新文件",
    apply_patch: "更新文件",
  };
  return labels[normalized] || cleanText(toolName);
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
