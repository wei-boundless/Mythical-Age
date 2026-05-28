"use client";

import { ChevronRight, SquareTerminal } from "lucide-react";

import type { RuntimeProgressEntry } from "@/lib/store/types";

const MAX_COMMAND_ROWS = 4;

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

function isCommandEntry(entry: RuntimeProgressEntry) {
  return entry.kind === "tool";
}

function commandLabel(entry: RuntimeProgressEntry) {
  return truncate(
    entry.meta?.find((item) => item.label === "目标")?.value
    || entry.body
    || entry.toolName
    || entry.title,
    180,
  ) || entry.toolName || "command";
}

function commandStatus(entry: RuntimeProgressEntry) {
  if (entry.level === "error") return "failed";
  if (entry.level === "success" || entry.completedAt) return "done";
  if (entry.statusText) return cleanText(entry.statusText);
  return "running";
}

export function RuntimeRunSummary({ entries }: { entries: RuntimeProgressEntry[] }) {
  const commands = entries.filter(isCommandEntry);
  if (!commands.length) return null;

  const recentCommands = commands.slice(-MAX_COMMAND_ROWS);
  const failed = commands.some((entry) => entry.level === "error");
  const completed = commands.filter((entry) => entry.level === "success" || entry.completedAt).length;
  const summary = failed
    ? `Ran ${commands.length} ${commands.length === 1 ? "command" : "commands"} · failed`
    : completed === commands.length
      ? `Ran ${commands.length} ${commands.length === 1 ? "command" : "commands"}`
      : `Running ${commands.length} ${commands.length === 1 ? "command" : "commands"}`;

  return (
    <details className="runtime-run-summary" aria-label="Command activity">
      <summary className="runtime-run-summary__header">
        <span className="runtime-run-summary__summary">
          <SquareTerminal size={13} />
          <span>{summary}</span>
        </span>
        <ChevronRight size={13} className="runtime-run-summary__chevron" />
      </summary>
      <div className="runtime-run-summary__commands">
        {recentCommands.map((entry) => (
          <div className="runtime-run-summary__command" key={entry.id}>
            <span>{commandLabel(entry)}</span>
            <em>{commandStatus(entry)}</em>
          </div>
        ))}
      </div>
    </details>
  );
}
