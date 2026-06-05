"use client";

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

function stripPublicFeedbackLabel(value: unknown) {
  return cleanText(value).replace(/^(?:观察结果|观察报告|观察)[：:\s]*/u, "").trim();
}

function shortFact(value: unknown, limit = 220) {
  return short(stripPublicFeedbackLabel(value), limit);
}

function blockedFact(value: unknown, fallback = "") {
  const text = stripPublicFeedbackLabel(value) || stripPublicFeedbackLabel(fallback);
  if (/shell command uses control operators/i.test(text)) {
    return "命令被安全规则拦截，我会拆成更简单的步骤继续。";
  }
  if (/path traversal detected/i.test(text)) {
    return "路径被安全规则拦截，我会改用项目内可访问路径继续。";
  }
  if (/当前(?:动作|步骤).*(?:路径|权限|输入).*继续/.test(text)) {
    return "当前步骤没有执行成功，我会换一种方式继续。";
  }
  if (/permission|denied|权限|拒绝/.test(text)) {
    return "当前权限不足，我会改用允许的路径或方式继续。";
  }
  return text || "这一步没有执行成功，我会换一种方式继续。";
}

function sentence(value: unknown) {
  const text = shortFact(value, 220);
  if (!text) return "";
  return /[。！？.!?]$/.test(text) ? text : `${text}。`;
}

