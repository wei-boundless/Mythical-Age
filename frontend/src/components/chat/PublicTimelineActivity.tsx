"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { looksLikeRawToolOutput } from "@/components/chat/agentRunProjection";
import type { PublicChatTimelineItem, SingleAgentTaskProjection } from "@/lib/api";
import { cleanPublicTimelineText, isPublicTimelineControlItem, normalizePublicTimelineItems } from "@/lib/projection/timeline";

type PublicTimelineActivityProps = {
  items?: PublicChatTimelineItem[] | null;
  taskProjections?: SingleAgentTaskProjection[] | null;
  compactCompletedTools?: boolean;
};

type PublicTimelineActivityOptions = {
  compactCompletedTools?: boolean;
};

type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type ActivityEntrySource = "timeline" | "projection";

type ActivityEntry = {
  collapsed?: boolean;
  detail?: string;
  eventRefs?: string[];
  groupKey?: string;
  id: string;
  kind: "status" | "stopped" | "tool";
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

export function PublicTimelineActivity({ items, taskProjections, compactCompletedTools = false }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items, taskProjections, { compactCompletedTools });
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
        entry.kind === "tool"
          ? <ToolWindow entry={entry} key={entry.id || entry.text} />
        : <ActivityLine entry={entry} key={entry.id || entry.text} />
      ))}
    </div>
  );
}

export function publicTimelineHasDisplayableActivity(
  items: PublicChatTimelineItem[] | null | undefined,
  taskProjections?: SingleAgentTaskProjection[] | null,
  options: PublicTimelineActivityOptions = {},
) {
  return Boolean(publicTimelineActivityView(items, taskProjections, options));
}

function publicTimelineActivityView(
  items: PublicChatTimelineItem[] | null | undefined,
  taskProjections?: SingleAgentTaskProjection[] | null,
  options: PublicTimelineActivityOptions = {},
): PublicTimelineActivityView | null {
  const normalizedItems = normalizePublicTimelineItems(items ?? []).filter((item) => !isPublicTimelineControlItem(item));
  const projections = taskProjections ?? [];
  const projectionTone = taskProjectionTone(projections);
  const timelineItems = projectionTone && projectionTone !== "running"
    ? normalizedItems.filter((item) => !isStalePublicTimelineItemForProjectionTone(item, projectionTone))
    : normalizedItems;
  const projectionEntries = taskProjectionActivityEntries(projections);
  const timelineEntries = activityEntries(timelineItems, options);
  const entries = orderActivityEntries({
    timelineEntries,
    projectionEntries,
  });
  if (!entries.length) {
    return null;
  }
  return {
    entries,
    tone: projectionTone || publicTimelineTone(timelineItems),
  };
}

function taskProjectionActivityEntries(projections: SingleAgentTaskProjection[]): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  let sourceIndex = 0;
  const pushEntry = (entry: ActivityEntry | null) => {
    if (!entry) {
      return;
    }
    entries.push(finalizeActivityEntry(entry, "projection", sourceIndex++));
  };
  for (const projection of projections) {
    const projectionId = cleanPublicTimelineText(projection.projection_id || projection.task_run_id);
    const projectionTone = taskProjectionStatusTone(projection.status);
    const lifecycleEntry = taskProjectionLifecycleEntry(projection, projectionId, projectionTone);
    if (lifecycleEntry) {
      pushEntry(lifecycleEntry);
    } else {
      const currentAction = taskProjectionCurrentActionEntry(projection, projectionId);
      if (currentAction) {
        pushEntry(currentAction);
      } else {
        const todoEntry = taskProjectionTodoStatusEntry(projection, projectionId);
        if (todoEntry) {
          pushEntry(todoEntry);
        }
      }
    }
    for (const activity of projection.activities ?? []) {
      const entry = taskProjectionActivityEntry(activity, projectionId, projectionTone);
      pushEntry(entry);
    }
    for (const artifact of projection.artifact_refs ?? []) {
      const label = cleanPublicTimelineText(artifact.label ?? artifact.path ?? artifact.href ?? artifact.value);
      if (!label) continue;
      pushEntry({
        id: `${projectionId}:artifact:${label}`,
        kind: "status",
        state: "done",
        text: "产物已更新",
        detail: label,
      });
    }
  }
  return entries;
}

