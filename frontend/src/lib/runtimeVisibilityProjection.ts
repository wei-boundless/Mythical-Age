import type { RuntimeProgressEntry, SessionActivityLevel, UserReceiptArtifact } from "./store/types";

export type RuntimeVisibilityProjection = {
  stageStatus?: string;
  activityTitle?: string;
  activityDetail?: string;
  level?: SessionActivityLevel;
  progressEntry?: RuntimeProgressEntry;
  terminalEvent?: "done" | "error" | "stopped";
};

const INTERNAL_RUNTIME_STEPS = new Set([
  "turn_started",
  "runtime_packet_compiled",
  "model_action_received",
  "action_admission_checked",
  "bounded_observation_recorded",
]);

function isChatTurnRunId(value: unknown) {
  const normalized = text(value).toLowerCase();
  return normalized.startsWith("turnrun:");
}

function formalTaskRunId(...values: unknown[]) {
  for (const value of values) {
    const normalized = text(value);
    if (normalized.toLowerCase().startsWith("taskrun:")) {
      return normalized;
    }
  }
  return "";
}

function formalTurnRunId(...values: unknown[]) {
  for (const value of values) {
    const normalized = text(value);
    if (normalized.toLowerCase().startsWith("turnrun:")) {
      return normalized;
    }
  }
  return "";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function short(value: unknown, limit = 360) {
  const normalized = text(value).replace(/\s+/g, " ");
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function isInternalRuntimeReference(value: unknown) {
  const normalized = text(value);
  if (!normalized) return false;
  return /(?:^|\s)(?:harness|backend|runtime|query|agent_system|capability_system|health_system|task_system)(?:\.[A-Za-z0-9_-]+){2,}(?:\s|$)/i.test(normalized)
    || /\b(?:TaskRun|RuntimeInvocationPacket|runtime packet|answer_source|task_run_id|event_id)\b/i.test(normalized);
}

function publicRuntimeText(value: unknown, limit = 360) {
  if (isInternalRuntimeReference(value)) {
    return "";
  }
  const normalized = short(value, limit)
    .replace(/\bTaskRun\b/gi, "当前工作")
    .replace(/\bruntime packet\b/gi, "上下文")
    .replace(/\bagent\b/gi, "助手")
    .replace(/执行器/g, "处理流程")
    .replace(/正式任务/g, "当前工作")
    .replace(/任务待办/g, "处理清单")
    .replace(/任务生命周期/g, "处理流程")
    .replace(/任务运行/g, "处理进展")
    .replace(/会话运行/g, "处理进展")
    .replace(/运行装配/g, "整理上下文");
  return normalized.trim();
}

function terminalReasonIndicatesFailure(value: unknown) {
  const reason = text(value).toLowerCase();
  if (!reason || reason === "completed" || reason === "task_executor_scheduled" || reason === "waiting_executor") {
    return false;
  }
  return (
    reason.includes("failed")
    || reason.includes("error")
    || reason.includes("blocked")
    || reason.includes("limit")
    || reason.includes("exhausted")
    || reason.includes("repair_required")
    || reason.includes("user_aborted")
  );
}

function isTaskRunHandoffEvent(data: Record<string, unknown>) {
  const taskRun = record(data.task_run);
  const taskRunId = formalTaskRunId(data.runtime_task_run_id, taskRun.task_run_id);
  if (!taskRunId) {
    return false;
  }
  const reason = text(data.terminal_reason);
  const channel = text(data.answer_channel);
  return reason === "task_executor_scheduled"
    || reason === "session_active_task_exists"
    || channel === "task_control";
}

function shortCommand(value: unknown, limit = 180) {
  const normalized = text(value).replace(/\s+/g, " ");
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function shortId(value: unknown, limit = 18) {
  const normalized = text(value);
  if (!normalized) return "";
  if (normalized.length <= limit) return normalized;
  const parts = normalized.split(":").filter(Boolean);
  const tail = parts.at(-1) || normalized;
  return tail.length <= limit ? tail : `${tail.slice(0, Math.max(6, limit - 1))}...`;
}

function arrayText(value: unknown, limit = 6) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => text(item)).filter(Boolean).slice(0, limit);
}

function artifactsFromPaths(paths: string[]): UserReceiptArtifact[] {
  return paths.slice(0, 6).map((path) => ({ label: "产物", path }));
}

function artifactPathFromRecord(value: unknown) {
  const item = record(value);
  return text(item.path ?? item.file ?? item.file_path ?? item.artifact_path ?? item.ref ?? item.uri);
}

function artifactsFromMixed(value: unknown): UserReceiptArtifact[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") {
        const path = text(item);
        return path ? { label: "产物", path } : null;
      }
      const path = artifactPathFromRecord(item);
      if (path) return { label: text(record(item).label) || "产物", path };
      const label = text(record(item).label ?? record(item).title);
      return label ? { label } : null;
    })
    .filter((item): item is UserReceiptArtifact => Boolean(item))
    .slice(0, 6);
}

