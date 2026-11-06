"use client";

import { ChevronDown, Sparkles } from "lucide-react";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StatusLine, toolRoundStatusLabel } from "./AssistantTrace";
import { TodoPlan } from "./TodoPlan";
import { ToolRound, ToolWindow } from "./ToolTrace";

import { workbenchMarkdownComponents } from "@/components/markdown/WorkbenchMarkdownComponents";
import { publicRuntimeStatusText } from "@/lib/runtimeStatusText";
import { TOOL_ACTION_LABELS, displayToolActionName, isCommandToolName, toolDisplayFamily } from "@/lib/toolDisplay";
import type {
  ActivityArchiveProjectionBlock,
  ProjectionRenderBlock,
  StatusProjectionBlock,
  TodoPlanProjectionBlock,
  ToolProjectionBlock,
} from "@/lib/projection/chronological";

type PublicTimelineActivityProps = {
  ariaLabel?: string;
  blocks?: ProjectionRenderBlock[] | null;
  hideTodoPlans?: boolean;
};

type PublicTimelineActivityOptions = {
  hideTodoPlans?: boolean;
};

export type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

export type ActivityEntry = {
  collapsed?: boolean;
  commandLine?: string;
  consoleLabel?: string;
  contentWindow?: ToolProjectionBlock["contentWindow"];
  detail?: string;
  id: string;
  kind: "activity_archive" | "body_note" | "reasoning_window" | "status_line" | "todo_plan" | "tool_window";
  outputText?: string;
  polling?: ToolProjectionBlock["polling"];
  reasoningContent?: string;
  reasoningMeta?: string;
  sections: Array<{ label: string; text: string }>;
  startedAt?: number;
  updatedAt?: number;
  completedAt?: number;
  firstOffset?: number;
  lastOffset?: number;
  statusKind?: string;
  state?: string;
  statusLabel?: string;
  statusTone?: PublicTimelineActivityTone;
  text: string;
  toolFamily?: ToolUiFamily;
  todoItems?: TodoPlanProjectionBlock["items"];
  activeItemId?: string;
  completionReady?: boolean;
  toolRoundKey?: string;
  archivedEntries?: ActivityEntry[];
  archiveCount?: number;
  bodyText?: string;
};

export type ToolUiFamily =
  | "browser"
  | "command"
  | "data"
  | "file"
  | "generic"
  | "inspect"
  | "media"
  | "memory"
  | "search"
  | "write";

export type ActivityRenderUnit =
  | { kind: "entry"; entry: ActivityEntry }
  | {
      kind: "tool_round";
      count: number;
      entries: ActivityEntry[];
      id: string;
      preview: string;
      startedAt?: number;
      updatedAt?: number;
      completedAt?: number;
      firstOffset?: number;
      lastOffset?: number;
      statusLabel: string;
      statusTone: PublicTimelineActivityTone;
    };

export function PublicTimelineActivity({ ariaLabel = "运行状态", blocks, hideTodoPlans = false }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(blocks, { hideTodoPlans });
  if (!view.entries.length) {
    return null;
  }
  const rows = activityRenderRows(view.entries);

  return (
    <div
      className={`public-run-activity public-run-activity--${view.tone}`}
      aria-label={ariaLabel}
      data-entry-count={view.entries.length}
      data-row-count={rows.length}
    >
      {rows.map((row) => (
        renderActivityRow(row)
      ))}
    </div>
  );
}

export function publicTimelineHasDisplayableActivity(
  blocks: ProjectionRenderBlock[] | null | undefined,
  options: PublicTimelineActivityOptions = {},
) {
  return publicTimelineActivityView(blocks, options).entries.length > 0;
}

function publicTimelineActivityView(
  blocks: ProjectionRenderBlock[] | null | undefined,
  options: PublicTimelineActivityOptions = {},
) {
  const entries = (blocks ?? [])
    .map((block, index) => activityEntryFromBlock(block, index, { allowBody: false, hideTodoPlans: options.hideTodoPlans }))
    .filter((entry): entry is ActivityEntry => Boolean(entry));
  return {
    entries,
    tone: publicTimelineTone(entries),
  };
}