function taskProjectionLifecycleEntry(
  projection: SingleAgentTaskProjection,
  projectionId: string,
  projectionTone: PublicTimelineActivityTone | "",
): ActivityEntry | null {
  if (!projectionTone || projectionTone === "running" || projectionTone === "done") {
    return null;
  }
  const status = cleanPublicTimelineText(projection.status).toLowerCase();
  const current = projection.current_action;
  const currentRecord = current && typeof current === "object" && !Array.isArray(current)
    ? current
    : {};
  const currentTitle = cleanPublicTimelineText(currentRecord.title ?? currentRecord.phase);
  const currentDetail = cleanPublicTimelineText(currentRecord.detail);
  const currentState = cleanPublicTimelineText(currentRecord.state).toLowerCase();
  const title = currentTitle
    && !isActiveTaskProjectionActivityState(currentState)
    && !isGenericStatusActivity(currentTitle, currentDetail)
    ? currentTitle
    : taskProjectionLifecycleTitle(status);
  const detail = currentDetail && currentDetail !== title && !isGenericStatusActivity(currentTitle, currentDetail)
    ? currentDetail
    : "";
  return {
    detail,
    id: `${projectionId}:lifecycle:${status || projectionTone}`,
    kind: projectionTone === "waiting" ? "status" : "stopped",
    state: status || projectionTone,
    text: title,
  };
}

function taskProjectionCurrentActionEntry(projection: SingleAgentTaskProjection, projectionId: string): ActivityEntry | null {
  const current = projection.current_action;
  if (!current || typeof current !== "object" || Array.isArray(current)) {
    return null;
  }
  const title = cleanPublicTimelineText(current.title ?? current.phase);
  const detail = cleanPublicTimelineText(current.detail);
  if (!title && !detail) {
    return null;
  }
  if (isHiddenByTaskProjectionLevel(current)) {
    return null;
  }
  if (isGenericStatusActivity(title, detail)) {
    return null;
  }
  const state = cleanPublicTimelineText(current.state).toLowerCase();
  return {
    eventRefs: eventRefsFromUnknown(current.event_ref),
    id: `${projectionId}:current:${cleanPublicTimelineText(current.event_ref) || title || detail}`,
    kind: "status",
    state,
    text: title || detail,
    detail,
  };
}

function taskProjectionTodoStatusEntry(projection: SingleAgentTaskProjection, projectionId: string): ActivityEntry | null {
  const todo = projection.todo;
  const items = Array.isArray(todo?.items) ? todo.items : [];
  if (!items.length) {
    return null;
  }
  const completed = Number.isFinite(Number(todo?.completed_count))
    ? Number(todo?.completed_count)
    : items.filter((item) => cleanPublicTimelineText(item.status).toLowerCase() === "completed").length;
  const total = Number.isFinite(Number(todo?.total_count)) && Number(todo?.total_count) > 0
    ? Number(todo?.total_count)
    : items.length;
  const hasActive = Boolean(cleanPublicTimelineText(todo?.active_item_id));
  const detail = [
    total ? `${completed}/${total} 已完成` : "",
    hasActive ? "当前阶段正在推进" : "",
  ].filter(Boolean).join("；");
  if (!detail) {
    return null;
  }
  return {
    detail,
    eventRefs: eventRefsFromUnknown((todo as Record<string, unknown>)?.trace_refs),
    id: `${projectionId}:todo:${cleanPublicTimelineText(todo?.plan_id) || detail}`,
    kind: "status",
    state: completed >= total ? "completed" : "running",
    text: "任务进度",
  };
}

