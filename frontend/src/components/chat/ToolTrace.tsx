"use client";

import {
  BrainCircuit,
  Check,
  ChevronDown,
  Clock3,
  Copy,
  Database,
  File as FileIcon,
  FilePenLine,
  FileText,
  Folder,
  Image as ImageIcon,
  ListTree,
  Search,
  Terminal,
  Wrench,
} from "lucide-react";
import React, { useEffect, useState } from "react";

import { TOOL_ACTION_LABELS } from "@/lib/toolDisplay";

import type { ActivityEntry, ActivityRenderUnit, ToolUiFamily } from "./PublicTimelineActivity";

export function ToolRound({ group }: { group: Extract<ActivityRenderUnit, { kind: "tool_round" }> }) {
  const [open, setOpen] = useState(false);
  const primaryFamily = toolRoundFamily(group.entries);
  const preview = splitToolTitle(group.preview);
  const liveNow = useLiveToolNow(toolToneIsActive(group.statusTone));
  const timing = toolTimingRecord(group, group.statusTone, liveNow);

  useEffect(() => {
    setOpen(false);
  }, [group.id]);

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
          {timing ? <ToolTimingBadge active={toolToneIsActive(group.statusTone)} timing={timing} /> : null}
          <span className="public-run-activity__tool-round-count">{group.count} 个</span>
          <span className="public-run-activity__tool-caret" aria-hidden="true">
            <ChevronDown size={14} />
          </span>
        </span>
      </summary>
      {open ? (
        <div className="public-run-activity__tool-round-body">
          {group.entries.map((entry) => (
            <ToolWindow entry={entry} key={entry.id} nested />
          ))}
        </div>
      ) : null}
    </details>
  );
}

