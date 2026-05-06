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
    ["restore", "恢复仲裁", "把记忆与上下文句柄恢复结果投影为候选，并预检是否允许采用。"],
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
  if (nodeId === "memory" || nodeId === "restore") {
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
    nodes: ["execution-mode", "skill-policy", "context", "memory", "restore", "prompt"]
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
    mode: "primary",
    title: "Primary 控制",
    tone: "active",
    summary: "运行时以 OrchestrationPlan / ExecutionDirective 为唯一执行输入。",
    detail: "缺契约、缺 directive 或 validator 阻断时 fail-closed，不再回旧链路。"
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
  actual: string;
};

type RuntimeExecutionEntry = {
  execution_id: string;
  step_id: string;
  execution_kind: string;
  action: string;
  route: string;
  tool: string;
  worker_route: string;
  skill: string;
  agent_id: string;
  source: string;
  risk_tags: string[];
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
      actual: String(item.actual ?? item.legacy ?? "")
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
      execution_kind: String(item.execution_kind ?? item.entry_kind ?? ""),
      action: String(item.action ?? ""),
      route: String(item.route ?? ""),
      tool: String(item.tool ?? ""),
      worker_route: String(item.worker_route ?? ""),
      skill: String(item.skill ?? ""),
      agent_id: String(item.agent_id ?? ""),
      source: String(item.source ?? ""),
      risk_tags: toStringList(item.risk_tags)
    }))
    .filter((item) => item.execution_id || item.step_id);
}

function runtimeWarningLabel(warning: string) {
  if (warning === "validation_blocked") {
    return "编排校验未通过，已停止执行";
  }
  if (warning === "contract_incomplete") {
    return "正式编排契约不完整，已停止执行";
  }
  if (warning === "execution_directive_missing") {
    return "缺少执行指令，已停止执行";
  }
  if (warning === "execution_candidate_missing") {
    return "执行指令无法匹配候选执行，已停止执行";
  }
  return warning;
}

