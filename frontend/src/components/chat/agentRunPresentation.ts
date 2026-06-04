import type { PublicChatTimelineItem } from "@/lib/api";

export type AgentRunActionKind =
  | "artifact"
  | "browse"
  | "generic"
  | "image"
  | "inspect"
  | "read"
  | "run"
  | "search"
  | "verify"
  | "write";

export type AgentRunActionView = {
  detail: string;
  kind: AgentRunActionKind;
  observation: string;
  title: string;
};

export type AgentOpeningSignal = {
  label: string;
  text: string;
  tone: "thinking" | "done" | "error";
};

const GENERIC_TOOL_WAIT_PREFIXES = [
  "已发起工具调用，正在等待工具返回",
  "已经过工具调用，正在等待工具返回",
];

const INTERNAL_REFERENCE_PATTERN =
  /(?:^|\s)(?:rtevt:|taskrun:|turnrun:|toolobs:|toolinv:|rtpacket:|harness\.|runtime\.|backend\.|agent_system\.|task_system\.)/i;

export function cleanRunText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function shortRunText(value: unknown, limit = 220) {
  const text = cleanRunText(value);
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}...` : text;
}

export function stateClassForTimelineItem(item: PublicChatTimelineItem) {
  const state = cleanRunText(item.state).toLowerCase();
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return "error";
  if (["done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

export function timelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  return cleanRunText(item.text || item.detail || item.title || item.path || item.href);
}

export function sameRunText(left: unknown, right: unknown) {
  const leftText = cleanRunText(left);
  const rightText = cleanRunText(right);
  if (!leftText || !rightText) return false;
  return leftText === rightText || leftText.includes(rightText) || rightText.includes(leftText);
}

export function agentOpeningSignalFromTimeline(
  items: PublicChatTimelineItem[],
  options: { baseContent?: string; displayContent?: string } = {},
): AgentOpeningSignal | null {
  const assistantItem = [...items].reverse().find((item) => {
    const kind = cleanRunText(item.kind);
    return kind === "opening_judgment" || kind === "assistant_text";
  });
  const sourceKind = cleanRunText(assistantItem?.kind);
  const candidateText = cleanRunText(assistantItem?.text || assistantItem?.detail || assistantItem?.title);
  const baseText = cleanRunText(options.baseContent);
  const displayText = cleanRunText(options.displayContent);
  if (!baseText && candidateText && sameRunText(candidateText, displayText)) {
    return null;
  }
  const directText = candidateText && !sameRunText(candidateText, baseText) ? candidateText : "";
  const fallbackItem = !directText && !baseText ? openingFallbackItem(items) : null;
  const fallbackText = fallbackItem ? openingTextForItem(fallbackItem) : "";
  const text = directText || fallbackText;
  if (!text) {
    return null;
  }
  const state = cleanRunText((directText ? assistantItem : fallbackItem)?.state).toLowerCase();
  const tone = ["error", "failed", "blocked", "missing"].includes(state)
    ? "error"
    : ["done", "ready", "passed", "success"].includes(state)
      ? "done"
      : "thinking";
  return {
    label: directText
      ? sourceKind === "opening_judgment"
        ? "开局反馈"
        : tone === "error" ? "需要调整" : tone === "done" ? "判断完成" : "当前判断"
      : tone === "error" ? "需要调整" : tone === "done" ? "判断完成" : "开局反馈",
    text,
    tone,
  };
}

function openingFallbackItem(items: PublicChatTimelineItem[]) {
  const actionableItems = items.filter((item) => {
    const kind = cleanRunText(item.kind);
    return kind && kind !== "assistant_text" && kind !== "opening_judgment" && kind !== "final_summary";
  });
  return [...actionableItems].reverse().find((item) => {
    const state = cleanRunText(item.state).toLowerCase();
    return item.stream_state === "streaming" || ["running", "working", "partial", "error", "failed", "blocked", "missing"].includes(state);
  }) ?? actionableItems.at(-1) ?? null;
}

function openingTextForItem(item: PublicChatTimelineItem) {
  const kind = cleanRunText(item.kind);
  if (kind === "blocked") {
    const text = shortRunText(item.recovery_hint || item.text || item.title || "当前步骤没有继续条件", 120);
    return `我先调整当前条件：${text}。`;
  }
  if (kind === "artifact") {
    return "我已经拿到阶段产物，先把结果整理成可读结论。";
  }
  if (kind === "verification") {
    return "我先做结果校验，确认它不是只停留在表面完成。";
  }
  if (kind !== "tool_activity") {
    const text = shortRunText(item.title || item.text || item.detail, 120);
    return text ? `我先确认当前进展：${text}。` : "";
  }
  const action = actionViewForTimelineItem(item);
  const target = action.detail;
  if (action.kind === "read" && /agents\.md/i.test(target)) {
    return "我先确认项目约定和协作边界，再决定改动范围。";
  }
  if (action.kind === "read") {
    return target
      ? `我先读取 ${target}，把判断建立在真实上下文上。`
      : "我先补齐上下文，避免凭空判断。";
  }
  if (action.kind === "search") {
    return target
      ? `我先搜索 ${target}，定位真正影响输出的调用链。`
      : "我先定位调用链，找到真正影响主页面输出的位置。";
  }
  if (action.kind === "inspect") {
    return target
      ? `我先确认 ${target} 的状态，避免后续动作偏离目标。`
      : "我先确认目标状态，再决定下一步动作。";
  }
  if (action.kind === "write") {
    return target
      ? `我正在更新 ${target}，把判断落到实际界面。`
      : "我已经定位到改动点，正在把表达层改到界面上。";
  }
  if (action.kind === "run") {
    return target
      ? `我正在运行 ${target}，用结果判断是否还要继续修正。`
      : "我先验证当前状态，再决定是否继续修正。";
  }
  return target
    ? `我先处理 ${target}，再把结果整理成可读结论。`
    : "我先推进当前步骤，并在拿到结果后说明判断。";
}

export function actionViewForTimelineItem(item: PublicChatTimelineItem): AgentRunActionView {
  const state = stateClassForTimelineItem(item);
  const rawTitle = shortRunText(item.title || item.text || "处理进展", 220);
  const rawDetail = suppressGenericToolWait(shortRunText(item.detail || item.path || item.href || "", 220));
  const kind = inferActionKind(item, rawTitle, rawDetail);
  const detail = actionTarget(item, kind, rawTitle, rawDetail);
  const title = actionTitle(kind, state);
  return {
    detail,
    kind,
    observation: observationForAction({ detail, item, kind, rawDetail, state }),
    title,
  };
}

function inferActionKind(item: PublicChatTimelineItem, rawTitle: string, rawDetail: string): AgentRunActionKind {
  const kind = cleanRunText(item.kind);
  if (kind === "artifact") return "artifact";
  if (kind === "verification") return "verify";
  const haystack = cleanRunText([rawTitle, rawDetail, item.path, item.href].filter(Boolean).join(" ")).toLowerCase();
  if (/path_exists|stat_path|list_dir|确认|检查|路径|目录|artifact 路径/.test(haystack)) return "inspect";
  if (/read_file|read_path|读取|查看|文件读取|read\b/.test(haystack)) return "read";
  if (/search_text|search_files|glob_paths|rg\b|grep\b|搜索|查找|检索|匹配|search\b/.test(haystack)) return "search";
  if (/write_file|edit_file|apply_patch|写入|编辑|更新|修改|创建|write\b|edit\b|patch\b/.test(haystack)) return "write";
  if (/terminal|shell|powershell|command|npm\b|pytest\b|vitest\b|测试|命令|运行|执行/.test(haystack)) return "run";
  if (/web_search|fetch_url|browser|浏览器|网页|url|http/.test(haystack)) return "browse";
  if (/image_generate|生成图像|图片|图像|image/.test(haystack)) return "image";
  return "generic";
}

function actionTarget(item: PublicChatTimelineItem, kind: AgentRunActionKind, rawTitle: string, rawDetail: string) {
  const fromPath = cleanRunText(item.path || item.href);
  const titleTarget = stripActionPrefix(rawTitle);
  const detailTarget = stripActionPrefix(rawDetail);
  const candidates = kind === "run"
    ? [titleTarget, detailTarget, fromPath]
    : [fromPath, titleTarget, detailTarget];
  for (const candidate of candidates) {
    const target = publicTargetText(candidate, kind);
    if (target) return target;
  }
  return "";
}

function stripActionPrefix(value: unknown) {
  return cleanRunText(value)
    .replace(/^正在使用.+?处理\s*/i, "")
    .replace(/^(?:已读取文件|读取完成|搜索完成|检查完成|命令已完成|写入完成|更新完成|编辑完成|工具已完成|工具失败|读取失败|搜索失败|检查失败|命令失败|写入失败)\s*/i, "")
    .replace(/^正在(?:读取文件|读取|搜索|检查|确认|运行|调用工具|调用|写入|编辑|更新)\s*/i, "")
    .replace(/^(?:读取文件|读取|搜索|检查|确认|运行|调用工具|调用|写入|编辑|更新)\s*/i, "")
    .replace(/^执行\s+(?:read_file|read_path|search_text|search_files|glob_paths|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir)\s*/i, "")
    .replace(/[。.]$/g, "")
    .trim();
}

function publicTargetText(value: unknown, kind: AgentRunActionKind) {
  const text = stripTechnicalNoise(value);
  if (!text || isPureTechnicalToken(text) || isGenericActionTarget(text) || INTERNAL_REFERENCE_PATTERN.test(text)) {
    return "";
  }
  if (kind === "inspect" && /(?:不存在|尚未存在|已存在|存在|状态已确认|路径检查已完成|检查已完成)/.test(text)) {
    return "";
  }
  if (kind === "run") {
    return shortRunText(text, 120);
  }
  if (kind === "search" && !looksLikePath(text)) {
    return shortRunText(text, 90);
  }
  if (kind === "browse" && /^https?:\/\//i.test(text)) {
    return shortRunText(text, 120);
  }
  return compactPathLabel(text, 90);
}

function stripTechnicalNoise(value: unknown) {
  let text = cleanRunText(value);
  if (!text) return "";
  for (const prefix of GENERIC_TOOL_WAIT_PREFIXES) {
    if (text.toLowerCase().startsWith(prefix.toLowerCase())) {
      return "";
    }
  }
  text = text
    .replace(/(?:^|[：:\s])(?:read_file|read_path|search_text|search_files|glob_paths|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir)[。.]?$/i, "")
    .replace(/^工具(?:返回|状态|调用)?[：:]\s*/i, "")
    .replace(/^调用工具\s*/i, "")
    .replace(/^工具已完成\s*/i, "")
    .trim();
  if (/^(?:true|false|null|none|ok|success|done|completed|running|working)$/i.test(text)) {
    return "";
  }
  return text;
}

function isPureTechnicalToken(value: string) {
  return /^(?:read_file|read_path|search_text|search_files|glob_paths|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir|tool|工具)$/i.test(value);
}

function isGenericActionTarget(value: string) {
  return /^(?:文件|目录|路径|路径信息|路径状态|目标路径|artifact 路径|目标|当前目标|关键文件|相关代码|代码引用|测试|命令|验证|检查|工具|动作|操作|结果|上下文)$/i.test(value.trim());
}

function looksLikePath(value: string) {
  return /[\\/]/.test(value) || /\.[a-z0-9]{1,8}(?:\s|$)/i.test(value);
}

export function compactPathLabel(value: unknown, limit = 90) {
  const text = cleanRunText(value);
  if (!text) return "";
  const normalized = text.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 2 || !looksLikePath(text)) {
    return shortRunText(text, limit);
  }
  const tail = parts.at(-1) || "";
  const parent = parts.at(-2) || "";
  return shortRunText(parent ? `${parent}/${tail}` : tail, limit);
}

function actionTitle(kind: AgentRunActionKind, state: "running" | "done" | "error") {
  const done = state === "done";
  const error = state === "error";
  if (kind === "inspect") return error ? "确认目标需调整" : done ? "已确认目标" : "确认目标";
  if (kind === "read") return error ? "读取上下文需调整" : done ? "已读取上下文" : "读取上下文";
  if (kind === "search") return error ? "搜索方式需调整" : done ? "已搜索引用" : "搜索引用";
  if (kind === "write") return error ? "更新路径需调整" : done ? "已更新文件" : "更新文件";
  if (kind === "run") return error ? "验证方式需调整" : done ? "验证已返回" : "运行验证";
  if (kind === "browse") return error ? "访问方式需调整" : done ? "已读取网页" : "读取网页";
  if (kind === "image") return error ? "图像生成需调整" : done ? "图像已生成" : "生成图像";
  if (kind === "artifact") return "产物就绪";
  if (kind === "verify") return error ? "校验方式需调整" : done ? "校验完成" : "校验结果";
  return error ? "步骤需调整" : done ? "结果已返回" : "处理步骤";
}

export function actionSentence(item: PublicChatTimelineItem, variant: "current" | "history" = "history") {
  const kind = cleanRunText(item.kind);
  if (kind !== "tool_activity") {
    const text = shortRunText(item.title || item.text || item.detail || "处理中", 180);
    return variant === "current" && text && !text.startsWith("正在") ? `正在${text}` : text;
  }
  const action = actionViewForTimelineItem(item);
  const state = stateClassForTimelineItem(item);
  const subject = action.detail ? `${action.title} ${action.detail}` : action.title;
  if (state === "error") {
    return `${subject}，我会调整后继续`;
  }
  if (state === "done" || variant === "history") {
    return subject;
  }
  if (action.kind === "read") {
    return action.detail ? `正在读取 ${action.detail}` : "正在读取上下文";
  }
  if (action.kind === "search") {
    return action.detail ? `正在搜索 ${action.detail}` : "正在搜索相关引用";
  }
  if (action.kind === "inspect") {
    return action.detail ? `正在确认 ${action.detail}` : "正在确认目标状态";
  }
  if (action.kind === "write") {
    return action.detail ? `正在更新 ${action.detail}` : "正在更新文件";
  }
  if (action.kind === "run") {
    return action.detail ? `正在运行验证 ${action.detail}` : "正在运行验证";
  }
  return subject.startsWith("正在") ? subject : `正在${subject}`;
}

function observationForAction({
  detail,
  item,
  kind,
  rawDetail,
  state,
}: {
  detail: string;
  item: PublicChatTimelineItem;
  kind: AgentRunActionKind;
  rawDetail: string;
  state: "running" | "done" | "error";
}) {
  const result = meaningfulObservationDetail(rawDetail || item.text || item.detail || item.title, detail);
  if (state === "error") {
    return `观察：${shortRunText(item.recovery_hint || result || "当前动作需要调整路径、权限或输入后继续。", 180)}`;
  }
  if (state !== "done") {
    return "";
  }
  if (kind === "inspect") {
    if (/不存在|尚未存在|not exist|missing/i.test(result)) {
      return `观察：${shortRunText(result || "目标还不存在", 90)}，下一步应该创建目标或修正路径。`;
    }
    if (/存在|已确认/.test(result)) {
      return "观察：目标状态已确认，可以继续推进下一步。";
    }
    return detail ? `观察：已确认 ${detail} 的当前状态。` : "观察：目标状态已确认。";
  }
  if (kind === "read") {
    if (/agents\.md/i.test(detail)) {
      return result
        ? `观察：项目约定已读到，${shortRunText(result, 150)}`
        : "观察：项目约定已确认，后续要受协作边界、固定端口和验证闭环约束。";
    }
    return result && result !== detail
      ? `观察：已读到关键信息，${shortRunText(result, 150)}`
      : "观察：关键上下文已拿到，下一步可以基于文件事实判断。";
  }
  if (kind === "search") {
    if (/0\s*(?:条|个|matches|results)|没有|未找到|no results/i.test(result)) {
      return "观察：没有直接命中，下一步需要换关键词或回到调用入口排查。";
    }
    return result && result !== detail
      ? `观察：已定位相关线索，${shortRunText(result, 150)}`
      : "观察：相关引用已定位，下一步应该收敛到真实改动点。";
  }
  if (kind === "write") {
    return result && result !== detail
      ? `观察：更新结果已返回，${shortRunText(result, 150)}`
      : "观察：文件更新已返回，下一步需要用页面或测试验证。";
  }
  if (kind === "run") {
    return result
      ? `观察：验证命令已返回，${shortRunText(result, 150)}`
      : "观察：验证命令已返回，需要根据结果判断是否继续修正。";
  }
  if (result && result !== detail) {
    return `观察：${shortRunText(result, 160)}`;
  }
  return "观察：结果已返回，继续根据结果推进下一步。";
}

function meaningfulObservationDetail(value: unknown, target: string) {
  const text = stripActionPrefix(stripTechnicalNoise(value));
  if (!text || text === target || compactPathLabel(text) === target || INTERNAL_REFERENCE_PATTERN.test(text)) {
    return "";
  }
  if (GENERIC_TOOL_WAIT_PREFIXES.some((prefix) => text.toLowerCase().startsWith(prefix.toLowerCase()))) {
    return "";
  }
  return text;
}

function suppressGenericToolWait(value: string) {
  const text = cleanRunText(value);
  if (!text) return "";
  const lowered = text.toLowerCase();
  if (GENERIC_TOOL_WAIT_PREFIXES.some((prefix) => lowered.startsWith(prefix.toLowerCase()))) {
    return "";
  }
  return text;
}