function activityRenderRows(entries: ActivityEntry[]): ActivityRenderUnit[] {
  const rows: ActivityRenderUnit[] = [];
  let roundTools: ActivityEntry[] = [];
  let roundKey = "";

  const flushRoundTools = () => {
    if (!roundTools.length) return;
    if (roundTools.length === 1) {
      rows.push({ kind: "entry", entry: roundTools[0] });
    } else {
      rows.push(toolRoundFromEntries(roundTools, roundKey));
    }
    roundTools = [];
    roundKey = "";
  };

  for (const entry of entries) {
    if (entry.kind !== "tool_window") {
      flushRoundTools();
      rows.push({ kind: "entry", entry });
      continue;
    }
    const nextRoundKey = entry.toolRoundKey ?? "";
    if (!nextRoundKey) {
      flushRoundTools();
      rows.push({ kind: "entry", entry });
      continue;
    }
    if (roundTools.length && nextRoundKey !== roundKey) {
      flushRoundTools();
    }
    roundKey = nextRoundKey;
    roundTools.push(entry);
  }
  flushRoundTools();
  return rows;
}

function renderActivityRow(row: ActivityRenderUnit): React.ReactNode {
  if (row.kind === "tool_round") {
    return <ToolRound group={row} key={row.id} />;
  }
  const { entry } = row;
  if (entry.kind === "activity_archive") {
    return <ActivityArchive entry={entry} key={entry.id} />;
  }
  if (entry.kind === "body_note") {
    return <BodyNote entry={entry} key={entry.id} />;
  }
  if (entry.kind === "reasoning_window") {
    return <ReasoningWindow entry={entry} key={entry.id} />;
  }
  if (entry.kind === "tool_window") {
    return <ToolWindow entry={entry} key={entry.id} />;
  }
  if (entry.kind === "todo_plan") {
    return <TodoPlan entry={entry} key={entry.id} />;
  }
  return <StatusLine entry={entry} key={entry.id} />;
}

