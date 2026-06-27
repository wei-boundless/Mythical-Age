"use client";

import { ArrowUp, ChevronDown, ChevronUp, Eye, EyeOff, FileText, ImagePlus, ListChecks, Plus, Square, Target, X } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";

import type { ModelProviderConfig, ImageAssetConfig } from "@/lib/api";
import type { ChatThinkingMode } from "@/lib/store/types";

import {
  createLongTextCompactionModel,
  LONG_TEXT_COMPACTION_PROFILES,
  resolveLongTextCompactionMode,
  type LongTextDraftIntent,
  type LongTextCompactionMode,
} from "./longTextCompact";

export function ChatInput({
  disabled,
  streaming,
  modelProviderConfig,
  imageAssetConfig,
  onSend,
  onStop,
  onSelectChatModel,
  onSelectPermissionMode,
  onSelectThinkingMode,
  onSelectThinkingProjectionEnabled = () => undefined,
  chatThinkingMode,
  thinkingProjectionEnabled = true,
  permissionMode,
  supportedPermissionModes,
  selectedChatModelId,
}: {
  disabled: boolean;
  streaming: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  imageAssetConfig: ImageAssetConfig | null;
  onSend: (value: string, options?: { files?: File[] }) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectPermissionMode: (mode: string) => Promise<void> | void;
  onSelectThinkingMode: (mode: ChatThinkingMode) => void;
  onSelectThinkingProjectionEnabled?: (enabled: boolean) => void;
  chatThinkingMode: ChatThinkingMode;
  thinkingProjectionEnabled?: boolean;
  permissionMode: string;
  supportedPermissionModes: string[];
  selectedChatModelId: string;
}) {
  const [value, setValue] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [draftMode, setDraftMode] = useState<LongTextCompactionMode>("expanded");
  const [quickMenuOpen, setQuickMenuOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const quickMenuRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingDraftIntentRef = useRef<LongTextDraftIntent | null>(null);
  const focusExpandedDraftRef = useRef(false);
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, imageAssetConfig), [modelProviderConfig, imageAssetConfig]);
  const inputDisabled = disabled || (submitting && !streaming);
  const trimmedValue = value.trim();
  const draftCompaction = useMemo(
    () => createLongTextCompactionModel(value, LONG_TEXT_COMPACTION_PROFILES.composer),
    [value],
  );
  const draftCompacted = draftCompaction.shouldCompact && draftMode === "compact";
  const hasSelectedFiles = selectedFiles.length > 0;
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";
  const activeModel = resolveActiveChatModel(activeModelId, modelProviderConfig);
  const activeModelSupportsReasoning = Boolean(activeModel && supportsHiddenReasoning(activeModel.provider, activeModel.model, modelProviderConfig));
  const activeThinkingMode = activeModelSupportsReasoning ? chatThinkingMode : "normal";
  const showThinkingProjectionControl = activeModelSupportsReasoning && activeThinkingMode === "thinking";
  const activeThinkingProjectionEnabled = showThinkingProjectionControl && thinkingProjectionEnabled;
  const thinkingProjectionToggleDisabled = inputDisabled || !showThinkingProjectionControl;
  const thinkingProjectionToggleTitle = activeThinkingProjectionEnabled
    ? "隐藏模型思考窗口"
    : "显示模型思考窗口";
  const thinkingModeTitle = activeModelSupportsReasoning
    ? "选择本轮思考模式"
    : "当前模型不支持思考模式";
  const quickMenuDisabled = inputDisabled || streaming;
  const permissionOptions = useMemo(
    () => buildPermissionModeOptions(supportedPermissionModes),
    [supportedPermissionModes]
  );
  const activePermissionMode = permissionOptions.some((option) => option.value === permissionMode)
    ? permissionMode
    : permissionOptions[0]?.value ?? "default";
  const panelClassName = [
    "chat-input-panel chat-input-panel--inline",
    streaming ? "chat-input-panel--streaming" : "",
    draftCompacted ? "chat-input-panel--draft-compact" : "",
  ].filter(Boolean).join(" ");
  const primaryAction = streaming ? "stop_stream" : "send";
  const primaryDisabled = primaryAction === "stop_stream"
    ? false
    : inputDisabled || (!trimmedValue && !hasSelectedFiles);
  const primaryLabel = primaryAction === "stop_stream"
    ? "停止本轮生成"
    : "发送";
  const primaryButtonClassName = [
    "chat-send-button",
    primaryAction === "stop_stream" ? "chat-stop-button chat-send-button--stop" : "",
  ].filter(Boolean).join(" ");

  useEffect(() => {
    if (!activeModelSupportsReasoning && chatThinkingMode !== "normal") {
      onSelectThinkingMode("normal");
    }
  }, [activeModelSupportsReasoning, chatThinkingMode, onSelectThinkingMode]);

  useEffect(() => {
    if (!draftCompaction.shouldCompact && draftMode !== "expanded") {
      setDraftMode("expanded");
    }
  }, [draftCompaction.shouldCompact, draftMode]);

  useEffect(() => {
    if (draftMode !== "expanded" || !focusExpandedDraftRef.current) {
      return;
    }
    focusExpandedDraftRef.current = false;
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }, [draftMode]);

  useEffect(() => {
    if (!quickMenuOpen || typeof document === "undefined") {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const menu = quickMenuRef.current;
      if (!menu || !(event.target instanceof Node) || menu.contains(event.target)) {
        return;
      }
      setQuickMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setQuickMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [quickMenuOpen]);

  useEffect(() => {
    if (quickMenuOpen && quickMenuDisabled) {
      setQuickMenuOpen(false);
    }
  }, [quickMenuDisabled, quickMenuOpen]);

  const submit = async () => {
    const nextValue = value.trim();
    const nextFiles = selectedFiles;
    if (inputDisabled || (!nextValue && !nextFiles.length)) {
      return;
    }
    setSubmitting(true);
    setValue("");
    setDraftMode("expanded");
    setSelectedFiles([]);
    try {
      await onSend(nextValue, nextFiles.length ? { files: nextFiles } : undefined);
    } catch (error) {
      console.error("Failed to send chat message", error);
      setValue(nextValue);
      setDraftMode((currentMode) => resolveLongTextCompactionMode({
        content: nextValue,
        currentMode,
        intent: "restore",
      }));
      setSelectedFiles(nextFiles);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDraftChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const nextValue = event.target.value;
    const intent = pendingDraftIntentRef.current ?? "type";
    pendingDraftIntentRef.current = null;
    setValue(nextValue);
    setDraftMode((currentMode) => resolveLongTextCompactionMode({
      content: nextValue,
      currentMode,
      intent,
    }));
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (disabled || submitting || streaming) {
      return;
    }
    const pastedText = event.clipboardData.getData("text/plain");
    if (pastedText) {
      pendingDraftIntentRef.current = "paste";
    }
    const pastedImages = imageFilesFromClipboard(event.clipboardData);
    if (!pastedImages.length) {
      return;
    }
    if (!pastedText.trim()) {
      event.preventDefault();
    }
    setSelectedFiles((current) => [...current, ...pastedImages].slice(0, 8));
  };

  const runPrimaryAction = async () => {
    if (primaryAction === "stop_stream") {
      onStop();
      return;
    }
    await submit();
  };

  const runTaskModeShortcut = async (mode: TaskModeShortcut) => {
    if (inputDisabled || streaming) {
      return;
    }
    setQuickMenuOpen(false);
    const nextValue = value.trim();
    const nextFiles = selectedFiles;
    const command = taskModeSlashCommand(mode, nextValue);
    setSubmitting(true);
    setValue("");
    setDraftMode("expanded");
    setSelectedFiles([]);
    try {
      await onSend(command, nextFiles.length ? { files: nextFiles } : undefined);
    } catch (error) {
      console.error("Failed to start task mode", error);
      setValue(nextValue);
      setDraftMode((currentMode) => resolveLongTextCompactionMode({
        content: nextValue,
        currentMode,
        intent: "restore",
      }));
      setSelectedFiles(nextFiles);
    } finally {
      setSubmitting(false);
    }
  };

  const handleComposerShortcut = (event: React.KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void runPrimaryAction();
    }
  };

  const expandDraft = () => {
    focusExpandedDraftRef.current = true;
    setDraftMode((currentMode) => resolveLongTextCompactionMode({
      content: value,
      currentMode,
      intent: "expand",
    }));
  };

  return (
    <div className={panelClassName}>
      <div className="chat-input-panel__composer">
        {draftCompacted ? (
          <div aria-label="已压缩的长输入" className="chat-input-panel__draft-compact" role="group">
            <button
              aria-label={`展开编辑完整输入，当前 ${draftCompaction.metricLabel}`}
              className="chat-input-panel__draft-compact-main"
              disabled={inputDisabled}
              onClick={expandDraft}
              onKeyDown={handleComposerShortcut}
              title={`${draftCompaction.title}，点击展开编辑`}
              type="button"
            >
              <FileText aria-hidden="true" size={15} />
              <span className="chat-input-panel__draft-compact-preview">{draftCompaction.preview}</span>
              <span className="chat-input-panel__draft-compact-count">{draftCompaction.metricLabel}</span>
              <ChevronDown aria-hidden="true" size={15} />
            </button>
            <button
              aria-label="清空输入"
              className="chat-input-panel__draft-compact-clear"
              disabled={inputDisabled}
              onClick={() => {
                setValue("");
                setDraftMode("expanded");
                pendingDraftIntentRef.current = null;
              }}
              title="清空输入"
              type="button"
            >
              <X size={14} />
            </button>
          </div>
        ) : (
          <>
            <textarea
              aria-label="输入消息"
              className="chat-input-panel__textarea"
              disabled={inputDisabled}
              onChange={handleDraftChange}
              onKeyDown={handleComposerShortcut}
              onPaste={handlePaste}
              placeholder="输入任务、修改或继续说明"
              ref={textareaRef}
              value={value}
            />
            {draftCompaction.shouldCompact && draftMode === "expanded" ? (
              <div className="chat-input-panel__draft-expanded-tools" aria-label="长输入操作">
                <span>{draftCompaction.metricLabel}</span>
                <button
                  onClick={() => setDraftMode((currentMode) => resolveLongTextCompactionMode({
                    content: value,
                    currentMode,
                    intent: "collapse",
                  }))}
                  type="button"
                >
                  <ChevronUp size={13} />
                  收起预览
                </button>
              </div>
            ) : null}
          </>
        )}
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
          <div className={`chat-more-actions${quickMenuOpen ? " chat-more-actions--open" : ""}`} ref={quickMenuRef}>
            <button
              aria-expanded={quickMenuOpen}
              aria-haspopup="menu"
              aria-label="打开附加操作"
              className="chat-more-actions__trigger"
              disabled={quickMenuDisabled}
              onClick={() => setQuickMenuOpen((open) => !open)}
              title="命令与附件"
              type="button"
            >
              <Plus size={17} />
            </button>
            {quickMenuOpen ? (
              <div className="chat-more-actions__menu" role="menu" aria-label="附加操作">
                <div className="chat-more-actions__section">
                  <span className="chat-more-actions__section-label">任务命令</span>
                  {TASK_MODE_SHORTCUTS.map((item) => (
                    <button
                      aria-label={`开启 ${item.label} Mode`}
                      className="chat-more-actions__item"
                      disabled={quickMenuDisabled}
                      key={item.mode}
                      onClick={() => void runTaskModeShortcut(item.mode)}
                      role="menuitem"
                      title={item.title}
                      type="button"
                    >
                      <item.icon aria-hidden="true" size={15} />
                      <span>
                        <strong>{item.label}</strong>
                        <small>{item.description}</small>
                      </span>
                    </button>
                  ))}
                </div>
                <div className="chat-more-actions__section">
                  <span className="chat-more-actions__section-label">附件</span>
                  <button
                    aria-label="上传图片"
                    className="chat-more-actions__item"
                    disabled={disabled || submitting || streaming}
                    onClick={() => {
                      setQuickMenuOpen(false);
                      fileInputRef.current?.click();
                    }}
                    role="menuitem"
                    title={streaming ? "本轮运行结束后可上传图片" : "上传图片"}
                    type="button"
                  >
                    <ImagePlus aria-hidden="true" size={15} />
                    <span>
                      <strong>添加图片</strong>
                      <small>支持截图、照片和粘贴图片</small>
                    </span>
                  </button>
                </div>
              </div>
            ) : null}
          </div>
          <div
            className={`chat-runtime-controls${showThinkingProjectionControl ? " chat-runtime-controls--with-projection" : " chat-runtime-controls--without-projection"}`}
            aria-label="本轮运行设置"
          >
            <label className="chat-model-select chat-runtime-select chat-runtime-select--model" title="选择本轮模型">
              <span className="chat-runtime-control__label">模型</span>
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
            <label
              className={`chat-model-select chat-runtime-select chat-runtime-select--thinking${activeModelSupportsReasoning ? "" : " chat-runtime-select--disabled"}`}
              title={thinkingModeTitle}
            >
              <select
                aria-label="选择思考模式"
                disabled={inputDisabled || !activeModelSupportsReasoning}
                onChange={(event) => onSelectThinkingMode(event.target.value as ChatThinkingMode)}
                value={activeThinkingMode}
              >
                {THINKING_MODE_OPTIONS.map((option) => (
                  <option key={option.value} title={option.title} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            {showThinkingProjectionControl ? (
              <button
                aria-label={activeThinkingProjectionEnabled ? "隐藏模型思考窗口" : "显示模型思考窗口"}
                aria-pressed={activeThinkingProjectionEnabled}
                className={`chat-thinking-projection-toggle${activeThinkingProjectionEnabled ? " chat-thinking-projection-toggle--on" : ""}`}
                disabled={thinkingProjectionToggleDisabled}
                onClick={() => onSelectThinkingProjectionEnabled(!thinkingProjectionEnabled)}
                title={thinkingProjectionToggleTitle}
                type="button"
              >
                {activeThinkingProjectionEnabled ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            ) : null}
            <label className="chat-model-select chat-runtime-select chat-runtime-select--permission">
              <span className="chat-runtime-control__label">权限</span>
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
        </div>
        <div className="chat-input-panel__actions">
          <button
            aria-label={primaryLabel}
            className={`${primaryButtonClassName} disabled:cursor-not-allowed disabled:opacity-50`}
            disabled={primaryDisabled}
            onClick={() => void runPrimaryAction()}
            title={primaryLabel}
            type="button"
          >
            {primaryAction === "stop_stream" ? (
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

type TaskModeShortcut = "goal" | "plan" | "todo";

const TASK_MODE_SHORTCUTS: Array<{
  mode: TaskModeShortcut;
  label: string;
  title: string;
  description: string;
  icon: typeof Target;
}> = [
  { mode: "goal", label: "Goal", title: "通过 /task goal 开启 Goal Mode", description: "建立持续目标", icon: Target },
  { mode: "plan", label: "Plan", title: "通过 /task plan 开启 Plan Mode", description: "进入计划审阅", icon: FileText },
  { mode: "todo", label: "Todo", title: "通过 /task todo 开启 Todo Mode", description: "生成任务清单", icon: ListChecks },
];

function taskModeSlashCommand(mode: TaskModeShortcut, body: string) {
  const text = body.trim();
  return text ? `/task ${mode} ${text}` : `/task ${mode}`;
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
    : "系统默认";
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
  { value: "normal", label: "标准", title: "标准回复，不额外开启 Thinking" },
  { value: "thinking", label: "思考", title: "开启 Thinking，适合复杂任务" },
];

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
