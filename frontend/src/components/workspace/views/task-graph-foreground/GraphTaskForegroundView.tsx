"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Eye,
  FileText,
  FolderTree,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  PencilLine,
  PlayCircle,
  Plus,
  RefreshCw,
  Save,
  Search,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  createGraphTaskInstance,
  getGraphTaskInstanceFileTree,
  getGraphTaskInstanceMonitor,
  listGraphTaskInstances,
  listGraphTasks,
  readGraphTaskInstanceFile,
  startGraphTaskInstanceRun,
  submitGraphTaskInstanceHumanEdgeDecision,
  writeGraphTaskInstanceFile,
  type GraphTaskDefinitionSummary,
  type HumanEdgeControlView,
  type HumanEdgeDecisionKind,
  type GraphTaskInstanceFileTree,
  type GraphTaskInstanceMonitor,
  type GraphTaskInstanceSummary,
  type SessionScope,
  type SessionSummary,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

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

const FILE_PATH_TEMPLATES = [
  { label: "任务简报", path: "input/brief.md" },
  { label: "世界观", path: "world/world.md" },
  { label: "角色表", path: "characters/characters.md" },
  { label: "大纲", path: "outline/outline.md" },
  { label: "正文 001", path: "chapters/chapter-001.md" },
  { label: "审校记录", path: "review/review-notes.md" },
] as const;

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

function monitorCounts(monitor: GraphTaskInstanceMonitor | null) {
  const summary = recordOf(monitor?.summary);
  return {
    ready: numberValue(summary.ready_count),
    running: numberValue(summary.running_count),
    completed: numberValue(summary.completed_count),
    failed: numberValue(summary.failed_count),
    blocked: numberValue(summary.blocked_count),
    sessions: numberValue(summary.node_session_count, monitor?.node_sessions.length ?? 0),
    artifacts: numberValue(summary.artifact_count, monitor?.artifacts.artifacts.length ?? 0),
  };
}

function parseTreeNode(value: unknown): FileTreeNode {
  const record = recordOf(value);
  return {
    children: Array.isArray(record.children) ? record.children.map(parseTreeNode) : [],
    kind: stringValue(record.kind, "file"),
    name: stringValue(record.name, stringValue(record.path, "root")),
    path: stringValue(record.path),
  };
}

function flattenFileTree(node: FileTreeNode): FileTreeNode[] {
  return [
    ...(node.kind === "file" ? [node] : []),
    ...node.children.flatMap(flattenFileTree),
  ];
}

