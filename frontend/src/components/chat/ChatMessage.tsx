"use client";

import { Pencil } from "lucide-react";
import React, { memo, useEffect, useMemo, useState } from "react";

import { AssistantMessage } from "@/components/chat/AssistantMessage";
import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { UserMessage } from "@/components/chat/UserMessage";
import { orderedProjectionMessageBlocksFromView } from "@/components/chat/projectionMessageBlocks";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { ChronologicalProjectionView, ProjectionRenderBlock } from "@/lib/projection/chronological";
import type {
  RetrievalResult,
  ToolCall,
  ChatAttachment,
} from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";

import { writeClipboardText } from "./clipboardText";

type ChatMessageProps = {
  id: string;
  role: "user" | "assistant";
  content: string;
  image?: {
    src: string;
    alt?: string;
    caption?: string;
  } | null;
  attachments?: ChatAttachment[];
  projectionView?: ChronologicalProjectionView;
  closeoutSummary?: string;
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
  compactUserLongText?: boolean;
  fileNameIndex?: Map<string, string>;
  hideInlineTodoPlans?: boolean;
  onOpenWorkspaceFile?: (path: string, options?: { lineNumber?: number }) => void;
  onResendEdit?: (messageId: string, value: string) => Promise<void>;
  workspaceRoot?: string;
};

