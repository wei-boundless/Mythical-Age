"use client";

import {
  BrainCircuit,
  ChevronDown,
  Database,
  FilePenLine,
  FileText,
  Image as ImageIcon,
  ListTree,
  Search,
  Terminal,
  Wrench,
} from "lucide-react";
import React, { useEffect, useState } from "react";

import type { ActivityEntry, ActivityRenderUnit, ToolUiFamily } from "./PublicTimelineActivity";

export function ToolRound({ group }: { group: Extract<ActivityRenderUnit, { kind: "tool_round" }> }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);
  const primaryFamily = toolRoundFamily(group.entries);
  const preview = splitToolTitle(group.preview);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [group.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-round public-run-activity__tool-round--${group.statusTone}`}
      data-tool-count={group.count}
      data-tool-family={primaryFamily}
      data-status-tone={group.statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-round-icon" aria-hidden="true">
          <ToolFamilyIcon family={primaryFamily} />
        </span>
        <span className="public-run-activity__tool-round-copy">
          <span className="public-run-activity__tool-round-preview">
            <span className="public-run-activity__tool-action">{preview.action}</span>
            {preview.target ? <span className="public-run-activity__tool-target">{preview.target}</span> : null}
            <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${group.statusTone}`}>
              <span className="public-run-activity__tool-status-dot" aria-hidden="true" />
              <span className="public-run-activity__tool-status-text">{group.statusLabel}</span>
            </span>
          </span>
        </span>
        <span className="public-run-activity__tool-round-meta">
          <span className="public-run-activity__tool-round-count">{group.count} 个</span>
          <span className="public-run-activity__tool-caret" aria-hidden="true">
            <ChevronDown size={14} />
          </span>
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

