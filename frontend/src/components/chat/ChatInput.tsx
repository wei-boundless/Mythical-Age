"use client";

import { ArrowUp, BrainCircuit, Square } from "lucide-react";
import { useMemo, useState } from "react";

import type { ModelProviderConfig, SoulImageAssetConfig } from "@/lib/api";
import { MAIN_AGENT_ASSEMBLY_MODES } from "@/lib/mainAgentAssemblyModes";
import type { MainAgentAssemblyMode, SearchPolicySource, SearchPolicyState, TaskSelectionState } from "@/lib/store/types";

const SEARCH_POLICY_OPTIONS: Array<{
  id: SearchPolicySource;
  label: string;
}> = [
  { id: "rag", label: "启用知识库" },
  { id: "local_files", label: "启用本地权限" },
  { id: "web", label: "启用联网权限" }
];

const MAIN_AGENT_MODE_ORDER: MainAgentAssemblyMode[] = ["role", "standard", "professional"];

export function ChatInput({
  disabled,
  modelProviderConfig,
  soulImageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onSelectMainAgentAssemblyMode,
  onToggleSearchPolicy,
  mainAgentAssemblyMode,
  searchPolicy,
  selectedChatModelId,
  taskSelection,
}: {
  disabled: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  soulImageAssetConfig: SoulImageAssetConfig | null;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectMainAgentAssemblyMode: (mode: MainAgentAssemblyMode) => void;
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  mainAgentAssemblyMode: MainAgentAssemblyMode;
  searchPolicy: SearchPolicyState;
  selectedChatModelId: string;
  taskSelection: TaskSelectionState | null;
}) {
  const [value, setValue] = useState("");
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, soulImageAssetConfig), [modelProviderConfig, soulImageAssetConfig]);
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";

  const selectionLabel = taskSelection?.label?.trim()
    || taskSelection?.selected_task_id?.trim()
    || "";

  return (
    <div className="chat-input-panel chat-input-panel--inline">
      {taskSelection ? (
        <div className="chat-task-selection-bar">
          <div className="chat-task-selection-bar__content">
            <span className="chat-task-selection-bar__eyebrow">当前承接</span>
            <strong>特定任务 · {selectionLabel}</strong>
          </div>
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
          <div className="chat-main-agent-mode" aria-label="主 Agent 装配模式">
            {MAIN_AGENT_MODE_ORDER.map((mode) => {
              const option = MAIN_AGENT_ASSEMBLY_MODES[mode];
              const active = mainAgentAssemblyMode === mode;
              return (
                <button
                  aria-pressed={active}
                  className={active ? "chat-main-agent-mode__item chat-main-agent-mode__item--active" : "chat-main-agent-mode__item"}
                  disabled={disabled}
                  key={mode}
                  onClick={() => onSelectMainAgentAssemblyMode(mode)}
                  type="button"
                >
                  <span>{option.label}</span>
                </button>
              );
            })}
          </div>
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
  addConfiguredModelOption(options, {
    id: config?.provider && config?.model ? `${config.provider}::${config.model}` : "",
    label: config?.provider && config?.model ? `${providerDisplayName(config, config.provider)} · ${config.model}` : "",
    baseUrl: config?.base_url,
  });
  addConfiguredModelOption(options, {
    id: config?.fallback_provider && config?.fallback_model ? `${config.fallback_provider}::${config.fallback_model}` : "",
    label: config?.fallback_provider && config?.fallback_model ? `${providerDisplayName(config, config.fallback_provider)} · ${config.fallback_model}（备用）` : "",
    baseUrl: config?.fallback_base_url,
  });
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

function addConfiguredModelOption(
  options: Array<{ id: string; label: string }>,
  item: { id?: string; label?: string; baseUrl?: string | null }
) {
  const id = String(item.id || "").trim();
  const label = String(item.label || "").trim();
  const baseUrl = String(item.baseUrl || "").trim();
  if (!id || !label || !baseUrl || options.some((option) => option.id === id)) {
    return;
  }
  options.push({ id, label });
}

function providerDisplayName(config: ModelProviderConfig | null, provider: string) {
  return config?.provider_catalog?.providers?.[provider]?.display_name
    || config?.supported_providers?.[provider]?.display_name
    || provider;
}