function ChatMessageComponent({
  id,
  role,
  content,
  image,
  attachments = [],
  projectionView,
  closeoutSummary,
  answerChannel,
  answerCanonicalState,
  answerPersistPolicy,
  answerSource,
  answerLeakFlags,
  streamingContent = false,
  retrievals,
  canEdit = false,
  compactUserLongText = true,
  fileNameIndex,
  hideInlineTodoPlans = false,
  onOpenWorkspaceFile,
  onResendEdit,
  workspaceRoot
}: ChatMessageProps) {
  const isUser = role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);
  const [submittingEdit, setSubmittingEdit] = useState(false);
  const [editError, setEditError] = useState("");
  const [copiedReply, setCopiedReply] = useState(false);
  const [failedImageSrc, setFailedImageSrc] = useState("");
  const imageUnavailable = Boolean(image?.src && failedImageSrc === image.src);
  const projectionMode = projectionView?.displayMode ?? "";
  const taskClosed = projectionMode === "committed" || projectionMode === "closeout";
  const projectionBodyText = projectionView?.canonicalContent && !isInternalControlProtocolText(projectionView.canonicalContent)
    ? projectionView.canonicalContent
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
  const projectionBlocks = useMemo(
    () => isUser ? [] : projectionView?.blocks ?? [],
    [isUser, projectionView?.blocks],
  );
  const hasPublicTimelineActivity = useMemo(
    () => publicTimelineHasDisplayableActivity(projectionBlocks, { hideTodoPlans: hideInlineTodoPlans }),
    [hideInlineTodoPlans, projectionBlocks],
  );
  const hasAssistantAnchoredProjection = useMemo(
    () => projectionBlocks.some((block) => projectionBlockCanAnchorAssistantMessage(block, { hideTodoPlans: hideInlineTodoPlans })),
    [hideInlineTodoPlans, projectionBlocks],
  );
  const baseDisplayContent = isUser
    ? content
    : taskClosed
      ? projectionBodyText || assistantContentText || closeoutText
      : projectionBodyText || assistantContentText;
  const messageDisplayContent = baseDisplayContent;
  const visibleMessageDisplayContent = messageDisplayContent;
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || Boolean(visibleMessageDisplayContent.trim());
  const projectionCanRenderInAssistantMessage = shouldRenderContent || hasAssistantAnchoredProjection;
  const renderProjectionTimeline =
    !isUser
    && !taskClosed
    && projectionCanRenderInAssistantMessage
    && (
      projectionMode === "live"
      || projectionMode === "recovery"
      || (streamingContent && projectionBlocks.length > 0)
      || (!projectionBodyText && !assistantContentText && hasAssistantAnchoredProjection)
    );
  const renderClosedTimeline = hasPublicTimelineActivity && projectionCanRenderInAssistantMessage;
  const showThinkingPlaceholder =
    !isUser
    && streamingContent
    && !shouldRenderContent
    && !hasAssistantAnchoredProjection;
  const copyableReplyText = !isUser && shouldRenderContent ? visibleMessageDisplayContent.trim() : "";
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
    const displayText = bodyText ?? visibleMessageDisplayContent;
    const explicitBodyText = bodyText !== undefined;
    const renderableContent =
      isUser
      || (!explicitBodyText && Boolean(image?.src))
      || (!explicitBodyText && imageUnavailable)
      || Boolean(displayText.trim());
    if (!renderableContent) return null;
    return isUser ? (
      <UserMessage
        attachments={attachments}
        compactLongText={compactUserLongText}
        content={content}
        draft={draft}
        editing={editing}
        editError={editError}
        key={key}
        onCancelEdit={() => {
          setEditError("");
          setEditing(false);
        }}
        onDraftChange={(value) => {
          setDraft(value);
          setEditError("");
        }}
        onSubmitEdit={() => void submitEdit()}
        sendEditDisabled={sendEditDisabled}
        submittingEdit={submittingEdit}
      />
    ) : (
      <AssistantMessage
        copiedReply={copiedReply}
        copyableReplyText={copyableReplyText}
        displayText={displayText}
        explicitBodyText={explicitBodyText}
        fileNameIndex={fileNameIndex}
        image={image}
        imageUnavailable={imageUnavailable}
        key={key}
        onCopyReply={() => void copyReply()}
        onOpenWorkspaceFile={onOpenWorkspaceFile}
        onImageError={setFailedImageSrc}
        showCopy={showCopy}
        streamingContent={streamingContent}
        workspaceRoot={workspaceRoot}
      />
    );
  };
  const orderedMessageBlocks = useMemo(
    () => isUser || taskClosed || !renderProjectionTimeline
      ? []
      : orderedProjectionMessageBlocksFromView(projectionBlocks, {
        fallbackBodyText: visibleMessageDisplayContent,
        hasBody: shouldRenderContent,
      }),
    [
      isUser,
      projectionBlocks,
      renderProjectionTimeline,
      shouldRenderContent,
      taskClosed,
      visibleMessageDisplayContent,
    ],
  );
  const firstBodyBlockKey = orderedMessageBlocks.find((block) => block.kind === "body")?.key ?? "";
  const renderClosedMessage = () => (
    <>
      {renderClosedTimeline ? (
        <PublicTimelineActivity
          ariaLabel="收口前轨迹"
          blocks={projectionBlocks}
          hideTodoPlans={hideInlineTodoPlans}
        />
      ) : null}
      {renderMessageContent()}
    </>
  );
  const shouldRenderMessageShell =
    isUser
    || shouldRenderContent
    || renderProjectionTimeline
    || (taskClosed && renderClosedTimeline)
    || showThinkingPlaceholder
    || (!isUser && retrievals.length > 0);

  if (!shouldRenderMessageShell) {
    return null;
  }

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
      {isUser
        ? renderMessageContent()
        : taskClosed
          ? renderClosedMessage()
          : !renderProjectionTimeline
            ? renderMessageContent()
            : orderedMessageBlocks.map((block) => (
              block.kind === "body"
                ? renderMessageContent(block.key, block.text, block.key === firstBodyBlockKey)
                : (
                  <PublicTimelineActivity
                    ariaLabel="运行状态"
                    blocks={block.blocks}
                    hideTodoPlans={hideInlineTodoPlans}
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

export const ChatMessage = memo(ChatMessageComponent, areChatMessagePropsEqual);
ChatMessage.displayName = "ChatMessage";

function areChatMessagePropsEqual(previous: ChatMessageProps, next: ChatMessageProps) {
  return previous.id === next.id
    && previous.role === next.role
    && previous.content === next.content
    && previous.image === next.image
    && previous.attachments === next.attachments
    && previous.projectionView === next.projectionView
    && previous.closeoutSummary === next.closeoutSummary
    && previous.answerChannel === next.answerChannel
    && previous.answerCanonicalState === next.answerCanonicalState
    && previous.answerPersistPolicy === next.answerPersistPolicy
    && previous.answerFinalizationPolicy === next.answerFinalizationPolicy
    && previous.answerFallbackReason === next.answerFallbackReason
    && previous.answerSelectedChannel === next.answerSelectedChannel
    && previous.answerSelectedSource === next.answerSelectedSource
    && previous.answerLeakFlags === next.answerLeakFlags
    && previous.answerSource === next.answerSource
    && previous.streamingContent === next.streamingContent
    && previous.toolCalls === next.toolCalls
    && previous.retrievals === next.retrievals
    && previous.canEdit === next.canEdit
    && previous.compactUserLongText === next.compactUserLongText
    && previous.fileNameIndex === next.fileNameIndex
    && previous.hideInlineTodoPlans === next.hideInlineTodoPlans
    && previous.onOpenWorkspaceFile === next.onOpenWorkspaceFile
    && previous.onResendEdit === next.onResendEdit
    && previous.workspaceRoot === next.workspaceRoot;
}

function editFailureMessage(error: unknown) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || "改写没有发送成功。";
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

function projectionBlockCanAnchorAssistantMessage(
  block: ProjectionRenderBlock,
  options: { hideTodoPlans?: boolean } = {},
): boolean {
  if (block.kind === "body_segment") {
    return Boolean(cleanText(block.text)) && !isInternalControlProtocolText(block.text);
  }
  if (block.kind === "todo_plan") {
    return !options.hideTodoPlans;
  }
  if (block.kind === "tool_event") {
    return true;
  }
  if (block.kind === "activity_archive") {
    return block.blocks.some((child) => projectionBlockCanAnchorAssistantMessage(child, options));
  }
  return false;
}
