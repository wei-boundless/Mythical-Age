import type {
  ActivityArchiveChildBlock,
  BodyProjectionBlock,
  ChronologicalProjectionLedger,
  ChronologicalProjectionView,
  LogProjectionBlock,
  ProjectionDisplayMode,
  ProjectionRenderBlock,
  StatusProjectionBlock,
  TodoPlanProjectionBlock,
  ToolProjectionBlock,
} from "./types";

export function projectionViewFromLedger(ledger: ChronologicalProjectionLedger | undefined): ChronologicalProjectionView | undefined {
  if (!ledger) return undefined;
  const displayMode = displayModeFromLedger(ledger);
  const toolBlocks = ledger.toolLifecycles
    .filter((tool) => tool.visible || tool.pinned)
    .map((tool): ToolProjectionBlock => ({
      kind: "tool_event",
      id: tool.id,
      title: tool.title,
      detail: tool.detail,
      state: tool.state,
      target: tool.target,
      commandLine: tool.commandLine,
      output: tool.output,
      toolCallId: tool.toolCallId,
      toolLifecycleId: tool.toolLifecycleId,
      toolName: tool.toolName,
      actionKind: tool.actionKind,
      argumentsPreview: tool.argumentsPreview,
      sourceItemId: tool.sourceItemId,
      sourceEventType: tool.sourceEventType,
      sourceEventId: tool.sourceEventId,
      firstOffset: tool.firstOffset,
      lastOffset: tool.lastOffset,
      collapsed: tool.collapsed,
    }));
  const todoBlocks = (ledger.todoPlans ?? []).map((plan): TodoPlanProjectionBlock => ({
    kind: "todo_plan",
    id: plan.id,
    title: plan.title,
    detail: plan.detail,
    state: plan.state,
    statusKind: plan.statusKind,
    planId: plan.planId,
    activeItemId: plan.activeItemId,
    completionReady: plan.completionReady,
    items: plan.items,
    offset: plan.offset,
    sourceEventType: plan.sourceEventType,
    sourceEventId: plan.sourceEventId,
  }));
  const statusBlocks = (ledger.statusEvents ?? []).map((event): StatusProjectionBlock => ({
    kind: event.kind,
    id: event.id,
    statusKind: event.statusKind,
    title: event.title,
    detail: event.detail,
    state: event.state,
    reasoningContent: event.reasoningContent,
    reasoningContentChars: event.reasoningContentChars,
    reasoningContentEstimatedTokens: event.reasoningContentEstimatedTokens,
    reasoningContentSha256: event.reasoningContentSha256,
    reasoningProjectionPolicy: event.reasoningProjectionPolicy,
    offset: event.offset,
    sourceEventType: event.sourceEventType,
    sourceEventId: event.sourceEventId,
    logRef: event.logRef,
  }));
  const otherStatusBlocks = statusBlocks.filter((block) => !isReasoningStatusBlock(block));
  const bodyBlocks = ledger.bodySegments.map((segment): BodyProjectionBlock => ({
    kind: "body_segment" as const,
    id: segment.id,
    text: segment.text,
    firstOffset: segment.firstOffset,
    lastOffset: segment.lastOffset,
    state: segment.state,
    sourceEventType: segment.sourceEventType,
    retention: segment.retention,
    mainVisibility: segment.mainVisibility,
  }));
  const activityBlocks: ActivityArchiveChildBlock[] = [...todoBlocks, ...toolBlocks, ...otherStatusBlocks];
  const finalBodyBoundaryOffset = finalBodyBoundaryOffsetFrom(bodyBlocks);
  const hasFinalBodyBoundary = finalBodyBoundaryOffset !== undefined;
  const closeoutMode = displayMode === "committed" || displayMode === "closeout";
  const closeoutViewMode = closeoutMode || hasFinalBodyBoundary;
  const showLiveReasoning = displayMode === "live" && !hasFinalBodyBoundary;
  const reasoningBlocks = showLiveReasoning ? statusBlocks.filter(isReasoningStatusBlock) : [];
  const visibleBodyBlocks = visibleTimelineBodyBlocks(bodyBlocks, finalBodyBoundaryOffset, closeoutViewMode);
  const archivedBodyBlocks = closeoutViewMode
    ? bodyBlocks.filter((block) => isArchivedBodyBlock(block, finalBodyBoundaryOffset))
    : [];
  const lifecycleBlocks: ProjectionRenderBlock[] = closeoutViewMode
    ? activityArchiveBlocks(
        ledger,
        [
          ...archivedBodyBlocks,
          ...activityBlocks.filter((block) => !hasFinalBodyBoundary || blockOffset(block) < finalBodyBoundaryOffset),
        ],
      )
    : activityBlocks;
  const recoveryOrTerminalBlocks = otherStatusBlocks.filter((block) => block.kind === "recovery_event" || block.kind === "terminal_event");
  const logBlocks: LogProjectionBlock[] = (displayMode === "committed" || displayMode === "closeout" || displayMode === "recovery")
    && (toolBlocks.length || recoveryOrTerminalBlocks.length)
    ? [{
        kind: "log_entry" as const,
        id: `log:${ledger.keyString ?? "projection"}`,
        logRef: recoveryOrTerminalBlocks[0]?.logRef || ledger.key?.taskRunId || ledger.key?.turnRunId || ledger.key?.streamRunId || ledger.key?.runId || "",
        toolEventCount: toolBlocks.length,
      }]
    : [];
  const blocks = [
    ...reasoningBlocks,
    ...visibleBodyBlocks,
    ...lifecycleBlocks,
    ...logBlocks,
  ].sort(compareBlocks);
  return {
    key: ledger.key,
    keyString: ledger.keyString,
    displayMode,
    canonicalContent: ledger.bodyText,
    copyText: ledger.bodyText,
    bodyState: ledger.bodyState,
    blocks,
    logRef: logBlocks[0]?.logRef,
    toolEventCount: toolBlocks.length,
    traceAvailable: toolBlocks.length > 0 || todoBlocks.length > 0 || recoveryOrTerminalBlocks.length > 0,
    diagnostics: ledger.diagnostics,
  };
}

