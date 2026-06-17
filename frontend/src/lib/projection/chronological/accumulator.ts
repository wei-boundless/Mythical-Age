import type { PublicProjectionFrame } from "@/lib/api";

import { normalizeProjectionFrame, text } from "./normalize";
import type {
  BodySegment,
  ChronologicalProjectionLedger,
  NormalizedProjectionFrame,
  ProjectionDiagnostic,
  StatusProjectionEvent,
  TodoPlanEvent,
  ToolLifecycle,
} from "./types";

export function emptyChronologicalProjectionLedger(): ChronologicalProjectionLedger {
  return {
    seenFrameKeys: [],
    cursor: {},
    bodyText: "",
    bodyState: "streaming",
    bodySegments: [],
    toolLifecycles: [],
    todoPlans: [],
    statusEvents: [],
    commit: { state: "none" },
    diagnostics: [],
  };
}

export function reduceChronologicalProjectionLedger(
  current: ChronologicalProjectionLedger | undefined,
  frame: PublicProjectionFrame,
): ChronologicalProjectionLedger {
  const normalized = normalizeProjectionFrame(frame);
  const ledger = cloneLedger(current ?? emptyChronologicalProjectionLedger());
  if (!normalized) {
    ledger.diagnostics = appendDiagnostic(ledger.diagnostics, {
      code: "projection_frame_without_anchor",
      detail: "Projection frame cannot be attached to a chat projection key.",
      frameId: text(frame.frame_id || frame.projection_id),
    });
    return ledger;
  }
  if (ledger.seenFrameKeys.includes(normalized.identity.key)) {
    return ledger;
  }
  ledger.key = ledger.key ?? normalized.key;
  ledger.keyString = ledger.keyString || normalized.keyString;
  ledger.seenFrameKeys = [...ledger.seenFrameKeys, normalized.identity.key];
  ledger.cursor = updateCursor(ledger.cursor, normalized.offset);

  switch (normalized.op) {
    case "body_append":
      return sortLedger(applyBodyAppend(ledger, normalized));
    case "body_finalize":
      return sortLedger(applyBodyFinalize(ledger, normalized));
    case "item_upsert":
      return sortLedger(applyItemUpsert(ledger, normalized));
    case "item_retire":
      return sortLedger(applyItemRetire(ledger, normalized));
    case "scope_retire":
      return sortLedger(applyScopeRetire(ledger));
    case "commit_ack":
      return sortLedger(applyCommit(ledger, normalized, "committed"));
    default:
      ledger.diagnostics = appendDiagnostic(ledger.diagnostics, {
        code: "unsupported_projection_op",
        detail: normalized.op,
        frameId: normalized.frameId,
        offset: normalized.offset,
      });
      return sortLedger(ledger);
  }
}

function applyBodyAppend(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame) {
  if (!frameCanWriteBody(normalized)) {
    return recordRejectedFrame(ledger, normalized, "body_frame_from_non_model_source");
  }
  const body = rawText(normalized.frame.text);
  if (!body) return ledger;
  const semanticKey = bodySemanticKey(normalized);
  if (semanticKey && bodySegmentsHaveSource(ledger.bodySegments, semanticKey)) {
    return ledger;
  }
  ledger.bodyText += body;
  ledger.bodyState = "streaming";
  appendBodySegment(ledger, normalized, body, "streaming");
  return ledger;
}

function applyBodyFinalize(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame) {
  if (!frameCanWriteBody(normalized)) {
    return recordRejectedFrame(ledger, normalized, "body_frame_from_non_model_source");
  }
  const body = rawText(normalized.frame.text);
  const previous = ledger.bodyText;
  if (body) {
    const previousSegment = ledger.bodySegments[ledger.bodySegments.length - 1];
    const replacesTransientBody = Boolean(
      previous
      && previousSegment
      && normalized.retention !== "transient"
      && (previousSegment.retention === "transient" || previousSegment.sourceEventType === "runtime_step_summary")
    );
    const missingSuffix = !replacesTransientBody && body.startsWith(previous) ? body.slice(previous.length) : "";
    ledger.bodyText = body;
    if (missingSuffix) {
      appendBodySegment(ledger, normalized, missingSuffix, "finalized");
    } else if (!ledger.bodySegments.length || replacesTransientBody || (previous && !body.startsWith(previous))) {
      appendBodySegment(ledger, normalized, body, "finalized", { forceNewSegment: true });
    } else {
      markLatestBodySegment(ledger, normalized.offset, "finalized");
    }
  } else {
    markLatestBodySegment(ledger, normalized.offset, "finalized");
  }
  ledger.bodyState = "finalized";
  return ledger;
}

