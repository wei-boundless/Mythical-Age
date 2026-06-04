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
import { normalizePublicTimelineItems, publicTimelineItemKey } from "@/lib/store/publicTimeline";
import {
  actionSentence as presentedActionSentence,
  actionViewForTimelineItem,
  cleanRunText,
  sameRunText,
  shortRunText,
  stateClassForTimelineItem,
  timelineItemText,
} from "@/components/chat/agentRunPresentation";

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

function cleanText(value: unknown) {
  return cleanRunText(value);
}

function short(value: unknown, limit = 220) {
  return shortRunText(value, limit);
}

function textOfItem(item: PublicChatTimelineItem) {
  return timelineItemText(item);
}

function samePublicText(left: unknown, right: unknown) {
  return sameRunText(left, right);
}

function publicItems(items: PublicChatTimelineItem[], assistantContent = "") {
  return normalizePublicTimelineItems(items.filter((item) => shouldRenderItem(item, assistantContent)));
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
  if (kind === "assistant_text") return false;
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
  return Boolean(plan.current || plan.recent.length || plan.finalItems.length || plan.collapsedCount);
}

function stateClass(item: PublicChatTimelineItem) {
  return stateClassForTimelineItem(item);
}

function ActivityIcon({ item }: { item: PublicChatTimelineItem }) {
  const state = stateClass(item);
  if (item.kind === "artifact") return <FileText size={14} />;
  if (state === "error") return <AlertTriangle size={14} />;
  if (state === "done") return <CheckCircle2 size={14} />;
  const action = actionDisplay(item);
  if (state === "running" || item.stream_state === "streaming") return <Loader2 className="public-run-activity__spinner" size={14} />;
  if (action.kind === "search") return <Search size={14} />;
  if (action.kind === "run") return <Terminal size={14} />;
  if (action.kind === "write") return <PenLine size={14} />;
  return <CircleDot size={14} />;
}

function actionDisplay(item: PublicChatTimelineItem) {
  return actionViewForTimelineItem(item);
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
    const action = actionDisplay(item);
    return (
      <>
        <strong>{presentedActionSentence(item, variant === "current" ? "current" : "history")}</strong>
        {action.observation ? <small className="public-run-activity__observation">{action.observation}</small> : null}
      </>
    );
  }
  return (
    <>
      <strong>{presentedActionSentence(item, variant === "current" ? "current" : "history")}</strong>
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

function activitySummary(plan: ReturnType<typeof activityPlan>) {
  if (plan.current) {
    const state = stateClass(plan.current);
    const kind = cleanText(plan.current.kind);
    const currentAction = presentedActionSentence(plan.current, "current");
    return {
      detail: state === "error"
        ? short(plan.current.recovery_hint || textOfItem(plan.current), 180)
        : plan.collapsedCount && currentAction
          ? `已完成 ${plan.collapsedCount} 步；${currentAction}。`
          : currentAction || "当前动作正在处理。",
      item: plan.current,
      meta: state === "error" ? "受阻" : "实时",
      title: state === "error" ? "需要处理" : kind === "status_update" ? "判断中" : "执行中",
      tone: state === "error" ? "error" : "running",
    };
  }
  const lastFinal = lastOf(plan.finalItems);
  if (lastFinal) {
    const state = stateClass(lastFinal);
    return {
      detail: state === "error" ? short(lastFinal.recovery_hint || textOfItem(lastFinal), 180) : "结果已进入回答收口。",
      item: lastFinal,
      meta: state === "error" ? "受阻" : "已收口",
      title: state === "error" ? "需要处理" : lastFinal.kind === "artifact" ? "产物就绪" : "已完成",
      tone: state === "error" ? "error" : "done",
    };
  }
  const lastRecent = lastOf(plan.recent);
  if (lastRecent || plan.collapsedCount) {
    const recentAction = lastRecent ? presentedActionSentence(lastRecent, "history") : "";
    return {
      detail: recentAction || (plan.collapsedCount ? `已完成 ${plan.collapsedCount} 步处理。` : "关键动作已完成。"),
      item: lastRecent,
      meta: "已同步",
      title: "阶段完成",
      tone: "done",
    };
  }
  return {
    detail: "正在同步处理进展。",
    item: null,
    meta: "实时",
    title: "处理中",
    tone: "running",
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
  if (!plan.current && !plan.recent.length && !plan.finalItems.length && !plan.collapsedCount) {
    return null;
  }
  const summary = activitySummary(plan);
  return (
    <div className={`public-run-activity public-run-activity--${summary.tone}`} aria-label="处理进展">
      <div className="public-run-activity__summary">
        <span className="public-run-activity__summary-icon" aria-hidden="true">
          {summary.item ? <ActivityIcon item={summary.item} /> : <CircleDot size={14} />}
        </span>
        <span className="public-run-activity__summary-copy">
          <strong>{summary.title}</strong>
          <small>{summary.detail}</small>
        </span>
        <em>{summary.meta}</em>
      </div>
      <div className="public-run-activity__rows">
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
            key={publicTimelineItemKey(item, index)}
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
            key={publicTimelineItemKey(plan.current, plan.recent.length)}
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
            key={publicTimelineItemKey(item, index + plan.recent.length + 1)}
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
    </div>
  );
}