function displayModeFromLedger(ledger: ChronologicalProjectionLedger): ProjectionDisplayMode {
  if (ledger.commit.state === "committed") return "committed";
  if (ledger.commit.state === "failed") return "recovery";
  if ((ledger.statusEvents ?? []).some((event) => event.kind === "recovery_event" || event.kind === "terminal_event")) return "recovery";
  if (
    !ledger.bodySegments.length
    && !ledger.toolLifecycles.length
    && !(ledger.todoPlans ?? []).length
    && !(ledger.statusEvents ?? []).length
  ) {
    return "log_only";
  }
  return "live";
}

function activityArchiveBlocks(
  ledger: ChronologicalProjectionLedger,
  blocks: ActivityArchiveChildBlock[],
): ProjectionRenderBlock[] {
  if (!blocks.length) return [];
  const sortedBlocks = [...blocks].sort(compareBlocks);
  const offset = sortedBlocks.reduce((earliest, block) => Math.min(earliest, blockOffset(block)), Number.MAX_SAFE_INTEGER);
  return [{
    kind: "activity_archive",
    id: `activity-archive:${ledger.keyString ?? "projection"}`,
    title: "",
    detail: archiveDetail(sortedBlocks),
    state: archiveState(sortedBlocks),
    blocks: sortedBlocks,
    offset,
  }];
}

function archiveDetail(blocks: ActivityArchiveChildBlock[]) {
  return `${blocks.length} 条`;
}

