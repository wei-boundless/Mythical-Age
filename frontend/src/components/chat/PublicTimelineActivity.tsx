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
  detail?: string;
  id: string;
  kind: "status" | "tool_window";
  meta: string[];
  outputText?: string;
  sections: Array<{ label: string; text: string }>;
  state?: string;
  text: string;
};

export function PublicTimelineActivity({ ariaLabel = "系统提示", items }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items);
  if (!view.entries.length) {
    return null;
  }

  return (
    <div
      className={`public-run-activity public-run-activity--${view.tone}`}
      aria-label={ariaLabel}
      data-entry-count={view.entries.length}
    >
      {view.entries.map((entry) => (
        entry.kind === "tool_window"
          ? <ToolWindow entry={entry} key={entry.id} />
          : <ActivityLine entry={entry} key={entry.id} />
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

function activityEntryFromItem(item: PublicChatTimelineItem, index: number): ActivityEntry | null {
  const kind = activityKindFromItem(item);
  const text = kind === "tool_window"
    ? toolWindowText(item)
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
    detail,
    id: kind === "tool_window" ? `tool-window:${stableId}` : stableId,
    kind,
    meta,
    outputText,
    sections,
    state: cleanText(item.state).toLowerCase(),
    text,
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
    const text = cleanText(value);
    if (text) return text;
  }
  return "";
}

function firstDifferentText(summary: string, ...values: unknown[]) {
  const normalizedSummary = compactText(summary);
  for (const value of values) {
    const text = cleanText(value);
    if (text && compactText(text) !== normalizedSummary) return text;
  }
  return "";
}

function toolWindowText(item: PublicChatTimelineItem) {
  const toolWindow = item.tool_window;
  const baseText = firstText(item.text, item.title, item.public_summary, item.subject_label, item.detail);
  const target = displayTargetLabel(toolWindow?.target || item.target || item.subject_label);
  const status = displayToolStatus(toolWindow?.status || item.state);
  const parts = [baseText];
  const compactBase = compactText(baseText);
  if (target && !compactBase.includes(compactText(target))) {
    parts.push(target);
  }
  const compactWithTarget = compactText(parts.join(""));
  if (status && !compactWithTarget.includes(compactText(status))) {
    parts.push(status);
  }
  return parts.filter(Boolean).join(" ");
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
  const explicit = cleanText(item.tool_window?.output);
  if (explicit) return explicit;
  const observation = firstSectionText(sections, "观察")
    || firstSectionText(sections, "错误")
    || firstSectionText(sections, "详情");
  if (observation) return observation;
  return cleanText(detail || item.observation || item.public_summary || item.recovery_hint);
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
    apply_patch: "更新文件",
  };
  return labels[normalized] || cleanText(value);
}

function displayToolStatus(value: unknown) {
  const normalized = cleanText(value).toLowerCase();
  const labels: Record<string, string> = {
    running: "运行中",
    waiting: "等待中",
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

function ToolWindow({ entry }: { entry: ActivityEntry }) {
  const defaultOpen = !entry.collapsed;
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className="public-run-activity__tool-window"
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-window-title">{entry.text}</span>
      </summary>
      {entry.commandLine || entry.outputText ? (
        <div className="public-run-activity__tool-window-body">
          <pre className="public-run-activity__tool-console">
            {entry.commandLine ? <code>{`$ ${entry.commandLine}`}</code> : null}
            {entry.commandLine && entry.outputText ? "\n" : null}
            {entry.outputText ? <code>{entry.outputText}</code> : null}
          </pre>
        </div>
      ) : null}
    </details>
  );
}
