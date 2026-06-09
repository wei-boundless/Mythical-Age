import type { PublicChatTimelineItem } from "@/lib/api";
import { isInternalActiveWorkControlText } from "@/lib/internalControlText";

export type PublicTimelineTerminalState = "done" | "error" | "stopped" | "";

type MergeOptions = {
  terminalState?: PublicTimelineTerminalState;
  limit?: number;
};

const TOOL_LIMIT_BLOCKED_PUBLIC_TEXT = "本轮连续工具调用已达到运行上限，且没有生成可直接展示的结论。当前处理已停止。你可以让我继续下一轮，或补充要优先核查的位置。";
const PUBLIC_TIMELINE_TEXT_FIELDS = [
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
const TOOL_WINDOW_TEXT_FIELDS = ["tool_label", "target", "status"] as const;
const CONTROL_TIMELINE_PHASES = new Set(["waiting_user", "active_work_control"]);

export function sanitizePublicTimelineItems(items: PublicChatTimelineItem[] | null | undefined) {
  if (!Array.isArray(items) || !items.length) {
    return Array.isArray(items) ? items : undefined;
  }
  let changed = false;
  const sanitized = items.map((item) => {
    const next = sanitizePublicTimelineItem(item);
    if (next !== item) {
      changed = true;
    }
    return next;
  });
  return changed ? sanitized : items;
}

export function sanitizePublicTimelineItem(item: PublicChatTimelineItem) {
  const next: Record<string, unknown> = { ...item };
  let changed = false;
  for (const field of PUBLIC_TIMELINE_TEXT_FIELDS) {
    const sanitized = sanitizePublicTimelineText(next[field], { replacementForProtocolProjection: TOOL_LIMIT_BLOCKED_PUBLIC_TEXT });
    if (sanitized !== next[field]) {
      next[field] = sanitized;
      changed = true;
    }
  }
  const toolWindow = sanitizePublicTimelineToolWindow(item.tool_window);
  if (toolWindow !== item.tool_window) {
    if (toolWindow && Object.keys(toolWindow).length) {
      next.tool_window = toolWindow;
    } else {
      delete next.tool_window;
    }
    changed = true;
  }
  return changed ? next as PublicChatTimelineItem : item;
}

export function cleanPublicTimelineText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function publicTimelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  const text = cleanPublicTimelineText(item.public_summary || item.observation || item.text || item.detail || item.title || item.subject_label || item.path || item.href);
  if (text) return text;
  if (cleanPublicTimelineText(item.kind) !== "todo_plan" || !Array.isArray(item.todo_items)) {
    return "";
  }
  const activeItemId = cleanPublicTimelineText(item.active_item_id);
  const active = item.todo_items.find((todo) => cleanPublicTimelineText(todo.todo_id) === activeItemId)
    ?? item.todo_items.find((todo) => cleanPublicTimelineText(todo.status) === "in_progress")
    ?? item.todo_items[0];
  return cleanPublicTimelineText(active?.active_form || active?.content);
}

export function isPublicTimelineControlItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  if (slot === "control") {
    return true;
  }
  const kind = cleanPublicTimelineText(item.kind);
  const phase = cleanPublicTimelineText(item.phase).toLowerCase();
  if (kind === "status_update" && CONTROL_TIMELINE_PHASES.has(phase)) {
    return true;
  }
  const title = cleanPublicTimelineText(item.title);
  return kind === "status_update" && title === "等待补充信息";
}