function archiveState(blocks: ActivityArchiveChildBlock[]) {
  const states = blocks.map((block) => String(block.state ?? "").toLowerCase());
  if (states.some((state) => ["failed", "error", "blocked"].includes(state))) return "failed";
  if (states.some((state) => ["stopped", "aborted", "cancelled", "canceled"].includes(state))) return "stopped";
  if (states.some((state) => ["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(state))) return "waiting";
  return "done";
}

function compareBlocks(left: ProjectionRenderBlock, right: ProjectionRenderBlock) {
  const leftOffset = blockOffset(left);
  const rightOffset = blockOffset(right);
  if (leftOffset !== rightOffset) return leftOffset - rightOffset;
  const leftRank = blockDisplayRank(left);
  const rightRank = blockDisplayRank(right);
  if (leftRank !== rightRank) return leftRank - rightRank;
  return blockId(left).localeCompare(blockId(right));
}

function blockDisplayRank(block: ProjectionRenderBlock) {
  if (block.kind === "status_event" && isReasoningStatusBlock(block)) return 0;
  if (block.kind === "body_segment") return 1;
  if (block.kind === "activity_archive") return 2;
  if (block.kind === "todo_plan" || block.kind === "tool_event" || block.kind === "status_event" || block.kind === "recovery_event" || block.kind === "terminal_event") return 3;
  if (block.kind === "log_entry") return 4;
  return 5;
}

function isReasoningStatusBlock(block: StatusProjectionBlock) {
  return String(block.statusKind ?? "").trim() === "reasoning_projection_state";
}

function blockOffset(block: ProjectionRenderBlock) {
  if (block.kind === "body_segment") return block.firstOffset;
  if (block.kind === "tool_event") return block.firstOffset;
  if (block.kind === "todo_plan") return block.offset;
  if (block.kind === "status_event" || block.kind === "recovery_event" || block.kind === "terminal_event") return block.offset;
  if (block.kind === "activity_archive") return block.offset;
  if (block.kind === "log_entry") return Number.MAX_SAFE_INTEGER;
  return Number.MAX_SAFE_INTEGER;
}

function blockId(block: ProjectionRenderBlock) {
  return block.id;
}

function finalBodyBoundaryOffsetFrom(
  bodyBlocks: Array<{ firstOffset: number; sourceEventType?: string; mainVisibility?: string }>,
) {
  const finalOffsets = bodyBlocks
    .filter(isExplicitFinalBodyBlock)
    .map((block) => block.firstOffset);
  if (!finalOffsets.length) return undefined;
  return Math.min(...finalOffsets);
}

function isExplicitFinalBodyBlock(block: { sourceEventType?: string; mainVisibility?: string }) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const mainVisibility = String(block.mainVisibility ?? "");
  return sourceEventType === "assistant_text_final" || mainVisibility === "visible_final";
}

function visibleTimelineBodyBlocks(
  bodyBlocks: BodyProjectionBlock[],
  finalBodyBoundaryOffset?: number,
  closeoutMode = false,
): BodyProjectionBlock[] {
  if (finalBodyBoundaryOffset === undefined) return bodyBlocks;
  if (closeoutMode) return [];
  return bodyBlocks.filter((block) =>
    Number(block.firstOffset ?? Number.MAX_SAFE_INTEGER) < finalBodyBoundaryOffset
    && isProcessBodyBlock(block)
  );
}

function isArchivedBodyBlock(
  block: { id?: string; firstOffset?: number; sourceEventType?: string; mainVisibility?: string },
  finalBodyBoundaryOffset?: number,
) {
  if (finalBodyBoundaryOffset === undefined) return false;
  if (isExplicitFinalBodyBlock(block)) return false;
  return Number(block.firstOffset ?? Number.MAX_SAFE_INTEGER) < finalBodyBoundaryOffset
    && isProcessBodyBlock(block);
}

function isProcessBodyBlock(block: { id?: string; sourceEventType?: string }) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const id = String(block.id ?? "");
  return sourceEventType === "assistant_public_feedback"
    || sourceEventType === "runtime_step_summary"
    || id.startsWith("assistant-public-feedback:")
    || id.startsWith("model-action-feedback-body:");
}
