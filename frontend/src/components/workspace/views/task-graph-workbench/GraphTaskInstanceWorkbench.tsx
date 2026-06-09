"use client";

import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  Bot,
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
  listGraphTasks,
  listGraphTaskInstances,
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

type GraphTaskInstanceWorkbenchProps = {
  graphTasks: GraphTaskDefinitionSummary[];
  onOpenEditor?: () => void;
  onSelectedGraphChange?: (graphId: string) => void;
  selectedGraphId: string;
  showEditorAction?: boolean;
};

type FileTreeNode = {
  children: FileTreeNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

type FileEditorMode = "edit" | "preview";

const FILE_PATH_TEMPLATES = [
  { label: "任务简报", path: "input/brief.md" },
  { label: "世界观", path: "world/world.md" },
  { label: "角色表", path: "characters/characters.md" },
  { label: "大纲", path: "outline/outline.md" },
  { label: "正文 001", path: "chapters/chapter-001.md" },
  { label: "审校记录", path: "review/review-notes.md" },
] as const;

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

function timestampLabel(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "-";
  const milliseconds = numeric > 10_000_000_000 ? numeric : numeric * 1000;
  return new Date(milliseconds).toLocaleString("zh-CN", {
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
    running: "运行中",
    dispatching: "派发中",
    blocked: "阻塞",
    paused: "已暂停",
    failed: "失败",
    error: "错误",
    completed: "已完成",
    done: "已完成",
    stopped: "已停止",
  };
  return labels[status] ?? status;
}

function statusTone(value: unknown) {
  const status = stringValue(value, "idle").toLowerCase();
  if (["running", "dispatching", "pending"].includes(status)) return "active";
  if (["blocked", "failed", "error"].includes(status)) return "attention";
  if (["completed", "done"].includes(status)) return "success";
  if (["paused", "stopped"].includes(status)) return "paused";
  return "idle";
}

function timestampValue(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return numeric > 10_000_000_000 ? numeric : numeric * 1000;
}

function instancePriority(instance: GraphTaskInstanceSummary) {
  const tone = statusTone(instance.status);
  if (tone === "attention") return 0;
  if (tone === "active") return 1;
  if (tone === "paused") return 2;
  if (tone === "idle") return 3;
  if (tone === "success") return 4;
  return 5;
}

function sortInstancesForOperations(instances: GraphTaskInstanceSummary[]) {
  return [...instances].sort((left, right) => {
    const priority = instancePriority(left) - instancePriority(right);
    if (priority) return priority;
    return timestampValue(right.updated_at) - timestampValue(left.updated_at);
  });
}

function nextActionText(instance: GraphTaskInstanceSummary | null, counts: ReturnType<typeof monitorCounts>) {
  if (!instance) return "先创建或选择一个实例项目。";
  if (counts.failed || counts.blocked) return "优先查看阻塞节点、节点会话和运行监控。";
  const tone = statusTone(instance.status);
  if (tone === "active") return "运行中，重点观察节点会话、产物和失败计数。";
  if (tone === "success") return "已完成，检查产物并决定是否开启下一轮。";
  if (tone === "paused") return "已暂停，可以从运行监控继续或重新提交。";
  return "实例已就绪，可以启动后台运行。";
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

function parseTreeNode(value: unknown): FileTreeNode {
  const record = recordOf(value);
  const children = Array.isArray(record.children)
    ? record.children.map(parseTreeNode)
    : [];
  return {
    children,
    kind: stringValue(record.kind, "file"),
    name: stringValue(record.name, stringValue(record.path, "root")),
    path: stringValue(record.path),
  };
}

function normalizedQuery(value: string) {
  return value.trim().toLowerCase();
}

function fileTreeMatches(node: FileTreeNode, query: string) {
  if (!query) return true;
  return `${node.name} ${node.path}`.toLowerCase().includes(query);
}

function filterFileTreeNode(node: FileTreeNode, query: string): FileTreeNode | null {
  if (!query) return node;
  const children = node.children
    .map((child) => filterFileTreeNode(child, query))
    .filter((child): child is FileTreeNode => Boolean(child));
  if (fileTreeMatches(node, query) || children.length) {
    return { ...node, children };
  }
  return null;
}

function countFileTreeFiles(node: FileTreeNode | null): number {
  if (!node) return 0;
  return (node.kind === "file" && node.path ? 1 : 0)
    + node.children.reduce((total, child) => total + countFileTreeFiles(child), 0);
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

function sessionRoleLabel(session: SessionSummary) {
  const role = stringValue(recordOf(session).session_role);
  if (role === "root") return "项目主会话";
  return "节点会话";
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

function GraphTaskFileTree({
  node,
  onSelectFile,
  selectedPath,
}: {
  node: FileTreeNode;
  onSelectFile: (path: string) => void;
  selectedPath: string;
}) {
  const children = node.children ?? [];
  const isFile = node.kind === "file";
  const visibleName = node.path ? node.name : "项目文件";
  return (
    <div className="graph-task-file-tree__node">
      <button
        aria-current={isFile && node.path === selectedPath ? "true" : undefined}
        className={classNames(
          "graph-task-file-tree__row",
          isFile && node.path === selectedPath ? "graph-task-file-tree__row--active" : false,
        )}
        disabled={!isFile}
        onClick={() => isFile && onSelectFile(node.path)}
        type="button"
      >
        <span>{node.kind === "directory" ? "DIR" : "FILE"}</span>
        <strong>{visibleName}</strong>
      </button>
      {children.length ? (
        <div className="graph-task-file-tree__children">
          {children.map((child) => (
            <GraphTaskFileTree
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

export function GraphTaskInstanceWorkbench({
  graphTasks,
  onOpenEditor,
  onSelectedGraphChange,
  selectedGraphId,
  showEditorAction = true,
}: GraphTaskInstanceWorkbenchProps) {
  const {
    bindTaskGraphMonitorRun,
    currentSessionId,
    selectSession,
    setTaskGraphRunInteractionOpen,
  } = useAppStore();
  const [apiGraphTasks, setApiGraphTasks] = useState<GraphTaskDefinitionSummary[]>([]);
  const graphTaskOptions = graphTasks.length ? graphTasks : apiGraphTasks;
  const selectedGraph = useMemo(
    () => graphTaskOptions.find((graph) => graph.graph_id === selectedGraphId) ?? graphTaskOptions[0] ?? null,
    [graphTaskOptions, selectedGraphId],
  );
  const effectiveGraphId = selectedGraph?.graph_id ?? "";
  const [instances, setInstances] = useState<GraphTaskInstanceSummary[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [monitor, setMonitor] = useState<GraphTaskInstanceMonitor | null>(null);
  const [fileTree, setFileTree] = useState<GraphTaskInstanceFileTree | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newInstanceTitle, setNewInstanceTitle] = useState("");
  const [newInstanceDescription, setNewInstanceDescription] = useState("");
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [newFilePath, setNewFilePath] = useState("input/brief.md");
  const [newFileContent, setNewFileContent] = useState("");
  const [fileSearch, setFileSearch] = useState("");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [fileEditorMode, setFileEditorMode] = useState<FileEditorMode>("edit");
  const deferredFileSearch = useDeferredValue(fileSearch);
  const deferredArtifactSearch = useDeferredValue(artifactSearch);
  const counts = monitorCounts(monitor);
  const selectedInstance = useMemo(
    () => instances.find((instance) => instance.graph_task_instance_id === selectedInstanceId)
      ?? monitor?.instance
      ?? instances[0]
      ?? null,
    [instances, monitor, selectedInstanceId],
  );
  const rootTreeNode = useMemo(() => parseTreeNode(fileTree?.tree), [fileTree]);
  const artifacts = monitor?.artifacts.artifacts ?? [];
  const fileQuery = normalizedQuery(deferredFileSearch);
  const artifactQuery = normalizedQuery(deferredArtifactSearch);
  const filteredRootTreeNode = useMemo(
    () => filterFileTreeNode(rootTreeNode, fileQuery),
    [fileQuery, rootTreeNode],
  );
  const visibleFileCount = useMemo(() => countFileTreeFiles(filteredRootTreeNode), [filteredRootTreeNode]);
  const filteredArtifacts = useMemo(
    () => artifacts.filter((artifact) => artifactMatches(artifact, artifactQuery)),
    [artifactQuery, artifacts],
  );
  const nodeSessions = monitor?.node_sessions ?? [];
  const sortedInstances = useMemo(() => sortInstancesForOperations(instances), [instances]);
  const activeInstanceCount = useMemo(
    () => instances.filter((instance) => statusTone(instance.status) === "active").length,
    [instances],
  );
  const attentionInstanceCount = useMemo(
    () => instances.filter((instance) => statusTone(instance.status) === "attention").length,
    [instances],
  );
  const nextAction = nextActionText(selectedInstance, counts);

  useEffect(() => {
    if (graphTasks.length) return;
    let cancelled = false;
    void listGraphTasks()
      .then((payload) => {
        if (!cancelled) setApiGraphTasks(payload.graph_tasks);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "图任务定义加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [graphTasks.length]);

  useEffect(() => {
    if (!graphTaskOptions.length) return;
    if (selectedGraphId && graphTaskOptions.some((graph) => graph.graph_id === selectedGraphId)) return;
    onSelectedGraphChange?.(graphTaskOptions[0].graph_id);
  }, [graphTaskOptions, onSelectedGraphChange, selectedGraphId]);

  const loadInstances = useCallback(async (graphId: string) => {
    if (!graphId) {
      setInstances([]);
      setSelectedInstanceId("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const payload = await listGraphTaskInstances(graphId);
      const sortedPayloadInstances = sortInstancesForOperations(payload.instances);
      setInstances(sortedPayloadInstances);
      setSelectedInstanceId((current) => {
        if (current && sortedPayloadInstances.some((instance) => instance.graph_task_instance_id === current)) {
          return current;
        }
        return sortedPayloadInstances[0]?.graph_task_instance_id ?? "";
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "图任务实例加载失败");
      setInstances([]);
      setSelectedInstanceId("");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshInstance = useCallback(async (instanceId: string) => {
    if (!instanceId) {
      setMonitor(null);
      setFileTree(null);
      return;
    }
    setError("");
    try {
      const [monitorPayload, treePayload] = await Promise.all([
        getGraphTaskInstanceMonitor(instanceId, 80),
        getGraphTaskInstanceFileTree(instanceId, { maxDepth: 5, maxEntries: 800 }).catch(() => null),
      ]);
      setMonitor(monitorPayload);
      setFileTree(treePayload);
      setInstances((current) => current.map((instance) => (
        instance.graph_task_instance_id === monitorPayload.instance.graph_task_instance_id
          ? monitorPayload.instance
          : instance
      )));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "图任务实例监控刷新失败");
    }
  }, []);

  useEffect(() => {
    if (!effectiveGraphId) return;
    void loadInstances(effectiveGraphId);
  }, [effectiveGraphId, loadInstances]);

  useEffect(() => {
    if (!selectedInstanceId) {
      setMonitor(null);
      setFileTree(null);
      setSelectedFilePath("");
      setFileContent("");
      return;
    }
    void refreshInstance(selectedInstanceId);
  }, [refreshInstance, selectedInstanceId]);

  useEffect(() => {
    if (!selectedGraph) return;
    setNewInstanceTitle((current) => current || `${selectedGraph.title || selectedGraph.graph_id} 项目 ${instances.length + 1}`);
  }, [instances.length, selectedGraph]);

  async function createInstance() {
    if (!effectiveGraphId || !selectedGraph) return;
    const title = newInstanceTitle.trim() || `${selectedGraph.title || effectiveGraphId} 项目 ${instances.length + 1}`;
    setAction("create");
    setError("");
    setNotice("");
    try {
      const payload = await createGraphTaskInstance(effectiveGraphId, {
        title,
        description: newInstanceDescription.trim(),
        metadata: {
          created_from: "graph_task_instance_workbench",
        },
      });
      setInstances((current) => [payload.instance, ...current.filter((item) => item.graph_task_instance_id !== payload.instance.graph_task_instance_id)]);
      setSelectedInstanceId(payload.instance.graph_task_instance_id);
      setNewInstanceTitle("");
      setNewInstanceDescription("");
      setNotice("图任务实例项目已创建。");
      await refreshInstance(payload.instance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建图任务实例失败");
    } finally {
      setAction("");
    }
  }

  async function startRun() {
    if (!selectedInstance) return;
    const instanceId = selectedInstance.graph_task_instance_id;
    setAction("start");
    setError("");
    setNotice("");
    try {
      const payload = await startGraphTaskInstanceRun(instanceId, {
        dispatch_ready: true,
        run_mode: "auto_run",
        wait_for_completion: false,
        initial_inputs: {
          requested_from: "graph_task_instance_workbench",
        },
      });
      const start = payload.start;
      const sessionScope = graphTaskScope(instanceId);
      bindTaskGraphMonitorRun({
        task_run_id: start.task_run_id,
        graph_run_id: start.graph_run_id,
        graph_harness_config_id: start.graph_harness_config_id,
        graph_id: payload.instance.graph_id,
        session_id: start.graph_session_id || start.launch_session_id || payload.instance.root_session_id,
        project_id: instanceId,
        session_scope: sessionScope,
        title: payload.instance.title || payload.instance.graph_id,
      });
      setTaskGraphRunInteractionOpen(true);
      setInstances((current) => current.map((item) => (
        item.graph_task_instance_id === payload.instance.graph_task_instance_id ? payload.instance : item
      )));
      setSelectedInstanceId(payload.instance.graph_task_instance_id);
      setNotice("实例运行已提交后台执行。");
      await refreshInstance(payload.instance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "启动图任务实例运行失败");
    } finally {
      setAction("");
    }
  }

  async function openSession(session: SessionSummary) {
    if (!selectedInstance) return;
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
      setError(caught instanceof Error ? caught.message : "文件读取失败");
    } finally {
      setAction("");
    }
  }

  async function saveSelectedFile() {
    if (!selectedInstance || !selectedFilePath) return;
    setAction("save-file");
    setError("");
    setNotice("");
    try {
      await writeGraphTaskInstanceFile(selectedInstance.graph_task_instance_id, selectedFilePath, fileContent);
      setNotice(`已保存 ${selectedFilePath}`);
      await refreshInstance(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件保存失败");
    } finally {
      setAction("");
    }
  }

  async function createOrOverwriteFile() {
    if (!selectedInstance || !newFilePath.trim()) return;
    setAction("new-file");
    setError("");
    setNotice("");
    try {
      const result = await writeGraphTaskInstanceFile(selectedInstance.graph_task_instance_id, newFilePath.trim(), newFileContent);
      setSelectedFilePath(result.path);
      setFileContent(newFileContent);
      setNewFileContent("");
      setNotice(`已写入 ${result.path}`);
      await refreshInstance(selectedInstance.graph_task_instance_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件写入失败");
    } finally {
      setAction("");
    }
  }

  const graphSummary = selectedGraph
    ? `${selectedGraph.graph_kind || "task_graph"} · ${selectedGraph.publish_state || "draft"}`
    : "未选择任务图";

  return (
    <section className="graph-task-instance-workbench" aria-label="图任务实例项目工作区">
      <header className="graph-task-instance-workbench__header">
        <div>
          <span>Graph Task Project</span>
          <strong>{selectedGraph?.title || "选择图任务定义"}</strong>
          <small>{effectiveGraphId || "没有可运行的图定义"} · {graphSummary}</small>
        </div>
        <div className="graph-task-instance-workbench__actions">
          <button disabled={!effectiveGraphId || loading} onClick={() => void loadInstances(effectiveGraphId)} type="button">
            <RefreshCw size={14} />
            <span>{loading ? "刷新中" : "刷新实例"}</span>
          </button>
          <button disabled={!selectedInstanceId || action === "refresh"} onClick={() => void refreshInstance(selectedInstanceId)} type="button">
            <RefreshCw size={14} />
            <span>刷新监控</span>
          </button>
          {showEditorAction ? (
            <button onClick={onOpenEditor} type="button">
              <GitBranch size={14} />
              <span>编辑图定义</span>
            </button>
          ) : null}
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
      {notice ? <div className="boundary-notice">{notice}</div> : null}

      <section className="graph-task-ops-summary" aria-label="图任务项目总览">
        <article>
          <span>图定义</span>
          <strong>{graphTaskOptions.length}</strong>
          <small>{selectedGraph?.publish_state || "未选择"}</small>
        </article>
        <article className={activeInstanceCount ? "graph-task-ops-summary__tile--active" : ""}>
          <span>运行中</span>
          <strong>{activeInstanceCount}</strong>
          <small>{instances.length} 个实例项目</small>
        </article>
        <article className={attentionInstanceCount ? "graph-task-ops-summary__tile--attention" : ""}>
          <span>需处理</span>
          <strong>{attentionInstanceCount + counts.failed + counts.blocked}</strong>
          <small>失败、阻塞或停滞优先</small>
        </article>
        <article>
          <span>当前资产</span>
          <strong>{counts.sessions + counts.artifacts}</strong>
          <small>{counts.sessions} 会话 · {counts.artifacts} 产物</small>
        </article>
      </section>

      <div className="graph-task-instance-workbench__body">
        <aside className="graph-task-instance-workbench__rail" aria-label="图定义和实例项目">
          <section className="graph-task-instance-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>图定义</span>
                <strong>{graphTaskOptions.length} 张图</strong>
              </div>
            </header>
            <div className="graph-task-definition-list">
              {graphTaskOptions.map((graph) => {
                const active = graph.graph_id === effectiveGraphId;
                return (
                  <button
                    aria-current={active ? "page" : undefined}
                    className={classNames("graph-task-definition-row", active && "graph-task-definition-row--active")}
                    key={graph.graph_id}
                    onClick={() => onSelectedGraphChange?.(graph.graph_id)}
                    type="button"
                  >
                    <strong>{graph.title || graph.graph_id}</strong>
                    <small>{graph.graph_id}</small>
                    <span>{graph.publish_state || "draft"}</span>
                  </button>
                );
              })}
              {!graphTaskOptions.length ? <div className="boundary-empty">还没有可运行的图任务定义。</div> : null}
            </div>
          </section>

          <section className="graph-task-instance-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>实例项目</span>
                <strong>{instances.length} 个项目</strong>
              </div>
            </header>
            <div className="graph-task-instance-list">
              {sortedInstances.map((instance) => {
                const active = instance.graph_task_instance_id === selectedInstance?.graph_task_instance_id;
                const tone = statusTone(instance.status);
                return (
                  <button
                    aria-current={active ? "page" : undefined}
                    className={classNames(
                      "graph-task-instance-row",
                      `graph-task-instance-row--tone-${tone}`,
                      active && "graph-task-instance-row--active",
                    )}
                    key={instance.graph_task_instance_id}
                    onClick={() => setSelectedInstanceId(instance.graph_task_instance_id)}
                    type="button"
                  >
                    <strong>{instance.title || instance.graph_task_instance_id}</strong>
                    <small>{instance.graph_task_instance_id}</small>
                    <span className="graph-task-instance-row__status">{statusLabel(instance.status)} · {timestampLabel(instance.updated_at)}</span>
                  </button>
                );
              })}
              {!instances.length ? <div className="boundary-empty">这个图还没有实例项目。</div> : null}
            </div>
          </section>

          <section className="graph-task-instance-panel graph-task-instance-panel--create">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>新实例</span>
                <strong>创建项目</strong>
              </div>
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
                placeholder="可选：目标、范围、人工约束"
                rows={3}
                value={newInstanceDescription}
              />
            </label>
            <button disabled={!effectiveGraphId || action === "create"} onClick={() => void createInstance()} type="button">
              <Plus size={14} />
              <span>{action === "create" ? "创建中" : "创建实例项目"}</span>
            </button>
          </section>
        </aside>

        <main className="graph-task-instance-workbench__main" aria-label="实例运行监控">
          <section className="graph-task-instance-hero">
            <div>
              <span>当前实例</span>
              <strong>{selectedInstance?.title || "选择或创建实例项目"}</strong>
              <small>{selectedInstance?.graph_task_instance_id || "实例是图任务的项目级运行容器"}</small>
            </div>
            <div className="graph-task-instance-hero__status">
              <em className={`graph-task-instance-status-pill graph-task-instance-status-pill--${statusTone(selectedInstance?.status)}`}>
                {statusLabel(selectedInstance?.status)}
              </em>
              <button disabled={!selectedInstance || action === "start"} onClick={() => void startRun()} type="button">
                <PlayCircle size={15} />
                <span>{action === "start" ? "提交中" : "启动运行"}</span>
              </button>
            </div>
          </section>

          <section className={classNames(
            "graph-task-next-action",
            Boolean(counts.failed || counts.blocked || attentionInstanceCount) && "graph-task-next-action--attention",
          )} aria-label="下一动作">
            <div>
              <span>下一动作</span>
              <strong>{nextAction}</strong>
            </div>
            <small>
              {selectedInstance
                ? `${selectedInstance.graph_task_instance_id} · ${timestampLabel(selectedInstance.updated_at)}`
                : "没有实例时无法启动图运行"}
            </small>
          </section>

          <section className="graph-task-instance-metrics" aria-label="运行指标">
            <span>Ready <strong>{counts.ready}</strong></span>
            <span className={counts.running ? "graph-task-instance-metric--active" : ""}>Running <strong>{counts.running}</strong></span>
            <span className={counts.completed ? "graph-task-instance-metric--success" : ""}>Done <strong>{counts.completed}</strong></span>
            <span className={counts.failed ? "graph-task-instance-metric--attention" : ""}>Failed <strong>{counts.failed}</strong></span>
            <span className={counts.blocked ? "graph-task-instance-metric--attention" : ""}>Blocked <strong>{counts.blocked}</strong></span>
            <span>Sessions <strong>{counts.sessions}</strong></span>
            <span>Artifacts <strong>{counts.artifacts}</strong></span>
          </section>

        </main>

        <section className="graph-task-instance-workbench__files" aria-label="项目文件和产物">
          <section className="graph-task-instance-panel graph-task-file-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>文件中心</span>
                <strong>{fileTree?.total_entries ?? 0} 项 · {fileQuery ? `${visibleFileCount} 个匹配文件` : `${visibleFileCount} 个文件`}</strong>
              </div>
              <FolderTree size={16} />
            </header>
            <div className="graph-task-file-panel__body">
              <div className="graph-task-file-panel__browser">
                <div className="graph-task-file-toolbar">
                  <label className="graph-task-filter-input">
                    <Search size={14} />
                    <input
                      onChange={(event) => setFileSearch(event.target.value)}
                      placeholder="搜索文件路径或名称"
                      value={fileSearch}
                    />
                  </label>
                  {fileSearch ? (
                    <button onClick={() => setFileSearch("")} type="button">
                      清除
                    </button>
                  ) : null}
                </div>
                <div className="graph-task-file-tree">
                  {fileTree && filteredRootTreeNode ? (
                    <GraphTaskFileTree
                      node={filteredRootTreeNode}
                      onSelectFile={(path) => void loadFile(path)}
                      selectedPath={selectedFilePath}
                    />
                  ) : fileTree ? (
                    <div className="boundary-empty">没有匹配的项目文件。</div>
                  ) : (
                    <div className="boundary-empty">选择实例后显示项目文件。</div>
                  )}
                </div>
              </div>
              <div className="graph-task-file-panel__editor-stack">
                <div className="graph-task-file-editor">
                  <div className="graph-task-file-editor__head">
                    <label>
                      <span>当前文件</span>
                      <input
                        onChange={(event) => setSelectedFilePath(event.target.value)}
                        placeholder="选择或输入文件路径"
                        value={selectedFilePath}
                      />
                    </label>
                    <div className="graph-task-file-editor-mode" role="group" aria-label="当前文件显示模式">
                      <button
                        aria-pressed={fileEditorMode === "edit"}
                        className={fileEditorMode === "edit" ? "graph-task-file-editor-mode__button--active" : undefined}
                        onClick={() => setFileEditorMode("edit")}
                        title="编辑"
                        type="button"
                      >
                        <PencilLine size={14} />
                        <span>编辑</span>
                      </button>
                      <button
                        aria-pressed={fileEditorMode === "preview"}
                        className={fileEditorMode === "preview" ? "graph-task-file-editor-mode__button--active" : undefined}
                        onClick={() => setFileEditorMode("preview")}
                        title="预览"
                        type="button"
                      >
                        <Eye size={14} />
                        <span>预览</span>
                      </button>
                    </div>
                  </div>
                  {fileEditorMode === "edit" ? (
                    <textarea
                      disabled={!selectedInstance}
                      onChange={(event) => setFileContent(event.target.value)}
                      placeholder="选择文件后编辑内容"
                      rows={12}
                      value={fileContent}
                    />
                  ) : (
                    <div className="graph-task-file-preview markdown" aria-label="当前文件预览">
                      {fileContent.trim() ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {fileContent}
                        </ReactMarkdown>
                      ) : (
                        <p>选择文件后显示预览。</p>
                      )}
                    </div>
                  )}
                  <button disabled={!selectedInstance || !selectedFilePath || action === "save-file"} onClick={() => void saveSelectedFile()} type="button">
                    <Save size={14} />
                    <span>{action === "save-file" ? "保存中" : "保存文件"}</span>
                  </button>
                </div>
                <div className="graph-task-file-editor graph-task-file-editor--new">
                  <label>
                    <span>写入文件</span>
                    <input
                      onChange={(event) => setNewFilePath(event.target.value)}
                      placeholder="input/brief.md"
                      value={newFilePath}
                    />
                  </label>
                  <div className="graph-task-file-template-grid" aria-label="常用写作文件路径">
                    {FILE_PATH_TEMPLATES.map((template) => (
                      <button
                        className={newFilePath === template.path ? "graph-task-file-template-grid__button--active" : undefined}
                        key={template.path}
                        onClick={() => setNewFilePath(template.path)}
                        type="button"
                      >
                        <span>{template.label}</span>
                        <small>{template.path}</small>
                      </button>
                    ))}
                  </div>
                  <textarea
                    disabled={!selectedInstance}
                    onChange={(event) => setNewFileContent(event.target.value)}
                    placeholder="输入需要放入项目文件区的内容"
                    rows={5}
                    value={newFileContent}
                  />
                  <button disabled={!selectedInstance || !newFilePath.trim() || action === "new-file"} onClick={() => void createOrOverwriteFile()} type="button">
                    <FileText size={14} />
                    <span>{action === "new-file" ? "写入中" : "写入项目文件"}</span>
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="graph-task-instance-panel graph-task-artifact-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>产物</span>
                <strong>{artifacts.length} 个文件{artifactQuery ? ` · ${filteredArtifacts.length} 个匹配` : ""}</strong>
              </div>
              <FileText size={16} />
            </header>
            <div className="graph-task-artifact-toolbar">
              <label className="graph-task-filter-input">
                <Search size={14} />
                <input
                  onChange={(event) => setArtifactSearch(event.target.value)}
                  placeholder="搜索产物路径、名称或类型"
                  value={artifactSearch}
                />
              </label>
              {artifactSearch ? (
                <button onClick={() => setArtifactSearch("")} type="button">
                  清除
                </button>
              ) : null}
            </div>
            <div className="graph-task-artifact-list">
              {filteredArtifacts.slice(0, 60).map((artifact) => {
                const path = stringValue(artifact.path);
                return (
                  <button
                    className={path && path === selectedFilePath ? "graph-task-artifact-list__row--active" : undefined}
                    disabled={!path}
                    key={stringValue(artifact.artifact_id, path)}
                    onClick={() => path && void loadFile(path)}
                    title={path ? "载入当前文件编辑器" : "这个产物没有可读取路径"}
                    type="button"
                  >
                    <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                    <small>{path || "没有文件路径"}</small>
                    <span>{numberValue(artifact.size)} bytes · {timestampLabel(artifact.updated_at)}</span>
                  </button>
                );
              })}
              {!artifacts.length ? <div className="boundary-empty">运行产物会进入实例项目空间。</div> : null}
              {artifacts.length && !filteredArtifacts.length ? <div className="boundary-empty">没有匹配的运行产物。</div> : null}
            </div>
          </section>
        </section>

        <section className="graph-task-instance-workbench__sessions" aria-label="节点会话">
          <section className="graph-task-instance-panel graph-task-node-session-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>节点会话</span>
                <strong>每个节点独立沟通记录</strong>
              </div>
              <Bot size={16} />
            </header>
            <div className="graph-task-node-session-list">
              {nodeSessions.map((session) => {
                const nodeLabel = sessionNodeLabel(session);
                return (
                  <button
                    className={classNames("graph-task-node-session-row", currentSessionId === session.id && "graph-task-node-session-row--active")}
                    key={session.id}
                    onClick={() => void openSession(session)}
                    type="button"
                  >
                    <MessageSquare size={15} />
                    <strong>{session.title || session.id}</strong>
                    <small>{sessionRoleLabel(session)}{nodeLabel ? ` · ${nodeLabel}` : ""}</small>
                    <span>{session.message_count ?? 0} 条消息 · {timestampLabel(session.updated_at)}</span>
                  </button>
                );
              })}
              {!nodeSessions.length ? <div className="boundary-empty">运行后会在这里看到项目主会话和节点会话。</div> : null}
            </div>
          </section>
        </section>
      </div>
    </section>
  );
}
