"use client";

import { FileText } from "lucide-react";
import React from "react";

export function RuntimeLogEntry({
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