function applyItemUpsert(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame) {
  if (frameIsTypedStatus(normalized)) {
    return upsertStatusEvent(applyCommitFromStatusFrame(ledger, normalized), statusEventFromFrame(normalized));
  }
  if (frameIsTodoPlan(normalized)) {
    return upsertTodoPlan(ledger, todoPlanFromFrame(normalized));
  }
  if (frameIsTool(normalized)) {
    return upsertToolLifecycle(ledger, toolLifecycleFromFrame(normalized));
  }
  return ledger;
}

function applyItemRetire(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame) {
  if (frameIsTool(normalized)) {
    return upsertToolLifecycle(ledger, toolLifecycleFromFrame(normalized));
  }
  return ledger;
}

function applyScopeRetire(ledger: ChronologicalProjectionLedger) {
  ledger.toolLifecycles = ledger.toolLifecycles.map((tool) =>
    tool.state === "running" || tool.state === "waiting"
      ? { ...tool, visible: false }
      : tool
  );
  return ledger;
}

function applyCommit(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame, state: "committed" | "failed") {
  ledger.commit = {
    state,
    key: commitKey(normalized.frame),
    offset: normalized.offset,
  };
  if (state === "committed") {
    ledger.bodyState = "committed";
    ledger.bodySegments = ledger.bodySegments.map((segment) => ({ ...segment, state: "committed" }));
    ledger.cursor = {
      ...ledger.cursor,
      lastCommittedOffset: normalized.offset,
    };
  }
  return ledger;
}

function appendBodySegment(
  ledger: ChronologicalProjectionLedger,
  normalized: NormalizedProjectionFrame,
  body: string,
  state: BodySegment["state"],
  options: { forceNewSegment?: boolean } = {},
) {
  const semanticKey = bodySemanticKey(normalized);
  const sourceKeys = uniqueStrings([normalized.identity.key, semanticKey]);
  const previous = ledger.bodySegments[ledger.bodySegments.length - 1];
  if (previous && sourceKeys.some((key) => previous.sourceKeys.includes(key))) {
    return;
  }
  if (
    !options.forceNewSegment
    && ledger.displayCursor?.kind === "body"
    && previous
    && previous.sourceEventType === normalized.sourceEventType
    && previous.retention === normalized.retention
  ) {
    previous.text += body;
    previous.lastOffset = normalized.offset;
    previous.state = state;
    previous.sourceKeys = semanticKey
      ? uniqueStrings([...previous.sourceKeys, semanticKey])
      : previous.sourceKeys;
  } else {
    ledger.bodySegments.push({
      id: text(normalized.frame.item_id) || `body:${normalized.keyString}:${normalized.offset}`,
      text: body,
      firstOffset: normalized.offset,
      lastOffset: normalized.offset,
      state,
      sourceEventType: normalized.sourceEventType,
      retention: normalized.retention,
      mainVisibility: normalized.mainVisibility,
      sourceKeys,
    });
  }
  ledger.displayCursor = { kind: "body" };
}

function markLatestBodySegment(ledger: ChronologicalProjectionLedger, offset: number, state: BodySegment["state"]) {
  const latest = ledger.bodySegments[ledger.bodySegments.length - 1];
  if (!latest) return;
  latest.lastOffset = Math.max(latest.lastOffset, offset);
  latest.state = state;
}

function upsertToolLifecycle(ledger: ChronologicalProjectionLedger, incoming: ToolLifecycle | null) {
  if (!incoming) {
    ledger.diagnostics = appendDiagnostic(ledger.diagnostics, {
      code: "tool_projection_without_tool_id",
      detail: "Tool projection frame has no tool_call_id or tool_lifecycle_id.",
    });
    return ledger;
  }
  const index = ledger.toolLifecycles.findIndex((tool) => tool.id === incoming.id);
  if (index < 0) {
    ledger.toolLifecycles = [...ledger.toolLifecycles, incoming];
  } else {
    const next = [...ledger.toolLifecycles];
    next[index] = mergeTool(next[index], incoming);
    ledger.toolLifecycles = next;
  }
  ledger.displayCursor = { kind: "activity", id: incoming.id };
  return ledger;
}