export function publicTimelineItemKey(item: PublicChatTimelineItem | undefined, fallbackIndex = 0) {
  if (!item) return "";
  const itemId = cleanPublicTimelineText(item.item_id);
  if (itemId) return itemId;
  const semanticKey = publicTimelineSemanticKey(item);
  if (semanticKey) return semanticKey;
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
  if (kind === "work_action") {
    if (cleanPublicTimelineText(item.item_id)) return "";
    const actionKind = cleanPublicTimelineText(item.action_kind);
    const subject = cleanPublicTimelineText(item.subject_label);
    const refs = Array.isArray(item.trace_refs)
      ? item.trace_refs.map((ref) => cleanPublicTimelineText(ref)).filter(Boolean)
      : [];
    if (actionKind && subject && actionKind !== "batch") return `work:${actionKind}:${subject}`;
    return refs.length ? `work:${refs.join(",")}` : "";
  }
  if (kind !== "tool_activity") return "";
  const titleTarget = normalizedToolActivityTarget(item.title || item.text);
  const detailTarget = normalizedToolActivityTarget(item.path || item.href || item.detail);
  const target = titleTarget || detailTarget;
  return target ? `tool:${toolActivityOperation(item)}:${target}` : "";
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
    const sanitizedItem = sanitizePublicTimelineItem(rawItem);
    const item = options.terminalState
      ? finalizePublicTimelineItem(sanitizedItem, options.terminalState)
      : sanitizedItem;
    if (!publicTimelineItemText(item)) {
      continue;
    }
    const semanticKey = publicTimelineSemanticKey(item);
    const key = publicTimelineItemKey(item, index);
    const existingIndex = indexByKey.get(key)
      ?? (semanticKey ? indexBySemanticKey.get(semanticKey) : undefined);

    if (existingIndex !== undefined) {
      result[existingIndex] = preferPublicTimelineItem(result[existingIndex], item);
      indexByKey.set(key, existingIndex);
      if (semanticKey) {
        indexBySemanticKey.set(semanticKey, existingIndex);
      }
      continue;
    }

    indexByKey.set(key, result.length);
    if (semanticKey) {
      indexBySemanticKey.set(semanticKey, result.length);
    }
    result.push(item);
  }

  return trimPublicTimelineItems(result, options.limit);
}

function sanitizePublicTimelineToolWindow(value: PublicChatTimelineItem["tool_window"]) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return value;
  }
  const next: Record<string, unknown> = { ...value };
  let changed = false;
  for (const field of TOOL_WINDOW_TEXT_FIELDS) {
    const sanitized = sanitizePublicTimelineText(next[field], { replacementForProtocolProjection: "" });
    if (sanitized !== next[field]) {
      next[field] = sanitized;
      changed = true;
    }
  }
  if (Array.isArray(value.sections)) {
    const sections = value.sections
      .map((section) => {
        if (!section || typeof section !== "object" || Array.isArray(section)) {
          changed = true;
          return null;
        }
        const label = sanitizePublicTimelineText(section.label, { replacementForProtocolProjection: "" });
        const text = sanitizePublicTimelineText(section.text, { replacementForProtocolProjection: "" });
        if (label !== section.label || text !== section.text) {
          changed = true;
        }
        if (!cleanPublicTimelineText(label) || !cleanPublicTimelineText(text)) {
          changed = true;
          return null;
        }
        return { label: String(label), text: String(text) };
      })
      .filter((section): section is { label: string; text: string } => Boolean(section))
      .slice(0, 4);
    if (sections.length !== value.sections.length || sections.some((section, index) =>
      section.label !== value.sections?.[index]?.label || section.text !== value.sections?.[index]?.text
    )) {
      changed = true;
    }
    next.sections = sections;
  }
  return changed ? next as NonNullable<PublicChatTimelineItem["tool_window"]> : value;
}

function sanitizePublicTimelineText(
  value: unknown,
  options: { replacementForProtocolProjection: string },
) {
  if (typeof value !== "string") {
    return value;
  }
  if (isInternalActiveWorkControlText(value) || isInternalProtocolEnumText(value)) {
    return "";
  }
  if (looksLikeInternalProtocolProjectionText(value)) {
    return options.replacementForProtocolProjection;
  }
  return value;
}

function looksLikeInternalProtocolProjectionText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  return /内部工具协议|工具调用残片|<｜｜DSML｜｜|DSML|active_work_control\.action/.test(text)
    || /\btool_calls\b/i.test(text)
    || /模型返回了.*协议/.test(text);
}

function isInternalProtocolEnumText(value: unknown) {
  return String(value ?? "").trim().toLowerCase() === "assistant_message";
}

