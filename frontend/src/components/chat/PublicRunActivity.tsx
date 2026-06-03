"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  FileText,
  Loader2,
  PenLine,
  Search,
  Terminal,
} from "lucide-react";
import React from "react";

import type { PublicChatTimelineItem } from "@/lib/api";

type PublicRunActivityProps = {
  items: PublicChatTimelineItem[];
  assistantContent?: string;
};

const RECENT_HISTORY_LIMIT = 1;
const SUPPRESSED_STATUS_TEXT = new Set([
  "已同步最新进展。",
  "已接上当前工作，正在同步最新进展。",
  "已接上当前工作，正在整理上下文。",
  "已开始继续处理；接下来会持续汇报正在推进的步骤。",
  "任务执行器已接管，正在推进第一步。",
]);
const GENERIC_TOOL_WAIT_PREFIXES = [
  "已发起工具调用，正在等待工具返回",
  "已经过工具调用，正在等待工具返回",
];

function cleanText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function short(value: unknown, limit = 220) {
  const text = cleanText(value);
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function compactPathLabel(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  const normalized = text.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 2) return text;
  const tail = parts.at(-1) || "";
  const parent = parts.at(-2) || "";
  return parent ? `${parent}/${tail}` : tail;
}

function textOfItem(item: PublicChatTimelineItem) {
  return cleanText(item.text || item.detail || item.title || item.path || item.href);
}

function semanticTextOfItem(item: PublicChatTimelineItem) {
  const title = cleanText(item.title || item.text);
  const detail = cleanText(item.detail || item.path || item.href);
  return [cleanText(item.kind), title, detail, cleanText(item.state)].join("|").toLowerCase();
}

function samePublicText(left: unknown, right: unknown) {
  const leftText = cleanText(left);
  const rightText = cleanText(right);
  if (!leftText || !rightText) return false;
  return leftText === rightText || leftText.includes(rightText) || rightText.includes(leftText);
}

function itemKey(item: PublicChatTimelineItem, index: number) {
  const id = cleanText(item.item_id);
  if (id) return id;
  const refs = Array.isArray(item.trace_refs) ? item.trace_refs.filter(Boolean).join(",") : "";
  if (refs) return `${item.kind}:${refs}`;
  return `${item.kind}:${textOfItem(item)}:${index}`;
}

function dedupeItems(items: PublicChatTimelineItem[]) {
  const seen = new Set<string>();
  const semanticSeen = new Set<string>();
  const result: PublicChatTimelineItem[] = [];
  for (const [index, item] of items.entries()) {
    const key = itemKey(item, index);
    const semanticKey = semanticTextOfItem(item);
    if (!textOfItem(item) || seen.has(key)) {
      continue;
    }
    if (semanticKey && semanticSeen.has(semanticKey) && cleanText(item.kind) === "tool_activity") {
      continue;
    }
    seen.add(key);
    semanticSeen.add(semanticKey);
    result.push(item);
  }
  return result;
}

function publicItems(items: PublicChatTimelineItem[], assistantContent = "") {
  return dedupeItems(
    items
      .filter((item) => shouldRenderItem(item, assistantContent)),
  );
}

function isStatusUpdate(item: PublicChatTimelineItem) {
  const kind = cleanText(item.kind);
  return kind === "status_update" || kind === "stage" || kind === "task_order";
}

function isFinalItem(item: PublicChatTimelineItem) {
  const kind = cleanText(item.kind);
  return kind === "final_summary" || kind === "artifact";
}

function isAgentFeedback(item: PublicChatTimelineItem) {
  return cleanText(item.kind) === "assistant_text";
}

function shouldRenderItem(item: PublicChatTimelineItem, assistantContent: string) {
  const kind = cleanText(item.kind);
  const text = textOfItem(item);
  if (!text) return false;
  if ((kind === "assistant_text" || kind === "final_summary") && samePublicText(text, assistantContent)) {
    return false;
  }
  if (isStatusUpdate(item) && SUPPRESSED_STATUS_TEXT.has(text)) {
    return false;
  }
  if (/重复(?:只读)?工具调用/.test(text)) {
    return false;
  }
  if (["done", "completed", "running", "working", "回答已生成并写回会话", "会话输出完成"].includes(text.toLowerCase())) {
    return false;
  }
  if (/(agent_turn_terminal|runtime_invocation_packet_compiled|task_execution_packet_compiled|step_summary_recorded)/.test(text)) {
    return false;
  }
  return true;
}

