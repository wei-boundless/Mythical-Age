const PUBLIC_RUNTIME_STATUS_LABELS: Record<string, string> = {
  user_input_required: "等待你的确认",
  waiting_executor: "等待继续",
  waiting_user: "等待你的确认",
  waiting_approval: "等待权限确认",
  waiting_safe_boundary: "等待安全边界",
  task_executor_scheduled: "任务已进入执行流程",
  runtime_restart_waiting_resume: "运行时重启后待续跑",
  runtime_cell_missing_after_restart: "连接恢复后需要重新接续运行",
  background_executor_missing_after_restart: "连接恢复后需要重新接续运行",
  runtime_cell_cancelled: "输出流已取消",
  missing_terminal_event: "输出流没有正常收口",
  stream_exception: "输出流异常中断",
  stream_cancelled: "输出流已取消",
  stream_transport_error: "输出流连接中断",
  stream_reconnect_attempts_exhausted: "输出流连接恢复失败",
  partial_stream_error: "输出流暂时中断",
  partial_stream_recovery: "输出流已恢复",
  agent_contract_feedback_required: "需要 agent 重新收口",
  tool_budget_exhausted: "本轮工具预算已用完",
  single_turn_tool_iteration_limit: "本轮工具预算已用完",
  single_agent_turn_empty_response: "agent 未生成可发布回复",
  tool_limit_closeout_protocol_failed: "agent 收口动作未满足要求",
  tool_limit_missing_answer: "agent 收口缺少可发布回复",
  backend_error: "后端处理异常",
  completed: "已完成",
  failed: "处理失败",
  blocked: "处理遇到阻塞",
  stopped: "运行已停止",
  aborted: "运行已停止",
  cancelled: "运行已停止",
  canceled: "运行已停止",
};

const INLINE_RUNTIME_STATUS_LABELS = Object.fromEntries(
  Object.entries(PUBLIC_RUNTIME_STATUS_LABELS)
    .filter(([code]) => code.includes("_") || code.includes("-") || code.includes(":")),
);

const INLINE_RUNTIME_STATUS_PATTERN = new RegExp(
  `(^|[^A-Za-z0-9_:-])(${Object.keys(INLINE_RUNTIME_STATUS_LABELS)
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp)
    .join("|")})(?=$|[^A-Za-z0-9_:-])`,
  "gi",
);

const MACHINE_PROGRESS_STATES = new Set([
  "thinking",
  "working",
  "responding",
  "verifying",
  "waiting_for_tool",
  "tool_returned",
  "ready_to_finish",
  "blocked",
]);

export function publicRuntimeStatusLabel(value: unknown) {
  const normalized = runtimeCode(value);
  return normalized ? PUBLIC_RUNTIME_STATUS_LABELS[normalized] || "" : "";
}

export function publicRuntimeStatusText(value: unknown) {
  const text = cleanRuntimeText(value);
  if (!text) return "";
  const exact = publicRuntimeStatusLabel(text);
  if (exact) return exact;
  const replaced = text.replace(INLINE_RUNTIME_STATUS_PATTERN, (match, prefix: string, code: string) => {
    const label = PUBLIC_RUNTIME_STATUS_LABELS[String(code || "").toLowerCase()];
    return label ? `${prefix}${label}` : match;
  });
  if (replaced !== text) return replaced.trim();
  return looksLikeRuntimeReasonCode(text) ? "运行状态已更新" : text;
}

export function publicRuntimeProgressText(value: unknown) {
  const text = publicRuntimeStatusText(value);
  if (!text) return "";
  return runtimeLooksLikeMachineStatusLeak(text) ? "" : text;
}

export function runtimeLooksLikeMachineStatusLeak(value: unknown) {
  const lowered = cleanRuntimeText(value).toLowerCase();
  if (!lowered) return false;
  if (MACHINE_PROGRESS_STATES.has(lowered)) return true;
  if (/^(状态|status|completion[_\s-]*status|visible[_\s-]*status)\s*[:：]?\s*(thinking|working|responding|verifying|waiting_for_tool|tool_returned|ready_to_finish|blocked)$/i.test(lowered)) {
    return true;
  }
  const compact = lowered.replace(/[\s。.!！?？,，;；:：_-]+/g, "");
  return Array.from(MACHINE_PROGRESS_STATES).some((item) => item.replace(/_/g, "") === compact);
}

function runtimeCode(value: unknown) {
  return cleanRuntimeText(value).toLowerCase();
}

function cleanRuntimeText(value: unknown) {
  return String(value ?? "")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function looksLikeRuntimeReasonCode(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return false;
  if (anyNonAscii(normalized)) return false;
  return normalized.includes("_") || /^(task|stream|runtime|background)[-:]/i.test(normalized);
}

function anyNonAscii(value: string) {
  return Array.from(value).some((char) => char.charCodeAt(0) > 127);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
