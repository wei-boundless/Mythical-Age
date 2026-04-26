"use client";

import { SendHorizonal } from "lucide-react";
import { useState } from "react";

import type { SearchPolicySource, SearchPolicyState } from "@/lib/store/types";

const SEARCH_POLICY_OPTIONS: Array<{
  id: SearchPolicySource;
  label: string;
}> = [
  { id: "rag", label: "启用知识库" },
  { id: "local_files", label: "启用本地权限" },
  { id: "web", label: "启用联网权限" }
];

export function ChatInput({
  disabled,
  onSend,
  onToggleSearchPolicy,
  searchPolicy
}: {
  disabled: boolean;
  onSend: (value: string) => Promise<void>;
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  searchPolicy: SearchPolicyState;
}) {
  const [value, setValue] = useState("");

  return (
    <div className="panel chat-input-panel rounded-[30px] p-4">
      <div className="archive-section-head mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="archive-section-head__eyebrow">Compose</p>
          <p className="chat-input-panel__note text-sm">输入问题并开始当前会话。</p>
        </div>
        <div className="chat-search-policy chat-search-policy--corner" aria-label="对话级搜索权限">
          {SEARCH_POLICY_OPTIONS.map((option) => {
            const enabled = searchPolicy[option.id];
            return (
              <button
                aria-pressed={enabled}
                className={enabled ? "chat-search-policy__item chat-search-policy__item--active" : "chat-search-policy__item"}
                key={option.id}
                onClick={() => onToggleSearchPolicy(option.id)}
                type="button"
              >
                <span>{option.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      <textarea
        className="chat-input-panel__textarea min-h-28 w-full resize-none rounded-[24px] px-4 py-4 text-[var(--color-text)] outline-none transition placeholder:text-[var(--color-text-soft)] focus:border-[var(--color-soul)] focus:ring-2 focus:ring-[var(--color-soul-soft)]"
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
      <div className="chat-input-panel__footer mt-3 flex items-center justify-between gap-3">
        <p className="chat-input-panel__hint text-sm">
          直接提问即可，本轮权限会约束可用来源。
        </p>
        <button
          className="action-button action-button--primary navbar-action-button disabled:cursor-not-allowed disabled:opacity-50"
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