function ActivityArchive({ entry }: { entry: ActivityEntry }) {
  const entries = entry.archivedEntries ?? [];
  const rows = activityRenderRows(entries);
  const statusTone = entry.statusTone ?? publicTimelineTone(entries);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    setOpen(false);
  }, [entry.id]);

  return (
    <details
      className={`public-run-activity__archive public-run-activity__archive--${statusTone}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-archive-count={entry.archiveCount ?? entries.length}
      data-status-tone={statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__archive-label">记录</span>
        <span className="public-run-activity__archive-rule" aria-hidden="true" />
        <span className="public-run-activity__archive-meta">
          {entry.detail || `${entry.archiveCount ?? entries.length} 条`}
        </span>
        <span className="public-run-activity__archive-caret" aria-hidden="true" />
      </summary>
      <div className="public-run-activity__archive-body">
        {rows.map((row) => renderActivityRow(row))}
      </div>
    </details>
  );
}

function BodyNote({ entry }: { entry: ActivityEntry }) {
  const statusTone = entry.statusTone ?? "done";
  const bodyText = entry.bodyText || entry.text;
  return (
    <div
      className={`public-run-activity__body-note public-run-activity__body-note--${statusTone}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-status-tone={statusTone}
    >
      <div className="public-run-activity__body markdown">
        <ReactMarkdown components={workbenchMarkdownComponents} remarkPlugins={[remarkGfm]}>
          {bodyText}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function ReasoningWindow({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = React.useState(false);
  const statusTone = entry.statusTone ?? "done";
  const reasoningContent = entry.reasoningContent || entry.detail || "";

  React.useEffect(() => {
    setOpen(false);
  }, [entry.id]);

  return (
    <details
      className={`public-run-activity__reasoning-window public-run-activity__reasoning-window--${statusTone}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.statusKind || entry.kind}
      data-status-tone={statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__reasoning-icon" aria-hidden="true">
          <Sparkles size={15} />
        </span>
        <span className="public-run-activity__reasoning-copy">
          <span className="public-run-activity__reasoning-title">
            <span>{entry.text || "模型思考"}</span>
            <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${statusTone}`}>
              <span className="public-run-activity__tool-status-dot" aria-hidden="true" />
              <span className="public-run-activity__tool-status-text">{entry.statusLabel || "已记录"}</span>
            </span>
          </span>
          {entry.reasoningMeta ? <span className="public-run-activity__reasoning-meta">{entry.reasoningMeta}</span> : null}
        </span>
        <span className="public-run-activity__reasoning-caret" aria-hidden="true">
          <ChevronDown size={14} />
        </span>
      </summary>
      {open ? (
        <div className="public-run-activity__reasoning-body" role="region" aria-label="运行中的模型思考观察">
          {reasoningContent ? (
            <div className="public-run-activity__reasoning-text markdown markdown--reasoning-projection">
              <ReactMarkdown components={workbenchMarkdownComponents} remarkPlugins={[remarkGfm]}>
                {reasoningContent}
              </ReactMarkdown>
            </div>
          ) : (
            <p>暂无可见思考内容。</p>
          )}
        </div>
      ) : null}
    </details>
  );
}

function toolRoundFromEntries(entries: ActivityEntry[], roundKey: string): ActivityRenderUnit {
  const statusTone = publicTimelineTone(entries);
  const count = entries.length;
  return {
    kind: "tool_round",
    count,
    completedAt: latestToolTime(entries, "completedAt"),
    entries,
    firstOffset: earliestToolOffset(entries, "firstOffset"),
    id: `tool-round:${roundKey || entries[0]?.id || "tools"}`,
    lastOffset: latestToolOffset(entries, "lastOffset"),
    preview: toolRoundPreview(entries),
    startedAt: earliestToolTime(entries, "startedAt"),
    statusLabel: toolRoundStatusLabel(statusTone),
    statusTone,
    updatedAt: latestToolTime(entries, "updatedAt"),
  };
}

function earliestToolTime(entries: ActivityEntry[], key: "startedAt" | "updatedAt" | "completedAt") {
  const values = entries
    .map((entry) => entry[key])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
  return values.length ? Math.min(...values) : undefined;
}

function latestToolTime(entries: ActivityEntry[], key: "startedAt" | "updatedAt" | "completedAt") {
  const values = entries
    .map((entry) => entry[key])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
  return values.length ? Math.max(...values) : undefined;
}

function earliestToolOffset(entries: ActivityEntry[], key: "firstOffset" | "lastOffset") {
  const values = entries
    .map((entry) => entry[key])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0);
  return values.length ? Math.min(...values) : undefined;
}

function latestToolOffset(entries: ActivityEntry[], key: "firstOffset" | "lastOffset") {
  const values = entries
    .map((entry) => entry[key])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0);
  return values.length ? Math.max(...values) : undefined;
}

function toolRoundPreview(entries: ActivityEntry[]) {
  const parts = entries.map(toolPreviewPart).filter((part) => part.action || part.target);
  const firstAction = parts[0]?.action ?? "";
  const sameAction = Boolean(firstAction) && parts.every((part) => part.action === firstAction);
  const preview = sameAction
    ? `${firstAction} ${parts.map((part) => part.target).filter(Boolean).slice(0, 3).join("、")}`.trim()
    : parts
        .map((part) => [part.action, part.target].filter(Boolean).join(" "))
        .filter(Boolean)
        .slice(0, 3)
        .join(" / ");
  if (!preview) {
    return "工具运行记录";
  }
  return entries.length > 3 ? `${preview} 等` : preview;
}

function toolPreviewPart(entry: ActivityEntry) {
  const text = cleanText(entry.text);
  for (const label of TOOL_ACTION_LABELS) {
    if (text === label) return { action: label, target: "" };
    if (text.startsWith(`${label} `)) return { action: label, target: cleanText(text.slice(label.length)) };
    if (text.startsWith(`${label}：`)) return { action: label, target: cleanText(text.slice(label.length + 1)) };
  }
  return { action: "", target: text };
}

function activityEntryFromBlock(
  block: ProjectionRenderBlock,
  index: number,
  options: { allowBody: boolean; hideTodoPlans?: boolean },
): ActivityEntry | null {
  if (block.kind === "body_segment") {
    return options.allowBody ? bodyEntryFromBlock(block, index) : null;
  }
  if (block.kind === "log_entry") {
    return null;
  }
  if (block.kind === "activity_archive") {
    return archiveEntryFromBlock(block, index, { hideTodoPlans: options.hideTodoPlans });
  }
  if (block.kind === "todo_plan") {
    if (options.hideTodoPlans) {
      return null;
    }
    return todoEntryFromBlock(block, index);
  }
  if (block.kind === "status_event" || block.kind === "recovery_event" || block.kind === "terminal_event") {
    return statusEntryFromBlock(block, index);
  }
  if (block.kind === "tool_event") {
    return toolEntryFromBlock(block, index);
  }
  return null;
}

function archiveEntryFromBlock(
  block: ActivityArchiveProjectionBlock,
  index: number,
  options: { hideTodoPlans?: boolean } = {},
): ActivityEntry | null {
  const entries = (block.blocks ?? [])
    .map((item, childIndex) => activityEntryFromBlock(item, childIndex, { allowBody: true, hideTodoPlans: options.hideTodoPlans }))
    .filter((entry): entry is ActivityEntry => Boolean(entry));
  if (!entries.length) {
    return null;
  }
  const stableId = cleanText(block.id) || `archive:${index}`;
  const statusTone = publicTimelineTone(entries);
  return {
    archivedEntries: entries,
    archiveCount: entries.length,
    detail: firstText(block.detail) || `${entries.length} 条`,
    id: `activity-archive:${stableId}`,
    kind: "activity_archive",
    sections: [],
    state: cleanText(block.state).toLowerCase(),
    statusTone,
    text: "",
  };
}

function bodyEntryFromBlock(block: Extract<ProjectionRenderBlock, { kind: "body_segment" }>, index: number): ActivityEntry | null {
  const bodyText = displayText(block.text);
  if (!bodyText) return null;
  const stableId = cleanText(block.id) || `body:${index}`;
  return {
    bodyText,
    id: `body-note:${stableId}`,
    kind: "body_note",
    sections: [],
    state: cleanText(block.state).toLowerCase() || "done",
    statusTone: "done",
    text: bodyText,
  };
}

function toolEntryFromBlock(block: ToolProjectionBlock, index: number): ActivityEntry | null {
  if (cleanText(block.toolName).toLowerCase() === "agent_todo") {
    return null;
  }
  const text = toolWindowTitle(block);
  if (!text) {
    return null;
  }
  const sections = toolWindowSections(block);
  const outputText = toolWindowOutputText(block, sections);
  let detail = firstDifferentToolText(text, block.detail);
  if (
    sections.some((section) => compactText(section.text) === compactText(detail))
    || compactText(outputText) === compactText(detail)
  ) {
    detail = "";
  }
  const stableId = cleanText(block.id) || cleanText(block.sourceEventId) || `tool:${index}`;
  const toolFamily = toolWindowFamily(block);
  return {
    collapsed: typeof block.collapsed === "boolean" ? block.collapsed : undefined,
    commandLine: toolWindowCommandLine(block, sections),
    consoleLabel: toolWindowConsoleLabel(block),
    contentWindow: block.contentWindow,
    completedAt: block.completedAt,
    detail,
    firstOffset: block.firstOffset,
    id: `tool-window:${stableId}`,
    kind: "tool_window",
    outputText,
    polling: block.polling,
    sections,
    startedAt: block.startedAt,
    state: cleanText(block.state).toLowerCase(),
    statusLabel: toolWindowStatusLabel(block),
    statusTone: toolWindowStatusTone(block),
    text,
    lastOffset: block.lastOffset,
    toolFamily,
    toolRoundKey: toolWindowRoundKey(block),
    updatedAt: block.updatedAt,
  };
}

function todoEntryFromBlock(block: TodoPlanProjectionBlock, index: number): ActivityEntry | null {
  const todoItems = (block.items ?? []).filter((todo) => cleanText(todo.content));
  if (!todoItems.length) {
    return null;
  }
  const stableId = cleanText(block.id) || cleanText(block.planId) || cleanText(block.sourceEventId) || `todo:${index}`;
  return {
    detail: firstDifferentText("任务清单", block.detail),
    id: `todo-plan:${stableId}`,
    kind: "todo_plan",
    sections: [],
    state: cleanText(block.state).toLowerCase(),
    text: firstText(block.title) || "任务清单",
    todoItems,
    activeItemId: cleanText(block.activeItemId),
    completionReady: block.completionReady,
  };
}

function statusEntryFromBlock(block: StatusProjectionBlock, index: number): ActivityEntry | null {
  if (cleanText(block.statusKind) === "reasoning_projection_state") {
    return reasoningEntryFromBlock(block, index);
  }
  const title = firstText(block.title) || statusKindLabel(block.kind);
  const detail = firstDifferentText(title, block.detail);
  const stableId = cleanText(block.id) || cleanText(block.sourceEventId) || `status:${index}`;
  const statusTone = statusBlockTone(block);
  return {
    detail,
    id: `status-line:${stableId}`,
    kind: "status_line",
    sections: [],
    state: cleanText(block.state).toLowerCase(),
    statusKind: cleanText(block.statusKind) || block.kind,
    statusLabel: statusBlockLabel(block, statusTone),
    statusTone,
    text: title,
  };
}

function reasoningEntryFromBlock(block: StatusProjectionBlock, index: number): ActivityEntry | null {
  const reasoningContent = typeof block.reasoningContent === "string" ? block.reasoningContent : "";
  const detail = firstDifferentText("模型思考", block.detail);
  const stableId = cleanText(block.id) || cleanText(block.sourceEventId) || `reasoning:${index}`;
  const statusTone = statusBlockTone(block);
  const meta = reasoningMetaFromBlock(block);
  return {
    detail,
    id: `reasoning-window:${stableId}`,
    kind: "reasoning_window",
    reasoningContent,
    reasoningMeta: meta,
    sections: [],
    state: cleanText(block.state).toLowerCase(),
    statusKind: cleanText(block.statusKind) || block.kind,
    statusLabel: statusBlockLabel(block, statusTone),
    statusTone,
    text: "模型思考",
  };
}

function reasoningMetaFromBlock(block: StatusProjectionBlock) {
  const parts = [];
  if (typeof block.reasoningContentEstimatedTokens === "number" && block.reasoningContentEstimatedTokens > 0) {
    parts.push(`约 ${Math.round(block.reasoningContentEstimatedTokens).toLocaleString()} tokens`);
  }
  if (typeof block.reasoningContentChars === "number" && block.reasoningContentChars > 0) {
    parts.push(`${Math.round(block.reasoningContentChars).toLocaleString()} 字符`);
  }
  return parts.join(" · ");
}

function publicTimelineTone(entries: ActivityEntry[]): PublicTimelineActivityTone {
  const state = [...entries].reverse().map((entry) => cleanText(entry.state).toLowerCase()).find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "interrupted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function statusKindLabel(kind: StatusProjectionBlock["kind"]) {
  if (kind === "recovery_event") return "状态异常";
  if (kind === "terminal_event") return "运行已结束";
  return "状态更新";
}

function statusBlockTone(block: StatusProjectionBlock): PublicTimelineActivityTone {
  if (block.kind === "recovery_event") return "soft_error";
  if (block.kind === "terminal_event") {
    const state = cleanText(block.state).toLowerCase();
    if (["failed", "error", "blocked"].includes(state)) return "soft_error";
    if (["stopped", "aborted", "interrupted", "cancelled", "canceled"].includes(state)) return "stopped";
    if (["completed", "complete", "done", "success"].includes(state)) return "done";
    return "stopped";
  }
  const state = cleanText(block.state).toLowerCase();
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["failed", "error", "blocked"].includes(state)) return "soft_error";
  if (["completed", "complete", "done", "success", "accepted"].includes(state)) return "done";
  return "running";
}

