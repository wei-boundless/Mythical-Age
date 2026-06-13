"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { looksLikeRawToolOutput } from "@/components/chat/agentRunProjection";
import type { PublicChatTimelineItem } from "@/lib/api";
import { cleanPublicTimelineText, isPublicTimelineControlItem, normalizePublicTimelineItems, publicTimelineExplicitOrderValue, sanitizePublicTimelineText } from "@/lib/projection/timeline";

type PublicTimelineActivityProps = {
  items?: PublicChatTimelineItem[] | null;
  compactCompletedTools?: boolean;
};

type PublicTimelineActivityOptions = {
  compactCompletedTools?: boolean;
};

type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type ActivityEntrySource = "timeline";

type ActivityEntry = {
  collapsed?: boolean;
  detail?: string;
  eventRefs?: string[];
  groupKey?: string;
  id: string;
  kind: "body" | "status" | "stopped" | "tool";
  order?: number;
  source?: ActivityEntrySource;
  sourceIndex?: number;
  sourceRank?: number;
  sources?: ActivityEntrySource[];
  state?: string;
  stateRank?: number;
  text: string;
  actionKind?: string;
  toolName?: string;
  toolTarget?: string;
  toolWindow?: ToolWindowProjection;
};

type PublicTimelineActivityView = {
  entries: ActivityEntry[];
  tone: PublicTimelineActivityTone;
};

type ToolWindowProjection = {
  meta: string[];
  sections: Array<{
    label: string;
    text: string;
  }>;
};

export function PublicTimelineActivity({ items, compactCompletedTools = false }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items, { compactCompletedTools });
  if (!view) {
    return null;
  }

  return (
    <div
      className={`public-run-activity public-run-activity--${view.tone}`}
      aria-label="处理进展"
      data-entry-count={view.entries.length}
    >
      {view.entries.map((entry) => (
        entry.kind === "body"
          ? <ActivityBody entry={entry} key={entry.id || entry.text} />
        : entry.kind === "tool"
          ? <ToolWindow entry={entry} key={entry.id || entry.text} />
        : <ActivityLine entry={entry} key={entry.id || entry.text} />
      ))}
    </div>
  );
}

export function publicTimelineHasDisplayableActivity(
  items: PublicChatTimelineItem[] | null | undefined,
  options: PublicTimelineActivityOptions = {},
) {
  return Boolean(publicTimelineActivityView(items, options));
}

function publicTimelineActivityView(
  items: PublicChatTimelineItem[] | null | undefined,
  options: PublicTimelineActivityOptions = {},
): PublicTimelineActivityView | null {
  const normalizedItems = normalizePublicTimelineItems(items ?? []).filter((item) => !isPublicTimelineControlItem(item));
  const entries = mergeAndOrderActivityEntries(activityEntries(normalizedItems, options));
  if (!entries.length) {
    return null;
  }
  return {
    entries,
    tone: publicTimelineTone(normalizedItems),
  };
}

function mergeAndOrderActivityEntries(entries: ActivityEntry[]) {
  const ordered = entries
    .map((entry, index) => finalizeActivityEntry(entry, entry.source ?? "timeline", entry.sourceIndex ?? index))
    .sort(compareActivityEntries);
  const result: ActivityEntry[] = [];
  const indexByKey = new Map<string, number>();
  for (const entry of ordered) {
    const keys = activityMergeKeys(entry);
    const matchingIndexes = [...new Set(
      keys
        .map((key) => indexByKey.get(key))
        .filter((value): value is number => value !== undefined),
    )].sort((left, right) => left - right);
    if (!matchingIndexes.length) {
      result.push(entry);
      rebuildActivityMergeIndex(result, indexByKey);
      continue;
    }
    const targetIndex = matchingIndexes[0];
    let merged = mergeActivityEntries(result[targetIndex], entry);
    for (const duplicateIndex of matchingIndexes.slice(1).reverse()) {
      merged = mergeActivityEntries(result[duplicateIndex], merged);
      result.splice(duplicateIndex, 1);
    }
    result[targetIndex] = merged;
    rebuildActivityMergeIndex(result, indexByKey);
  }
  return result.sort(compareActivityEntries);
}

