"use client";

import { Pencil } from "lucide-react";
import React, { memo, useEffect, useMemo, useState } from "react";

import { AssistantMessage } from "@/components/chat/AssistantMessage";
import { PublicTimelineActivity, publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { RuntimeLogEntry } from "@/components/chat/RuntimeLogEntry";
import { UserMessage } from "@/components/chat/UserMessage";
import { orderedProjectionMessageBlocksFromView } from "@/components/chat/projectionMessageBlocks";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { ChronologicalProjectionView } from "@/lib/projection/chronological";
import type {
  RetrievalResult,
  ToolCall,
  ChatAttachment,
} from "@/lib/api";
import { shouldDisplayAssistantContent } from "@/lib/store/assistantContentVisibility";

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
  runtimeLogRef?: string;
  sourceTaskRunId?: string;
  sourceTurnRunId?: string;
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
};

function ChatMessageComponent({
  id,
  role,
  content,
  image,
  attachments = [],
  projectionView,
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
    () => publicTimelineHasDisplayableActivity(projectionBlocks),
    [projectionBlocks],
  );
  const renderProjectionTimeline =
    !isUser
    && !taskClosed
    && (
      projectionMode === "live"
      || projectionMode === "recovery"
      || (streamingContent && projectionBlocks.length > 0)
      || (!projectionBodyText && !assistantContentText && hasPublicTimelineActivity)
    );
  const baseDisplayContent = isUser
    ? content
    : taskClosed
      ? projectionBodyText || assistantContentText || closeoutText
      : projectionBodyText || assistantContentText;
  const messageDisplayContent = baseDisplayContent;
  const visibleMessageDisplayContent = messageDisplayContent;
  const projectionLogRef = projectionView?.logRef || runtimeLogRef;
  const projectionToolEventCount = projectionView?.toolEventCount ?? toolEventCount;
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || Boolean(visibleMessageDisplayContent.trim());
  const showThinkingPlaceholder =
    !isUser
    && streamingContent
    && !shouldRenderContent
    && !hasPublicTimelineActivity;
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
        image={image}
        imageUnavailable={imageUnavailable}
        key={key}
        onCopyReply={() => void copyReply()}
        onImageError={setFailedImageSrc}
        showCopy={showCopy}
        streamingContent={streamingContent}
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
              ariaLabel="运行状态"
              blocks={block.blocks}
              key={block.key}
            />
          )
      ))}
      {!isUser && taskClosed ? (
        <RuntimeLogEntry
          onOpen={onOpenRuntimeLog}
          runtimeLogRef={projectionLogRef}
          toolEventCount={projectionToolEventCount}
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
    && previous.runtimeLogRef === next.runtimeLogRef
    && previous.sourceTaskRunId === next.sourceTaskRunId
    && previous.sourceTurnRunId === next.sourceTurnRunId
    && previous.toolEventCount === next.toolEventCount
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
    && previous.onResendEdit === next.onResendEdit;
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
