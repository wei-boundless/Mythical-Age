"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  FileText,
  FolderTree,
  GitBranch,
  MessageSquare,
  PlayCircle,
  Plus,
  RefreshCw,
  Save,
} from "lucide-react";

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
};

type FileTreeNode = {
  children: FileTreeNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

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
  const nodeSessions = monitor?.node_sessions ?? [];

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
      setInstances(payload.instances);
      setSelectedInstanceId((current) => {
        if (current && payload.instances.some((instance) => instance.graph_task_instance_id === current)) {
          return current;
        }
        return payload.instances[0]?.graph_task_instance_id ?? "";
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
          <button onClick={onOpenEditor} type="button">
            <GitBranch size={14} />
            <span>编辑图定义</span>
          </button>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
      {notice ? <div className="boundary-notice">{notice}</div> : null}

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
              {instances.map((instance) => {
                const active = instance.graph_task_instance_id === selectedInstance?.graph_task_instance_id;
                return (
                  <button
                    aria-current={active ? "page" : undefined}
                    className={classNames("graph-task-instance-row", active && "graph-task-instance-row--active")}
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
              <em>{statusLabel(selectedInstance?.status)}</em>
              <button disabled={!selectedInstance || action === "start"} onClick={() => void startRun()} type="button">
                <PlayCircle size={15} />
                <span>{action === "start" ? "提交中" : "启动运行"}</span>
              </button>
            </div>
          </section>

          <section className="graph-task-instance-metrics" aria-label="运行指标">
            <span>Ready <strong>{counts.ready}</strong></span>
            <span>Running <strong>{counts.running}</strong></span>
            <span>Done <strong>{counts.completed}</strong></span>
            <span>Failed <strong>{counts.failed}</strong></span>
            <span>Blocked <strong>{counts.blocked}</strong></span>
            <span>Sessions <strong>{counts.sessions}</strong></span>
            <span>Artifacts <strong>{counts.artifacts}</strong></span>
          </section>

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
        </main>

        <aside className="graph-task-instance-workbench__files" aria-label="项目文件和产物">
          <section className="graph-task-instance-panel graph-task-file-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>项目文件</span>
                <strong>{fileTree?.total_entries ?? 0} 项</strong>
              </div>
              <FolderTree size={16} />
            </header>
            <div className="graph-task-file-tree">
              {fileTree ? (
                <GraphTaskFileTree
                  node={rootTreeNode}
                  onSelectFile={(path) => void loadFile(path)}
                  selectedPath={selectedFilePath}
                />
              ) : (
                <div className="boundary-empty">选择实例后显示项目文件。</div>
              )}
            </div>
            <div className="graph-task-file-editor">
              <label>
                <span>当前文件</span>
                <input
                  onChange={(event) => setSelectedFilePath(event.target.value)}
                  placeholder="选择或输入文件路径"
                  value={selectedFilePath}
                />
              </label>
              <textarea
                disabled={!selectedInstance}
                onChange={(event) => setFileContent(event.target.value)}
                placeholder="选择文件后编辑内容"
                rows={8}
                value={fileContent}
              />
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
              <textarea
                disabled={!selectedInstance}
                onChange={(event) => setNewFileContent(event.target.value)}
                placeholder="输入需要放入项目文件区的内容"
                rows={4}
                value={newFileContent}
              />
              <button disabled={!selectedInstance || !newFilePath.trim() || action === "new-file"} onClick={() => void createOrOverwriteFile()} type="button">
                <FileText size={14} />
                <span>{action === "new-file" ? "写入中" : "写入项目文件"}</span>
              </button>
            </div>
          </section>

          <section className="graph-task-instance-panel graph-task-artifact-panel">
            <header className="graph-task-instance-panel__head">
              <div>
                <span>产物</span>
                <strong>{artifacts.length} 个文件</strong>
              </div>
              <FileText size={16} />
            </header>
            <div className="graph-task-artifact-list">
              {artifacts.slice(0, 30).map((artifact) => (
                <button
                  key={stringValue(artifact.artifact_id, stringValue(artifact.path))}
                  onClick={() => void loadFile(stringValue(artifact.path))}
                  type="button"
                >
                  <strong>{stringValue(artifact.name, stringValue(artifact.path))}</strong>
                  <small>{stringValue(artifact.path)}</small>
                  <span>{numberValue(artifact.size)} bytes · {timestampLabel(artifact.updated_at)}</span>
                </button>
              ))}
              {!artifacts.length ? <div className="boundary-empty">运行产物会进入实例项目空间。</div> : null}
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
