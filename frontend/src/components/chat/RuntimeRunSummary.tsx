"use client";

import { ChevronRight, CircleDashed, SquareTerminal } from "lucide-react";
import React from "react";
import { useEffect, useState } from "react";

import type { SessionRuntimeAttachment } from "@/lib/api";
import type { RuntimeProgressEntry } from "@/lib/store/types";

const MAX_ACTIVITY_ROWS = 6;

function cleanText(value: string | undefined) {
  return String(value ?? "")
    .replace(/(?:taskrun|taskinst|rtevt|event|runtime|orderrun|order)[:_-][^\s]+/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(value: string | undefined, limit = 150) {
  const normalized = cleanText(value);
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function isVisibleEntry(entry: RuntimeProgressEntry) {
  return [
    "task_order",
    "task_draft",
    "stage",
    "tool",
    "verification",
    "permission",
    "terminal",
  ].includes(entry.kind || "");
}

function isFormalTaskEntry(entry: RuntimeProgressEntry) {
  const taskRunId = String(entry.taskRunId ?? "").trim().toLowerCase();
  if (taskRunId.startsWith("turnrun:")) {
    return false;
  }
  if (taskRunId.startsWith("taskrun:turn:")) {
    return true;
  }
  return entry.kind === "task_order" || entry.kind === "task_draft";
}

function entryLabel(entry: RuntimeProgressEntry) {
  return truncate(
    entry.meta?.find((item) => item.label === "目标")?.value
    || entry.body
    || entry.toolName
    || entry.title,
    180,
  ) || entry.toolName || entry.title;
}

function entryStatus(entry: RuntimeProgressEntry) {
  if (entry.level === "error") return "失败";
  if (entry.level === "success" || entry.completedAt) return entry.statusText ? cleanText(entry.statusText) : "完成";
  if (entry.level === "waiting") return entry.statusText ? cleanText(entry.statusText) : "等待";
  if (entry.statusText) return cleanText(entry.statusText);
  return "运行中";
}

function summaryText(entries: RuntimeProgressEntry[]) {
  const failed = entries.some((entry) => entry.level === "error");
  const waiting = entries.some((entry) => entry.level === "waiting");
  const formalTaskEntries = entries.filter(isFormalTaskEntry);
  const runtimeEntries = entries.filter((entry) => entry.kind && entry.kind !== "tool");
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  const label = formalTaskEntries.length ? "任务运行" : "会话运行";
  if (failed) return `${label} · 失败`;
  if (waiting) return `${label} · 等待`;
  if (runtimeEntries.length) return toolCount ? `${label} · ${toolCount} 个工具` : label;
  return toolCount ? `运行 ${toolCount} 个工具` : label;
}

function entriesFromAttachments(attachments: SessionRuntimeAttachment[]) {
  return attachments.flatMap((attachment) => {
    const progress = Array.isArray(attachment.progress_entries)
      ? attachment.progress_entries.map((item) => ({
          id: String(item.id ?? `${attachment.task_run_id}:${item.eventType ?? item.event_type ?? ""}`),
          level: String(item.level ?? "running") as RuntimeProgressEntry["level"],
          title: String(item.title ?? attachment.title ?? "任务运行"),
          body: String(item.body ?? item.summary ?? attachment.latest_step_summary ?? ""),
          eventType: String(item.eventType ?? item.event_type ?? attachment.latest_event_type ?? "runtime_attachment"),
          kind: String(item.kind ?? "stage") as RuntimeProgressEntry["kind"],
          statusText: String(item.statusText ?? item.status ?? attachment.status ?? ""),
          toolName: String(item.toolName ?? ""),
          taskRunId: attachment.task_run_id,
          createdAt: Number(item.createdAt ?? item.created_at ?? 0) || undefined,
        }))
      : [];
    const artifactRefs = Array.isArray(attachment.artifact_refs) ? attachment.artifact_refs : [];
    const terminalEntry: RuntimeProgressEntry = {
      id: `${attachment.attachment_id}:status`,
      level: attachment.status === "completed" ? "success" : attachment.status === "failed" ? "error" : "running",
      title: attachment.status === "completed" ? "任务已完成" : attachment.title || "任务运行",
      body: attachment.latest_step_summary || attachment.summary || attachment.final_answer || "",
      eventType: attachment.latest_event_type || "runtime_attachment",
      kind: attachment.status === "completed" ? "terminal" : "task_order",
      statusText: attachment.status,
      taskRunId: attachment.task_run_id,
      artifacts: artifactRefs
        .map((item) => ({
          label: "产物",
          path: String(item.path ?? item.absolute_path ?? ""),
        }))
        .filter((item) => item.path)
        .slice(0, 6),
    };
    return [...progress, terminalEntry];
  });
}

export function RuntimeRunSummary({ entries, attachments = [] }: { entries: RuntimeProgressEntry[]; attachments?: SessionRuntimeAttachment[] }) {
  const activities = [...entries, ...entriesFromAttachments(attachments)].filter(isVisibleEntry);
  const recentActivities = activities.slice(-MAX_ACTIVITY_ROWS);
  const hasTaskActivity = activities.some(isFormalTaskEntry);
  const Icon = hasTaskActivity ? CircleDashed : SquareTerminal;
  const [isOpen, setIsOpen] = useState(hasTaskActivity);

  useEffect(() => {
    if (hasTaskActivity) {
      setIsOpen(true);
    }
  }, [hasTaskActivity]);

  if (!activities.length) return null;

  return (
    <details
      className="runtime-run-summary"
      aria-label="Runtime activity"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      open={isOpen}
    >
      <summary className="runtime-run-summary__header">
        <span className="runtime-run-summary__summary">
          <Icon size={13} />
          <span>{summaryText(activities)}</span>
        </span>
        <ChevronRight size={13} className="runtime-run-summary__chevron" />
      </summary>
      <div className="runtime-run-summary__items">
        {recentActivities.map((entry) => (
          <div className="runtime-run-summary__item" data-level={entry.level} key={entry.id}>
            <span>{entryLabel(entry)}</span>
            <em>{entryStatus(entry)}</em>
          </div>
        ))}
      </div>
    </details>
  );
}