export function hasPublicRunActivity(
  items: PublicChatTimelineItem[],
  assistantContent = "",
) {
  const plan = activityPlan(publicItems(items, assistantContent));
  return Boolean(plan.agentFeedback || plan.current || plan.recent.length || plan.finalItems.length || plan.collapsedCount);
}

function stateClass(item: PublicChatTimelineItem) {
  const state = cleanText(item.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return "error";
  if (["done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function ActivityIcon({ item }: { item: PublicChatTimelineItem }) {
  const state = stateClass(item);
  if (item.kind === "artifact") return <FileText size={14} />;
  if (state === "error") return <AlertTriangle size={14} />;
  if (state === "done") return <CheckCircle2 size={14} />;
  const action = actionDisplay(item);
  if (state === "running" || item.stream_state === "streaming") return <Loader2 className="public-run-activity__spinner" size={14} />;
  if (action.icon === "search") return <Search size={14} />;
  if (action.icon === "terminal") return <Terminal size={14} />;
  if (action.icon === "write") return <PenLine size={14} />;
  return <CircleDot size={14} />;
}

function actionDisplay(item: PublicChatTimelineItem) {
  const state = stateClass(item);
  const rawTitle = short(item.title || item.text || "处理进展", 220);
  const rawDetailCandidate = short(item.detail || item.path || item.href || "", 220);
  const rawDetail = suppressGenericToolWait(rawDetailCandidate);
  const combined = [rawTitle, rawDetail].filter(Boolean).join(" ");
  const lower = combined.toLowerCase();
  const running = state === "running";
  const done = state === "done";
  const targetFromUsePattern = rawTitle.match(/^正在使用(.+?)处理\s*(.+?)[。.]?$/);
  const searchFromTitle = rawTitle.match(/^正在搜索\s*(.+)$/);
  const readFromTitle = rawTitle.match(/^正在读取\s*(.+)$/);
  const inspectFromTitle = rawTitle.match(/^正在检查\s*(.+)$/);
  const writeFromTitle = rawTitle.match(/^正在(?:写入|编辑|更新)\s*(.+)$/);
  const completedSearch = rawTitle.match(/^搜索完成\s*(.+)?$/);
  const completedRead = rawTitle.match(/^读取完成\s*(.+)?$/);
  const completedInspect = rawTitle.match(/^检查完成\s*(.+)?$/);
  const completedWrite = rawTitle.match(/^(?:写入完成|更新完成|编辑完成)\s*(.+)?$/);
  const commandTitle = rawTitle.match(/^正在运行\s*(.+)$/);

  if (targetFromUsePattern) {
    const tool = targetFromUsePattern[1].toLowerCase();
    const target = compactPathLabel(rawDetail || targetFromUsePattern[2]);
    if (tool.includes("读取") || tool.includes("read") || tool.includes("file")) {
      return { title: done ? "已读取文件" : "读取文件", detail: target, icon: "read" };
    }
    if (tool.includes("搜索") || tool.includes("search") || tool.includes("text")) {
      return { title: done ? "已搜索代码" : "搜索代码引用", detail: target, icon: "search" };
    }
    if (tool.includes("写入") || tool.includes("编辑") || tool.includes("write") || tool.includes("edit")) {
      return { title: done ? "已更新文件" : "更新文件", detail: target, icon: "write" };
    }
  }
  if (searchFromTitle || lower.includes("search") || rawTitle.includes("搜索")) {
    return {
      title: done || completedSearch ? "已搜索代码" : running ? "搜索代码引用" : "搜索代码",
      detail: compactPathLabel(rawDetail || searchFromTitle?.[1] || completedSearch?.[1] || ""),
      icon: "search",
    };
  }
  if (
    inspectFromTitle
    || completedInspect
    || lower.includes("path_exists")
    || lower.includes("stat_path")
    || lower.includes("list_dir")
    || rawTitle.includes("确认路径")
    || rawTitle.includes("检查路径")
    || rawTitle.includes("artifact 路径")
  ) {
    const target = compactPathLabel(rawDetail || inspectFromTitle?.[1] || completedInspect?.[1] || "");
    return {
      title: done || completedInspect ? "已确认目标路径" : "确认目标路径",
      detail: target,
      icon: "read",
    };
  }
  if (readFromTitle || completedRead || lower.includes("read_file") || rawTitle.includes("读取")) {
    return {
      title: done || completedRead ? "已读取文件" : "读取文件",
      detail: compactPathLabel(rawDetail || readFromTitle?.[1] || completedRead?.[1] || ""),
      icon: "read",
    };
  }
  if (writeFromTitle || completedWrite || lower.includes("write_file") || lower.includes("edit_file") || /写入|编辑|更新/.test(rawTitle)) {
    return {
      title: done || completedWrite ? "已更新文件" : "更新文件",
      detail: compactPathLabel(rawDetail || writeFromTitle?.[1] || completedWrite?.[1] || ""),
      icon: "write",
    };
  }
  if (commandTitle || lower.includes("terminal") || rawTitle.includes("运行命令") || rawTitle.includes("正在运行")) {
    return {
      title: done ? "命令已完成" : "运行命令",
      detail: short(rawDetail || commandTitle?.[1] || "", 120),
      icon: "terminal",
    };
  }
  return {
    title: rawTitle,
    detail: compactPathLabel(rawDetail),
    icon: "default",
  };
}

function suppressGenericToolWait(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  const lowered = text.toLowerCase();
  if (GENERIC_TOOL_WAIT_PREFIXES.some((prefix) => lowered.startsWith(prefix))) {
    return "";
  }
  return text;
}

function actionSentence(item: PublicChatTimelineItem, variant: "current" | "history" | "final" = "history") {
  const kind = cleanText(item.kind);
  if (kind === "tool_activity") {
    const action = actionDisplay(item);
    const state = stateClass(item);
    const detail = cleanText(action.detail);
    const subject = detail ? `${action.title} ${detail}` : action.title;
    if (state === "done" || variant === "history") {
      return subject;
    }
    if (state === "error") {
      return `${subject} 时遇到问题`;
    }
    return `正在${subject}`;
  }
  const text = short(item.title || item.text || item.detail || "处理中", 180);
  if (variant === "current") {
    return text.startsWith("正在") ? text : `正在${text}`;
  }
  return text;
}

function ActivityCopy({ item, variant = "normal" }: { item: PublicChatTimelineItem; variant?: "normal" | "current" | "history" }) {
  const kind = cleanText(item.kind);
  if (kind === "blocked") {
    return (
      <>
        <strong>{short(item.text || item.title || "处理受阻", 180)}</strong>
        {item.recovery_hint ? <small>{short(item.recovery_hint, 180)}</small> : null}
      </>
    );
  }
  if (kind === "artifact") {
    const href = cleanText(item.href || item.path);
    return (
      <>
        <strong>{short(item.title || "产物已生成", 120)}</strong>
        {href ? <code>{short(href, 180)}</code> : null}
      </>
    );
  }
  if (kind === "final_summary" || kind === "assistant_text") {
    return (
      <>
        <strong>{short(item.text || item.detail || item.title, 240)}</strong>
      </>
    );
  }
  if (kind === "tool_activity") {
    return (
      <>
        <strong>{actionSentence(item, variant === "current" ? "current" : "history")}</strong>
      </>
    );
  }
  return (
    <>
      <strong>{actionSentence(item, variant === "current" ? "current" : "history")}</strong>
      {item.detail ? <small>{short(item.detail, 180)}</small> : null}
    </>
  );
}

function AgentFeedbackCopy({ item }: { item: PublicChatTimelineItem }) {
  return (
    <>
      <span className="public-run-activity__eyebrow">当前判断</span>
      <p>{short(item.text || item.detail || item.title, 260)}</p>
    </>
  );
}

function lastOf<T>(items: T[]) {
  return items.length ? items[items.length - 1] : null;
}

function activityPlan(items: PublicChatTimelineItem[]) {
  const finalItems = items.filter(isFinalItem);
  const statusItems = items.filter((item) => isStatusUpdate(item) && !isFinalItem(item));
  const agentFeedback = lastOf(items.filter((item) => isAgentFeedback(item) && !isFinalItem(item)));
  const actionItems = items.filter((item) => !isStatusUpdate(item) && !isFinalItem(item) && !isAgentFeedback(item));
  const current = [...actionItems].reverse().find((item) => {
    const state = stateClass(item);
    return state === "running" || state === "error";
  }) ?? null;
  const history = actionItems.filter((item) => item !== current);
  const recent = current ? [] : history.slice(-RECENT_HISTORY_LIMIT);
  const collapsedCount = Math.max(0, history.length - recent.length);
  const fallbackCurrent = !current && !recent.length && !finalItems.length
    ? lastOf(statusItems.filter((item) => stateClass(item) === "running")) ?? lastOf(statusItems)
    : null;
  return {
    collapsedCount,
    agentFeedback,
    recent,
    current: current ?? fallbackCurrent,
    finalItems,
  };
}

function collapsedSummary(count: number, hasCurrent: boolean) {
  if (!count) return "";
  return hasCurrent
    ? `前面已完成 ${count} 步，继续处理中。`
    : `已完成 ${count} 步处理。`;
}

export function PublicRunActivity({ items, assistantContent = "" }: PublicRunActivityProps) {
  const plan = activityPlan(publicItems(items, assistantContent));
  if (!plan.agentFeedback && !plan.current && !plan.recent.length && !plan.finalItems.length && !plan.collapsedCount) {
    return null;
  }
  return (
    <div className="public-run-activity" aria-label="处理进展">
      {plan.agentFeedback ? (
        <div
          className={`public-run-activity__agent-message public-run-activity__agent-message--${stateClass(plan.agentFeedback)}`}
          key={itemKey(plan.agentFeedback, -1)}
        >
          <AgentFeedbackCopy item={plan.agentFeedback} />
        </div>
      ) : null}
      {plan.collapsedCount ? (
        <div className="public-run-activity__row public-run-activity__row--done public-run-activity__row--collapsed">
          <span className="public-run-activity__icon" aria-hidden="true">
            <CheckCircle2 size={14} />
          </span>
          <span className="public-run-activity__copy">
            <small>{collapsedSummary(plan.collapsedCount, Boolean(plan.current))}</small>
          </span>
        </div>
      ) : null}
      {plan.recent.map((item, index) => (
        <div
          className={`public-run-activity__row public-run-activity__row--history public-run-activity__row--${stateClass(item)} public-run-activity__row--${cleanText(item.kind) || "item"}`}
          key={itemKey(item, index)}
        >
          <span className="public-run-activity__icon" aria-hidden="true">
            <ActivityIcon item={item} />
          </span>
          <span className="public-run-activity__copy">
            <ActivityCopy item={item} variant="history" />
          </span>
        </div>
      ))}
      {plan.current ? (
        <div
          className={`public-run-activity__row public-run-activity__row--current public-run-activity__row--${stateClass(plan.current)} public-run-activity__row--${cleanText(plan.current.kind) || "item"}`}
          key={itemKey(plan.current, plan.recent.length)}
        >
          <span className="public-run-activity__icon" aria-hidden="true">
            <ActivityIcon item={plan.current} />
          </span>
          <span className="public-run-activity__copy">
            <ActivityCopy item={plan.current} variant="current" />
          </span>
        </div>
      ) : null}
      {plan.finalItems.map((item, index) => (
        <div
          className={`public-run-activity__row public-run-activity__row--final public-run-activity__row--${stateClass(item)} public-run-activity__row--${cleanText(item.kind) || "item"}`}
          key={itemKey(item, index + plan.recent.length + 1)}
        >
          <span className="public-run-activity__icon" aria-hidden="true">
            <ActivityIcon item={item} />
          </span>
          <span className="public-run-activity__copy">
            <ActivityCopy item={item} />
          </span>
        </div>
      ))}
    </div>
  );
}