export function ToolWindow({ entry, nested = false }: { entry: ActivityEntry; nested?: boolean }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);
  const statusTone = entry.statusTone ?? "running";
  const consoleLabel = entry.consoleLabel || "工具操作";
  const commandText = entry.commandLine || entry.text || "工具调用";
  const commandPrefix = consoleLabel === "命令行" ? "$ " : "";
  const toolFamily = entry.toolFamily ?? "generic";
  const outputText = entry.outputText
    || (statusTone === "running" || statusTone === "waiting" ? "等待返回结果" : "无输出");
  const metaSections = (entry.sections ?? []).slice(0, 3);
  const title = splitToolTitle(entry.text);
  const consoleRows = toolConsoleRows({
    commandText,
    consoleLabel,
    metaSections,
    outputText,
    statusTone,
    toolFamily,
  });
  const hasBody = metaSections.length > 0 || consoleRows.length > 0;

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-window public-run-activity__tool-window--${statusTone}${nested ? " public-run-activity__tool-window--nested" : ""}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-status-tone={statusTone}
      data-tool-family={toolFamily}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-window-icon" aria-hidden="true">
          <ToolFamilyIcon family={toolFamily} />
        </span>
        <span className="public-run-activity__tool-window-copy">
          <span className="public-run-activity__tool-window-title">
            <span className="public-run-activity__tool-action">{title.action}</span>
            {title.target ? <span className="public-run-activity__tool-target">{title.target}</span> : null}
            <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${statusTone}`}>
              <span className="public-run-activity__tool-status-dot" aria-hidden="true" />
              <span className="public-run-activity__tool-status-text">{entry.statusLabel}</span>
            </span>
          </span>
          {entry.detail ? <span className="public-run-activity__tool-window-subtitle">{entry.detail}</span> : null}
        </span>
        <span className="public-run-activity__tool-caret" aria-hidden="true">
          <ChevronDown size={14} />
        </span>
      </summary>
      {hasBody ? (
        <div className="public-run-activity__tool-window-body">
          {metaSections.length ? (
            <dl className="public-run-activity__tool-meta">
              {metaSections.map((section) => (
                <div className="public-run-activity__tool-meta-item" key={`${entry.id}:${section.label}`}>
                  <dt>{section.label}</dt>
                  <dd>{section.text}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {consoleRows.length ? (
            <div className="public-run-activity__tool-console" role="group" aria-label="工具调用窗口">
              {consoleRows.map((row) => (
                <div className={`public-run-activity__tool-console-row public-run-activity__tool-console-row--${row.kind}`} key={row.label}>
                  <div className="public-run-activity__tool-console-label">{row.label}</div>
                  <pre className={`public-run-activity__tool-console-${row.kind}`}>
                    <code>{row.kind === "command" ? commandPrefix : ""}{row.text}</code>
                  </pre>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function toolRoundFamily(entries: ActivityEntry[]): ToolUiFamily {
  const families = entries.map((entry) => entry.toolFamily ?? "generic");
  for (const preferred of ["write", "command", "search", "file", "inspect", "media", "data", "memory", "browser"] as ToolUiFamily[]) {
    if (families.includes(preferred)) return preferred;
  }
  return families[0] ?? "generic";
}

function ToolFamilyIcon({ family }: { family: ToolUiFamily }) {
  const size = 15;
  if (family === "command") return <Terminal size={size} />;
  if (family === "data") return <Database size={size} />;
  if (family === "file") return <FileText size={size} />;
  if (family === "inspect") return <ListTree size={size} />;
  if (family === "media") return <ImageIcon size={size} />;
  if (family === "memory") return <BrainCircuit size={size} />;
  if (family === "search" || family === "browser") return <Search size={size} />;
  if (family === "write") return <FilePenLine size={size} />;
  return <Wrench size={size} />;
}

type ToolConsoleRow = {
  kind: "command" | "output";
  label: string;
  text: string;
};

function toolConsoleRows({
  commandText,
  consoleLabel,
  metaSections,
  outputText,
  statusTone,
  toolFamily,
}: {
  commandText: string;
  consoleLabel: string;
  metaSections: Array<{ label: string; text: string }>;
  outputText: string;
  statusTone: string;
  toolFamily: ToolUiFamily;
}): ToolConsoleRow[] {
  const rows: ToolConsoleRow[] = [];
  if (shouldShowCommandRow({ commandText, metaSections, toolFamily })) {
    rows.push({ kind: "command", label: consoleLabel, text: commandText });
  }
  if (shouldShowOutputRow({ metaSections, outputText, statusTone })) {
    rows.push({ kind: "output", label: "返回结果", text: outputText });
  }
  return rows;
}

function shouldShowCommandRow({
  commandText,
  metaSections,
  toolFamily,
}: {
  commandText: string;
  metaSections: Array<{ label: string; text: string }>;
  toolFamily: ToolUiFamily;
}) {
  const command = cleanTraceText(commandText);
  if (!command) return false;
  if (toolFamily === "command") return !isToolNamePlaceholder(command);
  if (metaSections.length && ["file", "search", "inspect", "write", "data", "memory", "browser"].includes(toolFamily)) {
    return false;
  }
  return !sectionHasSameText(metaSections, command);
}

function shouldShowOutputRow({
  metaSections,
  outputText,
  statusTone,
}: {
  metaSections: Array<{ label: string; text: string }>;
  outputText: string;
  statusTone: string;
}) {
  const output = cleanTraceText(outputText);
  if (!output) return false;
  if ([
    "等待返回结果",
    "无输出",
    "工具调用已完成。",
    "工具调用运行中。",
    "已提交工具调用。",
    "工具调用已通过准入。",
    "读取完成。",
    "读取文件完成。",
    "文件读取完成。",
    "文件更新完成。",
    "搜索完成。",
  ].includes(output)) {
    return false;
  }
  if ((statusTone === "running" || statusTone === "waiting") && output === "等待返回结果") {
    return false;
  }
  if (sectionHasSameText(metaSections, output)) {
    return false;
  }
  const target = metaSections.find((section) => section.label === "目标")?.text ?? "";
  if (target && traceIncludes(output, target) && /(?:完成|已完成|成功)$|(?:完成|已完成|成功)[：:]/u.test(output)) {
    return false;
  }
  return true;
}

function sectionHasSameText(sections: Array<{ text: string }>, value: string) {
  const normalized = compactTraceText(value);
  return Boolean(normalized) && sections.some((section) => compactTraceText(section.text) === normalized);
}

function traceIncludes(value: string, part: string) {
  const normalizedValue = compactTraceText(value).replace(/\\/g, "/");
  const normalizedPart = compactTraceText(part).replace(/\\/g, "/");
  return Boolean(normalizedValue && normalizedPart && normalizedValue.includes(normalizedPart));
}

function compactTraceText(value: string) {
  return cleanTraceText(value).replace(/\s+/g, "").toLowerCase();
}

function cleanTraceText(value: string) {
  return String(value || "").replace(/[ \t\f\v]+/g, " ").trim();
}

function isToolNamePlaceholder(value: string) {
  return ["bash", "cmd", "command", "powershell", "python_repl", "shell", "terminal", "$ terminal", "$ shell"].includes(
    cleanTraceText(value).toLowerCase(),
  );
}

const TOOL_TITLE_ACTIONS = [
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
  "工具操作",
];

function splitToolTitle(value: string) {
  const text = String(value || "").trim();
  for (const action of TOOL_TITLE_ACTIONS) {
    if (text === action) return { action, target: "" };
    if (text.startsWith(`${action} `)) return { action, target: text.slice(action.length).trim() };
    if (text.startsWith(`${action}：`)) return { action, target: text.slice(action.length + 1).trim() };
  }
  return { action: text, target: "" };
}
