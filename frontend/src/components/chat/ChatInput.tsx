"use client";

import { ArrowUp, BrainCircuit, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ModelProviderConfig, ImageAssetConfig } from "@/lib/api";
import type { ChatThinkingMode } from "@/lib/store/types";

export function ChatInput({
  disabled,
  streaming,
  modelProviderConfig,
  imageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onSelectThinkingMode,
  chatThinkingMode,
  selectedChatModelId,
}: {
  disabled: boolean;
  streaming: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  imageAssetConfig: ImageAssetConfig | null;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectThinkingMode: (mode: ChatThinkingMode) => void;
  chatThinkingMode: ChatThinkingMode;
  selectedChatModelId: string;
}) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, imageAssetConfig), [modelProviderConfig, imageAssetConfig]);
  const inputDisabled = disabled || submitting;
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";
  const activeModel = resolveActiveChatModel(activeModelId, modelProviderConfig);
  const activeModelSupportsReasoning = Boolean(activeModel && supportsHiddenReasoning(activeModel.provider, activeModel.model, modelProviderConfig));
  const activeThinkingMode = activeModelSupportsReasoning ? chatThinkingMode : "normal";
  const modelModeOptions = useMemo(
    () => buildChatModelModeOptions(modelOptions, modelProviderConfig),
    [modelOptions, modelProviderConfig]
  );
  const activeModelModeValue = encodeChatModelModeSelection(activeModelId, activeThinkingMode);
  const panelClassName = `chat-input-panel chat-input-panel--inline${streaming ? " chat-input-panel--streaming" : ""}`;

  useEffect(() => {
    if (!activeModelSupportsReasoning && chatThinkingMode !== "normal") {
      onSelectThinkingMode("normal");
    }
  }, [activeModelSupportsReasoning, chatThinkingMode, onSelectThinkingMode]);

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
    <div className={panelClassName}>
      <div className="chat-input-panel__composer">
        <textarea
          aria-label="输入消息"
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
          placeholder="输入任务、修改或继续说明"
          value={value}
        />
      </div>
      <div className="chat-input-panel__footer">
        <div className="chat-input-panel__controls">
          <div className="chat-control-cluster chat-control-cluster--model">
            <span className="chat-control-cluster__name">模型</span>
            <label className="chat-model-select chat-model-select--compound">
              <BrainCircuit size={16} />
              <select
                aria-label="选择本轮模型和模式"
                disabled={inputDisabled || modelModeOptions.length <= 1}
                onChange={(event) => {
                  const selection = decodeChatModelModeSelection(event.target.value);
                  onSelectChatModel(selection.modelId);
                  onSelectThinkingMode(selection.thinkingMode);
                }}
                value={activeModelModeValue}
              >
                {modelModeOptions.map((option) => (
                  <option key={option.value} title={option.title} value={option.value}>
                    {option.label}
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

function buildChatModelOptions(config: ModelProviderConfig | null, imageConfig: ImageAssetConfig | null) {
  const systemLabel = config?.provider && config?.model
    ? config.model
    : "系统默认模型";
  const options: Array<{ id: string; label: string }> = [{ id: "system-default", label: systemLabel }];
  if (config?.provider) {
    const provider = String(config.provider || "").trim().toLowerCase();
    const activeModel = String(config.model || "").trim();
    const providerOption = providerCatalogOption(config, provider);
    const presets = providerOption?.model_presets || [];
    presets.forEach((model) => {
      const modelId = String(model || "").trim();
      if (!modelId || modelId === activeModel) {
        return;
      }
      addConfiguredModelOption(options, {
        id: `${provider}::${modelId}`,
        label: modelId,
        baseUrl: config.base_url || providerOption?.default_base_url,
      });
    });
  }
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

function buildChatModelModeOptions(
  modelOptions: Array<{ id: string; label: string }>,
  config: ModelProviderConfig | null
) {
  return modelOptions.flatMap((option) => {
    const model = resolveActiveChatModel(option.id, config);
    const supportsReasoning = Boolean(model && supportsHiddenReasoning(model.provider, model.model, config));
    const modeOptions = supportsReasoning ? THINKING_MODE_OPTIONS : [THINKING_MODE_OPTIONS[0]];
    return modeOptions.map((mode) => ({
      value: encodeChatModelModeSelection(option.id, mode.value),
      label: supportsReasoning ? `${option.label} · ${mode.label}` : option.label,
      title: supportsReasoning ? mode.title : "使用标准调用模式",
    }));
  });
}

function addConfiguredModelOption(
  options: Array<{ id: string; label: string }>,
  item: { id?: string; label?: string; baseUrl?: string | null }
) {
  const id = String(item.id || "").trim();
  const label = String(item.label || "").trim();
  const baseUrl = String(item.baseUrl || "").trim();
  if (!id || !label || !baseUrl || options.some((option) => option.id === id || option.label === label)) {
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

const THINKING_MODE_OPTIONS: Array<{ value: ChatThinkingMode; label: string; title: string }> = [
  { value: "normal", label: "标准", title: "关闭 Thinking" },
  { value: "thinking", label: "Thinking", title: "开启 Thinking，推理强度由 DeepSeek 自动调度" },
];

const MODEL_MODE_SEPARATOR = "::mode::";

function encodeChatModelModeSelection(modelId: string, thinkingMode: ChatThinkingMode) {
  return `${encodeURIComponent(modelId)}${MODEL_MODE_SEPARATOR}${thinkingMode}`;
}

function decodeChatModelModeSelection(value: string): { modelId: string; thinkingMode: ChatThinkingMode } {
  const [encodedModelId, rawThinkingMode] = value.split(MODEL_MODE_SEPARATOR);
  const modelId = decodeURIComponent(encodedModelId || "system-default");
  return {
    modelId,
    thinkingMode: isChatThinkingMode(rawThinkingMode) ? rawThinkingMode : "normal",
  };
}

function isChatThinkingMode(value: string | undefined): value is ChatThinkingMode {
  return value === "normal" || value === "thinking";
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

