"use client";

import { Check, ChevronDown, ChevronUp, Copy, FileText, X } from "lucide-react";
import React from "react";

import type { ChatAttachment } from "@/lib/api";

import { writeClipboardText } from "./clipboardText";
import {
  createLongTextCompactionModel,
  LONG_TEXT_COMPACTION_PROFILES,
} from "./longTextCompact";
import { MessageAttachments } from "./MessageAttachments";

type UserMessageProps = {
  attachments: ChatAttachment[];
  compactLongText?: boolean;
  content: string;
  draft: string;
  editing: boolean;
  editError: string;
  onCancelEdit: () => void;
  onDraftChange: (value: string) => void;
  onSubmitEdit: () => void;
  sendEditDisabled: boolean;
  submittingEdit: boolean;
};

export function UserMessage({
  attachments,
  compactLongText = true,
  content,
  draft,
  editing,
  editError,
  onCancelEdit,
  onDraftChange,
  onSubmitEdit,
  sendEditDisabled,
  submittingEdit,
}: UserMessageProps) {
  const [expanded, setExpanded] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const compaction = React.useMemo(
    () => createLongTextCompactionModel(content, LONG_TEXT_COMPACTION_PROFILES.userMessage),
    [content],
  );
  const compact = compactLongText && compaction.shouldCompact;

  React.useEffect(() => {
    setExpanded(false);
    setCopied(false);
  }, [content]);

  async function copyFullContent() {
    if (!content) return;
    await writeClipboardText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="chat-message-shell__content whitespace-pre-wrap leading-7">
      {editing ? (
        <div className="message-edit-form">
          <textarea
            className="message-edit-form__textarea"
            onChange={(event) => onDraftChange(event.target.value)}
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
              onClick={onCancelEdit}
              type="button"
            >
              <X size={14} />
              取消
            </button>
            <button
              className="message-edit-form__button message-edit-form__button--primary"
              disabled={sendEditDisabled}
              onClick={onSubmitEdit}
              type="button"
            >
              <Check size={14} />
              {submittingEdit ? "发送中" : "发送"}
            </button>
          </div>
        </div>
      ) : (
        <>
          {content ? compact && !expanded ? (
            <button
              aria-label={`展开完整用户消息，当前 ${compaction.metricLabel}`}
              className="user-message-compact-trigger"
              onClick={() => setExpanded(true)}
              title={`${compaction.title}，点击展开完整用户消息`}
              type="button"
            >
              <FileText aria-hidden="true" size={13} />
              <span>{compaction.preview}</span>
              <ChevronDown aria-hidden="true" size={14} />
            </button>
          ) : (
            <>
              <span className="user-message-full-text">{content}</span>
              {compact ? (
                <div className="user-message-long-actions" aria-label="长消息操作">
                  <button onClick={() => setExpanded(false)} type="button">
                    <ChevronUp size={13} />
                    收起
                  </button>
                  <button onClick={() => void copyFullContent()} type="button">
                    {copied ? <Check size={13} /> : <Copy size={13} />}
                    {copied ? "已复制" : "复制全文"}
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
          <MessageAttachments attachments={attachments} />
        </>
      )}
    </div>
  );
}
