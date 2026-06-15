"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { PublicChatTimelineItem } from "@/lib/api";

type PublicTimelineActivityProps = {
  ariaLabel?: string;
  items?: PublicChatTimelineItem[] | null;
};

type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type ActivityEntry = {
  collapsed?: boolean;
  commandLine?: string;
  consoleLabel?: string;
  detail?: string;
  id: string;
  kind: "status" | "tool_window";
  meta: string[];
  outputText?: string;
  sections: Array<{ label: string; text: string }>;
  state?: string;
  statusLabel?: string;
  statusTone?: PublicTimelineActivityTone;
  text: string;
  toolRoundKey?: string;
};

type ActivityRenderUnit =
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

export function PublicTimelineActivity({ ariaLabel = "系统提示", items }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items);
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
        row.kind === "tool_round"
          ? <ToolRound group={row} key={row.id} />
          : row.entry.kind === "tool_window"
            ? <ToolWindow entry={row.entry} key={row.entry.id} />
            : <ActivityLine entry={row.entry} key={row.entry.id} />
      ))}
    </div>
  );
}

export function publicTimelineHasDisplayableActivity(
  items: PublicChatTimelineItem[] | null | undefined,
) {
  return publicTimelineActivityView(items).entries.length > 0;
}

function publicTimelineActivityView(items: PublicChatTimelineItem[] | null | undefined) {
  const entries = (items ?? [])
    .map(activityEntryFromItem)
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
    return "系统工具执行轨迹";
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

function toolRoundStatusLabel(tone: PublicTimelineActivityTone) {
  if (tone === "done") return "已完成";
  if (tone === "soft_error") return "有失败";
  if (tone === "stopped") return "已停止";
  if (tone === "waiting") return "等待中";
  return "运行中";
}

function activityEntryFromItem(item: PublicChatTimelineItem, index: number): ActivityEntry | null {
  if (cleanText(item.tool_name).toLowerCase() === "agent_todo") {
    return null;
  }
  const kind = activityKindFromItem(item);
  const text = kind === "tool_window"
    ? toolWindowTitle(item)
    : firstText(item.text, item.title, item.public_summary, item.subject_label, item.detail);
  if (!text) {
    return null;
  }
  let detail = firstDifferentText(text, item.detail, item.public_summary, item.observation, item.recovery_hint);
  const toolWindow = item.tool_window;
  const sections = Array.isArray(toolWindow?.sections)
    ? toolWindow.sections
        .map((section) => ({
          label: cleanText(section?.label),
          text: cleanText(section?.text),
        }))
        .filter((section) => section.label && section.text && !isInternalToolWindowSection(section.label))
    : [];
  if (kind === "tool_window" && sections.some((section) => compactText(section.text) === compactText(detail))) {
    detail = "";
  }
  const commandLine = kind === "tool_window" ? toolWindowCommandLine(item, sections) : "";
  const outputText = kind === "tool_window" ? toolWindowOutputText(item, sections, detail) : "";
  const meta = kind === "tool_window" ? [] : [
    displayToolLabel(toolWindow?.tool_label),
    displayToolStatus(toolWindow?.status),
    toolWindow?.target,
  ].map(cleanText).filter(Boolean);
  const stableId = cleanText(item.item_id) || cleanText(item.source_event_id) || `${kind}:${index}`;
  return {
    collapsed: kind === "tool_window" && typeof item.collapsed === "boolean" ? item.collapsed : undefined,
    commandLine,
    consoleLabel: kind === "tool_window" ? toolWindowConsoleLabel(item) : undefined,
    detail,
    id: kind === "tool_window" ? `tool-window:${stableId}` : stableId,
    kind,
    meta,
    outputText,
    sections,
    state: cleanText(item.state).toLowerCase(),
    statusLabel: kind === "tool_window" ? toolWindowStatusLabel(item) : undefined,
    statusTone: kind === "tool_window" ? toolWindowStatusTone(item) : undefined,
    text,
    toolRoundKey: kind === "tool_window" ? toolWindowRoundKey(item) : undefined,
  };
}

function activityKindFromItem(item: PublicChatTimelineItem): ActivityEntry["kind"] {
  const kind = cleanText(item.kind).toLowerCase();
  const slot = cleanText((item as { slot?: unknown }).slot).toLowerCase();
  const surface = cleanText((item as { surface?: unknown }).surface).toLowerCase();
  if (surface === "tool_window" || kind === "work_action") return "tool_window";
  if (kind === "tool_activity" || slot === "tool" || cleanText(item.tool_call_id) || cleanText(item.tool_lifecycle_id)) return "tool_window";
  return "status";
}

function publicTimelineTone(entries: ActivityEntry[]): PublicTimelineActivityTone {
  const state = [...entries].reverse().map((entry) => cleanText(entry.state).toLowerCase()).find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
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

function toolWindowTitle(item: PublicChatTimelineItem) {
  const action = toolInvocationName(item);
  const target = toolInvocationTarget(item);
  return [action, target].filter(Boolean).join(" ");
}

function toolInvocationName(item: PublicChatTimelineItem) {
  const rawTool = cleanText(item.tool_name || item.action_kind || item.tool_window?.tool_label);
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

function toolInvocationTarget(item: PublicChatTimelineItem) {
  return displayTargetLabel(item.tool_window?.target || item.target || item.subject_label);
}

function toolWindowStatusTone(item: PublicChatTimelineItem): PublicTimelineActivityTone {
  const state = cleanText(item.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function toolWindowStatusLabel(item: PublicChatTimelineItem) {
  const tone = toolWindowStatusTone(item);
  if (tone === "done") return "完成";
  if (tone === "soft_error") return "失败";
  if (tone === "stopped") return "停止";
  if (tone === "waiting") return "等待";
  return "运行中";
}

function toolWindowRoundKey(item: PublicChatTimelineItem) {
  const sourceItemId = cleanText(item.source_item_id);
  if (!sourceItemId) return "";
  if (sourceItemId === cleanText(item.tool_call_id) || sourceItemId === cleanText(item.tool_lifecycle_id)) return "";
  const parts = sourceItemId.split(":").map((part) => cleanText(part)).filter(Boolean);
  const markerIndex = parts.indexOf("single-agent-tool");
  if (markerIndex < 0) return "";
  const roundIndex = parts[markerIndex + 1] ?? "";
  const hasPerToolSuffix = parts.length > markerIndex + 2;
  if (!roundIndex || !/^\d+$/.test(roundIndex) || !hasPerToolSuffix) return "";
  return parts.slice(0, markerIndex + 2).join(":");
}

function toolWindowConsoleLabel(item: PublicChatTimelineItem) {
  const tool = cleanText(item.tool_name).toLowerCase();
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

function toolWindowCommandLine(item: PublicChatTimelineItem, sections: Array<{ label: string; text: string }>) {
  const explicit = cleanText(item.tool_window?.command_line);
  if (explicit) return explicit;
  const rawTool = cleanText(item.tool_name || item.action_kind || item.tool_window?.tool_label || "tool");
  const target = firstSectionText(sections, "目标") || displayTargetLabel(item.target || item.subject_label || item.tool_window?.target);
  const params = firstSectionText(sections, "参数") || cleanText(item.arguments_preview);
  return [rawTool, target ? quoteCommandPart(target) : "", params && !sameCompactText(params, target) ? params : ""]
    .filter(Boolean)
    .join(" ");
}

function toolWindowOutputText(
  item: PublicChatTimelineItem,
  sections: Array<{ label: string; text: string }>,
  detail: string,
) {
  const explicit = displayText(item.tool_window?.output);
  if (explicit) return explicit;
  const observation = firstSectionText(sections, "观察")
    || firstSectionText(sections, "错误")
    || firstSectionText(sections, "详情");
  if (observation) return observation;
  return displayText(item.observation || item.recovery_hint);
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

function displayToolLabel(value: unknown) {
  const normalized = cleanText(value).toLowerCase();
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
    edit_file: "更新文件",
    batch_edit_file: "批量编辑文件",
    apply_patch: "更新文件",
  };
  return labels[normalized] || cleanText(value);
}

function displayToolStatus(value: unknown) {
  const normalized = cleanText(value).toLowerCase();
  const labels: Record<string, string> = {
    running: "运行中",
    waiting: "等待中",
    waiting_executor: "等待中",
    waiting_user: "等待中",
    waiting_approval: "等待权限",
    queued: "排队中",
    done: "已完成",
    complete: "已完成",
    completed: "已完成",
    success: "已完成",
    passed: "已完成",
    failed: "失败",
    error: "失败",
    blocked: "受阻",
    missing: "缺失",
    stopped: "已停止",
    aborted: "已停止",
    cancelled: "已停止",
    canceled: "已停止",
  };
  return labels[normalized] || cleanText(value);
}

function ActivityLine({ entry }: { entry: ActivityEntry }) {
  return (
    <div
      className={`public-run-activity__line public-run-activity__line--${entry.kind}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
    >
      <p>
        <span>{entry.text}</span>
      </p>
      {entry.meta.length ? (
        <div className="public-run-activity__line-meta">
          {entry.meta.map((item) => <span key={item}>{item}</span>)}
        </div>
      ) : null}
      {entry.detail ? (
        <div className="public-run-activity__line-detail markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {entry.detail}
          </ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}

function ToolRound({ group }: { group: Extract<ActivityRenderUnit, { kind: "tool_round" }> }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [group.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-round public-run-activity__tool-round--${group.statusTone}`}
      data-tool-count={group.count}
      data-status-tone={group.statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-round-icon" aria-hidden="true" />
        <span className="public-run-activity__tool-round-copy">
          <span className="public-run-activity__tool-round-title">工具调用</span>
          <span className="public-run-activity__tool-round-separator" aria-hidden="true">·</span>
          <span className="public-run-activity__tool-round-preview">{group.preview}</span>
        </span>
        <span className="public-run-activity__tool-round-count">{group.count} 个工具</span>
        <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${group.statusTone}`}>
          {group.statusLabel}
        </span>
      </summary>
      <div className="public-run-activity__tool-round-body">
        {group.entries.map((entry) => (
          <ToolWindow entry={entry} key={entry.id} nested />
        ))}
      </div>
    </details>
  );
}

function ToolWindow({ entry, nested = false }: { entry: ActivityEntry; nested?: boolean }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);
  const statusTone = entry.statusTone ?? "running";
  const outputText = entry.outputText
    || (statusTone === "running" || statusTone === "waiting" ? "等待系统返回" : "无输出");

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-window public-run-activity__tool-window--${statusTone}${nested ? " public-run-activity__tool-window--nested" : ""}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-status-tone={statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-window-icon" aria-hidden="true" />
        <span className="public-run-activity__tool-window-title">{entry.text}</span>
        <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${statusTone}`}>
          {entry.statusLabel}
        </span>
      </summary>
      <div className="public-run-activity__tool-window-body">
        <div className="public-run-activity__tool-console" role="group" aria-label="工具调用窗口">
          <div className="public-run-activity__tool-console-row public-run-activity__tool-console-row--command">
            <div className="public-run-activity__tool-console-label">{entry.consoleLabel || "命令行"}</div>
            <pre className="public-run-activity__tool-console-command">
              <code>{entry.commandLine ? `$ ${entry.commandLine}` : "$ tool"}</code>
            </pre>
          </div>
          <div className="public-run-activity__tool-console-row public-run-activity__tool-console-row--output">
            <div className="public-run-activity__tool-console-label">系统返回</div>
            <pre className="public-run-activity__tool-console-output">
              <code>{outputText}</code>
            </pre>
          </div>
        </div>
      </div>
    </details>
  );
}
