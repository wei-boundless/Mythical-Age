import type { PublicProjectionFrame, PublicTodoItem } from "@/lib/api";

export type ProjectionDisplayMode = "live" | "committed" | "closeout" | "recovery" | "log_only";

export type ProjectionKey = {
  sessionId: string;
  turnId: string;
  messageId: string;
  streamRunId: string;
  runId: string;
  turnRunId: string;
  taskRunId: string;
};

export type FrameIdentity = {
  eventLogId: string;
  eventOffset: number;
  frameId: string;
  key: string;
};

export type NormalizedProjectionFrame = {
  frame: PublicProjectionFrame;
  identity: FrameIdentity;
  key: ProjectionKey;
  keyString: string;
  offset: number;
  frameId: string;
  op: string;
  slot: string;
  channel: string;
  eventFamily: string;
  sourceAuthority: string;
  sourceEventType: string;
  mainVisibility: string;
  retention: string;
};

export type ProjectionDiagnostic = {
  code: string;
  detail: string;
  frameId?: string;
  offset?: number;
};

export type BodySegment = {
  id: string;
  text: string;
  firstOffset: number;
  lastOffset: number;
  state: "streaming" | "finalized" | "committed" | string;
  sourceKeys: string[];
};

export type ToolLifecycle = {
  id: string;
  toolCallId: string;
  toolLifecycleId: string;
  toolName: string;
  actionKind: string;
  title: string;
  detail: string;
  target: string;
  argumentsPreview: string;
  commandLine: string;
  output: string;
  state: string;
  sourceItemId: string;
  sourceEventType: string;
  sourceEventId: string;
  firstOffset: number;
  lastOffset: number;
  visible: boolean;
  pinned: boolean;
  collapsed?: boolean;
};

export type TodoPlanEvent = {
  id: string;
  title: string;
  detail: string;
  state: string;
  statusKind: string;
  planId: string;
  activeItemId: string;
  completionReady?: boolean;
  items: PublicTodoItem[];
  sourceEventType: string;
  sourceEventId: string;
  offset: number;
};

export type StatusProjectionEvent = {
  id: string;
  kind: "status_event" | "recovery_event" | "terminal_event";
  title: string;
  detail: string;
  state: string;
  sourceEventType: string;
  sourceEventId: string;
  offset: number;
  logRef: string;
};

export type ProjectionLedgerCursor = {
  minOffset?: number;
  maxOffset?: number;
  lastCommittedOffset?: number;
};

export type ChronologicalProjectionLedger = {
  key?: ProjectionKey;
  keyString?: string;
  seenFrameKeys: string[];
  cursor: ProjectionLedgerCursor;
  bodyText: string;
  bodyState: "streaming" | "finalized" | "committed" | string;
  displayCursor?: {
    kind: "body" | "activity";
    id?: string;
  };
  bodySegments: BodySegment[];
  toolLifecycles: ToolLifecycle[];
  todoPlans: TodoPlanEvent[];
  statusEvents: StatusProjectionEvent[];
  commit: {
    state: "none" | "checked" | "committed" | "failed" | "skipped" | string;
    key?: string;
    offset?: number;
  };
  diagnostics: ProjectionDiagnostic[];
};

export type BodyProjectionBlock = {
  kind: "body_segment";
  id: string;
  text: string;
  firstOffset: number;
  lastOffset: number;
  state: string;
};

export type ToolProjectionBlock = {
  kind: "tool_event";
  id: string;
  title: string;
  detail: string;
  state: string;
  target: string;
  commandLine: string;
  output: string;
  toolCallId: string;
  toolLifecycleId: string;
  toolName: string;
  actionKind: string;
  argumentsPreview: string;
  sourceItemId: string;
  sourceEventType: string;
  sourceEventId: string;
  firstOffset: number;
  lastOffset: number;
  collapsed?: boolean;
};

export type TodoPlanProjectionBlock = {
  kind: "todo_plan";
  id: string;
  title: string;
  detail: string;
  state: string;
  statusKind: string;
  planId: string;
  activeItemId: string;
  completionReady?: boolean;
  items: PublicTodoItem[];
  offset: number;
  sourceEventType?: string;
  sourceEventId?: string;
};

export type LogProjectionBlock = {
  kind: "log_entry";
  id: string;
  logRef: string;
  toolEventCount: number;
};

export type ActivityArchiveChildBlock =
  | ToolProjectionBlock
  | TodoPlanProjectionBlock
  | StatusProjectionBlock;

export type ActivityArchiveProjectionBlock = {
  kind: "activity_archive";
  id: string;
  title: string;
  detail: string;
  state: string;
  blocks: ActivityArchiveChildBlock[];
  offset: number;
};

export type StatusProjectionBlock = {
  kind: "status_event" | "recovery_event" | "terminal_event";
  id: string;
  title: string;
  detail: string;
  state: string;
  offset: number;
  sourceEventType?: string;
  sourceEventId?: string;
  logRef?: string;
};

export type ProjectionRenderBlock =
  | BodyProjectionBlock
  | ToolProjectionBlock
  | TodoPlanProjectionBlock
  | StatusProjectionBlock
  | ActivityArchiveProjectionBlock
  | LogProjectionBlock;

export type ChronologicalProjectionView = {
  key?: ProjectionKey;
  keyString?: string;
  displayMode: ProjectionDisplayMode;
  canonicalContent: string;
  copyText: string;
  bodyState: string;
  blocks: ProjectionRenderBlock[];
  logRef?: string;
  toolEventCount: number;
  traceAvailable: boolean;
  diagnostics: ProjectionDiagnostic[];
};
