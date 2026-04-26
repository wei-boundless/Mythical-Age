"use client";

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  BrainCircuit,
  Database,
  FileText,
  GitBranch,
  Hammer,
  Loader2,
  Network,
  RefreshCw,
  Route,
  ShieldCheck,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getExperimentTurnOrchestration,
  getOrchestrationCatalog,
  refreshOrchestrationCatalog,
  runOrchestrationDryRun,
  setOrchestrationPlanMode,
  setPermissionMode,
  setPrimaryEntrySelection,
  type OrchestrationCatalog,
  type OrchestrationEvent,
  type OrchestrationNode,
  type OrchestrationSnapshot
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

function emptySnapshot(sessionId: string | null): OrchestrationSnapshot {
  const nodes: OrchestrationNode[] = [
    ["input", "用户输入", "接收本轮用户请求，并绑定当前会话。"],
    ["followup", "Follow-up 仲裁", "判断是否续接已有任务、对象或 bundle item。"],
    ["planner", "任务规划", "形成 route、execution mode、tool、skill 和 worker 决策。"],
    ["execution-mode", "执行模式", "进入 single、bundle 或 explicit fanout 执行拓扑。"],
    ["context", "上下文压缩", "整理历史窗口和上下文压力。"],
    ["memory", "记忆读取", "读取状态记忆、长期记忆和上下文包。"],
    ["prompt", "上下文装配", "组合灵魂、准则、记忆、skill 和本轮提示。"],
    ["capability", "能力调度", "决定进入模型、工具或 worker 分支。"],
    ["model", "模型生成", "模型主链流式输出或发起工具调用。"],
    ["worker", "Worker / Agent", "检索、PDF、结构化数据等 worker 分支。"],
    ["tool", "工具执行", "direct tool 或模型工具调用。"],
    ["output", "输出收口", "选择最终可见答案并过滤内部协议。"],
    ["persistence", "状态写回", "写回会话、状态记忆和长期记忆抽取任务。"]
  ].map(([id, label, description], index) => ({
    id,
    label,
    description,
    index: index + 1,
    status: "idle",
    summary: "",
    source_event: ""
  }));
  return {
    source: "inferred",
    session_id: sessionId ?? "",
    execution_mode: "等待请求",
    route: "未运行",
    status: "idle",
    summary: "还没有 live 编排事件。发送一条消息，或从测试系统选择一个 turn 来复盘。",
    problem_node_id: "",
    nodes,
    edges: [],
    events: [],
    artifacts: {}
  };
}

function statusLabel(status: string) {
  if (status === "running") {
    return "运行中";
  }
  if (status === "success" || status === "passed") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "warning") {
    return "警告";
  }
  return "待观察";
}

function sourceLabel(source: string) {
  if (source === "live-session") {
    return "当前会话";
  }
  if (source === "test-turn") {
    return "测试 Turn";
  }
  if (source === "dry-run") {
    return "行为推演";
  }
  return "推断骨架";
}

function jsonText(value: unknown) {
  if (value == null) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function nodeIcon(nodeId: string) {
  if (nodeId === "memory") {
    return <BrainCircuit size={16} />;
  }
  if (nodeId === "prompt") {
    return <Sparkles size={16} />;
  }
  if (nodeId === "worker") {
    return <Network size={16} />;
  }
  if (nodeId === "tool") {
    return <TerminalSquare size={16} />;
  }
  if (nodeId === "persistence") {
    return <Database size={16} />;
  }
  return <Route size={16} />;
}

const stageGroups = [
  {
    title: "理解",
    hint: "这句话被识别成什么任务",
    nodes: ["input", "memory-intent", "task-understanding", "followup", "planner", "continuation"]
  },
  {
    title: "策略",
    hint: "用什么上下文和行为包",
    nodes: ["execution-mode", "skill-policy", "context", "memory", "prompt"]
  },
  {
    title: "能力",
    hint: "开放哪些工具、worker 和边界",
    nodes: ["capability", "contract", "tool", "worker"]
  },
  {
    title: "收口",
    hint: "最终会怎样执行和输出",
    nodes: ["execution", "model", "output", "persistence"]
  }
];

function compactValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length ? `${value.length} 项` : "空";
  }
  if (value && typeof value === "object") {
    return `${Object.keys(value as Record<string, unknown>).length} 个字段`;
  }
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  return String(value ?? "-");
}

const orchestrationModeCards = [
  {
    mode: "plan_only",
    title: "Plan-only 观测",
    tone: "safe",
    summary: "默认安全水位。生成计划、记录 diff，但不改变执行链。",
    detail: "适合日常开发、前端调试和对比行为偏移。"
  },
  {
    mode: "primary",
    title: "Primary 控制",
    tone: "active",
    summary: "运行时以 OrchestrationPlan 为准，legacy execution 作为兼容与回滚边界。",
    detail: "已通过 smoke、stable、long core、long batches 和 60 轮 mega 验证。"
  },
  {
    mode: "legacy",
    title: "Legacy 回退",
    tone: "fallback",
    summary: "关闭 plan 事件，完全回到旧 planner/runtime 链路。",
    detail: "用于线上异常回滚或验证编排层是否引入偏移。"
  }
];

function modeCardTone(mode: string) {
  return orchestrationModeCards.find((item) => item.mode === mode)?.tone ?? "safe";
}

type DiffItem = {
  field: string;
  expected?: unknown;
  actual?: unknown;
  status?: string;
  reason?: string;
};

type ExecutionObservation = {
  execution_id?: string;
  task_id?: string;
  subtask_index?: number;
  query?: string;
  execution_kind?: string;
  tool_name?: string;
  worker_route?: string;
  bundle_id?: string;
  bundle_item_id?: string;
  summary_preview?: string;
  content_preview?: string;
  output_chars?: number;
  status?: string;
};

type ExecutionEventFilter = {
  index: number;
  label: string;
  markers: Record<string, string | number>;
};

type DroppedAnswerSegment = {
  task_id: string;
  title: string;
  reason: string;
  detail: string;
};

type RuntimeExecutionMismatch = {
  execution_id: string;
  field: string;
  planned: string;
  legacy: string;
};

type RuntimeExecutionEntry = {
  execution_id: string;
  step_id: string;
  entry_kind: string;
  route: string;
  tool: string;
  worker_route: string;
  skill: string;
  agent_id: string;
  source: string;
  strategy: string;
};

type PromptAssemblySection = {
  id: string;
  title: string;
  layer: string;
  source: string;
  chars: number;
  model_visible: boolean;
  preview: string;
  order: number;
};

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function toPromptAssemblySections(value: unknown): PromptAssemblySection[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item, index) => {
      const record = toRecord(item);
      return {
        id: String(record.id ?? `section-${index + 1}`),
        title: String(record.title ?? "未命名片段"),
        layer: String(record.layer ?? "unknown"),
        source: String(record.source ?? "unknown"),
        chars: Number(record.chars ?? 0),
        model_visible: Boolean(record.model_visible),
        preview: String(record.preview ?? ""),
        order: Number(record.order ?? index + 1)
      };
    })
    .sort((left, right) => left.order - right.order);
}

function optionalText(value: unknown) {
  const text = String(value ?? "").trim();
  return text || undefined;
}

function optionalNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
}

function toDiffItems(value: unknown): DiffItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      field: String(item.field ?? ""),
      expected: item.expected,
      actual: item.actual,
      status: String(item.status ?? "unknown"),
      reason: String(item.reason ?? "")
    }))
    .filter((item) => item.field);
}