function rebuildActivityMergeIndex(entries: ActivityEntry[], indexByKey: Map<string, number>) {
  indexByKey.clear();
  for (const [index, entry] of entries.entries()) {
    for (const key of activityMergeKeys(entry)) {
      if (!indexByKey.has(key)) {
        indexByKey.set(key, index);
      }
    }
  }
}

function mergeActivityEntries(left: ActivityEntry, right: ActivityEntry): ActivityEntry {
  const mergedKind: ActivityEntry["kind"] = left.kind === "tool" || right.kind === "tool"
    ? "tool"
    : left.kind === "body" || right.kind === "body"
      ? "body"
    : left.kind === "stopped" || right.kind === "stopped"
      ? "stopped"
      : "status";
  const preferred = preferActivityEntry(left, right);
  const secondary = preferred === left ? right : left;
  const state = preferred.state || secondary.state;
  const toolWindow = mergedKind === "tool"
    ? mergeToolWindowProjection(activityToolWindowProjection(left), activityToolWindowProjection(right))
    : undefined;
  return {
    ...preferred,
    actionKind: preferred.actionKind || secondary.actionKind,
    collapsed: mergedKind === "tool" ? mergedToolCollapsed(preferred, secondary, state) : undefined,
    detail: mergeActivityDetail(preferred.detail, secondary.detail),
    eventRefs: uniqueStrings([...(left.eventRefs ?? []), ...(right.eventRefs ?? [])]),
    groupKey: preferred.groupKey || secondary.groupKey,
    id: preferred.id || secondary.id,
    kind: mergedKind,
    order: Math.min(activityEntryOrder(left), activityEntryOrder(right)),
    sourceIndex: Math.min(left.sourceIndex ?? 0, right.sourceIndex ?? 0),
    sourceRank: Math.min(left.sourceRank ?? 0, right.sourceRank ?? 0),
    sources: uniqueActivitySources([...(left.sources ?? sourceList(left.source)), ...(right.sources ?? sourceList(right.source))]),
    state,
    stateRank: Math.max(left.stateRank ?? activityStateRank(left.state), right.stateRank ?? activityStateRank(right.state)),
    text: preferred.text || secondary.text,
    toolName: preferred.toolName || secondary.toolName,
    toolTarget: preferred.toolTarget || secondary.toolTarget,
    toolWindow,
  };
}

function preferActivityEntry(left: ActivityEntry, right: ActivityEntry) {
  return activityDisplayRank(right) > activityDisplayRank(left) ? right : left;
}

function activityDisplayRank(entry: ActivityEntry) {
  let rank = activityStateRank(entry.state) * 100;
  if (entry.kind === "body") rank += 20;
  rank += entry.source === "timeline" ? 14 : 8;
  if (entry.toolTarget) rank += 6;
  if (entry.detail) rank += 3;
  if (entry.toolWindow?.sections.length) rank += 3;
  if (entry.toolWindow?.meta.length) rank += 1;
  if (isGenericCompletedToolText(entry.text)) rank -= 24;
  if (/^[a-z0-9_.-]+\s+已返回$/i.test(entry.text)) rank -= 8;
  return rank;
}

function mergeToolWindowProjection(
  left: ToolWindowProjection | undefined,
  right: ToolWindowProjection | undefined,
): ToolWindowProjection | undefined {
  const meta = uniqueStrings([...(left?.meta ?? []), ...(right?.meta ?? [])]).slice(0, 5);
  const sections: ToolWindowProjection["sections"] = [];
  const seen = new Set<string>();
  for (const section of [...(left?.sections ?? []), ...(right?.sections ?? [])]) {
    const label = shortText(cleanPublicTimelineText(section.label), 36);
    const text = shortText(sanitizePublicTimelineText(section.text), 260);
    if (!label || !text) {
      continue;
    }
    const key = compactActivityText(`${label}:${text}`);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    sections.push({ label, text });
  }
  if (!meta.length && !sections.length) {
    return undefined;
  }
  return { meta, sections: sections.slice(0, 5) };
}

