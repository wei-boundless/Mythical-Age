"use client";

import { Check, Copy, FileText, Pencil, X } from "lucide-react";
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
  runtimeDisplayState,
  mainChatSurface,
  closeoutSummary,
  runtimeLogRef,
  toolEventCount,
  answerChannel,
  answerCanonicalState,
  answerPersistPolicy,
  answerSource,
  answerLeakFlags,
  streamingContent = false,
  retrievals,
  canEdit = false,
  onOpenRuntimeLog,
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
  runtimeDisplayState?: string;
  mainChatSurface?: string;
  closeoutSummary?: string;
  runtimeLogRef?: string;
  toolEventCount?: number;
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
  onOpenRuntimeLog?: () => void;
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
  const mainSurface = normalizedMainChatSurface(mainChatSurface, runtimeDisplayState);
  const taskClosed = mainSurface === "closeout_summary";
  const renderProjectionTimeline = !isUser && !taskClosed && mainSurface !== "log_only";
  const projectionBodyText = publicProjection?.bodyText && !isInternalControlProtocolText(publicProjection.bodyText)
    ? publicProjection.bodyText
    : "";
  const closeoutText = closeoutSummary && !isInternalControlProtocolText(closeoutSummary)
    ? closeoutSummary
    : "";
  const assistantContentText = isUser
    ? ""
    : assistantDisplayContent(content, {
      answerChannel,
      answerCanonicalState,
      answerPersistPolicy,
      answerSource,
      answerLeakFlags,
    });
  const projectionBodyBlocks = renderProjectionTimeline
    ? (publicProjection?.bodyBlocks ?? []).filter((block) => block.text && !isInternalControlProtocolText(block.text))
    : [];
  const baseDisplayContent = isUser
    ? content
    : taskClosed
      ? projectionBodyText || assistantContentText || closeoutText
      : projectionBodyText || assistantContentText;
  const messageDisplayContent = baseDisplayContent;
  const publicTimelineItems = isUser
    ? []
    : renderProjectionTimeline
      ? publicTimelineItemsFromProjection(publicProjection)
      : [];
  const activeModelWaitPlaceholder = publicTimelineItems.some(isModelWaitPlaceholderTimelineItem);
  const publicActivityItems = publicTimelineItems.filter((item) => !isModelWaitPlaceholderTimelineItem(item));
  const hasPublicTimelineActivity = publicTimelineHasDisplayableActivity(publicActivityItems);
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
    && (streamingContent || activeModelWaitPlaceholder)
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
  const orderedMessageBlocks = isUser || taskClosed || !renderProjectionTimeline
    ? []
    : orderedProjectionMessageBlocks({
      bodyBlocks: projectionBodyBlocks,
      hasBody: shouldRenderContent,
      fallbackBodyText: naturalizedMessageDisplayContent,
      timelineItems: publicActivityItems,
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
      {isUser || taskClosed || !renderProjectionTimeline ? renderMessageContent() : orderedMessageBlocks.map((block) => (
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
      {!isUser && taskClosed ? (
        <RuntimeLogEntry
          onOpen={onOpenRuntimeLog}
          runtimeLogRef={runtimeLogRef}
          toolEventCount={toolEventCount}
        />
      ) : null}
      {showThinkingPlaceholder ? (
        <div className="chat-message-shell__thinking-placeholder" aria-live="polite">
          <span>正在思考</span>
        </div>
      ) : null}
    </article>
  );
}

function RuntimeLogEntry({
  onOpen,
  runtimeLogRef,
  toolEventCount,
}: {
  onOpen?: () => void;
  runtimeLogRef?: string;
  toolEventCount?: number;
}) {
  const count = Number(toolEventCount ?? 0);
  const detail = Number.isFinite(count) && count > 0
    ? `${count} 次工具调用`
    : "完整执行轨迹";
  const title = runtimeLogRef ? "查看执行日志" : "执行日志";
  const content = (
    <>
      <FileText size={14} />
      <span>{title}</span>
      <strong>{detail}</strong>
    </>
  );
  if (!onOpen) {
    return (
      <div className="chat-message-shell__runtime-log-entry" aria-label="执行日志">
        {content}
      </div>
    );
  }
  return (
    <button
      className="chat-message-shell__runtime-log-entry chat-message-shell__runtime-log-entry--button"
      onClick={onOpen}
      type="button"
    >
      {content}
    </button>
  );
}

function normalizedMainChatSurface(mainChatSurface?: string, runtimeDisplayState?: string) {
  const surface = cleanText(mainChatSurface).toLowerCase();
  if (surface === "body_only" || surface === "live_timeline" || surface === "closeout_summary" || surface === "log_only") {
    return surface;
  }
  const displayState = cleanText(runtimeDisplayState).toLowerCase();
  if (displayState === "task_live") return "live_timeline";
  if (displayState === "task_closed") return "closeout_summary";
  if (displayState === "normal_turn") return "body_only";
  return "body_only";
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
  const seenBodyText = new Set<string>();
  const seenModelFeedback = new Set<string>();
  if (bodyBlocks.length > 0) {
    for (const block of bodyBlocks) {
      const bodyKey = compactText(block.text);
      if (bodyKey) seenBodyText.add(bodyKey);
      entries.push({
        kind: "body",
        key: block.blockId,
        offset: Number.isFinite(Number(block.firstOffset)) ? Number(block.firstOffset) : Number.MAX_SAFE_INTEGER,
        text: block.text,
      });
    }
  } else if (hasBody) {
    const bodyKey = compactText(fallbackBodyText);
    if (bodyKey) seenBodyText.add(bodyKey);
    entries.push({
      kind: "body",
      key: "projection-body",
      offset: Number.MAX_SAFE_INTEGER,
      text: fallbackBodyText,
    });
  }
  for (const item of timelineItems) {
    if (isModelFeedbackTimelineItem(item)) {
      const feedbackText = modelFeedbackBodyText(item);
      if (feedbackText) {
        const feedbackKey = modelFeedbackIdentityKey(item);
        const feedbackTextKey = compactText(feedbackText);
        if (feedbackTextKey && seenBodyText.has(feedbackTextKey)) {
          continue;
        }
        if (feedbackKey && seenModelFeedback.has(feedbackKey)) {
          continue;
        }
        if (feedbackKey) {
          seenModelFeedback.add(feedbackKey);
        }
        if (feedbackTextKey) seenBodyText.add(feedbackTextKey);
        entries.push({
          kind: "body",
          key: `model-feedback:${item.source_event_id || item.item_id || item.event_offset || entries.length}`,
          offset: Number.isFinite(Number(item.event_offset)) ? Number(item.event_offset) : 0,
          text: feedbackText,
        });
      }
      continue;
    }
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

function modelFeedbackIdentityKey(item: PublicChatTimelineItem) {
  return cleanText(item.item_id)
    || cleanText(item.source_event_id)
    || cleanText(item.source_event_type && item.event_offset !== undefined ? `${item.source_event_type}:${item.event_offset}` : "")
    || "";
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
    ].filter((item): item is PublicProjectionItem => Boolean(item));
  const items = coalesceProjectionTimelineItems(timeline)
    .map(projectionItemToTimelineItem)
    .filter((item): item is PublicChatTimelineItem => Boolean(item))
    .sort((left, right) =>
      Number(left.event_offset ?? 0) - Number(right.event_offset ?? 0)
      || String(left.item_id || "").localeCompare(String(right.item_id || ""))
    );
  const latestBodyOffset = latestProjectionBodyOffset(projection);
  const latestNonWaitOffset = Math.max(
    Number.NEGATIVE_INFINITY,
    ...items
      .filter((item) => !isModelWaitPlaceholderTimelineItem(item))
      .map((item) => Number(item.event_offset ?? Number.NEGATIVE_INFINITY)),
  );
  return items.filter((item) => {
    if (!isModelWaitPlaceholderTimelineItem(item)) return true;
    const itemOffset = Number(item.event_offset ?? Number.NEGATIVE_INFINITY);
    return itemOffset >= latestBodyOffset && itemOffset >= latestNonWaitOffset;
  });
}

function latestProjectionBodyOffset(projection: MessagePublicProjection) {
  const bodyBlockOffsets = (projection.bodyBlocks ?? []).flatMap((block) => [
    Number(block.firstOffset),
    Number(block.lastOffset),
  ]);
  return Math.max(
    Number.NEGATIVE_INFINITY,
    Number(projection.bodyEventOffset ?? Number.NEGATIVE_INFINITY),
    ...bodyBlockOffsets.filter(Number.isFinite),
  );
}

function projectionItemToTimelineItem(item: PublicProjectionItem): PublicChatTimelineItem | null {
  if (!isProjectionTimelineItem(item)) return null;
  if (cleanText(item.toolName).toLowerCase() === "agent_todo") return null;
  const toolOwned = Boolean(item.toolCallId || item.toolLifecycleId || item.toolName);
  const toolWindow = toolOwned && projectionItemNeedsToolWindow(item);
  const toolLabel = projectionToolLabel(item.toolName);
  const detail = normalizeProjectionToolTitle(cleanText(item.detail), item);
  const rawTarget = cleanText(item.target || item.subjectLabel || projectionTargetFromTitle(item.title || item.text));
  const target = projectionToolTargetLabel(rawTarget);
  const argumentsPreview = projectionToolArgumentsPreview(item.argumentsPreview, rawTarget);
  const statusLabel = projectionToolStatusLabel(item);
  const commandLine = projectionToolCommandLine(item, { argumentsPreview, target });
  const output = projectionToolConsoleOutput(item, { detail, statusLabel });
  const title = toolWindow
    ? projectionToolWindowTitle(item, { argumentsPreview, statusLabel, target, toolLabel })
    : projectionTimelineTitle(item);
  if (!title) return null;
  return {
    item_id: item.itemId,
    source_item_id: item.sourceItemId,
    kind: toolOwned ? (toolWindow ? "work_action" : "tool_activity") : "status_update",
    slot: toolOwned ? "tool" : "status",
    surface: toolWindow ? "tool_window" : "timeline",
    source_authority: item.sourceAuthority,
    event_family: item.eventFamily,
    channel: item.channel,
    status_kind: item.statusKind,
    lossless: item.lossless,
    title,
    text: title,
    detail,
    state: item.state,
    phase: item.state === "running" || item.state === "waiting" ? "running" : "done",
    stream_state: item.state === "running" || item.state === "waiting" ? "streaming" : "done",
    tool_call_id: item.toolCallId,
    tool_lifecycle_id: item.toolLifecycleId,
    tool_name: item.toolName,
    permission_decision_id: item.permissionDecisionId,
    arguments_preview: argumentsPreview,
    target,
    action_kind: item.actionKind,
    subject_label: target || item.subjectLabel,
    collapsed: item.collapsed,
    trace_refs: item.traceRefs,
    artifacts: item.artifactRefs,
    event_offset: item.eventOffset,
    updated_event_offset: item.updatedEventOffset,
    source_event_id: item.sourceEventId,
    source_event_type: item.sourceEventType,
    tool_window: toolWindow ? {
      tool_label: toolLabel || item.toolName,
      status: statusLabel,
      target,
      command_line: commandLine,
      output,
      sections: projectionToolWindowSections(item, { detail, target, argumentsPreview }),
    } : undefined,
    public_summary: detail || title,
  };
}

function coalesceProjectionTimelineItems(items: PublicProjectionItem[]) {
  const result: PublicProjectionItem[] = [];
  const indexByToolKey = new Map<string, number>();
  for (const item of [...items].sort(compareProjectionItemsByOffset)) {
    const key = projectionToolWindowKey(item);
    if (!key) {
      result.push(item);
      continue;
    }
    const existingIndex = indexByToolKey.get(key);
    if (existingIndex === undefined) {
      indexByToolKey.set(key, result.length);
      result.push(item);
      continue;
    }
    result[existingIndex] = mergeProjectionTimelineItem(result[existingIndex], item);
  }
  return result;
}

function compareProjectionItemsByOffset(left: PublicProjectionItem, right: PublicProjectionItem) {
  return Number(left.eventOffset ?? 0) - Number(right.eventOffset ?? 0)
    || Number(left.updatedEventOffset ?? 0) - Number(right.updatedEventOffset ?? 0)
    || left.itemId.localeCompare(right.itemId);
}

function projectionToolWindowKey(item: PublicProjectionItem) {
  return cleanText(item.toolCallId) || cleanText(item.toolLifecycleId);
}

function mergeProjectionTimelineItem(existing: PublicProjectionItem, incoming: PublicProjectionItem): PublicProjectionItem {
  const merged: PublicProjectionItem = { ...existing };
  for (const [key, value] of Object.entries(incoming) as Array<[keyof PublicProjectionItem, PublicProjectionItem[keyof PublicProjectionItem]]>) {
    if (key === "itemId" || key === "eventOffset") continue;
    if (value === "" || value === undefined || value === null) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    merged[key] = value as never;
  }
  const existingOffset = Number(existing.eventOffset);
  const incomingOffset = Number(incoming.eventOffset);
  merged.eventOffset = Number.isFinite(existingOffset)
    ? existingOffset
    : (Number.isFinite(incomingOffset) ? incomingOffset : existing.eventOffset);
  const offsets = [existing.updatedEventOffset, incoming.updatedEventOffset, existing.eventOffset, incoming.eventOffset]
    .map(Number)
    .filter(Number.isFinite);
  if (offsets.length) {
    merged.updatedEventOffset = Math.max(...offsets);
  }
  merged.itemId = projectionToolWindowKey(merged) || existing.itemId;
  return merged;
}

function projectionToolWindowTitle(
  item: PublicProjectionItem,
  {
    argumentsPreview,
    statusLabel,
    target,
    toolLabel,
  }: {
    argumentsPreview: string;
    statusLabel?: string;
    target: string;
    toolLabel: string;
  },
) {
  const explicit = normalizeProjectionToolTitle(cleanText(item.title || item.text), item);
  const targetLabel = projectionToolTargetLabel(target);
  let action = toolLabel || explicit || "工具";
  if (!targetLabel && explicit && toolLabel && !sameCompactText(explicit, toolLabel)) {
    action = explicit;
  }
  const parts = [action];
  if (targetLabel && !compactText(action).includes(compactText(targetLabel))) {
    parts.push(targetLabel);
  }
  const preview = cleanText(argumentsPreview);
  if (preview && !compactText(parts.join("")).includes(compactText(preview))) {
    parts.push(preview);
  }
  const status = cleanText(statusLabel);
  const compactTitle = compactText(parts.join(""));
  if (status && !compactTitle.includes(compactText(status))) {
    parts.push(status);
  }
  return parts.join(" ");
}

function projectionToolWindowSections(
  item: PublicProjectionItem,
  {
    argumentsPreview,
    detail,
    target,
  }: {
    argumentsPreview: string;
    detail: string;
    target: string;
  },
) {
  const sections: Array<{ label: string; text: string }> = [];
  const title = cleanText(item.title || item.text);
  if (target) {
    sections.push({ label: "目标", text: target });
  }
  if (argumentsPreview && !sameCompactText(argumentsPreview, target)) {
    sections.push({ label: "参数", text: argumentsPreview });
  }
  if (
    detail
    && !sameCompactText(detail, title)
    && !sameCompactText(detail, target)
    && !sameCompactText(detail, argumentsPreview)
  ) {
    sections.push({ label: projectionToolDetailLabel(item), text: detail });
  }
  return sections;
}

function projectionToolCommandLine(
  item: PublicProjectionItem,
  {
    argumentsPreview,
    target,
  }: {
    argumentsPreview: string;
    target: string;
  },
) {
  const tool = cleanText(item.toolName || item.actionKind || "tool");
  const parts = [tool];
  if (target) parts.push(quoteCommandPart(target));
  if (argumentsPreview && !sameCompactText(argumentsPreview, target)) {
    parts.push(argumentsPreview);
  }
  return parts.join(" ");
}

function projectionToolConsoleOutput(
  item: PublicProjectionItem,
  {
    detail,
    statusLabel,
  }: {
    detail: string;
    statusLabel?: string;
  },
) {
  if (detail) return detail;
  const sourceEventType = cleanText(item.sourceEventType).toLowerCase();
  const state = cleanText(item.state).toLowerCase();
  if (sourceEventType === "tool_call_requested") return "已提交系统调用。";
  if (sourceEventType === "tool_permission_decided") return "系统调用已通过准入。";
  if (sourceEventType === "tool_item_started" || state === "running") return "系统调用运行中。";
  return statusLabel ? `系统调用${statusLabel}。` : "";
}

function quoteCommandPart(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  return /\s/.test(text) ? `"${text.replace(/"/g, '\\"')}"` : text;
}

function projectionToolDetailLabel(item: PublicProjectionItem) {
  const state = cleanText(item.state).toLowerCase();
  if (["failed", "error", "blocked", "missing"].includes(state)) return "错误";
  if (["done", "complete", "completed", "success", "passed"].includes(state)) return "观察";
  return "详情";
}

function projectionItemNeedsToolWindow(item: PublicProjectionItem) {
  if (item.toolCallId || item.toolLifecycleId || item.toolName) return true;
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
  if (item.toolCallId || item.toolLifecycleId || item.toolName) return true;
  const visibility = cleanText(item.mainVisibility).toLowerCase();
  if (visibility === "hidden") return false;
  return Boolean(cleanText(item.title || item.text || item.detail));
}

function projectionTimelineTitle(item: PublicProjectionItem) {
  const explicit = cleanText(item.title || item.text);
  if (explicit) return normalizeProjectionToolTitle(explicit, item);
  const tool = projectionToolLabel(item.toolName) || "工具";
  if (!item.toolCallId && !item.toolLifecycleId && !item.toolName) return "";
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

function projectionTargetFromTitle(value: unknown) {
  const text = cleanText(value);
  const match = text.match(/^[^:：]{2,24}[:：]\s*(.+)$/);
  return cleanText(match?.[1]);
}

function projectionToolTargetLabel(value: unknown) {
  const text = cleanText(value).replace(/\\/g, "/");
  if (!text) return "";
  const projectRelative = text.match(/(?:^|\/)langchain-agent\/(.+)$/i)?.[1];
  if (projectRelative) return projectRelative;
  const parts = text.split("/").filter(Boolean);
  if (/^[A-Za-z]:\//.test(text) && parts.length) {
    return parts.slice(-3).join("/");
  }
  if (parts.length > 3) {
    return parts.slice(-3).join("/");
  }
  return text;
}

function projectionToolArgumentsPreview(value: unknown, rawTarget: string) {
  const text = cleanText(value);
  if (!text) return "";
  const visibleParts = text
    .split(",")
    .map((part) => cleanText(part))
    .filter((part) => part && !argumentPartRepeatsTarget(part, rawTarget));
  return visibleParts.join(", ");
}

function argumentPartRepeatsTarget(part: string, rawTarget: string) {
  if (!rawTarget) return false;
  const value = cleanText(part.replace(/^[A-Za-z0-9_.-]+\s*=\s*/, ""));
  return sameCompactText(value, rawTarget)
    || sameCompactText(projectionToolTargetLabel(value), projectionToolTargetLabel(rawTarget));
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
    batch_edit_file: "批量编辑文件",
    apply_patch: "更新文件",
  };
  return labels[normalized] || cleanText(toolName);
}

function isModelFeedbackTimelineItem(item: PublicChatTimelineItem) {
  if (cleanText(item.tool_call_id) || cleanText(item.tool_lifecycle_id) || cleanText(item.tool_name)) return false;
  const sourceAuthority = cleanText(item.source_authority).toLowerCase();
  const eventFamily = cleanText(item.event_family).toLowerCase();
  const channel = cleanText(item.channel).toLowerCase();
  const sourceEventType = cleanText(item.source_event_type).toLowerCase();
  const statusKind = cleanText(item.status_kind || (item as { statusKind?: unknown }).statusKind).toLowerCase();
  if (sourceEventType === "runtime_step_summary" && statusKind === "public_stage_status") return true;
  return sourceAuthority === "model" && (eventFamily === "status_trace" || channel === "status");
}

function isModelWaitPlaceholderTimelineItem(item: PublicChatTimelineItem) {
  const itemId = cleanText(item.item_id);
  const sourceEventType = cleanText(item.source_event_type).toLowerCase();
  const statusKind = cleanText(item.status_kind || (item as { statusKind?: unknown }).statusKind).toLowerCase();
  const title = compactText(item.text || item.title || item.public_summary);
  return itemId.startsWith("model-wait:")
    || statusKind === "model_wait_placeholder"
    || (
      sourceEventType === "runtime_status"
      && statusKind === "public_stage_status"
      && (title === compactText("正在思考") || title === compactText("等待模型返回"))
    );
}

function modelFeedbackBodyText(item: PublicChatTimelineItem) {
  const main = cleanText(item.text || item.title || item.public_summary);
  const detail = cleanText(item.detail);
  if (!main) return detail;
  if (!detail || compactText(detail) === compactText(main)) return main;
  return `${main}\n\n${detail}`;
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

function compactText(value: unknown) {
  return cleanText(value).replace(/\s+/g, "").toLowerCase();
}

function sameCompactText(left: unknown, right: unknown) {
  const normalizedLeft = compactText(left);
  const normalizedRight = compactText(right);
  return Boolean(normalizedLeft && normalizedRight && normalizedLeft === normalizedRight);
}
