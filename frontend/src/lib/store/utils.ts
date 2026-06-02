import { type ToolCall, type SessionHistory, type SessionRuntimeAttachment } from "@/lib/api";

import type { Message, SkillSummary } from "./types";

export const FIXED_FILES = [
  "durable_memory/index/MEMORY.md"
];

export function makeId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function appendMessageContent(base: string, extra: string) {
  if (!extra.trim()) {
    return base;
  }
  if (!base.trim()) {
    return extra;
  }
  return `${base}\n\n${extra}`;
}

export function isInternalSkillRead(toolCall: ToolCall) {
  const toolName = (toolCall.tool || "").toLowerCase();
  const io = `${toolCall.input ?? ""}\n${toolCall.output ?? ""}`.toLowerCase();
  return toolName === "read_file" && io.includes("/skills/") && io.includes("/skill.md");
}

export function looksLikeSkillDocument(text: string) {
  const normalized = (text || "").trim();
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase();
  const hasSkillFrontmatter =
    (normalized.startsWith("---") || lowered.startsWith("name:")) &&
    lowered.includes("metadata:") &&
    lowered.includes("description:");
  const hasSkillSections =
    lowered.includes("display_name:") &&
    (
      lowered.includes("## execution steps") ||
      lowered.includes("## output format") ||
      lowered.includes("目标") ||
      lowered.includes("执行步骤") ||
      lowered.includes("输出格式") ||
      lowered.includes("故障排查") ||
      lowered.includes("查询策略")
    );
  return hasSkillFrontmatter || hasSkillSections;
}

export function looksLikeSkillDocumentPrefix(text: string) {
  const normalized = (text || "").trim();
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase();
  return (
    lowered.startsWith("name:") ||
    lowered.startsWith("---") ||
    (lowered.includes("metadata:") && lowered.includes("description:"))
  );
}

export function sanitizeToolCall(toolCall: ToolCall): ToolCall | null {
  if (isInternalSkillRead(toolCall)) {
    return null;
  }

  const input = String(toolCall.input ?? "");
  const output = String(toolCall.output ?? "");
  const inputIsSkill = looksLikeSkillDocument(input);
  const outputIsSkill = looksLikeSkillDocument(output);

  if ((inputIsSkill && !output.trim()) || (inputIsSkill && outputIsSkill)) {
    return null;
  }

  return {
    ...toolCall,
    input: inputIsSkill ? "[internal skill instructions hidden]" : input,
    output: outputIsSkill ? "[internal skill instructions hidden]" : output
  };
}

function attachmentTurnIndex(anchorTurnId: string) {
  const parts = String(anchorTurnId || "").split(":");
  const tail = parts.at(-1) || "";
  const parsed = Number(tail);
  return Number.isFinite(parsed) ? parsed : 0;
}

function runtimeAttachmentsByAssistantIndex(
  history: SessionHistory["messages"],
  attachments: SessionRuntimeAttachment[],
) {
  const buckets = new Map<number, SessionRuntimeAttachment[]>();
  const assistantIndexes = history
    .map((message, index) => message.role === "assistant" ? index : -1)
    .filter((index) => index >= 0);

  for (const attachment of attachments) {
    const anchorIndex = attachmentTurnIndex(attachment.anchor_turn_id);
    const assistantIndex = assistantIndexes.find((index) => index >= anchorIndex) ?? assistantIndexes.at(-1);
    if (assistantIndex === undefined) {
      continue;
    }
    const existing = buckets.get(assistantIndex) ?? [];
    buckets.set(assistantIndex, [...existing, attachment]);
  }
  return buckets;
}

export function toUiMessages(history: SessionHistory["messages"], runtimeAttachments: SessionRuntimeAttachment[] = []) {
  const attachmentsByAssistantIndex = runtimeAttachmentsByAssistantIndex(history, runtimeAttachments);
  const normalized = history
    .map<Message | null>((message, sourceIndex) => {
      const toolCalls = (message.tool_calls ?? [])
        .map(sanitizeToolCall)
        .filter((toolCall): toolCall is ToolCall => Boolean(toolCall));
      const content = message.content ?? "";
      if (message.role === "assistant" && looksLikeSkillDocument(content) && toolCalls.length === 0) {
        return null;
      }
      if (message.role === "assistant" && !content.trim() && toolCalls.length === 0) {
        return null;
      }
      return {
        id: makeId(),
        role: message.role,
        content,
        toolCalls,
        retrievals: [],
        sourceIndex,
        answerChannel: message.answer_channel,
        answerSource: message.answer_source,
        image: message.image ?? null,
        runtimeAttachments: attachmentsByAssistantIndex.get(sourceIndex) ?? []
      };
    })
    .filter(Boolean) as Message[];

  const merged: Message[] = [];
  for (const message of normalized) {
    const previous = merged[merged.length - 1];
    const hasRuntimeAttachment = Boolean(message.runtimeAttachments?.length || previous?.runtimeAttachments?.length);
    const sameAnswerChannel = (message.answerChannel || "") === (previous?.answerChannel || "");
    if (message.role === "assistant" && previous?.role === "assistant" && !hasRuntimeAttachment && sameAnswerChannel) {
      previous.content = appendMessageContent(previous.content, message.content);
      previous.toolCalls = [...previous.toolCalls, ...message.toolCalls];
      previous.retrievals = [...previous.retrievals, ...message.retrievals];
      previous.image = previous.image ?? message.image ?? null;
      continue;
    }
    merged.push(message);
  }
  return merged;
}

export function buildEditableFiles(skills: SkillSummary[]) {
  return [...FIXED_FILES, ...skills.map((skill) => skill.path)];
}