function activityToolWindowProjection(entry: ActivityEntry): ToolWindowProjection | undefined {
  if (entry.toolWindow) {
    return entry.toolWindow;
  }
  if (entry.kind !== "tool" || !entry.detail) {
    return undefined;
  }
  return { meta: [], sections: [{ label: "结果", text: shortText(entry.detail, 260) }] };
}

function mergedToolCollapsed(preferred: ActivityEntry, secondary: ActivityEntry, state: string | undefined) {
  const normalized = cleanPublicTimelineText(state).toLowerCase();
  if (["", "running", "working", "partial", "error", "failed", "blocked", "missing"].includes(normalized)) {
    return false;
  }
  if (typeof preferred.collapsed === "boolean") {
    return preferred.collapsed;
  }
  if (typeof secondary.collapsed === "boolean") {
    return secondary.collapsed;
  }
  return undefined;
}

function mergeActivityDetail(primary: string | undefined, secondary: string | undefined) {
  const left = cleanPublicTimelineText(primary);
  const right = cleanPublicTimelineText(secondary);
  if (!left) return right;
  if (!right) return left;
  const compactLeft = compactActivityText(left);
  const compactRight = compactActivityText(right);
  if (compactLeft === compactRight || compactLeft.includes(compactRight)) {
    return left;
  }
  if (compactRight.includes(compactLeft)) {
    return right;
  }
  return `${left}\n${right}`;
}

function activityMergeKeys(entry: ActivityEntry) {
  return uniqueStrings([
    ...(entry.eventRefs ?? []).map((ref) => `event:${ref}`),
    entry.groupKey,
  ].filter(Boolean));
}

function finalizeActivityEntry(entry: ActivityEntry, source: ActivityEntrySource, sourceIndex: number): ActivityEntry {
  const eventRefs = normalizedEventRefs(entry.eventRefs);
  const sourceRank = source === "timeline" ? 0 : 1;
  const finalized: ActivityEntry = {
    ...entry,
    eventRefs,
    order: entry.order ?? activityOrderFromRefs(eventRefs, sourceIndex, sourceRank),
    source,
    sourceIndex,
    sourceRank,
    sources: entry.sources ?? [source],
    stateRank: entry.stateRank ?? activityStateRank(entry.state),
  };
  return {
    ...finalized,
    groupKey: finalized.groupKey || activityGroupKey(finalized),
  };
}

function activityGroupKey(entry: ActivityEntry) {
  if (entry.kind !== "tool") {
    return "";
  }
  const target = normalizedActivityKey(entry.toolTarget);
  if (!target) {
    return "";
  }
  const action = normalizedActivityKey(entry.actionKind || entry.toolName || "tool") || "tool";
  return `tool:${action}:${target}`;
}

function activityOrderFromRefs(eventRefs: string[], sourceIndex: number, sourceRank: number) {
  const order = eventRefs.map(eventRefOrder).find((value) => Number.isFinite(value));
  if (order !== undefined) {
    return Number(order) + sourceRank / 10 + sourceIndex / 10000;
  }
  return 100000 + sourceRank * 10000 + sourceIndex;
}

function eventRefOrder(ref: string) {
  const parts = cleanPublicTimelineText(ref).split(":");
  for (let index = parts.length - 2; index >= 0; index -= 1) {
    const value = parts[index];
    if (/^\d+$/.test(value)) {
      return Number(value);
    }
  }
  const last = parts.at(-1);
  return last && /^\d+$/.test(last) ? Number(last) : Number.NaN;
}

function compareActivityEntries(left: ActivityEntry, right: ActivityEntry) {
  return activityEntryOrder(left) - activityEntryOrder(right)
    || (left.sourceRank ?? 0) - (right.sourceRank ?? 0)
    || (left.sourceIndex ?? 0) - (right.sourceIndex ?? 0)
    || left.id.localeCompare(right.id);
}

