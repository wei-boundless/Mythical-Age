const MODEL_ACTION_TYPES = new Set([
  "respond",
  "ask_user",
  "tool_call",
  "request_task_run",
  "active_work_control",
  "block",
]);

const INTERNAL_CONTRACT_OPENERS = [
  "你是一名正在收口的 coding agent",
  "当你需要提交动作时",
  "请根据用户当前请求、运行边界和允许动作",
  "你只能输出一个 JSON action",
  "你必须只输出一个 JSON action",
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
  "closeout_lifecycle",
  "authority 必须",
  "只输出一个合法 JSON",
  "不能输出 Markdown 代码块",
];

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
  if (containsInternalControlProtocolObject(parseJsonLike(text))) {
    return true;
  }
  if (looksLikeEmbeddedModelActionProtocol(text)) {
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

function looksLikeEmbeddedModelActionProtocol(value: string) {
  return /"authority"\s*:\s*"harness\.loop\.model_action_request"/i.test(value)
    || /"action_type"\s*:\s*"(?:respond|ask_user|tool_call|request_task_run|active_work_control|block)"/i.test(value)
    && /"(?:public_action_state|task_contract_seed|tool_call|final_answer|user_question|blocking_reason|active_work_control)"\s*:/i.test(value);
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
