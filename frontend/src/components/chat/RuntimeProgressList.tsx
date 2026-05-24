"use client";

import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Circle,
  Clock3,
  FileText,
  GitBranch,
  Loader2,
  PauseCircle,
  PenLine,
  Search,
  TerminalSquare,
  XCircle,
} from "lucide-react";

import type { RuntimeProgressEntry } from "@/lib/store/types";

const MAX_FLOW_ENTRIES = 10;
const MAX_TOOL_ENTRIES = 4;
const USER_VISIBLE_KINDS = new Set<RuntimeProgressEntry["kind"]>([
  "task_order",
  "task_draft",
  "stage",
  "tool",
  "artifact",
  "verification",
  "terminal",
]);

function iconForEntry(entry: RuntimeProgressEntry) {
  if (entry.kind === "task_order" || entry.kind === "task_draft") return <Boxes size={14} />;
  if (entry.kind === "tool") return <TerminalSquare size={14} />;
  if (entry.kind === "verification") return <Search size={14} />;
  if (entry.kind === "terminal") {
    if (entry.level === "error") return <XCircle size={14} />;
    if (entry.level === "stopped") return <Clock3 size={14} />;
    return <CheckCircle2 size={14} />;
  }
  if (entry.title.includes("计划")) return <PenLine size={14} />;
  if (entry.level === "success") return <CheckCircle2 size={14} />;
  if (entry.level === "warning") return <AlertTriangle size={14} />;
  if (entry.level === "error") return <XCircle size={14} />;
  if (entry.level === "waiting") return <PauseCircle size={14} />;
  if (entry.level === "stopped") return <Clock3 size={14} />;
  if (entry.level === "running") return <Loader2 size={14} />;
  return <Circle size={14} />;
}

function cleanTitle(value: string) {
  return value.replace(/(?:taskrun|taskinst|rtevt|event|runtime|orderrun|order)[:_-][^\s]+/gi, "").trim() || "运行进展";
}

function flowLabel(entry: RuntimeProgressEntry) {
  if (entry.kind === "task_order") return "订单";
  if (entry.kind === "task_draft") return "确认";
  if (entry.kind === "tool") return "工具";
  if (entry.kind === "verification") return "验收";
  if (entry.kind === "terminal") return "结束";
  return "阶段";
}

function terminalSummary(entries: RuntimeProgressEntry[]) {
  const latest = entries[entries.length - 1];
  const terminal = [...entries].reverse().find((entry) => entry.kind === "terminal");
  if (terminal) {
    return terminal.statusText || (terminal.level === "success" ? "完成" : terminal.level === "error" ? "失败" : "结束");
  }
  if (latest?.level === "waiting") return "等待";
  if (latest?.level === "error") return "异常";
  return "运行中";
}

function isUserVisibleEntry(entry: RuntimeProgressEntry) {
  if (!entry.kind) return false;
  return USER_VISIBLE_KINDS.has(entry.kind);
}

function currentStage(entries: RuntimeProgressEntry[]) {
  const latest = entries[entries.length - 1];
  if (!latest) return "准备中";
  if (latest.kind === "terminal") return latest.statusText || terminalSummary(entries);
  if (latest.kind === "tool") return latest.toolName ? `调用 ${latest.toolName}` : "调用工具";
  return cleanTitle(latest.title);
}

function progressCountLabel(entries: RuntimeProgressEntry[]) {
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  const stageCount = entries.filter((entry) => entry.kind !== "tool").length;
  return [
    stageCount ? `${stageCount} 个阶段` : "",
    toolCount ? `${toolCount} 次工具` : "",
  ].filter(Boolean).join(" / ") || "等待阶段";
}

function bodyText(entry: RuntimeProgressEntry) {
  if (!entry.body) return "";
  return entry.body.length > 280 ? `${entry.body.slice(0, 279)}...` : entry.body;
}