function metaItem(label: string, value: unknown, options: { shorten?: boolean } = {}) {
  const normalized = options.shorten ? shortId(value) : text(value);
  return normalized ? { label, value: normalized } : null;
}

function compactMeta(items: Array<{ label: string; value: string } | null | undefined>) {
  return items.filter((item): item is { label: string; value: string } => Boolean(item?.label && item.value)).slice(0, 6);
}

function commandPreviewFromArgs(args: Record<string, unknown>, fallback?: unknown) {
  const command = shortCommand(args.command ?? args.shell_command ?? args.cmd ?? args.script);
  if (command) return command;
  const path = shortCommand(args.path ?? args.file_path ?? args.relative_path ?? args.target_path);
  if (path) return path;
  const query = shortCommand(args.query ?? args.pattern ?? args.search ?? args.text);
  if (query) return query;
  const url = shortCommand(args.url ?? args.href);
  if (url) return url;
  return shortCommand(fallback);
}

function commandPreviewFromToolCall(toolCall: Record<string, unknown>, fallback?: unknown) {
  const args = record(toolCall.args ?? toolCall.input);
  return commandPreviewFromArgs(args, fallback ?? toolCall.command ?? toolCall.path ?? toolCall.query);
}

function toolActivityText(toolName: string, preview?: string) {
  const normalized = toolName.toLowerCase();
  const target = preview || toolName || "工具";
  if (normalized === "terminal" || normalized === "shell" || normalized.includes("command")) {
    return {
      startedTitle: "正在运行",
      completedTitle: "命令已完成",
      failedTitle: "命令失败",
      statusRunning: "运行中",
      statusDone: "已完成",
      statusFailed: "失败",
      display: target,
    };
  }
  if (normalized.includes("read")) {
    return {
      startedTitle: "正在读取",
      completedTitle: "读取完成",
      failedTitle: "读取失败",
      statusRunning: "读取中",
      statusDone: "已完成",
      statusFailed: "失败",
      display: target,
    };
  }
  if (normalized.includes("write") || normalized.includes("edit")) {
    return {
      startedTitle: "正在写入",
      completedTitle: "写入完成",
      failedTitle: "写入失败",
      statusRunning: "写入中",
      statusDone: "已完成",
      statusFailed: "失败",
      display: target,
    };
  }
  if (normalized.includes("search")) {
    return {
      startedTitle: "正在搜索",
      completedTitle: "搜索完成",
      failedTitle: "搜索失败",
      statusRunning: "搜索中",
      statusDone: "已完成",
      statusFailed: "失败",
      display: target,
    };
  }
  return {
    startedTitle: "正在调用",
    completedTitle: "工具已完成",
    failedTitle: "工具失败",
    statusRunning: "调用中",
    statusDone: "已完成",
    statusFailed: "失败",
    display: target,
  };
}

function runtimeEvent(data: Record<string, unknown>) {
  const event = record(data.event);
  if (Object.keys(event).length) {
    const payload = record(event.payload);
    const taskRun = record(payload.task_run);
    const runId = text(event.run_id) || text(event.task_run_id);
    return {
      eventId: text(event.event_id),
      runId,
      taskRunId: formalTaskRunId(taskRun.task_run_id, data.task_run_id, event.task_run_id, runId),
      eventType: text(event.event_type),
      createdAt: numberValue(event.created_at),
      payload,
    };
  }
  const runId = text(data.run_id) || text(data.task_run_id);
  return {
    eventId: text(data.event_id),
    runId,
    taskRunId: formalTaskRunId(data.task_run_id, runId),
    eventType: text(data.event_type),
    createdAt: numberValue(data.created_at),
    payload: record(data.payload),
  };
}