function taskProjectionActivityEntry(
  activity: NonNullable<SingleAgentTaskProjection["activities"]>[number],
  projectionId: string,
  projectionTone: PublicTimelineActivityTone | "",
): ActivityEntry | null {
  if (!activity || typeof activity !== "object") {
    return null;
  }
  if (isStaleTaskProjectionActivityForProjectionTone(activity, projectionTone)) {
    return null;
  }
  const title = cleanPublicTimelineText(activity.title);
  const detail = cleanPublicTimelineText(activity.detail);
  if (!title && !detail) {
    return null;
  }
  if (isHiddenByTaskProjectionLevel(activity)) {
    return null;
  }
  if (isLowSignalTaskProjectionActivity(activity, title, detail)) {
    return null;
  }
  const kind = cleanPublicTimelineText(activity.kind).toLowerCase();
  const state = cleanPublicTimelineText(activity.state).toLowerCase();
  const displaySurface = cleanPublicTimelineText(activity.display_surface).toLowerCase();
  const isObservation = kind === "observation";
  const entryKind: ActivityEntry["kind"] = displaySurface === "tool_window"
    ? "tool"
    : kind === "error" || state === "failed"
      ? "stopped"
      : "status";
  const observationDetail = [title, detail].filter(Boolean).join("\n");
  const sourceKind = cleanPublicTimelineText(activity.source_kind);
  const toolName = cleanPublicTimelineText(activity.tool_name);
  const toolTarget = cleanPublicTimelineText(activity.tool_target);
  return {
    collapsed: entryKind === "tool" ? true : undefined,
    eventRefs: eventRefsFromUnknown(activity.event_ref),
    id: `${projectionId}:activity:${cleanPublicTimelineText(activity.activity_id) || cleanPublicTimelineText(activity.event_ref) || title || detail}`,
    kind: entryKind,
    actionKind: sourceKind,
    state,
    text: isObservation && entryKind !== "tool" ? "任务观察" : title || detail,
    detail: isObservation && entryKind !== "tool" ? observationDetail : detail && detail !== title ? detail : "",
    toolName,
    toolTarget,
    toolWindow: entryKind === "tool"
      ? {
          meta: taskProjectionToolMeta(activity, state),
          sections: detail && detail !== title ? [{ label: "结果", text: detail }] : [],
        }
      : undefined,
  };
}

