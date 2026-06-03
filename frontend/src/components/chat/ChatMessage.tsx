"use client";

import { AlertTriangle, Check, CircleCheck, Copy, Database, Pencil, ShieldCheck, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { hasPublicRunActivity, PublicRunActivity } from "@/components/chat/PublicRunActivity";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import type { PublicChatTimelineItem, RetrievalResult, SessionRuntimeAttachment, ToolCall } from "@/lib/api";
import { mergePublicTimelineItems, publicTimelineTerminalStateFromAnswer } from "@/lib/store/publicTimeline";
import type { RuntimeProgressEntry } from "@/lib/store/types";

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
  answerFinalizationPolicy,
  answerFallbackReason,
  answerSelectedChannel,
  answerSelectedSource,
  answerLeakFlags,
  answerSource,
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
  const baseDisplayContent = isUser ? content : assistantDisplayContent({ content, answerChannel, answerSource });
  const publicTimelineItems = isUser
    ? []
    : mergedPublicTimelineItems(
      runtimeAttachments,
      runtimePublicTimelineDraft,
      publicTimelineTerminalStateFromAnswer({ answerCanonicalState, answerChannel }),
    );
  const displayContent = isUser
    ? baseDisplayContent
    : assistantContentFromTimeline(baseDisplayContent, publicTimelineItems);
  const hasRunActivity = !isUser && hasPublicRunActivity(publicTimelineItems, displayContent);
  const legacyTaskContractReceipt = !isUser && isLegacyTaskContractReceipt({ content, answerChannel, answerSource });
  const hideLegacyTaskContractReceipt = legacyTaskContractReceipt && hasRunActivity;
  const boundary = {
    channel: answerChannel,
    canonicalState: answerCanonicalState,
    persistPolicy: answerPersistPolicy,
    finalizationPolicy: answerFinalizationPolicy,
    fallbackReason: answerFallbackReason,
    selectedChannel: answerSelectedChannel,
    selectedSource: answerSelectedSource,
    leakFlags: answerLeakFlags,
  };
  const shouldRenderContent =
    isUser
    || Boolean(image?.src)
    || imageUnavailable
    || (!hideLegacyTaskContractReceipt && (Boolean(displayContent.trim()) || !hasRunActivity));
  const copyableReplyText = !isUser && shouldRenderContent ? displayContent.trim() : "";
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
              {displayContent || "正在思考..."}
            </ReactMarkdown>
          )}
        </div>
      ) : null}
      {hasRunActivity ? (
        <PublicRunActivity items={publicTimelineItems} assistantContent={displayContent} />
      ) : null}
      {!isUser ? <OutputBoundaryStatus {...boundary} /> : null}
    </article>
  );
}

function editFailureMessage(error: unknown) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || "改写发送失败。";
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
    Array.isArray(attachment.public_timeline) ? attachment.public_timeline : [],
  );
  return mergePublicTimelineItems(persisted, runtimePublicTimelineDraft, { terminalState });
}

function assistantContentFromTimeline(content: string, items: PublicChatTimelineItem[]) {
  const normalized = String(content || "").trim();
  if (normalized) {
    return content;
  }
  const feedback = [...items].reverse().find((item) => String(item.kind || "").trim() === "assistant_text");
  const text = cleanBoundaryText(feedback?.text || feedback?.detail || feedback?.title);
  return text || content;
}

function cleanBoundaryText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function boundaryLabel(state: string, persistPolicy: string, channel: string) {
  if (state === "stable_answer" && persistPolicy === "persist_canonical") return "稳定答案";
  if (state === "tool_summary") return "工具摘要";
  if (state === "progress_only" || persistPolicy === "persist_debug_only") {
    if (channel === "task_control") return "任务控制消息";
    if (channel === "ask_user") return "等待补充";
    if (channel === "active_work_control") return "当前工作控制";
    if (channel === "blocked") return "运行受阻";
    return "过程状态";
  }
  if (state === "missing_answer" || persistPolicy === "do_not_persist") return "未形成稳定答案";
  if (state) return state.replace(/_/g, " ");
  return "";
}

