"use client";

import { SendHorizonal, Square } from "lucide-react";
import { useState } from "react";

import type { SearchPolicySource, SearchPolicyState, TaskSelectionState } from "@/lib/store/types";

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
  onStop,
  onToggleSearchPolicy,
  searchPolicy,
  taskSelection,
  onClearTaskSelection,
}: {
  disabled: boolean;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  searchPolicy: SearchPolicyState;
  taskSelection: TaskSelectionState | null;
  onClearTaskSelection: () => void;
}) {
  const [value, setValue] = useState("");

  const selectionLabel = taskSelection?.label?.trim()
    || taskSelection?.coordination_task_id?.trim()
    || taskSelection?.selected_task_id?.trim()
    || "";
  const selectionModeLabel = taskSelection?.mode === "coordination" ? "协调任务" : "特定任务";

  return (
    <div className="chat-input-panel chat-input-panel--inline">
      {taskSelection ? (
        <div className="chat-task-selection-bar">
          <div className="chat-task-selection-bar__content">
            <span className="chat-task-selection-bar__eyebrow">当前承接</span>
            <strong>{selectionModeLabel} · {selectionLabel}</strong>
          </div>
          <button className="chat-task-selection-bar__clear" onClick={onClearTaskSelection} type="button">
            清除
          </button>
        </div>
      ) : null}
      <div className="chat-input-panel__composer">
        <textarea
          className="chat-input-panel__textarea"
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
          placeholder="输入消息，Cmd/Ctrl + Enter 发送"
          value={value}
        />
      </div>
      <div className="chat-input-panel__footer">
        <div className="chat-search-policy chat-search-policy--compact" aria-label="本轮能力权限">
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
        <div className="chat-input-panel__actions">
          {disabled ? (
            <button
              className="action-button action-button--danger navbar-action-button"
              onClick={onStop}
              type="button"
            >
              <Square size={15} />
              停止
            </button>
          ) : null}
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
    </div>
  );
}
