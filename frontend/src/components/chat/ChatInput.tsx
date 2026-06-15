"use client";

import { ArrowUp, BrainCircuit, ImagePlus, Radio, ShieldCheck, Square, X } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";

import type { ModelProviderConfig, ImageAssetConfig } from "@/lib/api";
import type { ChatThinkingMode } from "@/lib/store/types";

export type ChatPrimaryTaskAction = {
  kind: "stop_task";
  onAction: () => Promise<void> | void;
};

export function ChatInput({
  disabled,
  streaming,
  taskPrimaryAction,
  modelProviderConfig,
  imageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onSelectPermissionMode,
  onSelectStreamDisplayEnabled,
  onSelectThinkingMode,
  chatThinkingMode,
  chatStreamDisplayEnabled,
  permissionMode,
  supportedPermissionModes,
  selectedChatModelId,
}: {
  disabled: boolean;
  streaming: boolean;
  taskPrimaryAction?: ChatPrimaryTaskAction | null;
  modelProviderConfig: ModelProviderConfig | null;
  imageAssetConfig: ImageAssetConfig | null;
  onSend: (value: string, options?: { files?: File[] }) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectPermissionMode: (mode: string) => Promise<void> | void;
  onSelectStreamDisplayEnabled: (enabled: boolean) => void;
  onSelectThinkingMode: (mode: ChatThinkingMode) => void;
  chatThinkingMode: ChatThinkingMode;
  chatStreamDisplayEnabled: boolean;
  permissionMode: string;
  supportedPermissionModes: string[];
  selectedChatModelId: string;
}) {
  const [value, setValue] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, imageAssetConfig), [modelProviderConfig, imageAssetConfig]);
  const inputDisabled = disabled || (submitting && !streaming);
  const trimmedValue = value.trim();
  const hasSelectedFiles = selectedFiles.length > 0;
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
  const permissionOptions = useMemo(
    () => buildPermissionModeOptions(supportedPermissionModes),
    [supportedPermissionModes]
  );
  const activePermissionMode = permissionOptions.some((option) => option.value === permissionMode)
    ? permissionMode
    : permissionOptions[0]?.value ?? "default";
  const activeModelModeValue = encodeChatModelModeSelection(activeModelId, activeThinkingMode);
  const panelClassName = `chat-input-panel chat-input-panel--inline${streaming ? " chat-input-panel--streaming" : ""}`;
  const primaryAction = trimmedValue || hasSelectedFiles
    ? "send"
    : streaming
      ? "stop_stream"
      : taskPrimaryAction?.kind ?? "send";
  const primaryDisabled = primaryAction === "stop_stream"
    ? false
    : primaryAction === "send"
      ? inputDisabled || (!trimmedValue && !hasSelectedFiles)
      : disabled || submitting;
  const primaryLabel = primaryAction === "stop_stream"
    ? "停止本轮生成"
    : primaryAction === "stop_task"
      ? "停止当前任务"
      : "发送";
  const primaryButtonClassName = [
    "chat-send-button",
    primaryAction === "stop_stream" || primaryAction === "stop_task" ? "chat-stop-button chat-send-button--stop" : "",
  ].filter(Boolean).join(" ");
  const streamToggleTitle = streaming
    ? "本轮运行中，下一轮可切换流式显示"
    : chatStreamDisplayEnabled
      ? "流式显示已开启"
      : "流式显示已关闭";

  useEffect(() => {
    if (!activeModelSupportsReasoning && chatThinkingMode !== "normal") {
      onSelectThinkingMode("normal");
    }
  }, [activeModelSupportsReasoning, chatThinkingMode, onSelectThinkingMode]);

  const submit = async () => {
    const nextValue = value.trim();
    const nextFiles = selectedFiles;
    if (inputDisabled || (!nextValue && !nextFiles.length)) {
      return;
    }
    setSubmitting(true);
    setValue("");
    setSelectedFiles([]);
    try {
      await onSend(nextValue, nextFiles.length ? { files: nextFiles } : undefined);
    } catch (error) {
      console.error("Failed to send chat message", error);
      setValue(nextValue);
      setSelectedFiles(nextFiles);
    } finally {
      setSubmitting(false);
    }
  };

  const pasteImages = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (disabled || submitting || streaming) {
      return;
    }
    const pastedImages = imageFilesFromClipboard(event.clipboardData);
    if (!pastedImages.length) {
      return;
    }
    const pastedText = event.clipboardData.getData("text/plain").trim();
    if (!pastedText) {
      event.preventDefault();
    }
    setSelectedFiles((current) => [...current, ...pastedImages].slice(0, 8));
  };

  const runTaskPrimaryAction = async () => {
    if (!taskPrimaryAction || submitting || disabled) {
      return;
    }
    setSubmitting(true);
    try {
      await taskPrimaryAction.onAction();
    } catch (error) {
      console.error("Failed to run chat task action", error);
    } finally {
      setSubmitting(false);
    }
  };

  const runPrimaryAction = async () => {
    if (primaryAction === "stop_stream") {
      onStop();
      return;
    }
    if (primaryAction === "stop_task") {
      await runTaskPrimaryAction();
      return;
    }
    await submit();
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
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              void runPrimaryAction();
            }
          }}
          onPaste={pasteImages}
          placeholder="输入任务、修改或继续说明"
          value={value}
        />
      </div>
      {selectedFiles.length ? (
        <div className="chat-attachment-strip" aria-label="已选择图片">
          {selectedFiles.map((file, index) => (
            <span className="chat-attachment-chip" key={`${file.name}-${file.size}-${index}`} title={file.name}>
              <span className="chat-attachment-chip__name">{file.name}</span>
              <span className="chat-attachment-chip__meta">{formatFileSize(file.size)}</span>
              <button
                aria-label={`移除 ${file.name}`}
                className="chat-attachment-chip__remove"
                disabled={submitting}
                onClick={() => setSelectedFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                title="移除"
                type="button"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
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
          <div className="chat-control-cluster chat-control-cluster--permission">
            <label className="chat-model-select chat-model-select--permission">
              <ShieldCheck size={15} />
              <select
                aria-label="选择运行权限模式"
                disabled={disabled || permissionOptions.length <= 1}
                onChange={(event) => {
                  void Promise.resolve(onSelectPermissionMode(event.target.value)).catch((error) => {
                    console.error("Failed to update permission mode", error);
                  });
                }}
                value={activePermissionMode}
              >
                {permissionOptions.map((option) => (
                  <option key={option.value} title={option.title} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="chat-control-cluster chat-control-cluster--stream">
            <button
              aria-label={chatStreamDisplayEnabled ? "关闭流式显示" : "开启流式显示"}
              aria-pressed={chatStreamDisplayEnabled}
              className={`chat-stream-toggle${chatStreamDisplayEnabled ? " chat-stream-toggle--active" : ""}`}
              disabled={disabled || streaming}
              onClick={() => onSelectStreamDisplayEnabled(!chatStreamDisplayEnabled)}
              title={streamToggleTitle}
              type="button"
            >
              <Radio size={14} />
              <span>流式</span>
            </button>
          </div>
        </div>
        <div className="chat-input-panel__actions">
          <input
            accept=".png,.jpg,.jpeg,.webp,.bmp,.tiff,.tif,image/png,image/jpeg,image/webp,image/bmp,image/tiff"
            aria-label="选择图片"
            className="chat-attachment-input"
            disabled={disabled || submitting || streaming}
            multiple
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              setSelectedFiles((current) => [...current, ...files].slice(0, 8));
              event.currentTarget.value = "";
            }}
            ref={fileInputRef}
            type="file"
          />
          <button
            aria-label="上传图片"
            className="chat-attachment-button"
            disabled={disabled || submitting || streaming}
            onClick={() => fileInputRef.current?.click()}
            title={streaming ? "本轮运行结束后可上传图片" : "上传图片"}
            type="button"
          >
            <ImagePlus size={16} />
          </button>
          <button
            aria-label={primaryLabel}
            className={`${primaryButtonClassName} disabled:cursor-not-allowed disabled:opacity-50`}
            disabled={primaryDisabled}
            onClick={() => void runPrimaryAction()}
            title={primaryLabel}
            type="button"
          >
            {primaryAction === "stop_stream" || primaryAction === "stop_task" ? (
              <Square size={15} />
            ) : (
              <ArrowUp size={18} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatFileSize(size: number) {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${Math.max(0, size)} B`;
}

function imageFilesFromClipboard(data: DataTransfer) {
  const directFiles = Array.from(data.files ?? [])
    .filter((file) => file.type.startsWith("image/"))
    .map((file, index) => normalizeClipboardImageFile(file, index));
  if (directFiles.length) {
    return directFiles;
  }
  return Array.from(data.items ?? [])
    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
    .map((item, index) => item.getAsFile() ? normalizeClipboardImageFile(item.getAsFile() as File, index) : null)
    .filter((file): file is File => Boolean(file));
}

function normalizeClipboardImageFile(file: File, index: number) {
  const suffix = fileExtensionFromMime(file.type);
  const hasImageName = /\.(png|jpe?g|webp|bmp|tiff?|tif)$/i.test(file.name);
  if (hasImageName) {
    return file;
  }
  const timestamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  return new File([file], `pasted-image-${timestamp}-${index + 1}${suffix}`, {
    type: file.type || "image/png",
    lastModified: file.lastModified || Date.now(),
  });
}

function fileExtensionFromMime(mimeType: string) {
  switch (mimeType.toLowerCase()) {
    case "image/jpeg":
      return ".jpg";
    case "image/webp":
      return ".webp";
    case "image/bmp":
      return ".bmp";
    case "image/tiff":
      return ".tiff";
    case "image/png":
    default:
      return ".png";
  }
}

function buildPermissionModeOptions(supportedModes: string[]) {
  const normalized = supportedModes.map((mode) => mode.trim()).filter(Boolean);
  const modes = normalized.length ? normalized : ["default", "plan", "accept_edits", "bypass", "full_access"];
  return modes.map((mode) => ({
    value: mode,
    label: permissionModeLabel(mode),
    title: permissionModeTitle(mode),
  }));
}

function permissionModeLabel(mode: string) {
  switch (mode) {
    case "default":
      return "标准";
    case "plan":
      return "计划";
    case "accept_edits":
      return "自动编辑";
    case "bypass":
      return "旁路";
    case "full_access":
      return "全权限";
    default:
      return mode;
  }
}

function permissionModeTitle(mode: string) {
  switch (mode) {
    case "full_access":
      return "使用已授予的完整运行权限";
    case "accept_edits":
      return "自动允许文件编辑类操作";
    case "plan":
      return "偏只读规划模式";
    case "bypass":
      return "旁路默认确认策略";
    default:
      return "标准运行权限模式";
  }
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