function activityEntryOrder(entry: ActivityEntry) {
  return Number.isFinite(entry.order) ? Number(entry.order) : Number.MAX_SAFE_INTEGER;
}

function activityStateRank(state: unknown) {
  const normalized = cleanPublicTimelineText(state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(normalized)) return 5;
  if (["stopped", "aborted", "cancelled", "canceled"].includes(normalized)) return 5;
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(normalized)) return 4;
  if (["waiting", "waiting_user", "waiting_approval", "waiting_safe_boundary", "queued", "paused"].includes(normalized)) return 3;
  if (["running", "working", "partial", ""].includes(normalized)) return 2;
  return 1;
}

function eventRefsFromUnknown(value: unknown) {
  if (Array.isArray(value)) {
    return normalizedEventRefs(value);
  }
  return normalizedEventRefs(
    cleanPublicTimelineText(value)
      .split(",")
      .map((item) => item.trim()),
  );
}

function normalizedEventRefs(values: unknown) {
  if (!Array.isArray(values)) {
    return [];
  }
  return uniqueStrings(values.map((value) => cleanPublicTimelineText(value)).filter(isRuntimeEventRef));
}

function isRuntimeEventRef(value: string) {
  return /^(rtevt|event|rtobs|obs|toolobs):/.test(value);
}

function uniqueStrings(values: Array<string | undefined>) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const text = cleanPublicTimelineText(value);
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    result.push(text);
  }
  return result;
}

function uniqueActivitySources(values: ActivityEntrySource[]) {
  return [...new Set(values.filter(Boolean))];
}

function sourceList(source: ActivityEntrySource | undefined) {
  return source ? [source] : [];
}

function normalizedActivityKey(value: unknown) {
  return cleanPublicTimelineText(value)
    .replace(/^正在(?:调用|读取|写入|更新|确认|搜索|运行)\s*/g, "")
    .replace(/^工具(?:已完成|结果已返回|已返回)\s*/g, "")
    .replace(/^已(?:读取|写入|更新|确认|搜索)\s*/g, "")
    .replace(/^命令已返回\s*/g, "")
    .replace(/[\\]+/g, "/")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function compactActivityText(value: string) {
  return String(value ?? "").replace(/\s+/g, "").toLowerCase();
}

function isGenericStatusActivity(title: string, detail: string) {
  const normalizedTitle = title.replace(/\s+/g, "");
  const normalizedDetail = detail.replace(/\s+/g, "");
  return [
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在思考",
    "正在处理",
    "正在处理任务",
    "正在建立任务运行",
    "已同步最新进展",
    "已接上当前工作正在同步最新进展",
    "已开始继续处理接下来会持续汇报正在推进的步骤",
    "已把任务目标转成可跟踪的待办清单",
    "已把任务目标转成可跟踪的处理清单",
    "补齐验收证据",
    "搜索证据",
    "读取文件内容",
    "检查路径信息",
    "确认路径状态",
  ].includes(normalizedTitle.replace(/[。.]$/g, ""))
    && (!normalizedDetail || normalizedDetail === normalizedTitle);
}

function activityEntries(items: PublicChatTimelineItem[], options: PublicTimelineActivityOptions = {}): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  for (const [index, item] of items.entries()) {
    if (kindOf(item) === "todo_plan") {
      continue;
    }
    const kind = activityLineKind(item);
    if (!kind) {
      continue;
    }
    const text = kind === "tool" ? toolSummaryText(item) : publicText(item);
    if (!text) {
      continue;
    }
    const detail = kind === "tool" ? toolDetailText(item, text) : statusDetailText(item, text);
    if (kind === "status" && isGenericStatusActivity(text, detail)) {
      continue;
    }
    const toolTarget = publicTimelineToolTarget(item);
    entries.push({
      collapsed: kind === "tool" ? shouldCollapseToolWindow(item, options) : undefined,
      detail,
      eventRefs: eventRefsFromUnknown(item.trace_refs),
      id: String(item.item_id ?? "") || `${kind}:${index}:${text}`,
      kind,
      actionKind: cleanPublicTimelineText(item.action_kind),
      order: publicTimelineExplicitOrderValue(item),
      state: cleanPublicTimelineText(item.state).toLowerCase(),
      text: shortText(text, kind === "tool" ? 180 : 220),
      toolName: cleanPublicTimelineText(item.tool_name),
      toolTarget,
      toolWindow: kind === "tool" ? toolWindowProjection(item, detail) : undefined,
    });
  }
  return entries;
}