function entry(
  eventType: string,
  title: string,
  options: {
    body?: string;
    publicNote?: string;
    agentBrief?: string;
    evidenceType?: string;
    level?: SessionActivityLevel;
    kind?: RuntimeProgressEntry["kind"];
    statusText?: string;
    meta?: RuntimeProgressEntry["meta"];
    toolName?: string;
    runId?: string;
    taskRunId?: string;
    eventId?: string;
    createdAt?: number;
    startedAt?: number;
    completedAt?: number;
    artifacts?: UserReceiptArtifact[];
  } = {},
): RuntimeProgressEntry {
  return {
    id: options.eventId || `${eventType}:${options.taskRunId || options.runId || ""}:${options.createdAt || Date.now()}:${title}`,
    level: options.level || "running",
    title,
    body: options.body ? short(options.body) : undefined,
    publicNote: options.publicNote ? short(options.publicNote) : undefined,
    agentBrief: options.agentBrief ? short(options.agentBrief, 180) : undefined,
    evidenceType: options.evidenceType,
    eventType,
    kind: options.kind,
    statusText: options.statusText,
    meta: options.meta?.slice(0, 6),
    toolName: options.toolName,
    runId: options.runId,
    taskRunId: options.taskRunId,
    createdAt: options.createdAt,
    startedAt: options.startedAt,
    completedAt: options.completedAt,
    artifacts: options.artifacts?.slice(0, 6),
  };
}

function planningPhaseProjection(eventType: string, payload: Record<string, unknown>, meta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const review = record(payload.plan_coverage_review);
  const plan = record(payload.agent_plan_draft);
  const requirement = record(payload.agent_plan_requirement);
  const passed = review.passed === true;
  const stepCount = Array.isArray(plan.steps) ? plan.steps.length : 0;
  const reason = text(review.required_replan_reason ?? requirement.reason);
  const body = [
    `计划步骤：${stepCount}`,
    reason ? `状态：${reason}` : "",
  ].filter(Boolean).join("\n");
  return {
    stageStatus: "检查执行计划",
    activityTitle: "检查执行计划",
    activityDetail: reason || (passed ? "计划覆盖要求" : "计划需要补充"),
    level: passed ? "success" : "warning",
    progressEntry: entry(eventType, "检查执行计划", {
      body,
      level: passed ? "success" : "warning",
      kind: "stage",
      statusText: passed ? "通过" : "需补充",
      runId: meta.runId,
      taskRunId: meta.taskRunId,
      eventId: meta.eventId,
      createdAt: meta.createdAt,
      meta: compactMeta([
        metaItem("步骤", stepCount),
        metaItem("来源", plan.source),
      ]),
    }),
  };
}

function verificationProjection(eventType: string, payload: Record<string, unknown>, meta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const verification = record(payload.verification);
  const review = record(verification.verification_review);
  const judgment = record(verification.completion_judgment);
  const passed = verification.passed === true || review.passed === true || judgment.completed === true;
  const body = short(
    review.summary
    ?? judgment.reason
    ?? verification.summary
    ?? (passed ? "交付物验证通过" : "交付物仍有缺口"),
  );
  return {
    stageStatus: "检查交付物",
    activityTitle: "检查交付物",
    activityDetail: body,
    level: passed ? "success" : "warning",
    progressEntry: entry(eventType, "检查交付物", {
      body,
      level: passed ? "success" : "warning",
      kind: "verification",
      statusText: passed ? "通过" : "有缺口",
      runId: meta.runId,
      taskRunId: meta.taskRunId,
      eventId: meta.eventId,
      createdAt: meta.createdAt,
    }),
  };
}

function toolNameFromActionRequest(payload: Record<string, unknown>) {
  const actionRequest = record(payload.action_request);
  const requestPayload = record(actionRequest.payload);
  const toolCall = record(requestPayload.tool_call);
  return text(
    payload.tool_name
    ?? requestPayload.tool_name
    ?? toolCall.tool_name
    ?? toolCall.name
    ?? payload.tool
  );
}

