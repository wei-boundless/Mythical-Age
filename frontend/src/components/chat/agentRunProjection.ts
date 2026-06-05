import type { PublicChatTimelineItem } from "@/lib/api";
import { normalizePublicTimelineItems, publicTimelineItemKey } from "@/lib/store/publicTimeline";
import {
  actionSentence as presentedActionSentence,
  actionViewForTimelineItem,
  cleanRunText,
  compactPathLabel,
  sameRunText,
  shortRunText,
  stateClassForTimelineItem,
  timelineItemText,
} from "@/components/chat/agentRunPresentation";

export type AgentRunProjectionTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

export type AgentRunCommandOutput = {
  content: string;
  key: string;
  label: string;
};

export type TodoProjectionItem = {
  content: string;
  id: string;
  status: string;
};

export type TodoProjection = {
  activeText: string;
  detail: string;
  hidden: number;
  items: TodoProjectionItem[];
  title: string;
};

export type AgentRunProjection = {
  opening: string;
  liveAction: string;
  feedback: string;
  commandOutput: AgentRunCommandOutput | null;
  todo: TodoProjection | null;
  closeout: string;
  stopped: string;
  tone: AgentRunProjectionTone;
};

const SUPPRESSED_STATUS_TEXT = new Set([
  "已同步最新进展。",
  "已接上当前工作，正在同步最新进展。",
  "已接上当前工作，正在整理上下文。",
  "已开始继续处理；接下来会持续汇报正在推进的步骤。",
  "任务执行器已接管，正在推进第一步。",
]);

function emptyProjection(opening = ""): AgentRunProjection {
  return {
    closeout: "",
    commandOutput: null,
    feedback: "",
    liveAction: "",
    opening,
    stopped: "",
    todo: null,
    tone: "done",
  };
}

export function assistantContentFromPublicTimeline(content: string, items: PublicChatTimelineItem[]) {
  const normalized = cleanRunText(content);
  if (normalized && !looksLikeRawToolOutput(normalized)) {
    return content;
  }
  const normalizedItems = normalizePublicTimelineItems(items);
  return directAssistantText(normalizedItems, "") || finalSummaryText(normalizedItems) || "";
}

export function hasAgentRunProjection(projection: AgentRunProjection) {
  return Boolean(
    projection.stopped
    || projection.liveAction
    || projection.feedback
    || projection.commandOutput
    || projection.todo
    || projection.closeout,
  );
}

export function hasProjectedPublicRunActivity(items: PublicChatTimelineItem[], assistantContent = "") {
  return hasAgentRunProjection(projectAgentRun(items, assistantContent));
}