function publicTimelineToolTarget(item: PublicChatTimelineItem) {
  return sanitizePublicTimelineText(item.tool_window?.target)
    || sanitizePublicTimelineText(item.subject_label)
    || sanitizePublicTimelineText(item.path)
    || sanitizePublicTimelineText(item.href);
}

function activityLineKind(item: PublicChatTimelineItem): ActivityEntry["kind"] | "" {
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  if (slot === "tool") return "tool";
  if (slot === "status" || slot === "timeline" || slot === "task") return "status";
  if (slot === "control") return "";
  return "";
}

function isGenericCompletedToolText(value: unknown) {
  const normalized = compactActivityText(cleanPublicTimelineText(value)).replace(/[。.!！?？,，;；:：]$/g, "");
  return GENERIC_COMPLETED_TOOL_TEXT.has(normalized);
}

const GENERIC_COMPLETED_TOOL_TEXT = new Set([
  "",
  "工具已完成",
  "工具调用已完成",
  "工具返回成功",
  "操作已返回",
  "结果已返回",
  "执行完成",
  "调用完成",
  "运行完成",
  "读取完成",
  "已读取完成",
  "读取已完成",
  "完成",
  "已完成",
].map(compactActivityText));

function shouldCollapseToolWindow(item: PublicChatTimelineItem, options: PublicTimelineActivityOptions = {}) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const running = ["", "running", "working", "partial"].includes(state) || item.stream_state === "streaming";
  const failed = ["error", "failed", "blocked", "missing"].includes(state);
  if (running || failed) return false;
  if (typeof item.collapsed === "boolean") return item.collapsed;
  if (options.compactCompletedTools) return true;
  return true;
}

