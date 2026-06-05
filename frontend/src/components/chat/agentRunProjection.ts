import type { PublicChatTimelineItem } from "@/lib/api";
import {
  normalizePublicTimelineItems,
  publicTimelineItemKey,
  publicTimelineSemanticKey,
} from "@/lib/store/publicTimeline";

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
  const terminalFinalOwnedByAssistant = finalAnswerOwnedByAssistant(normalized, assistantContent);
  const publicItems = normalizePublicTimelineItems(
    normalized.filter((item) => shouldProjectItem(item, assistantContent, terminalFinalOwnedByAssistant)),
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
  const terminalOutcomeOwnsProjection = Boolean(closeout || terminalFinalOwnedByAssistant);
  const feedbackItems = terminalOutcomeOwnsProjection
    ? actionItems.filter((item) => stateClass(item) !== "error")
    : actionItems;
  const latestFeedback = latestFeedbackItem(feedbackItems);
  const latestLive = terminalOutcomeOwnsProjection
    ? null
    : lastOf(feedbackItems.filter((item) =>
      isRunningActionItem(item)
      && !feedbackSupersedesRunningAction(latestFeedback, item)
    ));
  const latestError = terminalOutcomeOwnsProjection
    ? null
    : lastOf(actionItems.filter((item) =>
      stateClass(item) === "error"
      && !feedbackSupersedesRunningAction(latestFeedback, item)
    ));

  let liveAction = "";
  let feedback = "";
  let tone: AgentRunProjectionTone = "done";

  if (waitingItem) {
    feedback = statusText(waitingItem);
    tone = "waiting";
  } else if (latestError && (!latestLive || itemPosition(publicItems, latestError) >= itemPosition(publicItems, latestLive))) {
    feedback = feedbackText(latestError);
    tone = "soft_error";
  } else if (latestLive && (!latestFeedback || itemPosition(publicItems, latestLive) > itemPosition(publicItems, latestFeedback))) {
    liveAction = actionText(latestLive);
    if (latestFeedback && kindOf(latestFeedback) === "observation_report") {
      feedback = feedbackText(latestFeedback);
    }
    tone = "running";
  } else if (latestFeedback) {
    feedback = feedbackText(latestFeedback);
    tone = stateClass(latestFeedback) === "error" ? "soft_error" : "done";
  } else if (todo && !todoItem?.completion_ready) {
    tone = "running";
  }

  const commandOutput = terminalOutcomeOwnsProjection
    ? null
    : commandOutputProjectionForItem(latestFeedback || latestLive);

  if (samePublicText(liveAction, assistantContent)) {
    liveAction = "";
  }
  if (samePublicText(feedback, assistantContent)) {
    feedback = "";
  }
  if (samePublicText(feedback, liveAction)) {
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

function shouldProjectItem(
  item: PublicChatTimelineItem,
  assistantContent: string,
  terminalFinalOwnedByAssistant = false,
) {
  const kind = kindOf(item);
  const text = textOfItem(item);
  if (!text) return false;
  if (kind === "assistant_text" || kind === "opening_judgment") return false;
  if ((kind === "assistant_text" || kind === "final_summary") && samePublicText(text, assistantContent)) {
    return false;
  }
  if (terminalFinalOwnedByAssistant && isErroredActionItem(item) && rawFailureProjectionTextOfItem(item)) {
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
  const item = items.find((candidate) => kindOf(candidate) === "opening_judgment")
    ?? [...items].reverse().find((candidate) => kindOf(candidate) === "assistant_text");
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
    return sentence(withNextStepFact(
      firstProjectionText([item.detail, item.text, item.public_summary, item.title]),
      item.implication || item.next_step,
    ));
  }
  if (kindOf(item) === "blocked") {
    return sentence(withNextStepFact(
      firstProjectionText([item.text, item.detail, item.recovery_hint]),
      item.next_step,
    ));
  }
  if (hasSuppressedPrimaryResult(item)) {
    return "";
  }
  return sentence(withNextStepFact(
    resultProjectionText(item),
    item.next_step,
  ));
}

function actionText(item: PublicChatTimelineItem) {
  return sentence(firstProjectionText([item.public_summary, item.text, item.detail, item.title, item.subject_label]));
}

function closeoutText(items: PublicChatTimelineItem[], assistantContent: string) {
  const final = lastFinalItem(items);
  if (!final) return "";
  const state = stateClass(final);
  if (state === "error") {
    return sentence(firstProjectionText([final.recovery_hint, textOfItem(final)]));
  }
  const text = stripPublicFeedbackLabel(final.text || final.detail || final.title || final.path || final.href);
  if (!text || samePublicText(text, assistantContent) || looksLikeRawToolOutput(text)) {
    return "";
  }
  if (kindOf(final) === "artifact") {
    return sentence(firstProjectionText([final.title, final.detail, final.path, final.href]));
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

function stoppedText(item: PublicChatTimelineItem) {
  return sentence(firstProjectionText([item.detail, item.text, item.title]));
}

function statusText(item: PublicChatTimelineItem) {
  return sentence(firstProjectionText([item.detail, item.text, item.public_summary, item.title]));
}

function stripPublicFeedbackLabel(value: unknown) {
  return cleanText(value)
    .replace(/^(?:观察结果|观察报告|观察)[：:\s]*/u, "")
    .replace(/^工具返回失败[：:\s]*/u, "结果返回失败：")
    .trim();
}

function projectionText(value: unknown) {
  const text = stripMachineFragments(stripPublicFeedbackLabel(value));
  const rawFailureText = rawToolFailureProjectionText(text);
  if (rawFailureText) {
    return rawFailureText;
  }
  if (!text || looksLikeRawToolOutput(text) || looksLikeToolPlaceholder(text) || looksLikeRawCommandText(text)) {
    return "";
  }
  return text;
}

function firstProjectionText(values: unknown[]) {
  for (const value of values) {
    const text = projectionText(value);
    if (text) return text;
  }
  return "";
}

function resultProjectionText(item: PublicChatTimelineItem) {
  const result = firstProjectionText([item.observation, item.detail, item.text, item.recovery_hint]);
  if (!result || sameExactPublicText(result, item.public_summary) || sameExactPublicText(result, item.title)) {
    return "";
  }
  return result;
}

function hasSuppressedPrimaryResult(item: PublicChatTimelineItem) {
  return [item.observation, item.detail, item.text].some((value) => {
    const text = cleanText(value);
    return Boolean(text && !projectionText(text));
  });
}

function stripMachineFragments(value: string) {
  const text = cleanText(value);
  if (!text) return "";
  return text
    .replace(/\bstorage[\\/]+task_environments[\\/]+[^\\/]+[\\/]+(?:workspace|vibe-workspace)[\\/]+/gi, "")
    .replace(/\b(?:rtevt|taskrun|turnrun|toolobs|toolinv|rtpacket):[^\s，。；;]+/gi, "")
    .replace(/\b(?:agent_turn_terminal|runtime_invocation_packet_compiled|task_execution_packet_compiled|step_summary_recorded)\b/gi, "")
    .replace(/[（(]\s*[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\s*[）)]/gi, "")
    .replace(/[：:]\s*[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}[。.]?$/gi, "")
    .replace(/\s+[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}[。.]?$/gi, "")
    .replace(/[：:\s]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanBoundaryText(value: unknown) {
  return cleanRunText(value);
}

function cleanText(value: unknown) {
  return cleanRunText(value);
}

function cleanRunText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function short(value: unknown, limit = 220) {
  return shortRunText(value, limit);
}

function shortRunText(value: unknown, limit = 220) {
  const text = cleanRunText(value);
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}...` : text;
}

function sentence(value: unknown) {
  const text = short(projectionText(value), 240);
  if (!text) return "";
  return /[。！？.!?]$/.test(text) ? text : `${text}。`;
}

function kindOf(item: PublicChatTimelineItem | null | undefined) {
  return cleanText(item?.kind);
}

function stateClass(item: PublicChatTimelineItem) {
  const state = cleanText(item.state).toLowerCase();
  if (["stopped", "aborted", "user_aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return "error";
  if (["done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function textOfItem(item: PublicChatTimelineItem) {
  return cleanText(item.public_summary || item.observation || item.text || item.detail || item.title || item.subject_label || item.path || item.href);
}

function samePublicText(left: unknown, right: unknown) {
  const leftText = cleanText(left);
  const rightText = cleanText(right);
  if (!leftText || !rightText) return false;
  return leftText === rightText || leftText.includes(rightText) || rightText.includes(leftText);
}

function sameExactPublicText(left: unknown, right: unknown) {
  const leftText = projectionText(left);
  const rightText = projectionText(right);
  return Boolean(leftText && rightText && leftText === rightText);
}

export function looksLikeRawToolOutput(value: unknown) {
  const text = cleanText(value);
  if (!text) return false;
  return rawFileListingPaths(text).length > 0
    || rawCopiedPaths(text).length > 0
    || Boolean(rawToolFailureProjectionText(text))
    || looksLikePersistedToolResultFailure(text)
    || /\b(?:not allowlisted read-only|read-only validator|unsupported read-only)\b/i.test(text)
    || /\b\d+\s+bytes\s+(?:file|directory|dir)\b/i.test(text)
    || /\b(?:Exit code|Wall time|Output):/i.test(text)
    || looksLikeRawCommandText(text)
    || /\b(?:authority|diagnostics|matched_version_count|candidate_version_count|result_envelope|structured_payload)\b/i.test(text)
    || ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")));
}

function looksLikeToolPlaceholder(value: string) {
  const text = cleanText(value);
  if (!text) return true;
  return /^已发起工具调用，正在等待工具返回[：:]/.test(text)
    || /^已经过工具调用，正在等待工具返回[：:]/.test(text)
    || /^正在调用(?:\s|工具|$)/i.test(text)
    || /^工具已完成\s+/i.test(text)
    || /^工具失败\s+/i.test(text)
    || /^true$|^false$|^null$|^none$|^ok$|^success$|^done$|^completed$|^running$|^working$/i.test(text);
}

function looksLikeRawCommandText(value: string) {
  const lines = String(value || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) return false;

  const commandLines = lines.filter(looksLikeShellCommandLine).length;
  if (!commandLines) return false;

  const proseLines = lines.filter((line) => !looksLikeShellCommandLine(line) && looksLikeHumanProseLine(line)).length;
  if (proseLines && commandLines < Math.max(2, lines.length * 0.6)) {
    return false;
  }
  return commandLines === lines.length || lines.length <= 3 || commandLines >= Math.ceil(lines.length * 0.75);
}

function looksLikeShellCommandLine(line: string) {
  const normalized = line.replace(/^```(?:\w+)?\s*/i, "").replace(/```$/i, "").trim();
  if (!normalized) return false;
  const statusPrefixStripped = normalized
    .replace(/^(?:正在运行|正在调用|正在执行|已运行|已调用|运行|调用|执行)\s+/u, "")
    .trim();
  const promptPattern = /^(?:[$>]|PS\s+[^>]+>)\s*\S+/i;
  const commandStartPattern = /^(?:New-Item|Set-Content|Get-Content|Remove-Item|Move-Item|Copy-Item|npm|pnpm|yarn|pytest|python|powershell|cmd\s*\/c|git|rg|grep|mkdir|touch)\b/i;
  return promptPattern.test(normalized)
    || commandStartPattern.test(normalized)
    || commandStartPattern.test(statusPrefixStripped)
    || (/\s-(?:ItemType|Path|Recurse|Force|Filter|Pattern|Command)\b/i.test(normalized) && commandStartPattern.test(normalized));
}

function looksLikeHumanProseLine(line: string) {
  const normalized = line.trim();
  if (!normalized || /^```/.test(normalized)) return false;
  if (/^#{1,6}\s+\S/.test(normalized)) return true;
  if (/^\|.*\|$/.test(normalized)) return true;
  if (/[\u4e00-\u9fa5]{4,}/.test(normalized)) return true;
  return /[.!?。！？]\s*$/.test(normalized) && /\s/.test(normalized);
}

function looksLikePersistedToolResultFailure(value: unknown) {
  const text = cleanText(value);
  if (!text) return false;
  return /Read persisted tool result failed|persisted tool result read failed/i.test(text)
    || /(?:runtime_context|runtime[-_ ]context)[\\/]+tool-results/i.test(text)
    || /tool-results[\\/]+session[-_A-Za-z0-9]+/i.test(text);
}

function rawToolFailureProjectionText(value: unknown) {
  const text = cleanText(value);
  if (!text) return "";
  if (/^Edit failed:\s*old_text not found\b/i.test(text) || /\bold_text not found\b/i.test(text)) {
    return "文件更新未完成：当前内容与预期不一致，需要先读取最新片段再修改。";
  }
  if (/^Edit failed:\s*file does not exist\b/i.test(text)) {
    return "文件更新未完成：目标文件不存在，需要先确认路径。";
  }
  if (/^Edit failed:\s*path is a directory\b/i.test(text)) {
    return "文件更新未完成：目标是目录，需要重新确认文件路径。";
  }
  if (/^Edit failed:/i.test(text)) {
    return "文件更新未完成，需要根据返回结果调整后继续。";
  }
  if (/^Read failed:/i.test(text)) {
    return "读取未完成，需要重新确认读取范围后继续。";
  }
  if (/^Write failed:/i.test(text)) {
    return "写入未完成，需要确认目标路径和写入条件后继续。";
  }
  return "";
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
  const observationText = cleanText([
    observation.detail,
    observation.text,
    observation.implication,
    observation.public_summary,
    observation.title,
  ].filter(Boolean).join(" "));
  const actionKind = cleanText(running.action_kind).toLowerCase();
  if (actionKind === "verify") {
    return /验证|测试|\b(?:test|tests|passed|failed|pass|fail)\b/i.test(observationText);
  }
  if (actionKind === "read" || actionKind === "inspect") {
    const subject = cleanText(running.subject_label);
    return Boolean(subject && observationText.includes(subject));
  }
  return false;
}

function sameActionFingerprint(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftSemantic = publicTimelineSemanticKey(left);
  const rightSemantic = publicTimelineSemanticKey(right);
  if (leftSemantic && rightSemantic && leftSemantic === rightSemantic) {
    return true;
  }
  const leftKind = cleanText(left.action_kind);
  const rightKind = cleanText(right.action_kind);
  const leftSubject = normalizedComparableText(left.subject_label);
  const rightSubject = normalizedComparableText(right.subject_label);
  if (leftKind && rightKind && leftKind === rightKind && leftSubject && rightSubject) {
    return leftSubject === rightSubject;
  }
  return hasMeaningfulTextOverlap(itemFingerprintText(left), itemFingerprintText(right));
}

function sharesTraceRef(left: PublicChatTimelineItem, right: PublicChatTimelineItem) {
  const leftRefs = new Set((left.trace_refs ?? []).map((ref) => cleanText(ref)).filter(Boolean));
  if (!leftRefs.size) {
    return false;
  }
  return (right.trace_refs ?? []).some((ref) => leftRefs.has(cleanText(ref)));
}

function withNextStepFact(value: unknown, nextStep: unknown) {
  const base = sentence(value);
  const next = sentence(stripPublicFeedbackLabel(nextStep));
  if (!base || !next || samePublicText(base, next)) {
    return base;
  }
  return `${base} ${next}`;
}

function itemFingerprintText(item: PublicChatTimelineItem) {
  return cleanText([
    item.public_summary,
    item.title,
    item.subject_label,
    item.detail,
    item.text,
    item.action_kind,
  ].filter(Boolean).join(" "));
}

function normalizedComparableText(value: unknown) {
  return cleanText(value).replace(/\\/g, "/").toLowerCase();
}

function hasMeaningfulTextOverlap(left: unknown, right: unknown) {
  const leftTokens = textFeatures(left);
  if (!leftTokens.size) return false;
  const rightTokens = textFeatures(right);
  for (const token of leftTokens) {
    if (rightTokens.has(token)) return true;
  }
  return false;
}

function textFeatures(value: unknown) {
  const text = cleanText(value).toLowerCase();
  const tokens = new Set<string>();
  for (const match of text.matchAll(/[a-z0-9][a-z0-9_-]{2,}/gi)) {
    const token = match[0].replace(/[_-]+/g, " ");
    if (!COMMON_TEXT_FEATURES.has(token)) tokens.add(token);
  }
  for (const match of text.matchAll(/[\u4e00-\u9fa5]{2,}/g)) {
    const segment = match[0];
    for (let index = 0; index < segment.length - 1; index += 1) {
      const token = segment.slice(index, index + 2);
      if (!COMMON_TEXT_FEATURES.has(token)) tokens.add(token);
    }
  }
  return tokens;
}

const COMMON_TEXT_FEATURES = new Set([
  "正在",
  "已经",
  "当前",
  "处理",
  "任务",
  "结果",
  "返回",
  "下一",
  "一步",
  "可以",
  "继续",
  "根据",
  "确认",
  "目标",
  "上下",
  "下文",
  "文件",
  "状态",
]);

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

function isErroredActionItem(item: PublicChatTimelineItem) {
  return isActionOrFeedbackItem(item) && stateClass(item) === "error";
}

function isStaleRawToolFailure(item: PublicChatTimelineItem, text: string) {
  if (kindOf(item) !== "tool_activity") return false;
  if (stateClass(item) !== "error") return false;
  return Boolean(rawToolFailureProjectionText(text) || rawFailureProjectionTextOfItem(item))
    || /(?:Tool execution failed|Fetch failed|HTTP\s+4\d\d|HTTP\s+5\d\d|tool_execution_failed)/i.test(text);
}

function finalAnswerOwnedByAssistant(items: PublicChatTimelineItem[], assistantContent: string) {
  const final = lastFinalItem(items);
  if (!final) return false;
  const text = cleanText(final.text || final.detail || final.title || final.path || final.href);
  return Boolean(text && !looksLikeRawToolOutput(text) && samePublicText(text, assistantContent));
}

function rawFailureProjectionTextOfItem(item: PublicChatTimelineItem) {
  return rawToolFailureProjectionText([
    item.observation,
    item.detail,
    item.text,
    item.recovery_hint,
    item.title,
  ].filter(Boolean).join(" "));
}

function itemPosition(items: PublicChatTimelineItem[], item: PublicChatTimelineItem | null) {
  if (!item) return -1;
  const key = publicTimelineItemKey(item);
  return items.findIndex((candidate) => publicTimelineItemKey(candidate) === key);
}

function lastOf<T>(items: T[]) {
  return items.length ? items[items.length - 1] : null;
}
