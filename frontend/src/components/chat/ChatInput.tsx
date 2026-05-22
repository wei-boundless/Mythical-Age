"use client";

import { ArrowUp, BrainCircuit, Square } from "lucide-react";
import { useMemo, useState } from "react";

import type { ModelProviderConfig, SoulImageAssetConfig } from "@/lib/api";
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
  modelProviderConfig,
  soulImageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onToggleSearchPolicy,
  searchPolicy,
  selectedChatModelId,
  taskSelection,
  onClearTaskSelection,
}: {
  disabled: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  soulImageAssetConfig: SoulImageAssetConfig | null;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  searchPolicy: SearchPolicyState;
  selectedChatModelId: string;
  taskSelection: TaskSelectionState | null;
  onClearTaskSelection: () => void;
}) {
  const [value, setValue] = useState("");
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, soulImageAssetConfig), [modelProviderConfig, soulImageAssetConfig]);
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";

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
        <div className="chat-input-panel__controls">
          <label className="chat-model-select">
            <BrainCircuit size={15} />
            <select
              aria-label="选择本轮模型"
              disabled={disabled || modelOptions.length <= 1}
              onChange={(event) => onSelectChatModel(event.target.value)}
              value={activeModelId}
            >
              {modelOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
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
            aria-label="发送"
            className="chat-send-button disabled:cursor-not-allowed disabled:opacity-50"
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
            <ArrowUp size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}

function buildChatModelOptions(config: ModelProviderConfig | null, imageConfig: SoulImageAssetConfig | null) {
  const systemLabel = config?.provider && config?.model
    ? `系统默认 · ${config.provider}/${config.model}`
    : "系统默认模型";
  const options = [{ id: "system-default", label: systemLabel }];
  const providers = Object.keys(config?.provider_catalog?.providers ?? {}).length
    ? config?.provider_catalog?.providers ?? {}
    : FALLBACK_CHAT_MODEL_PROVIDERS;
  for (const provider of Object.values(providers)) {
    if (!provider.default_base_url || !String(provider.default_base_url).trim()) {
      continue;
    }
    const presets = provider.model_presets?.length ? provider.model_presets : [provider.default_model];
    for (const model of presets) {
      const normalizedModel = String(model || "").trim();
      if (!normalizedModel) {
        continue;
      }
      const id = `${provider.provider}::${normalizedModel}`;
      if (options.some((option) => option.id === id)) {
        continue;
      }
      const label = `${provider.display_name || provider.provider} · ${normalizedModel}`;
      options.push({ id, label });
    }
  }
  if (imageConfig?.configured && imageConfig.base_url && imageConfig.model) {
    const imageId = `openai::${imageConfig.model}`;
    if (!options.some((option) => option.id === imageId)) {
      options.push({
        id: imageId,
        label: `OpenAI · ${imageConfig.model}（生图）`
      });
    }
  }
  return options;
}

const FALLBACK_CHAT_MODEL_PROVIDERS = {
  deepseek: {
    provider: "deepseek",
    display_name: "DeepSeek",
    default_model: "deepseek-v4-pro",
    model_presets: ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat"],
  },
  openai: {
    provider: "openai",
    display_name: "OpenAI",
    default_model: "gpt-4.1-mini",
    model_presets: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
  },
  bailian: {
    provider: "bailian",
    display_name: "Qwen",
    default_model: "qwen3.5-plus",
    model_presets: ["qwen3.5-plus", "qwen-plus", "qwen-max"],
  },
};