function toolNameFromObservation(payload: Record<string, unknown>) {
  const observation = record(payload.observation);
  const observationPayload = record(observation.payload);
  return text(
    payload.tool_name
    ?? observationPayload.tool_name
    ?? observation.source
  ).replace(/^tool:/, "");
}

function toolResultArtifacts(payload: Record<string, unknown>) {
  const observation = record(payload.observation);
  const observationPayload = record(observation.payload);
  return [
    ...artifactsFromPaths(arrayText(observationPayload.observed_paths, 6)),
    ...artifactsFromPaths(arrayText(observationPayload.matched_paths, 6)),
    ...artifactsFromMixed(observationPayload.artifact_refs),
  ].slice(0, 6);
}

function toolRequestProjection(eventType: string, payload: Record<string, unknown>, eventMeta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const actionRequest = record(payload.action_request);
  const requestPayload = record(actionRequest.payload);
  const toolCall = record(requestPayload.tool_call);
  const toolName = toolNameFromActionRequest(payload) || "工具";
  const preview = commandPreviewFromToolCall(toolCall, requestPayload.command ?? requestPayload.path ?? requestPayload.query);
  const activity = toolActivityText(toolName, preview);
  const body = short(
    preview
    || text(requestPayload.command_preview)
    || text(requestPayload.assistant_content_preview)
    || short(toolCall.args)
    || text(actionRequest.request_type)
    || "已发起工具请求",
  );
  return {
    stageStatus: `${activity.startedTitle} ${activity.display}`,
    activityTitle: activity.startedTitle,
    activityDetail: activity.display,
    level: "running",
    progressEntry: entry(eventType, `${activity.startedTitle} ${activity.display}`, {
      body,
      kind: "tool",
      statusText: activity.statusRunning,
      toolName,
      runId: eventMeta.runId,
      taskRunId: eventMeta.taskRunId,
      eventId: eventMeta.eventId,
      createdAt: eventMeta.createdAt,
      startedAt: eventMeta.createdAt,
      meta: compactMeta([
        metaItem("工具", toolName),
        preview ? metaItem("目标", preview) : null,
      ]),
    }),
  };
}

function toolResultProjection(eventType: string, payload: Record<string, unknown>, eventMeta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const observation = record(payload.observation);
  const observationPayload = record(observation.payload);
  const toolName = toolNameFromObservation(payload) || "工具";
  const toolArgs = record(observationPayload.tool_args);
  const preview = commandPreviewFromArgs(toolArgs);
  const activity = toolActivityText(toolName, preview);
  const resultChars = numberValue(observationPayload.result_chars ?? observation.content_chars);
  const truncated = observationPayload.truncated === true;
  const failed = text(observationPayload.error) || text(record(observationPayload.execution_receipt).error);
  const resultText = short(
    observationPayload.result
    ?? observationPayload.error
    ?? observation.source
    ?? "工具结果已写入运行上下文",
  );
  return {
    stageStatus: "整理工具结果",
    activityTitle: failed ? activity.failedTitle : activity.completedTitle,
    activityDetail: preview || resultText,
    level: failed ? "error" : "running",
    progressEntry: entry(eventType, failed ? `${activity.failedTitle} ${activity.display}` : `${activity.completedTitle} ${activity.display}`, {
      body: resultText,
      kind: "tool",
      level: failed ? "error" : "running",
      statusText: failed ? activity.statusFailed : truncated ? "已截断" : activity.statusDone,
      toolName,
      runId: eventMeta.runId,
      taskRunId: eventMeta.taskRunId,
      eventId: eventMeta.eventId,
      createdAt: eventMeta.createdAt,
      completedAt: eventMeta.createdAt,
      meta: compactMeta([
        metaItem("工具", toolName),
        preview ? metaItem("目标", preview) : null,
        metaItem("结果字符", resultChars),
      ]),
      artifacts: toolResultArtifacts(payload),
    }),
  };
}

