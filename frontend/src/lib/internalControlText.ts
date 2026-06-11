const INTERNAL_ACTIVE_WORK_CONTROL_TERMS = new Set([
  "continue_active_work",
  "pause_active_work",
  "stop_active_work",
  "append_instruction_to_active_work",
  "answer_about_active_work",
  "ask_user",
  "answer_then_continue_active_work",
  "active_work_control",
  "active_work_control.action",
  "control_action",
]);

const INTERNAL_ACTIVE_WORK_CONTROL_KEYS = new Set([
  "action",
  "intent",
  "resolved_action",
  "active_work_control",
  "relation_to_current_work",
  "relation",
  "response",
  "appended_instruction",
  "continuation_strategy",
  "turn_response_policy",
  "user_turn_kind",
  "answer_obligation",
]);

const INTERNAL_ACTIVE_WORK_CONTROL_RE = new RegExp(
  `\\b(?:${Array.from(INTERNAL_ACTIVE_WORK_CONTROL_TERMS)
    .sort((left, right) => right.length - left.length)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|")})\\b`,
  "i",
);

export function isInternalActiveWorkControlText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  if (containsInternalActiveWorkControlObject(parseJsonLike(text))) {
    return true;
  }
  const normalized = text.toLowerCase().replace(/^[`'"([\s]+|[`'".。,:：;；)\]\s]+$/g, "");
  if (
    /"(?:action|intent|resolved_action)"\s*:\s*"[^"]*active_work/i.test(normalized)
    && /"(?:active_work_control|relation_to_current_work|continuation_strategy|turn_response_policy|answer_obligation|appended_instruction|user_turn_kind)"\s*:/i.test(normalized)
  ) {
    return true;
  }
  if (INTERNAL_ACTIVE_WORK_CONTROL_TERMS.has(normalized)) {
    return true;
  }
  return INTERNAL_ACTIVE_WORK_CONTROL_RE.test(normalized);
}

export function hideInternalActiveWorkControlText(value: unknown) {
  return isInternalActiveWorkControlText(value) ? "" : String(value ?? "").trim();
}

export function isInternalControlProtocolText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  if (isInternalActiveWorkControlText(text)) {
    return true;
  }
  const parsed = parseJsonLike(text);
  if (containsInternalControlProtocolObject(parsed)) {
    return true;
  }
  const normalized = text.toLowerCase();
  if (/(?:本轮(?:已经)?达到工具预算上限|本轮工具预算已经耗尽)[\s\S]{0,120}?(?:内部工具协议|动作残片|收口裁决)/i.test(text)) {
    return true;
  }
  return /"authority"\s*:\s*"harness\.loop\.model_action_request"/i.test(normalized)
    || /"model_action_request"\s*:/i.test(normalized)
    || /"action_type"\s*:\s*"(?:respond|ask_user|tool_call|request_task_run|active_work_control|block)"/i.test(normalized)
    || /\bmodel_action_(?:request|admission)\b/i.test(normalized);
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

function containsInternalActiveWorkControlObject(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some((item) => containsInternalActiveWorkControlObject(item));
  }
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  const actionType = String(record.action_type ?? "").trim().toLowerCase();
  if (actionType === "active_work_control") {
    return true;
  }
  if (containsInternalActiveWorkControlObject(record.active_work_control)) {
    return true;
  }
  const action = String(record.resolved_action ?? record.action ?? record.intent ?? "").trim().toLowerCase();
  if (!INTERNAL_ACTIVE_WORK_CONTROL_TERMS.has(action)) {
    return false;
  }
  return Object.keys(record).some((key) => INTERNAL_ACTIVE_WORK_CONTROL_KEYS.has(key));
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
  if (record.model_action_request || record.model_action_admission || record.admission) {
    return true;
  }
  const actionType = String(record.action_type ?? "").trim();
  if (/^(respond|ask_user|tool_call|request_task_run|active_work_control|block)$/.test(actionType)) {
    return true;
  }
  return containsInternalActiveWorkControlObject(record);
}
