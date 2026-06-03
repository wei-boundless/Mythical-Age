import type { PublicChatTimelineItem } from "@/lib/api";

export type PublicTimelineTerminalState = "done" | "error" | "stopped" | "";

type MergeOptions = {
  terminalState?: PublicTimelineTerminalState;
  limit?: number;
};

export function cleanPublicTimelineText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function publicTimelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  return cleanPublicTimelineText(item.text || item.detail || item.title || item.path || item.href);
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
    const item = options.terminalState
      ? finalizePublicTimelineItem(rawItem, options.terminalState)
      : rawItem;
    if (!publicTimelineItemText(item)) {
      continue;
    }
    const semanticKey = publicTimelineSemanticKey(item);
    const key = publicTimelineItemKey(item, index);
    const existingIndex = semanticKey
      ? indexBySemanticKey.get(semanticKey)
      : indexByKey.get(key);

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

  return options.limit && options.limit > 0 ? result.slice(-options.limit) : result;
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
  const leftRank = publicTimelineStateRank(left);
  const rightRank = publicTimelineStateRank(right);
  if (rightRank >= leftRank) {
    return { ...left, ...right };
  }
  return left;
}

function publicTimelineStateRank(item: PublicChatTimelineItem) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return 4;
  if (["done", "ready", "passed", "success"].includes(state)) return 3;
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
