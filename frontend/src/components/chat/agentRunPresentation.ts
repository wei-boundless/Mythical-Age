import type { PublicChatTimelineItem } from "@/lib/api";

export type AgentRunActionKind =
  | "artifact"
  | "browse"
  | "edit"
  | "generic"
  | "image"
  | "inspect"
  | "memory"
  | "prepare"
  | "read"
  | "run"
  | "search"
  | "verify"
  | "work"
  | "write";

export type AgentRunActionView = {
  detail: string;
  kind: AgentRunActionKind;
  observation: string;
  title: string;
};

type AgentRunActionState = "running" | "done" | "error" | "stopped";

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
  if (["stopped", "aborted", "user_aborted", "cancelled", "canceled"].includes(state)) return "stopped";
  if (["error", "failed", "blocked", "missing"].includes(state) || item.kind === "blocked") return "error";
  if (["done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

export function timelineItemText(item: PublicChatTimelineItem | undefined) {
  if (!item) return "";
  return cleanRunText(item.public_summary || item.observation || item.text || item.detail || item.title || item.subject_label || item.path || item.href);
}

export function sameRunText(left: unknown, right: unknown) {
  const leftText = cleanRunText(left);
  const rightText = cleanRunText(right);
  if (!leftText || !rightText) return false;
  return leftText === rightText || leftText.includes(rightText) || rightText.includes(leftText);
}

export function actionViewForTimelineItem(item: PublicChatTimelineItem): AgentRunActionView {
  const state = stateClassForTimelineItem(item);
  const semantic = semanticActionViewForTimelineItem(item, state);
  if (semantic) return semantic;
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

function semanticActionViewForTimelineItem(item: PublicChatTimelineItem, state: AgentRunActionState): AgentRunActionView | null {
  const kind = cleanRunText(item.kind);
  const actionKind = normalizeActionKind(item.action_kind);
  const summary = cleanRunText(item.public_summary);
  const subject = publicTargetText(item.subject_label, actionKind || "generic");
  if (kind !== "work_action" && !actionKind && !summary && !cleanRunText(item.observation)) {
    return null;
  }
  const resolvedKind = actionKind || "generic";
  const title = cleanRunText(item.title) || actionTitle(resolvedKind, state);
  return {
    detail: subject,
    kind: resolvedKind,
    observation: cleanRunText(item.observation) || observationForAction({
      detail: subject,
      item,
      kind: resolvedKind,
      rawDetail: cleanRunText(item.detail),
      state,
    }),
    title,
  };
}

function normalizeActionKind(value: unknown): AgentRunActionKind | "" {
  const kind = cleanRunText(value).toLowerCase();
  if (kind === "edit" || kind === "write") return "edit";
  if (["artifact", "browse", "generic", "image", "inspect", "memory", "prepare", "read", "run", "search", "verify", "work"].includes(kind)) {
    return kind as AgentRunActionKind;
  }
  return "";
}

function inferActionKind(item: PublicChatTimelineItem, rawTitle: string, rawDetail: string): AgentRunActionKind {
  const kind = cleanRunText(item.kind);
  if (kind === "artifact") return "artifact";
  if (kind === "verification") return "verify";
  const haystack = cleanRunText([rawTitle, rawDetail, item.path, item.href].filter(Boolean).join(" ")).toLowerCase();
  if (/\bnew-item\b|\bmkdir\b|itemtype\s+directory/.test(haystack)) return "prepare";
  if (/memory_search|记忆检索|检索记忆|相关记忆|\bmemory\b/.test(haystack)) return "memory";
  if (/path_exists|stat_path|list_dir|确认|检查|路径|目录|artifact 路径/.test(haystack)) return "inspect";
  if (/read_file|read_path|读取|查看|文件读取|read\b/.test(haystack)) return "read";
  if (/search_text|search_files|glob_paths|rg\b|grep\b|搜索|查找|检索|匹配|search\b/.test(haystack)) return "search";
  if (/write_file|edit_file|apply_patch|写入|编辑|更新|修改|创建|write\b|edit\b|patch\b/.test(haystack)) return "write";
  if (/web_search|fetch_url|browser|浏览器|网页|url|http/.test(haystack)) return "browse";
  if (/image_generate|生成图像|图片|图像|image/.test(haystack)) return "image";
  if (/terminal|shell|powershell|command|npm\b|pytest\b|vitest\b|测试|命令|运行|执行/.test(haystack)) return "run";
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
    .replace(/^执行\s+(?:read_file|read_path|search_text|search_files|glob_paths|memory_search|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir|image_generate|image_generation|generate_image|image_asset)\s*/i, "")
    .replace(/[。.]$/g, "")
    .trim();
}

function publicTargetText(value: unknown, kind: AgentRunActionKind) {
  const text = stripTechnicalNoise(value);
  if (
    !text
    || looksLikeStructuredToolPayload(text)
    || looksLikeRawFileListing(text)
    || looksLikeRawCommand(text)
    || isPureTechnicalToken(text)
    || isGenericActionTarget(text)
    || INTERNAL_REFERENCE_PATTERN.test(text)
  ) {
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
    .replace(/(?:^|[：:\s])(?:read_file|read_path|search_text|search_files|glob_paths|memory_search|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir|image_generate|image_generation|generate_image|image_asset)[。.]?$/i, "")
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
  return /^(?:read_file|read_path|search_text|search_files|glob_paths|memory_search|write_file|edit_file|terminal|shell|path_exists|stat_path|list_dir|image_generate|image_generation|generate_image|image_asset|tool|工具)$/i.test(value);
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

function actionTitle(kind: AgentRunActionKind, state: AgentRunActionState) {
  const done = state === "done";
  const error = state === "error";
  if (state === "stopped") return "已停止";
  if (kind === "inspect") return error ? "确认目标未完成" : done ? "已确认目标" : "确认目标";
  if (kind === "read") return error ? "读取上下文未完成" : done ? "已读取上下文" : "读取上下文";
  if (kind === "search") return error ? "搜索未完成" : done ? "已搜索引用" : "搜索引用";
  if (kind === "memory") return error ? "记忆检索未完成" : done ? "记忆检索已返回" : "检索相关记忆";
  if (kind === "write" || kind === "edit") return error ? "更新未完成" : done ? "已更新文件" : "更新文件";
  if (kind === "run") return error ? "验证未完成" : done ? "验证已返回" : "运行验证";
  if (kind === "prepare") return error ? "输出准备未完成" : done ? "输出准备完成" : "准备输出";
  if (kind === "browse") return error ? "网页读取未完成" : done ? "已读取网页" : "读取网页";
  if (kind === "image") return error ? "图像生成未完成" : done ? "图像已生成" : "生成图像";
  if (kind === "artifact") return "产物就绪";
  if (kind === "verify") return error ? "校验未完成" : done ? "校验完成" : "校验结果";
  if (kind === "work") return error ? "步骤未完成" : done ? "结果已返回" : "处理任务";
  return error ? "步骤未完成" : done ? "结果已返回" : "处理任务";
}

export function actionSentence(item: PublicChatTimelineItem, variant: "current" | "history" = "history") {
  const kind = cleanRunText(item.kind);
  if (kind !== "tool_activity" && kind !== "work_action") {
    const text = shortRunText(item.title || item.text || item.detail || "处理中", 180);
    return variant === "current" && text && !text.startsWith("正在") ? `正在${text}` : text;
  }
  const action = actionViewForTimelineItem(item);
  const state = stateClassForTimelineItem(item);
  const summary = publicTargetText(item.public_summary, action.kind);
  if (summary && cleanRunText(item.kind) === "work_action") {
    return state === "error" ? `${summary}，我会换一种方式继续` : summary;
  }
  const subject = action.detail ? `${action.title} ${action.detail}` : action.title;
  if (state === "error") {
    return `${subject}，我会换一种方式继续`;
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
  if (action.kind === "memory") {
    return action.detail ? `正在检索记忆 ${action.detail}` : "正在检索相关记忆";
  }
  if (action.kind === "inspect") {
    return action.detail ? `正在确认 ${action.detail}` : "正在确认目标状态";
  }
  if (action.kind === "write" || action.kind === "edit") {
    return action.detail ? `正在更新 ${action.detail}` : "正在更新文件";
  }
  if (action.kind === "prepare") {
    return action.detail ? `正在准备 ${action.detail}` : "正在准备输出";
  }
  if (action.kind === "image") {
    return action.detail ? `正在生成图像 ${action.detail}` : "正在生成图像";
  }
  if (action.kind === "browse") {
    return action.detail ? `正在读取网页 ${action.detail}` : "正在读取网页";
  }
  if (action.kind === "run") {
    return action.detail ? `正在运行验证 ${action.detail}` : "正在运行验证";
  }
  if (action.kind === "work" || action.kind === "generic") {
    return action.detail ? `正在处理 ${action.detail}` : "正在处理任务";
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
  state: AgentRunActionState;
}) {
  const result = meaningfulObservationDetail(rawDetail || item.text || item.detail || item.title, detail);
  const semanticObservation = cleanRunText(item.observation);
  if (semanticObservation) {
    return stripObservationLabel(semanticObservation);
  }
  if (state === "error") {
    return shortRunText(item.recovery_hint || result || "当前动作没有执行成功，我会换一种方式继续。", 180);
  }
  if (state === "stopped") {
    return "本轮操作已停止。";
  }
  if (state !== "done") {
    return "";
  }
  if (kind === "inspect") {
    if (/不存在|尚未存在|not exist|missing/i.test(result)) {
      return `${shortRunText(result || "目标还不存在", 90)}，下一步应该创建目标或修正路径。`;
    }
    if (/存在|已确认/.test(result)) {
      return "目标状态已确认，可以继续推进下一步。";
    }
    return detail ? `已确认 ${detail} 的当前状态。` : "目标状态已确认。";
  }
  if (kind === "read") {
    if (/agents\.md/i.test(detail)) {
      return result
        ? `项目约定已读到，${shortRunText(result, 150)}`
        : "项目约定已确认，后续要受协作边界、固定端口和验证闭环约束。";
    }
    return result && result !== detail
      ? `已读到关键信息，${shortRunText(result, 150)}`
      : "关键上下文已拿到，下一步可以基于文件事实判断。";
  }
  if (kind === "search") {
    if (/0\s*(?:条|个|matches|results)|没有|未找到|no results/i.test(result)) {
      return "没有直接命中，下一步需要换关键词或回到调用入口排查。";
    }
    return result && result !== detail
      ? `已定位相关线索，${shortRunText(result, 150)}`
      : "相关引用已定位，下一步应该收敛到真实改动点。";
  }
  if (kind === "memory") {
    return result && result !== detail
      ? `已检索相关记忆，${shortRunText(result, 150)}`
      : "记忆检索已返回，下一步会纳入判断。";
  }
  if (kind === "write" || kind === "edit") {
    return result && result !== detail
      ? `更新结果已返回，${shortRunText(result, 150)}`
      : "文件更新已返回，下一步需要用页面或测试验证。";
  }
  if (kind === "prepare") {
    return result && result !== detail
      ? `输出准备已返回，${shortRunText(result, 150)}`
      : "输出准备已确认，可以继续推进。";
  }
  if (kind === "image") {
    return result && result !== detail
      ? `图像生成已返回，${shortRunText(result, 150)}`
      : "图像生成已返回，下一步会确认产物是否可用。";
  }
  if (kind === "run") {
    return result
      ? `验证命令已返回，${shortRunText(result, 150)}`
      : "验证命令已返回，需要根据结果判断是否继续修正。";
  }
  if (result && result !== detail) {
    return shortRunText(result, 160);
  }
  return "结果已返回，继续根据结果推进下一步。";
}

function stripObservationLabel(value: unknown) {
  return cleanRunText(value).replace(/^(?:观察结果|观察报告|观察)[：:\s]*/u, "");
}

function meaningfulObservationDetail(value: unknown, target: string) {
  const text = stripActionPrefix(stripTechnicalNoise(value));
  if (!text || text === target || compactPathLabel(text) === target || INTERNAL_REFERENCE_PATTERN.test(text)) {
    return "";
  }
  if (looksLikeStructuredToolPayload(text) || looksLikeRawFileListing(text)) {
    return "";
  }
  if (GENERIC_TOOL_WAIT_PREFIXES.some((prefix) => text.toLowerCase().startsWith(prefix.toLowerCase()))) {
    return "";
  }
  return text;
}

function looksLikeStructuredToolPayload(value: string) {
  const text = cleanRunText(value);
  if (!text) return false;
  if ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]"))) {
    return true;
  }
  return /\b(?:authority|diagnostics|matched_version_count|candidate_version_count|structured_payload|result_envelope)\b/i.test(text);
}

function looksLikeRawFileListing(value: string) {
  const text = cleanRunText(value);
  if (!text) return false;
  return /\bfile\s+[^\s]+\s+\d+\s+bytes\b/i.test(text)
    || /\b\d+\s+bytes\s+(?:file|directory|dir)\b/i.test(text);
}

function looksLikeRawCommand(value: string) {
  const text = cleanRunText(value);
  if (!text) return false;
  return /\b(New-Item|Set-Content|Get-Content|Remove-Item|Move-Item|Copy-Item|npm|pnpm|yarn|pytest|python|powershell|cmd\s*\/c|git|rg|grep|mkdir|touch)\b/i.test(text)
    || /\s-(?:ItemType|Path|Recurse|Force|Filter|Pattern|Command)\b/i.test(text)
    || /[;&|]{1,2}/.test(text);
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