export function projectAgentRun(items: PublicChatTimelineItem[], assistantContent = ""): AgentRunProjection {
  const normalized = normalizePublicTimelineItems(items);
  const opening = directAssistantText(normalized, assistantContent);
  const publicItems = normalizePublicTimelineItems(
    normalized.filter((item) => shouldProjectItem(item, assistantContent)),
  );
  if (!publicItems.length) {
    return emptyProjection(opening);
  }

  const closeout = closeoutText(publicItems, assistantContent);
  const stoppedItem = lastOf(publicItems.filter(isStoppedItem));
  if (stoppedItem) {
    const stopped = stoppedText(stoppedItem);
    const visibleStopped = samePublicText(stopped, assistantContent) ? "" : stopped;
    return {
      closeout,
      commandOutput: null,
      feedback: "",
      liveAction: "",
      opening,
      stopped: visibleStopped,
      todo: null,
      tone: "stopped",
    };
  }

  const waitingItem = lastOf(publicItems.filter(isWaitingItem));
  const todoItem = lastOf(publicItems.filter((item) => kindOf(item) === "todo_plan"));
  const todo = todoItem ? todoProjectionForItem(todoItem) : null;
  const actionItems = publicItems.filter(isActionOrFeedbackItem);
  const latestFeedback = latestFeedbackItem(actionItems);
  const latestLive = closeout
    ? null
    : lastOf(actionItems.filter((item) =>
      isRunningActionItem(item)
      && !feedbackSupersedesRunningAction(latestFeedback, item)
    ));
  const latestError = lastOf(actionItems.filter((item) =>
    stateClass(item) === "error"
    && !feedbackSupersedesRunningAction(latestFeedback, item)
  ));

  let liveAction = "";
  let feedback = "";
  let tone: AgentRunProjectionTone = "done";

  if (waitingItem) {
    feedback = waitingText(waitingItem);
    tone = "waiting";
  } else if (latestError && (!latestLive || itemPosition(publicItems, latestError) >= itemPosition(publicItems, latestLive))) {
    feedback = errorFeedbackText(latestError);
    tone = "soft_error";
  } else if (latestLive && (!latestFeedback || itemPosition(publicItems, latestLive) > itemPosition(publicItems, latestFeedback))) {
    liveAction = naturalActionSentence(latestLive);
    tone = "running";
  } else if (latestFeedback) {
    feedback = feedbackText(latestFeedback);
    tone = stateClass(latestFeedback) === "error" ? "soft_error" : "done";
  } else if (todo && !todoItem?.completion_ready) {
    tone = "running";
  }

  const commandOutput = commandOutputProjectionForItem(latestFeedback || latestLive);

  if (samePublicText(liveAction, assistantContent)) {
    liveAction = "";
  }
  if (samePublicText(feedback, assistantContent)) {
    feedback = "";
  }

  return {
    closeout,
    commandOutput,
    feedback,
    liveAction,
    opening,
    stopped: "",
    todo,
    tone,
  };
}

