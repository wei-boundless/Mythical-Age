"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  FileText,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  PauseCircle,
  PencilLine,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  StepForward,
} from "lucide-react";

import {
  createGraphTaskInstance,
  getGraphTaskInstanceFileTree,
  getWritingGraphInstanceDesk,
  listGraphTaskInstances,
  listGraphTasks,
  pauseGraphRun,
  readGraphTaskInstanceFile,
  resumeGraphRun,
  startGraphTaskInstanceRun,
  submitGraphRunUntilIdle,
  submitGraphTaskInstanceHumanEdgeDecision,
  submitWritingGraphChapterAction,
  writeGraphTaskInstanceFile,
  type GraphTaskDefinitionSummary,
  type HumanEdgeControlView,
  type HumanEdgeDecisionKind,
  type GraphTaskInstanceHumanControls,
  type GraphTaskInstanceFileTree,
  type GraphTaskInstanceMonitor,
  type GraphTaskInstanceSummary,
  type SessionScope,
  type SessionSummary,
  type WritingChapterAction,
  type WritingGraphInstanceDesk,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Notice } from "@/ui/Notice";
import { WritingChapterDesk } from "./WritingChapterDesk";

type GraphTaskForegroundViewProps = {
  requestedGraphId?: string;
};

type FileTreeNode = {
  children: FileTreeNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

type FileEditorMode = "edit" | "preview";
type InstanceFilter = "all" | "active" | "attention" | "idle" | "success";
type AssetTab = "library" | "artifacts";
type ConsoleScreen = "monitor" | "sessions";

type NodeRuntimeCard = {
  artifactCount: number;
  detail: string;
  nodeId: string;
  scopeLabel: string;
  session: SessionSummary | null;
  status: string;
  title: string;
  updatedAt: unknown;
};

const INSTANCE_FILTERS: Array<{ label: string; value: InstanceFilter }> = [
  { label: "全部", value: "all" },
  { label: "运行", value: "active" },
  { label: "关注", value: "attention" },
  { label: "待启动", value: "idle" },
  { label: "完成", value: "success" },
];

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function numberValue(value: unknown, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function normalizedQuery(value: string) {
  return value.trim().toLowerCase();
}

function timestampValue(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return numeric > 10_000_000_000 ? numeric : numeric * 1000;
}

function timestampLabel(value: unknown) {
  const numeric = timestampValue(value);
  if (!numeric) return "-";
  return new Date(numeric).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(value: unknown) {
  const status = stringValue(value, "idle").toLowerCase();
  const labels: Record<string, string> = {
    idle: "未启动",
    created: "已创建",
    pending: "等待中",
    queued: "排队中",
    ready: "就绪",
    running: "运行中",
    dispatching: "派发中",
    blocked: "阻塞",
    paused: "已暂停",
    failed: "失败",
    error: "错误",
    completed: "已完成",
    done: "已完成",
    success: "成功",
    stopped: "已停止",
  };
  return labels[status] ?? status;
}

function statusTone(value: unknown) {
  const status = stringValue(value, "idle").toLowerCase();
  if (["running", "dispatching", "pending", "queued", "ready"].includes(status)) return "active";
  if (["blocked", "failed", "error"].includes(status)) return "attention";
  if (["completed", "done", "success"].includes(status)) return "success";
  if (["paused", "stopped"].includes(status)) return "paused";
  return "idle";
}

function nestedRecord(value: unknown, key: string): Record<string, unknown> {
  return recordOf(recordOf(value)[key]);
}

function graphConfigIdFromMonitor(monitor: GraphTaskInstanceMonitor | null, instance: GraphTaskInstanceSummary | null) {
  const graphMonitor = monitor?.graph_monitor;
  const config = recordOf(graphMonitor?.graph_harness_config);
  const metadata = recordOf(instance?.metadata);
  return stringValue(
    config.config_id
      ?? config.graph_harness_config_id
      ?? metadata.latest_graph_harness_config_id,
  );
}

function graphRunIdFromMonitor(monitor: GraphTaskInstanceMonitor | null, instance: GraphTaskInstanceSummary | null) {
  return stringValue(monitor?.graph_monitor?.graph_run_id ?? instance?.active_graph_run_id);
}

function graphTaskRunIdFromMonitor(monitor: GraphTaskInstanceMonitor | null, instance: GraphTaskInstanceSummary | null) {
  const graphMonitor = monitor?.graph_monitor;
  const taskRun = recordOf(graphMonitor?.task_run);
  const taskRunMonitor = recordOf(graphMonitor?.task_run_monitor ?? graphMonitor?.runtime_monitor);
  const metadata = recordOf(instance?.metadata);
  return stringValue(
    taskRun.task_run_id
      ?? taskRunMonitor.task_run_id
      ?? metadata.latest_task_run_id,
  );
}

function graphRunControlState(monitor: GraphTaskInstanceMonitor | null) {
  const graphMonitor = monitor?.graph_monitor;
  const taskRun = recordOf(graphMonitor?.task_run);
  const taskRunDiagnostics = recordOf(taskRun.diagnostics);
  const taskRunMonitor = recordOf(graphMonitor?.task_run_monitor ?? graphMonitor?.runtime_monitor);
  const monitorControl = recordOf(taskRunMonitor.runtime_control);
  const taskControl = recordOf(taskRunDiagnostics.runtime_control);
  const graphRunControl = nestedRecord(graphMonitor?.graph_run, "diagnostics");
  const graphControl = recordOf(graphRunControl.runtime_control);
  return stringValue(
    taskRunMonitor.control_state
      ?? monitorControl.state
      ?? taskControl.state
      ?? graphControl.state,
  ).toLowerCase();
}

function graphLoopStatus(monitor: GraphTaskInstanceMonitor | null) {
  return stringValue(recordOf(monitor?.graph_monitor?.graph_loop_state).status);
}

function graphRunStatus(monitor: GraphTaskInstanceMonitor | null, instance: GraphTaskInstanceSummary | null) {
  const controlState = graphRunControlState(monitor);
  if (controlState === "paused" || controlState === "pause_requested") return controlState;
  const graphRun = recordOf(monitor?.graph_monitor?.graph_run);
  return stringValue(
    recordOf(monitor?.graph_monitor?.task_run).status
      ?? graphRun.status
      ?? graphLoopStatus(monitor)
      ?? instance?.status,
    "idle",
  ).toLowerCase();
}

function graphRuntimeStatusLabel(value: string) {
  if (value === "pause_requested") return "暂停中";
  if (value === "waiting_executor") return "待续跑";
  if (value === "budget_exhausted" || value === "idle") return "待续跑";
  return statusLabel(value);
}

function graphRuntimeStatusTone(value: string) {
  if (value === "pause_requested" || value === "paused" || value === "waiting_executor" || value === "idle" || value === "budget_exhausted") return "paused";
  return statusTone(value);
}

function graphRunIsTerminal(status: string) {
  return ["completed", "done", "success", "failed", "error", "cancelled", "canceled", "aborted", "stopped"].includes(status);
}

function sortInstances(instances: GraphTaskInstanceSummary[]) {
  return [...instances].sort((left, right) => {
    const priority = tonePriority(statusTone(left.status)) - tonePriority(statusTone(right.status));
    if (priority) return priority;
    return timestampValue(right.updated_at) - timestampValue(left.updated_at);
  });
}

function tonePriority(tone: string) {
  if (tone === "attention") return 0;
  if (tone === "active") return 1;
  if (tone === "paused") return 2;
  if (tone === "idle") return 3;
  if (tone === "success") return 4;
  return 5;
}

function graphTaskScope(instanceId: string): Partial<SessionScope> {
  return {
    workspace_view: "graph_task",
    task_environment_id: "",
    project_id: instanceId,
  };
}

function graphTaskPoolKey(instanceId: string) {
  return `graph_task:${instanceId}` as const;
}

function monitorCounts(monitor: GraphTaskInstanceMonitor | null, writingDesk: WritingGraphInstanceDesk | null) {
  const summary = recordOf(monitor?.summary);
  const deskSummary = recordOf(writingDesk?.summary);
  const monitorSessions = monitor?.node_sessions.length ?? 0;
  const deskSessions = writingDesk?.node_sessions.length ?? 0;
  const monitorArtifacts = monitor?.artifacts.artifacts.length ?? 0;
  const deskArtifacts = writingDesk?.artifacts.artifacts.length ?? 0;
  return {
    ready: numberValue(summary.ready_count),
    running: numberValue(summary.running_count),
    completed: numberValue(summary.completed_count),
    failed: numberValue(summary.failed_count),
    blocked: numberValue(summary.blocked_count),
    sessions: numberValue(summary.node_session_count ?? deskSummary.node_session_count, monitorSessions || deskSessions),
    artifacts: numberValue(summary.artifact_count ?? deskSummary.artifact_count, monitorArtifacts || deskArtifacts),
  };
}

function parseTreeNode(value: unknown): FileTreeNode | null {
  const record = recordOf(value);
  if (!Object.keys(record).length) return null;
  return {
    children: Array.isArray(record.children) ? record.children.map(parseTreeNode).filter((node): node is FileTreeNode => Boolean(node)) : [],
    kind: stringValue(record.kind, "file"),
    name: stringValue(record.name, stringValue(record.path, "root")),
    path: stringValue(record.path),
  };
}

function flattenFileTree(node: FileTreeNode | null): FileTreeNode[] {
  if (!node) return [];
  return [
    ...(node.kind === "file" ? [node] : []),
    ...node.children.flatMap(flattenFileTree),
  ];
}

function isChapterFile(node: FileTreeNode) {
  if (node.kind !== "file") return false;
  const path = node.path.replace(/\\/g, "/").toLowerCase();
  const segments = path.split("/").filter(Boolean);
  const parentSegments = segments.slice(0, -1);
  const fileName = (segments.at(-1) || node.name || "").toLowerCase();
  if (!/\.(?:md|markdown|txt)$/.test(fileName)) return false;
  if (/(?:^|[_.\- ])(?:unit_)?route(?:[_.\- ]|$)/.test(fileName)) return false;
  if (/(?:^|[_.\- ])(?:outline|review|plan|summary)(?:[_.\- ]|$)/.test(fileName)) return false;

  const hasChaptersDir = parentSegments.includes("chapters");
  const hasExactChapterDir = parentSegments.some((segment) => /^chapter[_.\- ]?\d+$/.test(segment));
  const isSimpleChapterFile = /^chapter[_.\- ]?\d+\.(?:md|markdown|txt)$/.test(fileName);
  const isDraftFile = /^draft(?:[_.\- ]round)?(?:[_.\- ]?\d+)?\.(?:md|markdown|txt)$/.test(fileName);
  const isZhChapterFile = /第\s*\d+\s*章/.test(node.name);
  return (
    (hasChaptersDir && isSimpleChapterFile)
    || (hasChaptersDir && hasExactChapterDir && isDraftFile)
    || (hasChaptersDir && isZhChapterFile)
  );
}

function sessionNodeLabel(session: SessionSummary) {
  const scope = recordOf(session.scope);
  const binding = recordOf(session.task_binding);
  return stringValue(
    binding.node_id
    ?? binding.graph_node_id
    ?? scope.node_id
    ?? recordOf(session.conversation_state).node_id,
    "",
  );
}

function sessionRoleLabel(session: SessionSummary) {
  return stringValue(recordOf(session).session_role) === "root" ? "项目主会话" : "节点会话";
}

function artifactMatches(artifact: Record<string, unknown>, query: string) {
  if (!query) return true;
  return [
    artifact.name,
    artifact.path,
    artifact.artifact_id,
    artifact.kind,
    artifact.type,
  ].map((value) => String(value ?? "").toLowerCase()).join(" ").includes(query);
}

function artifactNodeId(artifact: Record<string, unknown>) {
  return stringValue(
    artifact.node_id
    ?? artifact.source_node_id
    ?? artifact.graph_node_id
    ?? recordOf(artifact.metadata).node_id,
    "",
  );
}

function nodeIdFromRuntimeView(view: Record<string, unknown>, index: number) {
  return stringValue(
    view.node_id
    ?? view.graph_node_id
    ?? view.id
    ?? recordOf(view.node).node_id
    ?? recordOf(view.work_order).node_id,
    `node_${index + 1}`,
  );
}

function nodeTitleFromRuntimeView(view: Record<string, unknown>, nodeId: string) {
  return stringValue(
    view.title
    ?? view.label
    ?? view.node_title
    ?? recordOf(view.node).title
    ?? recordOf(view.node).label,
    nodeId,
  );
}

function nodeStatusFromRuntimeView(view: Record<string, unknown>) {
  return stringValue(
    view.status
    ?? view.state
    ?? view.phase
    ?? recordOf(view.runtime).status
    ?? recordOf(view.work_order).status,
    "idle",
  );
}

function nodeDetailFromRuntimeView(view: Record<string, unknown>) {
  return stringValue(
    view.summary
    ?? view.public_summary
    ?? view.detail
    ?? view.message
    ?? view.last_output
    ?? recordOf(view.runtime).summary,
    "等待运行信号。",
  );
}

function runtimeScopeLabel(view: Record<string, unknown>) {
  return stringValue(
    view.subgraph_id
    ?? view.active_subgraph_id
    ?? view.scope_id
    ?? view.scope_ref
    ?? view.phase_id
    ?? view.phase_ref
    ?? view.frame_id
    ?? view.unit_id
    ?? view.group_id
    ?? view.module_id
    ?? recordOf(view.runtime).scope_id
    ?? recordOf(view.runtime).phase_id
    ?? recordOf(view.work_order).scope_id
    ?? recordOf(view.work_order).phase_id,
    "",
  );
}

function buildNodeRuntimeCards(monitor: GraphTaskInstanceMonitor | null, writingDesk: WritingGraphInstanceDesk | null): NodeRuntimeCard[] {
  const graphMonitor = monitor?.graph_monitor;
  const runtimeViews = Array.isArray(graphMonitor?.active_node_runtime_views)
    ? graphMonitor.active_node_runtime_views
    : [];
  const workOrders = Array.isArray(graphMonitor?.active_node_work_orders)
    ? graphMonitor.active_node_work_orders
    : [];
  const byNode = new Map<string, NodeRuntimeCard>();
  const sessions = monitor?.node_sessions.length ? monitor.node_sessions : writingDesk?.node_sessions ?? [];
  const artifacts = monitor?.artifacts.artifacts.length ? monitor.artifacts.artifacts : writingDesk?.artifacts.artifacts ?? [];

  runtimeViews.forEach((view, index) => {
    const nodeId = nodeIdFromRuntimeView(view, index);
    byNode.set(nodeId, {
      artifactCount: artifacts.filter((artifact) => artifactNodeId(artifact) === nodeId).length,
      detail: nodeDetailFromRuntimeView(view),
      nodeId,
      scopeLabel: runtimeScopeLabel(view),
      session: sessions.find((session) => sessionNodeLabel(session) === nodeId) ?? null,
      status: nodeStatusFromRuntimeView(view),
      title: nodeTitleFromRuntimeView(view, nodeId),
      updatedAt: view.updated_at ?? view.timestamp ?? monitor?.instance.updated_at,
    });
  });

  workOrders.forEach((workOrder, index) => {
    const nodeId = stringValue(workOrder.node_id ?? workOrder.graph_node_id, `work_order_${index + 1}`);
    if (byNode.has(nodeId)) return;
    byNode.set(nodeId, {
      artifactCount: artifacts.filter((artifact) => artifactNodeId(artifact) === nodeId).length,
      detail: stringValue(workOrder.summary ?? workOrder.detail ?? workOrder.status, "已收到工作单。"),
      nodeId,
      scopeLabel: runtimeScopeLabel(workOrder),
      session: sessions.find((session) => sessionNodeLabel(session) === nodeId) ?? null,
      status: stringValue(workOrder.status ?? workOrder.state, "ready"),
      title: stringValue(workOrder.title ?? workOrder.node_title, nodeId),
      updatedAt: workOrder.updated_at ?? monitor?.instance.updated_at,
    });
  });

  sessions.forEach((session, index) => {
    const nodeId = sessionNodeLabel(session) || (stringValue(recordOf(session).session_role) === "root" ? "project_root" : `session_${index + 1}`);
    if (byNode.has(nodeId)) return;
    byNode.set(nodeId, {
      artifactCount: artifacts.filter((artifact) => artifactNodeId(artifact) === nodeId).length,
      detail: `${sessionRoleLabel(session)} · ${session.message_count ?? 0} 条消息`,
      nodeId,
      scopeLabel: "",
      session,
      status: stringValue(recordOf(session).status, "idle"),
      title: session.title || nodeId,
      updatedAt: session.updated_at ?? monitor?.instance.updated_at,
    });
  });

  return Array.from(byNode.values()).sort((left, right) => {
    const priority = tonePriority(statusTone(left.status)) - tonePriority(statusTone(right.status));
    if (priority) return priority;
    return timestampValue(right.updatedAt) - timestampValue(left.updatedAt);
  });
}

function defaultInstanceId(instances: GraphTaskInstanceSummary[], current: string) {
  if (current && instances.some((instance) => instance.graph_task_instance_id === current)) return current;
  const active = instances.find((instance) => statusTone(instance.status) === "active");
  const attention = instances.find((instance) => statusTone(instance.status) === "attention");
  const paused = instances.find((instance) => statusTone(instance.status) === "paused");
  return (active ?? attention ?? paused ?? instances[0])?.graph_task_instance_id ?? "";
}

function defaultGraphId(graphs: GraphTaskDefinitionSummary[], current: string, requested: string) {
  if (requested && graphs.some((graph) => graph.graph_id === requested)) return requested;
  if (current && graphs.some((graph) => graph.graph_id === current)) return current;
  return (
    graphs.find((graph) => graph.graph_id === "graph.writing.modular_novel.master")
    ?? graphs.find((graph) => graph.graph_id.includes("writing"))
    ?? graphs[0]
  )?.graph_id ?? "";
}

function humanControlItemsFromControls(controls: GraphTaskInstanceHumanControls | null | undefined): HumanEdgeControlView[] {
  const pending = Array.isArray(controls?.pending) ? controls.pending : [];
  const available = Array.isArray(controls?.available) ? controls.available : [];
  const byId = new Map<string, HumanEdgeControlView>();
  [...pending, ...available].forEach((control, index) => {
    const controlId = stringValue(control.control_id, `${control.graph_run_id}:${control.edge_id}:${index}`);
    byId.set(controlId, { ...control, control_id: controlId });
  });
  return Array.from(byId.values());
}

function humanControlItems(monitor: GraphTaskInstanceMonitor | null): HumanEdgeControlView[] {
  return humanControlItemsFromControls(monitor?.human_controls);
}

function humanDecisionHistory(monitor: GraphTaskInstanceMonitor | null): Array<Record<string, unknown>> {
  const history = monitor?.human_controls?.history;
  return Array.isArray(history) ? history : [];
}

function humanDecisionHistoryFromControls(controls: GraphTaskInstanceHumanControls | null | undefined): Array<Record<string, unknown>> {
  const history = controls?.history;
  return Array.isArray(history) ? history : [];
}

function decisionLabel(control: HumanEdgeControlView | null, decision: HumanEdgeDecisionKind) {
  const label = control?.decision_labels?.[decision];
  if (label) return label;
  if (decision === "pass") return "通过并传给下游";
  if (decision === "revise") return "退稿并回传上游";
  return "我来替写并继续";
}

function writingDecisionLabel(decision: HumanEdgeDecisionKind) {
  if (decision === "pass") return "通过本章";
  if (decision === "revise") return "退稿给写手";
  return "采用我的改写稿";
}

function writingDrawerTitle(decision: HumanEdgeDecisionKind) {
  if (decision === "pass") return "通过本章";
  if (decision === "revise") return "退稿意见";
  return "采用改写稿";
}

function controlTitle(control: HumanEdgeControlView) {
  return `${control.source_node_id || "上游"} -> ${control.target_node_id || "下游"}`;
}

function instanceMatches(instance: GraphTaskInstanceSummary, filter: InstanceFilter, query: string) {
  if (filter !== "all" && statusTone(instance.status) !== filter) return false;
  if (!query) return true;
  return [
    instance.title,
    instance.description,
    instance.graph_task_instance_id,
    instance.graph_id,
    instance.status,
  ].map((value) => String(value ?? "").toLowerCase()).join(" ").includes(query);
}

export function GraphTaskForegroundView({ requestedGraphId = "" }: GraphTaskForegroundViewProps) {
  const {
    bindTaskGraphMonitorRun,
    currentSessionId,
    selectSession,
    setTaskGraphRunInteractionOpen,
  } = useAppStore();
  const [graphs, setGraphs] = useState<GraphTaskDefinitionSummary[]>([]);
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [instances, setInstances] = useState<GraphTaskInstanceSummary[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [monitor, setMonitor] = useState<GraphTaskInstanceMonitor | null>(null);
  const [writingDesk, setWritingDesk] = useState<WritingGraphInstanceDesk | null>(null);
  const [fileTree, setFileTree] = useState<GraphTaskInstanceFileTree | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [newFilePath, setNewFilePath] = useState("input/brief.md");
  const [newFileContent, setNewFileContent] = useState("");
  const [fileSearch, setFileSearch] = useState("");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [graphSearch, setGraphSearch] = useState("");
  const [instanceSearch, setInstanceSearch] = useState("");
  const [instanceFilter, setInstanceFilter] = useState<InstanceFilter>("all");
  const [fileEditorMode, setFileEditorMode] = useState<FileEditorMode>("preview");
  const [assetTab, setAssetTab] = useState<AssetTab>("library");
  const [consoleScreen, setConsoleScreen] = useState<ConsoleScreen>("sessions");
  const [readerFocusMode, setReaderFocusMode] = useState(false);
  const [selectedHumanControlId, setSelectedHumanControlId] = useState("");
  const [selectedChapterAction, setSelectedChapterAction] = useState<WritingChapterAction | null>(null);
  const [decisionDrawerOpen, setDecisionDrawerOpen] = useState(false);
  const [decisionKind, setDecisionKind] = useState<HumanEdgeDecisionKind>("pass");
  const [decisionInstruction, setDecisionInstruction] = useState("");
  const [decisionReplacePath, setDecisionReplacePath] = useState("");
  const [decisionReplaceContent, setDecisionReplaceContent] = useState("");
  const [newInstanceTitle, setNewInstanceTitle] = useState("");
  const [newInstanceDescription, setNewInstanceDescription] = useState("");
  const [loadingGraphs, setLoadingGraphs] = useState(false);
  const [loadingInstances, setLoadingInstances] = useState(false);
  const [loadingWritingDesk, setLoadingWritingDesk] = useState(false);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selectedGraph = useMemo(
    () => graphs.find((graph) => graph.graph_id === selectedGraphId) ?? graphs[0] ?? null,
    [graphs, selectedGraphId],
  );
  const selectedInstance = useMemo(
    () => instances.find((instance) => instance.graph_task_instance_id === selectedInstanceId)
      ?? monitor?.instance
      ?? null,
    [instances, monitor, selectedInstanceId],
  );
  const counts = monitorCounts(monitor, writingDesk);
  const totalNodeCount = counts.ready + counts.running + counts.completed + counts.failed + counts.blocked;
  const progressPercent = totalNodeCount ? Math.round((counts.completed / totalNodeCount) * 100) : 0;
  const nodeCards = useMemo(() => buildNodeRuntimeCards(monitor, writingDesk), [monitor, writingDesk]);
  const selectedNode = useMemo(
    () => nodeCards.find((node) => node.nodeId === selectedNodeId) ?? nodeCards[0] ?? null,
    [nodeCards, selectedNodeId],
  );
  const focusLabel = useMemo(() => {
    if (!selectedInstance) return "先选择项目实例";
    if (!nodeCards.length) return "自动跟随当前活跃子图";
    const activeNodes = nodeCards.filter((node) => ["active", "attention"].includes(statusTone(node.status)));
    const focusNodes = activeNodes.length ? activeNodes : nodeCards;
    const scope = focusNodes.map((node) => node.scopeLabel).find(Boolean);
    const nodeText = `${focusNodes.length} 个节点信号`;
    return scope ? `自动跟随 ${scope} · ${nodeText}` : `自动跟随活跃节点组 · ${nodeText}`;
  }, [nodeCards, selectedInstance]);
  const artifacts = monitor?.artifacts.artifacts.length ? monitor.artifacts.artifacts : writingDesk?.artifacts.artifacts ?? [];
  const latestArtifact = useMemo(
    () => [...artifacts].sort((left, right) => timestampValue(right.updated_at) - timestampValue(left.updated_at))[0] ?? null,
    [artifacts],
  );
  const filteredGraphs = useMemo(() => {
    const query = normalizedQuery(graphSearch);
    if (!query) return graphs;
    return graphs.filter((graph) => `${graph.title} ${graph.graph_id} ${graph.graph_kind}`.toLowerCase().includes(query));
  }, [graphSearch, graphs]);
  const sortedInstances = useMemo(() => sortInstances(instances), [instances]);
  const filteredInstances = useMemo(() => {
    const query = normalizedQuery(instanceSearch);
    return sortedInstances.filter((instance) => instanceMatches(instance, instanceFilter, query));
  }, [instanceFilter, instanceSearch, sortedInstances]);
  const filteredArtifacts = useMemo(() => {
    const query = normalizedQuery(artifactSearch);
    return artifacts.filter((artifact) => artifactMatches(artifact, query));
  }, [artifactSearch, artifacts]);
  const rootTreeNode = useMemo(() => parseTreeNode(fileTree?.tree), [fileTree]);
  const flatFiles = useMemo(() => flattenFileTree(rootTreeNode), [rootTreeNode]);
  const chapterFiles = useMemo(() => flatFiles.filter(isChapterFile), [flatFiles]);
  const projectedChapterFiles = useMemo<FileTreeNode[]>(() => {
    const chapters = Array.isArray(writingDesk?.chapter_index) ? writingDesk.chapter_index : [];
    return chapters
      .filter((chapter) => stringValue(chapter.path))
      .map((chapter) => ({
        children: [],
        kind: "file",
        name: stringValue(chapter.title, stringValue(chapter.path)),
        path: stringValue(chapter.path),
      }));
  }, [writingDesk]);
  const writingChapterFiles = projectedChapterFiles.length ? projectedChapterFiles : chapterFiles;
  const visibleChapterFiles = useMemo(() => {
    const files = writingChapterFiles.length ? writingChapterFiles : flatFiles;
    const query = normalizedQuery(fileSearch);
    if (!query) return files;
    return files.filter((file) => `${file.name} ${file.path}`.toLowerCase().includes(query));
  }, [fileSearch, flatFiles, writingChapterFiles]);
  const selectedFileName = selectedFilePath
    ? selectedFilePath.split(/[\\/]/).filter(Boolean).at(-1) || selectedFilePath
    : "";
  const selectedChapterIndex = useMemo(
    () => visibleChapterFiles.findIndex((file) => file.path === selectedFilePath),
    [selectedFilePath, visibleChapterFiles],
  );
  const previousChapterFile = selectedChapterIndex > 0 ? visibleChapterFiles[selectedChapterIndex - 1] : null;
  const nextChapterFile = selectedChapterIndex >= 0 && selectedChapterIndex < visibleChapterFiles.length - 1
    ? visibleChapterFiles[selectedChapterIndex + 1]
    : null;
  const selectedNodeArtifacts = useMemo(
    () => selectedNode ? artifacts.filter((artifact) => artifactNodeId(artifact) === selectedNode.nodeId).slice(0, 8) : [],
    [artifacts, selectedNode],
  );
  const humanControls = useMemo(
    () => writingDesk?.human_controls ? humanControlItemsFromControls(writingDesk.human_controls) : humanControlItems(monitor),
    [monitor, writingDesk],
  );
  const selectedHumanControl = useMemo(
    () => humanControls.find((control) => control.control_id === selectedHumanControlId) ?? humanControls[0] ?? null,
    [humanControls, selectedHumanControlId],
  );
  const decisionHistory = useMemo(
    () => writingDesk?.human_controls ? humanDecisionHistoryFromControls(writingDesk.human_controls) : humanDecisionHistory(monitor),
    [monitor, writingDesk],
  );
  const chapterActions = useMemo<WritingChapterAction[]>(
    () => Array.isArray(writingDesk?.chapter_actions) ? writingDesk.chapter_actions : [],
    [writingDesk],
  );
  const humanActionCount = humanControls.length;
  const selectedGraphRequiresProjectBrief = Boolean(selectedGraph?.graph_id?.startsWith("graph.writing.modular_novel."));
  const activeGraphRunId = graphRunIdFromMonitor(monitor, selectedInstance);
  const activeGraphHarnessConfigId = graphConfigIdFromMonitor(monitor, selectedInstance);
  const activeGraphTaskRunId = graphTaskRunIdFromMonitor(monitor, selectedInstance);
  const activeGraphControlState = graphRunControlState(monitor);
  const activeGraphRuntimeStatus = graphRunStatus(monitor, selectedInstance);
  const activeGraphRuntimeTone = graphRuntimeStatusTone(activeGraphRuntimeStatus);
  const activeGraphIsPaused = activeGraphControlState === "paused" || activeGraphRuntimeStatus === "paused";
  const activeGraphPausePending = activeGraphControlState === "pause_requested" || activeGraphRuntimeStatus === "pause_requested";
  const activeGraphCanPause = Boolean(
    selectedInstance
      && activeGraphRunId
      && activeGraphHarnessConfigId
      && !activeGraphIsPaused
      && !activeGraphPausePending
      && !graphRunIsTerminal(activeGraphRuntimeStatus),
  );
  const activeGraphCanContinue = Boolean(
    selectedInstance
      && activeGraphRunId
      && activeGraphHarnessConfigId
      && !activeGraphPausePending
      && !graphRunIsTerminal(activeGraphRuntimeStatus),
  );
  const deskSummary = recordOf(writingDesk?.summary);
  const chapterCount = numberValue(deskSummary.chapter_count);
  const graphMonitorEnabled = Boolean(monitor?.graph_monitor);

  const loadGraphs = useCallback(async () => {
    setLoadingGraphs(true);
    setError("");
    try {
      const payload = await listGraphTasks();
      setGraphs(payload.graph_tasks);
      setSelectedGraphId((current) => {
        const requested = requestedGraphId.trim();
        return defaultGraphId(payload.graph_tasks, current, requested);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "图任务定义加载失败");
    } finally {
      setLoadingGraphs(false);
    }
  }, [requestedGraphId]);

  const loadInstances = useCallback(async (graphId: string) => {
    if (!graphId) {
      setInstances([]);
      setSelectedInstanceId("");
      setWritingDesk(null);
      return;
    }
    setLoadingInstances(true);
    setError("");
    try {
      const payload = await listGraphTaskInstances(graphId);
      const sorted = sortInstances(payload.instances);
      setInstances(sorted);
      setSelectedInstanceId((current) => defaultInstanceId(sorted, current));
    } catch (caught) {
      setInstances([]);
      setSelectedInstanceId("");
      setError(caught instanceof Error ? caught.message : "项目实例加载失败");
    } finally {
      setLoadingInstances(false);
    }
  }, []);

  const loadProjectFileTree = useCallback(async (instanceId: string) => {
    if (!instanceId) {
      setFileTree(null);
      return;
    }
    try {
      setFileTree(await getGraphTaskInstanceFileTree(instanceId, { maxDepth: 4, maxEntries: 500 }));
    } catch {
      setFileTree(null);
    }
  }, []);

  const loadWritingDesk = useCallback(async (instanceId: string, options: { adoptReader?: boolean; includeRuntime?: boolean; includeFileTree?: boolean } = {}) => {
    if (!instanceId) {
      setWritingDesk(null);
      return;
    }
    setLoadingWritingDesk(true);
    try {
      const includeRuntime = Boolean(options.includeRuntime);
      const includeFileTree = Boolean(options.includeFileTree);
      const payload = await getWritingGraphInstanceDesk(instanceId, includeRuntime ? 40 : 10, {
        includeRuntime,
        includeFileTree,
      });
      setWritingDesk(payload);
      if (payload.file_tree) {
        setFileTree(payload.file_tree);
      }
      const readerPath = stringValue(payload.reader?.path);
      const readerContent = String(payload.reader?.content ?? "");
      if (readerPath && options.adoptReader) {
        setSelectedFilePath(readerPath);
        setFileContent(readerContent);
        setFileEditorMode("preview");
      }
    } catch (caught) {
      setWritingDesk(null);
      setError(caught instanceof Error ? caught.message : "写作台投影加载失败");
    } finally {
      setLoadingWritingDesk(false);
    }
  }, []);

  const refreshProjectRuntime = useCallback(async (instanceId: string, options: { adoptReader?: boolean } = {}) => {
    if (!instanceId) return;
    await loadWritingDesk(instanceId, { ...options, includeRuntime: false, includeFileTree: false });
  }, [loadWritingDesk]);

  useEffect(() => {
    void loadGraphs();
  }, [loadGraphs]);

  useEffect(() => {
    const requested = requestedGraphId.trim();
    if (!requested) return;
    setSelectedGraphId(requested);
  }, [requestedGraphId]);

  useEffect(() => {
    if (!selectedGraphId) return;
    setMonitor(null);
    setWritingDesk(null);
    setFileTree(null);
    setSelectedFilePath("");
    setFileContent("");
    setSelectedNodeId("");
    setAssetTab("library");
    setConsoleScreen("sessions");
    setReaderFocusMode(false);
    void loadInstances(selectedGraphId);
  }, [loadInstances, selectedGraphId]);

  useEffect(() => {
    if (!selectedInstanceId) {
      setMonitor(null);
      setWritingDesk(null);
      setFileTree(null);
      setSelectedNodeId("");
      return;
    }
    void loadWritingDesk(selectedInstanceId, { adoptReader: true });
  }, [loadWritingDesk, selectedInstanceId]);

  useEffect(() => {
    if (!selectedGraph) return;
    setNewInstanceTitle((current) => current || `${selectedGraph.title || selectedGraph.graph_id} 项目 ${instances.length + 1}`);
  }, [instances.length, selectedGraph]);

  useEffect(() => {
    if (!nodeCards.length) {
      setSelectedNodeId("");
      return;
    }
    setSelectedNodeId((current) => current && nodeCards.some((node) => node.nodeId === current) ? current : nodeCards[0].nodeId);
  }, [nodeCards]);

  useEffect(() => {
    if (!humanControls.length) {
      setSelectedHumanControlId("");
      return;
    }
    setSelectedHumanControlId((current) => (
      current && humanControls.some((control) => control.control_id === current)
        ? current
        : humanControls[0].control_id
    ));
  }, [humanControls]);

  async function createInstance() {
    if (!selectedGraph) return;
    const title = newInstanceTitle.trim() || `${selectedGraph.title || selectedGraph.graph_id} 项目 ${instances.length + 1}`;
    const projectBrief = newInstanceDescription.trim();
    if (selectedGraphRequiresProjectBrief && !projectBrief) {
      setError("写作图任务需要先填写项目启动包。");
      return;
    }
    setAction("create-instance");
    setError("");
    setNotice("");
    try {
      const payload = await createGraphTaskInstance(selectedGraph.graph_id, {
        title,
        description: projectBrief,
        initial_inputs: {
          project_title: title,
          title,
          project_brief: projectBrief,
        },
        metadata: {
          created_from: "graph_task_foreground",
          writing_project: {
            project_title: title,
            project_brief: projectBrief,
          },
        },
      });
      setInstances((current) => sortInstances([
        payload.instance,
        ...current.filter((instance) => instance.graph_task_instance_id !== payload.instance.graph_task_instance_id),
      ]));
      setSelectedInstanceId(payload.instance.graph_task_instance_id);
      setAssetTab("library");
      setConsoleScreen("sessions");
      setNewInstanceTitle("");
      setNewInstanceDescription("");
      setNotice("项目实例已创建。");
      await refreshProjectRuntime(payload.instance.graph_task_instance_id, { adoptReader: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建项目实例失败");
    } finally {
      setAction("");
    }
  }

  async function startRunForInstance(instance: GraphTaskInstanceSummary | null) {
    if (!instance) return;
    setAction("start-run");
    setError("");
    setNotice("");
    try {
      setSelectedInstanceId(instance.graph_task_instance_id);
      const payload = await startGraphTaskInstanceRun(instance.graph_task_instance_id, {
        dispatch_ready: true,
        run_mode: "auto_run",
        wait_for_completion: false,
      });
      const start = payload.start;
      const sessionScope = graphTaskScope(payload.instance.graph_task_instance_id);
      bindTaskGraphMonitorRun({
        task_run_id: start.task_run_id,
        graph_run_id: start.graph_run_id,
        graph_harness_config_id: start.graph_harness_config_id,
        graph_id: payload.instance.graph_id,
        session_id: start.graph_session_id || start.launch_session_id || payload.instance.root_session_id,
        project_id: payload.instance.graph_task_instance_id,
        session_scope: sessionScope,
        title: payload.instance.title || payload.instance.graph_id,
      });
      setTaskGraphRunInteractionOpen(true);
      setInstances((current) => sortInstances(current.map((instance) => (
        instance.graph_task_instance_id === payload.instance.graph_task_instance_id ? payload.instance : instance
      ))));
      setSelectedInstanceId(payload.instance.graph_task_instance_id);
      setConsoleScreen("sessions");
      setNotice("运行已提交后台。");
      await refreshProjectRuntime(payload.instance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "启动图任务运行失败");
    } finally {
      setAction("");
    }
  }

  async function startRun() {
    await startRunForInstance(selectedInstance);
  }

  async function pauseCurrentGraphRun() {
    if (!selectedInstance || !activeGraphRunId || !activeGraphHarnessConfigId) {
      setError("当前项目没有可暂停的图运行。");
      return;
    }
    setAction("pause-run");
    setError("");
    setNotice("");
    try {
      await pauseGraphRun(activeGraphRunId, {
        graph_harness_config_id: activeGraphHarnessConfigId,
        session_scope: graphTaskScope(selectedInstance.graph_task_instance_id),
        reason: "graph_task_foreground_pause",
      });
      setNotice("暂停请求已提交，当前节点到达运行边界后会停在可续跑状态。");
      await refreshProjectRuntime(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "暂停图任务运行失败");
    } finally {
      setAction("");
    }
  }

  async function continueCurrentGraphRun() {
    if (!selectedInstance) return;
    if (!activeGraphRunId || !activeGraphHarnessConfigId) {
      await startRunForInstance(selectedInstance);
      return;
    }
    setAction("continue-run");
    setError("");
    setNotice("");
    try {
      if (activeGraphIsPaused) {
        await resumeGraphRun(activeGraphRunId, {
          graph_harness_config_id: activeGraphHarnessConfigId,
          session_scope: graphTaskScope(selectedInstance.graph_task_instance_id),
          reason: "graph_task_foreground_resume",
        });
      }
      const submission = await submitGraphRunUntilIdle(activeGraphRunId, {
        graph_harness_config_id: activeGraphHarnessConfigId,
        session_scope: graphTaskScope(selectedInstance.graph_task_instance_id),
        max_node_executions: 64,
        max_node_steps: 12,
        max_dispatch_requests: 1,
      });
      const scheduled = Number(submission.scheduled_work_order_count ?? 0);
      const alreadyRunning = Number(submission.already_running_work_order_count ?? 0);
      setNotice(scheduled || alreadyRunning ? "续跑已提交后台。" : "续跑请求已提交，当前没有新的可派发节点。");
      await refreshProjectRuntime(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "续跑图任务运行失败");
    } finally {
      setAction("");
    }
  }

  async function openSession(session: SessionSummary | null) {
    if (!session || !selectedInstance) return;
    await selectSession({
      sessionId: session.id,
      scope: graphTaskScope(selectedInstance.graph_task_instance_id),
      poolKey: graphTaskPoolKey(selectedInstance.graph_task_instance_id),
    });
  }

  async function loadFile(path: string) {
    if (!selectedInstance || !path) return;
    setAction("read-file");
    setError("");
    try {
      const payload = await readGraphTaskInstanceFile(selectedInstance.graph_task_instance_id, path);
      setSelectedFilePath(payload.path);
      setFileContent(payload.content);
      setFileEditorMode("preview");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取项目文件失败");
    } finally {
      setAction("");
    }
  }

  async function saveSelectedFile() {
    if (!selectedInstance || !selectedFilePath.trim()) return;
    setAction("save-file");
    setError("");
    setNotice("");
    try {
      await writeGraphTaskInstanceFile(selectedInstance.graph_task_instance_id, selectedFilePath.trim(), fileContent);
      setNotice(`已保存 ${selectedFilePath.trim()}`);
      await refreshProjectRuntime(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存项目文件失败");
    } finally {
      setAction("");
    }
  }

  async function writeNewFile() {
    if (!selectedInstance || !newFilePath.trim()) return;
    setAction("write-file");
    setError("");
    setNotice("");
    try {
      const payload = await writeGraphTaskInstanceFile(selectedInstance.graph_task_instance_id, newFilePath.trim(), newFileContent);
      setSelectedFilePath(payload.path);
      setFileContent(newFileContent);
      setFileEditorMode("preview");
      setNewFileContent("");
      setNotice(`已写入 ${payload.path}`);
      await refreshProjectRuntime(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "写入项目文件失败");
    } finally {
      setAction("");
    }
  }

  function openHumanDecision(
    control: HumanEdgeControlView | null,
    kind?: HumanEdgeDecisionKind,
    sourceChapterAction: WritingChapterAction | null = null,
  ) {
    if (!control) return;
    const nextKind = kind ?? control.default_decision ?? control.allowed_decisions[0] ?? "pass";
    setSelectedHumanControlId(control.control_id);
    setSelectedChapterAction(sourceChapterAction);
    setDecisionKind(nextKind);
    setDecisionInstruction("");
    setDecisionReplacePath(selectedFilePath || "chapters/chapter-001.md");
    setDecisionReplaceContent(fileContent);
    setDecisionDrawerOpen(true);
  }

  function openChapterAction(chapterAction: WritingChapterAction) {
    const control = humanControls.find((item) => item.control_id === chapterAction.control_id) ?? selectedHumanControl;
    openHumanDecision(control, chapterAction.decision, chapterAction);
  }

  async function submitHumanDecision() {
    if (!selectedInstance || !selectedHumanControl) return;
    if (decisionKind === "revise" && !decisionInstruction.trim()) {
      setError("退稿需要填写回传意见。");
      return;
    }
    const artifactRefs = selectedFilePath.trim()
      ? [{ repository_id: "instance", path: selectedFilePath.trim(), ref_kind: "project_file" }]
      : selectedHumanControl.artifact_refs ?? [];
    const contentSubmission = decisionKind === "replace"
      ? {
          path: decisionReplacePath.trim() || selectedFilePath.trim(),
          content: decisionReplaceContent,
          content_kind: isChapterFile({ children: [], kind: "file", name: decisionReplacePath, path: decisionReplacePath }) ? "chapter" : "document",
          commit_policy: "project_file",
        }
      : null;
    if (decisionKind === "replace" && (!String(contentSubmission?.path || "").trim() || !decisionReplaceContent.trim())) {
      setError("替写需要填写文件路径和内容。");
      return;
    }
    setAction("human-edge-decision");
    setError("");
    setNotice("");
    try {
      const writingAction = selectedChapterAction
        ? selectedChapterAction.decision === decisionKind
          ? selectedChapterAction
          : chapterActions.find((item) => item.control_id === selectedHumanControl.control_id && item.decision === decisionKind) ?? null
        : null;
      if (writingAction) {
        await submitWritingGraphChapterAction(selectedInstance.graph_task_instance_id, {
          action: writingAction.action,
          chapter_id: stringValue(writingDesk?.current_chapter?.chapter_id),
          control_id: selectedHumanControl.control_id,
          instruction: decisionInstruction.trim(),
          content: decisionKind === "replace" ? decisionReplaceContent : "",
          target_path: decisionKind === "replace" ? String(contentSubmission?.path || "") : "",
          apply_now: true,
          metadata: { submitted_from: "writing_chapter_desk" },
        });
      } else {
        await submitGraphTaskInstanceHumanEdgeDecision(selectedInstance.graph_task_instance_id, {
          graph_run_id: selectedHumanControl.graph_run_id,
          edge_id: selectedHumanControl.edge_id,
          decision: decisionKind,
          instruction: decisionInstruction.trim(),
          artifact_refs: artifactRefs,
          content_submission: contentSubmission,
          apply_now: true,
          metadata: { submitted_from: "graph_task_foreground" },
        });
      }
      if (decisionKind === "replace" && contentSubmission?.path) {
        setSelectedFilePath(String(contentSubmission.path));
        setFileContent(decisionReplaceContent);
        await loadProjectFileTree(selectedInstance.graph_task_instance_id);
      }
      await refreshProjectRuntime(selectedInstance.graph_task_instance_id);
      setNotice(`${writingDecisionLabel(decisionKind)}已应用。`);
      setSelectedChapterAction(null);
      setDecisionDrawerOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工传播决策提交失败");
    } finally {
      setAction("");
    }
  }

  const nextAction = !selectedInstance
    ? "先选择或创建项目实例。"
    : activeGraphPausePending
      ? "正在暂停，等待当前节点到达运行边界。"
    : activeGraphIsPaused
      ? "项目已暂停，可以续跑。"
    : humanActionCount
      ? `有 ${humanActionCount} 个边传播动作可处理。`
    : counts.failed || counts.blocked
      ? "优先处理失败或阻塞节点。"
      : activeGraphRuntimeTone === "active"
        ? "运行中，观察节点画布和最新输出。"
        : "项目已就绪，可以启动运行。";
  const hasSelectedInstance = Boolean(selectedInstance);
  const activeInstanceCount = instances.filter((instance) => statusTone(instance.status) === "active").length;
  const attentionInstanceCount = instances.filter((instance) => statusTone(instance.status) === "attention").length;
  const completedInstanceCount = instances.filter((instance) => statusTone(instance.status) === "success").length;

  return (
    <section className={classNames("graph-foreground-shell", hasSelectedInstance ? "graph-foreground-shell--console" : "graph-foreground-shell--manager")} aria-label="图任务前台">
      <header className="graph-foreground-topbar">
        <div>
          <span>{hasSelectedInstance ? "Writing Desk" : "Writing Graph Projects"}</span>
          <strong>{hasSelectedInstance ? selectedInstance?.title : "写作项目台"}</strong>
          <small>{selectedGraph?.title || selectedGraph?.graph_id || "选择写作图任务"} · {instances.length} 个项目实例</small>
        </div>
        <div className="graph-foreground-topbar__actions">
          {hasSelectedInstance ? (
            <button onClick={() => setSelectedInstanceId("")} type="button">
              <LayoutDashboard size={14} />
              <span>项目列表</span>
            </button>
          ) : null}
          <button disabled={loadingGraphs} onClick={() => void loadGraphs()} type="button">
            <RefreshCw size={14} />
            <span>{loadingGraphs ? "刷新中" : "刷新图任务"}</span>
          </button>
          <button disabled={!selectedGraphId || loadingInstances} onClick={() => void loadInstances(selectedGraphId)} type="button">
            <RefreshCw size={14} />
            <span>{loadingInstances ? "加载中" : "刷新项目"}</span>
          </button>
          {selectedInstance ? (
            <button disabled={action === "start-run"} onClick={() => void startRun()} type="button">
              <PlayCircle size={15} />
              <span>{action === "start-run" ? "提交中" : activeGraphRunId ? "启动新运行" : "启动运行"}</span>
            </button>
          ) : null}
        </div>
      </header>

      {error ? <Notice tone="error">{error}</Notice> : null}
      {notice ? <Notice>{notice}</Notice> : null}

      {!selectedInstance ? (
        <div className="graph-foreground-manager">
          <aside className="graph-foreground-graph-dock" aria-label="图任务定义">
            <section className="graph-foreground-panel">
              <header>
                <div>
                  <span>图任务定义</span>
                  <strong>{graphs.length} 张图</strong>
                </div>
                <GitBranch size={15} />
              </header>
              <label className="graph-foreground-search">
                <Search size={14} />
                <input
                  onChange={(event) => setGraphSearch(event.target.value)}
                  placeholder="搜索图任务"
                  value={graphSearch}
                />
              </label>
              <div className="graph-foreground-list graph-foreground-list--graphs">
                {filteredGraphs.map((graph) => {
                  const active = graph.graph_id === selectedGraph?.graph_id;
                  return (
                    <button
                      aria-current={active ? "page" : undefined}
                      className={classNames("graph-foreground-list-row", active && "graph-foreground-list-row--active")}
                      key={graph.graph_id}
                      onClick={() => setSelectedGraphId(graph.graph_id)}
                      type="button"
                    >
                      <strong>{graph.title || graph.graph_id}</strong>
                      <small>{graph.graph_id}</small>
                      <span>{graph.graph_kind || "task_graph"} · {graph.publish_state || "draft"}</span>
                    </button>
                  );
                })}
                {!filteredGraphs.length ? <div className="boundary-empty">没有匹配的图任务定义。</div> : null}
              </div>
            </section>
          </aside>

          <main className="graph-foreground-project-board" aria-label="项目实例管理">
            <section className="graph-foreground-board-head">
              <div>
                <span>当前图任务</span>
                <strong>{selectedGraph?.title || "选择图任务"}</strong>
                <small>{selectedGraph?.graph_id || "选择图后加载项目实例"}</small>
              </div>
              <div className="graph-foreground-board-metrics">
                <span><b>{instances.length}</b>项目</span>
                <span><b>{activeInstanceCount}</b>运行</span>
                <span className={attentionInstanceCount ? "graph-foreground-board-metrics__attention" : undefined}><b>{attentionInstanceCount}</b>关注</span>
                <span><b>{completedInstanceCount}</b>完成</span>
              </div>
            </section>

            <section className="graph-foreground-project-toolbar" aria-label="项目筛选">
              <label className="graph-foreground-search">
                <Search size={14} />
                <input
                  onChange={(event) => setInstanceSearch(event.target.value)}
                  placeholder="搜索项目名称、状态或 id"
                  value={instanceSearch}
                />
              </label>
              <div className="graph-foreground-segmented" role="group" aria-label="项目状态筛选">
                {INSTANCE_FILTERS.map((filter) => (
                  <button
                    aria-pressed={instanceFilter === filter.value}
                    className={instanceFilter === filter.value ? "graph-foreground-segmented__button--active" : undefined}
                    key={filter.value}
                    onClick={() => setInstanceFilter(filter.value)}
                    type="button"
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            </section>

            <section className="graph-foreground-project-table" aria-label="项目实例列表">
              <div className="graph-foreground-project-table__head">
                <span>项目</span>
                <span>状态</span>
                <span>最近更新</span>
                <span>运行</span>
              </div>
              {filteredInstances.map((instance) => {
                const tone = statusTone(instance.status);
                return (
                  <article className={classNames("graph-foreground-project-row", `graph-foreground-project-row--${tone}`)} key={instance.graph_task_instance_id}>
                    <button className="graph-foreground-project-row__title" onClick={() => { setConsoleScreen("sessions"); setSelectedInstanceId(instance.graph_task_instance_id); }} type="button">
                      <strong>{instance.title || instance.graph_task_instance_id}</strong>
                      <small>{instance.graph_task_instance_id}</small>
                    </button>
                    <span className={`graph-foreground-status graph-foreground-status--${tone}`}>{statusLabel(instance.status)}</span>
                    <span>{timestampLabel(instance.updated_at)}</span>
                    <div className="graph-foreground-project-row__actions">
                      <button disabled={action === "start-run"} onClick={() => void startRunForInstance(instance)} type="button">
                        <PlayCircle size={13} />
                        <span>启动</span>
                      </button>
                      <button onClick={() => { setConsoleScreen("sessions"); setSelectedInstanceId(instance.graph_task_instance_id); }} type="button">
                        <MessageSquare size={13} />
                        <span>章节台</span>
                      </button>
                    </div>
                  </article>
                );
              })}
              {!instances.length ? (
                <div className="graph-foreground-compact-empty">
                  <FileText size={20} />
                  <strong>这个图还没有项目实例</strong>
                  <span>在右侧创建项目后进入章节生产台。</span>
                </div>
              ) : null}
              {instances.length && !filteredInstances.length ? <div className="graph-foreground-compact-empty">没有匹配的项目实例。</div> : null}
            </section>
          </main>

          <aside className="graph-foreground-create-dock" aria-label="创建项目实例">
            <section className="graph-foreground-panel graph-foreground-panel--create">
              <header>
                <div>
                  <span>新项目</span>
                  <strong>创建实例</strong>
                </div>
                <Plus size={15} />
              </header>
              <label>
                <span>项目名称</span>
                <input
                  onChange={(event) => setNewInstanceTitle(event.target.value)}
                  placeholder="例如：长篇写作第 1 轮"
                  value={newInstanceTitle}
                />
              </label>
              <label>
                <span>项目启动包</span>
                <textarea
                  onChange={(event) => setNewInstanceDescription(event.target.value)}
                  placeholder="题材、世界核心、主角、风格、硬性约束"
                  rows={7}
                  value={newInstanceDescription}
                />
              </label>
              <button disabled={!selectedGraph || action === "create-instance" || (selectedGraphRequiresProjectBrief && !newInstanceDescription.trim())} onClick={() => void createInstance()} type="button">
                <Plus size={14} />
                <span>{action === "create-instance" ? "创建中" : "创建并进入章节台"}</span>
              </button>
            </section>
          </aside>
        </div>
      ) : (
        <div className="graph-foreground-console">
          <section className="graph-foreground-console-bar" aria-label="项目运行条">
            <div>
              <span>当前项目</span>
              <strong>{selectedInstance.title || selectedInstance.graph_task_instance_id}</strong>
              <small>{activeGraphRunId ? `${selectedInstance.graph_task_instance_id} · ${activeGraphRunId}` : selectedInstance.graph_task_instance_id}</small>
            </div>
            <div className="graph-foreground-console-actions">
              <div className="graph-foreground-console-switch" role="tablist" aria-label="项目控制台屏幕">
                <button aria-selected={consoleScreen === "sessions"} className={consoleScreen === "sessions" ? "graph-foreground-console-switch__active" : undefined} onClick={() => setConsoleScreen("sessions")} type="button">
                  <MessageSquare size={13} />
                  章节台
                </button>
                <button aria-selected={consoleScreen === "monitor"} className={consoleScreen === "monitor" ? "graph-foreground-console-switch__active" : undefined} onClick={() => setConsoleScreen("monitor")} type="button">
                  <GitBranch size={13} />
                  运行信号
                </button>
              </div>
              <em className={`graph-foreground-status graph-foreground-status--${activeGraphRuntimeTone}`}>
                {graphRuntimeStatusLabel(activeGraphRuntimeStatus)}
              </em>
              <div className="graph-foreground-run-controls" aria-label="项目运行控制">
                <button disabled={action === "start-run"} onClick={() => void startRun()} type="button">
                  <PlayCircle size={14} />
                  <span>{action === "start-run" ? "启动中" : activeGraphRunId ? "新运行" : "启动"}</span>
                </button>
                <button disabled={!activeGraphCanPause || action === "pause-run"} onClick={() => void pauseCurrentGraphRun()} type="button">
                  <PauseCircle size={14} />
                  <span>{action === "pause-run" ? "暂停中" : "暂停"}</span>
                </button>
                <button disabled={!activeGraphCanContinue || action === "continue-run"} onClick={() => void continueCurrentGraphRun()} type="button">
                  <StepForward size={14} />
                  <span>{action === "continue-run" ? "提交中" : activeGraphIsPaused ? "续跑" : "继续"}</span>
                </button>
                <button disabled={loadingWritingDesk} onClick={() => void refreshProjectRuntime(selectedInstance.graph_task_instance_id)} type="button">
                  <RefreshCw size={14} />
                  <span>{loadingWritingDesk ? "刷新中" : "刷新"}</span>
                </button>
              </div>
            </div>
          </section>

          {consoleScreen === "monitor" ? (
          <div className="graph-foreground-console-grid">
            <aside className="graph-foreground-node-nav" aria-label="节点导航">
              <header>
                <div>
                  <span>节点</span>
                  <strong>{nodeCards.length} 个信号</strong>
                </div>
                <Bot size={15} />
              </header>
              <div className="graph-foreground-node-list">
                {nodeCards.map((node) => {
                  const active = selectedNode?.nodeId === node.nodeId;
                  const tone = statusTone(node.status);
                  return (
                    <button
                      aria-current={active ? "true" : undefined}
                      className={classNames("graph-foreground-node-list-row", `graph-foreground-node-list-row--${tone}`, active && "graph-foreground-node-list-row--active")}
                      key={node.nodeId}
                      onClick={() => setSelectedNodeId(node.nodeId)}
                      type="button"
                    >
                      <span>{statusLabel(node.status)}</span>
                      <strong>{node.title}</strong>
                      <small>{node.scopeLabel || node.nodeId}</small>
                    </button>
                  );
                })}
                {!nodeCards.length ? <div className="boundary-empty">启动项目后出现节点信号。</div> : null}
              </div>
            </aside>

            <main className="graph-foreground-run-stage" aria-label="运行焦点">
              <section className={classNames(
                "graph-foreground-next-action",
                Boolean(counts.failed || counts.blocked || humanActionCount) && "graph-foreground-next-action--attention",
              )}>
                <div>
                  <span>下一动作</span>
                  <strong>{nextAction}</strong>
                </div>
                {counts.failed || counts.blocked || humanActionCount ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
              </section>

              {humanControls.length ? (
                <section className="graph-foreground-human-strip" aria-label="人工传播控制">
                  <header>
                    <div>
                      <span>人工传播</span>
                      <strong>{humanControls.length} 条可处理边</strong>
                    </div>
                    <GitBranch size={15} />
                  </header>
                  <div className="graph-foreground-human-strip__list">
                    {humanControls.slice(0, 4).map((control) => (
                      <button
                        className={selectedHumanControl?.control_id === control.control_id ? "graph-foreground-human-control graph-foreground-human-control--active" : "graph-foreground-human-control"}
                        key={control.control_id}
                        onClick={() => openHumanDecision(control)}
                        type="button"
                      >
                        <strong>{controlTitle(control)}</strong>
                        <span>{control.reason || "等待人工选择传播动作"}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="graph-foreground-run-summary" aria-label="运行摘要">
                <article>
                  <span>{graphMonitorEnabled ? "完成" : "运行信号"}</span>
                  <strong>{graphMonitorEnabled ? `${progressPercent}%` : graphRuntimeStatusLabel(activeGraphRuntimeStatus)}</strong>
                  <small>{graphMonitorEnabled && totalNodeCount ? `${counts.completed}/${totalNodeCount} 节点` : activeGraphRunId || "尚未创建运行"}</small>
                  {graphMonitorEnabled ? (
                    <div className="graph-foreground-progress" aria-hidden="true">
                      <i style={{ width: `${progressPercent}%` }} />
                    </div>
                  ) : null}
                </article>
                <article className={counts.failed || counts.blocked ? "graph-foreground-summary-card--attention" : ""}>
                  <span>{graphMonitorEnabled ? "风险" : "章节"}</span>
                  <strong>{graphMonitorEnabled ? (counts.failed || counts.blocked ? `${counts.failed} 失败 · ${counts.blocked} 阻塞` : "无") : chapterCount}</strong>
                  <small>{graphMonitorEnabled ? (counts.running ? `${counts.running} 运行中` : "没有运行中的节点") : "来自写作台轻量索引"}</small>
                </article>
                <article>
                  <span>{graphMonitorEnabled ? "最近产物" : "产物"}</span>
                  <strong>{graphMonitorEnabled ? (latestArtifact ? stringValue(latestArtifact.name, stringValue(latestArtifact.path, "未命名产物")) : "暂无") : counts.artifacts}</strong>
                  <small>{graphMonitorEnabled ? (latestArtifact ? stringValue(latestArtifact.path, "没有文件路径") : "运行后显示") : "不打开完整文件树"}</small>
                </article>
                <article>
                  <span>{graphMonitorEnabled ? "会话" : "最近更新"}</span>
                  <strong>{graphMonitorEnabled ? counts.sessions : timestampLabel(selectedInstance.updated_at)}</strong>
                  <small>{graphMonitorEnabled ? `${counts.artifacts} 个产物` : selectedInstance.graph_task_instance_id}</small>
                </article>
              </section>

              <section className="graph-foreground-canvas" aria-label="运行焦点图">
                <header>
                  <div>
                    <span>运行焦点 · 跟随模式</span>
                      <strong>{graphMonitorEnabled && nodeCards.length ? `${nodeCards.length} 个节点信号` : "图监控未开启"}</strong>
                  </div>
                  <small>{graphMonitorEnabled ? focusLabel : "当前只显示项目运行信号，避免首屏拉取完整图监控。"}</small>
                </header>
                <div className="graph-foreground-node-grid">
                  {nodeCards.map((node) => {
                    const active = selectedNode?.nodeId === node.nodeId;
                    const tone = statusTone(node.status);
                    return (
                      <button
                        aria-current={active ? "true" : undefined}
                        className={classNames("graph-foreground-node-card", `graph-foreground-node-card--${tone}`, active && "graph-foreground-node-card--active")}
                        key={node.nodeId}
                        onClick={() => setSelectedNodeId(node.nodeId)}
                        type="button"
                      >
                        <span>{statusLabel(node.status)}</span>
                        <strong>{node.title}</strong>
                        <small>{node.scopeLabel ? `${node.scopeLabel} · ${node.nodeId}` : node.nodeId}</small>
                        <p>{node.detail}</p>
                        <footer>
                          <b>{node.session ? `${node.session.message_count ?? 0} 消息` : "无会话"}</b>
                          <b>{node.artifactCount} 产物</b>
                        </footer>
                      </button>
                    );
                  })}
                  {!nodeCards.length ? (
                    <div className="graph-foreground-canvas-empty">
                      <Bot size={24} />
                      <strong>{graphMonitorEnabled ? "还没有节点运行信号" : "图监控未开启"}</strong>
                      <span>{graphMonitorEnabled ? "启动运行后显示活跃节点、输出摘要和节点会话入口。" : "需要完整节点画布时再打开图监控链路。"}</span>
                    </div>
                  ) : null}
                </div>
              </section>
            </main>

            <aside className="graph-foreground-inspector" aria-label="节点对话输出">
              <section className="graph-foreground-panel graph-foreground-node-output">
                <header>
                  <div>
                    <span>节点输出</span>
                    <strong>{selectedNode?.title || "选择节点"}</strong>
                  </div>
                  <MessageSquare size={15} />
                </header>
                {selectedNode ? (
                  <>
                    <div className={`graph-foreground-node-output__status graph-foreground-node-output__status--${statusTone(selectedNode.status)}`}>
                      <strong>{statusLabel(selectedNode.status)}</strong>
                      <span>{selectedNode.nodeId} · {timestampLabel(selectedNode.updatedAt)}</span>
                    </div>
                    <div className="graph-foreground-node-output__body">
                      <p>{selectedNode.detail}</p>
                    </div>
                    <button disabled={!selectedNode.session} onClick={() => void openSession(selectedNode.session)} type="button">
                      <MessageSquare size={14} />
                      <span>{selectedNode.session ? "打开节点会话" : "暂无节点会话"}</span>
                    </button>
                    <div className="graph-foreground-node-output__artifacts">
                      <span>节点产物</span>
                      {selectedNodeArtifacts.map((artifact) => {
                        const path = stringValue(artifact.path);
                        return (
                          <button disabled={!path} key={stringValue(artifact.artifact_id, path)} onClick={() => path && void loadFile(path)} type="button">
                            <FileText size={13} />
                            <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                          </button>
                        );
                      })}
                      {!selectedNodeArtifacts.length ? <small>这个节点还没有产物。</small> : null}
                    </div>
                  </>
                ) : (
                  <div className="boundary-empty">选择节点后显示节点输出。</div>
                )}
              </section>
              <section className="graph-foreground-panel graph-foreground-human-inspector">
                <header>
                  <div>
                    <span>边传播控制</span>
                    <strong>{selectedHumanControl ? controlTitle(selectedHumanControl) : "无可处理边"}</strong>
                  </div>
                  <GitBranch size={15} />
                </header>
                {selectedHumanControl ? (
                  <>
                    <p>{selectedHumanControl.reason || "选择人工动作后，系统会按边契约推进图任务。"}</p>
                    <div className="graph-foreground-human-actions">
                      {selectedHumanControl.allowed_decisions.map((kind) => (
                        <button key={kind} onClick={() => openHumanDecision(selectedHumanControl, kind)} type="button">
                          {kind === "replace" ? <PencilLine size={14} /> : kind === "revise" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                          <span>{decisionLabel(selectedHumanControl, kind)}</span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="boundary-empty">当前没有后端允许的人工传播动作。</div>
                )}
              </section>
            </aside>
          </div>
          ) : (
          <WritingChapterDesk
            action={action}
            artifactSearch={artifactSearch}
            artifacts={artifacts}
            assetTab={assetTab}
            chapterActions={chapterActions}
            chapterFiles={writingChapterFiles}
            decisionHistory={decisionHistory}
            fileContent={fileContent}
            fileEditorMode={fileEditorMode}
            fileSearch={fileSearch}
            filteredArtifacts={filteredArtifacts}
            flatFiles={flatFiles}
            focusMode={readerFocusMode}
            loadFile={loadFile}
            newFileContent={newFileContent}
            newFilePath={newFilePath}
            nextChapterFile={nextChapterFile}
            nodeCards={nodeCards}
            openChapterAction={openChapterAction}
            openSession={openSession}
            previousChapterFile={previousChapterFile}
            saveSelectedFile={saveSelectedFile}
            selectedFileName={selectedFileName}
            selectedFilePath={selectedFilePath}
            selectedHumanControl={selectedHumanControl}
            selectedNode={selectedNode}
            setArtifactSearch={setArtifactSearch}
            setAssetTab={setAssetTab}
            setFileContent={setFileContent}
            setFileEditorMode={setFileEditorMode}
            setFileSearch={setFileSearch}
            setFocusMode={setReaderFocusMode}
            setNewFileContent={setNewFileContent}
            setNewFilePath={setNewFilePath}
            setSelectedFilePath={setSelectedFilePath}
            setSelectedNodeId={setSelectedNodeId}
            visibleChapterFiles={visibleChapterFiles}
            writeNewFile={writeNewFile}
          />
          )}
        </div>
      )}
      {decisionDrawerOpen && selectedHumanControl ? (
        <div className="graph-foreground-decision-drawer" role="dialog" aria-modal="true" aria-label="章节审核决策">
          <div className="graph-foreground-decision-drawer__panel">
            <header>
              <div>
                <span>章节审核</span>
                <strong>{writingDrawerTitle(decisionKind)}</strong>
              </div>
              <button onClick={() => setDecisionDrawerOpen(false)} type="button">关闭</button>
            </header>
            <div className="graph-foreground-decision-kind" role="group" aria-label="决策类型">
              {selectedHumanControl.allowed_decisions.map((kind) => (
                <button
                  aria-pressed={decisionKind === kind}
                  className={decisionKind === kind ? "graph-foreground-decision-kind__active" : undefined}
                  key={kind}
                  onClick={() => setDecisionKind(kind)}
                  type="button"
                >
                  {kind === "replace" ? <PencilLine size={14} /> : kind === "revise" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                  <span>{writingDecisionLabel(kind)}</span>
                </button>
              ))}
            </div>
            <label>
              <span>{decisionKind === "revise" ? "退稿意见" : "审核说明"}</span>
              <textarea onChange={(event) => setDecisionInstruction(event.target.value)} placeholder={decisionKind === "revise" ? "写清楚退稿原因和修改方向" : "可选，写给下一环节的补充说明"} value={decisionInstruction} />
            </label>
            {decisionKind === "replace" ? (
              <div className="graph-foreground-decision-replace">
                <label>
                  <span>正式库路径</span>
                  <input onChange={(event) => setDecisionReplacePath(event.target.value)} value={decisionReplacePath} />
                </label>
                <label>
                  <span>改写正文</span>
                  <textarea onChange={(event) => setDecisionReplaceContent(event.target.value)} value={decisionReplaceContent} />
                </label>
              </div>
            ) : null}
            <footer>
              <button onClick={() => setDecisionDrawerOpen(false)} type="button">取消</button>
              <button disabled={action === "human-edge-decision"} onClick={() => void submitHumanDecision()} type="button">
                <GitBranch size={14} />
                <span>{action === "human-edge-decision" ? "应用中" : "确认审核动作"}</span>
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </section>
  );
}