function toExecutionObservations(value: unknown): ExecutionObservation[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      execution_id: optionalText(item.execution_id),
      task_id: optionalText(item.task_id),
      subtask_index: optionalNumber(item.subtask_index),
      query: optionalText(item.query),
      execution_kind: optionalText(item.execution_kind),
      tool_name: optionalText(item.tool_name),
      worker_route: optionalText(item.worker_route),
      bundle_id: optionalText(item.bundle_id),
      bundle_item_id: optionalText(item.bundle_item_id),
      summary_preview: optionalText(item.summary_preview),
      content_preview: optionalText(item.content_preview),
      output_chars: optionalNumber(item.output_chars),
      status: optionalText(item.status)
    }));
}

function toDroppedAnswerSegments(value: unknown): DroppedAnswerSegment[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      task_id: String(item.task_id ?? ""),
      title: String(item.title ?? ""),
      reason: String(item.reason ?? ""),
      detail: String(item.detail ?? "")
    }));
}

function toRuntimeExecutionMismatches(value: unknown): RuntimeExecutionMismatch[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      execution_id: String(item.execution_id ?? ""),
      field: String(item.field ?? ""),
      planned: String(item.planned ?? ""),
      legacy: String(item.legacy ?? "")
    }))
    .filter((item) => item.field);
}

function toRuntimeExecutionEntries(value: unknown): RuntimeExecutionEntry[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      execution_id: String(item.execution_id ?? ""),
      step_id: String(item.step_id ?? ""),
      entry_kind: String(item.entry_kind ?? ""),
      route: String(item.route ?? ""),
      tool: String(item.tool ?? ""),
      worker_route: String(item.worker_route ?? ""),
      skill: String(item.skill ?? ""),
      agent_id: String(item.agent_id ?? ""),
      source: String(item.source ?? ""),
      strategy: String(item.strategy ?? "")
    }))
    .filter((item) => item.execution_id || item.step_id);
}

function runtimeWarningLabel(warning: string) {
  if (warning === "primary_fallback_validation_blocked") {
    return "编排校验未通过，已回退旧链路";
  }
  if (warning === "primary_fallback_allowlist_blocked") {
    return "超出低风险 primary 范围，已回退旧链路";
  }
  if (warning === "primary_fallback_legacy_execution_mismatch") {
    return "计划分支与旧执行分支不匹配，已回退旧链路";
  }
  if (warning === "primary_fallback_incomplete_contract") {
    return "正式编排契约不完整，已回退旧链路";
  }
  if (warning === "primary_fallback_legacy_field_mismatch") {
    return "正式计划和旧执行字段不一致，已回退旧链路";
  }
  return warning;
}

function runtimeControlSummary(data: Record<string, unknown>) {
  const diagnostics = toRecord(data.diagnostics);
  const warnings = toStringList(data.warnings);
  const primaryActive = Boolean(data.primary_active);
  if (warnings.length) {
    return {
      status: "fallback",
      title: "未接管执行",
      detail: warnings.map(runtimeWarningLabel).join("；"),
      source: String(data.source ?? "legacy_fallback"),
      diagnostics
    };
  }
  if (primaryActive) {
    return {
      status: "primary",
      title: "Primary 已接管",
      detail: `执行模式：${String(data.execution_mode ?? "unknown")}`,
      source: String(data.source ?? "orchestration_plan"),
      diagnostics
    };
  }
  if (data.source === "orchestration_plan_only") {
    return {
      status: "plan_only",
      title: "Plan-only 观测",
      detail: `不改变旧执行链；校验状态：${String(diagnostics.validation_status ?? "未记录")}`,
      source: "orchestration_plan_only",
      diagnostics
    };
  }
  return {
    status: "legacy",
    title: "Legacy 执行",
    detail: `来源：${String(data.source ?? "legacy")}`,
    source: String(data.source ?? "legacy"),
    diagnostics
  };
}

function executionIndexFromField(field: string) {
  const match = field.match(/^executions\[(\d+)\]\./);
  return match ? Number(match[1]) : null;
}

function executionFieldName(field: string) {
  const match = field.match(/^executions\[\d+\]\.(.+)$/);
  return match ? match[1] : field;
}

function addExecutionMarker(markers: Record<string, string | number>, key: string, value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    markers[key] = value;
    return;
  }
  const text = optionalText(value);
  if (text) {
    markers[key] = text;
  }
}

function buildExecutionEventFilter(index: number, planned: ExecutionObservation, actual: ExecutionObservation): ExecutionEventFilter | null {
  if (index < 0) {
    return null;
  }
  const markers: Record<string, string | number> = {};
  const merged = { ...planned, ...actual };
  addExecutionMarker(markers, "execution_id", merged.execution_id);
  addExecutionMarker(markers, "task_id", merged.task_id);
  addExecutionMarker(markers, "subtask_index", merged.subtask_index);
  addExecutionMarker(markers, "bundle_id", merged.bundle_id);
  addExecutionMarker(markers, "bundle_item_id", merged.bundle_item_id);
  addExecutionMarker(markers, "tool_name", merged.tool_name);
  addExecutionMarker(markers, "worker_route", merged.worker_route);
  if (!Object.keys(markers).length) {
    return null;
  }
  const label = merged.execution_id
    || merged.task_id
    || merged.bundle_item_id
    || merged.tool_name
    || merged.worker_route
    || `分支 #${index + 1}`;
  return { index, label, markers };
}

function valueMatchesMarker(value: unknown, expected: string | number) {
  if (typeof expected === "number") {
    return Number(value) === expected;
  }
  return String(value ?? "") === expected;
}

function recordContainsMarker(value: unknown, markerKey: string, markerValue: string | number, depth = 0): boolean {
  if (depth > 4 || value == null) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some((item) => recordContainsMarker(item, markerKey, markerValue, depth + 1));
  }
  if (typeof value !== "object") {
    return valueMatchesMarker(value, markerValue);
  }
  const record = value as Record<string, unknown>;
  const aliases: Record<string, string[]> = {
    execution_id: ["execution_id", "id", "subtask_plan_id", "request_id"],
    task_id: ["task_id"],
    subtask_index: ["subtask_index", "index"],
    bundle_id: ["bundle_id"],
    bundle_item_id: ["bundle_item_id", "item_id"],
    tool_name: ["tool_name", "tool"],
    worker_route: ["worker_route", "route"]
  };
  const keys = aliases[markerKey] ?? [markerKey];
  if (keys.some((key) => valueMatchesMarker(record[key], markerValue))) {
    return true;
  }
  return Object.values(record).some((item) => recordContainsMarker(item, markerKey, markerValue, depth + 1));
}

function eventMatchesExecutionFilter(event: OrchestrationEvent, filter: ExecutionEventFilter) {
  return Object.entries(filter.markers).some(([key, value]) => recordContainsMarker(event.data, key, value));
}

function firstProblemNodeId(snapshot: OrchestrationSnapshot) {
  return snapshot.problem_node_id
    || snapshot.nodes.find((node) => node.status === "failed" || node.status === "blocked")?.id
    || snapshot.nodes.find((node) => node.status === "warning")?.id
    || "";
}