function statusBlockLabel(block: StatusProjectionBlock, tone: PublicTimelineActivityTone) {
  if (block.kind === "recovery_event") return "异常";
  if (block.kind === "terminal_event") return toolRoundStatusLabel(tone);
  if (tone === "done") return "已接收";
  if (tone === "waiting") return "等待中";
  if (tone === "soft_error") return "异常";
  return "处理中";
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const text = displayText(value);
    if (text) return text;
  }
  return "";
}

function firstDifferentText(summary: string, ...values: unknown[]) {
  const normalizedSummary = compactText(summary);
  for (const value of values) {
    const text = displayText(value);
    if (text && compactText(text) !== normalizedSummary) return text;
  }
  return "";
}

function firstDifferentToolText(summary: string, ...values: unknown[]) {
  const normalizedSummary = compactText(summary);
  for (const value of values) {
    const text = displayToolText(value);
    if (text && compactText(text) !== normalizedSummary) return text;
  }
  return "";
}

function toolWindowTitle(block: ToolProjectionBlock) {
  const action = toolInvocationName(block);
  const target = toolInvocationTarget(block);
  const structured = [action, target].filter(Boolean).join(" ");
  if (structured && !sameCompactText(structured, "工具操作")) return structured;
  return firstText(block.title, block.detail, structured || "工具操作");
}

