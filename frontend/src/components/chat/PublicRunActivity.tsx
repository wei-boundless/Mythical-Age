"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  FileText,
  Loader2,
} from "lucide-react";
import React from "react";

import type { PublicChatTimelineItem, SessionRuntimeAttachment } from "@/lib/api";

type PublicRunActivityProps = {
  attachments: SessionRuntimeAttachment[];
  assistantContent?: string;
};

const RECENT_HISTORY_LIMIT = 2;
const SUPPRESSED_STATUS_TEXT = new Set([
  "已同步最新进展。",
  "已接上当前工作，正在同步最新进展。",
  "已接上当前工作，正在整理上下文。",
  "已开始继续处理；接下来会持续汇报正在推进的步骤。",
  "任务执行器已接管，正在推进第一步。",
]);

function cleanText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function short(value: unknown, limit = 220) {
  const text = cleanText(value);
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function textOfItem(item: PublicChatTimelineItem) {
  return cleanText(item.text || item.detail || item.title || item.path || item.href);
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
  const result: PublicChatTimelineItem[] = [];
  for (const [index, item] of items.entries()) {
    const key = itemKey(item, index);
    if (!textOfItem(item) || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(item);
  }
  return result;
}

function publicItems(attachments: SessionRuntimeAttachment[], assistantContent = "") {
  return dedupeItems(
    attachments
      .flatMap((attachment) => Array.isArray(attachment.public_timeline) ? attachment.public_timeline : [])
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
  if (["done", "completed", "running", "working", "回答已生成并写回会话", "会话输出完成"].includes(text.toLowerCase())) {
    return false;
  }
  if (/(agent_turn_terminal|runtime_invocation_packet_compiled|task_execution_packet_compiled|step_summary_recorded)/.test(text)) {
    return false;
  }
  return true;
}

export function hasPublicRunActivity(attachments: SessionRuntimeAttachment[], assistantContent = "") {
  const plan = activityPlan(publicItems(attachments, assistantContent));
  return Boolean(plan.current || plan.recent.length || plan.finalItems.length || plan.collapsedCount);
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
  if (state === "running" || item.stream_state === "streaming") return <Loader2 className="public-run-activity__spinner" size={14} />;
  return <CircleDot size={14} />;
}

function ActivityCopy({ item }: { item: PublicChatTimelineItem }) {
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
    return <strong>{short(item.text || item.detail || item.title, 240)}</strong>;
  }
  return (
    <>
      <strong>{short(item.title || item.text || "处理进展", 120)}</strong>
      {item.detail ? <small>{short(item.detail, 180)}</small> : null}
    </>
  );
}

function lastOf<T>(items: T[]) {
  return items.length ? items[items.length - 1] : null;
}

function activityPlan(items: PublicChatTimelineItem[]) {
  const finalItems = items.filter(isFinalItem);
  const statusItems = items.filter((item) => isStatusUpdate(item) && !isFinalItem(item));
  const actionItems = items.filter((item) => !isStatusUpdate(item) && !isFinalItem(item));
  const current = [...actionItems].reverse().find((item) => {
    const state = stateClass(item);
    return state === "running" || state === "error";
  }) ?? null;
  const history = actionItems.filter((item) => item !== current);
  const recent = history.slice(-RECENT_HISTORY_LIMIT);
  const collapsedCount = Math.max(0, history.length - recent.length);
  const fallbackCurrent = !current && !recent.length && !finalItems.length
    ? lastOf(statusItems.filter((item) => stateClass(item) === "running")) ?? lastOf(statusItems)
    : null;
  return {
    collapsedCount,
    recent,
    current: current ?? fallbackCurrent,
    finalItems,
  };
}

export function PublicRunActivity({ attachments, assistantContent = "" }: PublicRunActivityProps) {
  const plan = activityPlan(publicItems(attachments, assistantContent));
  if (!plan.current && !plan.recent.length && !plan.finalItems.length && !plan.collapsedCount) {
    return null;
  }
  return (
    <div className="public-run-activity" aria-label="处理进展">
      {plan.collapsedCount ? (
        <div className="public-run-activity__row public-run-activity__row--done public-run-activity__row--collapsed">
          <span className="public-run-activity__icon" aria-hidden="true">
            <CheckCircle2 size={14} />
          </span>
          <span className="public-run-activity__copy">
            <small>已完成 {plan.collapsedCount} 个步骤，已折叠。</small>
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
            <ActivityCopy item={item} />
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
            <ActivityCopy item={plan.current} />
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
