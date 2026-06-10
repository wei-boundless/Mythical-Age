import type { PublicChatTimelineItem } from "@/lib/api";
import { isInternalActiveWorkControlText } from "@/lib/internalControlText";

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
  if (isInternalActiveWorkControlText(text)) return "";
  if (looksLikeRawProjectedOutput(text)) return "";
  if (looksLikeProtocolText(text)) return "";
  return text;
}

export function publicTimelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  for (const field of TEXT_FIELDS) {
    const visible = sanitizePublicTimelineText(item[field]);
    if (visible) return visible;
  }
  if (cleanPublicTimelineText(item.kind) !== "todo_plan" || !Array.isArray(item.todo_items)) {
    return "";
  }
  const activeItemId = cleanPublicTimelineText(item.active_item_id);
  const active = item.todo_items.find((todo) => cleanPublicTimelineText(todo.todo_id) === activeItemId)
    ?? item.todo_items.find((todo) => cleanPublicTimelineText(todo.status) === "in_progress")
    ?? item.todo_items[0];
  return sanitizePublicTimelineText(active?.active_form || active?.content);
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
    if (isPublicTimelineBodyItem(rawItem)) continue;
    const item = options.terminalState
      ? finalizePublicTimelineItem(sanitizePublicTimelineItem(rawItem), options.terminalState)
      : sanitizePublicTimelineItem(rawItem);
    if (!publicTimelineItemText(item)) continue;
    const key = publicTimelineItemKey(item, index);
    const semanticKey = publicTimelineSemanticKey(item);
    const existingIndex = indexByKey.get(key) ?? (semanticKey ? indexBySemanticKey.get(semanticKey) : undefined);
    if (existingIndex !== undefined) {
      result[existingIndex] = preferPublicTimelineItem(result[existingIndex], item);
      indexByKey.set(key, existingIndex);
      if (semanticKey) indexBySemanticKey.set(semanticKey, existingIndex);
      continue;
    }
    indexByKey.set(key, result.length);
    if (semanticKey) indexBySemanticKey.set(semanticKey, result.length);
    result.push(item);
  }
  return trimPublicTimelineItems(result, options.limit);
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
  if (channel === "task_control") return "";
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
  let rawOutputSuppressed = false;
  for (const field of TEXT_FIELDS) {
    const rawText = cleanPublicTimelineText(next[field]);
    if (rawText && looksLikeRawProjectedOutput(rawText)) {
      rawOutputSuppressed = true;
    }
    next[field] = sanitizePublicTimelineText(next[field]);
  }
  if (rawOutputSuppressed) {
    next.raw_output_suppressed = true;
  }
  return next as PublicChatTimelineItem;
}

function finalizePublicTimelineItem(item: PublicChatTimelineItem, terminalState: PublicTimelineTerminalState) {
  if (!terminalState) return item;
  const currentState = cleanPublicTimelineText(item.state).toLowerCase();
  if (currentState && !["running", "working", "waiting"].includes(currentState)) return item;
  return { ...item, state: terminalState === "done" ? "done" : terminalState, stream_state: terminalState === "done" ? "done" : item.stream_state };
}

function preferPublicTimelineItem(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftRank = publicTimelineStateRank(left);
  const rightRank = publicTimelineStateRank(right);
  return rightRank >= leftRank ? { ...left, ...right } : { ...right, ...left };
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

function looksLikeProtocolText(value: string) {
  if (!value) return false;
  if ((value.startsWith("{") && value.endsWith("}")) || (value.startsWith("[") && value.endsWith("]"))) return true;
  return /(action_type|tool_call|task_control|terminal_reason|model_action_request|public_action_state|runtime_invocation_packet)/i.test(value);
}

function looksLikeRawProjectedOutput(value: string) {
  const raw = String(value ?? "").replace(/\r\n?/g, "\n");
  if (/(?:^|\n)\s*\d{1,6}\s*\|\s+/.test(raw)) return true;
  if (/^\d{1,6}\s*\|\s+/.test(cleanPublicTimelineText(raw))) return true;
  if (/\b(?:Exit code|Wall time|Output):/i.test(raw)) return true;
  if (/\b(?:Get-Content|Get-ChildItem|Select-Object|Stop-Process|Start-Process|python -m|npm run|npx )\b/i.test(raw)) return true;
  if (/Read persisted tool result failed|persisted tool result read failed/i.test(raw)) return true;
  if (/(?:runtime_context|runtime[-_ ]context)[\\/]+tool-results|tool-results[\\/]+session[-_A-Za-z0-9]+/i.test(raw)) return true;
  return false;
}

function normalizedToolTarget(value: unknown) {
  return cleanPublicTimelineText(value)
    .replace(/^正在(?:调用|读取|写入|更新|确认|搜索|运行)\s*/g, "")
    .replace(/^工具已完成\s*/g, "")
    .replace(/^已(?:读取|写入|更新|确认|搜索)\s*/g, "")
    .replace(/^命令已返回\s*/g, "")
    .trim();
}
