"use client";

import { ArrowUp, BrainCircuit, Database, FolderLock, Globe2, Lightbulb, Square } from "lucide-react";
import { useMemo, useState } from "react";

import type { ModelProviderConfig, SoulImageAssetConfig, TaskOrderProjection } from "@/lib/api";
import type { MainAgentAssemblyMode, SearchPolicySource, SearchPolicyState, TaskSelectionState } from "@/lib/store/types";

const SEARCH_POLICY_OPTIONS: Array<{
  id: SearchPolicySource;
  label: string;
  title: string;
}> = [
  { id: "rag", label: "知识库", title: "启用知识库" },
  { id: "local_files", label: "本地", title: "启用本地权限" },
  { id: "web", label: "联网", title: "启用联网权限" }
];

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
  onToggleDeepSeekThinking,
  onToggleSearchPolicy,
  deepSeekThinkingEnabled,
  mainAgentAssemblyMode,
  searchPolicy,
  selectedChatModelId,
  taskSelection,
  taskOrderProjection,
}: {
  disabled: boolean;
  streaming: boolean;
  modelProviderConfig: ModelProviderConfig | null;
  soulImageAssetConfig: SoulImageAssetConfig | null;
  onSend: (value: string) => Promise<void>;
  onStop: () => void;
  onSelectChatModel: (selectionId: string) => void;
  onSelectMainAgentAssemblyMode: (mode: MainAgentAssemblyMode) => void;
  onToggleDeepSeekThinking: (enabled: boolean) => void;
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  deepSeekThinkingEnabled: boolean;
  mainAgentAssemblyMode: MainAgentAssemblyMode;
  searchPolicy: SearchPolicyState;
  selectedChatModelId: string;
  taskSelection: TaskSelectionState | null;
  taskOrderProjection: TaskOrderProjection | null;
}) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const modelOptions = useMemo(() => buildChatModelOptions(modelProviderConfig, soulImageAssetConfig), [modelProviderConfig, soulImageAssetConfig]);
  const inputDisabled = disabled || submitting;
  const activeModelId = modelOptions.some((option) => option.id === selectedChatModelId)
    ? selectedChatModelId
    : "system-default";
  const activeModel = resolveActiveChatModel(activeModelId, modelProviderConfig);
  const showDeepSeekThinkingToggle = activeModel?.provider === "deepseek"
    && !activeModel.model.toLowerCase().includes("image");
  const selectionLabel = taskSelection?.label?.trim()
    || taskSelection?.selected_task_id?.trim()
    || "";
  const order = taskOrderProjection?.task_order ?? null;
  const run = taskOrderProjection?.task_order_run ?? null;
  const orderId = order && typeof order === "object" ? String(order.order_id ?? "") : "";
  const runId = run && typeof run === "object" ? String(run.run_id ?? "") : "";
  const submit = async () => {
    const nextValue = value.trim();
    if (inputDisabled || !nextValue) {
      return;
    }
    setSubmitting(true);
    try {
      await onSend(nextValue);
      setValue("");
    } catch (error) {
      console.error("Failed to send chat message", error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="chat-input-panel chat-input-panel--inline">
      {taskSelection ? (
        <div className="chat-task-selection-bar">
          <div className="chat-task-selection-bar__content">
            <span className="chat-task-selection-bar__eyebrow">{orderId ? "任务订单" : "当前承接"}</span>
            <strong>特定任务 · {selectionLabel}</strong>
            {orderId || runId ? <small>{[orderId, runId].filter(Boolean).join(" / ")}</small> : null}
          </div>
        </div>
      ) : null}
      <div className="chat-input-panel__composer">
        <div className="chat-control-cluster chat-control-cluster--scope">
          <div className="chat-search-policy chat-search-policy--compact" aria-label="本轮能力权限">
            {SEARCH_POLICY_OPTIONS.map((option) => {
              const enabled = searchPolicy[option.id];
              return (
                <button
                  aria-pressed={enabled}
                  className={enabled ? "chat-search-policy__item chat-search-policy__item--active" : "chat-search-policy__item"}
                  key={option.id}
                  onClick={() => onToggleSearchPolicy(option.id)}
                  title={option.title}
                  type="button"
                >
                  {searchPolicyIcon(option.id)}
                  <span>{option.label}</span>
                </button>
              );
            })}
          </div>
        </div>
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
            {showDeepSeekThinkingToggle ? (
              <button
                aria-label="DeepSeek 思考模式"
                aria-pressed={deepSeekThinkingEnabled}
                className={deepSeekThinkingEnabled ? "chat-thinking-toggle chat-thinking-toggle--active" : "chat-thinking-toggle"}
                disabled={inputDisabled}
                onClick={() => onToggleDeepSeekThinking(!deepSeekThinkingEnabled)}
                title="DeepSeek 思考模式"
                type="button"
              >
                <Lightbulb size={15} />
              </button>
            ) : null}
          </div>
          <div className="chat-control-cluster chat-control-cluster--mode">
            <span className="chat-control-cluster__name">模式</span>
            <label className="chat-mode-select">
              <select
                aria-label="选择主 Agent 模式"
                disabled={inputDisabled}
                onChange={(event) => onSelectMainAgentAssemblyMode(event.target.value as MainAgentAssemblyMode)}
                value={mainAgentAssemblyMode}
              >
                {MAIN_AGENT_MODE_ORDER.map((mode) => {
                  return (
                    <option key={mode} value={mode}>
                      {MAIN_AGENT_MODE_LABELS[mode]}
                    </option>
                  );
                })}
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

function searchPolicyIcon(source: SearchPolicySource) {
  if (source === "rag") return <Database size={13} />;
  if (source === "local_files") return <FolderLock size={13} />;
  return <Globe2 size={13} />;
}
