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

type ActivityEntry = {
  collapsed?: boolean;
  detail?: string;
  id: string;
  kind: "status" | "stopped" | "tool";
  text: string;
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
    <div className={`public-run-activity public-run-activity--${view.tone}`} aria-label="处理进展">
      {view.entries.map((entry) => (
        entry.kind === "tool"
          ? <ToolWindow entry={entry} key={entry.id || entry.text} />
        : <ActivityLine detail={entry.detail} kind={entry.kind} key={entry.id || entry.text} text={entry.text} />
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
  for (const projection of projections) {
    const projectionId = cleanPublicTimelineText(projection.projection_id || projection.task_run_id);
    const projectionTone = taskProjectionStatusTone(projection.status);
    const lifecycleEntry = taskProjectionLifecycleEntry(projection, projectionId, projectionTone);
    if (lifecycleEntry) {
      entries.push(lifecycleEntry);
    } else {
      const currentAction = taskProjectionCurrentActionEntry(projection, projectionId);
      if (currentAction) {
        entries.push(currentAction);
      }
    }
    for (const activity of projection.activities ?? []) {
      const entry = taskProjectionActivityEntry(activity, projectionId, projectionTone);
      if (entry) {
        entries.push(entry);
      }
    }
    for (const artifact of projection.artifact_refs ?? []) {
      const label = cleanPublicTimelineText(artifact.label ?? artifact.path ?? artifact.href ?? artifact.value);
      if (!label) continue;
      entries.push({
        id: `${projectionId}:artifact:${label}`,
        kind: "status",
        text: "产物已更新",
        detail: label,
      });
    }
  }
  return dedupeActivityEntries(entries);
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
  return {
    id: `${projectionId}:current:${cleanPublicTimelineText(current.event_ref) || title || detail}`,
    kind: "status",
    text: title || detail,
    detail,
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
  return {
    collapsed: entryKind === "tool" ? true : undefined,
    id: `${projectionId}:activity:${cleanPublicTimelineText(activity.activity_id) || cleanPublicTimelineText(activity.event_ref) || title || detail}`,
    kind: entryKind,
    text: isObservation && entryKind !== "tool" ? "任务观察" : title || detail,
    detail: isObservation && entryKind !== "tool" ? observationDetail : detail && detail !== title ? detail : "",
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
  const timelineFeedback = timelineEntries.filter((entry) => entry.kind !== "tool");
  const timelineTools = timelineEntries.filter((entry) => entry.kind === "tool");
  const projectionFeedback = projectionEntries.filter((entry) => entry.kind !== "tool");
  return [...timelineFeedback, ...projectionFeedback, ...timelineTools];
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

function dedupeActivityEntries(entries: ActivityEntry[]) {
  const seen = new Set<string>();
  const result: ActivityEntry[] = [];
  for (const entry of entries) {
    const key = entry.id || `${entry.kind}:${entry.text}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(entry);
  }
  return result;
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
    entries.push({
      collapsed: kind === "tool" ? shouldCollapseToolWindow(item) : undefined,
      detail,
      id: String(item.item_id ?? "") || `${kind}:${index}:${text}`,
      kind,
      text: shortText(text, kind === "tool" ? 180 : 220),
      toolWindow: kind === "tool" ? toolWindowProjection(item, detail) : undefined,
    });
  }
  return entries;
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

function ActivityLine({
  detail,
  kind,
  text,
}: {
  detail?: string;
  kind: "status" | "stopped";
  text: string;
}) {
  const detailMarkdown = detail ? activityDetailMarkdown(detail) : "";
  return (
    <div className={`public-run-activity__line public-run-activity__line--${kind}`}>
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