function upsertTodoPlan(ledger: ChronologicalProjectionLedger, incoming: TodoPlanEvent | null) {
  if (!incoming) {
    ledger.diagnostics = appendDiagnostic(ledger.diagnostics, {
      code: "todo_projection_without_items",
      detail: "Todo projection frame has no todo_items.",
    });
    return ledger;
  }
  const currentPlans = ledger.todoPlans ?? [];
  const index = currentPlans.findIndex((plan) => plan.id === incoming.id);
  if (index < 0) {
    ledger.todoPlans = [...currentPlans, incoming];
  } else {
    const next = [...currentPlans];
    next[index] = { ...next[index], ...withoutEmpty(incoming), offset: Math.max(next[index].offset, incoming.offset) };
    ledger.todoPlans = next;
  }
  ledger.displayCursor = { kind: "activity", id: incoming.id };
  return ledger;
}

function upsertStatusEvent(ledger: ChronologicalProjectionLedger, incoming: StatusProjectionEvent | null) {
  if (!incoming) return ledger;
  const currentEvents = ledger.statusEvents ?? [];
  const index = currentEvents.findIndex((event) => event.id === incoming.id);
  if (index < 0) {
    ledger.statusEvents = [...currentEvents, incoming];
  } else if (incoming.offset >= currentEvents[index].offset) {
    const next = [...currentEvents];
    next[index] = { ...next[index], ...withoutEmpty(incoming), offset: incoming.offset };
    ledger.statusEvents = next;
  }
  ledger.displayCursor = { kind: "activity", id: incoming.id };
  return ledger;
}

function statusEventFromFrame(normalized: NormalizedProjectionFrame): StatusProjectionEvent | null {
  const statusKind = typedStatusKind(normalized);
  if (!statusKind || !projectionFrameIsVisible(normalized)) return null;
  const frame = normalized.frame;
  const id = text(frame.item_id || frame.source_item_id || frame.frame_id || frame.projection_id) || `${statusKind}:${normalized.offset}`;
  return {
    id,
    kind: statusKind,
    title: statusTitleFromFrame(statusKind, normalized),
    detail: statusDetailFromFrame(statusKind, normalized),
    state: text(frame.state) || defaultStatusState(statusKind),
    sourceEventType: normalized.sourceEventType,
    sourceEventId: text(frame.source_event_id),
    offset: normalized.offset,
    logRef: text(frame.anchor?.task_run_id || frame.anchor?.turn_run_id || frame.anchor?.stream_run_id || frame.anchor?.run_id),
  };
}

function todoPlanFromFrame(normalized: NormalizedProjectionFrame): TodoPlanEvent | null {
  const frame = normalized.frame;
  const items = Array.isArray(frame.todo_items) ? frame.todo_items.filter((item) => item && item.content) : [];
  if (!items.length) return null;
  const planId = text(frame.plan_id);
  const id = text(frame.item_id || frame.source_item_id || planId || frame.frame_id || frame.projection_id) || `todo:${normalized.offset}`;
  return {
    id,
    title: text(frame.title || frame.text) || "任务清单",
    detail: text(frame.detail),
    state: text(frame.state) || "done",
    statusKind: text(frame.status_kind),
    planId,
    activeItemId: text(frame.active_item_id),
    completionReady: typeof frame.completion_ready === "boolean" ? frame.completion_ready : undefined,
    items,
    sourceEventType: normalized.sourceEventType,
    sourceEventId: text(frame.source_event_id),
    offset: normalized.offset,
  };
}