function toolInvocationName(block: ToolProjectionBlock) {
  const rawTool = cleanText(block.toolName || block.actionKind);
  const normalized = rawTool.toLowerCase();
  if (!rawTool || normalized === "tool") {
    return actionLabelFromText(block.title) || actionLabelFromText(block.detail) || "工具操作";
  }
  return displayToolActionName({
    actionKind: cleanText(block.actionKind),
    toolName: rawTool,
  });
}

function toolInvocationTarget(block: ToolProjectionBlock) {
  if (isShellTool(block)) {
    return commandInvocationText(block);
  }
  return displayTargetLabel(block.target);
}

function toolWindowStatusTone(block: ToolProjectionBlock): PublicTimelineActivityTone {
  const state = cleanText(block.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "interrupted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function toolWindowStatusLabel(block: ToolProjectionBlock) {
  const tone = toolWindowStatusTone(block);
  if (tone === "done") return "完成";
  if (tone === "soft_error") return "失败";
  if (tone === "stopped") return "停止";
  if (tone === "waiting") return "等待";
  return "运行中";
}

function toolWindowSections(block: ToolProjectionBlock) {
  const sections: Array<{ label: string; text: string }> = [];
  const target = displayTargetLabel(block.target);
  const argumentsPreview = cleanText(block.argumentsPreview);

  if (target) {
    sections.push({ label: "目标", text: target });
  }
  if (argumentsPreview) {
    sections.push({ label: "参数预览", text: argumentsPreview });
  }
  const polling = block.polling;
  if (polling?.mode === "poll") {
    const interval = Number(polling.interval_ms || 0);
    const timeout = Number(polling.timeout_ms || 0);
    const parts = [
      polling.poll_id ? `轮询 ${polling.poll_id}` : "轮询",
      interval > 0 ? `每 ${Math.round(interval / 1000)} 秒` : "",
      timeout > 0 ? `最长 ${Math.round(timeout / 1000)} 秒` : "",
    ].filter(Boolean);
    sections.push({ label: "轮询策略", text: parts.join(" · ") });
  }
  return sections.filter((section) => !isInternalToolWindowSection(section.label));
}

function toolWindowRoundKey(block: ToolProjectionBlock) {
  const sourceItemId = cleanText(block.sourceItemId);
  if (!sourceItemId) return "";
  if (sourceItemId === cleanText(block.toolCallId) || sourceItemId === cleanText(block.toolLifecycleId)) return "";
  const parts = sourceItemId.split(":").map((part) => cleanText(part)).filter(Boolean);
  const markerIndex = parts.indexOf("single-agent-tool");
  if (markerIndex < 0) return "";
  const roundIndex = parts[markerIndex + 1] ?? "";
  const hasPerToolSuffix = parts.length > markerIndex + 2;
  if (!roundIndex || !/^\d+$/.test(roundIndex) || !hasPerToolSuffix) return "";
  return parts.slice(0, markerIndex + 2).join(":");
}

function toolWindowConsoleLabel(block: ToolProjectionBlock) {
  const tool = cleanText(block.toolName).toLowerCase();
  if (isCommandToolName(tool)) {
    return "命令行";
  }
  if (toolWindowFamily(block) === "write") return "修改请求";
  if (toolWindowFamily(block) === "search") return "检索条件";
  if (toolWindowFamily(block) === "file") return "读取请求";
  if (toolWindowFamily(block) === "inspect") return "检查请求";
  return "调用参数";
}

function displayTargetLabel(value: unknown) {
  const text = cleanText(value).replace(/\\/g, "/");
  if (!text) return "";
  const projectRelative = text.match(/(?:^|\/)langchain-agent\/(.+)$/i)?.[1];
  if (projectRelative) return projectRelative;
  const parts = text.split("/").filter(Boolean);
  if (/^[A-Za-z]:\//.test(text) && parts.length) {
    return parts.slice(-3).join("/");
  }
  if (parts.length > 3) {
    return parts.slice(-3).join("/");
  }
  return text;
}

function isInternalToolWindowSection(label: string) {
  return ["时序", "调用", "调用号", "offset", "event", "source"].includes(cleanText(label).toLowerCase());
}

function toolWindowCommandLine(block: ToolProjectionBlock, sections: Array<{ label: string; text: string }>) {
  const explicit = cleanText(block.commandLine);
  const rawTool = cleanText(block.toolName || block.actionKind);
  const shellTool = isShellTool(block);
  const target = shellTool ? commandInvocationText(block) : firstSectionText(sections, "目标") || displayTargetLabel(block.target);
  const params = firstSectionText(sections, "参数预览") || firstSectionText(sections, "参数") || cleanText(block.argumentsPreview);
  const explicitIsGeneric = isGenericToolText(explicit);
  const explicitUsesRawTool = rawTool
    && (sameCompactText(explicit, rawTool) || cleanText(explicit).toLowerCase().startsWith(`${rawTool.toLowerCase()} `));
  if (explicit && shellTool && !explicitIsGeneric && !explicitUsesRawTool) return explicit;
  if (shellTool && target) return target;
  if (explicit && !explicitIsGeneric && !explicitUsesRawTool) return explicit;
  const action = toolInvocationName(block);
  const commandHead = shellTool ? (rawTool || "command") : action;
  return [commandHead, target ? quoteCommandPart(target) : "", params && !sameCompactText(params, target) ? params : ""]
    .filter(Boolean)
    .join(" ");
}

function toolWindowOutputText(
  block: ToolProjectionBlock,
  sections: Array<{ label: string; text: string }>,
) {
  const explicit = displayToolOutputText(block.output);
  if (explicit && !sectionHasSameText(sections, explicit)) return explicit;
  const detail = displayToolOutputText(block.detail);
  if (detail && !sectionHasSameText(sections, detail)) return detail;
  return "";
}

function firstSectionText(sections: Array<{ label: string; text: string }>, label: string) {
  return sections.find((section) => section.label === label)?.text ?? "";
}

function sectionHasSameText(sections: Array<{ text: string }>, value: string) {
  const normalized = compactText(value);
  return Boolean(normalized) && sections.some((section) => compactText(section.text) === normalized);
}

function quoteCommandPart(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  return /\s/.test(text) ? `"${text.replace(/"/g, '\\"')}"` : text;
}

function sameCompactText(left: string, right: string) {
  return Boolean(left) && Boolean(right) && compactText(left) === compactText(right);
}

function isShellTool(block: ToolProjectionBlock) {
  const tool = cleanText(block.toolName || block.actionKind).toLowerCase();
  return isCommandToolName(tool);
}

function toolWindowFamily(block: ToolProjectionBlock): ToolUiFamily {
  const family = toolDisplayFamily({
    actionKind: cleanText(block.actionKind),
    toolName: cleanText(block.toolName),
  });
  if (family !== "generic") return family;
  const inferredAction = actionLabelFromText(block.title)
    || actionLabelFromText(block.detail)
    || actionLabelFromText(block.output);
  const inferredFamily = toolFamilyFromActionLabel(inferredAction);
  if (inferredFamily) return inferredFamily;
  return "generic";
}

function toolFamilyFromActionLabel(label: string): ToolUiFamily | "" {
  if (["读取文件", "读取工作区"].includes(label)) return "file";
  if (["读取工具结果"].includes(label)) return "data";
  if (["搜索文件", "搜索文本", "匹配路径"].includes(label)) return "search";
  if (["列出目录", "检查路径"].includes(label)) return "inspect";
  if (["写入文件", "编辑文件", "批量编辑文件", "应用补丁"].includes(label)) return "write";
  if (["运行命令"].includes(label)) return "command";
  return "";
}

function isGenericToolText(value: string) {
  const normalized = cleanText(value).toLowerCase();
  return !normalized || normalized === "tool" || normalized.startsWith("tool ") || normalized.startsWith("tool\"");
}

function commandInvocationText(block: ToolProjectionBlock) {
  const direct = cleanText(block.target);
  if (direct && !isCommandToolName(direct.toLowerCase()) && !/^action\s*=\s*command$/i.test(direct)) return direct;
  return previewArgumentValue(block.argumentsPreview, ["command", "cmd", "script", "code"]);
}

function previewArgumentValue(preview: string, keys: string[]) {
  const source = cleanText(preview);
  if (!source) return "";
  for (const key of keys) {
    const marker = `${key}=`;
    const index = source.indexOf(marker);
    if (index < 0) continue;
    let rest = source.slice(index + marker.length).trim();
    const nextKey = rest.search(/,\s*(?:path|file|file_path|target|start_line|line_count|end_line|range|query|pattern|cwd|command|cmd|script|code|url)=/i);
    if (nextKey >= 0) {
      rest = rest.slice(0, nextKey).trim();
    }
    return stripWrappingQuotes(rest.replace(/,\s*$/, "").trim());
  }
  return "";
}

function stripWrappingQuotes(value: string) {
  const trimmed = cleanText(value);
  if (trimmed.length >= 2 && trimmed.startsWith("\"") && trimmed.endsWith("\"")) {
    return trimmed.slice(1, -1).replace(/\\"/g, "\"");
  }
  return trimmed;
}

function actionLabelFromText(value: unknown) {
  const text = cleanText(value).replace(/完成[:：]?.*$/u, "").trim();
  for (const label of TOOL_ACTION_LABELS) {
    if (text === label) return label;
    if (text.startsWith(`${label} `) || text.startsWith(`${label}：`)) return label;
  }
  if (text.startsWith("文件读取")) return "读取文件";
  if (text.startsWith("文件更新")) return "更新文件";
  if (text.startsWith("搜索完成")) return "搜索文件";
  return "";
}

function compactText(value: string) {
  return cleanText(value).replace(/\s+/g, "").toLowerCase();
}

function cleanText(value: unknown) {
  return String(value ?? "")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function displayText(value: unknown) {
  return publicRuntimeStatusText(cleanText(value));
}

function displayToolText(value: unknown) {
  const raw = cleanText(value);
  if (!raw) return "";
  const publicStatus = publicRuntimeStatusText(raw);
  if (publicStatus && publicStatus !== "状态已更新") return publicStatus;
  return raw;
}

function displayToolOutputText(value: unknown) {
  const text = displayToolText(value);
  return text === "状态已更新" ? "" : text;
}