export function finalizePublicTimelineItems(
  items: PublicChatTimelineItem[] | undefined,
  terminalState: PublicTimelineTerminalState,
) {
  if (!terminalState) {
    return items ?? [];
  }
  return (items ?? []).map((item) => finalizePublicTimelineItem(item, terminalState));
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
  if (canonicalState === "stable_answer" || canonicalState === "tool_summary") return "done";
  if (canonicalState === "missing_answer" || channel === "blocked") return "error";
  return "";
}

export function publicTimelineTerminalStateFromEvent(event: string): PublicTimelineTerminalState {
  if (event === "done") return "done";
  if (event === "error") return "error";
  if (event === "stopped") return "stopped";
  return "";
}

function finalizePublicTimelineItem(
  item: PublicChatTimelineItem,
  terminalState: Exclude<PublicTimelineTerminalState, "">,
) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const streamState = cleanPublicTimelineText(item.stream_state).toLowerCase();
  if (streamState !== "streaming" && !["", "running", "working", "partial"].includes(state)) {
    return item;
  }
  return {
    ...item,
    state: terminalState === "error" ? "error" : "done",
    stream_state: "done",
  };
}

function preferPublicTimelineItem(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const trace_refs = mergeTraceRefs(left.trace_refs, right.trace_refs);
  const merged = publicTimelineStateRank(right) >= publicTimelineStateRank(left)
    ? { ...left, ...right }
    : { ...right, ...left };
  return trace_refs.length ? { ...merged, trace_refs } : merged;
}

function mergeTraceRefs(left: PublicChatTimelineItem["trace_refs"], right: PublicChatTimelineItem["trace_refs"]) {
  const seen = new Set<string>();
  const refs: string[] = [];
  for (const ref of [...(left ?? []), ...(right ?? [])]) {
    const normalized = cleanPublicTimelineText(ref);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    refs.push(normalized);
  }
  return refs;
}

function publicTimelineStateRank(item: PublicChatTimelineItem) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return 4;
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return 3;
  if (["running", "working", "partial"].includes(state) || item.stream_state === "streaming") return 2;
  return 1;
}

function normalizedToolActivityTarget(value: unknown) {
  const text = cleanPublicTimelineText(value);
  if (!text) return "";
  return text
    .replace(/^正在使用.+?处理\s*/i, "")
    .replace(/^正在(?:调用(?:工具)?|写入|编辑|更新|读取|搜索|检查|确认|运行)\s*/i, "")
    .replace(/^(?:工具已完成|工具失败|写入完成|更新完成|编辑完成|读取完成|搜索完成|检查完成|命令已完成)\s*/i, "")
    .replace(/[。.]$/g, "")
    .replace(/\\/g, "/")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function toolActivityOperation(item: PublicChatTimelineItem) {
  const text = cleanPublicTimelineText([item.title, item.text, item.detail, item.path, item.href].filter(Boolean).join(" ")).toLowerCase();
  if (/写入|编辑|更新|write|edit/.test(text)) return "write";
  if (/读取|read/.test(text)) return "read";
  if (/搜索|search/.test(text)) return "search";
  if (/检查|确认|path_exists|stat_path|list_dir|inspect/.test(text)) return "inspect";
  if (/运行|terminal|command|shell/.test(text)) return "command";
  return "call";
}

function trimPublicTimelineItems(items: PublicChatTimelineItem[], limit: number | undefined) {
  if (!limit || limit <= 0 || items.length <= limit) {
    return items;
  }
  const protectedIndexes = new Set<number>();
  items.forEach((item, index) => {
    if (isPublicTimelineBodyItem(item)) {
      protectedIndexes.add(index);
    }
  });
  if (!protectedIndexes.size) {
    return items.slice(-limit);
  }
  const selectedIndexes = new Set(protectedIndexes);
  const targetSize = Math.max(limit, protectedIndexes.size);
  for (let index = items.length - 1; index >= 0 && selectedIndexes.size < targetSize; index -= 1) {
    selectedIndexes.add(index);
  }
  return items.filter((_item, index) => selectedIndexes.has(index));
}

export function isPublicTimelineBodyItem(item: PublicChatTimelineItem | undefined) {
  if (!item) return false;
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot);
  const authority = cleanPublicTimelineText(item.source_authority);
  return slot === "body" && authority === "model";
}