function toolLifecycleFromFrame(normalized: NormalizedProjectionFrame): ToolLifecycle | null {
  const frame = normalized.frame;
  const toolCallId = text(frame.tool_call_id);
  const toolLifecycleId = text(frame.tool_lifecycle_id);
  const id = toolCallId || toolLifecycleId;
  if (!id) return null;
  const state = text(frame.state) || stateForToolEvent(normalized.sourceEventType);
  const target = text(frame.target || frame.subject_label);
  const argumentsPreview = text(frame.arguments_preview);
  const toolName = text(frame.tool_name);
  const title = text(frame.title || frame.text) || toolTitle(toolName, target);
  return {
    id,
    toolCallId,
    toolLifecycleId,
    toolName,
    actionKind: text(frame.action_kind),
    title,
    detail: text(frame.detail),
    target,
    argumentsPreview,
    commandLine: toolCommandLine(toolName, target, argumentsPreview),
    output: toolOutput(normalized, state),
    state,
    sourceItemId: text(frame.source_item_id),
    sourceEventType: normalized.sourceEventType,
    sourceEventId: text(frame.source_event_id),
    firstOffset: normalized.offset,
    lastOffset: normalized.offset,
    visible: projectionFrameIsVisible(normalized),
    pinned: normalized.mainVisibility === "pinned" || normalized.retention === "pinned_until_resolved",
    collapsed: typeof frame.collapsed === "boolean" ? frame.collapsed : undefined,
  };
}

function mergeTool(existing: ToolLifecycle, incoming: ToolLifecycle): ToolLifecycle {
  const incomingIsOlder = incoming.lastOffset < existing.lastOffset;
  const merged = {
    ...existing,
    ...(incomingIsOlder ? {} : withoutEmpty(incoming)),
    firstOffset: Math.min(existing.firstOffset, incoming.firstOffset),
    lastOffset: Math.max(existing.lastOffset, incoming.lastOffset),
    visible: existing.visible || incoming.visible,
    pinned: existing.pinned || incoming.pinned,
    state: mergeLifecycleState(existing.state, incoming.state, incomingIsOlder),
  };
  const incomingCommandIsOnlyToolName = sameCompactText(incoming.commandLine, incoming.toolName);
  if (!incomingIsOlder && incomingCommandIsOnlyToolName && existing.commandLine && existing.commandLine !== incoming.commandLine) {
    merged.commandLine = existing.commandLine;
  }
  if (!incomingIsOlder && incoming.output === GENERIC_TOOL_DONE_OUTPUT) {
    merged.output = completedToolOutput(merged) || incoming.output;
  }
  return merged;
}

function frameIsTool(normalized: NormalizedProjectionFrame) {
  const frame = normalized.frame;
  return Boolean(frame.tool_call_id || frame.tool_lifecycle_id || frame.tool_name || normalized.eventFamily === "tool_control");
}

function frameIsTodoPlan(normalized: NormalizedProjectionFrame) {
  return text(normalized.frame.status_kind) === "todo_plan" && Array.isArray(normalized.frame.todo_items);
}

function frameIsTypedStatus(normalized: NormalizedProjectionFrame) {
  return Boolean(typedStatusKind(normalized));
}

function typedStatusKind(normalized: NormalizedProjectionFrame): StatusProjectionEvent["kind"] | "" {
  const statusKind = text(normalized.frame.status_kind);
  if (statusKind === "status_event" || statusKind === "recovery_event" || statusKind === "terminal_event") {
    return statusKind;
  }
  return "";
}

function applyCommitFromStatusFrame(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame) {
  const commitState = text(normalized.frame.commit?.state).toLowerCase();
  if (commitState === "failed") {
    ledger.commit = {
      state: "failed",
      key: commitKey(normalized.frame),
      offset: normalized.offset,
    };
  }
  return ledger;
}

function frameCanWriteBody(normalized: NormalizedProjectionFrame) {
  return normalized.slot === "body" && normalized.sourceAuthority === "model";
}

function projectionFrameIsVisible(normalized: NormalizedProjectionFrame) {
  return ["visible_live", "visible_final", "pinned"].includes(normalized.mainVisibility);
}

function sortLedger(ledger: ChronologicalProjectionLedger): ChronologicalProjectionLedger {
  ledger.bodySegments = [...ledger.bodySegments].sort((left, right) =>
    left.firstOffset - right.firstOffset || left.id.localeCompare(right.id)
  );
  ledger.toolLifecycles = [...ledger.toolLifecycles].sort((left, right) =>
    left.firstOffset - right.firstOffset || left.id.localeCompare(right.id)
  );
  ledger.todoPlans = [...(ledger.todoPlans ?? [])].sort((left, right) =>
    left.offset - right.offset || left.id.localeCompare(right.id)
  );
  ledger.statusEvents = [...(ledger.statusEvents ?? [])].sort((left, right) =>
    left.offset - right.offset || left.id.localeCompare(right.id)
  );
  return ledger;
}

