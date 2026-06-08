import {
  taskGraphRunIdsFromTrace,
  type PublicChatTimelineItem,
  type OrchestrationEdge,
  type OrchestrationNode,
  type OrchestrationSnapshot,
  type RetrievalResult,
  type HarnessTaskRunTrace,
  type SessionRuntimeAttachment,
  type SingleAgentTaskProjection,
} from "@/lib/api";
import { projectRuntimeStreamEvent, type RuntimeVisibilityProjection } from "../runtimeVisibilityProjection";
import { shouldDisplayAssistantStreamContent } from "./assistantContentVisibility";

import type { Message, RuntimeProgressEntry, StoreState, UserReceipt } from "./types";
import {
  looksLikeSkillDocument,
  looksLikeSkillDocumentPrefix,
  makeId
} from "./utils";
import { mergePublicTimelineItems, publicTimelineTerminalStateFromEvent, sanitizePublicTimelineItems } from "./publicTimeline";

export type StreamSession = {
  assistantId: string;
  userId?: string;
  queueOnly?: boolean;
};

type StreamTransition = {
  state: StoreState;
  session: StreamSession;
};

const MAX_MESSAGE_PROGRESS_ENTRIES = 12;
const MAX_PROGRESS_BODY_CHARS = 360;
const MAX_PROGRESS_ARTIFACTS = 6;
const INTERNAL_STREAM_EVENTS = new Set([
  "runtime_assembly_compiled",
  "runtime_invocation_packet",
]);
const INTERNAL_RUNTIME_STEP_SUMMARIES = new Set([
  "turn_started",
  "runtime_packet_compiled",
  "model_action_received",
  "action_admission_checked",
  "bounded_observation_recorded",
]);

const ORCHESTRATION_NODES: Array<{ id: string; label: string; description: string }> = [
  { id: "input", label: "用户输入", description: "接收本轮用户请求，并绑定当前会话。" },
  { id: "runtime", label: "运行时装配", description: "装配当前 agent、环境、权限、工具和上下文边界。" },
  { id: "agent-turn", label: "模型行动", description: "模型输出回复或发起结构化行动请求。" },
  { id: "task-lifecycle", label: "任务生命周期", description: "需要长任务时创建合同、待办、验收要求和执行记录。" },
  { id: "context", label: "上下文压缩", description: "整理历史窗口和上下文压力。" },
  { id: "memory", label: "记忆与状态", description: "读取当前会话、任务状态、观察记录和必要记忆。" },
  { id: "prompt", label: "Prompt 装配", description: "组合身份、准则、记忆、skill 和本轮提示。" },
  { id: "model", label: "模型行动", description: "模型生成回复或发出结构化行动请求。" },
  { id: "tool", label: "工具与观察", description: "执行获准工具调用并记录观察、失败和产物。" },
  { id: "output", label: "结果收口", description: "形成用户可见回复、进度摘要或任务交接信息。" },
  { id: "persistence", label: "写回状态", description: "写回会话、运行事件、任务状态和产物引用。" }
];

const ORCHESTRATION_EDGES: Array<{ id: string; from: string; to: string; label: string }> = [
  { id: "input-runtime", from: "input", to: "runtime", label: "提交请求" },
  { id: "runtime-agent-turn", from: "runtime", to: "agent-turn", label: "进入 agent 判断" },
  { id: "agent-task-lifecycle", from: "agent-turn", to: "task-lifecycle", label: "需要长任务" },
  { id: "agent-context", from: "agent-turn", to: "context", label: "准备上下文" },
  { id: "task-context", from: "task-lifecycle", to: "context", label: "绑定任务状态" },
  { id: "context-memory", from: "context", to: "memory", label: "读取状态" },
  { id: "memory-prompt", from: "memory", to: "prompt", label: "注入上下文" },
  { id: "prompt-model", from: "prompt", to: "model", label: "模型行动" },
  { id: "model-tool", from: "model", to: "tool", label: "请求工具" },
  { id: "model-output", from: "model", to: "output", label: "候选答案" },
  { id: "tool-output", from: "tool", to: "output", label: "结果返回" },
  { id: "output-persistence", from: "output", to: "persistence", label: "落盘写回" }
];

function stoppedPublicTimelineItem(): PublicChatTimelineItem {
  return {
    item_id: "stream:stopped",
    kind: "status_update",
    title: "已停止本轮生成",
    detail: "你已停止本轮生成，当前运行不会继续推进。",
    text: "你已停止本轮生成，当前运行不会继续推进。",
    state: "stopped",
    phase: "stopped",
    stream_state: "done",
  };
}

function stageStatusForEvent(event: string, data: Record<string, unknown>) {
  if (INTERNAL_STREAM_EVENTS.has(event)) {
    return "";
  }
  if (event === "runtime_step_summary" && INTERNAL_RUNTIME_STEP_SUMMARIES.has(String(data.step ?? "").trim())) {
    return "";
  }
  if (event === "debug") {
    return "";
  }
  if (event === "stream_reconnecting") {
    const attempt = String(data.attempt ?? "").trim();
    const maxAttempts = String(data.max_attempts ?? "").trim();
    return attempt && maxAttempts ? `正在续接当前运行 ${attempt}/${maxAttempts}` : "正在续接当前运行";
  }
  if (event === "stream_reconnected") {
    return "已接回当前运行";
  }
  if (event === "stream_reconnect_failed") {
    return "需要重新接回会话";
  }
  if (event === "input_commit_gate") {
    return "接收请求";
  }
  if (
    event === "harness_loop_event"
    || event === "runtime_directive"
    || event === "operation_gate"
    || event === "runtime_commit_gate"
  ) {
    const eventType = String(data.event_type ?? ((data.event as Record<string, unknown> | undefined)?.event_type) ?? "");
    return stageStatusForRuntimeEvent(eventType);
  }
  if (event === "context_management") {
    return "整理上下文";
  }
  if (event === "memory_context") {
    return "读取记忆";
  }
  if (event === "prompt_manifest") {
    return "装配提示词";
  }
  if (event === "retrieval" || event.startsWith("worker")) {
    return "检索证据";
  }
  if (event === "token" || event === "content_delta" || event === "answer_candidate" || event === "assistant_text") {
    return "生成回答";
  }
  if (event === "output_boundary") {
    return "整理输出";
  }
  if (event === "done") {
    if (isTaskRunHandoffEvent(data)) {
      return "后台任务已接管";
    }
    if (stringValue(data.completion_state) === "partial_timeout") {
      return "部分完成";
    }
    return "完成";
  }
  if (event === "error") {
    return "出错";
  }
  return "";
}

