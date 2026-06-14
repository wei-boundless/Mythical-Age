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
  detail?: string;
  id: string;
  kind: "status" | "tool_lifecycle" | "tool_window";
  meta: string[];
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
  const text = firstText(item.text, item.title, item.public_summary, item.subject_label, item.detail);
  if (!text) {
    return null;
  }
  const detail = firstDifferentText(text, item.detail, item.public_summary, item.observation, item.recovery_hint);
  const toolWindow = item.tool_window;
  const sections = Array.isArray(toolWindow?.sections)
    ? toolWindow.sections
        .map((section) => ({
          label: cleanText(section?.label),
          text: cleanText(section?.text),
        }))
        .filter((section) => section.label && section.text)
    : [];
  const kind = activityKindFromItem(item);
  const meta = [
    displayToolLabel(toolWindow?.tool_label || (kind === "tool_lifecycle" ? item.tool_name : "")),
    displayToolStatus(toolWindow?.status || (kind === "tool_lifecycle" ? item.state : "")),
    toolWindow?.target || (kind === "tool_lifecycle" ? item.subject_label : ""),
  ].map(cleanText).filter(Boolean);
  return {
    collapsed: kind === "tool_window" && typeof item.collapsed === "boolean" ? item.collapsed : undefined,
    detail,
    id: cleanText(item.item_id) || cleanText(item.source_event_id) || `${kind}:${index}`,
    kind,
    meta,
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
  if (kind === "tool_activity" || slot === "tool" || cleanText(item.tool_call_id)) return "tool_lifecycle";
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
        <span>{entry.text}</span>
      </summary>
      {entry.meta.length || entry.sections.length || entry.detail ? (
        <div className="public-run-activity__tool-window-body">
          {entry.meta.length ? (
            <div className="public-run-activity__tool-meta">
              {entry.meta.map((item) => <span key={item}>{item}</span>)}
            </div>
          ) : null}
          {entry.sections.length ? (
            <dl className="public-run-activity__tool-snapshot">
              {entry.sections.map((section) => (
                <div key={`${section.label}:${section.text}`}>
                  <dt>{section.label}</dt>
                  <dd>{section.text}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {entry.detail ? (
            <div className="public-run-activity__line-detail markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {entry.detail}
              </ReactMarkdown>
            </div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
