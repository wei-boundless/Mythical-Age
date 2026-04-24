"use client";

import { CornerDownLeft, SendHorizonal } from "lucide-react";
import { useState } from "react";

export function ChatInput({
  disabled,
  onSend
}: {
  disabled: boolean;
  onSend: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");

  return (
    <div className="panel rounded-[30px] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="section-kicker">Compose</p>
          <p className="text-sm text-[var(--color-text-soft)]">输入问题并开始当前会话。</p>
        </div>
        <div className="status-pill">
          <CornerDownLeft size={14} />
          Cmd/Ctrl + Enter
        </div>
      </div>
      <textarea
        className="min-h-28 w-full resize-none rounded-[24px] border border-[var(--color-border)] bg-[var(--color-panel-strong)] px-4 py-4 text-[var(--color-text)] outline-none transition placeholder:text-[var(--color-text-soft)] focus:border-[var(--color-soul)] focus:ring-2 focus:ring-[var(--color-soul-soft)]"
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (disabled) {
            return;
          }
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            const nextValue = value.trim();
            if (!nextValue) {
              return;
            }
            void onSend(nextValue);
            setValue("");
          }
        }}
        placeholder="输入你的问题，Cmd/Ctrl + Enter 发送"
        value={value}
      />
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-sm text-[var(--color-text-soft)]">
          直接提问即可，支持工具调用、检索和流式响应。
        </p>
        <button
          className="action-button action-button--primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={disabled || !value.trim()}
          onClick={() => {
            const nextValue = value.trim();
            if (!nextValue) {
              return;
            }
            void onSend(nextValue);
            setValue("");
          }}
          type="button"
        >
          <SendHorizonal size={16} />
          发送
        </button>
      </div>
    </div>
  );
}