function isChapterFile(node: FileTreeNode) {
  const path = node.path.toLowerCase();
  return node.kind === "file" && (
    path.includes("/chapters/")
    || path.startsWith("chapters/")
    || /chapter[-_ ]?\d+/.test(path)
    || /第.+章/.test(node.name)
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

function buildNodeRuntimeCards(monitor: GraphTaskInstanceMonitor | null): NodeRuntimeCard[] {
  const graphMonitor = monitor?.graph_monitor;
  const runtimeViews = Array.isArray(graphMonitor?.active_node_runtime_views)
    ? graphMonitor.active_node_runtime_views
    : [];
  const workOrders = Array.isArray(graphMonitor?.active_node_work_orders)
    ? graphMonitor.active_node_work_orders
    : [];
  const byNode = new Map<string, NodeRuntimeCard>();
  const sessions = monitor?.node_sessions ?? [];
  const artifacts = monitor?.artifacts.artifacts ?? [];

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

function humanControlItems(monitor: GraphTaskInstanceMonitor | null): HumanEdgeControlView[] {
  const controls = monitor?.human_controls;
  const pending = Array.isArray(controls?.pending) ? controls.pending : [];
  const available = Array.isArray(controls?.available) ? controls.available : [];
  const byId = new Map<string, HumanEdgeControlView>();
  [...pending, ...available].forEach((control, index) => {
    const controlId = stringValue(control.control_id, `${control.graph_run_id}:${control.edge_id}:${index}`);
    byId.set(controlId, { ...control, control_id: controlId });
  });
  return Array.from(byId.values());
}

function humanDecisionHistory(monitor: GraphTaskInstanceMonitor | null): Array<Record<string, unknown>> {
  const history = monitor?.human_controls?.history;
  return Array.isArray(history) ? history : [];
}

function decisionLabel(control: HumanEdgeControlView | null, decision: HumanEdgeDecisionKind) {
  const label = control?.decision_labels?.[decision];
  if (label) return label;
  if (decision === "pass") return "通过并传给下游";
  if (decision === "revise") return "退稿并回传上游";
  return "我来替写并继续";
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
  const [fileEditorMode, setFileEditorMode] = useState<FileEditorMode>("edit");
  const [assetTab, setAssetTab] = useState<AssetTab>("library");
  const [consoleScreen, setConsoleScreen] = useState<ConsoleScreen>("monitor");
  const [selectedHumanControlId, setSelectedHumanControlId] = useState("");
  const [decisionDrawerOpen, setDecisionDrawerOpen] = useState(false);
  const [decisionKind, setDecisionKind] = useState<HumanEdgeDecisionKind>("pass");
  const [decisionInstruction, setDecisionInstruction] = useState("");
  const [decisionReplacePath, setDecisionReplacePath] = useState("");
  const [decisionReplaceContent, setDecisionReplaceContent] = useState("");
  const [newInstanceTitle, setNewInstanceTitle] = useState("");
  const [newInstanceDescription, setNewInstanceDescription] = useState("");
  const [loadingGraphs, setLoadingGraphs] = useState(false);
  const [loadingInstances, setLoadingInstances] = useState(false);
  const [loadingMonitor, setLoadingMonitor] = useState(false);
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
  const counts = monitorCounts(monitor);
  const totalNodeCount = counts.ready + counts.running + counts.completed + counts.failed + counts.blocked;
  const progressPercent = totalNodeCount ? Math.round((counts.completed / totalNodeCount) * 100) : 0;
  const nodeCards = useMemo(() => buildNodeRuntimeCards(monitor), [monitor]);
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
  const artifacts = monitor?.artifacts.artifacts ?? [];
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
  const visibleChapterFiles = useMemo(() => {
    const files = chapterFiles.length ? chapterFiles : flatFiles;
    const query = normalizedQuery(fileSearch);
    if (!query) return files;
    return files.filter((file) => `${file.name} ${file.path}`.toLowerCase().includes(query));
  }, [chapterFiles, fileSearch, flatFiles]);
  const selectedNodeArtifacts = useMemo(
    () => selectedNode ? artifacts.filter((artifact) => artifactNodeId(artifact) === selectedNode.nodeId).slice(0, 8) : [],
    [artifacts, selectedNode],
  );
  const humanControls = useMemo(() => humanControlItems(monitor), [monitor]);
  const selectedHumanControl = useMemo(
    () => humanControls.find((control) => control.control_id === selectedHumanControlId) ?? humanControls[0] ?? null,
    [humanControls, selectedHumanControlId],
  );
  const decisionHistory = useMemo(() => humanDecisionHistory(monitor), [monitor]);
  const humanActionCount = humanControls.length;

  const loadGraphs = useCallback(async () => {
    setLoadingGraphs(true);
    setError("");
    try {
      const payload = await listGraphTasks();
      setGraphs(payload.graph_tasks);
      setSelectedGraphId((current) => {
        const requested = requestedGraphId.trim();
        if (requested && payload.graph_tasks.some((graph) => graph.graph_id === requested)) return requested;
        if (current && payload.graph_tasks.some((graph) => graph.graph_id === current)) return current;
        return payload.graph_tasks[0]?.graph_id ?? "";
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
      return;
    }
    setLoadingInstances(true);
    setError("");
    try {
      const payload = await listGraphTaskInstances(graphId);
      const sorted = sortInstances(payload.instances);
      setInstances(sorted);
      setSelectedInstanceId((current) => current && sorted.some((instance) => instance.graph_task_instance_id === current)
        ? current
        : "");
    } catch (caught) {
      setInstances([]);
      setSelectedInstanceId("");
      setError(caught instanceof Error ? caught.message : "项目实例加载失败");
    } finally {
      setLoadingInstances(false);
    }
  }, []);

  const refreshInstance = useCallback(async (instanceId: string) => {
    if (!instanceId) {
      setMonitor(null);
      setFileTree(null);
      setSelectedNodeId("");
      return;
    }
    setLoadingMonitor(true);
    setError("");
    try {
      const monitorPayload = await getGraphTaskInstanceMonitor(instanceId, 100);
      setMonitor(monitorPayload);
      setInstances((current) => sortInstances(current.map((instance) => (
        instance.graph_task_instance_id === monitorPayload.instance.graph_task_instance_id
          ? monitorPayload.instance
          : instance
      ))));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目运行监控加载失败");
    } finally {
      setLoadingMonitor(false);
    }
  }, []);

  const loadProjectFileTree = useCallback(async (instanceId: string) => {
    if (!instanceId) {
      setFileTree(null);
      return;
    }
    try {
      setFileTree(await getGraphTaskInstanceFileTree(instanceId, { maxDepth: 6, maxEntries: 1000 }));
    } catch {
      setFileTree(null);
    }
  }, []);

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
    setFileTree(null);
    setSelectedFilePath("");
    setFileContent("");
    setSelectedNodeId("");
    setAssetTab("library");
    setConsoleScreen("monitor");
    void loadInstances(selectedGraphId);
  }, [loadInstances, selectedGraphId]);

  useEffect(() => {
    if (!selectedInstanceId) {
      setMonitor(null);
      setFileTree(null);
      setSelectedNodeId("");
      return;
    }
    void refreshInstance(selectedInstanceId);
  }, [refreshInstance, selectedInstanceId]);

  useEffect(() => {
    if (!selectedInstanceId || (assetTab !== "library" && consoleScreen !== "sessions")) return;
    void loadProjectFileTree(selectedInstanceId);
  }, [assetTab, consoleScreen, loadProjectFileTree, selectedInstanceId]);

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
    setAction("create-instance");
    setError("");
    setNotice("");
    try {
      const payload = await createGraphTaskInstance(selectedGraph.graph_id, {
        title,
        description: newInstanceDescription.trim(),
        metadata: { created_from: "graph_task_foreground" },
      });
      setInstances((current) => sortInstances([
        payload.instance,
        ...current.filter((instance) => instance.graph_task_instance_id !== payload.instance.graph_task_instance_id),
      ]));
      setSelectedInstanceId(payload.instance.graph_task_instance_id);
      setAssetTab("library");
      setConsoleScreen("monitor");
      setNewInstanceTitle("");
      setNewInstanceDescription("");
      setNotice("项目实例已创建。");
      await refreshInstance(payload.instance.graph_task_instance_id);
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
        initial_inputs: { requested_from: "graph_task_foreground" },
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
      setNotice("运行已提交后台。");
      await refreshInstance(payload.instance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "启动图任务运行失败");
    } finally {
      setAction("");
    }
  }

  async function startRun() {
    await startRunForInstance(selectedInstance);
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
      await refreshInstance(selectedInstance.graph_task_instance_id);
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
      setNewFileContent("");
      setNotice(`已写入 ${payload.path}`);
      await refreshInstance(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "写入项目文件失败");
    } finally {
      setAction("");
    }
  }

  function openHumanDecision(control: HumanEdgeControlView | null, kind?: HumanEdgeDecisionKind) {
    if (!control) return;
    const nextKind = kind ?? control.default_decision ?? control.allowed_decisions[0] ?? "pass";
    setSelectedHumanControlId(control.control_id);
    setDecisionKind(nextKind);
    setDecisionInstruction("");
    setDecisionReplacePath(selectedFilePath || "chapters/chapter-001.md");
    setDecisionReplaceContent(fileContent);
    setDecisionDrawerOpen(true);
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
      if (decisionKind === "replace" && contentSubmission?.path) {
        setSelectedFilePath(String(contentSubmission.path));
        setFileContent(decisionReplaceContent);
        await loadProjectFileTree(selectedInstance.graph_task_instance_id);
      }
      await refreshInstance(selectedInstance.graph_task_instance_id);
      setNotice(`${decisionLabel(selectedHumanControl, decisionKind)}已应用。`);
      setDecisionDrawerOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工传播决策提交失败");
    } finally {
      setAction("");
    }
  }

  const nextAction = !selectedInstance
    ? "先选择或创建项目实例。"
    : humanActionCount
      ? `有 ${humanActionCount} 个边传播动作可处理。`
    : counts.failed || counts.blocked
      ? "优先处理失败或阻塞节点。"
      : statusTone(selectedInstance.status) === "active"
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
          <span>{hasSelectedInstance ? "Project Console" : "Graph Task Projects"}</span>
          <strong>{hasSelectedInstance ? selectedInstance?.title : "图任务项目管理"}</strong>
          <small>{selectedGraph?.title || selectedGraph?.graph_id || "选择图任务定义"} · {instances.length} 个项目实例</small>
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
              <span>{action === "start-run" ? "提交中" : "启动运行"}</span>
            </button>
          ) : null}
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
      {notice ? <div className="boundary-notice">{notice}</div> : null}

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
                    <button className="graph-foreground-project-row__title" onClick={() => { setConsoleScreen("monitor"); setSelectedInstanceId(instance.graph_task_instance_id); }} type="button">
                      <strong>{instance.title || instance.graph_task_instance_id}</strong>
                      <small>{instance.graph_task_instance_id}</small>
                    </button>
                    <span className={`graph-foreground-status graph-foreground-status--${tone}`}>{statusLabel(instance.status)}</span>
                    <span>{timestampLabel(instance.updated_at)}</span>
                    <div className="graph-foreground-project-row__actions">
                      <button disabled={action === "start-run"} onClick={() => void startRunForInstance(instance)} type="button">
                        <PlayCircle size={13} />
                        <span>{statusTone(instance.status) === "active" ? "继续" : "启动"}</span>
                      </button>
                      <button onClick={() => { setConsoleScreen("monitor"); setSelectedInstanceId(instance.graph_task_instance_id); }} type="button">
                        <MessageSquare size={13} />
                        <span>进入</span>
                      </button>
                    </div>
                  </article>
                );
              })}
              {!instances.length ? (
                <div className="graph-foreground-compact-empty">
                  <FileText size={20} />
                  <strong>这个图还没有项目实例</strong>
                  <span>在右侧创建项目后进入运行控制台。</span>
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
                <span>说明</span>
                <textarea
                  onChange={(event) => setNewInstanceDescription(event.target.value)}
                  placeholder="目标、范围、人工约束"
                  rows={4}
                  value={newInstanceDescription}
                />
              </label>
              <button disabled={!selectedGraph || action === "create-instance"} onClick={() => void createInstance()} type="button">
                <Plus size={14} />
                <span>{action === "create-instance" ? "创建中" : "创建并进入项目"}</span>
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
              <small>{selectedInstance.graph_task_instance_id}</small>
            </div>
            <div className="graph-foreground-console-actions">
              <div className="graph-foreground-console-switch" role="tablist" aria-label="项目控制台屏幕">
                <button aria-selected={consoleScreen === "monitor"} className={consoleScreen === "monitor" ? "graph-foreground-console-switch__active" : undefined} onClick={() => setConsoleScreen("monitor")} type="button">
                  <GitBranch size={13} />
                  图监控
                </button>
                <button aria-selected={consoleScreen === "sessions"} className={consoleScreen === "sessions" ? "graph-foreground-console-switch__active" : undefined} onClick={() => setConsoleScreen("sessions")} type="button">
                  <MessageSquare size={13} />
                  会话章节
                </button>
              </div>
              <em className={`graph-foreground-status graph-foreground-status--${statusTone(selectedInstance.status)}`}>
                {statusLabel(selectedInstance.status)}
              </em>
              <button disabled={loadingMonitor} onClick={() => void refreshInstance(selectedInstance.graph_task_instance_id)} type="button">
                <RefreshCw size={14} />
                <span>{loadingMonitor ? "刷新中" : "刷新监控"}</span>
              </button>
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
                Boolean(counts.failed || counts.blocked) && "graph-foreground-next-action--attention",
              )}>
                <div>
                  <span>下一动作</span>
                  <strong>{nextAction}</strong>
                </div>
                {counts.failed || counts.blocked ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
              </section>

              <section className="graph-foreground-run-summary" aria-label="运行摘要">
                <article>
                  <span>完成</span>
                  <strong>{progressPercent}%</strong>
                  <small>{totalNodeCount ? `${counts.completed}/${totalNodeCount} 节点` : "等待运行数据"}</small>
                  <div className="graph-foreground-progress" aria-hidden="true">
                    <i style={{ width: `${progressPercent}%` }} />
                  </div>
                </article>
                <article className={counts.failed || counts.blocked ? "graph-foreground-summary-card--attention" : ""}>
                  <span>风险</span>
                  <strong>{counts.failed || counts.blocked ? `${counts.failed} 失败 · ${counts.blocked} 阻塞` : "无"}</strong>
                  <small>{counts.running ? `${counts.running} 运行中` : "没有运行中的节点"}</small>
                </article>
                <article>
                  <span>最近产物</span>
                  <strong>{latestArtifact ? stringValue(latestArtifact.name, stringValue(latestArtifact.path, "未命名产物")) : "暂无"}</strong>
                  <small>{latestArtifact ? stringValue(latestArtifact.path, "没有文件路径") : "运行后显示"}</small>
                </article>
                <article>
                  <span>会话</span>
                  <strong>{counts.sessions}</strong>
                  <small>{counts.artifacts} 个产物</small>
                </article>
              </section>

              <section className="graph-foreground-canvas" aria-label="运行焦点图">
                <header>
                  <div>
                    <span>运行焦点 · 跟随模式</span>
                    <strong>{nodeCards.length ? `${nodeCards.length} 个节点信号` : "等待节点信号"}</strong>
                  </div>
                  <small>{focusLabel}</small>
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
                      <strong>还没有节点运行信号</strong>
                      <span>启动运行后显示活跃节点、输出摘要和节点会话入口。</span>
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
            </aside>
          </div>
          ) : (
          <div className="graph-foreground-session-screen">
            <aside className="graph-foreground-chapter-rail" aria-label="章节文件">
              <header>
                <div>
                  <span>章节</span>
                  <strong>{chapterFiles.length || flatFiles.length} 个文件</strong>
                </div>
                <FileText size={15} />
              </header>
              <label className="graph-foreground-search">
                <Search size={14} />
                <input onChange={(event) => setFileSearch(event.target.value)} placeholder="搜索章节或文件" value={fileSearch} />
              </label>
              <div className="graph-foreground-chapter-list">
                {visibleChapterFiles.slice(0, 120).map((file) => (
                  <button
                    className={selectedFilePath === file.path ? "graph-foreground-chapter-row graph-foreground-chapter-row--active" : "graph-foreground-chapter-row"}
                    key={file.path}
                    onClick={() => void loadFile(file.path)}
                    type="button"
                  >
                    <strong>{file.name}</strong>
                    <small>{file.path}</small>
                  </button>
                ))}
                {!flatFiles.length ? <div className="boundary-empty">正式库还没有可查看文件。</div> : null}
                {flatFiles.length && !visibleChapterFiles.length ? <div className="boundary-empty">没有匹配的章节或文件。</div> : null}
              </div>
            </aside>

          <section className="graph-foreground-assets graph-foreground-assets--session" aria-label="项目资产区">
            <header>
              <div>
                <span>项目资产</span>
                <strong>{assetTab === "library" ? "正式库" : "运行产物"}</strong>
              </div>
              <div className="graph-foreground-asset-tabs" role="tablist" aria-label="项目资产页签">
                <button aria-selected={assetTab === "library"} className={assetTab === "library" ? "graph-foreground-asset-tabs__active" : undefined} onClick={() => setAssetTab("library")} type="button">
                  <FolderTree size={13} />
                  正式库
                </button>
                <button aria-selected={assetTab === "artifacts"} className={assetTab === "artifacts" ? "graph-foreground-asset-tabs__active" : undefined} onClick={() => setAssetTab("artifacts")} type="button">
                  <FileText size={13} />
                  运行产物
                </button>
              </div>
            </header>
            {assetTab === "library" ? (
              <div className="graph-foreground-library__body graph-foreground-library__body--session">
                <div className="graph-foreground-library__editor">
                  <div className="graph-foreground-file-head">
                    <label>
                      <span>当前文件</span>
                      <input onChange={(event) => setSelectedFilePath(event.target.value)} placeholder="选择或输入文件路径" value={selectedFilePath} />
                    </label>
                    <div className="graph-foreground-mode-switch" role="group" aria-label="文件显示模式">
                      <button aria-pressed={fileEditorMode === "edit"} className={fileEditorMode === "edit" ? "graph-foreground-mode-switch__active" : undefined} onClick={() => setFileEditorMode("edit")} type="button">
                        <PencilLine size={13} />
                        编辑
                      </button>
                      <button aria-pressed={fileEditorMode === "preview"} className={fileEditorMode === "preview" ? "graph-foreground-mode-switch__active" : undefined} onClick={() => setFileEditorMode("preview")} type="button">
                        <Eye size={13} />
                        预览
                      </button>
                    </div>
                  </div>
                  {fileEditorMode === "edit" ? (
                    <textarea onChange={(event) => setFileContent(event.target.value)} placeholder="选择文件后编辑内容" value={fileContent} />
                  ) : (
                    <div className="graph-foreground-file-preview markdown">
                      {fileContent.trim() ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {fileContent}
                        </ReactMarkdown>
                      ) : (
                        <p>选择文件后显示预览。</p>
                      )}
                    </div>
                  )}
                  <button disabled={!selectedFilePath.trim() || action === "save-file"} onClick={() => void saveSelectedFile()} type="button">
                    <Save size={14} />
                    <span>{action === "save-file" ? "保存中" : "保存文件"}</span>
                  </button>
                </div>
                <div className="graph-foreground-library__writer">
                  <label>
                    <span>写入正式库</span>
                    <input onChange={(event) => setNewFilePath(event.target.value)} placeholder="input/brief.md" value={newFilePath} />
                  </label>
                  <div className="graph-foreground-template-grid">
                    {FILE_PATH_TEMPLATES.map((template) => (
                      <button className={newFilePath === template.path ? "graph-foreground-template-grid__active" : undefined} key={template.path} onClick={() => setNewFilePath(template.path)} type="button">
                        <strong>{template.label}</strong>
                        <small>{template.path}</small>
                      </button>
                    ))}
                  </div>
                  <textarea onChange={(event) => setNewFileContent(event.target.value)} placeholder="输入要写入项目正式库的内容" value={newFileContent} />
                  <button disabled={!newFilePath.trim() || action === "write-file"} onClick={() => void writeNewFile()} type="button">
                    <FileText size={14} />
                    <span>{action === "write-file" ? "写入中" : "写入项目库"}</span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="graph-foreground-artifacts-pane">
                <label className="graph-foreground-search">
                  <Search size={14} />
                  <input onChange={(event) => setArtifactSearch(event.target.value)} placeholder="搜索产物" value={artifactSearch} />
                </label>
                <div className="graph-foreground-artifact-list">
                  {filteredArtifacts.slice(0, 80).map((artifact) => {
                    const path = stringValue(artifact.path);
                    return (
                      <button disabled={!path} key={stringValue(artifact.artifact_id, path)} onClick={() => path && void loadFile(path)} type="button">
                        <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                        <small>{path || "没有文件路径"}</small>
                        <span>{numberValue(artifact.size)} bytes · {timestampLabel(artifact.updated_at)}</span>
                      </button>
                    );
                  })}
                  {!artifacts.length ? <div className="boundary-empty">运行产物会出现在这里。</div> : null}
                  {artifacts.length && !filteredArtifacts.length ? <div className="boundary-empty">没有匹配的运行产物。</div> : null}
                </div>
              </div>
            )}
          </section>

            <aside className="graph-foreground-session-side" aria-label="节点会话和产物">
              <section className="graph-foreground-panel graph-foreground-session-card">
                <header>
                  <div>
                    <span>节点会话</span>
                    <strong>{selectedNode?.title || "选择节点"}</strong>
                  </div>
                  <MessageSquare size={15} />
                </header>
                <div className="graph-foreground-node-list">
                  {nodeCards.map((node) => (
                    <button
                      aria-current={selectedNode?.nodeId === node.nodeId ? "true" : undefined}
                      className={classNames("graph-foreground-node-list-row", selectedNode?.nodeId === node.nodeId && "graph-foreground-node-list-row--active")}
                      key={node.nodeId}
                      onClick={() => setSelectedNodeId(node.nodeId)}
                      type="button"
                    >
                      <span>{statusLabel(node.status)}</span>
                      <strong>{node.title}</strong>
                      <small>{node.session ? `${node.session.message_count ?? 0} 条消息` : "暂无会话"}</small>
                    </button>
                  ))}
                  {!nodeCards.length ? <div className="boundary-empty">暂无节点会话。</div> : null}
                </div>
                <button disabled={!selectedNode?.session} onClick={() => void openSession(selectedNode?.session ?? null)} type="button">
                  <MessageSquare size={14} />
                  <span>{selectedNode?.session ? "打开节点会话" : "暂无节点会话"}</span>
                </button>
              </section>

              <section className="graph-foreground-panel graph-foreground-session-card">
                <header>
                  <div>
                    <span>运行产物</span>
                    <strong>{artifacts.length} 个产物</strong>
                  </div>
                  <FolderTree size={15} />
                </header>
                <div className="graph-foreground-artifact-list graph-foreground-artifact-list--side">
                  {filteredArtifacts.slice(0, 30).map((artifact) => {
                    const path = stringValue(artifact.path);
                    return (
                      <button disabled={!path} key={stringValue(artifact.artifact_id, path)} onClick={() => path && void loadFile(path)} type="button">
                        <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                        <small>{path || "没有文件路径"}</small>
                      </button>
                    );
                  })}
                  {!artifacts.length ? <div className="boundary-empty">运行产物会出现在这里。</div> : null}
                </div>
              </section>
            </aside>
          </div>
          )}
        </div>
      )}
    </section>
  );
}
