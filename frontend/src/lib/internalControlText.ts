const MODEL_ACTION_TYPES = new Set([
  "respond",
  "ask_user",
  "tool_call",
  "request_task_run",
  "active_work_control",
  "block",
]);

const INTERNAL_CONTRACT_OPENERS = [
  "系统运行控制观察如下",
  "你现在是本轮收口负责人",
  "当你需要让系统执行动作时",
  "请根据用户当前请求、运行边界和允许动作",
  "你只能输出一个 JSON action",
];

const INTERNAL_CONTRACT_MARKERS = [
  "harness.loop.model_action_request",
  "action_type",
  "allowed_action_types",
  "active_work_context",
  "active_work_control",
  "public_action_state",
  "final_answer",
  "tool_calls",
  "authority 必须",
  "只输出一个合法 JSON",
  "不能在 JSON 外输出正文",
];

const INTERNAL_RUNTIME_FALLBACK_TEXT = new Set([
  "本轮已经达到工具预算上限，且收口裁决仍不可安全展示。已停止继续调用工具，避免把内部工具协议或动作残片当作回答。",
  "本轮工具预算已经耗尽，但收口动作生成失败。已停止继续调用工具。",
]);

export function isInternalActiveWorkControlText(value: unknown) {
  return isInternalControlProtocolText(value);
}

export function hideInternalActiveWorkControlText(value: unknown) {
  return isInternalControlProtocolText(value) ? "" : String(value ?? "").trim();
}

export function isInternalControlProtocolText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  if (INTERNAL_RUNTIME_FALLBACK_TEXT.has(text)) {
    return true;
  }
  if (containsInternalControlProtocolObject(parseJsonLike(text))) {
    return true;
  }
  return looksLikeWholeInternalContractPrompt(text);
}

function parseJsonLike(value: string): unknown {
  let text = value.trim();
  if (text.startsWith("```")) {
    text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
  }
  if (!((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")))) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function containsInternalControlProtocolObject(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some((item) => containsInternalControlProtocolObject(item));
  }
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  const authority = String(record.authority ?? "").trim();
  if (authority === "harness.loop.model_action_request") {
    return true;
  }
  if (containsInternalControlProtocolObject(record.model_action_request)) {
    return true;
  }
  const actionType = String(record.action_type ?? "").trim();
  if (!MODEL_ACTION_TYPES.has(actionType)) {
    return false;
  }
  return Boolean(
    authority
    || record.final_answer
    || record.user_question
    || record.blocking_reason
    || record.tool_calls
    || record.task_contract_seed
    || record.active_work_control
  );
}

function looksLikeWholeInternalContractPrompt(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length < 120) {
    return false;
  }
  if (!INTERNAL_CONTRACT_OPENERS.some((opener) => text.startsWith(opener))) {
    return false;
  }
  const markerCount = INTERNAL_CONTRACT_MARKERS.reduce(
    (count, marker) => count + (text.includes(marker) ? 1 : 0),
    0,
  );
  return markerCount >= 2;
}
