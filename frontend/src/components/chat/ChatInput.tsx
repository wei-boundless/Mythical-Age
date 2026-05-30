"use client";

import { ArrowUp, BrainCircuit, Lightbulb, Square } from "lucide-react";
import { useMemo, useState } from "react";

import type { ModelProviderConfig, SoulImageAssetConfig } from "@/lib/api";
import type { MainAgentAssemblyMode } from "@/lib/store/types";

const MAIN_AGENT_MODE_ORDER: MainAgentAssemblyMode[] = ["role", "standard", "professional"];
const MAIN_AGENT_MODE_LABELS: Record<MainAgentAssemblyMode, string> = {
  role: "角色模式",
  standard: "标准模式",
  professional: "专家模式",
};

export function ChatInput({
  disabled,
  streaming,
  modelProviderConfig,
  soulImageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onSelectMainAgentAssemblyMode,
  onToggleThinking,
  thinkingEnabled,
  mainAgentAssemblyMode,
  selectedChatModelId,
}: {
  disabled: boolean;
  streaming: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  soulImageAssetConfig: SoulImageAssetConfig | null;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectMainAgentAssemblyMode: (mode: MainAgentAssemblyMode) => void;
  onToggleThinking: (enabled: boolean) => void;
  thinkingEnabled: boolean;
  mainAgentAssemblyMode: MainAgentAssemblyMode;
  selectedChatModelId: string;
}) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, soulImageAssetConfig), [modelProviderConfig, soulImageAssetConfig]);
  const inputDisabled = disabled || submitting;
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";
  const activeModel = resolveActiveChatModel(activeModelId, modelProviderConfig);
  const showThinkingToggle = Boolean(activeModel && supportsHiddenReasoning(activeModel.provider, activeModel.model, modelProviderConfig));
  const submit = async () => {
    const nextValue = value.trim();
    if (inputDisabled || !nextValue) {
      return;
    }
    setSubmitting(true);
    setValue("");
    try {
      await onSend(nextValue);
    } catch (error) {
      console.error("Failed to send chat message", error);
      setValue(nextValue);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="chat-input-panel chat-input-panel--inline">
      <div className="chat-input-panel__composer">
        <textarea
          className="chat-input-panel__textarea"
          disabled={inputDisabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (inputDisabled) {
              return;
            }
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="输入消息，Cmd/Ctrl + Enter 发送"
          value={value}
        />
      </div>
      <div className="chat-input-panel__footer">
        <div className="chat-input-panel__controls">
          <div className="chat-control-cluster chat-control-cluster--model">
            <span className="chat-control-cluster__name">模型</span>
            <label className="chat-model-select">
              <BrainCircuit size={15} />
              <select
                aria-label="选择本轮模型"
                disabled={inputDisabled || modelOptions.length <= 1}
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
            {showThinkingToggle ? (
              <button
                aria-label="隐藏推理模式"
                aria-pressed={thinkingEnabled}
                className={thinkingEnabled ? "chat-thinking-toggle chat-thinking-toggle--active" : "chat-thinking-toggle"}
                disabled={inputDisabled}
                onClick={() => onToggleThinking(!thinkingEnabled)}
                title="隐藏推理模式"
                type="button"
              >
                <Lightbulb size={15} />
              </button>
            ) : null}
          </div>
          <div className="chat-control-cluster chat-control-cluster--mode">
            <label className="chat-mode-select">
              <select
                aria-label="选择主 Agent 模式"
                disabled={inputDisabled}
                onChange={(event) => onSelectMainAgentAssemblyMode(event.target.value as MainAgentAssemblyMode)}
                value={mainAgentAssemblyMode}
              >
                {MAIN_AGENT_MODE_ORDER.map((mode) => (
                  <option key={mode} value={mode}>
                    {MAIN_AGENT_MODE_LABELS[mode]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <div className="chat-input-panel__actions">
          {streaming ? (
            <button
              className="chat-stop-button"
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
            disabled={inputDisabled || !value.trim()}
            onClick={() => void submit()}
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
    ? config.model
    : "系统默认模型";
  const options = [{ id: "system-default", label: systemLabel }];
  addConfiguredModelOption(options, {
    id: config?.fallback_provider && config?.fallback_model ? `${config.fallback_provider}::${config.fallback_model}` : "",
    label: config?.fallback_provider && config?.fallback_model ? config.fallback_model : "",
    baseUrl: config?.fallback_base_url,
  });
  if (imageConfig?.configured && imageConfig.base_url && imageConfig.model) {
    const imageId = `openai::${imageConfig.model}`;
    if (!options.some((option) => option.id === imageId)) {
      options.push({
        id: imageId,
        label: imageConfig.model
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

function resolveActiveChatModel(selectionId: string, config: ModelProviderConfig | null) {
  if (!config) {
    return null;
  }
  if (selectionId === "system-default") {
    const provider = String(config.provider || "").trim().toLowerCase();
    const model = String(config.model || "").trim();
    return provider && model ? { provider, model } : null;
  }
  const [provider, ...modelParts] = selectionId.split("::");
  const normalizedProvider = provider.trim().toLowerCase();
  const model = modelParts.join("::").trim();
  return normalizedProvider && model ? { provider: normalizedProvider, model } : null;
}

function supportsHiddenReasoning(provider: string, model: string, config: ModelProviderConfig | null) {
  const normalizedProvider = provider.trim().toLowerCase();
  const normalizedModel = model.trim().toLowerCase();
  if (!normalizedProvider || !normalizedModel || normalizedModel.includes("image")) {
    return false;
  }
  if (!providerCapabilityTags(config, normalizedProvider).has("reasoning")) {
    return false;
  }
  if (normalizedProvider === "deepseek") {
    return true;
  }
  if (normalizedProvider === "openai") {
    return isOpenAIReasoningModel(normalizedModel);
  }
  return false;
}

function providerCapabilityTags(config: ModelProviderConfig | null, provider: string) {
  const option = providerCatalogOption(config, provider);
  return new Set((option?.capability_tags || []).map((tag) => String(tag || "").trim().toLowerCase()).filter(Boolean));
}

function providerCatalogOption(config: ModelProviderConfig | null, provider: string) {
  if (!config) {
    return undefined;
  }
  const normalizedProvider = provider.trim().toLowerCase();
  const providers = {
    ...(config.supported_providers || {}),
    ...(config.provider_catalog?.providers || {}),
  };
  return providers[provider]
    || providers[normalizedProvider]
    || Object.entries(providers).find(([key]) => key.trim().toLowerCase() === normalizedProvider)?.[1];
}

function isOpenAIReasoningModel(model: string) {
  const normalized = model.trim().toLowerCase();
  return normalized.startsWith("gpt-5")
    || normalized.startsWith("o1")
    || normalized.startsWith("o3")
    || normalized.startsWith("o4");
}
