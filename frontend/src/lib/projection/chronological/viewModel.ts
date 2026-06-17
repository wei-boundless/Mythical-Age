import type {
  ActivityArchiveChildBlock,
  ChronologicalProjectionLedger,
  ChronologicalProjectionView,
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
    title: event.title,
    detail: event.detail,
    state: event.state,
    offset: event.offset,
    sourceEventType: event.sourceEventType,
    sourceEventId: event.sourceEventId,
    logRef: event.logRef,
  }));
  const bodyBlocks = ledger.bodySegments.map((segment) => ({
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
  const activityBlocks = [...todoBlocks, ...toolBlocks, ...statusBlocks];
  const closeoutMode = displayMode === "committed" || displayMode === "closeout";
  const closeoutBoundaryOffset = closeoutMode ? closeoutBodyBoundaryOffset(bodyBlocks, activityBlocks) : undefined;
  const closeoutBodyBlocks = closeoutMode
    ? bodyBlocks.filter((block) => isCloseoutBodyBlock(block, ledger.bodyText, closeoutBoundaryOffset))
    : bodyBlocks;
  const archivedBodyBlocks = closeoutMode
    ? bodyBlocks.filter((block) => isArchivedBodyBlock(block, ledger.bodyText, closeoutBoundaryOffset))
    : [];
  const lifecycleBlocks = closeoutMode
    ? activityArchiveBlocks(ledger, [...archivedBodyBlocks, ...activityBlocks])
    : activityBlocks;
  const recoveryOrTerminalBlocks = statusBlocks.filter((block) => block.kind === "recovery_event" || block.kind === "terminal_event");
  const logBlocks = (displayMode === "committed" || displayMode === "closeout" || displayMode === "recovery")
    && (toolBlocks.length || recoveryOrTerminalBlocks.length)
    ? [{
        kind: "log_entry" as const,
        id: `log:${ledger.keyString ?? "projection"}`,
        logRef: recoveryOrTerminalBlocks[0]?.logRef || ledger.key?.taskRunId || ledger.key?.turnRunId || ledger.key?.streamRunId || ledger.key?.runId || "",
        toolEventCount: toolBlocks.length,
      }]
    : [];
  const blocks = [
    ...closeoutBodyBlocks,
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
    title: "本轮记录",
    detail: archiveDetail(sortedBlocks),
    state: archiveState(sortedBlocks),
    blocks: sortedBlocks,
    offset,
  }];
}

function archiveDetail(blocks: ActivityArchiveChildBlock[]) {
  return `${blocks.length} 条记录`;
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
  return blockId(left).localeCompare(blockId(right));
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

function closeoutBodyBoundaryOffset(
  bodyBlocks: Array<{ firstOffset: number; sourceEventType?: string; mainVisibility?: string }>,
  activityBlocks: ProjectionRenderBlock[],
) {
  const finalOffsets = bodyBlocks
    .filter(isExplicitFinalBodyBlock)
    .map((block) => block.firstOffset);
  if (!finalOffsets.length) return undefined;
  const firstFinalOffset = Math.min(...finalOffsets);
  const priorActivityOffsets = activityBlocks
    .map(blockOffset)
    .filter((offset) => Number.isFinite(offset) && offset < firstFinalOffset);
  if (!priorActivityOffsets.length) return Number.NEGATIVE_INFINITY;
  return Math.max(...priorActivityOffsets);
}

function isExplicitFinalBodyBlock(block: { sourceEventType?: string; mainVisibility?: string }) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const mainVisibility = String(block.mainVisibility ?? "");
  return sourceEventType === "assistant_text_final" || mainVisibility === "visible_final";
}

function isCloseoutBodyBlock(
  block: { id?: string; firstOffset?: number; retention?: string; sourceEventType?: string; mainVisibility?: string; text?: string },
  finalBodyText = "",
  closeoutBoundaryOffset?: number,
) {
  const retention = String(block.retention ?? "");
  if (isExplicitFinalBodyBlock(block)) return true;
  if (isSupersededCloseoutBody(block, finalBodyText, closeoutBoundaryOffset)) return false;
  return retention !== "transient" && !isProcessBodyBlock(block);
}

function isArchivedBodyBlock(
  block: { id?: string; firstOffset?: number; retention?: string; sourceEventType?: string; mainVisibility?: string; text?: string },
  finalBodyText = "",
  closeoutBoundaryOffset?: number,
) {
  if (isCloseoutBodyBlock(block, finalBodyText, closeoutBoundaryOffset)) return false;
  if (isSupersededCloseoutBody(block, finalBodyText, closeoutBoundaryOffset)) return false;
  return isProcessBodyBlock(block) || String(block.retention ?? "") === "transient";
}

function isProcessBodyBlock(block: { id?: string; sourceEventType?: string }) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const id = String(block.id ?? "");
  return sourceEventType === "assistant_public_feedback"
    || sourceEventType === "runtime_step_summary"
    || id.startsWith("assistant-public-feedback:")
    || id.startsWith("model-action-feedback-body:");
}

function isSupersededCloseoutBody(
  block: { firstOffset?: number; sourceEventType?: string; text?: string },
  finalBodyText = "",
  closeoutBoundaryOffset?: number,
) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const finalText = normalizeBodyText(finalBodyText);
  if (!finalText) return false;
  if (!bodyIsInCloseoutPhase(block, closeoutBoundaryOffset)) {
    return false;
  }
  if (sourceEventType === "assistant_public_feedback" || sourceEventType === "runtime_step_summary") {
    return true;
  }
  if (sourceEventType === "assistant_stream_repair") {
    return true;
  }
  if (sourceEventType !== "assistant_text_delta") {
    return false;
  }
  const blockText = normalizeBodyText(block.text);
  return Boolean(
    blockText
    && finalText
    && (
      blockText === finalText
      || finalText.startsWith(blockText)
      || (blockText.length >= 80 && finalText.includes(blockText))
    )
  );
}

function bodyIsInCloseoutPhase(block: { firstOffset?: number }, closeoutBoundaryOffset?: number) {
  if (closeoutBoundaryOffset === undefined) return false;
  return Number(block.firstOffset ?? Number.NEGATIVE_INFINITY) > closeoutBoundaryOffset;
}

function normalizeBodyText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}
