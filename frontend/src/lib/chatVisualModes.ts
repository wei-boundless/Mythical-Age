import type { SoulKey } from "@/lib/souls";

export type ChatVisualMode = "default" | SoulKey;

export const SOUL_CHAT_VISUAL_MODES: SoulKey[] = ["hebo", "goumang", "siyue", "zhurong", "xuannv"];

export const CHAT_VISUAL_MODE_LABELS: Record<ChatVisualMode, string> = {
  default: "河伯",
  hebo: "河伯",
  goumang: "句芒",
  siyue: "四岳",
  zhurong: "祝融",
  xuannv: "玄女",
};

const CHAT_VISUAL_MODE_SET = new Set<ChatVisualMode>(["default", ...SOUL_CHAT_VISUAL_MODES]);

export function isChatVisualMode(value: string | null | undefined): value is ChatVisualMode {
  return Boolean(value && CHAT_VISUAL_MODE_SET.has(value as ChatVisualMode));
}

export function isSoulChatVisualMode(mode: ChatVisualMode): mode is SoulKey {
  return SOUL_CHAT_VISUAL_MODES.includes(mode as SoulKey);
}

export function normalizeChatVisualMode(value: string | null | undefined): ChatVisualMode {
  if (value === "default" || value === "reality") {
    return "hebo";
  }
  if (isChatVisualMode(value)) {
    return value;
  }
  return "hebo";
}
