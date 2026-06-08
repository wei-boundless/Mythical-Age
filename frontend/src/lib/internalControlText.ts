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
  const normalized = text.toLowerCase().replace(/^[`'"([\s]+|[`'".。,:：;；)\]\s]+$/g, "");
  if (INTERNAL_ACTIVE_WORK_CONTROL_TERMS.has(normalized)) {
    return true;
  }
  if (!INTERNAL_ACTIVE_WORK_CONTROL_RE.test(normalized)) {
    return false;
  }
  const remainder = normalized
    .replace(INTERNAL_ACTIVE_WORK_CONTROL_RE, "")
    .replace(/\b(?:action|intent|response|control)\b/gi, "")
    .replace(/[`'"=:.。,:：;；()[\]{}\s_-]+/g, "");
  return !remainder;
}

export function hideInternalActiveWorkControlText(value: unknown) {
  return isInternalActiveWorkControlText(value) ? "" : String(value ?? "").trim();
}
