"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StatusLine, toolRoundStatusLabel } from "./AssistantTrace";
import { TodoPlan } from "./TodoPlan";
import { ToolRound, ToolWindow } from "./ToolTrace";

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
};

export type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

export type ActivityEntry = {
  collapsed?: boolean;
  commandLine?: string;
  consoleLabel?: string;
  detail?: string;
  id: string;
  kind: "activity_archive" | "body_note" | "status_line" | "todo_plan" | "tool_window";
  outputText?: string;
  sections: Array<{ label: string; text: string }>;
  statusKind?: string;
  state?: string;
  statusLabel?: string;
  statusTone?: PublicTimelineActivityTone;
  text: string;
  todoItems?: TodoPlanProjectionBlock["items"];
  activeItemId?: string;
  completionReady?: boolean;
  toolRoundKey?: string;
  archivedEntries?: ActivityEntry[];
  archiveCount?: number;
  bodyText?: string;
};

export type ActivityRenderUnit =
  | { kind: "entry"; entry: ActivityEntry }
  | {
      kind: "tool_round";
      count: number;
      entries: ActivityEntry[];
      id: string;
      preview: string;
      statusLabel: string;
      statusTone: PublicTimelineActivityTone;
    };

export function PublicTimelineActivity({ ariaLabel = "运行状态", blocks }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(blocks);
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
) {
  return publicTimelineActivityView(blocks).entries.length > 0;
}

