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
  const inputRows = toolInputRows(metaSections, toolFamily);
  const structuredResult = toolStructuredResult(outputText, toolFamily);
  const title = splitToolTitle(entry.text);
  const subtitle = toolStructuredSummary(structuredResult) || entry.detail || "";
  const consoleRows = toolConsoleRows({
    commandText,
    consoleLabel,
    hasStructuredResult: Boolean(structuredResult),
    metaSections,
    outputText,
    statusTone,
    toolFamily,
  });
  const hasBody = inputRows.length > 0 || Boolean(structuredResult) || consoleRows.length > 0;

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
          {subtitle ? <span className="public-run-activity__tool-window-subtitle">{subtitle}</span> : null}
        </span>
        <span className="public-run-activity__tool-caret" aria-hidden="true">
          <ChevronDown size={14} />
        </span>
      </summary>
      {hasBody ? (
        <div className="public-run-activity__tool-window-body">
          {inputRows.length ? <ToolInputRows rows={inputRows} entryId={entry.id} /> : null}
          {structuredResult ? <ToolStructuredResult result={structuredResult} /> : null}
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

type ToolInputRow = {
  label: string;
  text: string;
  valueKind?: "code" | "path" | "plain";
};

type ToolSearchResultItem = {
  index: number;
  path: string;
  snippet: string;
  title: string;
};

type StructuredToolResult = {
  kind: "search_results";
  items: ToolSearchResultItem[];
  notice?: string;
  rawText: string;
  title: string;
};

type ToolConsoleRow = {
  kind: "command" | "output";
  label: string;
  text: string;
};

const HIDDEN_TOOL_ARGUMENT_KEYS = new Set([
  "context",
  "include_raw",
  "max_chars",
  "offset",
  "output_format",
  "output_mode",
  "raw",
  "source",
]);

const TOOL_ARGUMENT_LABELS: Record<string, string> = {
  cmd: "命令",
  command: "命令",
  cwd: "工作目录",
  end_line: "结束行",
  file: "文件",
  file_path: "文件",
  glob: "匹配规则",
  line_count: "行数",
  limit: "数量",
  max_results: "数量",
  path: "路径",
  pattern: "匹配词",
  query: "查询词",
  range: "范围",
  recursive: "递归",
  script: "脚本",
  start_line: "起始行",
  target: "目标",
  url: "网址",
};

const SUPPRESSED_TOOL_OUTPUTS = new Set([
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
  "状态已更新",
]);

function ToolInputRows({ entryId, rows }: { entryId: string; rows: ToolInputRow[] }) {
  return (
    <dl className="public-run-activity__tool-meta public-run-activity__tool-input">
      {rows.map((row) => (
        <div className="public-run-activity__tool-meta-item" key={`${entryId}:${row.label}:${row.text}`}>
          <dt>{row.label}</dt>
          <dd data-value-kind={row.valueKind ?? "plain"}>{row.text}</dd>
        </div>
      ))}
    </dl>
  );
}

function ToolStructuredResult({ result }: { result: StructuredToolResult }) {
  return (
    <section className="public-run-activity__tool-result" aria-label={result.title}>
      <header className="public-run-activity__tool-result-head">
        <span>{result.title}</span>
        <span>{result.items.length} 条</span>
      </header>
      <ol className="public-run-activity__tool-result-list">
        {result.items.map((item) => (
          <li className="public-run-activity__tool-result-item" key={`${item.index}:${item.path}`}>
            <span className="public-run-activity__tool-result-index">{item.index}</span>
            <span className="public-run-activity__tool-result-copy">
              <span className="public-run-activity__tool-result-title">{item.title}</span>
              <span className="public-run-activity__tool-result-path">{item.path}</span>
              {item.snippet ? <span className="public-run-activity__tool-result-snippet">{item.snippet}</span> : null}
            </span>
          </li>
        ))}
      </ol>
      {result.notice ? <p className="public-run-activity__tool-result-note">{result.notice}</p> : null}
      <ToolRawOutput text={result.rawText} />
    </section>
  );
}

function ToolRawOutput({ text }: { text: string }) {
  const lineCount = text.split("\n").length;
  const summary = lineCount > 1 ? `${lineCount} 行` : `${text.length} 字符`;
  return (
    <details className="public-run-activity__tool-raw">
      <summary>
        <span>原始输出</span>
        <span>{summary}</span>
      </summary>
      <pre>
        <code>{text}</code>
      </pre>
    </details>
  );
}

function toolConsoleRows({
  commandText,
  consoleLabel,
  hasStructuredResult,
  metaSections,
  outputText,
  statusTone,
  toolFamily,
}: {
  commandText: string;
  consoleLabel: string;
  hasStructuredResult: boolean;
  metaSections: Array<{ label: string; text: string }>;
  outputText: string;
  statusTone: string;
  toolFamily: ToolUiFamily;
}): ToolConsoleRow[] {
  const rows: ToolConsoleRow[] = [];
  if (shouldShowCommandRow({ commandText, metaSections, toolFamily })) {
    rows.push({ kind: "command", label: consoleLabel, text: commandText });
  }
  if (!hasStructuredResult && shouldShowOutputRow({ metaSections, outputText, statusTone })) {
    rows.push({ kind: "output", label: "返回结果", text: outputText });
  }
  return rows;
}

function toolInputRows(
  metaSections: Array<{ label: string; text: string }>,
  toolFamily: ToolUiFamily,
): ToolInputRow[] {
  const argumentText = firstLabeledSectionText(metaSections, "参数预览");
  const argumentRows = toolArgumentRows(argumentText, toolFamily);
  const visibleArgumentTexts = new Set(argumentRows.map((row) => compactTraceText(row.text)));
  const rows: ToolInputRow[] = [];

  for (const section of metaSections) {
    const label = cleanTraceText(section.label);
    const text = cleanTraceText(section.text);
    if (!label || !text || label === "参数预览") continue;
    if (label === "目标" && visibleArgumentTexts.has(compactTraceText(text))) continue;
    rows.push({
      label: toolSectionLabel(label, toolFamily),
      text,
      valueKind: toolSectionValueKind(label, toolFamily),
    });
  }

  rows.push(...argumentRows);
  return dedupeToolInputRows(rows);
}

function toolArgumentRows(argumentText: string, toolFamily: ToolUiFamily): ToolInputRow[] {
  const text = cleanTraceText(argumentText);
  if (!text) return [];
  const argumentsList = parsePreviewArguments(text);
  if (!argumentsList.length) {
    return [{ label: "参数", text, valueKind: "plain" }];
  }
  return argumentsList
    .filter((argument) => !isHiddenToolArgument(argument.key, toolFamily))
    .map((argument) => ({
      label: toolArgumentLabel(argument.key),
      text: argument.value,
      valueKind: toolArgumentValueKind(argument.key),
    }))
    .filter((row) => Boolean(row.text));
}

function isHiddenToolArgument(key: string, toolFamily: ToolUiFamily) {
  if (HIDDEN_TOOL_ARGUMENT_KEYS.has(key)) return true;
  if (toolFamily === "command" && ["cmd", "command", "script", "code"].includes(key)) return true;
  return false;
}

function parsePreviewArguments(value: string) {
  return splitPreviewArgumentParts(value)
    .map((part) => {
      const match = part.match(/^([A-Za-z_][\w.-]*)\s*=\s*([\s\S]*)$/);
      if (!match) return null;
      return {
        key: match[1].trim().toLowerCase(),
        value: stripWrappingQuotes(match[2].trim().replace(/,\s*$/, "")),
      };
    })
    .filter((argument): argument is { key: string; value: string } => Boolean(argument?.key && argument.value));
}

function splitPreviewArgumentParts(value: string) {
  const source = cleanTraceText(value);
  const parts: string[] = [];
  let quote = "";
  let depth = 0;
  let start = 0;

  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    const previous = source[index - 1];
    if (quote) {
      if (char === quote && previous !== "\\") quote = "";
      continue;
    }
    if (char === "\"" || char === "'") {
      quote = char;
      continue;
    }
    if (char === "{" || char === "[" || char === "(") depth += 1;
    if (char === "}" || char === "]" || char === ")") depth = Math.max(0, depth - 1);
    if (char === "," && depth === 0) {
      const part = cleanTraceText(source.slice(start, index));
      if (part) parts.push(part);
      start = index + 1;
    }
  }

  const tail = cleanTraceText(source.slice(start));
  if (tail) parts.push(tail);
  return parts;
}

function toolSectionLabel(label: string, toolFamily: ToolUiFamily) {
  if (label !== "目标") return label;
  if (toolFamily === "file" || toolFamily === "write") return "文件";
  if (toolFamily === "inspect") return "路径";
  return "目标";
}

function toolSectionValueKind(label: string, toolFamily: ToolUiFamily): ToolInputRow["valueKind"] {
  if (label === "目标" && ["file", "inspect", "write"].includes(toolFamily)) return "path";
  if (toolFamily === "command") return "code";
  return "plain";
}

function toolArgumentLabel(key: string) {
  return TOOL_ARGUMENT_LABELS[key] ?? key.replace(/[_-]+/g, " ");
}

function toolArgumentValueKind(key: string): ToolInputRow["valueKind"] {
  if (["command", "cmd", "script", "code"].includes(key)) return "code";
  if (["cwd", "file", "file_path", "path", "target"].includes(key)) return "path";
  return "plain";
}

function dedupeToolInputRows(rows: ToolInputRow[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = `${compactTraceText(row.label)}:${compactTraceText(row.text)}`;
    if (!row.label || !row.text || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function firstLabeledSectionText(sections: Array<{ label: string; text: string }>, label: string) {
  return sections.find((section) => cleanTraceText(section.label) === label)?.text ?? "";
}

function toolStructuredResult(outputText: string, toolFamily: ToolUiFamily): StructuredToolResult | null {
  const output = cleanTraceText(outputText);
  if (!output || isSuppressedToolOutput(output)) return null;
  if (toolFamily === "search") {
    const searchResult = parseSearchResultPayload(output);
    if (searchResult.items.length) {
      return {
        kind: "search_results",
        items: searchResult.items,
        notice: searchResult.notice,
        rawText: output,
        title: "命中结果",
      };
    }
  }
  return null;
}

function toolStructuredSummary(result: StructuredToolResult | null) {
  if (!result) return "";
  if (result.kind === "search_results") return `${result.title} · ${result.items.length} 条`;
  return "";
}

function parseSearchResultPayload(value: string) {
  const items = parseSearchResultItems(value);
  const lastItem = items[items.length - 1];
  if (!lastItem?.snippet || !isSearchResultNotice(lastItem.snippet)) {
    return { items, notice: "" };
  }
  return {
    items: items.map((item, index) => (
      index === items.length - 1 ? { ...item, snippet: "" } : item
    )),
    notice: lastItem.snippet,
  };
}

function parseSearchResultItems(value: string): ToolSearchResultItem[] {
  const text = cleanTraceText(value).replace(/\n+/g, " ");
  const markers = Array.from(text.matchAll(/\[(\d+)\]\s*/g));
  if (!markers.length) return [];

  return markers
    .map((marker, markerIndex) => {
      const start = (marker.index ?? 0) + marker[0].length;
      const end = markers[markerIndex + 1]?.index ?? text.length;
      const segment = cleanTraceText(text.slice(start, end));
      const parsed = parseSearchResultSegment(segment);
      if (!parsed) return null;
      return {
        index: Number(marker[1]) || markerIndex + 1,
        ...parsed,
      };
    })
    .filter((item): item is ToolSearchResultItem => Boolean(item));
}

function parseSearchResultSegment(segment: string): Omit<ToolSearchResultItem, "index"> | null {
  const text = cleanTraceText(segment).replace(/^[-:：]\s*/, "");
  if (!text) return null;

  const quoted = text.match(/^["']([^"']+)["']\s*([\s\S]*)$/);
  const rawPath = quoted ? quoted[1] : text.split(/\s+/)[0];
  const snippet = quoted ? quoted[2] : text.slice(rawPath.length);
  const path = cleanResultPath(rawPath);
  if (!path) return null;
  return {
    path,
    snippet: cleanTraceText(snippet),
    title: resultTitleFromPath(path),
  };
}

function cleanResultPath(value: string) {
  return stripWrappingQuotes(cleanTraceText(value)).replace(/[，,；;]$/u, "");
}

function resultTitleFromPath(value: string) {
  const normalized = value.replace(/\\/g, "/");
  const lastPart = normalized.split("/").filter(Boolean).pop() || value;
  return lastPart.replace(/:\d+(?::\d+)?$/u, "");
}

function isSearchResultNotice(value: string) {
  return /^(搜索已|结果可能|可缩小|已按|未穷尽)/u.test(cleanTraceText(value));
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
  if (isSuppressedToolOutput(output)) {
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

function isSuppressedToolOutput(value: string) {
  return SUPPRESSED_TOOL_OUTPUTS.has(cleanTraceText(value));
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

function stripWrappingQuotes(value: string) {
  const trimmed = cleanTraceText(value);
  if (trimmed.length < 2) return trimmed;
  if ((trimmed.startsWith("\"") && trimmed.endsWith("\"")) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1).replace(/\\"/g, "\"").replace(/\\'/g, "'");
  }
  return trimmed;
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
