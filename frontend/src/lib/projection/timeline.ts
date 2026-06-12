import type { PublicChatTimelineItem } from "@/lib/api";
import { isInternalControlProtocolText } from "@/lib/internalControlText";

export type PublicTimelineTerminalState = "done" | "error" | "stopped" | "";

type MergeOptions = {
  terminalState?: PublicTimelineTerminalState;
  limit?: number;
};

const TEXT_FIELDS = [
  "title",
  "detail",
  "text",
  "public_summary",
  "observation",
  "recovery_hint",
  "next_step",
  "subject_label",
  "implication",
  "path",
  "href",
] as const;

const CONTROL_KINDS = new Set([
  "control_state",
  "approval_request",
  "approval_decision",
  "safe_boundary_wait",
  "steer_ack",
  "error_notice",
]);

const SUPPRESSED_TEXT = new Set([
  "",
  "开始处理",
  "处理完成",
  "处理已完成",
  "正在处理",
  "正在处理当前请求",
  "正在思考",
  "thinking",
  "working",
  "responding",
  "verifying",
  "waiting_for_tool",
  "tool_returned",
  "ready_to_finish",
  "已同步最新进展",
  "已接上当前工作，正在同步最新进展。",
  "已接上当前工作正在同步最新进展",
  "已开始继续处理；接下来会持续汇报正在推进的步骤。",
  "已开始继续处理接下来会持续汇报正在推进的步骤",
  "已把任务目标转成可跟踪的待办清单。",
  "已把任务目标转成可跟踪的待办清单",
  "已把任务目标转成可跟踪的处理清单。",
  "已把任务目标转成可跟踪的处理清单",
  "处理清单已建立",
  "处理清单已更新。",
  "处理清单已更新",
  "等待结果返回",
  "结果已返回",
  "上下文已返回",
  "读取未完成，需要重新确认读取范围后继续。",
  "读取未完成需要重新确认读取范围后继续",
  "任务执行器已接管",
  "任务执行器已接管，正在推进第一步。",
  "已接手任务，正在整理执行步骤。",
  "工具检查次数达到边界",
  "single_turn_tool_iteration_limit",
  "done",
  "completed",
  "running",
  "true",
  "false",
  "null",
]);

export function cleanPublicTimelineText(value: unknown) {
  return String(value ?? "")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function sanitizePublicTimelineText(value: unknown) {
  const text = cleanPublicTimelineText(value);
  if (!text) return "";
  const compact = text.replace(/[。.!！?？,，;；:：]/g, "").toLowerCase();
  if (SUPPRESSED_TEXT.has(text) || SUPPRESSED_TEXT.has(compact)) return "";
  if (looksLikeMachineStatusText(text)) return "";
  if (isInternalControlProtocolText(text)) return "";
  return text;
}

export function publicTimelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  for (const field of TEXT_FIELDS) {
    const visible = sanitizePublicTimelineText(item[field]);
    if (visible) return visible;
  }
  return "";
}

export function isPublicTimelineControlItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  const surface = cleanPublicTimelineText((item as { surface?: unknown }).surface).toLowerCase();
  const kind = cleanPublicTimelineText(item.kind);
  return slot === "control" || surface === "control" || CONTROL_KINDS.has(kind);
}

export function isPublicTimelineBodyItem(item: PublicChatTimelineItem | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  const surface = cleanPublicTimelineText((item as { surface?: unknown }).surface).toLowerCase();
  const authority = cleanPublicTimelineText(item.source_authority).toLowerCase();
  return slot === "body" && surface === "assistant_body" && authority === "model";
}

export function isPublicTimelineStatusBarItem(item: PublicChatTimelineItem | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  const surface = cleanPublicTimelineText((item as { surface?: unknown }).surface).toLowerCase();
  return slot === "status" || surface === "status_bar";
}

export function isPublicTimelineUserVisibleRuntimeItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  const surface = cleanPublicTimelineText((item as { surface?: unknown }).surface).toLowerCase();
  if (slot === "body" || surface === "assistant_body") return false;
  if (slot === "control" || surface === "control" || surface === "diagnostics") return false;
  return true;
}

export function isTaskProjectionCompanionTimelineItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  return ["control", "timeline", "tool", "status", "task"].includes(slot);
}

export function publicTimelineItemKey(item: PublicChatTimelineItem | undefined, fallbackIndex = 0) {
  if (!item) return "";
  const itemId = cleanPublicTimelineText(item.item_id);
  if (itemId) return itemId;
  const refs = Array.isArray(item.trace_refs)
    ? item.trace_refs.map((ref) => cleanPublicTimelineText(ref)).filter(Boolean)
    : [];
  if (refs.length) return `refs:${refs.join(",")}`;
  return [
    cleanPublicTimelineText(item.kind),
    publicTimelineItemText(item),
    fallbackIndex,
  ].join(":");
}

export function publicTimelineSemanticKey(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  const kind = cleanPublicTimelineText(item.kind);
  if (isPublicTimelineBodyItem(item)) {
    const body = cleanPublicTimelineText(item.text || item.detail || item.public_summary || item.observation || item.implication);
    return body ? `body:${kind}:${body}` : "";
  }
  if (kind === "work_action" || kind === "tool_activity") {
    const actionKind = cleanPublicTimelineText(item.action_kind) || kind;
    const subject = cleanPublicTimelineText(item.subject_label) || normalizedToolTarget(item.title || item.text || item.detail || item.path || item.href);
    return subject ? `tool:${actionKind}:${subject}` : "";
  }
  return "";
}

export function mergePublicTimelineItems(
  existing: PublicChatTimelineItem[] | undefined,
  incoming: PublicChatTimelineItem[] | undefined,
  options: MergeOptions = {},
) {
  return normalizePublicTimelineItems([...(existing ?? []), ...(incoming ?? [])], options);
}

export function normalizePublicTimelineItems(
  items: PublicChatTimelineItem[] | undefined,
  options: MergeOptions = {},
) {
  const result: PublicChatTimelineItem[] = [];
  const indexByKey = new Map<string, number>();
  const indexBySemanticKey = new Map<string, number>();
  for (const [index, rawItem] of (items ?? []).entries()) {
    if (cleanPublicTimelineText(rawItem.kind) === "todo_plan") continue;
    if (isPublicTimelineBodyItem(rawItem)) continue;
    if (isPublicTimelineStatusBarItem(rawItem) && !shouldKeepStatusTimelineItem(rawItem, options.terminalState)) continue;
    const item = options.terminalState
      ? finalizePublicTimelineItem(sanitizePublicTimelineItem(rawItem), options.terminalState)
      : sanitizePublicTimelineItem(rawItem);
    if (!publicTimelineItemText(item)) continue;
    const key = publicTimelineItemKey(item, index);
    const semanticKey = publicTimelineSemanticKey(item);
    const existingIndex = indexByKey.get(key) ?? (semanticKey ? indexBySemanticKey.get(semanticKey) : undefined);
    if (existingIndex !== undefined) {
      result[existingIndex] = mergePublicTimelineItem(result[existingIndex], item);
      indexByKey.set(key, existingIndex);
      if (semanticKey) indexBySemanticKey.set(semanticKey, existingIndex);
      continue;
    }
    indexByKey.set(key, result.length);
    if (semanticKey) indexBySemanticKey.set(semanticKey, result.length);
    result.push(item);
  }
  return trimPublicTimelineItems(sortPublicTimelineItems(result), options.limit);
}

function shouldKeepStatusTimelineItem(item: PublicChatTimelineItem, terminalState: PublicTimelineTerminalState | undefined) {
  if (terminalState) {
    return true;
  }
  const kind = cleanPublicTimelineText(item.kind).toLowerCase();
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const phase = cleanPublicTimelineText(item.phase).toLowerCase();
  if (kind !== "status_update") {
    return false;
  }
  return ["error", "failed", "stopped", "stale", "waiting", "blocked"].includes(state)
    || ["error", "failed", "stopped", "stale", "waiting", "blocked"].includes(phase);
}