function activityLevelForEvent(event: string, data: Record<string, unknown>) {
  if (event === "done") {
    if (isTaskRunHandoffEvent(data)) {
      return "waiting" as const;
    }
    if (stringValue(data.completion_state) === "partial_timeout") {
      return "warning" as const;
    }
    return "success" as const;
  }
  if (event === "error") {
    return "error" as const;
  }
  if (event === "stopped") {
    return "stopped" as const;
  }
  if (event === "stream_reconnect_failed") {
    return "warning" as const;
  }
  if (event === "operation_gate") {
    const eventType = String(data.event_type ?? ((data.event as Record<string, unknown> | undefined)?.event_type) ?? "");
    if (eventType.includes("approval") || eventType.includes("gate")) {
      return "waiting" as const;
    }
  }
  return "running" as const;
}

function activityDetailForEvent(event: string, data: Record<string, unknown>) {
  if (event === "retrieval") {
    const results = Array.isArray(data.results) ? data.results.length : 0;
    return results ? `已检索到 ${results} 条候选证据` : "正在检索可用证据";
  }
  if (event === "stream_reconnecting") {
    return "连接短暂中断，已保留当前进度。";
  }
  if (event === "stream_reconnected") {
    return "后续进度会继续在这里同步。";
  }
  if (event === "stream_reconnect_failed") {
    return "自动续接没有成功，刷新或重新打开会话会继续查找可接回的运行。";
  }
  if (event === "active_task_steer_accepted") {
    return stringValue(data.summary) || "已收到你的补充要求。";
  }
  if (event === "done") {
    if (isTaskRunHandoffEvent(data)) {
      return "当前会话已有后台任务在执行，后续输入会进入当前任务控制。";
    }
    if (stringValue(data.completion_state) === "task_steer_accepted") {
      return stringValue(data.summary) || "当前任务已继续接收这次输入。";
    }
    if (stringValue(data.completion_state) === "partial_timeout") {
      return "模型已生成部分内容，但结束信号超时。";
    }
    return "回答已生成并写回会话";
  }
  if (event === "error") {
    return "详情已写入会话。";
  }
  if (event === "stopped") {
    return "已按你的操作停止本轮生成";
  }
  const summary = eventSummary(event, data);
  return summary === event ? "" : summary;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function stringArrayValue(value: unknown) {
  if (!Array.isArray(value)) return undefined;
  const values = value.map((item) => String(item ?? "").trim()).filter(Boolean);
  return values.length ? values : undefined;
}

function isTaskRunHandoffEvent(data: Record<string, unknown>) {
  const taskRunId = stringValue(
    data.runtime_task_run_id
    ?? recordValue(data.task_run).task_run_id,
  );
  if (!taskRunId) {
    return false;
  }
  const reason = stringValue(data.terminal_reason);
  const channel = stringValue(data.answer_channel);
  return reason === "task_executor_scheduled"
    || channel === "task_control";
}

function answerMetadataFromEvent(data: Record<string, unknown>): Partial<Message> {
  return {
    answerChannel: stringValue(data.answer_channel) || undefined,
    answerSource: stringValue(data.answer_source) || undefined,
    answerCanonicalState: stringValue(data.answer_canonical_state) || undefined,
    answerPersistPolicy: stringValue(data.answer_persist_policy) || undefined,
    answerFinalizationPolicy: stringValue(data.answer_finalization_policy) || undefined,
    answerFallbackReason: stringValue(data.answer_fallback_reason) || undefined,
    answerSelectedChannel: stringValue(data.answer_selected_channel) || undefined,
    answerSelectedSource: stringValue(data.answer_selected_source) || undefined,
    answerLeakFlags: stringArrayValue(data.answer_leak_flags),
  };
}

function shouldKeepStreamAssistantText(event: string, data: Record<string, unknown>) {
  const metadata = answerMetadataFromEvent(data);
  if (shouldDisplayAssistantStreamContent(metadata)) {
    return true;
  }
  if (event !== "assistant_text") {
    return false;
  }
  return stringValue(metadata.answerChannel) === "task_control"
    && stringValue(metadata.answerSource) === "harness.single_agent_turn.request_task_run";
}

function assistantDoneContentFromEvent(data: Record<string, unknown>) {
  const content = stringValue(data.content);
  if (content && !isMachineReference(content) && !isRawToolOutputText(content)) {
    return content;
  }
  const completionState = stringValue(data.completion_state);
  if (completionState === "task_steer_accepted") {
    return stringValue(data.summary ?? data.message) || "已加入当前任务队列。";
  }
  if (isTaskRunHandoffEvent(data)) {
    return "";
  }
  const candidates = [
    data.final_answer,
    data.answer,
    data.summary,
    data.receipt_summary,
    data.message,
  ];
  for (const candidate of candidates) {
    const text = stringValue(candidate);
    if (text && !isMachineReference(text) && !isRawToolOutputText(text) && !isRoutineDoneContent(text)) {
      return text;
    }
  }
  return "";
}

function isRoutineDoneContent(value: string) {
  const text = value.trim().toLowerCase();
  return [
    "done",
    "completed",
    "success",
    "回答已生成并写回会话",
    "会话输出完成",
    "工具调用已完成，正在根据结果继续。",
  ].includes(text);
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function isMachineReference(value: string) {
  const normalized = value.trim();
  return /^(taskrun|taskinst|turn|run|rtchk|runtime|event)[:_-]/i.test(normalized)
    || /(?:^|\s)(?:harness|backend|runtime|query|agent_system|capability_system|health_system|task_system)(?:\.[A-Za-z0-9_-]+){2,}(?:\s|$)/i.test(normalized)
    || /\b(?:RuntimeInvocationPacket|runtime packet|answer_source|task_run_id|event_id)\b/i.test(normalized)
    || isRawToolOutputText(normalized);
}

function isRawToolOutputText(value: string) {
  const text = stringValue(value);
  if (!text) return false;
  return /\bfile\s+[^\s]+\s+\d+\s+bytes\b/i.test(text)
    || /\bCopied:\s+\S+/i.test(text)
    || /Read persisted tool result failed|persisted tool result read failed/i.test(text)
    || /(?:runtime_context|runtime[-_ ]context)[\\/]+tool-results/i.test(text)
    || /tool-results[\\/]+session[-_A-Za-z0-9]+/i.test(text)
    || /\b(?:not allowlisted read-only|read-only validator|unsupported read-only)\b/i.test(text)
    || /\b\d+\s+bytes\s+(?:file|directory|dir)\b/i.test(text)
    || /\b(?:Exit code|Wall time|Output):/i.test(text)
    || /\b(?:authority|diagnostics|matched_version_count|candidate_version_count|result_envelope|structured_payload)\b/i.test(text)
    || ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")));
}

function extractArtifactPaths(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return stringValue(record.path ?? record.file ?? record.file_path ?? record.artifact_path);
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, 5);
}

function userReceiptForEvent(event: string, data: Record<string, unknown>): UserReceipt | null {
  if (event === "retrieval") {
    const results = Array.isArray(data.results) ? data.results.length : 0;
    return {
      level: "running",
      title: results ? `已检索到 ${results} 条候选证据` : "正在检索可用证据",
      body: "检索结果会用于本轮回答。",
      debug: { event },
    };
  }
  if (event === "done") {
    const paths = extractArtifactPaths(data.files ?? data.paths ?? data.artifacts ?? data.artifact_refs);
    const answerSource = stringValue(data.answer_source);
    const body = stringValue(data.receipt_summary ?? data.summary ?? data.message);
    const partialTimeout = stringValue(data.completion_state) === "partial_timeout";
    const taskSteerAccepted = stringValue(data.completion_state) === "task_steer_accepted";
    const taskRunHandoff = isTaskRunHandoffEvent(data);
    return {
      level: taskRunHandoff ? "waiting" : partialTimeout ? "warning" : "success",
      title: taskRunHandoff ? "后台任务已接管" : taskSteerAccepted ? "已收到补充要求" : partialTimeout ? "已生成部分内容" : paths.length ? `已更新 ${paths.length} 个文件` : "已处理 1 个命令",
      body: taskRunHandoff
        ? "当前会话已有后台任务在执行，后续输入会进入当前任务控制。"
        : taskSteerAccepted
        ? body && !isMachineReference(body) ? body : "当前任务会在后续步骤中处理这次输入。"
        : partialTimeout ? "模型结束信号超时，当前内容已保留。" : body && !isMachineReference(body) ? body : "结果已写回会话。",
      artifacts: paths.map((path) => ({ label: "文件已更新", path })),
      debug: {
        event,
        ...(answerSource ? { answerSource } : {}),
      },
    };
  }
  if (event === "error") {
    return {
      level: "error",
      title: "处理失败",
      body: "详情已写入会话。",
      debug: { event },
    };
  }
  if (event === "stopped") {
    return {
      level: "stopped",
      title: "已停止本轮生成",
      body: "这轮生成已停止。",
      debug: { event },
    };
  }
  const title = stageStatusForEvent(event, data);
  if (!title) return null;
  const detail = activityDetailForEvent(event, data);
  return {
    level: activityLevelForEvent(event, data),
    title,
    body: detail && !isMachineReference(detail) ? detail : undefined,
    debug: { event },
  };
}

function patchSessionActivity(
  state: StoreState,
  event: string,
  data: Record<string, unknown>,
  fallbackTitle = ""
): StoreState {
  const title = stageStatusForEvent(event, data) || fallbackTitle;
  if (!title) {
    return state;
  }
  return {
    ...state,
    sessionActivity: {
      level: activityLevelForEvent(event, data),
      title,
      detail: activityDetailForEvent(event, data),
      event,
      toolName: event.startsWith("tool") ? String(data.tool ?? "").trim() || undefined : undefined,
      receipt: userReceiptForEvent(event, data),
      updatedAt: Date.now()
    }
  };
}

function stageStatusForRuntimeEvent(eventType: string) {
  if (!eventType) {
    return "";
  }
  if (eventType === "task_contract_built") {
    return "理解任务";
  }
  if (eventType === "memory_runtime_view_built") {
    return "读取记忆";
  }
  if (eventType === "stage_projection_built") {
    return "选择投影";
  }
  if (eventType === "context_snapshot_built" || eventType === "context_invariant_checked") {
    return "整理上下文";
  }
  if (eventType === "runtime_directive_issued" || eventType === "operation_gate_checked") {
    return "权限已检查";
  }
  if (eventType === "executor_started" || eventType === "executor_observation_received") {
    return "生成回答";
  }
  if (eventType === "output_boundary_applied") {
    return "整理输出";
  }
  if (eventType === "commit_gate_checked" || eventType === "checkpoint_written") {
    return "写入状态";
  }
  if (eventType === "loop_terminal") {
    return "完成";
  }
  return "";
}

function makeOrchestrationSnapshot(state: StoreState, userContent: string): OrchestrationSnapshot {
  const nodes = ORCHESTRATION_NODES.map((node, index): OrchestrationNode => ({
    ...node,
    index: index + 1,
    status: node.id === "input" ? "success" : "idle",
    summary: node.id === "input" ? userContent.trim() : "",
    source_event: node.id === "input" ? "user_message" : ""
  }));
  return {
    source: "live-session",
    session_id: state.currentSessionId ?? "",
    execution_mode: "running",
    route: "pending",
    status: "running",
    summary: "当前请求正在进入编排链路。",
    problem_node_id: "",
    nodes,
    edges: deriveOrchestrationEdges(nodes),
    events: []
  };
}

function deriveOrchestrationEdges(nodes: OrchestrationNode[]): OrchestrationEdge[] {
  const statusById = new Map(nodes.map((node) => [node.id, node.status]));
  return ORCHESTRATION_EDGES.map((edge) => {
    const from = statusById.get(edge.from) ?? "idle";
    const to = statusById.get(edge.to) ?? "idle";
    const status = from === "failed" || to === "failed"
      ? "failed"
      : from === "warning" || to === "warning"
        ? "warning"
        : from !== "idle" && to !== "idle"
          ? "success"
          : "idle";
    return { ...edge, status, summary: edge.label };
  });
}

function normalizeSnapshotEdges(snapshot: OrchestrationSnapshot): OrchestrationSnapshot {
  return {
    ...snapshot,
    edges: snapshot.edges?.length ? snapshot.edges : deriveOrchestrationEdges(snapshot.nodes)
  };
}

function eventNodeId(event: string) {
  if (event === "orchestration_plan") {
    return "task-lifecycle";
  }
  if (event === "orchestration_diff") {
    return "output";
  }
  if (event === "orchestration_runtime_control") {
    return "agent-turn";
  }
  if (event === "active_task_steer_accepted") {
    return "task-lifecycle";
  }
  if (event === "behavior_trace") {
    return "agent-turn";
  }
  if (event === "context_management") {
    return "context";
  }
  if (event === "memory_context") {
    return "memory";
  }
  if (event === "prompt_manifest") {
    return "prompt";
  }
  if (event.startsWith("worker") || event === "retrieval") {
    return "tool";
  }
  if (event.startsWith("tool")) {
    return "tool";
  }
  if (event === "token" || event === "content_delta" || event === "answer_candidate" || event === "assistant_text" || event === "debug") {
    return "model";
  }
  if (event === "done" || event === "error") {
    return "output";
  }
  if (event === "runtime_branch_decided" || event === "single_agent_turn_started") {
    return "agent-turn";
  }
  if (event === "task_run_lifecycle_started" || event === "task_run_lifecycle_event") {
    return "task-lifecycle";
  }
  if (event === "runtime_assembly_compiled") {
    return "runtime";
  }
  return "agent-turn";
}

function resolveSnapshotNodeId(snapshot: OrchestrationSnapshot, event: string) {
  const preferred = eventNodeId(event);
  if (snapshot.nodes.some((node) => node.id === preferred)) {
    return preferred;
  }
  const fallbackByEvent: Record<string, string> = {
    context_management: "context",
    memory_context: "context",
    prompt_manifest: "prompt",
    token: "model",
    debug: "model",
    done: "output",
    error: "output",
    worker_start: "tool",
    worker_end: "tool"
  };
  const fallback = fallbackByEvent[event] ?? "agent-turn";
  if (snapshot.nodes.some((node) => node.id === fallback)) {
    return fallback;
  }
  return snapshot.nodes[0]?.id ?? preferred;
}

function eventSummary(event: string, data: Record<string, unknown>) {
  if (event === "orchestration_plan") {
    return "已形成处理计划。";
  }
  if (event === "orchestration_runtime_control") {
    const warnings = Array.isArray(data.warnings) ? data.warnings.map((item) => String(item)) : [];
    const reason = warnings.map(runtimeControlWarningLabel).filter(Boolean)[0];
    if (reason) {
      return `当前处理遇到边界：${reason}`;
    }
    if (data.primary_active) {
      return "处理流程已接管后续执行。";
    }
    return "处理流程已更新。";
  }
  if (event === "orchestration_diff") {
    return "处理计划已更新。";
  }
  if (event === "behavior_trace") {
    const snapshot = (data.snapshot ?? {}) as Record<string, unknown>;
    return String(snapshot.summary ?? "行为决策 trace 已生成。");
  }
  if (event === "done") {
    if (stringValue(data.completion_state) === "task_steer_accepted") {
      const summary = stringValue(data.summary ?? data.message);
      return summary && !isMachineReference(summary) ? summary.slice(0, 220) : "已收到补充要求";
    }
    const summary = stringValue(data.receipt_summary ?? data.summary ?? data.message ?? data.content);
    return summary && !isMachineReference(summary) ? summary.slice(0, 220) : "完成输出";
  }
  if (event === "error") {
    return String(data.error ?? "执行失败");
  }
  if (event === "prompt_manifest") {
    return "上下文已整理。";
  }
  if (event.startsWith("worker")) {
    return String(data.worker ?? data.task_status ?? "worker");
  }
  if (event.startsWith("tool")) {
    return String(data.tool ?? "tool");
  }
  if (event === "memory_context") {
    return "状态记忆与长期记忆上下文已读取。";
  }
  if (event === "context_management") {
    return "上下文窗口已整理。";
  }
  return publicStreamEventLabel(event);
}

function publicStreamEventLabel(event: string) {
  const map: Record<string, string> = {
    answer_candidate: "正在整理回答",
    assistant_text: "正在整理回答",
    active_task_steer_accepted: "已收到补充要求",
    behavior_trace: "处理路径已检查",
    content_delta: "正在生成回答",
    context_management: "上下文已整理",
    debug: "同步状态",
    done: "处理完成",
    error: "处理失败",
    harness_loop_event: "处理进展更新",
    memory_context: "已读取相关记忆",
    orchestration_diff: "处理计划已更新",
    orchestration_plan: "已形成处理计划",
    orchestration_runtime_control: "处理流程已更新",
    output_boundary: "整理输出",
    prompt_manifest: "上下文已整理",
    retrieval: "检索证据",
    token: "正在生成回答",
    tool_call: "正在调用工具",
    tool_result: "工具结果已返回",
    worker_end: "子任务已完成",
    worker_start: "子任务已开始",
  };
  return map[event] || "处理进展更新";
}

function runtimeControlWarningLabel(warning: string) {
  if (warning === "validation_blocked") {
    return "编排校验未通过";
  }
  if (warning === "contract_incomplete") {
    return "正式编排契约不完整";
  }
  if (warning === "execution_directive_missing") {
    return "缺少执行指令";
  }
  if (warning === "execution_candidate_missing") {
    return "执行指令无法匹配候选执行";
  }
  return warning;
}

function runtimeEventToUiEvent(eventType: string) {
  if (eventType === "loop_terminal") return "done";
  if (eventType === "task_contract_built") return "orchestration_plan";
  if (eventType === "runtime_directive_issued" || eventType === "operation_gate_checked") return "harness_loop_event";
  if (eventType === "context_snapshot_built" || eventType === "context_invariant_checked") return "context_management";
  if (eventType === "memory_runtime_view_built") return "memory_context";
  if (eventType === "stage_projection_built") return "prompt_manifest";
  if (eventType === "tool_call_requested") return "harness_loop_event";
  if (eventType === "executor_observation_received" || eventType === "executor_started") return "token";
  if (eventType.startsWith("coordination_")) return "harness_loop_event";
  return "harness_loop_event";
}

function summarizeRuntimeEvent(eventType: string, data: Record<string, unknown>) {
  const stage = stageStatusForRuntimeEvent(eventType);
  if (stage) {
    return stage;
  }
  const summaryByEventType = eventSummary("harness_loop_event", { event_type: eventType, ...data });
  return summaryByEventType !== "harness_loop_event" ? summaryByEventType : eventType;
}

function makeRuntimeTraceSnapshot(sessionId: string): OrchestrationSnapshot {
  const nodes = ORCHESTRATION_NODES.map((node, index): OrchestrationNode => ({
    ...node,
    index: index + 1,
    status: node.id === "input" ? "success" : "idle",
    summary: node.id === "input" ? "已读取运行轨迹。" : "",
    source_event: node.id === "input" ? "runtime_trace" : ""
  }));
  return {
    source: "runtime-trace",
    session_id: sessionId,
    execution_mode: "running",
    route: "harness",
    status: "running",
    summary: "已载入运行态轨迹。",
    problem_node_id: "",
    nodes,
    edges: deriveOrchestrationEdges(nodes),
    events: []
  };
}

export function buildSnapshotFromHarnessTrace(trace: HarnessTaskRunTrace): OrchestrationSnapshot {
  const taskRun = (trace.task_run ?? {}) as Record<string, unknown>;
  const sessionId = String(taskRun.session_id ?? "");
  let snapshot = makeRuntimeTraceSnapshot(sessionId);
  for (const runtimeEvent of trace.events ?? []) {
    const payload = (runtimeEvent.payload ?? runtimeEvent.payload_summary ?? {}) as Record<string, unknown>;
    const eventType = String(runtimeEvent.event_type ?? "").trim();
    if (!eventType) continue;
    const uiEvent = runtimeEventToUiEvent(eventType);
    const eventData: Record<string, unknown> = {
      event_type: eventType,
      ...payload,
      _runtime_event_id: runtimeEvent.event_id,
      _runtime_offset: runtimeEvent.offset,
      _runtime_refs: runtimeEvent.refs ?? {},
    };
    snapshot = updateOrchestrationSnapshot(snapshot, uiEvent, eventData) ?? snapshot;
    snapshot = {
      ...snapshot,
      events: [
        ...snapshot.events.slice(0, -1),
        {
          index: snapshot.events.length,
          event: eventType,
          node_id: snapshot.events[snapshot.events.length - 1]?.node_id ?? "agent-turn",
          summary: summarizeRuntimeEvent(eventType, eventData),
          ts_ms: runtimeEvent.created_at ? Math.round(runtimeEvent.created_at * 1000) : null,
          data: eventData,
        },
      ],
    };
  }
  return {
    ...(snapshot as OrchestrationSnapshot),
    source: "runtime-trace",
    task_run_id: String(taskRun["task_run_id"] ?? ""),
    graph_run_ids: taskGraphRunIdsFromTrace(trace),
    execution_mode: String((taskRun["diagnostics"] as Record<string, unknown> | undefined)?.["execution_mode"] ?? snapshot.execution_mode),
    route: String(taskRun["task_id"] ?? snapshot.route),
    summary: "已载入运行记录。",
  };
}

function updateOrchestrationSnapshot(
  snapshot: OrchestrationSnapshot | null,
  event: string,
  data: Record<string, unknown>
): OrchestrationSnapshot | null {
  if (!snapshot) {
    return snapshot;
  }
  if (event === "behavior_trace") {
    const nextSnapshot = data.snapshot as OrchestrationSnapshot | undefined;
    if (!nextSnapshot?.nodes?.length) {
      return snapshot;
    }
    return {
      ...normalizeSnapshotEdges(nextSnapshot),
      status: "running",
      events: [
        ...snapshot.events,
        {
          index: snapshot.events.length + 1,
          event,
          node_id: nextSnapshot.problem_node_id || "agent-turn",
          summary: String(nextSnapshot.summary || "行为决策 trace 已生成。"),
          data
        }
      ]
    };
  }
  const nodeId = resolveSnapshotNodeId(snapshot, event);
  const summary = eventSummary(event, data);
  const events = [
    ...snapshot.events,
    {
      index: snapshot.events.length + 1,
      event,
      node_id: nodeId,
      summary,
      data
    }
  ];
  const autoVisited = new Set<string>(["runtime", "agent-turn"]);
  if (["context_management", "memory_context", "prompt_manifest", "worker_start", "token", "content_delta", "answer_candidate", "assistant_text", "done"].includes(event)) {
    autoVisited.add("runtime");
    autoVisited.add("agent-turn");
  }
  const nodes = snapshot.nodes.map((node) => {
    if (event === "error" && node.id === nodeId) {
      return { ...node, status: "failed" as const, summary, source_event: event };
    }
    if (node.id === "persistence" && event === "done") {
      return { ...node, status: "success" as const, summary: "会话与运行状态等待后处理写回。", source_event: event };
    }
    if (node.id === nodeId || autoVisited.has(node.id)) {
      return {
        ...node,
        status: "success" as const,
        summary: node.id === nodeId ? summary : node.summary || "已进入该编排阶段。",
        source_event: node.id === nodeId ? event : node.source_event
      };
    }
    return node;
  });
  const promptManifest = (data.prompt_manifest ?? {}) as Record<string, unknown>;
  const plan = (data.plan ?? {}) as Record<string, unknown>;
  const topology = (plan.topology ?? {}) as Record<string, unknown>;
  const executionMode = String(data.execution_mode ?? topology.mode ?? snapshot.execution_mode);
  const route = String(data.route ?? topology.route ?? snapshot.route);
  const nextNodes = nodes.map((node) => node.id === "prompt" && event === "prompt_manifest"
    ? { ...node, summary: `${String(promptManifest.total_sections ?? 0)} sections / ${String(promptManifest.total_chars ?? 0)} chars` }
    : node);
  return {
    ...snapshot,
    execution_mode: executionMode === "undefined" ? snapshot.execution_mode : executionMode,
    route: route === "undefined" ? snapshot.route : route,
    status: event === "error" ? "failed" : event === "done" ? "success" : "running",
    summary: event === "done"
      ? "编排完成"
      : event === "error"
        ? `编排失败：${String(data.error ?? "unknown")}`
        : publicStreamEventLabel(event),
    problem_node_id: event === "error" ? nodeId : snapshot.problem_node_id,
    nodes: nextNodes,
    edges: snapshot.edges?.length ? snapshot.edges : deriveOrchestrationEdges(nextNodes),
    events
  };
}

function patchAssistant(
  state: StoreState,
  assistantId: string,
  updater: (message: Message) => Message
): StoreState {
  if (!assistantId) {
    return state;
  }
  return {
    ...state,
    messages: state.messages.map((message) =>
      message.id === assistantId ? updater(message) : message
    )
  };
}

function patchAssistantStage(
  state: StoreState,
  assistantId: string,
  stageStatus: string
): StoreState {
  if (!stageStatus) {
    return state;
  }
  return patchAssistant(state, assistantId, (message) => ({
    ...message,
    stageStatus
  }));
}

function normalizeProgressEntry(entry: RuntimeProgressEntry): RuntimeProgressEntry {
  const body = entry.body
    ? entry.body.length > MAX_PROGRESS_BODY_CHARS
      ? `${entry.body.slice(0, MAX_PROGRESS_BODY_CHARS - 1)}...`
      : entry.body
    : undefined;
  return {
    ...entry,
    body,
    artifacts: entry.artifacts?.slice(0, MAX_PROGRESS_ARTIFACTS),
  };
}

function appendAssistantProgress(
  state: StoreState,
  assistantId: string,
  entry: RuntimeProgressEntry | undefined,
): StoreState {
  if (!entry?.title) {
    return state;
  }
  const normalized = normalizeProgressEntry(entry);
  return patchAssistant(state, assistantId, (message) => {
    const existing = message.runtimeProgress ?? [];
    if (existing.some((item) => item.id === normalized.id)) {
      return message;
    }
    return {
      ...message,
      runtimeProgress: [...existing, normalized].slice(-MAX_MESSAGE_PROGRESS_ENTRIES),
    };
  });
}

function patchAssistantPublicTimelineDraft(
  state: StoreState,
  assistantId: string,
  items: PublicChatTimelineItem[] | undefined,
) {
  if (!assistantId || !items?.length) {
    return state;
  }
  return patchAssistant(state, assistantId, (message) => ({
    ...message,
    runtimePublicTimelineDraft: mergePublicTimelineItems(message.runtimePublicTimelineDraft, items),
  }));
}

function patchAssistantTaskProjectionDraft(
  state: StoreState,
  assistantId: string,
  projection: SingleAgentTaskProjection | null,
) {
  const attachment = runtimeAttachmentFromTaskProjection(projection);
  if (!assistantId || !attachment) {
    return state;
  }
  return patchAssistant(state, assistantId, (message) => {
    const existing = message.runtimeAttachments ?? [];
    const runId = runtimeAttachmentRunId(attachment);
    const next = [...existing];
    const index = next.findIndex((item) => runtimeAttachmentRunId(item) === runId);
    if (index >= 0) {
      next[index] = {
        ...next[index],
        ...attachment,
        public_timeline: [],
      };
    } else {
      next.push(attachment);
    }
    return {
      ...message,
      runtimeAttachments: next,
    };
  });
}

function taskProjectionFromEventData(data: Record<string, unknown>): SingleAgentTaskProjection | null {
  const value = data.task_projection_delta ?? data.task_projection;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as SingleAgentTaskProjection;
}

function runtimeAttachmentFromTaskProjection(projection: SingleAgentTaskProjection | null): SessionRuntimeAttachment | null {
  if (!projection) {
    return null;
  }
  const taskRunId = String(projection.task_run_id ?? "").trim();
  const projectionId = String(projection.projection_id ?? "").trim();
  const runId = taskRunId || projectionId;
  if (!runId) {
    return null;
  }
  const anchorTurnId = String(projection.anchor_turn_id ?? projection.turn_id ?? "").trim();
  return {
    attachment_id: `runtime-attachment:${runId}`,
    run_id: runId,
    anchor_turn_id: anchorTurnId,
    anchor_message_id: String(projection.anchor_message_id ?? "").trim() || undefined,
    anchor_role: "assistant",
    task_run_id: taskRunId,
    task_id: String(projection.task_id ?? "").trim() || undefined,
    status: String(projection.status ?? "").trim(),
    public_timeline: [],
    task_projection: projection,
    trace_available: true,
    debug_trace_ref: String(projection.debug_trace_ref ?? taskRunId ?? "").trim(),
    created_at: Number(projection.created_at ?? 0) || undefined,
    updated_at: Number(projection.updated_at ?? 0) || Date.now() / 1000,
  };
}

function runtimeAttachmentRunId(attachment: SessionRuntimeAttachment) {
  return String(attachment.run_id || attachment.task_run_id || "").trim();
}

function applyVisibilitySessionActivity(
  state: StoreState,
  event: string,
  visibility: RuntimeVisibilityProjection,
): StoreState {
  const title = visibility.activityTitle || visibility.stageStatus || "";
  if (!title) {
    return state;
  }
  const progressEntry = visibility.progressEntry;
  return {
    ...state,
    sessionActivity: {
      level: visibility.level || "running",
      title,
      detail: visibility.activityDetail || "",
      event,
      toolName: progressEntry?.toolName,
      receipt: {
        level: visibility.level || "running",
        title,
        body: visibility.activityDetail || undefined,
        artifacts: progressEntry?.artifacts,
        debug: { event },
      },
      updatedAt: Date.now(),
    },
  };
}

export function startStreamingTurn(
  state: StoreState,
  userContent: string,
  options: { existingUserMessageId?: string } = {},
): StreamTransition {
  const userId = options.existingUserMessageId || makeId();
  const userMessage: Message = {
    id: userId,
    role: "user",
    content: userContent.trim(),
    toolCalls: [],
    retrievals: []
  };
  const assistantMessage: Message = {
    id: makeId(),
    role: "assistant",
    content: "",
    toolCalls: [],
    retrievals: [],
    runtimeProgress: [],
    runtimePublicTimelineDraft: [],
    stageStatus: "正在整理上下文"
  };

  return {
    state: {
      ...state,
      isStreaming: true,
      messages: [
        ...(options.existingUserMessageId
          ? state.messages.map((message) =>
              message.id === options.existingUserMessageId
                ? { ...message, content: userContent.trim() }
                : message
            )
          : [...state.messages, userMessage]),
        assistantMessage
      ],
      sessionActivity: {
        level: "running",
        title: "正在整理上下文",
        detail: "准备判断下一步",
        event: "user_message",
        receipt: {
          level: "running",
          title: "正在整理上下文",
          body: "准备判断下一步",
          debug: { event: "user_message" },
        },
        updatedAt: Date.now()
      },
      orchestrationSnapshot: makeOrchestrationSnapshot(state, userContent)
    },
    session: {
      assistantId: assistantMessage.id,
      userId,
    }
  };
}

export function startQueuedActiveTurn(
  state: StoreState,
  userContent: string,
  options: { existingUserMessageId?: string } = {},
): StreamTransition {
  const userId = options.existingUserMessageId || makeId();
  const assistantId = makeId();
  const userMessage: Message = {
    id: userId,
    role: "user",
    content: userContent.trim(),
    toolCalls: [],
    retrievals: []
  };
  const assistantMessage: Message = {
    id: assistantId,
    role: "assistant",
    content: "",
    toolCalls: [],
    retrievals: [],
    runtimeProgress: [],
    runtimePublicTimelineDraft: [
      {
        item_id: `active-turn-steer-local:${userId}`,
        kind: "assistant_text",
        text: "我已收到这条补充要求，会把它接入当前任务。",
        state: "running",
        stream_state: "streaming",
      },
    ],
    stageStatus: "正在纳入补充要求",
  };

  return {
    state: {
      ...state,
      messages: [
        ...(options.existingUserMessageId
          ? state.messages.map((message) =>
            message.id === options.existingUserMessageId
              ? { ...message, content: userContent.trim() }
              : message
          )
          : [...state.messages, userMessage]),
        assistantMessage,
      ],
      sessionActivity: {
        level: "running",
        title: "正在纳入补充要求",
        detail: "这条补充输入会进入当前任务队列。",
        event: "active_turn_input_queued_locally",
        receipt: {
          level: "running",
          title: "正在纳入补充要求",
          body: "这条补充输入会进入当前任务队列。",
          debug: { event: "active_turn_input_queued_locally" },
        },
        updatedAt: Date.now()
      }
    },
    session: {
      assistantId,
      userId,
      queueOnly: true,
    }
  };
}

export function reduceStreamEvent(
  state: StoreState,
  session: StreamSession,
  event: string,
  data: Record<string, unknown>
): StreamTransition {
  const visibility = projectRuntimeStreamEvent(event, data);
  const terminalTimelineState = publicTimelineTerminalStateFromEvent(event);
  const publicTimelineDelta = Array.isArray(data.public_timeline_delta)
    ? sanitizePublicTimelineItems(data.public_timeline_delta as PublicChatTimelineItem[])
    : undefined;
  const taskProjectionDelta = taskProjectionFromEventData(data);
  const activeTurnId = String(data.active_turn_id ?? "").trim();
  const activeTurn = data.active_turn && typeof data.active_turn === "object" && !Array.isArray(data.active_turn)
    ? data.active_turn as Record<string, unknown>
    : {};
  const activeTurnSnapshot = activeTurnId || String(activeTurn.turn_id ?? "").trim()
    ? {
        turn_id: activeTurnId || String(activeTurn.turn_id ?? "").trim(),
        turn_run_id: String(activeTurn.turn_run_id ?? "").trim() || undefined,
        task_run_id: String(
          activeTurn.task_run_id
          ?? activeTurn.bound_task_run_id
          ?? data.runtime_task_run_id
          ?? "",
        ).trim() || undefined,
        state: String(activeTurn.state ?? "").trim() || undefined,
        updated_at: Number(activeTurn.updated_at ?? 0) || undefined,
      }
    : null;
  const taskRunHandoffId = isTaskRunHandoffEvent(data)
    ? String(data.runtime_task_run_id ?? recordValue(data.task_run).task_run_id ?? "").trim()
    : "";
  const taskRunHandoffSnapshot = taskRunHandoffId
    ? {
        turn_id: state.activeTurnSnapshot?.turn_id || "",
        task_run_id: taskRunHandoffId,
        state: "waiting_executor",
        updated_at: Date.now() / 1000,
      }
    : null;
  const stateWithActiveTurn = activeTurnSnapshot
    ? { ...state, activeTurnSnapshot }
    : taskRunHandoffSnapshot
      ? { ...state, activeTurnSnapshot: taskRunHandoffSnapshot }
    : event === "done" || event === "error" || event === "stopped"
      ? { ...state, activeTurnSnapshot: null }
      : state;
  const withOrchestration = updateOrchestrationSnapshot(state.orchestrationSnapshot, event, data);
  const stateWithOrchestrationBase = withOrchestration === stateWithActiveTurn.orchestrationSnapshot
    ? stateWithActiveTurn
    : { ...stateWithActiveTurn, orchestrationSnapshot: withOrchestration };
  const stateWithStage = patchAssistantStage(
    stateWithOrchestrationBase,
    session.assistantId,
    visibility.stageStatus || stageStatusForEvent(event, data)
  );
  const stateWithLegacyActivity = patchSessionActivity(stateWithStage, event, data);
  const stateWithVisibilityActivity = applyVisibilitySessionActivity(stateWithLegacyActivity, event, visibility);
  const stateWithOrchestration = appendAssistantProgress(
    stateWithVisibilityActivity,
    session.assistantId,
    visibility.progressEntry,
  );
  const stateWithTaskProjection = patchAssistantTaskProjectionDraft(
    stateWithOrchestration,
    session.assistantId,
    taskProjectionDelta,
  );
  const stateWithTimelineDraft = patchAssistantPublicTimelineDraft(
    stateWithTaskProjection,
    session.assistantId,
    publicTimelineDelta,
  );

  if (event === "retrieval") {
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => ({
        ...message,
        retrievals: (data.results as RetrievalResult[]) ?? []
      })),
      session
    };
  }

  if (event === "token" || event === "content_delta") {
    if (!stateWithTimelineDraft.chatStreamDisplayEnabled) {
      return {
        state: stateWithTimelineDraft,
        session,
      };
    }
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => {
        const nextContent = `${message.content}${String(data.content ?? "")}`;
        if (
          (!message.content.trim() && looksLikeSkillDocumentPrefix(nextContent)) ||
          looksLikeSkillDocument(nextContent)
        ) {
          return message;
        }
        return { ...message, content: nextContent };
      }),
      session
    };
  }

  if (event === "done") {
    const partialTimeout = String(data.completion_state ?? "").trim() === "partial_timeout";
    const taskSteerAccepted = String(data.completion_state ?? "").trim() === "task_steer_accepted";
    const answerMetadata = answerMetadataFromEvent(data);
    const doneContent = assistantDoneContentFromEvent(data);
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) =>
        message.content.trim()
          ? {
              ...message,
              ...answerMetadata,
              runtimePublicTimelineDraft: mergePublicTimelineItems(
                message.runtimePublicTimelineDraft,
                publicTimelineDelta,
                { terminalState: terminalTimelineState },
              ),
              stageStatus: taskSteerAccepted ? "已收到补充要求" : partialTimeout ? "部分完成" : "完成",
              image: (data.image as Message["image"]) ?? message.image ?? null
            }
          : {
              ...message,
              ...answerMetadata,
              content: doneContent,
              runtimePublicTimelineDraft: mergePublicTimelineItems(
                message.runtimePublicTimelineDraft,
                publicTimelineDelta,
                { terminalState: terminalTimelineState },
              ),
              stageStatus: taskSteerAccepted ? "已收到补充要求" : partialTimeout ? "部分完成" : "完成",
              image: (data.image as Message["image"]) ?? message.image ?? null
            }
      ),
      session
    };
  }

  if (event === "answer_candidate" || event === "assistant_text") {
    if (!stateWithTimelineDraft.chatStreamDisplayEnabled) {
      return {
        state: stateWithTimelineDraft,
        session,
      };
    }
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => {
        if (message.content.trim()) {
          return message;
        }
        if (!shouldKeepStreamAssistantText(event, data)) {
          return message;
        }
        const candidate = String(data.content ?? "").trim();
        return candidate ? { ...message, content: candidate } : message;
      }),
      session
    };
  }

  if (event === "active_task_steer_accepted") {
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => ({
        ...message,
        stageStatus: "已收到补充要求",
      })),
      session
    };
  }

  if (event === "error") {
    const errorText = String(data.content ?? data.error ?? "请求执行失败").trim() || "请求执行失败";
    const visibleError = `处理失败\n\n${errorText}`;
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => {
        const current = message.content.trim();
        if (!current) {
          return {
            ...message,
            content: visibleError,
            runtimePublicTimelineDraft: mergePublicTimelineItems(message.runtimePublicTimelineDraft, publicTimelineDelta, { terminalState: terminalTimelineState }),
            stageStatus: "出错",
          };
        }
        if (current.includes(errorText)) {
          return {
            ...message,
            runtimePublicTimelineDraft: mergePublicTimelineItems(message.runtimePublicTimelineDraft, publicTimelineDelta, { terminalState: terminalTimelineState }),
            stageStatus: "出错",
          };
        }
        return {
          ...message,
          content: `${current}\n\n${visibleError}`,
          runtimePublicTimelineDraft: mergePublicTimelineItems(message.runtimePublicTimelineDraft, publicTimelineDelta, { terminalState: terminalTimelineState }),
          stageStatus: "出错",
        };
      }),
      session
    };
  }

  if (event === "stopped") {
    return {
      state: patchAssistant(stateWithTimelineDraft, session.assistantId, (message) => ({
        ...message,
        content: message.content,
        runtimePublicTimelineDraft: mergePublicTimelineItems(
          message.runtimePublicTimelineDraft,
          [...(publicTimelineDelta ?? []), stoppedPublicTimelineItem()],
          { terminalState: terminalTimelineState },
        ),
        stageStatus: "已停止"
      })),
      session
    };
  }

  return { state: stateWithTimelineDraft, session };
}
