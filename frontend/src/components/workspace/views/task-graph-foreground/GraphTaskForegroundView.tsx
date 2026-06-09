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
  writeGraphTaskInstanceFile,
  type GraphTaskDefinitionSummary,
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

function filterFileTree(node: FileTreeNode, query: string): FileTreeNode | null {
  if (!query) return node;
  const children = node.children
    .map((child) => filterFileTree(child, query))
    .filter((child): child is FileTreeNode => Boolean(child));
  const haystack = `${node.name} ${node.path}`.toLowerCase();
  if (haystack.includes(query) || children.length) return { ...node, children };
  return null;
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

function FileTree({
  node,
  onSelectFile,
  selectedPath,
}: {
  node: FileTreeNode;
  onSelectFile: (path: string) => void;
  selectedPath: string;
}) {
  const isFile = node.kind === "file";
  return (
    <div className="graph-foreground-file-tree__node">
      <button
        aria-current={isFile && node.path === selectedPath ? "true" : undefined}
        className={classNames(
          "graph-foreground-file-tree__row",
          isFile && node.path === selectedPath && "graph-foreground-file-tree__row--active",
        )}
        disabled={!isFile}
        onClick={() => isFile && onSelectFile(node.path)}
        type="button"
      >
        <span>{isFile ? "FILE" : "DIR"}</span>
        <strong>{node.path ? node.name : "项目文件"}</strong>
      </button>
      {node.children.length ? (
        <div className="graph-foreground-file-tree__children">
          {node.children.map((child) => (
            <FileTree
              key={`${child.kind}:${child.path || child.name}`}
              node={child}
              onSelectFile={onSelectFile}
              selectedPath={selectedPath}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
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
      ?? instances[0]
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
  const filteredTree = useMemo(
    () => filterFileTree(rootTreeNode, normalizedQuery(fileSearch)),
    [fileSearch, rootTreeNode],
  );
  const selectedNodeArtifacts = useMemo(
    () => selectedNode ? artifacts.filter((artifact) => artifactNodeId(artifact) === selectedNode.nodeId).slice(0, 8) : [],
    [artifacts, selectedNode],
  );

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
        : sorted[0]?.graph_task_instance_id ?? "");
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
      const treePayload = await getGraphTaskInstanceFileTree(instanceId, { maxDepth: 6, maxEntries: 1000 }).catch(() => null);
      setFileTree(treePayload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目运行监控加载失败");
    } finally {
      setLoadingMonitor(false);
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

  async function startRun() {
    if (!selectedInstance) return;
    setAction("start-run");
    setError("");
    setNotice("");
    try {
      const payload = await startGraphTaskInstanceRun(selectedInstance.graph_task_instance_id, {
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

  const nextAction = !selectedInstance
    ? "先选择或创建项目实例。"
    : counts.failed || counts.blocked
      ? "优先处理失败或阻塞节点。"
      : statusTone(selectedInstance.status) === "active"
        ? "运行中，观察节点画布和最新输出。"
        : "项目已就绪，可以启动运行。";

  return (
    <section className="graph-foreground-shell" aria-label="图任务运行控制台">
      <header className="graph-foreground-topbar">
        <div>
          <span>Graph Task Console</span>
          <strong>{selectedGraph?.title || "图任务前台"}</strong>
          <small>{selectedGraph?.graph_id || "选择图任务定义"} · {selectedGraph?.publish_state || "未加载"}</small>
        </div>
        <div className="graph-foreground-topbar__actions">
          <button disabled={loadingGraphs} onClick={() => void loadGraphs()} type="button">
            <RefreshCw size={14} />
            <span>{loadingGraphs ? "刷新中" : "刷新图任务"}</span>
          </button>
          <button disabled={!selectedGraphId || loadingInstances} onClick={() => void loadInstances(selectedGraphId)} type="button">
            <RefreshCw size={14} />
            <span>{loadingInstances ? "加载中" : "刷新项目"}</span>
          </button>
          <button disabled={!selectedInstance || action === "start-run"} onClick={() => void startRun()} type="button">
            <PlayCircle size={15} />
            <span>{action === "start-run" ? "提交中" : "启动运行"}</span>
          </button>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
      {notice ? <div className="boundary-notice">{notice}</div> : null}

      <div className="graph-foreground-layout">
        <aside className="graph-foreground-rail" aria-label="图任务与项目">
          <section className="graph-foreground-panel graph-foreground-panel--stack">
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
            <div className="graph-foreground-list">
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

          <section className="graph-foreground-panel graph-foreground-panel--stack">
            <header>
              <div>
                <span>项目实例</span>
                <strong>{filteredInstances.length}/{instances.length} 个项目</strong>
              </div>
              <FileText size={15} />
            </header>
            <label className="graph-foreground-search">
              <Search size={14} />
              <input
                onChange={(event) => setInstanceSearch(event.target.value)}
                placeholder="搜索项目实例"
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
            <div className="graph-foreground-list graph-foreground-list--instances">
              {filteredInstances.map((instance) => {
                const active = instance.graph_task_instance_id === selectedInstance?.graph_task_instance_id;
                const tone = statusTone(instance.status);
                return (
                  <button
                    aria-current={active ? "page" : undefined}
                    className={classNames(
                      "graph-foreground-list-row",
                      `graph-foreground-list-row--tone-${tone}`,
                      active && "graph-foreground-list-row--active",
                    )}
                    key={instance.graph_task_instance_id}
                    onClick={() => setSelectedInstanceId(instance.graph_task_instance_id)}
                    type="button"
                  >
                    <strong>{instance.title || instance.graph_task_instance_id}</strong>
                    <small>{instance.graph_task_instance_id}</small>
                    <span>{statusLabel(instance.status)} · {timestampLabel(instance.updated_at)}</span>
                  </button>
                );
              })}
              {!instances.length ? <div className="boundary-empty">这个图还没有项目实例。</div> : null}
              {instances.length && !filteredInstances.length ? <div className="boundary-empty">没有匹配的项目实例。</div> : null}
            </div>
          </section>

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
                rows={3}
                value={newInstanceDescription}
              />
            </label>
            <button disabled={!selectedGraph || action === "create-instance"} onClick={() => void createInstance()} type="button">
              <Plus size={14} />
              <span>{action === "create-instance" ? "创建中" : "创建项目实例"}</span>
            </button>
          </section>
        </aside>

        <div className="graph-foreground-workspace">
          <div className="graph-foreground-runtime-row">
        <main className="graph-foreground-main" aria-label="运行焦点画布">
          <section className="graph-foreground-run-head">
            <div>
              <span>当前项目</span>
              <strong>{selectedInstance?.title || "选择或创建项目实例"}</strong>
              <small>{selectedInstance?.graph_task_instance_id || "项目实例是图任务的运行容器"}</small>
            </div>
            <em className={`graph-foreground-status graph-foreground-status--${statusTone(selectedInstance?.status)}`}>
              {statusLabel(selectedInstance?.status)}
            </em>
          </section>

          <section className={classNames(
            "graph-foreground-next-action",
            Boolean(counts.failed || counts.blocked) && "graph-foreground-next-action--attention",
          )}>
            <div>
              <span>下一动作</span>
              <strong>{nextAction}</strong>
            </div>
            <button disabled={!selectedInstance || loadingMonitor} onClick={() => selectedInstance && void refreshInstance(selectedInstance.graph_task_instance_id)} type="button">
              <RefreshCw size={14} />
              <span>{loadingMonitor ? "刷新中" : "刷新监控"}</span>
            </button>
          </section>

          <section className="graph-foreground-run-summary" aria-label="运行摘要">
            <article>
              <span>完成进度</span>
              <strong>{progressPercent}%</strong>
              <small>{totalNodeCount ? `${counts.completed}/${totalNodeCount} 节点完成` : "等待运行数据"}</small>
              <div className="graph-foreground-progress" aria-hidden="true">
                <i style={{ width: `${progressPercent}%` }} />
              </div>
            </article>
            <article className={counts.failed || counts.blocked ? "graph-foreground-summary-card--attention" : ""}>
              <span>运行风险</span>
              <strong>{counts.failed || counts.blocked ? `${counts.failed} 失败 · ${counts.blocked} 阻塞` : "暂无风险"}</strong>
              <small>{counts.running ? `${counts.running} 个节点运行中` : "没有运行中的节点"}</small>
            </article>
            <article>
              <span>最近产物</span>
              <strong>{latestArtifact ? stringValue(latestArtifact.name, stringValue(latestArtifact.path, "未命名产物")) : "暂无产物"}</strong>
              <small>{latestArtifact ? stringValue(latestArtifact.path, "没有文件路径") : "运行后会显示最新文件"}</small>
            </article>
            <article>
              <span>节点会话</span>
              <strong>{counts.sessions}</strong>
              <small>{counts.artifacts} 个产物</small>
            </article>
          </section>

          <section className="graph-foreground-canvas" aria-label="节点运行焦点画布">
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
                    className={classNames(
                      "graph-foreground-node-card",
                      `graph-foreground-node-card--${tone}`,
                      active && "graph-foreground-node-card--active",
                    )}
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
                  <Bot size={28} />
                  <strong>还没有节点运行信号</strong>
                  <span>启动项目后，这里会显示节点状态、输出摘要和节点会话入口。</span>
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
              <div className="boundary-empty">启动运行或选择节点后显示节点输出。</div>
            )}
          </section>
        </aside>
          </div>

        <section className="graph-foreground-library" aria-label="项目正式库">
          <section className="graph-foreground-panel graph-foreground-library__files">
            <header>
              <div>
                <span>项目正式库</span>
                <strong>{fileTree?.total_entries ?? 0} 项文件</strong>
              </div>
              <FolderTree size={15} />
            </header>
            <div className="graph-foreground-library__body">
              <div className="graph-foreground-library__browser">
                <label className="graph-foreground-search">
                  <Search size={14} />
                  <input
                    onChange={(event) => setFileSearch(event.target.value)}
                    placeholder="搜索项目文件"
                    value={fileSearch}
                  />
                </label>
                <div className="graph-foreground-file-tree">
                  {fileTree && filteredTree ? (
                    <FileTree node={filteredTree} onSelectFile={(path) => void loadFile(path)} selectedPath={selectedFilePath} />
                  ) : fileTree ? (
                    <div className="boundary-empty">没有匹配的项目文件。</div>
                  ) : (
                    <div className="boundary-empty">选择项目后显示正式库文件。</div>
                  )}
                </div>
              </div>
              <div className="graph-foreground-library__editor">
                <div className="graph-foreground-file-head">
                  <label>
                    <span>当前文件</span>
                    <input
                      onChange={(event) => setSelectedFilePath(event.target.value)}
                      placeholder="选择或输入文件路径"
                      value={selectedFilePath}
                    />
                  </label>
                  <div className="graph-foreground-mode-switch" role="group" aria-label="文件显示模式">
                    <button
                      aria-pressed={fileEditorMode === "edit"}
                      className={fileEditorMode === "edit" ? "graph-foreground-mode-switch__active" : undefined}
                      onClick={() => setFileEditorMode("edit")}
                      type="button"
                    >
                      <PencilLine size={13} />
                      编辑
                    </button>
                    <button
                      aria-pressed={fileEditorMode === "preview"}
                      className={fileEditorMode === "preview" ? "graph-foreground-mode-switch__active" : undefined}
                      onClick={() => setFileEditorMode("preview")}
                      type="button"
                    >
                      <Eye size={13} />
                      预览
                    </button>
                  </div>
                </div>
                {fileEditorMode === "edit" ? (
                  <textarea
                    disabled={!selectedInstance}
                    onChange={(event) => setFileContent(event.target.value)}
                    placeholder="选择文件后编辑内容"
                    value={fileContent}
                  />
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
                <button disabled={!selectedInstance || !selectedFilePath.trim() || action === "save-file"} onClick={() => void saveSelectedFile()} type="button">
                  <Save size={14} />
                  <span>{action === "save-file" ? "保存中" : "保存文件"}</span>
                </button>
              </div>
              <div className="graph-foreground-library__writer">
                <label>
                  <span>写入正式库</span>
                  <input
                    onChange={(event) => setNewFilePath(event.target.value)}
                    placeholder="input/brief.md"
                    value={newFilePath}
                  />
                </label>
                <div className="graph-foreground-template-grid">
                  {FILE_PATH_TEMPLATES.map((template) => (
                    <button
                      className={newFilePath === template.path ? "graph-foreground-template-grid__active" : undefined}
                      key={template.path}
                      onClick={() => setNewFilePath(template.path)}
                      type="button"
                    >
                      <strong>{template.label}</strong>
                      <small>{template.path}</small>
                    </button>
                  ))}
                </div>
                <textarea
                  disabled={!selectedInstance}
                  onChange={(event) => setNewFileContent(event.target.value)}
                  placeholder="输入要写入项目正式库的内容"
                  value={newFileContent}
                />
                <button disabled={!selectedInstance || !newFilePath.trim() || action === "write-file"} onClick={() => void writeNewFile()} type="button">
                  <FileText size={14} />
                  <span>{action === "write-file" ? "写入中" : "写入项目库"}</span>
                </button>
              </div>
            </div>
          </section>

          <section className="graph-foreground-panel graph-foreground-library__artifacts">
            <header>
              <div>
                <span>运行产物</span>
                <strong>{artifacts.length} 个产物</strong>
              </div>
              <FileText size={15} />
            </header>
            <label className="graph-foreground-search">
              <Search size={14} />
              <input
                onChange={(event) => setArtifactSearch(event.target.value)}
                placeholder="搜索产物"
                value={artifactSearch}
              />
            </label>
            <div className="graph-foreground-artifact-list">
              {filteredArtifacts.slice(0, 80).map((artifact) => {
                const path = stringValue(artifact.path);
                return (
                  <button
                    disabled={!path}
                    key={stringValue(artifact.artifact_id, path)}
                    onClick={() => path && void loadFile(path)}
                    type="button"
                  >
                    <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                    <small>{path || "没有文件路径"}</small>
                    <span>{numberValue(artifact.size)} bytes · {timestampLabel(artifact.updated_at)}</span>
                  </button>
                );
              })}
              {!artifacts.length ? <div className="boundary-empty">运行产物会出现在这里。</div> : null}
              {artifacts.length && !filteredArtifacts.length ? <div className="boundary-empty">没有匹配的运行产物。</div> : null}
            </div>
          </section>
        </section>
        </div>
      </div>
    </section>
  );
}