export function publicTimelineTerminalStateFromAnswer({
  answerCanonicalState,
  answerChannel,
}: {
  answerCanonicalState?: string;
  answerChannel?: string;
}): PublicTimelineTerminalState {
  const canonicalState = cleanPublicTimelineText(answerCanonicalState).toLowerCase();
  const channel = cleanPublicTimelineText(answerChannel).toLowerCase();
  if (channel === "task_control" || channel === "opening_judgment") return "";
  if (channel === "blocked" || canonicalState === "missing_answer") return "error";
  return ["final", "stable_answer"].includes(canonicalState) ? "done" : "";
}

export function publicTimelineTerminalStateFromEvent(event: string): PublicTimelineTerminalState {
  if (event === "done") return "done";
  if (event === "error") return "error";
  if (event === "stopped") return "stopped";
  return "";
}

function sanitizePublicTimelineItem(item: PublicChatTimelineItem) {
  const next: Record<string, unknown> = { ...item };
  for (const field of TEXT_FIELDS) {
    next[field] = sanitizePublicTimelineText(next[field]);
  }
  return next as PublicChatTimelineItem;
}

function finalizePublicTimelineItem(item: PublicChatTimelineItem, terminalState: PublicTimelineTerminalState) {
  if (!terminalState) return item;
  const currentState = cleanPublicTimelineText(item.state).toLowerCase();
  if (currentState && !["running", "working", "waiting"].includes(currentState)) return item;
  return { ...item, state: terminalState === "done" ? "done" : terminalState, stream_state: terminalState === "done" ? "done" : item.stream_state };
}

function mergePublicTimelineItem(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftRank = publicTimelineStateRank(left);
  const rightRank = publicTimelineStateRank(right);
  const preferred = rightRank >= leftRank ? { ...left, ...right } : { ...right, ...left };
  return preserveEarliestPublicTimelineOrder(preferred, left, right);
}

function preserveEarliestPublicTimelineOrder(
  merged: PublicChatTimelineItem,
  left: PublicChatTimelineItem,
  right: PublicChatTimelineItem,
) {
  const earliest = comparePublicTimelineOrder(left, right) <= 0 ? left : right;
  const latest = comparePublicTimelineOrder(left, right) <= 0 ? right : left;
  return {
    ...merged,
    ...publicTimelineOrderFields(earliest),
    ...publicTimelineUpdatedFields(latest),
  };
}

function sortPublicTimelineItems(items: PublicChatTimelineItem[]) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftOrder = publicTimelineOrderValue(left.item, left.index);
      const rightOrder = publicTimelineOrderValue(right.item, right.index);
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      const leftEvent = cleanPublicTimelineText(left.item.source_event_id ?? left.item.sourceEventId);
      const rightEvent = cleanPublicTimelineText(right.item.source_event_id ?? right.item.sourceEventId);
      return leftEvent.localeCompare(rightEvent) || left.index - right.index;
    })
    .map(({ item }) => item);
}

export function publicTimelineOrderValue(item: PublicChatTimelineItem | undefined, fallbackIndex = 0) {
  const explicitOrder = publicTimelineExplicitOrderValue(item);
  if (explicitOrder !== undefined) {
    return explicitOrder;
  }
  return 2_000_000_000 + fallbackIndex;
}

export function publicTimelineExplicitOrderValue(item: PublicChatTimelineItem | undefined) {
  const explicit = numericTimelineValue(item?.sequence)
    ?? numericTimelineValue(item?.event_offset)
    ?? numericTimelineValue(item?.eventOffset);
  const created = numericTimelineValue(item?.created_at)
    ?? numericTimelineValue(item?.createdAt);
  if (explicit !== undefined) {
    return explicit + (created ?? 0) / 1_000_000_000;
  }
  if (created !== undefined) {
    return 1_000_000_000 + created;
  }
  return undefined;
}

function comparePublicTimelineOrder(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftOrder = publicTimelineOrderValue(left, 0);
  const rightOrder = publicTimelineOrderValue(right, 0);
  if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  const leftEvent = cleanPublicTimelineText(left.source_event_id ?? left.sourceEventId);
  const rightEvent = cleanPublicTimelineText(right.source_event_id ?? right.sourceEventId);
  return leftEvent.localeCompare(rightEvent);
}