export function ExperimentsView() {
  const {
    currentSessionId,
    orchestrationInspectorTarget,
    orchestrationSnapshot,
    highlightSystemGraph,
    loadInspectorFile,
    setMemoryInspectorTarget,
    setOrchestrationInspectorTarget,
    setOrchestrationSnapshot,
    setWorkspaceView
  } = useAppStore();
  const [activePanel, setActivePanel] = useState<"behavior" | "control" | "skills" | "contracts">("behavior");
  const [testSnapshot, setTestSnapshot] = useState<OrchestrationSnapshot | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("input");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dryRunMessage, setDryRunMessage] = useState("");
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [catalog, setCatalog] = useState<OrchestrationCatalog | null>(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogAction, setCatalogAction] = useState("");
  const [selectedExecutionFilter, setSelectedExecutionFilter] = useState<ExecutionEventFilter | null>(null);
  const currentPlanMode = catalog?.orchestration_plan_mode ?? "plan_only";
  const currentPlanModeCard = orchestrationModeCards.find((item) => item.mode === currentPlanMode) ?? orchestrationModeCards[0];

  const target = orchestrationInspectorTarget;
  const activeSnapshot = target?.source === "test-system"
    ? testSnapshot
    : orchestrationSnapshot;
  const snapshot = activeSnapshot ?? emptySnapshot(currentSessionId);
  const autoProblemNodeId = firstProblemNodeId(snapshot);
  const selectedNode = useMemo(
    () => snapshot.nodes.find((node) => node.id === selectedNodeId)
      ?? snapshot.nodes.find((node) => node.id === snapshot.problem_node_id)
      ?? snapshot.nodes[0],
    [selectedNodeId, snapshot.nodes, snapshot.problem_node_id]
  );
  const problemNode = snapshot.nodes.find((node) => node.id === snapshot.problem_node_id);
  const visitedCount = snapshot.nodes.filter((node) => node.status !== "idle").length;
  const branchNodes = snapshot.nodes.filter((node) => ["worker", "tool"].includes(node.id) && node.status !== "idle");
  const nodeById = useMemo(() => new Map(snapshot.nodes.map((node) => [node.id, node])), [snapshot.nodes]);
  const executionNode = nodeById.get("execution") ?? nodeById.get("model") ?? nodeById.get("worker") ?? nodeById.get("tool");
  const contextNode = nodeById.get("context") ?? nodeById.get("memory");
  const contractNode = nodeById.get("contract") ?? nodeById.get("tool");
  const skillNode = nodeById.get("skill-policy") ?? nodeById.get("capability");
  const readableRoute = `${snapshot.route || "unknown"} / ${snapshot.execution_mode || "unknown"}`;
  const orchestrationDiff = (snapshot.orchestration_diff ?? {}) as Record<string, unknown>;
  const orchestrationPlan = (snapshot.orchestration_plan ?? snapshot.dry_run?.orchestration_plan ?? {}) as Record<string, unknown>;
  const intentFrame = toRecord(orchestrationPlan.intent_frame);
  const memoryPolicy = toRecord(orchestrationPlan.memory_policy);
  const contextPolicy = toRecord(orchestrationPlan.context_policy);
  const resourcePolicy = toRecord(orchestrationPlan.resource_policy);
  const answerPolicy = toRecord(orchestrationPlan.answer_policy);
  const validationDecision = toRecord(orchestrationPlan.validation);
  const executionDirectives = Array.isArray(orchestrationPlan.execution_directives)
    ? orchestrationPlan.execution_directives.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const validationIssues = Array.isArray(validationDecision.issues)
    ? validationDecision.issues.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const runtimeControlEvent = [...snapshot.events].reverse().find((event) => event.event === "orchestration_runtime_control");
  const runtimeControl = runtimeControlSummary(toRecord(runtimeControlEvent?.data));
  const runtimeDiagnostics = runtimeControl.diagnostics;
  const runtimeExecutionMismatches = useMemo(
    () => toRuntimeExecutionMismatches(runtimeDiagnostics.execution_mismatches),
    [runtimeDiagnostics.execution_mismatches]
  );
  const runtimeExecutionEntries = useMemo(
    () => toRuntimeExecutionEntries(runtimeDiagnostics.execution_entries),
    [runtimeDiagnostics.execution_entries]
  );
  const diffItems = useMemo(() => toDiffItems(orchestrationDiff.items), [orchestrationDiff.items]);
  const executionDiffItems = useMemo(
    () => diffItems.filter((item) => item.field === "executions.count" || item.field.startsWith("executions[")),
    [diffItems]
  );
  const executionMismatches = useMemo(
    () => executionDiffItems.filter((item) => item.status === "mismatch" || item.status === "warning"),
    [executionDiffItems]
  );
  const actualEnvelope = toRecord(orchestrationDiff.actual);
  const answerAssembly = toRecord(actualEnvelope.answer_assembly);
  const answerAssemblySelectedTaskIds = useMemo(
    () => new Set(toStringList(answerAssembly.selected_task_ids)),
    [answerAssembly.selected_task_ids]
  );
  const answerAssemblyDropped = useMemo(
    () => toDroppedAnswerSegments(answerAssembly.dropped_segments),
    [answerAssembly.dropped_segments]
  );
  const actualExecutions = useMemo(() => toExecutionObservations(actualEnvelope.executions), [actualEnvelope.executions]);
  const plannedExecutions = useMemo(() => toExecutionObservations(orchestrationPlan.executions), [orchestrationPlan.executions]);
  const executionBranchCount = Math.max(plannedExecutions.length, actualExecutions.length);
  const branchDiagnostics = useMemo(() => {
    const rows = Array.from({ length: executionBranchCount }, (_, index) => {
      const planned: ExecutionObservation = plannedExecutions[index] ?? {};
      const actual: ExecutionObservation = actualExecutions[index] ?? {};
      const items = executionDiffItems.filter((item) => executionIndexFromField(item.field) === index);
      const status = items.some((item) => item.status === "mismatch")
        ? "mismatch"
        : items.some((item) => item.status === "warning")
          ? "warning"
          : items.some((item) => item.status === "matched")
            ? "matched"
            : String(actual.status || planned.status || "observed");
      return { index, planned, actual, items, status };
    });
    const countItem = executionDiffItems.find((item) => item.field === "executions.count");
    if (countItem && executionBranchCount === 0) {
      return [{ index: -1, planned: {}, actual: {}, items: [countItem], status: countItem.status ?? "unknown" }];
    }
    return rows;
  }, [actualExecutions, executionBranchCount, executionDiffItems, plannedExecutions]);
  const filteredEvents = useMemo(
    () => selectedExecutionFilter
      ? snapshot.events.filter((event) => eventMatchesExecutionFilter(event, selectedExecutionFilter))
      : snapshot.events,
    [selectedExecutionFilter, snapshot.events]
  );

  useEffect(() => {
    setSelectedExecutionFilter(null);
  }, [snapshot.run_id, snapshot.turn_id, snapshot.session_id]);

  useEffect(() => {
    if (!autoProblemNodeId) {
      return;
    }
    setSelectedNodeId(autoProblemNodeId);
    window.setTimeout(() => {
      document
        .querySelector(`[data-orchestration-node-id="${autoProblemNodeId}"]`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 80);
  }, [autoProblemNodeId, snapshot.run_id, snapshot.turn_id, snapshot.session_id]);

  const loadTargetSnapshot = useCallback(async () => {
    if (!target?.runId || !target.turnId) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const payload = await getExperimentTurnOrchestration(target.runId, target.turnId, target.artifactPath);
      setTestSnapshot(payload);
      setOrchestrationSnapshot(payload);
      setSelectedNodeId(payload.problem_node_id || payload.nodes.find((node) => node.status === "failed")?.id || "input");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载编排链路失败");
    } finally {
      setLoading(false);
    }
  }, [setOrchestrationSnapshot, target?.artifactPath, target?.runId, target?.turnId]);

  useEffect(() => {
    if (target?.source === "test-system") {
      void loadTargetSnapshot();
    }
  }, [loadTargetSnapshot, target?.source]);

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      setCatalog(await getOrchestrationCatalog());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载编排 catalog 失败");
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  async function refreshCatalog() {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      setCatalog(await refreshOrchestrationCatalog());
      setCatalogAction("Registry 已刷新，skills 与 tools catalog 已重新读取。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "刷新 catalog 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function changePermissionMode(mode: string) {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      await setPermissionMode(mode);
      const nextCatalog = await getOrchestrationCatalog();
      setCatalog(nextCatalog);
      setCatalogAction(`Permission mode 已切换为 ${nextCatalog.permission_mode}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换 permission mode 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function changeOrchestrationPlanMode(mode: string) {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      await setOrchestrationPlanMode(mode);
      const nextCatalog = await getOrchestrationCatalog();
      setCatalog(nextCatalog);
      setCatalogAction(`Orchestration plan mode 已切换为 ${nextCatalog.orchestration_plan_mode}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换 orchestration plan mode 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function changePrimaryEntrySelection(enabled: boolean) {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      await setPrimaryEntrySelection(enabled);
      const nextCatalog = await getOrchestrationCatalog();
      setCatalog(nextCatalog);
      setCatalogAction(enabled ? "Primary entry selection 预览已开启。" : "Primary entry selection 预览已关闭。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换 primary entry selection 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  useEffect(() => {
    if (activePanel !== "behavior" && !catalog) {
      void loadCatalog();
    }
  }, [activePanel, catalog, loadCatalog]);

  function locateOnSystemGraph(node: OrchestrationNode) {
    const map: Record<string, string[]> = {
      input: ["api-router"],
      followup: ["query-core"],
      planner: ["planner"],
      "execution-mode": ["query-core"],
      context: ["query-core", "memory"],
      memory: ["memory"],
      prompt: ["prompt"],
      capability: ["query-core", "tooling"],
      model: ["model"],
      worker: ["evidence"],
      tool: ["tooling"],
      output: ["query-core"],
      persistence: ["session-store", "storage"]
    };
    highlightSystemGraph({
      nodeIds: map[node.id] ?? ["query-core"],
      edgeIds: [],
      reason: node.summary || node.description,
      source: `orchestration:${node.id}`
    });
    setWorkspaceView("system-framework");
  }

  function openMemoryNode() {
    if (snapshot.source === "test-turn" && snapshot.run_id && snapshot.turn_id) {
      setMemoryInspectorTarget({
        source: "test-system",
        runId: snapshot.run_id,
        turnId: snapshot.turn_id,
        turnIndex: snapshot.turn_index,
        layer: "state",
        reason: selectedNode?.summary || "从编排系统查看状态记忆。"
      });
    } else {
      setMemoryInspectorTarget({
        source: "manual",
        layer: "state",
        reason: selectedNode?.summary || "从编排系统查看当前会话状态记忆。"
      });
    }
    setWorkspaceView("memory");
  }

  async function submitDryRun() {
    const message = dryRunMessage.trim();
    if (!message || !currentSessionId) {
      setError(currentSessionId ? "请输入要推演的用户请求。" : "需要先选择一个会话，dry-run 才能读取当前上下文。");
      return;
    }
    setDryRunLoading(true);
    setError("");
    try {
      const payload = await runOrchestrationDryRun({
        session_id: currentSessionId,
        message
      });
      setTestSnapshot(null);
      setOrchestrationInspectorTarget(null);
      setOrchestrationSnapshot(payload);
      setSelectedNodeId(payload.problem_node_id || "task-understanding");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "行为推演失败");
    } finally {
      setDryRunLoading(false);
    }
  }

  const selectedDetails = selectedNode
    ? {
        source_module: selectedNode.source_module,
        reasons: selectedNode.reasons,
        inputs: selectedNode.inputs,
        outputs: selectedNode.outputs,
        refs: selectedNode.refs
      }
    : null;
  const selectedReasonList = (selectedNode?.reasons ?? []).filter(Boolean).slice(0, 6);
  const selectedOutputPreview = selectedNode?.outputs
    ? Object.entries(selectedNode.outputs).slice(0, 6)
    : [];
  const selectedPromptSections = selectedNode?.id === "prompt"
    ? toPromptAssemblySections(selectedNode.outputs?.sections)
    : [];
  const normalizedCatalogQuery = catalogQuery.trim().toLowerCase();
  const visibleCatalogSkills = (catalog?.skills ?? []).filter((skill) => {
    if (!normalizedCatalogQuery) {
      return true;
    }
    return `${skill.runtime.name} ${skill.runtime.title} ${skill.runtime.description} ${skill.runtime.allowed_tools.join(" ")} ${skill.runtime.capability_tags.join(" ")}`
      .toLowerCase()
      .includes(normalizedCatalogQuery);
  });
  const visibleCatalogTools = (catalog?.tools ?? []).filter((tool) => {
    if (!normalizedCatalogQuery) {
      return true;
    }
    return `${tool.name} ${tool.module} ${tool.capability_tags.join(" ")} ${tool.safety_tags.join(" ")} ${tool.route_hints.join(" ")}`
      .toLowerCase()
      .includes(normalizedCatalogQuery);
  });

  return (
    <div className="workspace-view orchestration-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Orchestration Control Tower</p>
          <h2 className="workspace-view__title">编排系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" disabled={loading || target?.source !== "test-system"} onClick={() => void loadTargetSnapshot()} type="button">
            {loading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
            刷新链路
          </button>
          <button className="action-button action-button--muted" onClick={() => setOrchestrationInspectorTarget(null)} type="button">
            看当前会话
          </button>
        </div>
      </header>

      <nav className="orchestration-tabs" aria-label="编排系统页面">
        {[
          { key: "behavior", label: "行为判读", icon: Route },
          { key: "control", label: "运行控制", icon: ShieldCheck },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={activePanel === item.key ? "orchestration-tabs__item orchestration-tabs__item--active" : "orchestration-tabs__item"}
              key={item.key}
              onClick={() => setActivePanel(item.key as "behavior" | "control" | "skills" | "contracts")}
              type="button"
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {error ? (
        <div className="workspace-alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      ) : null}

      {activePanel === "control" ? (
        <section className="workspace-section orchestration-runtime-control">
          <div className="workspace-section__head">
            <ShieldCheck size={18} />
            <h3>运行控制面</h3>
            <span className={`tag-chip orchestration-mode-chip orchestration-mode-chip--${modeCardTone(currentPlanMode)}`}>
              当前：{currentPlanMode}
            </span>
            <button className="action-button action-button--ghost" onClick={() => void loadCatalog()} type="button">
              {catalogLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
              刷新状态
            </button>
          </div>
          <div className={`orchestration-mode-hero orchestration-mode-hero--${modeCardTone(currentPlanMode)}`}>
            <span>Behavior Control Plane</span>
            <strong>{currentPlanModeCard.title}</strong>
            <p>{currentPlanModeCard.summary}</p>
            <small>{currentPlanModeCard.detail}</small>
          </div>
          <div className="orchestration-mode-grid">
            {orchestrationModeCards.map((item) => {
              const active = item.mode === currentPlanMode;
              const supported = (catalog?.supported_orchestration_plan_modes ?? []).includes(item.mode);
              return (
                <article className={`orchestration-mode-card orchestration-mode-card--${item.tone} ${active ? "orchestration-mode-card--active" : ""}`} key={item.mode}>
                  <div>
                    <span>{item.mode}</span>
                    {active ? <em>当前运行</em> : supported ? <em>可切换</em> : <em>未开放</em>}
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.summary}</p>
                  <small>{item.detail}</small>
                  <button
                    className={item.mode === "primary" ? "action-button action-button--primary" : "action-button action-button--muted"}
                    disabled={catalogLoading || !catalog || active || !supported}
                    onClick={() => void changeOrchestrationPlanMode(item.mode)}
                    type="button"
                  >
                    {active ? "已启用" : item.mode === "legacy" ? "回退到 Legacy" : `切换到 ${item.mode}`}
                  </button>
                </article>
              );
            })}
          </div>
          <div className="orchestration-runtime-ledger">
            <article>
              <b>最近 primary 验证</b>
              <span>smoke 2/2、stable 10/10、long core 3/3、long batches 6/6、mega 60 轮 1/1。</span>
            </article>
            <article>
              <b>回滚边界</b>
              <span>primary 匹配失败会自动 fallback legacy execution；手动可随时切回 plan-only 或 legacy。</span>
            </article>
            <article>
              <b>使用建议</b>
              <span>开发与测试优先 plan-only；专项验证可 primary；如果发现计划偏移或链路异常，先回 plan-only 再复盘 diff。</span>
            </article>
            <article>
              <b>入口选择预览</b>
              <span>{catalog?.primary_entry_selection_enabled ? "已开启：RuntimeControl 会标记 primary_entry_selection_preview。" : "默认关闭：继续复用 legacy execution，只观察入口计划。"}</span>
              <button
                className={catalog?.primary_entry_selection_enabled ? "action-button action-button--muted" : "action-button action-button--primary"}
                disabled={catalogLoading || !catalog}
                onClick={() => void changePrimaryEntrySelection(!catalog?.primary_entry_selection_enabled)}
                type="button"
              >
                {catalog?.primary_entry_selection_enabled ? "关闭预览" : "开启预览"}
              </button>
            </article>
          </div>
          {catalogAction ? <div className="workspace-alert">{catalogAction}</div> : null}
        </section>
      ) : activePanel === "skills" ? (
        <section className="workspace-section orchestration-management">
          <div className="workspace-section__head">
            <Boxes size={18} />
            <h3>Skills 管理</h3>
            <span className="tag-chip">{catalogLoading ? "加载中" : `${visibleCatalogSkills.length}/${catalog?.skills.length ?? 0}`}</span>
            <button className="action-button action-button--ghost" onClick={() => void refreshCatalog()} type="button">
              {catalogLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
              刷新 Registry
            </button>
          </div>
          {catalogAction ? <div className="workspace-alert">{catalogAction}</div> : null}
          <div className="workspace-search">
            <Sparkles size={17} />
            <input onChange={(event) => setCatalogQuery(event.target.value)} placeholder="查 skill、allowed tools、能力标签或 route" value={catalogQuery} />
          </div>
          <div className="orchestration-management-grid">
            {visibleCatalogSkills.map((skill) => (
              <article className="orchestration-management-card" key={skill.runtime.name}>
                <div className="workspace-record__meta">
                  <span>{skill.runtime.preferred_route || "route"}</span>
                  <span>{skill.runtime.activation_policy}</span>
                  <span>{skill.runtime.context_mode}</span>
                </div>
                <h3>{skill.runtime.title || skill.runtime.name}</h3>
                <p>{skill.runtime.description}</p>
                <div className="workspace-chip-row">
                  {skill.runtime.allowed_tools.slice(0, 6).map((tool) => <span className="workspace-mini-chip" key={tool}>{tool}</span>)}
                </div>
                <div className="orchestration-management-card__contract">
                  <b>Prompt 可见</b>
                  <span>{skill.prompt_view.use_when || skill.prompt_view.output_rule}</span>
                </div>
                <button className="action-button action-button--muted" onClick={() => void loadInspectorFile(skill.runtime.path)} type="button">
                  打开并编辑定义
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : activePanel === "contracts" ? (
        <section className="workspace-section orchestration-management">
          <div className="workspace-section__head">
            <ShieldCheck size={18} />
            <h3>工具管理</h3>
            <span className="tag-chip">permission: {catalog?.permission_mode ?? "-"}</span>
            <span className="tag-chip">contract: {catalog?.tool_contract_mode ?? "-"}</span>
            <button className="action-button action-button--ghost" onClick={() => void refreshCatalog()} type="button">
              {catalogLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
              刷新 Registry
            </button>
          </div>
          <div className="orchestration-permission-bar">
            <div>
              <b>Permission Mode</b>
              <span>这里只切换运行权限模式；tool contract 本体保持只读，避免前端绕过安全边界。</span>
            </div>
            <select
              disabled={catalogLoading || !catalog}
              onChange={(event) => void changePermissionMode(event.target.value)}
              value={catalog?.permission_mode ?? ""}
            >
              {(catalog?.supported_permission_modes ?? []).map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </div>
          <div className="orchestration-permission-bar">
            <div>
              <b>Orchestration Plan Mode</b>
              <span>legacy 关闭计划事件，plan-only 只观测不改行为，primary 使用已验证的 OrchestrationPlan 控制面。</span>
            </div>
            <select
              disabled={catalogLoading || !catalog}
              onChange={(event) => void changeOrchestrationPlanMode(event.target.value)}
              value={catalog?.orchestration_plan_mode ?? ""}
            >
              {(catalog?.supported_orchestration_plan_modes ?? []).map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </div>
          {catalogAction ? <div className="workspace-alert">{catalogAction}</div> : null}
          <div className="workspace-search">
            <Hammer size={17} />
            <input onChange={(event) => setCatalogQuery(event.target.value)} placeholder="查 tool、契约字段、安全标签或 route hint" value={catalogQuery} />
          </div>
          <div className="orchestration-contract-grid">
            {visibleCatalogTools.map((tool) => (
              <article className={`orchestration-contract-card ${tool.is_destructive ? "orchestration-contract-card--danger" : ""}`} key={tool.name}>
                <div className="workspace-record__meta">
                  <span>{tool.safe_for_auto_route ? "auto-route" : "manual"}</span>
                  <span>{tool.runtime_visibility}</span>
                  <span>{tool.is_read_only ? "read-only" : "write-capable"}</span>
                </div>
                <h3>{tool.name}</h3>
                <p>{tool.module}</p>
                <div className="orchestration-contract-card__matrix">
                  <span><b>输入</b><em>{compactValue(tool.contract.required_inputs)}</em></span>
                  <span><b>绑定</b><em>{compactValue(tool.contract.required_bindings)}</em></span>
                  <span><b>缺失处理</b><em>{compactValue(tool.contract.missing_binding_behavior)}</em></span>
                  <span><b>输出</b><em>{compactValue(tool.output_contract.display_mode)}</em></span>
                </div>
                <div className="workspace-chip-row">
                  {[...tool.safety_tags, ...tool.capability_tags].slice(0, 7).map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <>

      <section className="workspace-section orchestration-dry-run">
        <div className="workspace-section__head">
          <BrainCircuit size={18} />
          <h3>行为逻辑 Dry-run</h3>
          <span className="tag-chip">不调用模型</span>
          <span className="tag-chip">不执行工具</span>
          <span className="tag-chip">不写记忆</span>
        </div>
        <div className="orchestration-dry-run__body">
          <textarea
            onChange={(event) => setDryRunMessage(event.target.value)}
            placeholder="输入一句用户请求，推演 Agent 会怎样理解、路由、选择 skill、读取上下文和预检工具契约..."
            value={dryRunMessage}
          />
          <button className="action-button action-button--primary" disabled={dryRunLoading || !currentSessionId} onClick={() => void submitDryRun()} type="button">
            {dryRunLoading ? <Loader2 className="animate-spin" size={15} /> : <Route size={15} />}
            开始推演
          </button>
        </div>
      </section>

      <section className={`orchestration-hero orchestration-hero--${snapshot.status}`}>
        <div className="orchestration-hero__signal">
          <span>{sourceLabel(snapshot.source)}</span>
          <strong>{problemNode ? `问题在 #${problemNode.index}：${problemNode.label}` : `这轮会走：${readableRoute}`}</strong>
          <p>{problemNode ? problemNode.summary || snapshot.summary : snapshot.summary}</p>
        </div>
        <div className="orchestration-hero__metrics">
          <span><b>{snapshot.execution_mode || "unknown"}</b> 执行模式</span>
          <span><b>{snapshot.route || "unknown"}</b> 路由</span>
          <span><b>{visitedCount}/{snapshot.nodes.length}</b> 节点经过</span>
          <span><b>{String(orchestrationDiff.status ?? orchestrationPlan.mode ?? "plan_only")}</b> plan</span>
          <span><b>{snapshot.events.length}</b> 事件</span>
        </div>
      </section>

      {Object.keys(orchestrationPlan).length ? (
        <section className="workspace-section orchestration-contract-panel">
          <div className="workspace-section__head">
            <ShieldCheck size={18} />
            <h3>正式编排契约</h3>
            <span className={`tag-chip ${validationDecision.status === "blocked" ? "tag-chip--danger" : ""}`}>
              校验：{String(validationDecision.status ?? "未校验")}
            </span>
            <span className="tag-chip">{String(orchestrationPlan.mode ?? "plan_only")}</span>
          </div>
          <div className="orchestration-contract-panel__grid">
            <article className="orchestration-contract-panel__card orchestration-contract-panel__card--focus">
              <span>IntentFrame</span>
              <strong>{String(intentFrame.task_kind ?? "未知任务")}</strong>
              <p>{String(intentFrame.user_goal ?? snapshot.summary ?? "等待用户目标。")}</p>
              <div>
                {toStringList(intentFrame.source_needs).map((item) => <em key={item}>{item}</em>)}
              </div>
            </article>
            <article className="orchestration-contract-panel__card">
              <span>MemoryPolicy</span>
              <strong>{String(memoryPolicy.read_mode ?? "none")} / {String(memoryPolicy.write_mode ?? "none")}</strong>
              <p>{Boolean(memoryPolicy.ignore_memory) ? "本轮忽略记忆。" : `恢复候选：${compactValue(memoryPolicy.restored_candidates)}，写回范围：${compactValue(memoryPolicy.writeback_scope)}`}</p>
            </article>
            <article className="orchestration-contract-panel__card">
              <span>ContextPolicy</span>
              <strong>{compactValue(contextPolicy.required_handles)} 句柄</strong>
              <p>{String(contextPolicy.summary ?? "上下文由 runtime 装配。")}</p>
              <div>
                {toStringList(contextPolicy.prompt_sections).slice(0, 5).map((item) => <em key={item}>{item}</em>)}
              </div>
            </article>
            <article className="orchestration-contract-panel__card">
              <span>ResourcePolicy</span>
              <strong>{compactValue(resourcePolicy.allowed_tools)} 工具 / {compactValue(resourcePolicy.allowed_agents)} 智能体</strong>
              <p>来源权限：{toStringList(resourcePolicy.allowed_sources).join("、") || "默认"}</p>
              <div>
                {toStringList(resourcePolicy.blocked_tools).slice(0, 4).map((item) => <em className="is-danger" key={item}>{item}</em>)}
              </div>
            </article>
            <article className="orchestration-contract-panel__card">
              <span>AnswerPolicy</span>
              <strong>{Boolean(answerPolicy.require_citations) ? "需要引用" : "普通收口"}</strong>
              <p>{Boolean(answerPolicy.hide_internal_protocol) ? "隐藏内部协议。" : "允许显示内部协议。"} {Boolean(answerPolicy.memory_writeback_allowed) ? "允许记忆写回。" : "不写长期记忆。"}</p>
            </article>
            <article className={`orchestration-contract-panel__card ${validationIssues.length ? "orchestration-contract-panel__card--alert" : ""}`}>
              <span>ValidationDecision</span>
              <strong>{validationIssues.length ? `${validationIssues.length} 个问题` : "通过基础校验"}</strong>
              <p>{validationIssues[0] ? `${String(validationIssues[0].code ?? "issue")}：${String(validationIssues[0].detail ?? "")}` : "directive 可被 runtime control 读取；plan-only 下不会改变执行。"}</p>
            </article>
            <article className={`orchestration-contract-panel__card ${runtimeControl.status === "fallback" ? "orchestration-contract-panel__card--alert" : ""}`}>
              <span>RuntimeControl</span>
              <strong>{runtimeControl.title}</strong>
              <p>{runtimeControl.detail}</p>
              <div>
                <em>{runtimeControl.source}</em>
                {toStringList(runtimeDiagnostics.allowlist_blockers).slice(0, 4).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                {toStringList(runtimeDiagnostics.contract_blockers).slice(0, 4).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                {runtimeDiagnostics.validation_status ? <em>validation={String(runtimeDiagnostics.validation_status)}</em> : null}
              </div>
              {runtimeExecutionMismatches.length ? (
                <ul className="orchestration-runtime-mismatch-list">
                  {runtimeExecutionMismatches.slice(0, 4).map((item, index) => (
                    <li key={`${item.execution_id}-${item.field}-${index}`}>
                      <b>{item.execution_id || `step-${index + 1}`}</b>
                      <span>{item.field}</span>
                      <code>{item.planned || "-"}</code>
                      <i>旧执行：{item.legacy || "-"}</i>
                    </li>
                  ))}
                </ul>
              ) : null}
              {runtimeExecutionEntries.length ? (
                <div className="orchestration-runtime-entry-list">
                  {runtimeExecutionEntries.slice(0, 4).map((item, index) => (
                    <span key={`${item.execution_id || item.step_id}-${index}`}>
                      <b>{item.step_id || item.execution_id}</b>
                      {item.entry_kind || "entry"}
                      {item.tool || item.worker_route || item.agent_id ? ` -> ${item.tool || item.worker_route || item.agent_id}` : ""}
                      {item.source ? ` / ${item.source}` : ""}
                    </span>
                  ))}
                </div>
              ) : null}
            </article>
          </div>
          {executionDirectives.length ? (
            <div className="orchestration-directive-strip">
              {executionDirectives.map((directive, index) => (
                <article key={`${String(directive.step_id ?? "step")}-${index}`}>
                  <span>#{index + 1} {String(directive.action ?? "directive")}</span>
                  <strong>{String(directive.tool || directive.worker_route || directive.agent_id || "主链回答")}</strong>
                  <p>{String(directive.input_summary ?? "")}</p>
                  <div>
                    {toStringList(directive.risk_tags).map((item) => <em key={item}>{item}</em>)}
                    {toStringList(directive.shared_channels).map((item) => <em key={item}>{item}</em>)}
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="orchestration-brief">
        <article className="orchestration-brief__card orchestration-brief__card--primary">
          <span>行为结论</span>
          <strong>{readableRoute}</strong>
          <p>{executionNode?.summary || "等待 planner 产出执行落点。"}</p>
        </article>
        <article className="orchestration-brief__card">
          <span>上下文策略</span>
          <strong>{contextNode?.status === "skipped" ? "跳过" : contextNode?.label || "未记录"}</strong>
          <p>{contextNode?.summary || "还没有上下文选择信息。"}</p>
        </article>
        <article className="orchestration-brief__card">
          <span>能力策略</span>
          <strong>{skillNode?.summary?.split("/")[0] || skillNode?.label || "未选择"}</strong>
          <p>{skillNode?.summary || "还没有 skill / capability 信息。"}</p>
        </article>
        <article className={`orchestration-brief__card ${problemNode ? "orchestration-brief__card--alert" : ""}`}>
          <span>{problemNode ? "当前阻断" : "契约边界"}</span>
          <strong>{problemNode ? `#${problemNode.index} ${problemNode.label}` : contractNode?.status || "正常"}</strong>
          <p>{problemNode?.summary || contractNode?.summary || "没有发现明显契约阻断。"}</p>
        </article>
        <article className={`orchestration-brief__card ${orchestrationDiff.status === "mismatch" ? "orchestration-brief__card--alert" : ""}`}>
          <span>计划校验</span>
          <strong>{String(orchestrationDiff.status ?? orchestrationPlan.mode ?? "未生成")}</strong>
          <p>{String(orchestrationDiff.summary ?? orchestrationPlan.plan_id ?? "等待 orchestration plan / diff。")}</p>
        </article>
        <article className={`orchestration-brief__card ${executionMismatches.length ? "orchestration-brief__card--alert" : ""}`}>
          <span>分支校验</span>
          <strong>{executionMismatches.length ? `${executionMismatches.length} 个偏移` : `${executionBranchCount || "-"} 条分支`}</strong>
          <p>{executionMismatches[0] ? `${executionMismatches[0].field}: ${compactValue(executionMismatches[0].expected)} → ${compactValue(executionMismatches[0].actual)}` : "每条 execution 的数量、类型、tool、worker route 已纳入 diff。"}</p>
        </article>
      </section>

      {executionDiffItems.length || branchDiagnostics.length ? (
        <section className="workspace-section orchestration-execution-diff">
          <div className="workspace-section__head">
            <GitBranch size={18} />
            <h3>执行分支校验</h3>
            <span className={executionMismatches.length ? "tag-chip tag-chip--danger" : "tag-chip"}>{executionMismatches.length ? `${executionMismatches.length} 个偏移` : "matched"}</span>
            <span className="tag-chip">{executionBranchCount || 0} branches</span>
          </div>
          <div className="orchestration-execution-diff__grid">
            {branchDiagnostics.map((branch) => {
              const plannedLabel = branch.planned.worker_route || branch.planned.tool_name || branch.planned.execution_kind || "planned";
              const actualLabel = branch.actual.worker_route || branch.actual.tool_name || branch.actual.execution_kind || branch.actual.status || "actual";
              const outputPreview = branch.actual.summary_preview || branch.actual.content_preview || branch.planned.query || "";
              const assemblySelected = Boolean(branch.actual.task_id && answerAssemblySelectedTaskIds.has(branch.actual.task_id));
              const branchKey = branch.index >= 0 ? `branch-${branch.index}` : "branch-count";
              const branchFilter = buildExecutionEventFilter(branch.index, branch.planned, branch.actual);
              const isSelectedBranch = Boolean(selectedExecutionFilter && branchFilter && selectedExecutionFilter.index === branchFilter.index);
              return (
                <button
                  className={`orchestration-execution-card orchestration-execution-card--${branch.status} ${isSelectedBranch ? "orchestration-execution-card--selected" : ""}`}
                  key={branchKey}
                  onClick={() => {
                    setSelectedNodeId(branch.actual.worker_route ? "worker" : branch.actual.tool_name ? "tool" : "execution");
                    setSelectedExecutionFilter(branchFilter);
                  }}
                  type="button"
                >
                  <span>{branch.index >= 0 ? `分支 #${branch.index + 1}` : "分支数量"}</span>
                  <strong>{branch.actual.execution_id || branch.planned.execution_id || "未定位 execution"}</strong>
                  <p>{plannedLabel} → {actualLabel}</p>
                  <div className="orchestration-execution-card__meta">
                    <em>{branch.actual.status || branch.status}</em>
                    {branch.actual.task_id ? <em>{branch.actual.task_id}</em> : null}
                    {branch.actual.bundle_item_id ? <em>{branch.actual.bundle_item_id}</em> : null}
                    {branch.actual.output_chars ? <em>{branch.actual.output_chars} 字</em> : null}
                    {assemblySelected ? <em>进入最终答案</em> : null}
                  </div>
                  {outputPreview ? (
                    <blockquote className="orchestration-execution-card__preview">
                      {outputPreview}
                    </blockquote>
                  ) : null}
                  {branch.items.length ? (
                    <div className="orchestration-execution-card__items">
                      {branch.items.slice(0, 4).map((item) => (
                        <small className={`orchestration-diff-pill orchestration-diff-pill--${item.status}`} key={item.field}>
                          {executionFieldName(item.field)}: {compactValue(item.expected)} / {compactValue(item.actual)}
                        </small>
                      ))}
                    </div>
                  ) : (
                    <small className="orchestration-diff-pill orchestration-diff-pill--matched">没有字段偏移</small>
                  )}
                </button>
              );
            })}
          </div>
          {executionMismatches.length ? (
            <div className="orchestration-execution-diff__mismatches">
              {executionMismatches.slice(0, 6).map((item) => (
                <span key={`${item.field}-${item.reason}`}>
                  <b>{item.field}</b>
                  <em>{compactValue(item.expected)} → {compactValue(item.actual)}{item.reason ? ` / ${item.reason}` : ""}</em>
                </span>
              ))}
            </div>
          ) : null}
          {answerAssembly.answer_source ? (
            <div className="orchestration-answer-assembly">
              <span>输出汇总</span>
              <strong>{Number(answerAssembly.selected_count ?? 0)} 条分支进入最终答案</strong>
              <p>{String(answerAssembly.content_preview ?? "最终答案内容预览暂不可用。")}</p>
              {answerAssemblySelectedTaskIds.size ? (
                <div>
                  {Array.from(answerAssemblySelectedTaskIds).map((taskId) => <em key={taskId}>{taskId}</em>)}
                </div>
              ) : null}
              {answerAssemblyDropped.length ? (
                <div className="orchestration-answer-assembly__drops">
                  {answerAssemblyDropped.slice(0, 4).map((item, index) => (
                    <small key={`${item.task_id || item.title}-${index}`}>
                      <b>{item.task_id || item.title || `drop-${index + 1}`}</b>
                      <span>{item.reason}{item.detail ? ` · ${item.detail}` : ""}</span>
                    </small>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="workspace-section orchestration-map">
        <div className="workspace-section__head">
          <GitBranch size={18} />
          <h3>行为路径</h3>
          {snapshot.run_id ? <span className="tag-chip">{snapshot.run_id}</span> : null}
          {snapshot.turn_index ? <span className="tag-chip">Turn {snapshot.turn_index}</span> : null}
        </div>
        <div className="orchestration-stage-grid">
          {stageGroups.map((group) => {
            const groupNodes = group.nodes.map((id) => nodeById.get(id)).filter(Boolean) as OrchestrationNode[];
            if (!groupNodes.length) {
              return null;
            }
            const activeCount = groupNodes.filter((node) => node.status !== "idle" && node.status !== "skipped").length;
            return (
              <article className="orchestration-stage" key={group.title}>
                <header>
                  <span>{group.title}</span>
                  <strong>{activeCount}/{groupNodes.length}</strong>
                  <p>{group.hint}</p>
                </header>
                <div className="orchestration-stage__nodes">
                  {groupNodes.map((node) => (
                    <button
                      className={`orchestration-node orchestration-node--${node.status} ${selectedNode?.id === node.id ? "orchestration-node--selected" : ""}`}
                      data-orchestration-node-id={node.id}
                      key={node.id}
                      onClick={() => {
                        setSelectedNodeId(node.id);
                        setSelectedExecutionFilter(null);
                      }}
                      type="button"
                    >
                      <span>#{String(node.index).padStart(2, "0")}</span>
                      <i>{nodeIcon(node.id)}</i>
                      <strong>{node.label}</strong>
                      {node.source_module ? <small>{node.source_module}</small> : null}
                      <em>{node.summary || node.description}</em>
                    </button>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
        <div className="orchestration-branches">
          {branchNodes.length ? branchNodes.map((node) => (
            <button
              className={`orchestration-branch orchestration-branch--${node.status} ${selectedNode?.id === node.id ? "orchestration-branch--selected" : ""}`}
              data-orchestration-node-id={node.id}
              key={node.id}
              onClick={() => {
                setSelectedNodeId(node.id);
                setSelectedExecutionFilter(null);
              }}
              type="button"
            >
              <span>{nodeIcon(node.id)} 分支节点 #{node.index}</span>
              <strong>{node.label}</strong>
              {node.source_module ? <small>{node.source_module}</small> : null}
              <p>{node.summary || node.description}</p>
            </button>
          )) : (
            <article className="orchestration-branch orchestration-branch--idle">
              <span><TerminalSquare size={16} /> 分支节点</span>
              <strong>本轮未观测到工具或 worker 分支</strong>
              <p>如果请求触发 direct tool、模型工具调用或 evidence worker，这里会展开对应分支。</p>
            </article>
          )}
        </div>
      </section>

      <section className="orchestration-detail-grid">
        <article className="workspace-section orchestration-detail">
          <div className="workspace-section__head">
            <FileText size={18} />
            <h3>节点详情</h3>
            {selectedNode ? <span className="tag-chip">#{selectedNode.index} {selectedNode.status}</span> : null}
          </div>
          {selectedNode ? (
            <>
              <span>{selectedNode.source_event || "没有绑定单一事件"}</span>
              <strong>{selectedNode.label}</strong>
              <p>{selectedNode.description}</p>
              <pre>{selectedNode.summary || "这个节点在当前链路中还没有产生摘要。"}</pre>
              {selectedReasonList.length ? (
                <div className="orchestration-reasons">
                  {selectedReasonList.map((reason) => <span key={reason}>{reason}</span>)}
                </div>
              ) : null}
              {selectedOutputPreview.length ? (
                <div className="orchestration-kv">
                  {selectedOutputPreview.map(([key, value]) => (
                    <span key={key}>
                      <b>{key}</b>
                      <em>{compactValue(value)}</em>
                    </span>
                  ))}
                </div>
              ) : null}
              {selectedPromptSections.length ? (
                <div className="orchestration-prompt-assembly">
                  <div className="orchestration-prompt-assembly__head">
                    <span>上下文装配来源</span>
                    <strong>{selectedPromptSections.length} 个片段</strong>
                  </div>
                  {selectedPromptSections.map((section) => (
                    <article className="orchestration-prompt-section" key={`${section.order}-${section.id}`}>
                      <div>
                        <span>#{section.order} · {section.layer}</span>
                        <strong>{section.title}</strong>
                        <em>第 {section.order} 段</em>
                      </div>
                      <div className="orchestration-prompt-section__meta">
                        <span>{section.chars} 字</span>
                        <span>{section.model_visible ? "模型可见" : "仅调试"}</span>
                      </div>
                      {section.preview ? <p>{section.preview}</p> : <p>这一段暂无可展示内容。</p>}
                    </article>
                  ))}
                </div>
              ) : null}
              {selectedDetails ? (
                <details className="orchestration-json">
                  <summary>查看原始决策数据</summary>
                  <pre>{jsonText(selectedDetails)}</pre>
                </details>
              ) : null}
              <div className="orchestration-detail__actions">
                <button onClick={() => locateOnSystemGraph(selectedNode)} type="button">
                  <Network size={14} />
                  系统框架定位
                </button>
                {selectedNode.id === "memory" ? (
                  <button onClick={openMemoryNode} type="button">
                    <BrainCircuit size={14} />
                    查看状态记忆
                  </button>
                ) : null}
                {selectedNode.id === "tool" ? (
                  <button onClick={() => setWorkspaceView("operations")} type="button">
                    <TerminalSquare size={14} />
                    查看工具管理
                  </button>
                ) : null}
                {selectedNode.id === "worker" ? (
                  <button onClick={() => setWorkspaceView("evidence")} type="button">
                    <Network size={14} />
                    查看 agent 系统
                  </button>
                ) : null}
              </div>
            </>
          ) : null}
        </article>

        <article className="workspace-section orchestration-events">
          <div className="workspace-section__head">
            <Route size={18} />
            <h3>事件时间线</h3>
            <span className="tag-chip">{snapshot.events.length} events</span>
            {selectedExecutionFilter ? <span className="tag-chip">{filteredEvents.length} matched</span> : null}
          </div>
          {selectedExecutionFilter ? (
            <div className="orchestration-event-filter">
              <span>正在查看分支 #{selectedExecutionFilter.index + 1}</span>
              <strong>{selectedExecutionFilter.label}</strong>
              <p>{Object.entries(selectedExecutionFilter.markers).map(([key, value]) => `${key}=${value}`).join(" · ")}</p>
              <button onClick={() => setSelectedExecutionFilter(null)} type="button">查看全部事件</button>
            </div>
          ) : null}
          <div className="orchestration-events__list">
            {filteredEvents.length ? filteredEvents.map((event) => (
              <button
                className={`orchestration-event ${selectedNode?.id === event.node_id ? "orchestration-event--active" : ""}`}
                key={`${event.index}-${event.event}`}
                onClick={() => setSelectedNodeId(event.node_id)}
                type="button"
              >
                <span>{event.index}</span>
                <strong>{event.event}</strong>
                <ArrowRight size={13} />
                <em>{event.summary}</em>
              </button>
            )) : selectedExecutionFilter ? (
              <article className="workspace-record">
                <h3>这个分支还没有匹配到事件</h3>
                <p>当前测试产物里没有带上这些分支标识，可能需要在 runtime 事件中补充 task_id、execution_id 或 bundle_item_id。</p>
                <button onClick={() => setSelectedExecutionFilter(null)} type="button">查看全部事件</button>
              </article>
            ) : (
              <article className="workspace-record">
                <h3>{snapshot.source === "dry-run" ? "这是无副作用行为推演" : "还没有运行事件"}</h3>
                <p>{snapshot.source === "dry-run" ? "dry-run 不产生 SSE 时间线，请在左侧节点详情里查看每个行为决策。" : "发送一条消息后，这里会出现 SSE 编排事件；也可以从测试系统选择 turn 来复盘。"}</p>
              </article>
            )}
          </div>
        </article>
      </section>
        </>
      )}
    </div>
  );
}