function cloneLedger(ledger: ChronologicalProjectionLedger): ChronologicalProjectionLedger {
  return {
    ...ledger,
    key: ledger.key ? { ...ledger.key } : undefined,
    seenFrameKeys: [...ledger.seenFrameKeys],
    cursor: { ...ledger.cursor },
    displayCursor: ledger.displayCursor ? { ...ledger.displayCursor } : undefined,
    bodySegments: ledger.bodySegments.map((segment) => ({ ...segment, sourceKeys: [...segment.sourceKeys] })),
    toolLifecycles: ledger.toolLifecycles.map((tool) => ({ ...tool })),
    todoPlans: (ledger.todoPlans ?? []).map((plan) => ({ ...plan, items: plan.items.map((item) => ({ ...item })) })),
    statusEvents: (ledger.statusEvents ?? []).map((event) => ({ ...event })),
    commit: { ...ledger.commit },
    diagnostics: ledger.diagnostics.map((diagnostic) => ({ ...diagnostic })),
  };
}

function updateCursor(cursor: ChronologicalProjectionLedger["cursor"], offset: number) {
  return {
    ...cursor,
    minOffset: cursor.minOffset === undefined ? offset : Math.min(cursor.minOffset, offset),
    maxOffset: cursor.maxOffset === undefined ? offset : Math.max(cursor.maxOffset, offset),
  };
}

function appendDiagnostic(items: ProjectionDiagnostic[], incoming: ProjectionDiagnostic) {
  return [...items, incoming].slice(-20);
}

function recordRejectedFrame(ledger: ChronologicalProjectionLedger, normalized: NormalizedProjectionFrame, code: string) {
  ledger.diagnostics = appendDiagnostic(ledger.diagnostics, {
    code,
    detail: `${normalized.sourceAuthority}:${normalized.op}:${normalized.slot}`,
    frameId: normalized.frameId,
    offset: normalized.offset,
  });
  return ledger;
}

function bodySegmentsHaveSource(segments: BodySegment[], key: string) {
  return segments.some((segment) => segment.sourceKeys.includes(key));
}

function bodySemanticKey(normalized: NormalizedProjectionFrame) {
  const frame = normalized.frame;
  if (normalized.sourceAuthority !== "model" || normalized.slot !== "body") return "";
  const itemId = text(frame.item_id || frame.source_item_id);
  if (normalized.sourceEventType === "runtime_step_summary" || itemId.startsWith("model-action-feedback-body:")) {
    return itemId;
  }
  return "";
}

function stateForToolEvent(sourceEventType: string) {
  if (sourceEventType === "tool_call_requested" || sourceEventType === "tool_item_started") return "running";
  if (sourceEventType === "tool_item_completed") return "done";
  return "";
}

function toolTitle(toolName: string, target: string) {
  return [toolLabel(toolName) || toolName || "工具", target].filter(Boolean).join(" ");
}

function toolCommandLine(toolName: string, target: string, argumentsPreview: string) {
  return [toolName || "tool", target ? quote(target) : "", argumentsPreview && argumentsPreview !== target ? argumentsPreview : ""]
    .filter(Boolean)
    .join(" ");
}

function toolOutput(normalized: NormalizedProjectionFrame, state: string) {
  const detail = text(normalized.frame.detail);
  if (detail) return detail;
  if (normalized.sourceEventType === "tool_call_requested") return "已提交系统调用。";
  if (normalized.sourceEventType === "tool_permission_decided") return "系统调用已通过准入。";
  if (state === "running" || normalized.sourceEventType === "tool_item_started") return "系统调用运行中。";
  if (["failed", "error", "blocked"].includes(state)) return "系统调用失败。";
  return GENERIC_TOOL_DONE_OUTPUT;
}

const GENERIC_TOOL_DONE_OUTPUT = "系统调用已完成。";