function shouldShowBoundaryStatus(state: string, persistPolicy: string, leakFlags: string[], fallbackReason: string) {
  if (!state && !persistPolicy && !leakFlags.length && !fallbackReason) return false;
  const actionableLeaks = leakFlags.filter((flag) => !isRoutineBoundaryLeakFlag(flag));
  const routineFallback = fallbackReason.endsWith("_message") || fallbackReason === "task_executor_scheduled";
  if (actionableLeaks.length > 0) return true;
  if (fallbackReason && !routineFallback) return true;
  if (state === "missing_answer" || persistPolicy === "do_not_persist") return true;
  return false;
}

function isRoutineBoundaryLeakFlag(flag: string) {
  return flag === "internal_protocol_final_text"
    || flag === "inline_pseudo_tool_call_final_text"
    || flag.endsWith("_final_text");
}

function OutputBoundaryStatus({
  channel,
  canonicalState,
  persistPolicy,
  fallbackReason,
  selectedChannel,
  leakFlags,
}: {
  channel?: string;
  canonicalState?: string;
  persistPolicy?: string;
  finalizationPolicy?: string;
  fallbackReason?: string;
  selectedChannel?: string;
  selectedSource?: string;
  leakFlags?: string[];
}) {
  const state = cleanBoundaryText(canonicalState);
  const persist = cleanBoundaryText(persistPolicy);
  const answerChannel = cleanBoundaryText(channel);
  const selected = cleanBoundaryText(selectedChannel);
  const reason = cleanBoundaryText(fallbackReason);
  const leaks = Array.isArray(leakFlags)
    ? leakFlags.map(cleanBoundaryText).filter((flag) => flag && !isRoutineBoundaryLeakFlag(flag))
    : [];
  if (!shouldShowBoundaryStatus(state, persist, leaks, reason)) {
    return null;
  }
  const tone = state === "missing_answer" || persist === "do_not_persist"
    ? "warning"
    : state === "progress_only" || persist === "persist_debug_only"
      ? "debug"
      : "clean";
  const Icon = tone === "warning" ? AlertTriangle : persist === "persist_canonical" ? CircleCheck : Database;
  return (
    <div className={`output-boundary-status output-boundary-status--${tone}`} aria-label="输出状态">
      <span className="output-boundary-status__icon" aria-hidden="true">
        <Icon size={13} />
      </span>
      <span className="output-boundary-status__main">
        <strong>{boundaryLabel(state, persist, answerChannel)}</strong>
        <small>{persist === "persist_canonical" ? "可写入记忆" : "不写入长期记忆"}</small>
      </span>
      {selected && selected !== answerChannel ? (
        <code>{selected}</code>
      ) : null}
      {leaks.length ? (
        <span className="output-boundary-status__flag">
          <ShieldCheck size={12} />
          已清理内部协议
        </span>
      ) : null}
      {reason && reason !== answerChannel ? <small className="output-boundary-status__reason">{reason}</small> : null}
    </div>
  );
}

function assistantDisplayContent({
  content,
  answerChannel,
  answerSource,
}: {
  content: string;
  answerChannel?: string;
  answerSource?: string;
}) {
  const normalized = String(content || "").trim();
  const source = String(answerSource || "");
  const legacyToolLoop =
    source.includes("single_agent_turn.tool_loop")
    || normalized.includes("本轮工具观察次数已达到上限")
    || normalized.includes("连续检查了几次仍没有形成可靠结论");
  if (!legacyToolLoop) {
    return content;
  }
  if (String(answerChannel || "") === "blocked" || source.includes("tool_loop")) {
    return "我刚才连续检查了几次，但没有拿到足够的新信息。现在应该基于已有事实收口说明，或等你指定要重点核查的位置。";
  }
  return content;
}

function isLegacyTaskContractReceipt({
  content,
  answerChannel,
  answerSource,
}: {
  content: string;
  answerChannel?: string;
  answerSource?: string;
}) {
  void answerChannel;
  void answerSource;
  const normalized = String(content || "").trim();
  return (
    normalized.startsWith("我会按这个目标推进")
    || normalized.startsWith("我会按这个合同继续推进")
    || normalized.startsWith("后续进展会汇总在当前会话")
  );
}