export function ToolWindow({ entry, nested = false }: { entry: ActivityEntry; nested?: boolean }) {
  const statusTone = entry.statusTone ?? "running";
  const active = toolToneIsActive(statusTone);
  const liveNow = useLiveToolNow(active);
  const timing = toolTimingRecord(entry, statusTone, liveNow);
  const consoleLabel = entry.consoleLabel || "工具操作";
  const commandText = usableCommandText(entry.commandLine)
    || usableCommandText(entry.text)
    || "命令内容不可用";
  const commandPrefix = consoleLabel === "命令行" ? "$ " : "";
  const toolFamily = entry.toolFamily ?? "generic";
  const outputText = entry.outputText
    || (statusTone === "running" || statusTone === "waiting" ? "等待返回结果" : "无输出");
  const metaSections = (entry.sections ?? []).slice(0, 3);
  const [open, setOpen] = useState(false);
  const title = splitToolTitle(entry.text);
  const isReadFileWindow = toolFamily === "file" && title.action === "读取文件";
  const inputRows = toolInputRows(metaSections, toolFamily);
  const contentWindow = entry.contentWindow ?? (isReadFileWindow ? fallbackReadContentWindow(entry, metaSections, active) : undefined);
  const visibleInputRows = contentWindow || isReadFileWindow ? [] : inputRows;
  const structuredResult = toolStructuredResult(outputText, toolFamily, entry.text);
  const subtitle = toolStructuredSummary(structuredResult) || entry.detail || "";
  const consoleRows = toolConsoleRows({
    commandText,
    consoleLabel,
    hasStructuredResult: Boolean(structuredResult || contentWindow),
    metaSections,
    outputText,
    statusTone,
    toolFamily,
  });
  const showLiveNotice = active && !consoleRows.some((row) => row.kind === "output");
  const hasRuntimeMeta = Boolean(entry.startedAt || entry.updatedAt || entry.completedAt || active);
  const hasBody = Boolean(contentWindow)
    || visibleInputRows.length > 0
    || Boolean(structuredResult)
    || consoleRows.length > 0
    || hasRuntimeMeta
    || showLiveNotice;

  useEffect(() => {
    setOpen(false);
  }, [entry.id]);

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
        <span className="public-run-activity__tool-window-meta">
          {timing ? <ToolTimingBadge active={active} timing={timing} /> : null}
        </span>
        <span className="public-run-activity__tool-caret" aria-hidden="true">
          <ChevronDown size={14} />
        </span>
      </summary>
      {hasBody && open ? (
        <div className="public-run-activity__tool-window-body">
          {contentWindow ? <ToolContentWindow contentWindow={contentWindow} /> : null}
          {hasRuntimeMeta ? (
            <ToolRuntimeStrip
              active={active}
              entry={entry}
              timing={timing}
            />
          ) : null}
          {visibleInputRows.length ? <ToolInputRows rows={visibleInputRows} entryId={entry.id} /> : null}
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
          {showLiveNotice ? (
            <div className="public-run-activity__tool-live-line" role="status">
              <span className="public-run-activity__tool-live-indicator" aria-hidden="true" />
              <span>{statusTone === "waiting" ? "等待继续" : "等待工具返回"}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function usableCommandText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text || /^action\s*=\s*(?:command|run|verify)\s*$/i.test(text)) return "";
  return text;
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

type ToolTimingSource = Pick<ActivityEntry, "startedAt" | "updatedAt" | "completedAt">;

type ToolTiming = {
  elapsedSeconds: number;
  startedAt: string;
  endedAt: string;
};

function ToolTimingBadge({ active, timing }: { active: boolean; timing: ToolTiming }) {
  const label = `耗时 ${formatElapsedClock(timing.elapsedSeconds)}`;
  if (!label) return null;
  return (
    <span
      aria-label={formatElapsedAria(timing.elapsedSeconds)}
      className={`public-run-activity__tool-elapsed${active ? " public-run-activity__tool-elapsed--active" : ""}`}
      title={[
        formatElapsedAria(timing.elapsedSeconds),
        timing.startedAt ? `开始 ${timing.startedAt}` : "",
        timing.endedAt ? `结束 ${timing.endedAt}` : "",
      ].filter(Boolean).join(" · ")}
    >
      <Clock3 size={12} />
      <span>{label}</span>
    </span>
  );
}

function ToolRuntimeStrip({
  active,
  entry,
  timing,
}: {
  active: boolean;
  entry: ActivityEntry;
  timing: ToolTiming | null;
}) {
  return (
    <div className="public-run-activity__tool-runtime" data-activity-id={entry.id}>
      {active ? <span className="public-run-activity__tool-runtime-live">实时</span> : null}
      {timing?.startedAt ? <span className="public-run-activity__tool-runtime-time">开始 {timing.startedAt}</span> : null}
      {timing?.endedAt ? <span className="public-run-activity__tool-runtime-time">结束 {timing.endedAt}</span> : null}
    </div>
  );
}

function fallbackReadContentWindow(
  entry: ActivityEntry,
  metaSections: Array<{ label: string; text: string }>,
  active: boolean,
): ActivityEntry["contentWindow"] {
  const target = firstLabeledSectionText(metaSections, "目标");
  const args = parsePreviewArguments(firstLabeledSectionText(metaSections, "参数预览"));
  const argValue = (key: string) => args.find((argument) => argument.key === key)?.value ?? "";
  const path = cleanTraceText(target || argValue("path") || argValue("file") || argValue("file_path"));
  const startLine = positiveInteger(argValue("start_line"));
  const lineCount = positiveInteger(argValue("line_count"));
  const text = active
    ? "等待读取内容返回..."
    : "本次历史事件没有返回可展示的内容窗口。";
  return {
    authority: "frontend.tool_trace.read_file_window_fallback",
    content_available: false,
    kind: active ? "read_file_pending" : "read_file_missing_window",
    path,
    text,
    start_line: startLine ?? undefined,
    line_count: lineCount ?? undefined,
    preview_lines: text.split("\n").length,
  };
}

function ToolContentWindow({ contentWindow }: { contentWindow: NonNullable<ActivityEntry["contentWindow"]> }) {
  const [copied, setCopied] = useState(false);
  const path = cleanTraceText(contentWindow.path || "");
  const title = path ? resultTitleFromPath(path) : "读取内容";
  const rangeLabel = readWindowRangeLabel(contentWindow);
  const countLabel = readWindowCountLabel(contentWindow);
  const contentAvailable = contentWindow.content_available !== false;
  const reuseWindow = contentWindow.kind === "read_file_reuse";
  const missingWindow = !contentAvailable && !reuseWindow;
  const truncated = Boolean(contentWindow.preview_truncated || contentWindow.truncated || contentWindow.has_more);
  const previewTruncated = Boolean(contentWindow.preview_truncated);
  const visibleLineCount = readWindowTextLineCount(contentWindow.text);
  const previewLineCount = positiveInteger(contentWindow.preview_lines) ?? visibleLineCount;
  const canFoldContent = contentAvailable && visibleLineCount > 36;
  const [contentExpanded, setContentExpanded] = useState(false);
  const showFoldedContent = canFoldContent && !contentExpanded;
  const previewLabel = readWindowPreviewLabel(contentWindow, previewLineCount);

  useEffect(() => {
    setContentExpanded(false);
  }, [
    path,
    contentWindow.content_sha256,
    contentWindow.start_line,
    contentWindow.end_line,
    visibleLineCount,
  ]);

  const copyContent = async () => {
    const text = String(contentWindow.text || "");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section
      className="public-run-activity__tool-content-window"
      aria-label="读取到的文件内容"
      data-content-available={contentAvailable ? "true" : "false"}
      data-content-collapsed={showFoldedContent ? "true" : "false"}
      data-content-expanded={contentExpanded ? "true" : "false"}
      data-preview-truncated={previewTruncated ? "true" : "false"}
      data-window-kind={contentWindow.kind || "read_file"}
    >
      <header className="public-run-activity__tool-content-window-head">
        <span className="public-run-activity__tool-content-window-icon" aria-hidden="true">
          <FileText size={14} />
        </span>
        <span className="public-run-activity__tool-content-window-title">
          <strong>{title}</strong>
          {path ? <span>{path}</span> : null}
        </span>
        <span className="public-run-activity__tool-content-window-meta">
          {rangeLabel ? <span>{rangeLabel}</span> : null}
          {countLabel ? <span>{countLabel}</span> : null}
          {previewLabel ? <span>{previewLabel}</span> : null}
          {reuseWindow ? <span>复用</span> : null}
          {missingWindow ? <span>待返回</span> : null}
          {truncated && !previewLabel ? <span>预览</span> : null}
          {showFoldedContent ? <span>已折叠</span> : null}
        </span>
        <span className="public-run-activity__tool-content-window-actions">
          {canFoldContent ? (
            <button
              aria-label={contentExpanded ? "折叠读取内容" : "展开读取内容"}
              className="public-run-activity__tool-content-window-toggle"
              data-open={contentExpanded ? "true" : "false"}
              onClick={() => setContentExpanded((value) => !value)}
              title={contentExpanded ? "折叠" : "展开"}
              type="button"
            >
              <ChevronDown size={13} />
            </button>
          ) : null}
          <button
            aria-label={copied ? "已复制读取内容" : "复制读取内容"}
            className="public-run-activity__tool-content-window-copy"
            onClick={copyContent}
            type="button"
          >
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
        </span>
      </header>
      <pre className="public-run-activity__tool-content-window-code" tabIndex={0}>
        <code>{contentWindow.text}</code>
      </pre>
      {truncated ? (
        <footer className="public-run-activity__tool-content-window-foot">
          {contentWindow.preview_truncated ? <span>{readWindowPreviewNotice(contentWindow, previewLineCount)}</span> : null}
          {contentWindow.has_more && contentWindow.next_start_line ? <span>可从第 {contentWindow.next_start_line} 行继续读取。</span> : null}
        </footer>
      ) : null}
      {reuseWindow && (contentWindow.reused_observation_ref || contentWindow.exact_artifact_ref || contentWindow.reusable_result_ref) ? (
        <footer className="public-run-activity__tool-content-window-foot">
          {contentWindow.reused_observation_ref ? <span>{contentWindow.reused_observation_ref}</span> : null}
          {contentWindow.exact_artifact_ref ? <span>{contentWindow.exact_artifact_ref}</span> : null}
          {contentWindow.reusable_result_ref ? <span>{contentWindow.reusable_result_ref}</span> : null}
        </footer>
      ) : null}
    </section>
  );
}

function readWindowTextLineCount(value: unknown) {
  const text = String(value || "");
  if (!text) return 0;
  return text.split("\n").length;
}

function readWindowPreviewLabel(
  contentWindow: NonNullable<ActivityEntry["contentWindow"]>,
  previewLineCount: number,
) {
  if (!contentWindow.preview_truncated) return "";
  const returned = positiveInteger(contentWindow.returned_lines);
  if (returned && previewLineCount && previewLineCount < returned) {
    return `预览 ${previewLineCount}/${returned} 行`;
  }
  return previewLineCount ? `预览 ${previewLineCount} 行` : "预览";
}

function readWindowPreviewNotice(
  contentWindow: NonNullable<ActivityEntry["contentWindow"]>,
  previewLineCount: number,
) {
  const returned = positiveInteger(contentWindow.returned_lines);
  if (returned && previewLineCount && previewLineCount < returned) {
    return `当前只收到 ${previewLineCount}/${returned} 行预览。`;
  }
  return "当前只收到读取预览。";
}

function useLiveToolNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function toolToneIsActive(tone: ActivityEntry["statusTone"]) {
  return tone === "running" || tone === "waiting";
}

function toolTimingRecord(
  source: ToolTimingSource,
  tone: ActivityEntry["statusTone"],
  now: number,
) {
  const start = positiveTimestamp(source.startedAt);
  if (!start) return null;
  const end = toolToneIsActive(tone)
    ? now
    : positiveTimestamp(source.completedAt) ?? positiveTimestamp(source.updatedAt) ?? now;
  if (!Number.isFinite(end)) return null;
  return {
    elapsedSeconds: Math.max(0, Math.floor(end - start)),
    startedAt: formatToolClockTime(start),
    endedAt: toolToneIsActive(tone) ? "" : formatToolClockTime(end),
  };
}

function positiveTimestamp(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function formatElapsedClock(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;
  if (hours > 0) {
    return `${hours}:${padTimePart(minutes)}:${padTimePart(remainingSeconds)}`;
  }
  return `${minutes}:${padTimePart(remainingSeconds)}`;
}

function formatElapsedAria(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;
  const parts = [];
  if (hours) parts.push(`${hours} 小时`);
  if (minutes) parts.push(`${minutes} 分钟`);
  parts.push(`${remainingSeconds} 秒`);
  return `耗时 ${parts.join(" ")}`;
}

function formatToolClockTime(timestamp: number) {
  if (!timestamp) return "";
  return new Date(timestamp * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    second: "2-digit",
  });
}

function padTimePart(value: number) {
  return String(value).padStart(2, "0");
}

function readWindowRangeLabel(contentWindow: NonNullable<ActivityEntry["contentWindow"]>) {
  const start = positiveInteger(contentWindow.start_line);
  const end = positiveInteger(contentWindow.end_line);
  if (start && end) return start === end ? `第 ${start} 行` : `${start}-${end} 行`;
  if (start) return `第 ${start} 行起`;
  return "";
}

function readWindowCountLabel(contentWindow: NonNullable<ActivityEntry["contentWindow"]>) {
  const returned = positiveInteger(contentWindow.returned_lines);
  const total = positiveInteger(contentWindow.total_lines);
  if (returned && total) return `${returned}/${total} 行`;
  if (returned) return `${returned} 行`;
  return "";
}

function positiveInteger(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : null;
}

type ToolInputRow = {
  label: string;
  text: string;
  valueKind?: "code" | "path" | "plain";
};

type ToolSearchResultItem = {
  column?: number;
  index: number;
  line?: number;
  path: string;
  snippet: string;
  title: string;
};

type ToolDirectoryEntry = {
  index: number;
  kind: "dir" | "file";
  name: string;
  path: string;
  sizeBytes?: number;
  sizeLabel: string;
};

type StructuredToolResult =
  | {
      kind: "edit_error";
      code: string;
      message: string;
      repairInstruction: string;
      rejectedCount: number;
      rawText: string;
      title: string;
    }
  | {
      kind: "search_results";
      items: ToolSearchResultItem[];
      notice?: string;
      rawText: string;
      title: string;
    }
  | {
      directoryCount: number;
      fileCount: number;
      kind: "directory_listing";
      items: ToolDirectoryEntry[];
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
  "read_intent",
  "source",
  "intent",
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

const STRUCTURED_RESULT_MAX_ITEMS = 80;
const STRUCTURED_RESULT_PARSE_MAX_CHARS = 120000;
const STRUCTURED_RAW_MAX_CHARS = 20000;

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
  if (result.kind === "edit_error") {
    return (
      <section className="public-run-activity__tool-result" data-result-kind={result.kind} aria-label="文件编辑失败">
        <header className="public-run-activity__tool-result-head">
          <span className="public-run-activity__tool-result-head-main">
            <span className="public-run-activity__tool-result-head-title">文件编辑未提交</span>
            <span className="public-run-activity__tool-result-head-summary">{result.code}</span>
          </span>
        </header>
        <p className="public-run-activity__tool-result-note">{result.message}</p>
        {result.repairInstruction ? <p className="public-run-activity__tool-result-note">修复建议：{result.repairInstruction}</p> : null}
        {result.rejectedCount > 0 ? <p className="public-run-activity__tool-result-note">拒绝 {result.rejectedCount} 项；本批没有写入。</p> : null}
      </section>
    );
  }
  if (result.kind === "directory_listing") {
    return (
      <section className="public-run-activity__tool-result" data-result-kind={result.kind} aria-label={result.title}>
        <header className="public-run-activity__tool-result-head">
          <span className="public-run-activity__tool-result-head-main">
            <span className="public-run-activity__tool-result-head-title">{result.title}</span>
            <span className="public-run-activity__tool-result-head-summary">
              {result.items.length} 项 · {result.directoryCount} 目录 · {result.fileCount} 文件
            </span>
          </span>
        </header>
        <ol className="public-run-activity__tool-directory-list">
          {result.items.map((item) => (
            <li className="public-run-activity__tool-directory-item" data-entry-kind={item.kind} key={`${item.index}:${item.path}`}>
              <span className="public-run-activity__tool-directory-icon" aria-hidden="true">
                {item.kind === "dir" ? <Folder size={14} /> : <FileIcon size={14} />}
              </span>
              <span className="public-run-activity__tool-directory-copy">
                <span className="public-run-activity__tool-directory-name">{item.name}</span>
                <span className="public-run-activity__tool-directory-path">{item.path}</span>
              </span>
              <span className="public-run-activity__tool-directory-size">{item.sizeLabel}</span>
            </li>
          ))}
        </ol>
        <ToolRawOutput text={result.rawText} />
      </section>
    );
  }

  return (
    <section className="public-run-activity__tool-result" data-result-kind={result.kind} aria-label={result.title}>
      <header className="public-run-activity__tool-result-head">
        <span className="public-run-activity__tool-result-head-main">
          <span className="public-run-activity__tool-result-head-title">{result.title}</span>
          <span className="public-run-activity__tool-result-head-summary">{result.items.length} 条</span>
        </span>
      </header>
      <ol className="public-run-activity__tool-result-list">
        {result.items.map((item) => (
          <li className="public-run-activity__tool-result-item" key={`${item.index}:${item.path}`}>
            <span className="public-run-activity__tool-result-index">{item.index}</span>
            <span className="public-run-activity__tool-result-copy">
              <span className="public-run-activity__tool-result-title">
                <span>{item.title}</span>
                {item.line ? (
                  <span className="public-run-activity__tool-result-location">
                    {item.column ? `L${item.line}:C${item.column}` : `L${item.line}`}
                  </span>
                ) : null}
              </span>
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
  const previewText = boundedRawOutputText(text);
  const lineCount = previewText.split("\n").length;
  const summary = lineCount > 1 ? `${lineCount} 行` : `${previewText.length} 字符`;
  return (
    <details className="public-run-activity__tool-raw">
      <summary>
        <span>原始输出</span>
        <span>{summary}</span>
      </summary>
      <pre>
        <code>{previewText}</code>
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
  return compactToolInputRows(dedupeToolInputRows(rows), toolFamily);
}

function compactToolInputRows(rows: ToolInputRow[], toolFamily: ToolUiFamily) {
  const next = [...rows];
  const fileIndex = next.findIndex((row) => row.label === "文件");
  const pathIndex = next.findIndex((row) => row.label === "路径");
  if (fileIndex >= 0 && pathIndex >= 0) {
    const file = next[fileIndex];
    const path = next[pathIndex];
    next[fileIndex] = {
      label: "文件",
      text: compactFileAndPathText(file.text, path.text),
      valueKind: "path",
    };
    next.splice(pathIndex, 1);
  }

  const startIndex = next.findIndex((row) => row.label === "起始行");
  const endIndex = next.findIndex((row) => row.label === "结束行");
  const lineCountIndex = next.findIndex((row) => row.label === "行数");
  if (startIndex >= 0 || endIndex >= 0 || lineCountIndex >= 0) {
    const start = startIndex >= 0 ? next[startIndex]?.text : "";
    const end = endIndex >= 0 ? next[endIndex]?.text : "";
    const lineCount = lineCountIndex >= 0 ? next[lineCountIndex]?.text : "";
    const insertIndex = Math.min(
      ...[startIndex, endIndex, lineCountIndex].filter((index) => index >= 0),
    );
    const removeIndexes = [startIndex, endIndex, lineCountIndex]
      .filter((index) => index >= 0)
      .sort((left, right) => right - left);
    for (const index of removeIndexes) {
      next.splice(index, 1);
    }
    next.splice(insertIndex, 0, {
      label: "范围",
      text: formatToolLineRange(start, end, lineCount),
      valueKind: "plain",
    });
  }

  if (toolFamily === "file" || toolFamily === "write" || toolFamily === "inspect") {
    return next.filter((row) => !["数量"].includes(row.label));
  }
  return next;
}

function compactFileAndPathText(file: string, path: string) {
  const cleanFile = cleanTraceText(file);
  const cleanPath = cleanTraceText(path);
  if (!cleanFile) return cleanPath;
  if (!cleanPath || sameNormalizedPath(cleanFile, cleanPath)) return cleanFile;
  return `${cleanFile} · ${cleanPath}`;
}

function formatToolLineRange(start: string, end: string, lineCount: string) {
  const cleanStart = cleanTraceText(start);
  const cleanEnd = cleanTraceText(end);
  const cleanLineCount = cleanTraceText(lineCount);
  const range = cleanStart && cleanEnd
    ? `第 ${cleanStart}-${cleanEnd} 行`
    : cleanStart
      ? `第 ${cleanStart} 行起`
      : cleanEnd
        ? `至第 ${cleanEnd} 行`
        : "";
  const count = cleanLineCount ? `${cleanLineCount} 行` : "";
  return [range, count].filter(Boolean).join(" · ");
}

function sameNormalizedPath(left: string, right: string) {
  const normalize = (value: string) => cleanTraceText(value).replace(/\\/g, "/").toLowerCase();
  const normalizedLeft = normalize(left);
  const normalizedRight = normalize(right);
  return Boolean(normalizedLeft && normalizedRight) && (
    normalizedLeft === normalizedRight
    || normalizedLeft.endsWith(`/${normalizedRight}`)
    || normalizedRight.endsWith(`/${normalizedLeft}`)
  );
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

function toolStructuredResult(outputText: string, toolFamily: ToolUiFamily, toolTitle: string): StructuredToolResult | null {
  const output = boundedStructuredParseText(outputText);
  if (!output || isSuppressedToolOutput(output)) return null;
  const editError = parseEditErrorPayload(output);
  if (editError) return editError;
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
  if (toolFamily === "inspect" && splitToolTitle(toolTitle).action === "列出目录") {
    const listing = parseDirectoryListingPayload(output);
    if (listing.items.length) {
      return {
        directoryCount: listing.directoryCount,
        fileCount: listing.fileCount,
        kind: "directory_listing",
        items: listing.items,
        rawText: output,
        title: "目录内容",
      };
    }
  }
  return null;
}

function parseEditErrorPayload(value: string): Extract<StructuredToolResult, { kind: "edit_error" }> | null {
  let parsed: any;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  const error = parsed?.structured_error || parsed?.structured_payload?.structured_error || parsed?.tool_result?.structured_error;
  if (!error || typeof error !== "object") return null;
  const code = String(error.code || "").trim();
  if (!code.startsWith("target_") && !code.startsWith("batch_edit_")) return null;
  const rejected = parsed?.tool_result?.rejected_count ?? parsed?.structured_payload?.tool_result?.rejected_count ?? 0;
  return {
    kind: "edit_error",
    code,
    message: String(error.message || "目标编辑未提交。"),
    repairInstruction: String(error.repair_instruction || "重新读取目标后重试。"),
    rejectedCount: Number.isFinite(Number(rejected)) ? Number(rejected) : 0,
    rawText: value,
    title: "文件编辑未提交",
  };
}

function toolStructuredSummary(result: StructuredToolResult | null) {
  if (!result) return "";
  if (result.kind === "search_results") return `${result.title} · ${result.items.length} 条`;
  if (result.kind === "directory_listing") return `${result.title} · ${result.items.length} 项`;
  return "";
}

function parseSearchResultPayload(value: string) {
  const parsedItems = parseSearchResultItems(value);
  const items = parsedItems.slice(0, STRUCTURED_RESULT_MAX_ITEMS);
  const lastItem = items[items.length - 1];
  const limitNotice = parsedItems.length > items.length ? `仅显示前 ${items.length} 条。` : "";
  if (!lastItem?.snippet || !isSearchResultNotice(lastItem.snippet)) {
    return { items, notice: limitNotice };
  }
  return {
    items: items.map((item, index) => (
      index === items.length - 1 ? { ...item, snippet: "" } : item
    )),
    notice: [lastItem.snippet, limitNotice].filter(Boolean).join(" "),
  };
}

function parseSearchResultItems(value: string): ToolSearchResultItem[] {
  const bracketItems = parseBracketSearchResultItems(value);
  if (bracketItems.length) return bracketItems;
  const lineItems = parseColonSearchResultItems(value);
  if (lineItems.length) return lineItems;
  return parsePathListSearchResultItems(value);
}

function parseBracketSearchResultItems(value: string): ToolSearchResultItem[] {
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
  const located = splitResultPathLocation(path);
  return {
    column: located.column,
    line: located.line,
    path: located.path,
    snippet: cleanTraceText(snippet),
    title: resultTitleFromPath(located.path),
  };
}

function parseColonSearchResultItems(value: string): ToolSearchResultItem[] {
  const text = cleanTraceText(value);
  const records = text.includes("\n")
    ? text.split(/\n+/)
    : text.split(/\s+(?=(?:[A-Za-z]:)?[^\s]+:\d+(?::\d+)?:)/);
  return records
    .map((record, index) => parseColonSearchResultLine(record, index + 1))
    .filter((item): item is ToolSearchResultItem => Boolean(item));
}

function parseColonSearchResultLine(value: string, index: number): ToolSearchResultItem | null {
  const text = cleanTraceText(value);
  const match = text.match(/^(.+):(\d+)(?::(\d+))?:(.*)$/u);
  if (!match) return null;
  const path = cleanResultPath(match[1]);
  if (!looksLikeResultPath(path)) return null;
  const line = positiveInteger(match[2]) ?? undefined;
  const column = positiveInteger(match[3]) ?? undefined;
  return {
    column,
    index,
    line,
    path,
    snippet: cleanTraceText(match[4]),
    title: resultTitleFromPath(path),
  };
}

function parsePathListSearchResultItems(value: string): ToolSearchResultItem[] {
  const text = cleanTraceText(value).replace(/\n+/g, " ");
  const matches = Array.from(text.matchAll(/(?:^|\s)([A-Za-z]:(?:[\\/][^\s,;，；]+)+|(?:\.{1,2}[\\/])?[A-Za-z0-9_@~.-]+(?:[\\/][A-Za-z0-9_@~.-]+)*\.[A-Za-z0-9]{1,12}(?::\d+(?::\d+)?)?)(?=\s|$|[,;，；])/gu));
  const seen = new Set<string>();
  const items: ToolSearchResultItem[] = [];
  for (const match of matches) {
    const rawPath = cleanResultPath(match[1]);
    const located = splitResultPathLocation(rawPath);
    if (!looksLikeResultPath(located.path)) continue;
    const key = `${located.path}:${located.line ?? ""}:${located.column ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({
      column: located.column,
      index: items.length + 1,
      line: located.line,
      path: located.path,
      snippet: "",
      title: resultTitleFromPath(located.path),
    });
    if (items.length >= STRUCTURED_RESULT_MAX_ITEMS) break;
  }
  return items;
}

function parseDirectoryListingPayload(value: string) {
  const items = parseDirectoryListingItems(value).slice(0, STRUCTURED_RESULT_MAX_ITEMS);
  const directoryCount = items.filter((item) => item.kind === "dir").length;
  const fileCount = items.filter((item) => item.kind === "file").length;
  return { directoryCount, fileCount, items };
}

function parseDirectoryListingItems(value: string): ToolDirectoryEntry[] {
  const text = cleanTraceText(value).replace(/\n+/g, " ");
  const records = Array.from(text.matchAll(/\b(dir|file)\s+(.+?)\s+(-|\d+(?:\.\d+)?\s*(?:bytes?|b|kb|mb|gb|kib|mib|gib))(?=\s+(?:dir|file)\s+|$)/giu));
  return records
    .map((record, index): ToolDirectoryEntry | null => {
      const kind = record[1].toLowerCase() === "dir" ? "dir" : "file";
      const path = cleanResultPath(record[2]);
      if (!path) return null;
      const sizeLabel = formatDirectorySizeLabel(record[3]);
      const item: ToolDirectoryEntry = {
        index: index + 1,
        kind,
        name: resultTitleFromPath(path) || path,
        path,
        sizeLabel,
      };
      const sizeBytes = parseSizeBytes(sizeLabel);
      if (typeof sizeBytes === "number") {
        item.sizeBytes = sizeBytes;
      }
      return item;
    })
    .filter((item): item is ToolDirectoryEntry => item !== null);
}

function cleanResultPath(value: string) {
  return stripWrappingQuotes(cleanTraceText(value)).replace(/[，,；;]$/u, "");
}

function splitResultPathLocation(value: string) {
  const path = cleanResultPath(value);
  const match = path.match(/^(.+):(\d+)(?::(\d+))?$/u);
  if (!match || !looksLikeResultPath(match[1])) {
    return { path };
  }
  return {
    column: positiveInteger(match[3]) ?? undefined,
    line: positiveInteger(match[2]) ?? undefined,
    path: cleanResultPath(match[1]),
  };
}

function resultTitleFromPath(value: string) {
  const normalized = value.replace(/\\/g, "/");
  const lastPart = normalized.split("/").filter(Boolean).pop() || value;
  return lastPart.replace(/:\d+(?::\d+)?$/u, "");
}

function looksLikeResultPath(value: string) {
  const path = cleanTraceText(value);
  return Boolean(path && (
    /[\\/]/u.test(path)
    || /^[A-Za-z]:/u.test(path)
    || /^[\w@~.-]+\.[A-Za-z0-9]{1,12}$/u.test(path)
  ));
}

function formatDirectorySizeLabel(value: string) {
  const text = cleanTraceText(value).replace(/\s+/g, " ");
  if (!text || text === "-") return "目录";
  return text.replace(/\bbytes?\b/iu, "bytes");
}

function parseSizeBytes(value: string) {
  const match = cleanTraceText(value).match(/^(\d+(?:\.\d+)?)\s*(bytes?|b|kb|mb|gb|kib|mib|gib)$/iu);
  if (!match) return undefined;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return undefined;
  const unit = match[2].toLowerCase();
  const multipliers: Record<string, number> = {
    b: 1,
    byte: 1,
    bytes: 1,
    gb: 1000 ** 3,
    gib: 1024 ** 3,
    kb: 1000,
    kib: 1024,
    mb: 1000 ** 2,
    mib: 1024 ** 2,
  };
  return Math.round(amount * (multipliers[unit] ?? 1));
}

function isSearchResultNotice(value: string) {
  return /^(搜索已|结果可能|可缩小|已按|未穷尽)/u.test(cleanTraceText(value));
}

function boundedStructuredParseText(value: string) {
  return cleanTraceText(value).slice(0, STRUCTURED_RESULT_PARSE_MAX_CHARS);
}

function boundedRawOutputText(value: string) {
  const text = cleanTraceText(value);
  if (text.length <= STRUCTURED_RAW_MAX_CHARS) return text;
  return `${text.slice(0, STRUCTURED_RAW_MAX_CHARS).trimEnd()}\n... 已按性能上限截断`;
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

function splitToolTitle(value: string) {
  const text = String(value || "").trim();
  for (const action of TOOL_ACTION_LABELS) {
    if (text === action) return { action, target: "" };
    if (text.startsWith(`${action} `)) return { action, target: text.slice(action.length).trim() };
    if (text.startsWith(`${action}：`)) return { action, target: text.slice(action.length + 1).trim() };
  }
  return { action: text, target: "" };
}
