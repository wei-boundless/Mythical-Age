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
  const closeoutMode = displayMode === "committed" || displayMode === "closeout";
  const closeoutBodyBlocks = closeoutMode ? bodyBlocks.filter(isCloseoutBodyBlock) : bodyBlocks;
  const archivedBodyBlocks = closeoutMode ? bodyBlocks.filter((block) => !isCloseoutBodyBlock(block)) : [];
  const activityBlocks = [...todoBlocks, ...toolBlocks, ...statusBlocks];
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

function isCloseoutBodyBlock(block: { id?: string; retention?: string; sourceEventType?: string }) {
  const sourceEventType = String(block.sourceEventType ?? "");
  const retention = String(block.retention ?? "");
  const id = String(block.id ?? "");
  if (sourceEventType === "runtime_step_summary") return false;
  if (id.startsWith("model-action-feedback-body:")) return false;
  return retention !== "transient";
}