function runtimeControlSummary(data: Record<string, unknown>) {
  const diagnostics = toRecord(data.diagnostics);
  const warnings = toStringList(data.warnings);
  const primaryActive = Boolean(data.primary_active);
  if (warnings.length) {
    return {
      status: "blocked",
      title: "Fail-closed",
      detail: warnings.map(runtimeWarningLabel).join("；"),
      source: String(data.source ?? "orchestration_blocked"),
      diagnostics
    };
  }
  if (primaryActive) {
    return {
      status: "primary",
      title: "Directive 已接管",
      detail: `执行模式：${String(data.execution_mode ?? "unknown")}`,
      source: String(data.source ?? "orchestration_directive"),
      diagnostics
    };
  }
  return {
    status: "blocked",
    title: "Fail-closed",
    detail: `运行控制源：${String(data.source ?? "unknown")}`,
    source: String(data.source ?? "unknown"),
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
  const currentPlanMode = catalog?.orchestration_plan_mode ?? "primary";
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
  const orchestrationDiagnostics = toRecord(orchestrationPlan.diagnostics);
  const intentFrame = toRecord(orchestrationPlan.intent_frame);
  const intentAuthority = toRecord(orchestrationDiagnostics.intent_authority);
  const intentCandidates = Array.isArray(orchestrationDiagnostics.intent_candidates)
    ? orchestrationDiagnostics.intent_candidates.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
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
  const runtimeExecutionSpecSource = runtimeDiagnostics.execution_specs;
  const phase7Readiness = toRecord(runtimeDiagnostics.phase7_readiness);
  const phase7Decommission = toRecord(phase7Readiness.legacy_decommission);
  const phase7PrincipleAlignment = toRecord(phase7Readiness.principle_alignment);
  const phase7CutoverReadiness = toRecord(phase7Readiness.cutover_readiness);
  const phase7RestoreAuthority = toRecord(phase7Readiness.restore_authority);
  const phase7RestoreAdoptionGate = toRecord(phase7RestoreAuthority.adoption_gate);
  const phase7RestoreCutoverPlan = toRecord(phase7RestoreAuthority.cutover_plan);
  const phase7RestoreDryRunComparison = toRecord(phase7RestoreAuthority.dry_run_comparison);
  const phase8RestoreFormalReview = toRecord(phase7RestoreAuthority.formal_adoption_review);
  const phase8RestoreAdoptionTrace = toRecord(phase7RestoreAuthority.restore_adoption_trace);
  const phase8RestoreShadowPlan = toRecord(phase7RestoreAuthority.restore_shadow_replacement_plan);
  const phase8RestoreShadowComparison = toRecord(phase7RestoreAuthority.restore_shadow_comparison);
  const phase8RestoreRealShadowGate = toRecord(phase7RestoreAuthority.restore_real_shadow_consumer_gate);
  const phase8RestoreShadowContract = toRecord(phase7RestoreAuthority.restore_shadow_consumer_contract);
  const phase8RestoreShadowControl = toRecord(phase7RestoreAuthority.restore_shadow_consumer_control);
  const phase8RestoreShadowConsumerObservation = toRecord(phase7RestoreAuthority.restore_shadow_consumer_observation);
  const phase8RestoreLegacyDecommission = toRecord(phase7RestoreAuthority.restore_legacy_decommission_plan);
  const phase8RestoreAuthorityContextGate = toRecord(phase7RestoreAuthority.restore_authority_context_gate);
  const phase7OutputAuthority = toRecord(phase7Readiness.output_authority);
  const phase7OutputCutoverPlan = toRecord(phase7OutputAuthority.cutover_plan);
  const phase7DispatchAuthority = toRecord(phase7Readiness.dispatch_authority);
  const phase7DispatchCutoverPlan = toRecord(phase7DispatchAuthority.cutover_plan);
  const phase7ReadinessBlockers = toStringList(phase7Readiness.blockers);
  const phase7LegacyAuthorities = toStringList(phase7Readiness.legacy_authorities);
  const phase7PrincipleBlockers = toStringList(phase7PrincipleAlignment.blockers);
  const phase7CutoverBlockers = toStringList(phase7CutoverReadiness.blockers);
  const phase7CutoverGateBlockers = toStringList(phase7CutoverReadiness.gate_blockers);
  const phase7CutoverTopBlockers = toStringList(phase7CutoverReadiness.top_blockers);
  const phase7CutoverDomains = Array.isArray(phase7CutoverReadiness.domains)
    ? phase7CutoverReadiness.domains.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase7CutoverDomainSummaries = Array.isArray(phase7CutoverReadiness.domain_summaries)
    ? phase7CutoverReadiness.domain_summaries.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase7CutoverMigrationTasks = Array.isArray(phase7CutoverReadiness.migration_tasks)
    ? phase7CutoverReadiness.migration_tasks.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase7RestoreBlockers = toStringList(phase7RestoreAuthority.blockers);
  const phase7OutputBlockers = toStringList(phase7OutputAuthority.blockers);
  const phase7OutputWritebackScope = toStringList(phase7OutputAuthority.writeback_scope);
  const phase7DispatchBlockers = toStringList(phase7DispatchAuthority.blockers);
  const phase7RestoreCandidates = Array.isArray(phase7RestoreAuthority.candidates)
    ? phase7RestoreAuthority.candidates.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase7RestoreAdoptionDecisions = Array.isArray(phase7RestoreAuthority.adoption_decisions)
    ? phase7RestoreAuthority.adoption_decisions.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreFormalDecisions = Array.isArray(phase8RestoreFormalReview.decisions)
    ? phase8RestoreFormalReview.decisions.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreTraceEntries = Array.isArray(phase8RestoreAdoptionTrace.traces)
    ? phase8RestoreAdoptionTrace.traces.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreShadowCandidates = Array.isArray(phase8RestoreShadowPlan.replacement_candidates)
    ? phase8RestoreShadowPlan.replacement_candidates.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreShadowObservations = Array.isArray(phase8RestoreShadowComparison.shadow_observations)
    ? phase8RestoreShadowComparison.shadow_observations.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreRealShadowInterfaces = Array.isArray(phase8RestoreRealShadowGate.runtime_interfaces)
    ? phase8RestoreRealShadowGate.runtime_interfaces.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreRealShadowPlan = Array.isArray(phase8RestoreRealShadowGate.candidate_plan)
    ? phase8RestoreRealShadowGate.candidate_plan.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreShadowContractCandidates = Array.isArray(phase8RestoreShadowContract.contract_candidates)
    ? phase8RestoreShadowContract.contract_candidates.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreShadowConsumerObservations = Array.isArray(phase8RestoreShadowConsumerObservation.observations)
    ? phase8RestoreShadowConsumerObservation.observations.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase8RestoreLegacyDecommissionTargets = Array.isArray(phase8RestoreLegacyDecommission.targets)
    ? phase8RestoreLegacyDecommission.targets.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const phase7LegacyPowerDomains = Array.isArray(phase7PrincipleAlignment.legacy_power_domains)
    ? phase7PrincipleAlignment.legacy_power_domains.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const runtimeExecutionMismatches = useMemo(
    () => toRuntimeExecutionMismatches(runtimeDiagnostics.execution_mismatches),
    [runtimeDiagnostics.execution_mismatches]
  );
  const runtimeExecutionEntries = useMemo(
    () => toRuntimeExecutionEntries(runtimeExecutionSpecSource),
    [runtimeExecutionSpecSource]
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
      restore: ["query-core", "memory"],
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
    return `${skill.runtime.name} ${skill.runtime.title} ${skill.runtime.description} ${skill.runtime.capability_tags.join(" ")} ${skill.runtime.supported_task_kinds.join(" ")} ${skill.runtime.supported_source_kinds.join(" ")}`
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
                    className="action-button action-button--primary"
                    disabled={catalogLoading || !catalog || active || !supported}
                    onClick={() => void changeOrchestrationPlanMode(item.mode)}
                    type="button"
                  >
                    {active ? "已启用" : `切换到 ${item.mode}`}
                  </button>
                </article>
              );
            })}
          </div>
          <div className="orchestration-runtime-ledger">
            <article>
              <b>主路径</b>
              <span>RuntimeControl 只读取 OrchestrationPlan / ExecutionDirective，不再排序或接管旧执行列表。</span>
            </article>
            <article>
              <b>阻断边界</b>
              <span>缺契约、缺 directive、validator blocked、候选匹配失败都会 fail-closed。</span>
            </article>
            <article>
              <b>执行输入</b>
              <span>QueryPlanner 只保留候选生成职责，真实执行顺序由 directive specs 决定。</span>
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
            <input onChange={(event) => setCatalogQuery(event.target.value)} placeholder="查 skill、能力标签、任务类型或 route" value={catalogQuery} />
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
                  {skill.runtime.capability_tags.slice(0, 6).map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
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
              <span>编排层现在只暴露 primary 主路径，RuntimeControl 以 validated directive 驱动执行。</span>
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
          <span><b>{String(orchestrationDiff.status ?? orchestrationPlan.mode ?? "primary")}</b> plan</span>
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
            <span className="tag-chip">{String(orchestrationPlan.mode ?? "primary")}</span>
          </div>
          <div className="orchestration-contract-panel__grid">
            <article className="orchestration-contract-panel__card orchestration-contract-panel__card--focus">
              <span>IntentFrame</span>
              <strong>{String(intentFrame.task_kind ?? "未知任务")}</strong>
              <p>{String(intentFrame.user_goal ?? snapshot.summary ?? "等待用户目标。")}</p>
              <div>
                {toStringList(intentFrame.source_needs).map((item) => <em key={item}>{item}</em>)}
                {intentAuthority.state ? <em>理解层：{String(intentAuthority.state)}</em> : null}
                {intentAuthority.legacy_still_executes ? <em className="is-danger">旧 planner 仍执行</em> : null}
              </div>
              {intentCandidates.length ? (
                <small>候选来源：{intentCandidates.map((item) => String(item.owner_module || item.source || "candidate")).slice(0, 2).join("、")}</small>
              ) : null}
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
              <p>{validationIssues[0] ? `${String(validationIssues[0].code ?? "issue")}：${String(validationIssues[0].detail ?? "")}` : "directive 可被 runtime control 读取并驱动执行。"}</p>
            </article>
            <article className={`orchestration-contract-panel__card ${runtimeControl.status === "blocked" ? "orchestration-contract-panel__card--alert" : ""}`}>
              <span>RuntimeControl</span>
              <strong>{runtimeControl.title}</strong>
              <p>{runtimeControl.detail}</p>
              <div>
                <em>{runtimeControl.source}</em>
                {toStringList(runtimeDiagnostics.allowlist_blockers).slice(0, 4).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                {toStringList(runtimeDiagnostics.contract_blockers).slice(0, 4).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                {runtimeDiagnostics.validation_status ? <em>validation={String(runtimeDiagnostics.validation_status)}</em> : null}
                {runtimeDiagnostics.execution_spec_count !== undefined ? <em>执行 spec：{String(runtimeDiagnostics.execution_spec_count)}</em> : null}
                {toStringList(runtimeDiagnostics.directive_sources).map((item) => <em key={item}>{item}</em>)}
                {phase7Readiness.state ? <em className={phase7Readiness.state === "blocked" ? "is-danger" : ""}>Phase7准备：{String(phase7Readiness.state)}</em> : null}
                {phase7RestoreAuthority.state ? <em>恢复权力：{String(phase7RestoreAuthority.state)}</em> : null}
                {phase7OutputAuthority.state ? <em>输出写回：{String(phase7OutputAuthority.state)}</em> : null}
                {phase7DispatchAuthority.state ? <em>调度权力：{String(phase7DispatchAuthority.state)}</em> : null}
                {phase7CutoverReadiness.state ? <em className={phase7CutoverReadiness.state === "blocked" ? "is-danger" : ""}>切换门禁：{String(phase7CutoverReadiness.state)}</em> : null}
                {phase7PrincipleAlignment.state ? <em className={phase7PrincipleAlignment.state === "blocked" ? "is-danger" : ""}>准则校准：{String(phase7PrincipleAlignment.state)}</em> : null}
              </div>
              {phase7Readiness.state ? (
                <div className="orchestration-phase-readiness">
                  <b>{String(phase7Readiness.reason || "phase7_readiness")}</b>
                  <p>{String(phase7Readiness.safe_next_step || "当前只做准备诊断，不改变运行路径。")}</p>
                  {phase7ReadinessBlockers.length ? (
                    <div>
                      {phase7ReadinessBlockers.slice(0, 5).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                    </div>
                  ) : null}
                  {phase7LegacyAuthorities.length ? (
                    <small>旧决策点：{phase7LegacyAuthorities.slice(0, 3).join("、")}</small>
                  ) : null}
                  {phase7Decommission.state ? (
                    <small>旧链路清理：{String(phase7Decommission.state)}，删除允许：{phase7Decommission.delete_allowed ? "是" : "否"}</small>
                  ) : null}
                  {phase7PrincipleAlignment.state ? (
                    <small>架构准则：{String(phase7PrincipleAlignment.reason || "phase7e_principle_alignment_required")}</small>
                  ) : null}
                </div>
              ) : null}
              {phase7PrincipleAlignment.state ? (
                <div className="orchestration-phase-readiness">
                  <b>Phase 7E 架构校准：{String(phase7PrincipleAlignment.state)}</b>
                  <p>{String(phase7PrincipleAlignment.next_safe_phase || "只允许做诊断、权力归档和迁移计划。")}</p>
                  {phase7PrincipleBlockers.length ? (
                    <div>
                      {phase7PrincipleBlockers.slice(0, 6).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                    </div>
                  ) : null}
                  {phase7LegacyPowerDomains.length ? (
                    <small>
                      权力域：{phase7LegacyPowerDomains.slice(0, 4).map((item) => `${String(item.module || "")}=${toStringList(item.domains).join("/")}`).join("、")}
                    </small>
                  ) : null}
                </div>
              ) : null}
              {phase7CutoverReadiness.state ? (
                <div className="orchestration-phase-readiness">
                  <b>Phase 7L 五域切换门禁：{String(phase7CutoverReadiness.state)}</b>
                  <p>{String(phase7CutoverReadiness.human_summary || phase7CutoverReadiness.next_safe_step || "五个权力域全部 ready 前，不允许删除旧链路或扩大接管范围。")}</p>
                  {phase7CutoverTopBlockers.length ? (
                    <div>
                      {phase7CutoverTopBlockers.slice(0, 6).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                    </div>
                  ) : null}
                  <small>
                    域数量：{String(phase7CutoverReadiness.domain_count ?? 0)}；
                    阻断域：{String(phase7CutoverReadiness.blocked_domain_count ?? 0)}；
                    接管允许：{phase7CutoverReadiness.takeover_allowed ? "是" : "否"}；
                    删除允许：{phase7CutoverReadiness.delete_allowed ? "是" : "否"}
                  </small>
                  {phase7CutoverGateBlockers.length ? (
                    <small>总门禁：{phase7CutoverGateBlockers.slice(0, 4).join("、")}</small>
                  ) : null}
                  {phase7CutoverDomainSummaries.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase7CutoverDomainSummaries.map((item) => (
                        <span className={`orchestration-runtime-entry ${item.state === "ready" ? "is-ready" : "is-blocked"}`} key={String(item.domain ?? "domain")}>
                          <b>{String(item.domain ?? "权力域")}</b>
                          <span>{String(item.next_action ?? "等待下一步迁移计划")}</span>
                          <em>{String(item.state ?? "unknown")}</em>
                          <i>{toStringList(item.primary_blockers).slice(0, 2).join("、") || "无阻断"}</i>
                        </span>
                      ))}
                    </div>
                  ) : phase7CutoverDomains.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase7CutoverDomains.map((item) => (
                        <span className={`orchestration-runtime-entry ${item.state === "ready" ? "is-ready" : "is-blocked"}`} key={String(item.domain ?? "domain")}>
                          <b>{String(item.domain ?? "权力域")}</b>
                          <span>{String(item.canonical_owner ?? "orchestration")}</span>
                          <em>{String(item.state ?? "unknown")}</em>
                          <i>{toStringList(item.blockers).slice(0, 2).join("、") || "无阻断"}</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase7CutoverMigrationTasks.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase7CutoverMigrationTasks.slice(0, 5).map((item) => (
                        <span className="orchestration-runtime-entry is-blocked" key={String(item.task_id ?? item.domain ?? "migration")}>
                          <b>{String(item.domain ?? "迁移任务")}</b>
                          <span>{String(item.target ?? "编排切换任务")}</span>
                          <em>优先级 {String(item.priority ?? "-")}</em>
                          <i>{String(item.safe_rule ?? "只做诊断，不改变运行行为。")}</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {!phase7CutoverTopBlockers.length && phase7CutoverBlockers.length ? (
                    <small>完整阻断：{phase7CutoverBlockers.slice(0, 4).join("、")}</small>
                  ) : null}
                </div>
              ) : null}
              {phase7RestoreAuthority.state ? (
                <div className="orchestration-phase-readiness">
                  <b>Phase 7F 恢复权力：{String(phase7RestoreAuthority.state)}</b>
                  <p>{String(phase7RestoreAuthority.rule || "恢复层只能提交候选，不得覆盖当前轮 IntentFrame。")}</p>
                  <div>
                    {phase7RestoreBlockers.slice(0, 5).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                  </div>
                  <small>
                    候选数：{String(phase7RestoreAuthority.candidate_count ?? 0)}；
                    覆盖当前轮：{phase7RestoreAuthority.current_turn_override_allowed ? "允许" : "禁止"}；
                    采用门禁：{String(phase7RestoreAdoptionGate.state ?? "未评估")}；
                    迁移计划：{String(phase7RestoreCutoverPlan.state ?? "未生成")}；
                    对照：{String(phase7RestoreDryRunComparison.state ?? "未生成")}；
                    正式裁决：{String(phase8RestoreFormalReview.state ?? "未生成")}；
                    采纳追踪：{String(phase8RestoreAdoptionTrace.state ?? "未生成")}；
                    影子替换：{String(phase8RestoreShadowPlan.state ?? "未生成")}；
                    只读对照：{String(phase8RestoreShadowComparison.state ?? "未生成")}；
                    真实影子门禁：{String(phase8RestoreRealShadowGate.state ?? "未生成")}；
                    观测契约：{String(phase8RestoreShadowContract.state ?? "未生成")}；
                    运行开关：{String(phase8RestoreShadowControl.state ?? "未生成")} / {String(phase8RestoreShadowControl.mode ?? "disabled")}；
                    只读观测：{String(phase8RestoreShadowConsumerObservation.state ?? "未生成")}；
                    旧链路退场：{String(phase8RestoreLegacyDecommission.state ?? "未生成")}；
                    Planner 入口门：{String(phase8RestoreAuthorityContextGate.state ?? "未生成")}
                  </small>
                  {phase8RestoreAuthorityContextGate.state ? (
                    <div className="orchestration-runtime-entry-list">
                      <span className={`orchestration-runtime-entry ${phase8RestoreAuthorityContextGate.state === "orchestration_filtered" ? "is-ready" : "is-blocked"}`}>
                        <b>Planner 恢复入口</b>
                        <span>{String(phase8RestoreAuthorityContextGate.replacement_seam ?? "RestoreAuthorityContextGate")}</span>
                        <em>{String(phase8RestoreAuthorityContextGate.state)}</em>
                        <i>
                          进入 planner：{toStringList(phase8RestoreAuthorityContextGate.filtered_keys).join("、") || "无"}；
                          恢复候选：{toStringList(phase8RestoreAuthorityContextGate.candidate_keys).join("、") || toStringList(phase8RestoreAuthorityContextGate.legacy_keys).join("、") || "无"}
                        </i>
                      </span>
                    </div>
                  ) : null}
                  {phase8RestoreLegacyDecommissionTargets.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreLegacyDecommissionTargets.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.state === "ready_for_first_cut_review" || item.state === "removed" ? "is-ready" : "is-blocked"}`} key={String(item.target_id ?? item.legacy_entry ?? "restore-decommission")}>
                          <b>{String(item.target_id ?? "旧恢复入口")}</b>
                          <span>{String(item.legacy_entry ?? "legacy restore")}</span>
                          <em>{String(item.state ?? "blocked")}</em>
                          <i>{String(item.replacement_seam ?? "编排恢复 seam")}；删除仍需单独门禁</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreShadowConsumerObservations.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreShadowConsumerObservations.slice(0, 4).map((item) => (
                        <span className="orchestration-runtime-entry is-ready" key={String(item.candidate_id ?? item.replacement_point ?? "restore-shadow-observation-runtime")}>
                          <b>{String(item.replacement_point ?? "只读观测")}</b>
                          <span>{String(item.legacy_consumer ?? "旧恢复消费")}</span>
                          <em>{String(item.observation_state ?? "captured_observe_only")}</em>
                          <i>{String(item.comparison ?? "等待对照")}；未写入状态</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreShadowContractCandidates.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreShadowContractCandidates.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.consumer_state === "observe_only_ready" ? "is-ready" : "is-blocked"}`} key={String(item.candidate_id ?? item.replacement_point ?? "restore-shadow-contract")}>
                          <b>{String(item.replacement_point ?? "观测契约")}</b>
                          <span>{String(item.legacy_consumer ?? "旧恢复消费")}</span>
                          <em>{String(item.consumer_state ?? "blocked")}</em>
                          <i>只读观测：不写状态，不接管，不删除旧链路</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreRealShadowInterfaces.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreRealShadowInterfaces.slice(0, 4).map((item) => (
                        <span className="orchestration-runtime-entry is-blocked" key={String(item.interface ?? "restore-shadow-interface")}>
                          <b>{String(item.interface ?? "影子接口")}</b>
                          <span>{String(item.owner ?? "编排层")}</span>
                          <em>{item.required_before_enable ? "启用前必需" : "可选"}</em>
                          <i>{String(item.purpose ?? "真实 shadow consumer 的安全接口")}</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreRealShadowPlan.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreRealShadowPlan.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.design_status === "ready_for_interface_design" ? "is-ready" : "is-blocked"}`} key={String(item.candidate_id ?? item.replacement_point ?? "restore-shadow-design")}>
                          <b>{String(item.replacement_point ?? "设计候选")}</b>
                          <span>{String(item.legacy_consumer ?? "旧恢复消费")}</span>
                          <em>{String(item.design_status ?? "blocked")}</em>
                          <i>{String(item.comparison ?? "等待对照")}；启用仍禁止</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreShadowObservations.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreShadowObservations.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.comparison === "shadow_matches_legacy_observation" ? "is-ready" : "is-blocked"}`} key={String(item.candidate_id ?? item.replacement_point ?? "restore-shadow-observation")}>
                          <b>{String(item.replacement_point ?? "只读对照")}</b>
                          <span>{String(item.shadow_state ?? "shadow")} / {String(item.legacy_consumer ?? "旧恢复消费")}</span>
                          <em>{String(item.comparison ?? "observed")}</em>
                          <i>{String(item.shadow_value ?? "无影子观测值")}；不写状态</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreShadowCandidates.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreShadowCandidates.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.shadow_status === "eligible_for_shadow" ? "is-ready" : "is-blocked"}`} key={String(item.candidate_id ?? item.replacement_point ?? "restore-shadow")}>
                          <b>{String(item.replacement_point ?? "影子替换")}</b>
                          <span>{String(item.legacy_consumer ?? "旧恢复消费")} 到 {String(item.target_owner ?? "编排恢复")}</span>
                          <em>{String(item.shadow_status ?? "blocked")}</em>
                          <i>{String(item.alignment ?? "等待对照")}；只读影子，不接管</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreTraceEntries.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreTraceEntries.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.status === "ready_for_shadow_replacement" ? "is-ready" : "is-blocked"}`} key={String(item.trace_id ?? item.candidate_id ?? "restore-trace")}>
                          <b>{String(item.replacement_point ?? "替换点")}</b>
                          <span>{String(item.candidate_type ?? "恢复候选")} / {String(item.legacy_consumer ?? "旧消费点")}</span>
                          <em>{String(item.status ?? "observed")}</em>
                          <i>{String(item.alignment ?? "未对齐")}；目标：{String(item.target_owner ?? "编排恢复裁决")}</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase8RestoreFormalDecisions.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase8RestoreFormalDecisions.slice(0, 4).map((item) => (
                        <span className={`orchestration-runtime-entry ${item.decision === "accepted" ? "is-ready" : "is-blocked"}`} key={String(item.candidate_id ?? "formal-restore")}>
                          <b>{String(item.candidate_type ?? "恢复候选")}</b>
                          <span>{String(item.owner_module ?? "unknown")}</span>
                          <em>{String(item.decision ?? "unknown")}</em>
                          <i>{toStringList(item.blockers).join("、") || String(item.reason ?? "已通过正式裁决")}</i>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {phase7RestoreCandidates.length ? (
                    <div className="orchestration-runtime-entry-list">
                      {phase7RestoreCandidates.slice(0, 4).map((item, index) => (
                        <span className="orchestration-runtime-entry is-blocked" key={String(item.candidate_id ?? `restore-${index}`)}>
                          {(() => {
                            const adoptionDecision = toRecord(phase7RestoreAdoptionDecisions[index]);
                            const memoryContextValidation = toRecord(adoptionDecision.memory_context_validation);
                            const decisionLabel = adoptionDecision.decision ? String(adoptionDecision.decision) : "";
                            const validationLabel = memoryContextValidation.status ? String(memoryContextValidation.status) : "";
                            return (
                              <>
                          <b>{String(item.candidate_type ?? "恢复候选")}</b>
                          <span>{String(item.owner_module ?? item.source ?? "unknown")}</span>
                          <em>{String(item.adoption_state ?? "candidate")}</em>
                          <i>
                            {String(item.value ?? "-")}
                            {decisionLabel ? ` / ${decisionLabel}` : ""}
                            {validationLabel ? ` / 校验${validationLabel}` : ""}
                          </i>
                              </>
                            );
                          })()}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {runtimeExecutionMismatches.length ? (
                <ul className="orchestration-runtime-mismatch-list">
                  {runtimeExecutionMismatches.slice(0, 4).map((item, index) => (
                    <li key={`${item.execution_id}-${item.field}-${index}`}>
                      <b>{item.execution_id || `step-${index + 1}`}</b>
                      <span>{item.field}</span>
                      <code>{item.planned || "-"}</code>
                      <i>实际：{item.actual || "-"}</i>
                    </li>
                  ))}
                </ul>
              ) : null}
              {runtimeExecutionEntries.length ? (
                <div className="orchestration-runtime-entry-list">
                  {runtimeExecutionEntries.slice(0, 4).map((item, index) => (
                    <span
                      className="orchestration-runtime-entry is-ready"
                      key={`${item.execution_id || item.step_id}-${index}`}
                    >
                      <b>{item.step_id || item.execution_id}</b>
                      <span>{item.execution_kind || item.action || "entry"}{item.source ? ` / ${item.source}` : ""}</span>
                      <em>directive</em>
                      <i>{item.tool || item.worker_route || item.agent_id || "主链回答"}</i>
                      {item.risk_tags.length ? <small>{item.risk_tags.slice(0, 2).join("，")}</small> : null}
                    </span>
                  ))}
                </div>
              ) : null}
              {phase7OutputAuthority.state ? (
                <div className="orchestration-phase-readiness">
                  <b>Phase 7I 输出与写回：{String(phase7OutputAuthority.state)}</b>
                  <p>{String(phase7OutputAuthority.rule || "输出收口与状态写回由 OutputCommitGate 汇总为显式提交计划。")}</p>
                  <div>
                    {phase7OutputBlockers.slice(0, 5).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                  </div>
                  <small>
                    答案通道：{String(phase7OutputAuthority.answer_channel ?? "未记录")}；
                    允许回退：{phase7OutputAuthority.allow_fallback ? "是" : "否"}；
                    写回范围：{phase7OutputWritebackScope.join("、") || "无"}；
                    迁移计划：{String(phase7OutputCutoverPlan.state ?? "未生成")}
                  </small>
                </div>
              ) : null}
              {phase7DispatchAuthority.state ? (
                <div className="orchestration-phase-readiness">
                  <b>Phase 7J 调度权力：{String(phase7DispatchAuthority.state)}</b>
                  <p>{String(phase7DispatchAuthority.rule || "route、tool、worker、agent 的最终接管仍受 RuntimeControl 和旧链路保护。")}</p>
                  <div>
                    {phase7DispatchBlockers.slice(0, 5).map((item) => <em className="is-danger" key={item}>{item}</em>)}
                  </div>
                  <small>
                    route：{String(phase7DispatchAuthority.route ?? "unknown")}；
                    指令数：{String(phase7DispatchAuthority.directive_count ?? 0)}；
                    工具：{String(phase7DispatchAuthority.tool_directive_count ?? 0)}；
                    worker：{String(phase7DispatchAuthority.worker_directive_count ?? 0)}；
                    迁移计划：{String(phase7DispatchCutoverPlan.state ?? "未生成")}
                  </small>
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
                  <button onClick={() => setWorkspaceView("capability-system")} type="button">
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

