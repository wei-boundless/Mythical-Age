import { type ToolCall, type SessionHistory, type SessionRuntimeAttachment } from "@/lib/api";
import { isInternalActiveWorkControlText } from "@/lib/internalControlText";

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

function historyTurnId(message: SessionHistory["messages"][number]) {
  const record = message as SessionHistory["messages"][number] & {
    anchor_turn_id?: unknown;
    turn_ref?: unknown;
  };
  return String(message.turn_id ?? record.turn_ref ?? record.anchor_turn_id ?? "").trim();
}

function historyTaskRunId(message: SessionHistory["messages"][number]) {
  const record = message as SessionHistory["messages"][number] & {
    task_run_id?: unknown;
    source_task_run_id?: unknown;
  };
  return String(record.task_run_id ?? record.source_task_run_id ?? "").trim();
}

function runtimeAttachmentsByAssistantMessageId(
  history: SessionHistory["messages"],
  attachments: SessionRuntimeAttachment[],
) {
  const buckets = new Map<string, SessionRuntimeAttachment[]>();
  const assistantRefs = history
    .map((message, index) => message.role === "assistant"
      ? { index, id: historyMessageId(message, index), turnId: historyTurnId(message), taskRunId: historyTaskRunId(message) }
      : null)
    .filter((item): item is { index: number; id: string; turnId: string; taskRunId: string } => Boolean(item));

  for (const attachment of attachments) {
    const explicitMessageId = String(attachment.anchor_message_id ?? "").trim();
    const anchorTurnId = String(attachment.anchor_turn_id ?? "").trim();
    const taskRunId = String(attachment.task_run_id ?? "").trim();
    const taskRunRef = taskRunId
      ? assistantRefs.find((item) => item.taskRunId === taskRunId)
      : null;
    const explicitRef = explicitMessageId
      ? assistantRefs.find((item) => item.id === explicitMessageId)
      : null;
    const turnRef = anchorTurnId
      ? assistantRefs.find((item) => item.turnId === anchorTurnId)
      : null;
    const assistantRef = taskRunRef ?? explicitRef ?? turnRef;
    const targetId = assistantRef?.id ?? "";
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
  existingAssistantTaskRunIds: Set<string>,
) {
  const syntheticById = new Map<string, Message>();
  for (const attachment of attachments) {
    const explicitMessageId = String(attachment.anchor_message_id ?? "").trim();
    const anchorTurnId = String(attachment.anchor_turn_id ?? "").trim();
    const taskRunId = String(attachment.task_run_id ?? "").trim();
    if (taskRunId && existingAssistantTaskRunIds.has(taskRunId)) {
      continue;
    }
    const syntheticId = explicitMessageId || (anchorTurnId ? `history-message:${anchorTurnId}:assistant` : "");
    if (!syntheticId || existingAssistantIds.has(syntheticId)) {
      continue;
    }
    const hasVisibleRuntime = runtimeAttachmentHasUserVisibleProjection(attachment);
    if (!hasVisibleRuntime) {
      continue;
    }
    const anchorIndex = history.findIndex((message) =>
      message.role === "user" && String(message.turn_id ?? "").trim() === anchorTurnId
    );
    if (anchorIndex < 0) {
      continue;
    }
    const sourceIndex = anchorIndex + 0.5;
    const existing = syntheticById.get(syntheticId);
    syntheticById.set(syntheticId, {
      id: syntheticId,
      role: "assistant",
      content: "",
      toolCalls: [],
      retrievals: [],
      sourceIndex,
      sourceTurnId: anchorTurnId || undefined,
      sourceTaskRunId: taskRunId || undefined,
      runtimeAttachments: existing
        ? [...(existing.runtimeAttachments ?? []), attachment]
        : [attachment],
    });
  }
  return [...syntheticById.values()];
}

function runtimeAttachmentHasUserVisibleProjection(attachment: SessionRuntimeAttachment) {
  if (attachment.task_projection) {
    return true;
  }
  const hasPublicTimeline = (attachment.public_timeline ?? []).some((item) => {
    const slot = String(item.slot ?? "").trim();
    const surface = String(item.surface ?? "").trim();
    return slot !== "control" && surface !== "control" && surface !== "diagnostics";
  });
  if (hasPublicTimeline) {
    return true;
  }
  return (attachment.progress_entries ?? []).some(runtimeProgressEntryHasUserVisibleProjection);
}

function runtimeProgressEntryHasUserVisibleProjection(entry: Record<string, unknown>) {
  const kind = String(entry.kind ?? "").trim().toLowerCase();
  const surface = String(entry.surface ?? "").trim().toLowerCase();
  if (kind === "control" || kind === "diagnostics" || kind === "debug" || surface === "control" || surface === "diagnostics") {
    return false;
  }
  return Boolean(
    String(entry.title ?? "").trim()
    || String(entry.body ?? "").trim()
    || String(entry.publicNote ?? entry.public_note ?? "").trim()
    || String(entry.agentBrief ?? entry.agent_brief_output ?? "").trim()
  );
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
      if (message.role === "assistant" && isInternalActiveWorkControlText(content)) {
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
        sourceTurnId: historyTurnId(message) || undefined,
        sourceTaskRunId: historyTaskRunId(message) || undefined,
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
  const existingAssistantTaskRunIds = new Set(normalized
    .map((message) => message.sourceTaskRunId)
    .filter((value): value is string => Boolean(value)));
  const syntheticRuntimeMessages = syntheticAssistantMessagesForRuntimeAttachments(
    history,
    runtimeAttachments,
    existingAssistantIds,
    existingAssistantTaskRunIds,
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
