"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { PublicChatTimelineItem } from "@/lib/api";

type PublicTimelineActivityProps = {
  items?: PublicChatTimelineItem[] | null;
};

type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type ActivityEntry = {
  collapsed?: boolean;
  detail?: string;
  id: string;
  kind: "status" | "tool";
  meta: string[];
  sections: Array<{ label: string; text: string }>;
  state?: string;
  text: string;
};

export function PublicTimelineActivity({ items }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items);
  if (!view.entries.length) {
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
  const meta = [
    toolWindow?.tool_label,
    toolWindow?.status,
    toolWindow?.target,
  ].map(cleanText).filter(Boolean);
  const kind = isToolItem(item) ? "tool" : "status";
  return {
    collapsed: kind === "tool" && typeof item.collapsed === "boolean" ? item.collapsed : undefined,
    detail,
    id: cleanText(item.item_id) || cleanText(item.source_event_id) || `${kind}:${index}`,
    kind,
    meta,
    sections,
    state: cleanText(item.state).toLowerCase(),
    text,
  };
}

function isToolItem(item: PublicChatTimelineItem) {
  return cleanText((item as { slot?: unknown }).slot).toLowerCase() === "tool"
    || cleanText((item as { surface?: unknown }).surface).toLowerCase() === "tool_window"
    || cleanText(item.kind).toLowerCase() === "work_action";
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

function ActivityLine({ entry }: { entry: ActivityEntry }) {
  return (
    <div
      className="public-run-activity__line public-run-activity__line--status"
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
    >
      <p>{entry.text}</p>
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
      <summary>{entry.text}</summary>
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