function publicTimelineTone(items: PublicChatTimelineItem[]): PublicTimelineActivityTone {
  const state = items.map((item) => String(item.state ?? "").trim().toLowerCase()).reverse().find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function publicText(item: PublicChatTimelineItem) {
  const candidates = [
    item.public_summary,
    item.title,
    item.subject_label,
    item.detail,
    item.observation,
    item.text,
    item.path,
    item.href,
  ];
  for (const candidate of candidates) {
    const text = sanitizePublicTimelineText(candidate);
    if (text && !looksLikeRawToolOutput(text)) {
      return text;
    }
  }
  return "";
}

function toolSummaryText(item: PublicChatTimelineItem) {
  const title = sanitizePublicTimelineText(item.title);
  const target = publicTimelineToolTarget(item);
  if (title) {
    return target && !title.includes(target) ? `${title} ${target}` : title;
  }
  const candidates = [item.subject_label, item.text, item.public_summary, item.path, item.href];
  for (const candidate of candidates) {
    const text = sanitizePublicTimelineText(candidate);
    if (text && !looksLikeRawToolOutput(text)) {
      return text;
    }
  }
  return "";
}

function toolDetailText(item: PublicChatTimelineItem, summary: string) {
  const candidates = [item.observation, item.detail, item.public_summary, item.recovery_hint, item.path, item.href];
  for (const candidate of candidates) {
    const text = sanitizePublicTimelineText(candidate);
    if (text && text !== summary && !looksLikeRawToolOutput(text)) {
      return shortText(text, 260);
    }
  }
  return "";
}

function statusDetailText(item: PublicChatTimelineItem, summary: string) {
  const candidates = [item.detail, item.observation, item.public_summary, item.text];
  for (const candidate of candidates) {
    const text = sanitizePublicTimelineText(candidate);
    if (text && text !== summary && !looksLikeRawToolOutput(text)) {
      return text;
    }
  }
  return "";
}

function toolWindowProjection(item: PublicChatTimelineItem, fallbackDetail: string): ToolWindowProjection | undefined {
  const raw = item.tool_window;
  const rawSections = Array.isArray(raw?.sections) ? raw.sections : [];
  const sections = rawSections
    .map((section) => ({
      label: shortText(cleanPublicTimelineText(section?.label), 36),
      text: shortText(sanitizePublicTimelineText(section?.text), 260),
    }))
    .filter((section) => section.label && section.text)
    .slice(0, 4);
  if (!sections.length && fallbackDetail) {
    sections.push({ label: "结果", text: shortText(fallbackDetail, 260) });
  }
  const meta = [
    raw?.tool_label,
    raw?.status,
    raw?.target,
  ].map((value) => shortText(sanitizePublicTimelineText(value), 90)).filter(Boolean).slice(0, 3);
  if (!sections.length && !meta.length) {
    return undefined;
  }
  return { meta, sections };
}

function kindOf(item: PublicChatTimelineItem | null | undefined) {
  return String(item?.kind ?? "").trim();
}

function shortText(value: unknown, limit: number) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}...` : text;
}

function ActivityLine({ entry }: { entry: ActivityEntry }) {
  const { detail, kind, text } = entry;
  const detailMarkdown = detail ? activityDetailMarkdown(detail) : "";
  return (
    <div
      className={`public-run-activity__line public-run-activity__line--${kind}`}
      data-activity-group={entry.groupKey || undefined}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-activity-order={formatActivityOrder(entry.order)}
      data-activity-source={activitySourcesLabel(entry)}
    >
      <p>{text}</p>
      {detailMarkdown ? (
        <div className="public-run-activity__line-detail markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {detailMarkdown}
          </ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}

function activityDetailMarkdown(value: string) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const withListBreaks = text.replace(/\s+(?=\d{1,2}\.\s+\S)/g, "\n");
  return withListBreaks.replace(/([^\n])\n(?=1\.\s+\S)/, "$1\n\n");
}

function ActivityBody({ entry }: { entry: ActivityEntry }) {
  return (
    <div
      className="public-run-activity__body markdown"
      data-activity-group={entry.groupKey || undefined}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-activity-order={formatActivityOrder(entry.order)}
      data-activity-source={activitySourcesLabel(entry)}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {entry.text}
      </ReactMarkdown>
    </div>
  );
}

function ToolWindow({ entry }: { entry: ActivityEntry }) {
  const defaultOpen = !entry.collapsed;
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className="public-run-activity__tool-window"
      data-activity-group={entry.groupKey || undefined}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-activity-order={formatActivityOrder(entry.order)}
      data-activity-source={activitySourcesLabel(entry)}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>{entry.text}</summary>
      {entry.toolWindow ? (
        <div className="public-run-activity__tool-window-body">
          {entry.toolWindow.meta.length ? (
            <div className="public-run-activity__tool-meta">
              {entry.toolWindow.meta.map((item) => <span key={item}>{item}</span>)}
            </div>
          ) : null}
          {entry.toolWindow.sections.length ? (
            <dl className="public-run-activity__tool-snapshot">
              {entry.toolWindow.sections.map((section) => (
                <div key={`${section.label}:${section.text}`}>
                  <dt>{section.label}</dt>
                  <dd>{section.text}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : entry.detail ? (
        <div className="public-run-activity__tool-window-body">
          <p>{entry.detail}</p>
        </div>
      ) : null}
    </details>
  );
}

function formatActivityOrder(value: number | undefined) {
  if (!Number.isFinite(value)) {
    return undefined;
  }
  return Number(value).toFixed(4).replace(/\.?0+$/g, "");
}

function activitySourcesLabel(entry: ActivityEntry) {
  return (entry.sources?.length ? entry.sources : sourceList(entry.source)).join("+") || undefined;
}