function metaChips(entry: RuntimeProgressEntry) {
  const chips = entry.meta ?? [];
  if (!chips.length) return null;
  return (
    <div className="runtime-task-flow__meta">
      {chips.map((item) => (
        <span className="runtime-task-flow__chip" key={`${entry.id}-${item.label}-${item.value}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </span>
      ))}
    </div>
  );
}

function artifacts(entry: RuntimeProgressEntry) {
  if (!entry.artifacts?.length) return null;
  return (
    <div className="runtime-task-flow__artifacts">
      {entry.artifacts.map((artifact, index) => (
        <span className="runtime-task-flow__artifact" key={`${entry.id}-${artifact.path || artifact.value || artifact.label}-${index}`}>
          <FileText size={12} />
          <span>{artifact.path || artifact.value || artifact.label}</span>
        </span>
      ))}
    </div>
  );
}

function toolName(entry: RuntimeProgressEntry) {
  return entry.toolName || entry.meta?.find((item) => item.label === "工具")?.value || cleanTitle(entry.title);
}

export function RuntimeProgressList({ entries }: { entries: RuntimeProgressEntry[] }) {
  const userVisibleEntries = entries.filter(isUserVisibleEntry);
  const anchor = [...userVisibleEntries].find((entry) => entry.kind === "task_order" || entry.kind === "task_draft");
  const recentEntries = userVisibleEntries
    .filter((entry) => entry.id !== anchor?.id)
    .slice(-(MAX_FLOW_ENTRIES - (anchor ? 1 : 0)));
  const visibleEntries = anchor ? [anchor, ...recentEntries] : recentEntries;
  if (!visibleEntries.length) return null;

  const flowEntries = visibleEntries.filter((entry) => entry.id !== anchor?.id && entry.kind !== "tool");
  const toolEntries = visibleEntries.filter((entry) => entry.kind === "tool").slice(-MAX_TOOL_ENTRIES);
  const artifactEntries = visibleEntries.filter((entry) => entry.artifacts?.length);
  const status = terminalSummary(visibleEntries);

  return (
    <section className="runtime-task-flow" aria-label="会话任务流程">
      <header className="runtime-task-flow__header">
        <div className="runtime-task-flow__title">
          <GitBranch size={14} />
          <span>会话任务流程</span>
        </div>
        <div className="runtime-task-flow__summary">
          <span>{status}</span>
          <span>{currentStage(visibleEntries)}</span>
          <span>{progressCountLabel(visibleEntries)}</span>
        </div>
      </header>

      {anchor ? (
        <div className={`runtime-task-flow__anchor runtime-task-flow__anchor--${anchor.level}`}>
          <span className="runtime-task-flow__anchor-icon">{iconForEntry(anchor)}</span>
          <div className="runtime-task-flow__anchor-main">
            <div className="runtime-task-flow__anchor-row">
              <strong>{cleanTitle(anchor.title)}</strong>
              {anchor.statusText ? <span>{anchor.statusText}</span> : null}
            </div>
            {bodyText(anchor) ? <p>{bodyText(anchor)}</p> : null}
            {metaChips(anchor)}
          </div>
        </div>
      ) : null}

      <div className="runtime-task-flow__timeline">
        {flowEntries.map((entry) => (
          <article
            className={`runtime-task-flow__item runtime-task-flow__item--${entry.level} runtime-task-flow__item--${entry.kind || "stage"}`}
            key={entry.id}
          >
            <span className="runtime-task-flow__node">{iconForEntry(entry)}</span>
            <div className="runtime-task-flow__item-main">
              <div className="runtime-task-flow__item-head">
                <span className="runtime-task-flow__kind">{flowLabel(entry)}</span>
                <strong>{entry.kind === "tool" ? toolName(entry) : cleanTitle(entry.title)}</strong>
                {entry.statusText ? <span className="runtime-task-flow__status">{entry.statusText}</span> : null}
              </div>
              {bodyText(entry) ? <p>{bodyText(entry)}</p> : null}
              {metaChips(entry)}
              {artifacts(entry)}
            </div>
          </article>
        ))}
      </div>

      {toolEntries.length ? (
        <div className="runtime-task-flow__tool-strip" aria-label="工具使用">
          <span className="runtime-task-flow__tool-strip-label">工具使用</span>
          <div className="runtime-task-flow__tool-strip-items">
            {toolEntries.map((entry) => (
              <span className={`runtime-task-flow__tool-pill runtime-task-flow__tool-pill--${entry.level}`} key={`tool-${entry.id}`}>
                <TerminalSquare size={12} />
                <strong>{toolName(entry)}</strong>
                <span>{entry.statusText || cleanTitle(entry.title)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {artifactEntries.length ? (
        <div className="runtime-task-flow__artifact-strip" aria-label="产物">
          {artifactEntries.flatMap((entry) => entry.artifacts ?? []).slice(0, 4).map((artifact, index) => (
            <span className="runtime-task-flow__artifact" key={`artifact-strip-${artifact.path || artifact.value || artifact.label}-${index}`}>
              <FileText size={12} />
              <span>{artifact.path || artifact.value || artifact.label}</span>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
