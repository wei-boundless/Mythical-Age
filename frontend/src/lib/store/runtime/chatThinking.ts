import type { ChatThinkingMode } from "../types";

export function isOpenAIReasoningModel(model: string) {
  const normalized = model.trim().toLowerCase();
  return normalized.startsWith("gpt-5")
    || normalized.startsWith("o1")
    || normalized.startsWith("o3")
    || normalized.startsWith("o4");
}

export function normalizeChatThinkingMode(mode: ChatThinkingMode | string | null | undefined): ChatThinkingMode {
  return mode === "thinking" ? mode : "normal";
}

export function chatThinkingModeFromProviderConfig(config: { thinking_mode?: string; reasoning_effort?: string } | null): ChatThinkingMode {
  if (String(config?.thinking_mode || "").trim().toLowerCase() !== "enabled") {
    return "normal";
  }
  return "thinking";
}
