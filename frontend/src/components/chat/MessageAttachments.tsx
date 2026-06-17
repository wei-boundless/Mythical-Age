"use client";

import { FileText } from "lucide-react";
import React from "react";

import type { ChatAttachment } from "@/lib/api";

export function MessageAttachments({ attachments }: { attachments: ChatAttachment[] }) {
  if (!attachments.length) {
    return null;
  }
  return (
    <div className="chat-message-attachments" aria-label="图片附件">
      {attachments.map((attachment) => (
        <span
          className="chat-message-attachment"
          key={attachment.attachment_id || attachment.path}
          title={attachment.path}
        >
          <FileText size={13} />
          <span className="chat-message-attachment__name">{attachment.filename || "图片附件"}</span>
          {attachment.size_bytes ? (
            <span className="chat-message-attachment__meta">{formatAttachmentSize(attachment.size_bytes)}</span>
          ) : null}
        </span>
      ))}
    </div>
  );
}

function formatAttachmentSize(size: number) {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${Math.max(0, size)} B`;
}
