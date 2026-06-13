import {
  taskGraphRunIdsFromTrace,
  type OrchestrationEdge,
  type OrchestrationNode,
  type OrchestrationSnapshot,
  type RetrievalResult,
  type HarnessTaskRunTrace,
} from "@/lib/api";
import { looksLikeRuntimePrivateArtifactText } from "@/lib/runtimePrivateText";
import {
  applyPublicProjectionFrame,
  publicProjectionFrameFromRecord,
  publicProjectionFrameSuppressesLegacy,
} from "@/lib/projection/reducer";

import type { ActiveTurnState, AssistantTextSegmentState, AssistantTextStreamState, Message, StoreState } from "./types";
import {
  makeId
} from "./utils";

export type StreamSession = {
  assistantId: string;
  userId?: string;
  queueOnly?: boolean;
  boundTurnId?: string;
  boundRunId?: string;
  boundTaskRunId?: string;
  boundTurnRunId?: string;
};

type StreamTransition = {
  state: StoreState;
  session: StreamSession;
};

const TOOL_ITEM_STARTED_EVENT = "tool_item_started";
const TOOL_ITEM_COMPLETED_EVENT = "tool_item_completed";
const TURN_COMPLETED_EVENT = "turn_completed";

const PROJECTION_OWNED_ORCHESTRATION_EVENTS = new Set([
  "token",
  "assistant_text_delta",
  "assistant_text_final",
  "assistant_stream_repair",
  "active_task_steer_accepted",
  "done",
  TURN_COMPLETED_EVENT,
  TOOL_ITEM_STARTED_EVENT,
  TOOL_ITEM_COMPLETED_EVENT,
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
  { id: "output", label: "输出记录", description: "记录公开投影、提交状态或任务交接事实。" },
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
  { id: "model-tool", from: "model", to: "tool", label: "行动申请" },
  { id: "model-output", from: "model", to: "output", label: "公开输出" },
  { id: "tool-output", from: "tool", to: "output", label: "结果返回" },
  { id: "output-persistence", from: "output", to: "persistence", label: "落盘写回" }
];

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function isProjectionOwnedOrchestrationEvent(event: string) {
  const normalized = stringValue(event);
  return PROJECTION_OWNED_ORCHESTRATION_EVENTS.has(normalized)
    || normalized === "tool_call"
    || normalized === "tool_result"
    || normalized.startsWith("tool_");
}

function rawStringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function activeTurnStateValue(value: unknown): ActiveTurnState | undefined {
  const normalized = stringValue(value);
  return ACTIVE_TURN_STATES.has(normalized) ? normalized as ActiveTurnState : undefined;
}

const ACTIVE_TURN_STATES = new Set([
  "starting",
  "model_turn",
  "running_task",
  "waiting_executor",
  "waiting_user",
  "waiting_approval",
  "waiting_safe_boundary",
  "interrupting",
  "terminal",
]);

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

function assistantBodySegmentId(
  data: Record<string, unknown>,
  current?: AssistantTextStreamState,
  segments?: Record<string, AssistantTextSegmentState>,
) {
  const explicit = stringValue(data.body_segment_id)
    || stringValue(data.segment_id)
    || stringValue(data.stream_ref)
    || stringValue(data.message_ref);
  if (explicit) {
    return explicit;
  }
  const segmentIds = Object.keys(segments ?? assistantTextSegments(current));
  return segmentIds.length === 1 ? segmentIds[0] : "assistant-body";
}

function assistantBodySegmentRole(data: Record<string, unknown>) {
  return stringValue(data.segment_role)
    || stringValue(data.answer_channel)
    || "conversation";
}

function assistantBodySequence(
  current: AssistantTextStreamState | undefined,
  segmentId: string,
  data: Record<string, unknown>,
) {
  const explicit = numberValue(data.body_sequence);
  if (explicit > 0) {
    return explicit;
  }
  const existing = current?.segmentsById?.[segmentId]?.bodySequence;
  if (existing && existing > 0) {
    return existing;
  }
  return (current?.orderedSegmentIds?.length ?? 0) + 1;
}

function hasExplicitAssistantBodySegmentId(data: Record<string, unknown>) {
  return Boolean(stringValue(data.body_segment_id) || stringValue(data.segment_id));
}

function assistantProgressiveFinalSegmentId(
  baseSegmentId: string,
  current: AssistantTextStreamState | undefined,
  segments: Record<string, AssistantTextSegmentState>,
  data: Record<string, unknown>,
) {
  const ref = stringValue(data.stream_ref)
    || stringValue(data.message_ref)
    || baseSegmentId
    || "assistant-body";
  const sequence = numberValue(data.body_sequence) || numberValue(data.sequence) || (current?.orderedSegmentIds?.length ?? Object.keys(segments).length) + 1;
  let candidate = `${ref}:final:${sequence}`;
  let duplicate = 2;
  while (segments[candidate]) {
    candidate = `${ref}:final:${sequence}:${duplicate}`;
    duplicate += 1;
  }
  return candidate;
}

function progressiveFinalSegmentContent(previousContent: string, incomingContent: string) {
  if (!incomingContent) {
    return "";
  }
  if (!previousContent || previousContent === incomingContent) {
    return previousContent === incomingContent ? "" : incomingContent;
  }
  const previousTrimmedEnd = previousContent.trimEnd();
  if (previousTrimmedEnd && incomingContent.trimEnd() === previousTrimmedEnd) {
    return "";
  }
  if (incomingContent.startsWith(previousContent)) {
    return trimLeadingSegmentBreak(incomingContent.slice(previousContent.length));
  }
  if (previousTrimmedEnd && incomingContent.startsWith(previousTrimmedEnd)) {
    return trimLeadingSegmentBreak(incomingContent.slice(previousTrimmedEnd.length));
  }
  return incomingContent;
}

function trimLeadingSegmentBreak(value: string) {
  return value.replace(/^(?:[ \t]*\r?\n){1,2}/, "").replace(/^[ \t]+/, "");
}

function assistantTextSegments(current: AssistantTextStreamState | undefined): Record<string, AssistantTextSegmentState> {
  if (!current) {
    return {};
  }
  if (current.segmentsById) {
    return current.segmentsById;
  }
  if (!current.canonicalContent) {
    return {};
  }
  const segmentId = current.streamRef || current.messageRef || "assistant-body";
  return {
    [segmentId]: {
      segmentId,
      messageRef: current.messageRef,
      streamRef: current.streamRef,
      bodySequence: 1,
      segmentRole: "conversation",
      latestSequence: current.latestSequence,
      canonicalContent: current.canonicalContent,
      canonicalContentSha256: current.canonicalContentSha256,
      accumulatedUtf8Bytes: current.accumulatedUtf8Bytes,
      finalReceived: current.finalReceived,
      terminal: current.terminal,
      repairState: current.repairState,
      displayHintsBySequence: current.displayHintsBySequence,
    },
  };
}

function assistantTextOrderedSegmentIds(
  current: AssistantTextStreamState | undefined,
  segments: Record<string, AssistantTextSegmentState>,
) {
  const ordered = (current?.orderedSegmentIds ?? []).filter((id) => Boolean(segments[id]));
  for (const segmentId of Object.keys(segments)) {
    if (!ordered.includes(segmentId)) {
      ordered.push(segmentId);
    }
  }
  return ordered.sort((left, right) => {
    const leftSequence = segments[left]?.bodySequence ?? 0;
    const rightSequence = segments[right]?.bodySequence ?? 0;
    if (leftSequence !== rightSequence) {
      return leftSequence - rightSequence;
    }
    return ordered.indexOf(left) - ordered.indexOf(right);
  });
}

function composeAssistantBodyContent(
  orderedSegmentIds: string[],
  segments: Record<string, AssistantTextSegmentState>,
) {
  return orderedSegmentIds
    .map((segmentId) => segments[segmentId]?.canonicalContent ?? "")
    .filter((content) => content.length > 0)
    .join("\n\n");
}

function assistantStreamRepairState(segments: Record<string, AssistantTextSegmentState>) {
  const states = Object.values(segments).map((segment) => segment.repairState);
  if (states.includes("pending")) return "pending";
  if (states.includes("failed")) return "failed";
  if (states.includes("applied")) return "applied";
  return "none";
}

function assistantTextStreamStateFromSegments(
  current: AssistantTextStreamState | undefined,
  assistantId: string,
  segments: Record<string, AssistantTextSegmentState>,
) {
  const orderedSegmentIds = assistantTextOrderedSegmentIds(current, segments);
  const canonicalContent = composeAssistantBodyContent(orderedSegmentIds, segments);
  const lastSegment = segments[orderedSegmentIds[orderedSegmentIds.length - 1]];
  const allSegments = Object.values(segments);
  const finalReceived = allSegments.some((segment) => segment.finalReceived);
  return {
    messageId: assistantId,
    messageRef: lastSegment?.messageRef || current?.messageRef || "",
    streamRef: lastSegment?.streamRef || current?.streamRef || "",
    latestSequence: Math.max(0, ...allSegments.map((segment) => segment.latestSequence)),
    canonicalContent,
    canonicalContentSha256: lastSegment?.canonicalContentSha256 || current?.canonicalContentSha256 || "",
    accumulatedUtf8Bytes: utf8ByteLength(canonicalContent),
    finalReceived,
    terminal: finalReceived && allSegments.every((segment) => segment.finalReceived),
    repairState: assistantStreamRepairState(segments),
    displayHintsBySequence: current?.displayHintsBySequence ?? {},
    orderedSegmentIds,
    segmentsById: segments,
  } satisfies AssistantTextStreamState;
}

function applyAssistantTextStreamState(
  state: StoreState,
  assistantId: string,
  streamState: AssistantTextStreamState,
  options: { patchContent?: boolean; metadata?: Partial<Message> } = {},
) {
  const withStream = {
    ...state,
    assistantTextStreamsByMessageId: {
      ...state.assistantTextStreamsByMessageId,
      [assistantId]: streamState,
    },
  };
  if (options.patchContent === false) {
    return withStream;
  }
  return patchAssistant(withStream, assistantId, (message) => ({
    ...message,
    ...(options.metadata ?? {}),
    content: streamState.canonicalContent,
  }));
}

function mergeAssistantTextDeltaEvent(
  state: StoreState,
  assistantId: string,
  data: Record<string, unknown>,
): StoreState {
  const content = rawStringValue(data.content);
  const sequence = numberValue(data.sequence);
  if (content.length === 0 || sequence <= 0) {
    return state;
  }
  const current = state.assistantTextStreamsByMessageId[assistantId];
  const segments = assistantTextSegments(current);
  const segmentId = assistantBodySegmentId(data, current, segments);
  const currentSegment = segments[segmentId];
  if (currentSegment && sequence <= currentSegment.latestSequence) {
    return state;
  }
  if (!currentSegment && sequence !== 1) {
    const pendingSegment: AssistantTextSegmentState = {
      segmentId,
      messageRef: stringValue(data.message_ref) || current?.messageRef || "",
      streamRef: stringValue(data.stream_ref) || current?.streamRef || "",
      bodySequence: assistantBodySequence(current, segmentId, data),
      segmentRole: assistantBodySegmentRole(data),
      latestSequence: 0,
      canonicalContent: "",
      canonicalContentSha256: "",
      accumulatedUtf8Bytes: 0,
      finalReceived: false,
      terminal: false,
      repairState: "pending",
      displayHintsBySequence: {},
    };
    const streamState = assistantTextStreamStateFromSegments(
      current,
      assistantId,
      { ...segments, [segmentId]: pendingSegment },
    );
    return applyAssistantTextStreamState(state, assistantId, streamState, { patchContent: false });
  }
  if (currentSegment && sequence !== currentSegment.latestSequence + 1) {
    const streamState = assistantTextStreamStateFromSegments(
      current,
      assistantId,
      {
        ...segments,
        [segmentId]: {
          ...currentSegment,
          repairState: "pending",
        },
      },
    );
    return applyAssistantTextStreamState(state, assistantId, streamState, { patchContent: false });
  }
  const previousContent = currentSegment?.canonicalContent ?? "";
  const expectedStart = optionalNumberValue(data.content_utf8_start);
  const canonicalContent = `${previousContent}${content}`;
  const previousUtf8Bytes = utf8ByteLength(previousContent);
  const contentUtf8Bytes = utf8ByteLength(content);
  const canonicalUtf8Bytes = previousUtf8Bytes + contentUtf8Bytes;
  const reportedEnd = optionalNumberValue(data.content_utf8_end);
  const reportedContentBytes = optionalNumberValue(data.content_utf8_bytes);
  const reportedAccumulatedBytes = optionalNumberValue(data.accumulated_utf8_bytes);
  const hasOffsetMismatch =
    (expectedStart !== null && expectedStart !== previousUtf8Bytes)
    || (reportedEnd !== null && reportedEnd !== canonicalUtf8Bytes)
    || (reportedContentBytes !== null && reportedContentBytes !== contentUtf8Bytes)
    || (reportedAccumulatedBytes !== null && reportedAccumulatedBytes !== canonicalUtf8Bytes);
  const repairState = hasOffsetMismatch ? "pending" : currentSegment?.repairState ?? "none";
  const segmentState: AssistantTextSegmentState = {
    segmentId,
    messageRef: stringValue(data.message_ref) || currentSegment?.messageRef || current?.messageRef || "",
    streamRef: stringValue(data.stream_ref) || currentSegment?.streamRef || current?.streamRef || "",
    bodySequence: assistantBodySequence(current, segmentId, data),
    segmentRole: assistantBodySegmentRole(data),
    latestSequence: sequence,
    canonicalContent,
    canonicalContentSha256: stringValue(data.accumulated_sha256) || currentSegment?.canonicalContentSha256 || "",
    accumulatedUtf8Bytes: hasOffsetMismatch ? canonicalUtf8Bytes : reportedAccumulatedBytes ?? canonicalUtf8Bytes,
    finalReceived: false,
    terminal: false,
    repairState,
    displayHintsBySequence: {
      ...(currentSegment?.displayHintsBySequence ?? {}),
      [sequence]: recordValue(data.display_hint),
    },
  };
  const streamState = assistantTextStreamStateFromSegments(
    current,
    assistantId,
    { ...segments, [segmentId]: segmentState },
  );
  return applyAssistantTextStreamState(state, assistantId, streamState, {
    patchContent: state.chatStreamDisplayEnabled,
  });
}

function mergeAssistantTextFinalEvent(
  state: StoreState,
  assistantId: string,
  data: Record<string, unknown>,
): StoreState {
  const content = rawStringValue(data.content);
  const sequence = numberValue(data.sequence);
  const current = state.assistantTextStreamsByMessageId[assistantId];
  const segments = assistantTextSegments(current);
  const initialSegmentId = assistantBodySegmentId(data, current, segments);
  const currentSegment = segments[initialSegmentId];
  const shouldAppendProgressiveFinal = Boolean(
    currentSegment?.finalReceived
    && !hasExplicitAssistantBodySegmentId(data),
  );
  const progressiveContent = shouldAppendProgressiveFinal
    ? progressiveFinalSegmentContent(currentSegment?.canonicalContent ?? "", content)
    : content;
  if (shouldAppendProgressiveFinal && !progressiveContent) {
    return state;
  }
  const segmentId = shouldAppendProgressiveFinal
    ? assistantProgressiveFinalSegmentId(initialSegmentId, current, segments, data)
    : initialSegmentId;
  const targetSegment = shouldAppendProgressiveFinal ? segments[segmentId] : currentSegment;
  const sourceSegment = targetSegment ?? currentSegment;
  const usesIncomingWholeContent = progressiveContent === content;
  const segmentState: AssistantTextSegmentState = {
    segmentId,
    messageRef: stringValue(data.message_ref) || sourceSegment?.messageRef || current?.messageRef || "",
    streamRef: stringValue(data.stream_ref) || sourceSegment?.streamRef || current?.streamRef || "",
    bodySequence: assistantBodySequence(current, segmentId, data),
    segmentRole: assistantBodySegmentRole(data),
    latestSequence: Math.max(sequence, targetSegment?.latestSequence ?? 0),
    canonicalContent: progressiveContent,
    canonicalContentSha256: usesIncomingWholeContent ? stringValue(data.content_sha256) || targetSegment?.canonicalContentSha256 || "" : "",
    accumulatedUtf8Bytes: usesIncomingWholeContent ? optionalNumberValue(data.content_utf8_bytes) ?? utf8ByteLength(progressiveContent) : utf8ByteLength(progressiveContent),
    finalReceived: true,
    terminal: true,
    repairState: targetSegment?.repairState === "pending" ? "applied" : targetSegment?.repairState ?? "none",
    displayHintsBySequence: targetSegment?.displayHintsBySequence ?? {},
  };
  const streamState = assistantTextStreamStateFromSegments(
    current,
    assistantId,
    { ...segments, [segmentId]: segmentState },
  );
  return applyAssistantTextStreamState(state, assistantId, streamState, {
    metadata: answerMetadataFromEvent(data),
  });
}

function mergeAssistantStreamRepairEvent(
  state: StoreState,
  assistantId: string,
  data: Record<string, unknown>,
): StoreState {
  const replacement = rawStringValue(data.replacement_content);
  if (replacement.length === 0) {
    return state;
  }
  const current = state.assistantTextStreamsByMessageId[assistantId];
  const segments = assistantTextSegments(current);
  const segmentId = assistantBodySegmentId(data, current, segments);
  const currentSegment = segments[segmentId];
  const repairSequence = numberValue(data.repair_sequence);
  const segmentState: AssistantTextSegmentState = {
    segmentId,
    messageRef: stringValue(data.message_ref) || currentSegment?.messageRef || current?.messageRef || "",
    streamRef: stringValue(data.stream_ref) || currentSegment?.streamRef || current?.streamRef || "",
    bodySequence: assistantBodySequence(current, segmentId, data),
    segmentRole: assistantBodySegmentRole(data),
    latestSequence: Math.max(repairSequence, currentSegment?.latestSequence ?? 0),
    canonicalContent: replacement,
    canonicalContentSha256: stringValue(data.replacement_content_sha256) || currentSegment?.canonicalContentSha256 || "",
    accumulatedUtf8Bytes: utf8ByteLength(replacement),
    finalReceived: currentSegment?.finalReceived ?? false,
    terminal: currentSegment?.terminal ?? false,
    repairState: "applied",
    displayHintsBySequence: currentSegment?.displayHintsBySequence ?? {},
  };
  const streamState = assistantTextStreamStateFromSegments(
    current,
    assistantId,
    { ...segments, [segmentId]: segmentState },
  );
  return applyAssistantTextStreamState(state, assistantId, streamState, {
    patchContent: state.chatStreamDisplayEnabled || streamState.finalReceived,
  });
}

function numberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function optionalNumberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function utf8ByteLength(value: string) {
  return new TextEncoder().encode(String(value || "")).length;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function bindStreamSessionAnchor(
  session: StreamSession,
  event: string,
  data: Record<string, unknown>,
  options: { hasPublicProjectionFrame?: boolean } = {},
): StreamSession {
  let next = session;
  const bind = (field: keyof Pick<StreamSession, "boundTurnId" | "boundRunId" | "boundTaskRunId" | "boundTurnRunId">, value: string) => {
    const normalized = stringValue(value);
    if (!normalized) {
      return;
    }
    const current = stringValue(next[field]);
    if (current) {
      return;
    }
    if (next === session) {
      next = { ...session };
    }
    next[field] = normalized;
  };
  const bindTurnRun = (turnRunId: string, turnId = "") => {
    const normalizedTurnRunId = stringValue(turnRunId);
    if (!normalizedTurnRunId) {
      return;
    }
    bind("boundTurnRunId", normalizedTurnRunId);
    bind("boundRunId", normalizedTurnRunId);
    bind("boundTurnId", stringValue(turnId) || turnIdFromRuntimeRunId(normalizedTurnRunId));
  };
  if (event === "harness_run_started") {
    const turnRun = recordValue(data.turn_run);
    bindTurnRun(stringValue(turnRun.turn_run_id), stringValue(turnRun.turn_id));
    const taskRun = recordValue(data.task_run);
    const taskRunId = stringValue(taskRun.task_run_id);
    if (taskRunId) {
      bind("boundTaskRunId", taskRunId);
      bind("boundRunId", taskRunId);
      bind("boundTurnId", turnIdFromRuntimeRunId(taskRunId));
    }
  }
  if (
    event === "assistant_text_delta"
    || event === "assistant_text_final"
    || event === "assistant_stream_repair"
    || event === TOOL_ITEM_STARTED_EVENT
    || event === TOOL_ITEM_COMPLETED_EVENT
    || event === TURN_COMPLETED_EVENT
  ) {
    bindTurnRun(stringValue(data.turn_run_id), stringValue(data.turn_id));
    bind("boundTaskRunId", stringValue(data.task_run_id));
  }
  const frame = recordValue(data.public_projection_frame);
  const frameAnchor = recordValue(frame.anchor);
  if (frameAnchor) {
    bind("boundTurnId", stringValue(frameAnchor.turn_id));
    bind("boundRunId", stringValue(frameAnchor.run_id));
    bind("boundTaskRunId", stringValue(frameAnchor.task_run_id));
    bind("boundTurnRunId", stringValue(frameAnchor.turn_run_id));
  }
  const rawRunId = stringValue(data.run_id);
  if (!options.hasPublicProjectionFrame && rawRunId.startsWith("turnrun:")) {
    bindTurnRun(rawRunId, stringValue(data.turn_id));
  }
  return next;
}

function streamAnchorFromSession(session: StreamSession) {
  const turnId = stringValue(session.boundTurnId);
  const runId = stringValue(session.boundRunId);
  const taskRunId = stringValue(session.boundTaskRunId);
  const turnRunId = stringValue(session.boundTurnRunId);
  if (!turnId && !runId && !taskRunId && !turnRunId) {
    return undefined;
  }
  return { turnId, runId, taskRunId, turnRunId };
}

function patchAssistantStreamAnchor(state: StoreState, session: StreamSession): StoreState {
  const assistantId = stringValue(session.assistantId);
  if (!assistantId || !streamAnchorFromSession(session)) {
    return state;
  }
  return patchAssistant(state, assistantId, (message) => ({
    ...message,
    sourceTurnId: message.sourceTurnId || stringValue(session.boundTurnId) || undefined,
    sourceRunId: message.sourceRunId || stringValue(session.boundRunId) || undefined,
    sourceTaskRunId: message.sourceTaskRunId || stringValue(session.boundTaskRunId) || undefined,
    sourceTurnRunId: message.sourceTurnRunId || stringValue(session.boundTurnRunId) || undefined,
  }));
}

function turnIdFromRuntimeRunId(runId: string) {
  const normalized = stringValue(runId);
  const candidate = normalized.startsWith("turnrun:")
    ? normalized.slice("turnrun:".length)
    : normalized.startsWith("taskrun:")
      ? normalized.slice("taskrun:".length)
      : "";
  if (!candidate.startsWith("turn:")) {
    return "";
  }
  const parts = candidate.split(":");
  for (let index = parts.length - 1; index >= 2; index -= 1) {
    if (/^\d+$/.test(parts[index])) {
      return parts.slice(0, index + 1).join(":");
    }
  }
  return candidate;
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
  return looksLikeRuntimePrivateArtifactText(text)
    || /\bfile\s+[^\s]+\s+\d+\s+bytes\b/i.test(text)
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
    return "执行阶段";
  }
  if (eventType === "output_boundary_applied") {
    return "输出记录";
  }
  if (eventType === "commit_gate_checked" || eventType === "checkpoint_written") {
    return "写入状态";
  }
  if (eventType === "loop_terminal") {
    return "运行结束";
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
  if (event === TOOL_ITEM_STARTED_EVENT || event === TOOL_ITEM_COMPLETED_EVENT || event.startsWith("tool")) {
    return "tool";
  }
  if (event === "token" || event === "assistant_text_delta" || event === "assistant_text_final" || event === "assistant_stream_repair" || event === "debug") {
    return "model";
  }
  if (event === "done" || event === "error" || event === TURN_COMPLETED_EVENT) {
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
    [TURN_COMPLETED_EVENT]: "output",
    [TOOL_ITEM_STARTED_EVENT]: "tool",
    [TOOL_ITEM_COMPLETED_EVENT]: "tool",
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
  if (isProjectionOwnedOrchestrationEvent(event)) {
    return "";
  }
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
  if (event === "error") {
    return String(data.error ?? "执行失败");
  }
  if (event === "prompt_manifest") {
    return "上下文已整理。";
  }
  if (event.startsWith("worker")) {
    return String(data.worker ?? data.task_status ?? "worker");
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
    behavior_trace: "处理路径已检查",
    context_management: "上下文已整理",
    debug: "同步状态",
    error: "运行中断",
    harness_loop_event: "运行事件已记录",
    memory_context: "已读取相关记忆",
    orchestration_diff: "处理计划已更新",
    orchestration_plan: "已形成处理计划",
    orchestration_runtime_control: "处理流程已更新",
    output_boundary: "输出边界已检查",
    prompt_manifest: "上下文已整理",
    retrieval: "检索证据",
    worker_end: "子任务已完成",
    worker_start: "子任务已开始",
  };
  return map[event] || "";
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
  if (eventType === "loop_terminal") return TURN_COMPLETED_EVENT;
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
  return summaryByEventType || eventType;
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
    const previousEventCount = snapshot.events.length;
    const nextSnapshot = updateOrchestrationSnapshot(snapshot, uiEvent, eventData) ?? snapshot;
    if (nextSnapshot.events.length === previousEventCount) {
      snapshot = nextSnapshot;
      continue;
    }
    snapshot = nextSnapshot;
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
  if (isProjectionOwnedOrchestrationEvent(event)) {
    return snapshot;
  }
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
  if (["context_management", "memory_context", "prompt_manifest", "worker_start"].includes(event)) {
    autoVisited.add("runtime");
    autoVisited.add("agent-turn");
  }
  const nodes = snapshot.nodes.map((node) => {
    if (event === "error" && node.id === nodeId) {
      return { ...node, status: "failed" as const, summary, source_event: event };
    }
    if (node.id === nodeId || autoVisited.has(node.id)) {
      return {
        ...node,
        status: "success" as const,
        summary: node.id === nodeId ? summary : node.summary,
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
    status: event === "error" ? "failed" : "running",
    summary: event === "error"
        ? `编排失败：${String(data.error_summary ?? data.error ?? "unknown")}`
        : summary || snapshot.summary,
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
    stageStatus: ""
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
      sessionActivity: silentSessionActivity(Date.now()),
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
    stageStatus: "",
    answerChannel: "runtime_control",
    answerCanonicalState: "progress_only",
    answerPersistPolicy: "persist_debug_only",
  };
  const messages = options.existingUserMessageId
    ? [
        ...state.messages.map((message) =>
          message.id === options.existingUserMessageId
            ? { ...message, content: userContent.trim() }
            : message
        ),
        assistantMessage,
      ]
    : [...state.messages, userMessage, assistantMessage];

  return {
    state: {
      ...state,
      messages,
      sessionActivity: silentSessionActivity(Date.now()),
    },
    session: {
      assistantId: assistantMessage.id,
      userId,
      queueOnly: true,
    }
  };
}

function silentSessionActivity(updatedAt = 0): StoreState["sessionActivity"] {
  return {
    level: "idle",
    title: "",
    detail: "",
    event: "",
    updatedAt,
  };
}

export function reduceStreamEvent(
  state: StoreState,
  session: StreamSession,
  event: string,
  data: Record<string, unknown>
): StreamTransition {
  const publicProjectionFrame = publicProjectionFrameFromRecord(data.public_projection_frame);
  const hasPublicProjectionFrame = publicProjectionFrameSuppressesLegacy(publicProjectionFrame);
  const boundSession = bindStreamSessionAnchor(session, event, data, { hasPublicProjectionFrame });
  const activeTurnId = String(data.active_turn_id ?? "").trim();
  const activeTurn = data.active_turn && typeof data.active_turn === "object" && !Array.isArray(data.active_turn)
    ? data.active_turn as Record<string, unknown>
    : {};
  const taskRunHandoffId = isTaskRunHandoffEvent(data)
    ? String(data.runtime_task_run_id ?? recordValue(data.task_run).task_run_id ?? "").trim()
    : "";
  const activeTurnSnapshot = activeTurnId || String(activeTurn.turn_id ?? "").trim()
    ? {
        turn_id: activeTurnId || String(activeTurn.turn_id ?? "").trim(),
        turn_run_id: String(activeTurn.turn_run_id ?? "").trim() || undefined,
        task_run_id: String(
          activeTurn.task_run_id
          ?? activeTurn.bound_task_run_id
          ?? data.runtime_task_run_id
          ?? data.task_run_id
          ?? recordValue(data.task_run).task_run_id
          ?? "",
        ).trim() || undefined,
        state: activeTurnStateValue(activeTurn.state) || (taskRunHandoffId ? "waiting_executor" : undefined),
        updated_at: Number(activeTurn.updated_at ?? 0) || undefined,
      }
    : null;
  const taskRunHandoffSnapshot = taskRunHandoffId
    ? {
        turn_id: state.activeTurnSnapshot?.turn_id || "",
        task_run_id: taskRunHandoffId,
        state: "waiting_executor" as ActiveTurnState,
        updated_at: Date.now() / 1000,
      }
    : null;
  const stateWithActiveTurn = activeTurnSnapshot
    ? { ...state, activeTurnSnapshot }
    : taskRunHandoffSnapshot
      ? { ...state, activeTurnSnapshot: taskRunHandoffSnapshot }
    : event === "done" || event === "error" || event === "stopped" || event === TURN_COMPLETED_EVENT
      ? { ...state, activeTurnSnapshot: null }
      : state;
  const stateWithStreamAnchor = patchAssistantStreamAnchor(stateWithActiveTurn, boundSession);
  const withOrchestration = updateOrchestrationSnapshot(stateWithStreamAnchor.orchestrationSnapshot, event, data);
  const stateWithOrchestrationBase = withOrchestration === stateWithStreamAnchor.orchestrationSnapshot
    ? stateWithStreamAnchor
    : { ...stateWithStreamAnchor, orchestrationSnapshot: withOrchestration };
  const stateWithPublicProjection = publicProjectionFrame
    ? applyPublicProjectionFrame(stateWithOrchestrationBase, publicProjectionFrame, {
        assistantId: boundSession.assistantId,
        streamAnchor: streamAnchorFromSession(boundSession),
      })
    : stateWithOrchestrationBase;
  const stateWithTimelineDraft = stateWithPublicProjection;

  if (event === "retrieval") {
    return {
      state: patchAssistant(stateWithTimelineDraft, boundSession.assistantId, (message) => ({
        ...message,
        retrievals: (data.results as RetrievalResult[]) ?? []
      })),
      session: boundSession
    };
  }

  if (event === "assistant_text_delta") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  if (event === "assistant_stream_repair") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  if (event === "assistant_text_final") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  if (event === TOOL_ITEM_STARTED_EVENT || event === TOOL_ITEM_COMPLETED_EVENT) {
    return {
      state: stateWithTimelineDraft,
      session: boundSession,
    };
  }

  if (event === TURN_COMPLETED_EVENT) {
    return {
      state: stateWithTimelineDraft,
      session: boundSession,
    };
  }

  if (event === "token") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession,
    };
  }

  if (event === "done") {
    const answerMetadata = answerMetadataFromEvent(data);
    return {
      state: patchAssistant(stateWithTimelineDraft, boundSession.assistantId, (message) =>
        ({
          ...message,
          ...answerMetadata,
          stageStatus: message.stageStatus,
          image: (data.image as Message["image"]) ?? message.image ?? null
        })
      ),
      session: boundSession
    };
  }

  if (event === "answer_candidate" || event === "assistant_text") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession,
    };
  }

  if (event === "active_task_steer_accepted") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  if (event === "error") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  if (event === "stopped") {
    return {
      state: stateWithTimelineDraft,
      session: boundSession
    };
  }

  return { state: stateWithTimelineDraft, session: boundSession };
}