function objectText(verb: string, target: string) {
  return /[A-Za-z0-9_.\\/:-]/.test(target) ? `${verb} ${target}` : `${verb}${target}`;
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

function isWaitingItem(item: PublicChatTimelineItem) {
  const state = cleanText(item.state).toLowerCase();
  const phase = cleanText(item.phase).toLowerCase();
  const text = textOfItem(item);
  return ["waiting", "queued", "paused"].includes(state)
    || phase === "waiting"
    || (isStatusUpdate(item) && /等待|暂停|队列|停住/.test(text));
}

function isStoppedItem(item: PublicChatTimelineItem) {
  const state = cleanText(item.state).toLowerCase();
  const phase = cleanText(item.phase).toLowerCase();
  const text = textOfItem(item);
  return ["stopped", "aborted", "user_aborted", "cancelled", "canceled"].includes(state)
    || ["stopped", "aborted"].includes(phase)
    || (isStatusUpdate(item) && /已停止|已中断|停止本轮/.test(text));
}

function shouldRenderItem(item: PublicChatTimelineItem, assistantContent: string) {
  const kind = cleanText(item.kind);
  const text = textOfItem(item);
  if (!text) return false;
  if (assistantContent.trim() && isStaleRawToolFailure(item, text)) {
    return false;
  }
  if (kind === "assistant_text" || kind === "opening_judgment") return false;
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

function isStaleRawToolFailure(item: PublicChatTimelineItem, text: string) {
  if (cleanText(item.kind) !== "tool_activity") return false;
  if (stateClass(item) !== "error") return false;
  return /(?:Tool execution failed|Fetch failed|HTTP\s+4\d\d|HTTP\s+5\d\d|tool_execution_failed)/i.test(text);
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

function actionDisplay(item: PublicChatTimelineItem) {
  return actionViewForTimelineItem(item);
}

function naturalActionSentence(item: PublicChatTimelineItem) {
  const kind = cleanText(item.kind);
  if (kind !== "tool_activity" && kind !== "work_action") {
    return sentence(item.text || item.detail || item.title || "我正在同步当前处理进展。");
  }
  const action = actionDisplay(item);
  const target = action.detail;
  if (action.kind === "read") {
    return target
      ? `我先${objectText("读取", target)}，把判断建立在真实上下文上。`
      : "我先补齐上下文，避免凭空判断。";
  }
  if (action.kind === "search") {
    return target
      ? `我先${objectText("搜索", target)}，定位真正影响输出的位置。`
      : "我先定位调用链，找到真正影响输出的位置。";
  }
  if (action.kind === "inspect") {
    return target
      ? `我先确认${/[A-Za-z0-9_.\\/:-]/.test(target) ? ` ${target}` : target} 的状态，避免后续动作偏离目标。`
      : "我先确认目标状态，再决定下一步动作。";
  }
  if (action.kind === "write" || action.kind === "edit") {
    return target
      ? `我会${objectText("更新", target)}，再用结果验证一遍。`
      : "我会先把改动落下去，再用结果验证一遍。";
  }
  if (action.kind === "run" || action.kind === "verify") {
    if (target && /测试$/.test(target)) {
      return `我正在跑${target}，用结果判断是否还要继续修正。`;
    }
    return target
      ? `我正在${objectText("验证", target)}，用结果判断是否还要继续修正。`
      : "我正在验证当前状态，用结果判断是否还要继续修正。";
  }
  if (action.kind === "memory") {
    return "我先接上相关记忆，把前面的要求纳入当前判断。";
  }
  if (action.kind === "prepare") {
    return target
      ? `我先${objectText("准备", target)}，让后续产物有明确落点。`
      : "我先准备输出位置，让后续产物有明确落点。";
  }
  if (action.kind === "browse") {
    return target
      ? `我先${objectText("读取", target)}，把判断建立在真实资料上。`
      : "我先读取相关页面，把判断建立在真实资料上。";
  }
  if (action.kind === "image") {
    return "我正在生成图像，拿到结果后会确认是否可用。";
  }
  return target
    ? `我先${objectText("处理", target)}，拿到结果后再给你明确判断。`
    : "我已经接上当前任务，先确认关键事实，再给你明确判断。";
}

function ActivityCopy({ item, variant = "normal" }: { item: PublicChatTimelineItem; variant?: "normal" | "current" | "history" }) {
  const kind = cleanText(item.kind);
  if (kind === "blocked") {
    return (
      <>
        <strong>{short(blockedFact(item.text || item.title, item.recovery_hint), 180)}</strong>
        {item.recovery_hint ? <small>{shortFact(blockedFact(item.recovery_hint), 180)}</small> : null}
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
        {Array.isArray(item.verified) && item.verified.length ? (
          <small className="public-run-activity__observation">验证：{item.verified.slice(0, 3).map((entry) => short(entry, 90)).join("；")}</small>
        ) : null}
      </>
    );
  }
  if (kind === "todo_plan") {
    return <TodoPlanCopy item={item} />;
  }
  if (kind === "observation_report") {
    const fact = shortFact(item.detail || item.title || "当前事实已记录。", 180);
    return (
      <>
        <strong>{fact}</strong>
        {item.implication ? <small>{shortFact(item.implication, 150)}</small> : null}
      </>
    );
  }
  if (kind === "tool_activity" || kind === "work_action") {
    const action = actionDisplay(item);
    return (
      <>
        <strong>{presentedActionSentence(item, variant === "current" ? "current" : "history")}</strong>
        {action.observation ? <small className="public-run-activity__observation">{shortFact(action.observation, 180)}</small> : null}
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

function TodoPlanCopy({ item }: { item: PublicChatTimelineItem }) {
  const todos = Array.isArray(item.todo_items) ? item.todo_items : [];
  const completed = todos.filter((todo) => cleanText(todo.status) === "completed").length;
  const active = todos.find((todo) => cleanText(todo.todo_id) === cleanText(item.active_item_id))
    ?? todos.find((todo) => cleanText(todo.status) === "in_progress")
    ?? null;
  const pending = todos.filter((todo) => cleanText(todo.status) === "pending").slice(0, 2);
  const visibleTodos = [
    ...todos.filter((todo) => cleanText(todo.status) === "completed").slice(-1),
    ...(active ? [active] : []),
    ...pending,
  ].filter((todo, index, list) =>
    list.findIndex((candidate) => cleanText(candidate.todo_id) === cleanText(todo.todo_id)) === index
  ).slice(0, 4);
  const hidden = Math.max(0, todos.length - visibleTodos.length);
  return (
    <>
      <strong>{item.completion_ready ? "处理清单已完成" : active ? `当前：${short(active.active_form || active.content, 140)}` : "处理清单已建立"}</strong>
      <small>{item.detail || `${completed}/${todos.length} 已完成`}</small>
      {visibleTodos.length ? (
        <span className="public-run-activity__todo-list">
          {visibleTodos.map((todo) => {
            const status = cleanText(todo.status);
            return (
              <span className={`public-run-activity__todo public-run-activity__todo--${status || "pending"}`} key={cleanText(todo.todo_id) || cleanText(todo.content)}>
                <b aria-hidden="true">{status === "completed" ? "✓" : status === "in_progress" ? "●" : "○"}</b>
                <span>{short(status === "in_progress" ? todo.active_form || todo.content : todo.content, 120)}</span>
              </span>
            );
          })}
          {hidden ? <em>还有 {hidden} 项</em> : null}
        </span>
      ) : null}
    </>
  );
}

function lastOf<T>(items: T[]) {
  return items.length ? items[items.length - 1] : null;
}

function naturalResultFact(action: ReturnType<typeof actionDisplay>, item: PublicChatTimelineItem) {
  const raw = readableToolObservation(action.observation, action.detail, presentedActionSentence(item, "history"));
  if (/关键上下文已拿到|已读到关键信息/.test(raw)) {
    return action.detail
      ? `已${objectText("读到", action.detail)}，下一步可以基于文件事实判断。`
      : "已读到关键上下文，下一步可以基于文件事实判断。";
  }
  if (/相关引用已定位|已定位相关线索/.test(raw)) {
    return action.detail
      ? `已定位到${/[A-Za-z0-9_.\\/:-]/.test(action.detail) ? ` ${action.detail}` : action.detail} 的相关线索，下一步会收敛到真正的改动点。`
      : "已定位到相关线索，下一步会收敛到真正的改动点。";
  }
  if (/目标状态已确认|已确认/.test(raw) && action.kind === "inspect") {
    return action.detail ? `已确认${/[A-Za-z0-9_.\\/:-]/.test(action.detail) ? ` ${action.detail}` : action.detail} 的当前状态。` : "已确认目标当前状态。";
  }
  if (/记忆检索已返回/.test(raw)) {
    return "相关记忆已返回，下一步会纳入判断。";
  }
  if (/输出准备/.test(raw)) {
    return "输出准备已确认，可以继续推进。";
  }
  if (/图像生成已返回/.test(raw)) {
    return "图像生成已返回，下一步会确认产物是否可用。";
  }
  return sentence(raw);
}

function activityPlan(items: PublicChatTimelineItem[]) {
  const finalItems = items.filter(isFinalItem);
  const statusItems = items.filter((item) => isStatusUpdate(item) && !isFinalItem(item));
  const actionItems = items.filter((item) => !isStatusUpdate(item) && !isFinalItem(item));
  const stoppedCurrent = lastOf(items.filter(isStoppedItem));
  const waitingCurrent = lastOf(items.filter(isWaitingItem));
  const liveItems = actionItems.filter((item) => {
    const state = stateClass(item);
    return state === "running" || state === "error";
  });
  const liveCurrent = lastOf(liveItems.filter(isPreferredLiveItem)) ?? lastOf(liveItems);
  const latestObservation = [...actionItems].reverse().find((item) => cleanText(item.kind) === "observation_report") ?? null;
  const latestAction = lastOf(actionItems);
  const current = stoppedCurrent ?? waitingCurrent ?? liveCurrent ?? latestObservation ?? latestAction;
  const fallbackCurrent = !current && !finalItems.length
    ? lastOf(statusItems.filter((item) => stateClass(item) === "running")) ?? lastOf(statusItems)
    : null;
  const activeCurrent = current ?? fallbackCurrent;
  return {
    collapsedCount: 0,
    recent: [] as PublicChatTimelineItem[],
    current: activeCurrent,
    finalItems,
  };
}

function isPreferredLiveItem(item: PublicChatTimelineItem) {
  const kind = cleanText(item.kind);
  if (kind === "work_action" && cleanText(item.action_kind) && cleanText(item.action_kind) !== "work") return true;
  return kind === "todo_plan" || kind === "observation_report" || kind === "blocked";
}

function shouldRenderDetailRow(item: PublicChatTimelineItem) {
  return cleanText(item.kind) === "todo_plan";
}

function ActivityRows({ plan }: { plan: ReturnType<typeof activityPlan> }) {
  const rows = [
    ...plan.recent.map((item) => ({ item, variant: "history" as const })),
    ...(plan.current && shouldRenderDetailRow(plan.current)
      ? [{ item: plan.current, variant: "current" as const }]
      : []),
  ];
  if (!rows.length) {
    return null;
  }
  return (
    <div className="public-run-activity__rows">
      {rows.map(({ item, variant }, index) => (
        <div
          className={`public-run-activity__row public-run-activity__row--${variant} public-run-activity__row--${stateClass(item)} public-run-activity__row--${cleanText(item.kind) || "item"}`}
          key={publicTimelineItemKey(item, index)}
        >
          <span className="public-run-activity__copy">
            <ActivityCopy item={item} variant={variant} />
          </span>
        </div>
      ))}
    </div>
  );
}

function genericObservation(value: string) {
  return /(?:动作|结果)已返回，继续根据结果推进下一步|当前(?:动作|步骤).*(?:路径|权限|输入).*继续/.test(value);
}

function readableToolObservation(value: string, target = "", fallback = "") {
  const observation = stripPublicFeedbackLabel(value);
  if (observation && !genericObservation(observation)) {
    return observation;
  }
  const fallbackText = stripPublicFeedbackLabel(fallback);
  if (fallbackText && !/动作已返回|结果已返回|执行动作|处理步骤/.test(fallbackText)) {
    return fallbackText;
  }
  const targetText = cleanText(target);
  return targetText
    ? `${targetText} 已返回，我会据此推进下一步。`
    : "结果已返回，我会据此推进下一步。";
}

function finalActivitySummary(plan: ReturnType<typeof activityPlan>) {
  const lastFinal = lastOf(plan.finalItems);
  if (!lastFinal) return null;
  const state = stateClass(lastFinal);
  const finalText = shortFact(lastFinal.text || lastFinal.detail || lastFinal.title || lastFinal.path || lastFinal.href, 180);
  const errorText = short(blockedFact(lastFinal.recovery_hint || finalText), 180);
  return {
    detail: state === "error" ? "" : finalText || "结果已进入回答收口。",
    item: lastFinal,
    title: state === "error" ? errorText : lastFinal.kind === "artifact" ? "产物就绪" : "收尾总结",
    tone: state === "error" ? "error" : "done",
  };
}

function activitySummary(plan: ReturnType<typeof activityPlan>) {
  if (plan.current) {
    if (isStoppedItem(plan.current)) {
      return {
        detail: "",
        item: plan.current,
        title: sentence(plan.current.detail || plan.current.text || "本轮已停止，当前运行不会继续推进。"),
        tone: "stopped",
      };
    }
    if (isWaitingItem(plan.current)) {
      return {
        detail: "",
        item: plan.current,
        title: sentence(plan.current.detail || plan.current.text || "当前任务已停在可继续状态，继续后会接上现有进度。"),
        tone: "waiting",
      };
    }
    const state = stateClass(plan.current);
    const kind = cleanText(plan.current.kind);
    const currentAction = presentedActionSentence(plan.current, "current");
    if (kind === "todo_plan") {
      const todos = Array.isArray(plan.current.todo_items) ? plan.current.todo_items : [];
      const active = todos.find((todo) => cleanText(todo.status) === "in_progress");
      return {
        detail: active ? sentence(active.active_form || active.content) : sentence(plan.current.detail || "清单会跟随当前处理持续更新。"),
        item: plan.current,
        title: plan.current.completion_ready ? "处理清单已完成。" : "我会按处理清单推进当前任务。",
        tone: plan.current.completion_ready ? "done" : "running",
      };
    }
    if (kind === "observation_report") {
      const fact = shortFact(plan.current.detail || plan.current.implication || "关键事实已记录。", 180);
      return {
        detail: "",
        item: plan.current,
        title: sentence(fact),
        tone: state === "error" ? "error" : "done",
      };
    }
    const action = actionDisplay(plan.current);
    if (state === "done") {
      const fact = short(naturalResultFact(action, plan.current), 180);
      return {
        detail: "",
        item: plan.current,
        title: sentence(fact || currentAction || "结果已返回"),
        tone: "done",
      };
    }
    const errorDetail = kind === "blocked"
      ? blockedFact(textOfItem(plan.current), plan.current.recovery_hint)
      : genericObservation(action.observation)
        ? currentAction || plan.current.recovery_hint || "当前步骤没有执行成功，我会换一种方式继续。"
        : action.observation || currentAction || plan.current.recovery_hint || "当前步骤没有执行成功，我会换一种方式继续。";
    const errorFact = blockedFact(errorDetail);
    return {
      detail: "",
      item: plan.current,
      title: state === "error" ? sentence(errorFact) : naturalActionSentence(plan.current),
      tone: state === "error" ? "error" : "running",
    };
  }
  const finalSummary = finalActivitySummary(plan);
  if (finalSummary) return finalSummary;
  const lastRecent = lastOf(plan.recent);
  if (lastRecent || plan.collapsedCount) {
    const recentKind = cleanText(lastRecent?.kind);
    if (lastRecent && recentKind === "observation_report") {
      return {
        detail: "",
        item: lastRecent,
        title: sentence(lastRecent.detail || lastRecent.implication || "关键事实已记录。"),
        tone: stateClass(lastRecent) === "error" ? "error" : "done",
      };
    }
    if (lastRecent && recentKind === "todo_plan") {
      return {
        detail: lastRecent.detail || (plan.collapsedCount ? `已完成 ${plan.collapsedCount} 步处理。` : "清单已同步。"),
        item: lastRecent,
        title: lastRecent.completion_ready ? "处理清单已完成。" : "处理清单已同步。",
        tone: lastRecent.completion_ready ? "done" : "running",
      };
    }
    const recentAction = lastRecent ? presentedActionSentence(lastRecent, "history") : "";
    return {
      detail: "",
      item: lastRecent,
      title: sentence(recentAction || (plan.collapsedCount ? `已完成 ${plan.collapsedCount} 步处理。` : "关键动作已完成。")),
      tone: "done",
    };
  }
  return {
    detail: "",
    item: null,
    title: "我正在同步当前处理进展。",
    tone: "running",
  };
}

function ActivitySummaryLine({ summary }: { summary: ReturnType<typeof activitySummary> }) {
  const detail = sentence(summary.detail);
  return (
    <div className={`public-run-activity__summary public-run-activity__summary--${summary.tone}`}>
      <span className="public-run-activity__narrative">
        <p>{sentence(summary.title)}</p>
        {detail && !samePublicText(detail, summary.title) ? <p>{detail}</p> : null}
      </span>
    </div>
  );
}

export function PublicRunActivity({ items, assistantContent = "" }: PublicRunActivityProps) {
  const plan = activityPlan(publicItems(items, assistantContent));
  if (!plan.current && !plan.recent.length && !plan.finalItems.length && !plan.collapsedCount) {
    return null;
  }
  const summary = activitySummary(plan);
  const closeoutSummary = plan.current ? finalActivitySummary(plan) : null;
  return (
    <div className={`public-run-activity public-run-activity--${summary.tone}`} aria-label="处理进展">
      <ActivitySummaryLine summary={summary} />
      {closeoutSummary ? <ActivitySummaryLine summary={closeoutSummary} /> : null}
      <ActivityRows plan={plan} />
    </div>
  );
}