function operationGateProjection(eventType: string, payload: Record<string, unknown>, eventMeta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const gate = record(payload.gate);
  const allowed = gate.allowed === true;
  const requiresApproval = gate.requires_approval === true || text(gate.decision).includes("approval");
  const level: SessionActivityLevel = requiresApproval ? "waiting" : allowed ? "running" : "warning";
  const title = requiresApproval ? "等待确认" : "权限已检查";
  const detail = requiresApproval ? "需要你确认后才能继续执行。" : (allowed ? "当前操作已通过权限检查。" : "当前执行受限。");
  return {
    stageStatus: title,
    activityTitle: title,
    activityDetail: detail,
    level,
    progressEntry: requiresApproval
      ? entry(eventType, "等待确认", {
          body: detail,
          level,
          kind: "stage",
          statusText: "等待",
          runId: eventMeta.runId,
      taskRunId: eventMeta.taskRunId,
          eventId: eventMeta.eventId,
          createdAt: eventMeta.createdAt,
        })
      : undefined,
  };
}

function loopTerminalProjection(eventType: string, payload: Record<string, unknown>, eventMeta: ReturnType<typeof runtimeEvent>): RuntimeVisibilityProjection {
  const status = text(payload.status) || "completed";
  const terminalReason = publicRuntimeText(payload.terminal_reason || "completed");
  const title = status === "completed" ? "处理完成" : "处理结束";
  return {
    stageStatus: status === "completed" ? "完成" : "结束",
    activityTitle: title,
    activityDetail: terminalReason,
    level: status === "completed" ? "success" : "warning",
    progressEntry: entry(eventType, title, {
      body: terminalReason,
      level: status === "completed" ? "success" : "warning",
      kind: "terminal",
      statusText: status,
      runId: eventMeta.runId,
      taskRunId: eventMeta.taskRunId,
      eventId: eventMeta.eventId,
      createdAt: eventMeta.createdAt,
      completedAt: eventMeta.createdAt,
      meta: compactMeta([
        metaItem("状态", status),
        metaItem("结果", record(payload.task_result).result_id, { shorten: true }),
      ]),
    }),
  };
}

export function projectHarnessLoopEvent(data: Record<string, unknown>): RuntimeVisibilityProjection {
  const meta = runtimeEvent(data);
  const eventType = meta.eventType;
  const payload = meta.payload;
  if (!eventType) return {};
  if (eventType === "agent_runtime_planning_phase_checked") {
    return planningPhaseProjection(eventType, payload, meta);
  }
  if (eventType === "agent_runtime_closeout_phase_checked") {
    return verificationProjection(eventType, payload, meta);
  }
  if (eventType === "tool_call_requested") {
    return toolRequestProjection(eventType, payload, meta);
  }
  if (eventType === "tool_result_received") {
    return toolResultProjection(eventType, payload, meta);
  }
  if (eventType === "operation_gate_checked") {
    return operationGateProjection(eventType, payload, meta);
  }
  if (eventType === "loop_terminal") {
    return loopTerminalProjection(eventType, payload, meta);
  }
  const simple: Record<string, { title: string; level?: SessionActivityLevel; body?: string; kind?: RuntimeProgressEntry["kind"]; statusText?: string }> = {
    runtime_directive_issued: { title: "指令已下发", kind: "stage", statusText: "已下发" },
    approval_waiting: { title: "等待确认", level: "waiting", kind: "stage", statusText: "等待" },
    recovery_attempted: { title: "尝试纠错", level: "warning" },
    loop_error: { title: "运行出错", level: "error", body: text(payload.error), kind: "terminal", statusText: "失败" },
  };
  const projected = simple[eventType];
  if (!projected) return {};
  const shouldShowProgress = eventType.startsWith("agent_runtime_")
    || eventType === "recovery_attempted"
    || eventType === "approval_waiting"
    || eventType === "loop_error";
  return {
    stageStatus: projected.title,
    activityTitle: projected.title,
    activityDetail: short(projected.body || projected.title),
    level: projected.level || "running",
    progressEntry: shouldShowProgress
      ? entry(eventType, projected.title, {
          body: projected.body,
          level: projected.level || "running",
          kind: projected.kind || (eventType.startsWith("agent_runtime_") ? "stage" : "system"),
          statusText: projected.statusText || (projected.level === "success" ? "完成" : projected.level === "waiting" ? "等待" : "进行中"),
          runId: meta.runId,
      taskRunId: meta.taskRunId,
          eventId: meta.eventId,
          createdAt: meta.createdAt,
          completedAt: (projected.level === "success" || projected.level === "error") ? meta.createdAt : undefined,
        })
      : undefined,
  };
}

