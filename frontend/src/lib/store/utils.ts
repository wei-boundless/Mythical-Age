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

function historyMessageId(message: SessionHistory["messages"][number], sourceIndex: number) {
  const explicit = String(message.id ?? message.message_id ?? "").trim();
  if (explicit) {
    return explicit;
  }
  const turnId = String(message.turn_id ?? "").trim();
  if (turnId) {
    return `history-message:${turnId}:${message.role}`;
  }
  return `history-message:${sourceIndex}`;
}

function attachmentTurnIndex(anchorTurnId: string) {
  const parts = String(anchorTurnId || "").split(":");
  const tail = parts.at(-1) || "";
  const parsed = Number(tail);
  return Number.isFinite(parsed) ? parsed : 0;
}

function runtimeAttachmentsByAssistantMessageId(
  history: SessionHistory["messages"],
  attachments: SessionRuntimeAttachment[],
) {
  const buckets = new Map<string, SessionRuntimeAttachment[]>();
  const assistantRefs = history
    .map((message, index) => message.role === "assistant"
      ? { index, id: historyMessageId(message, index) }
      : null)
    .filter((item): item is { index: number; id: string } => Boolean(item));

  for (const attachment of attachments) {
    const explicitMessageId = String(attachment.anchor_message_id ?? "").trim();
    const assistantRef = explicitMessageId
      ? assistantRefs.find((item) => item.id === explicitMessageId)
      : null;
    const fallbackRef = (() => {
      const anchorIndex = attachmentTurnIndex(attachment.anchor_turn_id);
      if (anchorIndex > 0) {
        return assistantRefs.find((item) => item.index >= anchorIndex) ?? null;
      }
      return assistantRefs.at(-1) ?? null;
    })();
    const targetId = assistantRef?.id ?? (!explicitMessageId ? fallbackRef?.id : "");
    if (!targetId) {
      continue;
    }
    const existing = buckets.get(targetId) ?? [];
    buckets.set(targetId, [...existing, attachment]);
  }
  return buckets;
}

function syntheticAssistantMessagesForRuntimeAttachments(
  history: SessionHistory["messages"],
  attachments: SessionRuntimeAttachment[],
  existingAssistantIds: Set<string>,
) {
  const syntheticById = new Map<string, Message>();
  for (const attachment of attachments) {
    const explicitMessageId = String(attachment.anchor_message_id ?? "").trim();
    const anchorTurnId = String(attachment.anchor_turn_id ?? "").trim();
    const syntheticId = explicitMessageId || (anchorTurnId ? `history-message:${anchorTurnId}:assistant` : "");
    if (!syntheticId || existingAssistantIds.has(syntheticId)) {
      continue;
    }
    const hasVisibleRuntime = Boolean(
      attachment.task_projection
      || attachment.public_timeline?.length
      || attachment.progress_entries?.length
      || String(attachment.summary ?? "").trim()
      || String(attachment.latest_public_progress_note ?? attachment.latest_step_summary ?? "").trim()
    );
    if (!hasVisibleRuntime) {
      continue;
    }
    const anchorIndex = history.findIndex((message) =>
      message.role === "user" && String(message.turn_id ?? "").trim() === anchorTurnId
    );
    const sourceIndex = anchorIndex >= 0
      ? anchorIndex + 0.5
      : attachmentTurnIndex(anchorTurnId) + 0.5;
    const existing = syntheticById.get(syntheticId);
    syntheticById.set(syntheticId, {
      id: syntheticId,
      role: "assistant",
      content: "",
      toolCalls: [],
      retrievals: [],
      sourceIndex,
      runtimeAttachments: existing
        ? [...(existing.runtimeAttachments ?? []), attachment]
        : [attachment],
    });
  }
  return [...syntheticById.values()];
}

export function toUiMessages(history: SessionHistory["messages"], runtimeAttachments: SessionRuntimeAttachment[] = []) {
  const attachmentsByAssistantId = runtimeAttachmentsByAssistantMessageId(history, runtimeAttachments);
  const normalized = history
    .map<Message | null>((message, sourceIndex) => {
      if (message.role !== "user" && message.role !== "assistant") {
        return null;
      }
      const toolCalls = (message.tool_calls ?? [])
        .map(sanitizeToolCall)
        .filter((toolCall): toolCall is ToolCall => Boolean(toolCall));
      if (message.role === "assistant" && toolCalls.length > 0) {
        return null;
      }
      const content = message.content ?? "";
      if (message.role === "assistant" && looksLikeSkillDocument(content) && toolCalls.length === 0) {
        return null;
      }
      if (message.role === "assistant" && !content.trim() && toolCalls.length === 0) {
        return null;
      }
      return {
        id: historyMessageId(message, sourceIndex),
        role: message.role,
        content,
        toolCalls,
        retrievals: [],
        sourceIndex,
        answerChannel: message.answer_channel,
        answerSource: message.answer_source,
        answerCanonicalState: message.answer_canonical_state,
        answerPersistPolicy: message.answer_persist_policy,
        answerFinalizationPolicy: message.answer_finalization_policy,
        answerFallbackReason: message.answer_fallback_reason,
        answerSelectedChannel: message.answer_selected_channel,
        answerSelectedSource: message.answer_selected_source,
        answerLeakFlags: Array.isArray(message.answer_leak_flags)
          ? message.answer_leak_flags.map((item) => String(item ?? "").trim()).filter(Boolean)
          : undefined,
        image: message.image ?? null,
        runtimeAttachments: attachmentsByAssistantId.get(historyMessageId(message, sourceIndex)) ?? []
      };
    })
    .filter(Boolean) as Message[];
  const existingAssistantIds = new Set(normalized
    .filter((message) => message.role === "assistant")
    .map((message) => message.id));
  const syntheticRuntimeMessages = syntheticAssistantMessagesForRuntimeAttachments(
    history,
    runtimeAttachments,
    existingAssistantIds,
  );
  const ordered = [...normalized, ...syntheticRuntimeMessages].sort((left, right) => {
    const leftIndex = left.sourceIndex ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = right.sourceIndex ?? Number.MAX_SAFE_INTEGER;
    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }
    if (left.role !== right.role) {
      return left.role === "user" ? -1 : 1;
    }
    return left.id.localeCompare(right.id);
  });

  const merged: Message[] = [];
  for (const message of ordered) {
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