function publicTimelineOrderFields(item: PublicChatTimelineItem) {
  const fields: Partial<PublicChatTimelineItem> = {};
  if (numericTimelineValue(item.sequence) !== undefined) fields.sequence = Number(item.sequence);
  if (numericTimelineValue(item.event_offset) !== undefined) fields.event_offset = Number(item.event_offset);
  if (numericTimelineValue(item.eventOffset) !== undefined) fields.eventOffset = Number(item.eventOffset);
  if (numericTimelineValue(item.created_at) !== undefined) fields.created_at = Number(item.created_at);
  if (numericTimelineValue(item.createdAt) !== undefined) fields.createdAt = Number(item.createdAt);
  if (cleanPublicTimelineText(item.source_run_id)) fields.source_run_id = cleanPublicTimelineText(item.source_run_id);
  if (cleanPublicTimelineText(item.sourceRunId)) fields.sourceRunId = cleanPublicTimelineText(item.sourceRunId);
  if (cleanPublicTimelineText(item.source_event_id)) fields.source_event_id = cleanPublicTimelineText(item.source_event_id);
  if (cleanPublicTimelineText(item.sourceEventId)) fields.sourceEventId = cleanPublicTimelineText(item.sourceEventId);
  return fields;
}

function publicTimelineUpdatedFields(item: PublicChatTimelineItem) {
  const fields: Partial<PublicChatTimelineItem> = {};
  const updatedOffset = numericTimelineValue(item.updated_event_offset)
    ?? numericTimelineValue(item.event_offset)
    ?? numericTimelineValue(item.eventOffset)
    ?? numericTimelineValue(item.sequence);
  const updatedAt = numericTimelineValue(item.updated_at)
    ?? numericTimelineValue(item.created_at)
    ?? numericTimelineValue(item.createdAt);
  const updatedEvent = cleanPublicTimelineText(item.updated_source_event_id)
    || cleanPublicTimelineText(item.source_event_id)
    || cleanPublicTimelineText(item.sourceEventId);
  if (updatedOffset !== undefined) fields.updated_event_offset = updatedOffset;
  if (updatedAt !== undefined) fields.updated_at = updatedAt;
  if (updatedEvent) fields.updated_source_event_id = updatedEvent;
  return fields;
}

function numericTimelineValue(value: unknown) {
  if (value === null || value === undefined || value === "") return undefined;
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function trimPublicTimelineItems(items: PublicChatTimelineItem[], limit = 24) {
  return items.slice(-Math.max(1, limit));
}

function publicTimelineStateRank(item: PublicChatTimelineItem) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const streamState = cleanPublicTimelineText(item.stream_state).toLowerCase();
  if (state === "error") return 5;
  if (state === "stopped") return 4;
  if (state === "done" || streamState === "done") return 3;
  if (state === "waiting") return 2;
  if (state === "running") return 1;
  return 0;
}

function looksLikeMachineStatusText(value: string) {
  const lowered = cleanPublicTimelineText(value).toLowerCase();
  if (!lowered) return false;
  const states = ["thinking", "working", "responding", "verifying", "waiting_for_tool", "tool_returned", "ready_to_finish", "blocked"];
  if (states.includes(lowered)) return true;
  if (/^(状态|status|completion[_\s-]*status|visible[_\s-]*status)\s*[:：]?\s*(thinking|working|responding|verifying|waiting_for_tool|tool_returned|ready_to_finish|blocked)$/i.test(lowered)) {
    return true;
  }
  const compact = lowered.replace(/[\s。.!！?？,，;；:：_-]+/g, "");
  return states.some((item) => item.replace(/_/g, "") === compact);
}

function normalizedToolTarget(value: unknown) {
  return cleanPublicTimelineText(value)
    .replace(/^正在(?:调用|读取|写入|更新|确认|搜索|运行)\s*/g, "")
    .replace(/^工具已完成\s*/g, "")
    .replace(/^已(?:读取|写入|更新|确认|搜索)\s*/g, "")
    .replace(/^命令已返回\s*/g, "")
    .trim();
}