function orderActivityEntries({
  timelineEntries,
  projectionEntries,
}: {
  timelineEntries: ActivityEntry[];
  projectionEntries: ActivityEntry[];
}) {
  return mergeAndOrderActivityEntries([...timelineEntries, ...projectionEntries]);
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
    const text = shortText(cleanPublicTimelineText(section.text), 260);
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

function isHiddenByTaskProjectionLevel(activity: Record<string, unknown>) {
  const level = cleanPublicTimelineText(activity.visibility_level).toLowerCase();
  const displaySurface = cleanPublicTimelineText(activity.display_surface).toLowerCase();
  if (["debug", "internal"].includes(level)) {
    return true;
  }
  if (["diagnostics", "debug", "monitor"].includes(displaySurface)) {
    return true;
  }
  return false;
}

function isLowSignalTaskProjectionActivity(
  activity: NonNullable<SingleAgentTaskProjection["activities"]>[number],
  title: string,
  detail: string,
) {
  const sourceKind = cleanPublicTimelineText(activity.source_kind).toLowerCase();
  const level = cleanPublicTimelineText(activity.visibility_level).toLowerCase();
  const displaySurface = cleanPublicTimelineText(activity.display_surface).toLowerCase();
  if (isEmptyGenericToolWindowActivity(activity, title, detail)) {
    return true;
  }
  if (["primary", "secondary"].includes(level) && !["diagnostics", "debug", "monitor"].includes(displaySurface)) {
    return false;
  }
  const textBlob = `${title}\n${detail}`;
  if (["inspect_path", "search_text", "verification"].includes(sourceKind)) {
    return true;
  }
  if (sourceKind === "tool_action" && mentionsInternalTool(textBlob)) {
    return true;
  }
  if (isGenericTaskProjectionTitle(title, detail) || hasGenericToolFailure(textBlob)) {
    return true;
  }
  if (sourceKind === "stage" && (isGenericStatusActivity(title, detail) || mentionsInternalTool(textBlob) || isGenericToolCallStage(title, detail))) {
    return true;
  }
  return false;
}

function isEmptyGenericToolWindowActivity(
  activity: NonNullable<SingleAgentTaskProjection["activities"]>[number],
  title: string,
  detail: string,
) {
  const displaySurface = cleanPublicTimelineText(activity.display_surface).toLowerCase();
  if (displaySurface !== "tool_window") {
    return false;
  }
  if (cleanPublicTimelineText(detail) || cleanPublicTimelineText(activity.tool_target)) {
    return false;
  }
  const normalizedTitle = compactActivityText(title).replace(/[。.]$/g, "");
  return [
    "正在执行操作",
    "执行动作",
    "操作已返回",
    "结果已返回",
    "步骤未完成",
  ].map(compactActivityText).includes(normalizedTitle);
}

function mentionsInternalTool(value: string) {
  const normalized = value.toLowerCase().replace(/[-\s]+/g, "_");
  return [
    "agent_todo",
    "list_subagents",
    "spawn_subagent",
    "wait_subagent",
    "send_subagent_message",
    "close_subagent",
  ].some((toolName) => normalized.includes(toolName));
}

function hasGenericToolFailure(value: string) {
  const normalized = compactActivityText(value);
  return [
    "工具调用失败，正在根据失败原因调整处理路径。",
    "工具返回失败：工具调用失败",
    "正在根据失败原因调整处理路径",
  ].some((fragment) => normalized.includes(compactActivityText(fragment)));
}

function isGenericTaskProjectionTitle(title: string, detail: string) {
  const normalizedTitle = compactActivityText(title).replace(/[。.]$/g, "");
  const normalizedDetail = compactActivityText(detail).replace(/[。.]$/g, "");
  const genericTitles = new Set([
    "开始处理",
    "建立处理清单",
    "更新处理清单",
    "处理清单",
    "处理清单已建立",
    "处理清单已更新",
    "读取文件内容",
    "检查路径信息",
    "确认路径状态",
    "确认artifact路径",
    "搜索证据",
    "补齐验收证据",
    "正在处理",
    "正在建立任务运行",
    "正在思考",
    "正在整理回复",
  ].map(compactActivityText));
  return genericTitles.has(normalizedTitle) && (!normalizedDetail || normalizedDetail === normalizedTitle);
}

function compactActivityText(value: string) {
  return String(value ?? "").replace(/\s+/g, "").toLowerCase();
}

function isGenericToolCallStage(title: string, detail: string) {
  const normalized = `${title}\n${detail}`.toLowerCase();
  return normalized.includes("工具调用") && (/执行\s*\d+\s*个工具调用/.test(normalized) || normalized.includes("tool call"));
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

function taskProjectionToolMeta(
  activity: NonNullable<SingleAgentTaskProjection["activities"]>[number],
  state: string,
) {
  const target = shortText(cleanPublicTimelineText(activity.tool_target), 90);
  const toolName = shortText(cleanPublicTimelineText(activity.tool_name), 48);
  return [
    target,
    target ? "" : toolName,
    readableTaskActivityState(state),
  ].filter(Boolean);
}

function readableTaskActivityState(state: string) {
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "已完成";
  if (["running", "working", "partial", ""].includes(state)) return "运行中";
  if (["waiting", "waiting_user", "waiting_approval", "waiting_safe_boundary", "queued", "paused"].includes(state)) return "等待中";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "失败";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "已停止";
  return shortText(state, 48);
}

function activityEntries(items: PublicChatTimelineItem[], options: PublicTimelineActivityOptions = {}): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  for (const [index, item] of items.entries()) {
    if (kindOf(item) === "todo_plan") {
      continue;
    }
    if (isLowSignalCompletedToolActivity(item, options)) {
      continue;
    }
    const kind = activityLineKind(item);
    if (!kind) {
      continue;
    }
    const text = publicText(item);
    if (!text) {
      continue;
    }
    const detail = kind === "tool" ? toolDetailText(item, text) : statusDetailText(item, text);
    if (kind === "status" && isGenericStatusActivity(text, detail)) {
      continue;
    }
    const toolTarget = publicTimelineToolTarget(item);
    entries.push({
      collapsed: kind === "tool" ? shouldCollapseToolWindow(item) : undefined,
      detail,
      eventRefs: eventRefsFromUnknown(item.trace_refs),
      id: String(item.item_id ?? "") || `${kind}:${index}:${text}`,
      kind,
      actionKind: cleanPublicTimelineText(item.action_kind),
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
  return cleanPublicTimelineText(item.tool_window?.target)
    || cleanPublicTimelineText(item.subject_label)
    || cleanPublicTimelineText(item.path)
    || cleanPublicTimelineText(item.href);
}

function activityLineKind(item: PublicChatTimelineItem): ActivityEntry["kind"] | "" {
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  if (slot === "tool") return "tool";
  if (slot === "status" || slot === "timeline" || slot === "task") return "status";
  if (slot === "control") return "";
  return "";
}

function isLowSignalCompletedToolActivity(item: PublicChatTimelineItem, options: PublicTimelineActivityOptions = {}) {
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  if (slot !== "tool") {
    return false;
  }
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const phase = cleanPublicTimelineText(item.phase).toLowerCase();
  const done = phase === "done" || ["completed", "complete", "done", "ready", "passed", "success"].includes(state);
  const failed = ["error", "failed", "blocked", "missing"].includes(state);
  if (!done || failed) {
    return false;
  }
  const actionKind = cleanPublicTimelineText(item.action_kind).toLowerCase();
  const title = cleanPublicTimelineText(item.title);
  const normalizedTitle = compactActivityText(title).replace(/[。.]$/g, "");
  const rawOutputSuppressed = (item as { raw_output_suppressed?: unknown }).raw_output_suppressed === true;
  if (rawOutputSuppressed && ["读取完成", "已读取完成", "读取已完成", "工具已完成", "操作已返回", "结果已返回"].map(compactActivityText).includes(normalizedTitle)) {
    return true;
  }
  const hasMeaningfulPayload = hasMeaningfulCompletedToolPayload(item);
  if (!hasMeaningfulPayload && isGenericCompletedToolText(title) && isGenericCompletedToolText(item.public_summary)) {
    return true;
  }
  if (options.compactCompletedTools && !hasMeaningfulPayload) {
    return true;
  }
  return ["inspect", "search"].includes(actionKind)
    || title.startsWith("已确认目标")
    || title.startsWith("已搜索引用");
}

function hasMeaningfulCompletedToolPayload(item: PublicChatTimelineItem) {
  for (const candidate of [item.public_summary, item.observation, item.detail, item.recovery_hint, item.implication, item.next_step, item.text, item.path, item.href]) {
    const text = cleanPublicTimelineText(candidate);
    if (!text || looksLikeRawToolOutput(text) || isGenericCompletedToolText(text)) {
      continue;
    }
    return true;
  }
  return false;
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

function shouldCollapseToolWindow(item: PublicChatTimelineItem) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const running = ["", "running", "working", "partial"].includes(state) || item.stream_state === "streaming";
  const failed = ["error", "failed", "blocked", "missing"].includes(state);
  if (running || failed) return false;
  if (typeof item.collapsed === "boolean") return item.collapsed;
  return Boolean(item.collapse_after_body_feedback);
}

function publicTimelineTone(items: PublicChatTimelineItem[]): PublicTimelineActivityTone {
  const state = items.map((item) => String(item.state ?? "").trim().toLowerCase()).reverse().find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function taskProjectionTone(projections: SingleAgentTaskProjection[]): PublicTimelineActivityTone | "" {
  const status = projections.map((projection) => cleanPublicTimelineText(projection.status).toLowerCase()).reverse().find(Boolean) ?? "";
  return taskProjectionStatusTone(status);
}

function taskProjectionStatusTone(status: unknown): PublicTimelineActivityTone | "" {
  const normalized = cleanPublicTimelineText(status).toLowerCase();
  if (!normalized) return "";
  if (["failed", "error", "blocked", "missing"].includes(normalized)) return "soft_error";
  if (["waiting", "waiting_user", "waiting_executor", "waiting_approval", "waiting_safe_boundary", "queued", "paused"].includes(normalized)) return "waiting";
  if (["completed", "complete", "done", "success"].includes(normalized)) return "done";
  if (["stopped", "cancelled", "canceled", "aborted"].includes(normalized)) return "stopped";
  return "running";
}

function taskProjectionLifecycleTitle(status: string) {
  if (["stopped", "cancelled", "canceled", "aborted"].includes(status)) return "任务已停止";
  if (status === "paused") return "任务已暂停";
  if (["waiting_user", "waiting_executor"].includes(status)) return "等待继续";
  if (status === "waiting_safe_boundary") return "等待安全边界";
  if (status === "waiting_approval") return "等待确认";
  if (status === "queued") return "等待执行";
  if (["failed", "error", "blocked", "missing"].includes(status)) return "任务执行失败";
  return "任务状态已更新";
}

function isActiveTaskProjectionActivityState(state: string) {
  return ["", "running", "working", "partial"].includes(state);
}

function isStaleTaskProjectionActivityForProjectionTone(
  activity: NonNullable<SingleAgentTaskProjection["activities"]>[number],
  projectionTone: PublicTimelineActivityTone | "",
) {
  if (!projectionTone || projectionTone === "running") {
    return false;
  }
  if (cleanPublicTimelineText(activity.kind) === "todo") {
    return false;
  }
  const state = cleanPublicTimelineText(activity.state).toLowerCase();
  return isActiveTaskProjectionActivityState(state) || ["waiting", "queued", "paused"].includes(state);
}

function isStalePublicTimelineItemForProjectionTone(
  item: PublicChatTimelineItem,
  projectionTone: PublicTimelineActivityTone,
) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  if (isActivePublicTimelineItem(item)) {
    return true;
  }
  return ["waiting", "queued", "paused"].includes(state);
}

function isActivePublicTimelineItem(item: PublicChatTimelineItem) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const phase = cleanPublicTimelineText(item.phase).toLowerCase();
  const slot = cleanPublicTimelineText((item as { slot?: unknown }).slot).toLowerCase();
  if (item.stream_state === "streaming") return true;
  if (["running", "working", "partial"].includes(state)) return true;
  if (["running", "working", "partial", "streaming"].includes(phase)) return true;
  if (!state && ["tool", "status", "timeline"].includes(slot)) {
    return true;
  }
  return false;
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
    const text = cleanPublicTimelineText(candidate);
    if (text && !looksLikeRawToolOutput(text)) {
      return text;
    }
  }
  return "";
}

function toolDetailText(item: PublicChatTimelineItem, summary: string) {
  const candidates = [item.observation, item.detail, item.recovery_hint, item.path, item.href];
  for (const candidate of candidates) {
    const text = cleanPublicTimelineText(candidate);
    if (text && text !== summary && !looksLikeRawToolOutput(text)) {
      return shortText(text, 260);
    }
  }
  return "";
}

function statusDetailText(item: PublicChatTimelineItem, summary: string) {
  const candidates = [item.detail, item.observation, item.public_summary, item.text];
  for (const candidate of candidates) {
    const text = cleanPublicTimelineText(candidate);
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
      text: shortText(cleanPublicTimelineText(section?.text), 260),
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
  ].map((value) => shortText(cleanPublicTimelineText(value), 90)).filter(Boolean).slice(0, 3);
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
