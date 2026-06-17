"use client";

import { Check, X } from "lucide-react";
import React from "react";

import type { ChatAttachment } from "@/lib/api";

import { MessageAttachments } from "./MessageAttachments";

type UserMessageProps = {
  attachments: ChatAttachment[];
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
          {content ? <span>{content}</span> : null}
          <MessageAttachments attachments={attachments} />
        </>
      )}
    </div>
  );
}