function shouldProjectItem(item: PublicChatTimelineItem, assistantContent: string) {
  const kind = kindOf(item);
  const text = textOfItem(item);
  if (!text) return false;
  if (kind === "assistant_text" || kind === "opening_judgment") return false;
  if ((kind === "assistant_text" || kind === "final_summary") && samePublicText(text, assistantContent)) {
    return false;
  }
  if (assistantContent.trim() && isStaleRawToolFailure(item, text)) {
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

function directAssistantText(items: PublicChatTimelineItem[], assistantContent: string) {
  const item = [...items].reverse().find((candidate) => {
    const kind = kindOf(candidate);
    return kind === "opening_judgment" || kind === "assistant_text";
  });
  const text = cleanBoundaryText(item?.text || item?.detail || item?.title);
  if (!text || isRoutineAssistantTimelineText(text) || looksLikeRawToolOutput(text)) {
    return "";
  }
  return samePublicText(text, assistantContent) ? "" : text;
}

function isRoutineAssistantTimelineText(text: string) {
  return [
    "回答已生成并写回会话",
    "会话输出完成",
    "工具调用已完成，正在根据结果继续。",
  ].includes(text);
}

function isActionOrFeedbackItem(item: PublicChatTimelineItem) {
  const kind = kindOf(item);
  return kind === "blocked"
    || kind === "observation_report"
    || kind === "tool_activity"
    || kind === "verification"
    || kind === "work_action";
}

function isRunningActionItem(item: PublicChatTimelineItem) {
  const kind = kindOf(item);
  if (kind === "observation_report" || kind === "blocked") {
    return false;
  }
  return stateClass(item) === "running";
}

function latestFeedbackItem(items: PublicChatTimelineItem[]) {
  return [...items].reverse().find((item) => {
    if (kindOf(item) === "observation_report") return true;
    const state = stateClass(item);
    return state === "done" || state === "error";
  }) ?? null;
}

function feedbackText(item: PublicChatTimelineItem) {
  if (kindOf(item) === "observation_report") {
    const detail = readableToolObservation(item.detail || item.text || item.title || "当前事实已记录。");
    return sentence(withNextStepFact(detail, item.implication || item.next_step));
  }
  if (stateClass(item) === "error") {
    return errorFeedbackText(item);
  }
  return withNextStepFact(naturalResultFact(actionDisplay(item), item), item.next_step);
}

function errorFeedbackText(item: PublicChatTimelineItem) {
  const action = actionDisplay(item);
  if (kindOf(item) === "blocked") {
    return sentence(blockedFact(textOfItem(item), item.recovery_hint));
  }
  const raw = genericObservation(action.observation)
    ? presentedActionSentence(item, "current") || item.recovery_hint || "当前步骤没有执行成功，我会换一种方式继续。"
    : action.observation || presentedActionSentence(item, "current") || item.recovery_hint || "当前步骤没有执行成功，我会换一种方式继续。";
  return sentence(blockedFact(raw));
}

function naturalActionSentence(item: PublicChatTimelineItem) {
  const kind = kindOf(item);
  if (kind !== "tool_activity" && kind !== "work_action") {
    return sentence(item.text || item.detail || item.title || "我正在同步当前处理进展。");
  }
  const action = actionDisplay(item);
  const target = visibleActionTarget(action.detail);
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
    return "正在生成图像，拿到结果后会确认是否可用。";
  }
  return target
    ? `我先${objectText("处理", target)}，拿到结果后再给你明确判断。`
    : "我已经接上当前任务，先确认关键事实，再给你明确判断。";
}

function naturalResultFact(action: ReturnType<typeof actionDisplay>, item: PublicChatTimelineItem) {
  const itemRawObservation = item.observation || item.detail || item.text || "";
  if (looksLikeRawToolOutput(itemRawObservation)) {
    if (rawCopiedPaths(itemRawObservation).length) {
      return sentence(readableToolObservation(itemRawObservation, action.detail));
    }
    if (action.kind === "memory") {
      return "相关记忆已返回，下一步会纳入判断。";
    }
    if (action.kind === "verify" || action.kind === "run") {
      return "验证已返回，需要根据结果判断是否继续修正。";
    }
    return sentence(readableToolObservation(itemRawObservation, action.detail));
  }
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
  if (/下的相关文件/.test(raw)) {
    return sentence(raw);
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

function readableToolObservation(value: string, target = "", fallback = "") {
  const observation = stripPublicFeedbackLabel(value);
  const rawObservation = friendlyRawToolObservation(observation, target);
  if (rawObservation) {
    return rawObservation;
  }
  if (observation && !genericObservation(observation)) {
    return observation;
  }
  const fallbackText = stripPublicFeedbackLabel(fallback);
  const rawFallback = friendlyRawToolObservation(fallbackText, target);
  if (rawFallback) {
    return rawFallback;
  }
  if (fallbackText && !/动作已返回|结果已返回|执行动作|处理步骤/.test(fallbackText)) {
    return fallbackText;
  }
  const targetText = cleanText(target);
  return targetText
    ? `${targetText} 已返回，我会据此推进下一步。`
    : "结果已返回，我会据此推进下一步。";
}

function genericObservation(value: string) {
  return /(?:动作|结果)已返回，继续根据结果推进下一步|当前(?:动作|步骤).*(?:路径|权限|输入).*继续/.test(value);
}

function closeoutText(items: PublicChatTimelineItem[], assistantContent: string) {
  const final = lastFinalItem(items);
  if (!final) return "";
  const state = stateClass(final);
  if (state === "error") {
    return sentence(blockedFact(final.recovery_hint || textOfItem(final)));
  }
  const text = stripPublicFeedbackLabel(final.text || final.detail || final.title || final.path || final.href);
  if (!text || samePublicText(text, assistantContent) || looksLikeRawToolOutput(text)) {
    return "";
  }
  if (kindOf(final) === "artifact") {
    return sentence(final.title || "产物已生成");
  }
  return sentence(text);
}

function finalSummaryText(items: PublicChatTimelineItem[]) {
  const final = lastOf(items.filter((item) => kindOf(item) === "final_summary"));
  if (!final) return "";
  if (looksLikeRawToolOutput(final.text || final.detail || final.title)) return "";
  return sentence(final.text || final.detail || final.title);
}

function lastFinalItem(items: PublicChatTimelineItem[]) {
  return lastOf(items.filter((item) => kindOf(item) === "final_summary" || kindOf(item) === "artifact"));
}

function todoProjectionForItem(item: PublicChatTimelineItem): TodoProjection {
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
  return {
    activeText: active ? `当前：${short(active.active_form || active.content, 140)}` : "",
    detail: item.detail || `${completed}/${todos.length} 已完成`,
    hidden,
    items: visibleTodos.map((todo) => ({
      content: short(cleanText(todo.status) === "in_progress" ? todo.active_form || todo.content : todo.content, 120),
      id: cleanText(todo.todo_id) || cleanText(todo.content),
      status: cleanText(todo.status) || "pending",
    })),
    title: item.completion_ready ? "处理清单已完成" : "处理清单",
  };
}

function waitingText(item: PublicChatTimelineItem) {
  return sentence(item.detail || item.text || "当前任务已停在可继续状态，接上后会沿用现有进度。");
}

function stoppedText(item: PublicChatTimelineItem) {
  return sentence(item.detail || item.text || item.title || "本轮已停止，当前运行不会继续推进。");
}

function blockedFact(value: unknown, fallback = "") {
  const text = stripPublicFeedbackLabel(value) || stripPublicFeedbackLabel(fallback);
  if (looksLikePersistedToolResultFailure(text)) {
    return "上一段执行结果没有成功读回，我会重新获取可用结果后继续判断。";
  }
  if (/not allowlisted read-only|read-only validator|unsupported read-only/i.test(text)) {
    return "命令被只读权限拦截，我会改用允许的读取方式继续。";
  }
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

function stripPublicFeedbackLabel(value: unknown) {
  return cleanText(value)
    .replace(/^(?:观察结果|观察报告|观察)[：:\s]*/u, "")
    .replace(/^工具返回失败[：:\s]*/u, "结果返回失败：")
    .trim();
}

function cleanBoundaryText(value: unknown) {
  return cleanRunText(value);
}

function cleanText(value: unknown) {
  return cleanRunText(value);
}

function short(value: unknown, limit = 220) {
  return shortRunText(value, limit);
}

function sentence(value: unknown) {
  const text = short(stripPublicFeedbackLabel(value), 240);
  if (!text) return "";
  if (looksLikeRawToolOutput(text)) {
    return friendlyRawToolObservation(text) || "";
  }
  return /[。！？.!?]$/.test(text) ? text : `${text}。`;
}

function objectText(verb: string, target: string) {
  return /[A-Za-z0-9_.\\/:-]/.test(target) ? `${verb} ${target}` : `${verb}${target}`;
}

function actionDisplay(item: PublicChatTimelineItem) {
  return actionViewForTimelineItem(item);
}

function kindOf(item: PublicChatTimelineItem | null | undefined) {
  return cleanText(item?.kind);
}

function stateClass(item: PublicChatTimelineItem) {
  return stateClassForTimelineItem(item);
}

function textOfItem(item: PublicChatTimelineItem) {
  return timelineItemText(item);
}

function samePublicText(left: unknown, right: unknown) {
  return sameRunText(left, right);
}

function friendlyRawToolObservation(value: unknown, target = "") {
  const text = cleanText(value);
  if (!text || !looksLikeRawToolOutput(text)) {
    return "";
  }
  const copied = rawCopiedPaths(text);
  if (copied.length) {
    return copied.length > 1
      ? `已复制 ${copied.length} 个素材文件，下一步会确认目标页面是否能正确引用。`
      : "已复制素材文件，下一步会确认目标页面是否能正确引用。";
  }
  if (looksLikePersistedToolResultFailure(text)) {
    return "上一段执行结果没有成功读回，我会重新获取可用结果后继续判断。";
  }
  const subject = cleanText(target) || rawFileListingSubject(text);
  if (rawFileListingPaths(text).length) {
    return subject
      ? `已确认 ${subject} 下的相关文件，下一步会收敛到需要查看的具体文件。`
      : "已确认相关文件列表，下一步会收敛到需要查看的具体文件。";
  }
  return subject
    ? `${subject} 的返回结果已确认，下一步会基于可用信息继续判断。`
    : "结果已返回，下一步会基于可用信息继续判断。";
}

export function looksLikeRawToolOutput(value: unknown) {
  const text = cleanText(value);
  if (!text) return false;
  return rawFileListingPaths(text).length > 0
    || rawCopiedPaths(text).length > 0
    || looksLikePersistedToolResultFailure(text)
    || /\b(?:not allowlisted read-only|read-only validator|unsupported read-only)\b/i.test(text)
    || /\b\d+\s+bytes\s+(?:file|directory|dir)\b/i.test(text)
    || /\b(?:Exit code|Wall time|Output):/i.test(text)
    || /\b(?:authority|diagnostics|matched_version_count|candidate_version_count|result_envelope|structured_payload)\b/i.test(text)
    || ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")));
}

function looksLikePersistedToolResultFailure(value: unknown) {
  const text = cleanText(value);
  if (!text) return false;
  return /Read persisted tool result failed|persisted tool result read failed/i.test(text)
    || /(?:runtime_context|runtime[-_ ]context)[\\/]+tool-results/i.test(text)
    || /tool-results[\\/]+session[-_A-Za-z0-9]+/i.test(text);
}

function rawFileListingPaths(value: unknown) {
  const text = cleanText(value);
  if (!text) return [];
  return [...text.matchAll(/\bfile\s+([^\s]+)\s+\d+\s+bytes\b/gi)]
    .map((match) => cleanText(match[1]))
    .filter(Boolean);
}

function rawCopiedPaths(value: unknown) {
  const text = cleanText(value);
  if (!text) return [];
  return [...text.matchAll(/\bCopied:\s+(.+?)(?=\s+Copied:|$)/gi)]
    .map((match) => cleanText(match[1]))
    .filter(Boolean);
}

function commandOutputProjectionForItem(item: PublicChatTimelineItem | null): AgentRunCommandOutput | null {
  if (!item) return null;
  const raw = commandOutputText(
    item.observation
    || item.detail
    || item.text
    || item.public_summary
    || item.title,
  );
  if (!raw) return null;
  return {
    content: shortCommandOutput(raw),
    key: `${publicTimelineItemKey(item)}:command-output`,
    label: "终端",
  };
}

function commandOutputText(value: unknown) {
  const raw = String(value ?? "").replace(/\r\n/g, "\n").trim();
  if (!raw || !looksLikeCommandOutput(raw)) {
    return "";
  }
  return raw;
}

function looksLikeCommandOutput(value: unknown) {
  const text = cleanText(value);
  if (!text) return false;
  return rawCopiedPaths(text).length > 0
    || /\b(?:Exit code|Wall time|Output):/i.test(text)
    || /(?:^|\n)\s*(?:[$>]|PS [^>]+>)\s+\S/.test(String(value ?? ""));
}

function shortCommandOutput(value: unknown, limit = 2400) {
  const text = String(value ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+(?=Copied:\s+)/g, "\n")
    .trim();
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}...` : text;
}

function rawFileListingSubject(value: unknown) {
  const paths = rawFileListingPaths(value);
  if (!paths.length) return "";
  return compactPathLabel(commonParentDirectory(paths) || paths[0], 80);
}

function commonParentDirectory(paths: string[]) {
  const splitPaths = paths
    .map((path) => path.replace(/\\/g, "/").split("/").filter(Boolean))
    .filter((parts) => parts.length > 1)
    .map((parts) => parts.slice(0, -1));
  if (!splitPaths.length) return "";
  const common: string[] = [];
  for (let index = 0; index < splitPaths[0].length; index += 1) {
    const part = splitPaths[0][index];
    if (!part || splitPaths.some((candidate) => candidate[index] !== part)) {
      break;
    }
    common.push(part);
  }
  return common.join("/");
}

function feedbackSupersedesRunningAction(
  feedback: PublicChatTimelineItem | null,
  running: PublicChatTimelineItem,
) {
  if (!feedback || !isRunningActionItem(running)) {
    return false;
  }
  if (sharesTraceRef(feedback, running)) {
    return true;
  }
  if (kindOf(feedback) === "observation_report") {
    return observationMatchesAction(feedback, running);
  }
  if (!isRunningActionItem(feedback) && isActionOrFeedbackItem(feedback)) {
    return sameActionFingerprint(feedback, running);
  }
  return false;
}

function observationMatchesAction(
  observation: PublicChatTimelineItem,
  running: PublicChatTimelineItem,
) {
  const action = actionDisplay(running);
  const text = cleanText([
    observation.detail,
    observation.text,
    observation.implication,
    observation.title,
  ].filter(Boolean).join(" "));
  if (!text) {
    return false;
  }
  if (action.kind === "verify" || action.kind === "run") {
    return /(?:验证|测试|命令|运行).*(?:返回|完成|通过|失败|未完成)/.test(text);
  }
  if (action.kind === "read") {
    return /(?:已读到|读取|上下文|关键上下文)/.test(text);
  }
  if (action.kind === "search") {
    return /(?:已定位|搜索|引用|线索|命中)/.test(text);
  }
  if (action.kind === "inspect") {
    return /(?:已确认|目标状态|路径|存在|不存在)/.test(text);
  }
  if (action.kind === "edit" || action.kind === "write") {
    return /(?:更新|写入|编辑|文件).*(?:返回|完成|已)/.test(text);
  }
  if (action.kind === "memory") {
    return /(?:记忆|memory).*(?:返回|命中|检索)/i.test(text);
  }
  if (action.kind === "image") {
    return /(?:图像|图片|生成).*(?:返回|完成|失败)/.test(text);
  }
  if (action.kind === "prepare") {
    return /(?:准备|输出).*(?:返回|完成|确认)/.test(text);
  }
  return false;
}

function sameActionFingerprint(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftAction = actionDisplay(left);
  const rightAction = actionDisplay(right);
  if (leftAction.kind !== rightAction.kind) {
    return false;
  }
  const leftTarget = comparableActionTarget(leftAction.detail);
  const rightTarget = comparableActionTarget(rightAction.detail);
  if (leftTarget && rightTarget) {
    return leftTarget === rightTarget;
  }
  return ["verify", "run", "memory", "image", "prepare"].includes(leftAction.kind);
}

function sharesTraceRef(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftRefs = new Set((left.trace_refs ?? []).map((ref) => cleanText(ref)).filter(Boolean));
  if (!leftRefs.size) {
    return false;
  }
  return (right.trace_refs ?? []).some((ref) => leftRefs.has(cleanText(ref)));
}

function visibleActionTarget(value: unknown) {
  const target = cleanText(value);
  return isGenericActionTargetText(target) ? "" : target;
}

function comparableActionTarget(value: unknown) {
  return visibleActionTarget(value).replace(/\\/g, "/").toLowerCase();
}

function isGenericActionTargetText(value: string) {
  return /^(?:文件|目录|路径|路径信息|路径状态|目标路径|artifact 路径|目标|当前目标|关键文件|相关代码|代码引用|测试|命令|验证|验证结果|检查|工具|动作|操作|结果|上下文|输出准备)$/i.test(value.trim());
}

function withNextStepFact(value: unknown, nextStep: unknown) {
  const base = sentence(value);
  const next = sentence(stripPublicFeedbackLabel(nextStep));
  if (!base || !next || samePublicText(base, next)) {
    return base;
  }
  return `${base} ${next}`;
}

function isStatusUpdate(item: PublicChatTimelineItem) {
  const kind = kindOf(item);
  return kind === "status_update" || kind === "stage" || kind === "task_order";
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

function isStaleRawToolFailure(item: PublicChatTimelineItem, text: string) {
  if (kindOf(item) !== "tool_activity") return false;
  if (stateClass(item) !== "error") return false;
  return /(?:Tool execution failed|Fetch failed|HTTP\s+4\d\d|HTTP\s+5\d\d|tool_execution_failed)/i.test(text);
}

function itemPosition(items: PublicChatTimelineItem[], item: PublicChatTimelineItem | null) {
  if (!item) return -1;
  const key = publicTimelineItemKey(item);
  return items.findIndex((candidate) => publicTimelineItemKey(candidate) === key);
}

function lastOf<T>(items: T[]) {
  return items.length ? items[items.length - 1] : null;
}