function publicTimelineActivityView(blocks: ProjectionRenderBlock[] | null | undefined) {
  const entries = (blocks ?? [])
    .map((block, index) => activityEntryFromBlock(block, index, { allowBody: false }))
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
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {bodyText}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function toolRoundFromEntries(entries: ActivityEntry[], roundKey: string): ActivityRenderUnit {
  const statusTone = publicTimelineTone(entries);
  const count = entries.length;
  return {
    kind: "tool_round",
    count,
    entries,
    id: `tool-round:${roundKey || entries[0]?.id || "tools"}`,
    preview: toolRoundPreview(entries),
    statusLabel: toolRoundStatusLabel(statusTone),
    statusTone,
  };
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

const TOOL_ACTION_LABELS = [
  "运行命令",
  "匹配路径",
  "列出目录",
  "检查路径",
  "读取文件",
  "搜索文件",
  "搜索文本",
  "写入文件",
  "编辑文件",
  "批量编辑文件",
  "应用补丁",
];

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
  options: { allowBody: boolean },
): ActivityEntry | null {
  if (block.kind === "body_segment") {
    return options.allowBody ? bodyEntryFromBlock(block, index) : null;
  }
  if (block.kind === "log_entry") {
    return null;
  }
  if (block.kind === "activity_archive") {
    return archiveEntryFromBlock(block, index);
  }
  if (block.kind === "todo_plan") {
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

function archiveEntryFromBlock(block: ActivityArchiveProjectionBlock, index: number): ActivityEntry | null {
  const entries = (block.blocks ?? [])
    .map((item, childIndex) => activityEntryFromBlock(item, childIndex, { allowBody: true }))
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
  let detail = firstDifferentText(text, block.detail);
  const sections = [
    block.target ? { label: "目标", text: displayTargetLabel(block.target) } : null,
    block.argumentsPreview ? { label: "参数", text: block.argumentsPreview } : null,
    block.detail ? { label: "详情", text: block.detail } : null,
  ].filter((section): section is { label: string; text: string } => Boolean(section?.label && section?.text && !isInternalToolWindowSection(section.label)));
  if (sections.some((section) => compactText(section.text) === compactText(detail))) {
    detail = "";
  }
  const stableId = cleanText(block.id) || cleanText(block.sourceEventId) || `tool:${index}`;
  return {
    collapsed: typeof block.collapsed === "boolean" ? block.collapsed : undefined,
    commandLine: toolWindowCommandLine(block, sections),
    consoleLabel: toolWindowConsoleLabel(block),
    detail,
    id: `tool-window:${stableId}`,
    kind: "tool_window",
    outputText: toolWindowOutputText(block, sections),
    sections,
    state: cleanText(block.state).toLowerCase(),
    statusLabel: toolWindowStatusLabel(block),
    statusTone: toolWindowStatusTone(block),
    text,
    toolRoundKey: toolWindowRoundKey(block),
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
    statusKind: block.kind,
    statusLabel: statusBlockLabel(block, statusTone),
    statusTone,
    text: title,
  };
}

function publicTimelineTone(entries: ActivityEntry[]): PublicTimelineActivityTone {
  const state = [...entries].reverse().map((entry) => cleanText(entry.state).toLowerCase()).find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function statusKindLabel(kind: StatusProjectionBlock["kind"]) {
  if (kind === "recovery_event") return "需要处理";
  if (kind === "terminal_event") return "运行已结束";
  return "状态更新";
}

function statusBlockTone(block: StatusProjectionBlock): PublicTimelineActivityTone {
  if (block.kind === "recovery_event") return "soft_error";
  if (block.kind === "terminal_event") {
    const state = cleanText(block.state).toLowerCase();
    if (["failed", "error", "blocked"].includes(state)) return "soft_error";
    if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
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
  if (block.kind === "recovery_event") return "需处理";
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

function toolWindowTitle(block: ToolProjectionBlock) {
  const action = toolInvocationName(block);
  const target = toolInvocationTarget(block);
  return [action, target].filter(Boolean).join(" ");
}

function toolInvocationName(block: ToolProjectionBlock) {
  const rawTool = cleanText(block.toolName || block.actionKind);
  const normalized = rawTool.toLowerCase();
  if (!rawTool) return "tool";
  if (["terminal", "shell", "cmd", "command", "powershell", "bash"].includes(normalized)) {
    return "运行命令";
  }
  const labels: Record<string, string> = {
    glob_paths: "匹配路径",
    list_dir: "列出目录",
    path_exists: "检查路径",
    read_file: "读取文件",
    read_files: "读取文件",
    read_path: "读取文件",
    search_files: "搜索文件",
    search_text: "搜索文本",
    stat_path: "检查路径",
    write_file: "写入文件",
    edit_file: "编辑文件",
    batch_edit_file: "批量编辑文件",
    apply_patch: "应用补丁",
  };
  return labels[normalized] || rawTool;
}

function toolInvocationTarget(block: ToolProjectionBlock) {
  return displayTargetLabel(block.target);
}

function toolWindowStatusTone(block: ToolProjectionBlock): PublicTimelineActivityTone {
  const state = cleanText(block.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
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
  if (["terminal", "shell", "cmd", "command", "powershell", "bash"].includes(tool)) {
    return "命令行";
  }
  return "命令行";
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
  if (explicit) return explicit;
  const rawTool = cleanText(block.toolName || block.actionKind || "tool");
  const target = firstSectionText(sections, "目标") || displayTargetLabel(block.target);
  const params = firstSectionText(sections, "参数") || cleanText(block.argumentsPreview);
  return [rawTool, target ? quoteCommandPart(target) : "", params && !sameCompactText(params, target) ? params : ""]
    .filter(Boolean)
    .join(" ");
}

function toolWindowOutputText(
  block: ToolProjectionBlock,
  sections: Array<{ label: string; text: string }>,
) {
  const explicit = displayText(block.output);
  if (explicit) return explicit;
  const observation = firstSectionText(sections, "观察")
    || firstSectionText(sections, "错误")
    || firstSectionText(sections, "详情");
  if (observation) return observation;
  return displayText(block.detail);
}

function firstSectionText(sections: Array<{ label: string; text: string }>, label: string) {
  return sections.find((section) => section.label === label)?.text ?? "";
}

function quoteCommandPart(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  return /\s/.test(text) ? `"${text.replace(/"/g, '\\"')}"` : text;
}

function sameCompactText(left: string, right: string) {
  return Boolean(left) && Boolean(right) && compactText(left) === compactText(right);
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
  return publicTimelineText(cleanText(value));
}

function publicTimelineText(value: string) {
  return String(value ?? "")
    .replace(/\buser_input_required\b/g, "等待你的确认")
    .replace(/\bbackground_executor_missing_after_restart\b/g, "连接恢复后需要重新接续运行")
    .replace(/\bwaiting_executor\b/g, "等待继续");
}