function completedToolOutput(tool: Pick<ToolLifecycle, "target" | "toolName">) {
  const target = text(tool.target);
  if (!target) return "";
  const label = toolLabel(tool.toolName) || "工具";
  if (["读取文件", "检查路径", "列出目录", "搜索文件", "搜索文本", "匹配路径"].includes(label)) {
    return `${label}完成：${target}`;
  }
  if (["写入文件", "更新文件", "编辑文件", "批量编辑文件", "应用补丁"].includes(label)) {
    return `${label}完成：${target}`;
  }
  return `${label}完成：${target}`;
}

function mergeLifecycleState(existing: string, incoming: string, incomingIsOlder: boolean) {
  const existingRank = lifecycleStateRank(existing);
  const incomingRank = lifecycleStateRank(incoming);
  if (incomingIsOlder && existingRank >= incomingRank) return existing;
  return incoming || existing;
}

function lifecycleStateRank(state: string) {
  const normalized = state.toLowerCase();
  if (["failed", "error", "blocked"].includes(normalized)) return 5;
  if (["done", "complete", "completed", "success", "passed"].includes(normalized)) return 4;
  if (["stopped", "aborted", "cancelled", "canceled"].includes(normalized)) return 3;
  if (["waiting", "queued", "paused"].includes(normalized)) return 2;
  if (["running"].includes(normalized)) return 1;
  return 0;
}

function defaultStatusTitle(kind: StatusProjectionEvent["kind"]) {
  if (kind === "status_event") return "状态已更新";
  if (kind === "terminal_event") return "运行已停止";
  return "需要处理";
}

function statusTitleFromFrame(kind: StatusProjectionEvent["kind"], normalized: NormalizedProjectionFrame) {
  if (normalized.sourceAuthority === "runtime") {
    if (kind === "recovery_event") return runtimeRecoveryStatusTitle(normalized.sourceEventType);
    if (kind === "terminal_event") return defaultStatusTitle(kind);
  }
  return text(normalized.frame.title || normalized.frame.text) || defaultStatusTitle(kind);
}

function statusDetailFromFrame(kind: StatusProjectionEvent["kind"], normalized: NormalizedProjectionFrame) {
  const detail = text(normalized.frame.detail);
  if (normalized.sourceAuthority === "runtime" && kind === "recovery_event" && detail.includes("系统")) {
    return "";
  }
  return detail;
}

function runtimeRecoveryStatusTitle(sourceEventType: string) {
  if (sourceEventType === "session_output_commit_failed") return "输出未写入会话记录";
  return "需要处理";
}

function defaultStatusState(kind: StatusProjectionEvent["kind"]) {
  if (kind === "status_event") return "done";
  if (kind === "terminal_event") return "stopped";
  return "failed";
}

function toolLabel(toolName: string) {
  const labels: Record<string, string> = {
    glob_paths: "匹配路径",
    list_dir: "列出目录",
    path_exists: "检查路径",
    read_file: "读取文件",
    read_files: "读取文件",
    read_path: "读取文件",
    search_files: "搜索文件",
    search_text: "搜索文本",
    stat_path: "检查路径",
    write_file: "写入文件",
    edit_file: "更新文件",
    batch_edit_file: "批量编辑文件",
    apply_patch: "更新文件",
    attachment_extract_text: "提取附件文字",
  };
  return labels[toolName.toLowerCase()] || toolName;
}

function commitKey(frame: PublicProjectionFrame) {
  const commit = (frame.commit ?? {}) as Record<string, unknown>;
  return [
    text(frame.anchor?.session_id),
    text(frame.anchor?.turn_id),
    text(frame.anchor?.task_run_id),
    text(commit.commit_event_offset),
    text(commit.content_sha256),
  ].join("|");
}

function withoutEmpty<T extends Record<string, unknown>>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) =>
      item !== "" && item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)
    ),
  ) as Partial<T>;
}

function quote(value: string) {
  return /\s/.test(value) ? `"${value.replace(/"/g, '\\"')}"` : value;
}

function rawText(value: unknown) {
  return typeof value === "string" ? value : "";
}

function sameCompactText(left: string, right: string) {
  return Boolean(left) && Boolean(right) && compactText(left) === compactText(right);
}

function compactText(value: string) {
  return text(value).replace(/\s+/g, "").toLowerCase();
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map(text).filter(Boolean)));
}