export function projectRuntimeStreamEvent(event: string, data: Record<string, unknown>): RuntimeVisibilityProjection {
  if (event === "stream_reconnecting") {
    const attempt = text(data.attempt);
    const maxAttempts = text(data.max_attempts);
    const suffix = attempt && maxAttempts ? ` ${attempt}/${maxAttempts}` : "";
    return {
      stageStatus: `重新连接中${suffix}`,
      activityTitle: `重新连接中${suffix}`,
      activityDetail: "连接中断，正在续接当前运行。",
      level: "running",
    };
  }
  if (event === "stream_reconnected") {
    return {
      stageStatus: "已重新连接",
      activityTitle: "已重新连接",
      activityDetail: "已从上次位置继续接收事件。",
      level: "running",
    };
  }
  if (event === "stream_reconnect_failed") {
    return {
      stageStatus: "重连失败",
      activityTitle: "重连失败",
      activityDetail: "自动重连次数已用尽，后台运行可在监控中查看。",
      level: "error",
    };
  }
  if (event === "harness_run_started") {
    const taskRun = record(data.task_run);
    const turnRun = record(data.turn_run);
    const runtimeEvent = record(data.event);
    const payload = record(runtimeEvent.payload);
    const contract = record(payload.contract);
    const goal = text(contract.user_visible_goal ?? contract.task_run_goal ?? taskRun.goal ?? taskRun.title);
    const runtimeRunId = text(runtimeEvent.run_id) || text(runtimeEvent.task_run_id);
    const taskRunId = formalTaskRunId(taskRun.task_run_id, runtimeRunId);
    if (!taskRunId || isChatTurnRunId(taskRunId) || text(turnRun.execution_runtime_kind) === "single_agent_turn" || text(taskRun.execution_runtime_kind) === "single_agent_turn") {
      return {};
    }
    return {
      stageStatus: "处理已开始",
      activityTitle: "处理已开始",
      activityDetail: publicRuntimeText(goal || text(taskRun.status) || "已进入处理队列"),
      level: "running",
      progressEntry: entry("harness_run_started", "处理已开始", {
        body: publicRuntimeText(goal || "已进入处理队列"),
        level: "running",
        kind: "task_order",
        statusText: text(taskRun.status) || "running",
        taskRunId,
        eventId: text(runtimeEvent.event_id),
        createdAt: numberValue(runtimeEvent.created_at ?? taskRun.created_at) ?? Date.now(),
        meta: compactMeta([
          goal ? metaItem("目标", goal) : null,
        ]),
      }),
    };
  }
  if (event === "active_task_steer_accepted") {
    const summary = publicRuntimeText(data.summary) || "当前任务会在后续步骤中处理这次输入。";
    return {
      stageStatus: "已收到补充要求",
      activityTitle: "已收到补充要求",
      activityDetail: summary,
      level: "success",
      progressEntry: entry("active_task_steer_accepted", "已收到补充要求", {
        body: summary,
        publicNote: summary,
        level: "success",
        kind: "stage",
        statusText: "已接收",
        eventId: text(data.runtime_event_id),
        createdAt: Date.now(),
      }),
    };
  }
  if (event === "runtime_step_summary") {
    const step = text(data.step);
    const eventPayload = record(record(data.event).payload);
    const explicitPublicNote = publicRuntimeText(
      data.public_progress_note
      ?? data.publicProgressNote
      ?? eventPayload.public_progress_note
      ?? "",
    );
    if (INTERNAL_RUNTIME_STEPS.has(step) && !explicitPublicNote) {
      return {};
    }
    const status = text(data.status);
    const summary = publicRuntimeText(data.summary);
    const publicNote = publicRuntimeText(
      data.public_progress_note
      ?? data.publicProgressNote
      ?? eventPayload.public_progress_note
      ?? summary,
    );
    const agentBrief = publicRuntimeText(
      data.agent_brief_output
      ?? data.agentBrief
      ?? eventPayload.agent_brief_output
      ?? "",
    );
    const runtimeEvent = record(data.event);
    const runId = text(runtimeEvent.run_id) || text(runtimeEvent.task_run_id);
    const level: SessionActivityLevel = status === "completed" ? "success" : status === "failed" ? "error" : status === "waiting" ? "waiting" : "running";
    return {
      stageStatus: publicNote || summary || step || "运行步骤",
      activityTitle: publicNote || summary || step || "运行步骤",
      activityDetail: publicNote || summary,
      level,
      progressEntry: entry("runtime_step_summary", publicNote || summary || step || "运行步骤", {
        body: publicNote || summary,
        publicNote,
        agentBrief,
        level,
        kind: "stage",
        statusText: status || "进行中",
        runId,
        taskRunId: formalTaskRunId(runId),
        eventId: text(record(data.event).event_id),
        createdAt: numberValue(record(data.event).created_at) ?? Date.now(),
      }),
    };
  }
  if (event === "task_run_lifecycle_started") {
    const runtimeEvent = record(data.event);
    const payload = record(runtimeEvent.payload);
    const taskRun = record(payload.task_run);
    const contract = record(payload.contract);
    const goal = text(contract.user_visible_goal ?? contract.task_run_goal);
    return {
      stageStatus: "处理已开始",
      activityTitle: "处理已开始",
      activityDetail: publicRuntimeText(goal),
      level: "running",
      progressEntry: entry("task_run_lifecycle_started", "处理已开始", {
        body: publicRuntimeText(goal),
        level: "running",
        kind: "task_order",
        statusText: "进行中",
        runId: text(runtimeEvent.run_id) || text(runtimeEvent.task_run_id),
        taskRunId: text(taskRun.task_run_id),
        eventId: text(runtimeEvent.event_id),
        createdAt: numberValue(runtimeEvent.created_at) ?? Date.now(),
        meta: compactMeta([
          metaItem("目标", goal),
        ]),
      }),
    };
  }
  if (event === "task_run_lifecycle_event") {
    const runtimeEvent = record(data.event);
    const eventType = text(runtimeEvent.event_type);
    const payload = record(runtimeEvent.payload);
    const taskRun = record(payload.task_run);
    const observation = record(payload.observation);
    const source = text(observation.source);
    const status = text(taskRun.status);
    const waiting = eventType === "task_run_lifecycle_waiting_executor" || status === "waiting_executor";
    const title = eventType === "agent_todo_initialized"
      ? "处理清单已建立"
      : waiting
        ? "等待继续"
        : "处理进展更新";
    const body = publicRuntimeText(text(observation.summary) || text(payload.reason) || status || eventType);
    return {
      stageStatus: title,
      activityTitle: title,
      activityDetail: body,
      level: waiting ? "waiting" : "running",
      progressEntry: entry(eventType || "task_run_lifecycle_event", title, {
        body,
        level: waiting ? "waiting" : "running",
        kind: eventType === "agent_todo_initialized" ? "stage" : "terminal",
        statusText: waiting ? "等待" : status || "进行中",
        runId: text(runtimeEvent.run_id) || text(runtimeEvent.task_run_id),
        taskRunId: text(taskRun.task_run_id) || formalTaskRunId(runtimeEvent.run_id, runtimeEvent.task_run_id),
        eventId: text(runtimeEvent.event_id),
        createdAt: numberValue(runtimeEvent.created_at) ?? Date.now(),
        meta: compactMeta([
          metaItem("来源", source),
          metaItem("状态", status),
        ]),
      }),
    };
  }
  if (event === "agent_turn_terminal") {
    const runtimeEvent = record(data.event);
    const runtimeEventType = text(runtimeEvent.event_type);
    const payload = record(runtimeEvent.payload);
    const status = text(payload.status);
    const reason = text(payload.terminal_reason);
    const taskRun = record(payload.task_run);
    const taskRunStatus = text(taskRun.status);
    const waiting = status === "task_lifecycle_waiting_executor"
      || status === "task_executor_scheduled"
      || reason === "waiting_executor"
      || reason === "task_executor_scheduled"
      || taskRunStatus === "waiting_executor";
    const failed = runtimeEventType === "agent_turn_failed"
      || runtimeEventType === "agent_turn_blocked"
      || status === "failed"
      || status === "blocked"
      || terminalReasonIndicatesFailure(reason)
      || taskRunStatus === "failed"
      || taskRunStatus === "blocked";
    const title = waiting ? "继续在后台处理" : failed ? "处理失败" : "本轮完成";
    const publicReason = publicRuntimeText(reason || status);
    const handoffBody = "任务已切到后台继续执行。";
    const runId = text(runtimeEvent.run_id) || text(runtimeEvent.task_run_id);
    const taskRunId = text(taskRun.task_run_id) || formalTaskRunId(runId, runtimeEvent.task_run_id);
    return {
      stageStatus: title,
      activityTitle: title,
      activityDetail: waiting ? handoffBody : failed ? "详情已写入会话。" : publicReason,
      level: waiting ? "waiting" : failed ? "error" : "success",
      progressEntry: waiting
        ? entry("agent_turn_terminal", title, {
            body: handoffBody,
            level: "waiting",
            kind: "stage",
            statusText: "等待",
            runId,
            taskRunId,
            eventId: text(runtimeEvent.event_id),
            createdAt: numberValue(runtimeEvent.created_at) ?? Date.now(),
          })
        : undefined,
    };
  }
  if (event === "task_order_draft") {
    const draft = record(data.draft);
    const missing = arrayText(draft.missing_fields, 8);
    return {
      stageStatus: "等待确认",
      activityTitle: "需要确认",
      activityDetail: missing.length ? `缺少：${missing.join("、")}` : "需要补充信息",
      level: "waiting",
      progressEntry: entry("task_order_draft", "需要确认", {
        body: missing.length ? `缺少：${missing.join("、")}` : "需要补充信息",
        level: "waiting",
        kind: "task_draft",
        statusText: "待确认",
        eventId: text(draft.draft_id),
        createdAt: numberValue(draft.updated_at ?? draft.created_at),
        meta: compactMeta([
          metaItem("草稿", draft.draft_id, { shorten: true }),
          metaItem("缺少字段", missing.length),
        ]),
      }),
    };
  }
  if (event === "harness_loop_event") {
    return projectHarnessLoopEvent(data);
  }
  if (event === "done") {
    if (isTaskRunHandoffEvent(data)) {
      return {
        stageStatus: "后台任务已接管",
        activityTitle: "后台任务已接管",
        activityDetail: "当前会话已有后台任务在执行，后续输入会进入当前任务控制。",
        level: "waiting",
        terminalEvent: "done",
      };
    }
    const completionState = text(data.completion_state);
    if (completionState === "task_steer_accepted") {
      const summary = publicRuntimeText(data.summary ?? data.content) || "当前任务会在后续步骤中处理这次输入。";
      return {
        stageStatus: "已收到补充要求",
        activityTitle: "已收到补充要求",
        activityDetail: summary,
        level: "success",
        terminalEvent: "done",
      };
    }
    const partialTimeout = completionState === "partial_timeout";
    return {
      stageStatus: partialTimeout ? "部分完成" : "完成",
      activityTitle: partialTimeout ? "已生成部分内容" : "完成",
      activityDetail: partialTimeout ? "模型结束信号超时，当前内容已保留。" : "",
      level: partialTimeout ? "warning" : "success",
      terminalEvent: "done",
    };
  }
  if (event === "error") {
    const errorText = text(data.content ?? data.error) || "请求执行失败";
    return {
      stageStatus: "出错",
      activityTitle: "处理失败",
      activityDetail: "详情已写入会话。",
      level: "error",
      terminalEvent: "error",
      progressEntry: entry("error", "处理失败", {
        body: errorText,
        level: "error",
        kind: "terminal",
        statusText: "失败",
        createdAt: Date.now(),
        completedAt: Date.now(),
      }),
    };
  }
  if (event === "stopped") {
    return {
      stageStatus: "已停止",
      activityTitle: "已停止本轮生成",
      activityDetail: "这轮生成已停止",
      level: "stopped",
      terminalEvent: "stopped",
      progressEntry: entry("stopped", "已停止本轮生成", {
        body: "这轮生成已停止",
        level: "stopped",
        kind: "terminal",
        statusText: "已停止",
        createdAt: Date.now(),
        completedAt: Date.now(),
      }),
    };
  }
  if (event === "retrieval") {
    const results = Array.isArray(data.results) ? data.results.length : 0;
    return { stageStatus: "检索证据", activityTitle: results ? `已检索到 ${results} 条候选证据` : "正在检索可用证据", level: "running" };
  }
  if (event === "output_boundary") {
    return { stageStatus: "整理输出", activityTitle: "整理输出", level: "running" };
  }
  return {};
}

