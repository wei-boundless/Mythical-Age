"use client";

import { useCallback, useEffect, useState } from "react";
import { Archive, FolderTree, PlayCircle, RefreshCw } from "lucide-react";
import {
  getGraphTaskInstanceFileTree,
  getGraphTaskInstanceMonitor,
  listGraphTaskInstanceArtifacts,
  listGraphTaskInstanceNodeSessions,
  startGraphTaskInstanceRun,
  type GraphTaskInstanceArtifacts,
  type GraphTaskInstanceFileTree,
  type GraphTaskInstanceMonitor,
  type GraphTaskInstanceSummary,
  type SessionSummary,
  type TaskGraphRecord,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

import type { GraphInstanceWorkspaceExtension } from "../templates/graphTemplateTypes";
import { GraphInstanceArtifactManager } from "./GraphInstanceArtifactManager";
import { GraphInstanceFileManager } from "./GraphInstanceFileManager";
import { GraphInstanceNodeSessions } from "./GraphInstanceNodeSessions";
import { GraphInstanceRunMonitor } from "./GraphInstanceRunMonitor";

type InstanceCenterPanel = "files" | "artifacts";

export function GraphInstanceWorkspace({
  activeGraph,
  extensions,
  graphMetadata,
  graphTitle,
  initialPanel = "files",
  instance,
  instances = [],
  instancesLoading = false,
  onCreateInstance,
  onRefreshInstances,
  onSelectInstance,
  selectedInstanceId = "",
  variant = "standalone",
}: {
  instance: GraphTaskInstanceSummary | null;
  activeGraph?: TaskGraphRecord | null;
  extensions: GraphInstanceWorkspaceExtension[];
  graphMetadata?: Record<string, unknown>;
  graphTitle?: string;
  instances?: GraphTaskInstanceSummary[];
  instancesLoading?: boolean;
  initialPanel?: InstanceCenterPanel;
  selectedInstanceId?: string;
  onCreateInstance?: () => void;
  onRefreshInstances?: () => void;
  onSelectInstance?: (instance: GraphTaskInstanceSummary) => void;
  variant?: "standalone" | "canvas";
}) {
  const { openSessionProjection } = useAppStore();
  const [fileTree, setFileTree] = useState<GraphTaskInstanceFileTree | null>(null);
  const [artifacts, setArtifacts] = useState<GraphTaskInstanceArtifacts | null>(null);
  const [nodeSessions, setNodeSessions] = useState<SessionSummary[]>([]);
  const [monitor, setMonitor] = useState<GraphTaskInstanceMonitor | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [centerPanel, setCenterPanel] = useState<InstanceCenterPanel>(initialPanel);
  const [error, setError] = useState("");

  useEffect(() => {
    setCenterPanel(initialPanel);
  }, [initialPanel]);

  const loadWorkspace = useCallback(async () => {
    if (!instance?.graph_task_instance_id) {
      setFileTree(null);
      setArtifacts(null);
      setNodeSessions([]);
      setMonitor(null);
      return;
    }
    const instanceId = instance.graph_task_instance_id;
    setLoading(true);
    setError("");
    try {
      const [tree, artifactPayload, sessionsPayload, monitorPayload] = await Promise.all([
        getGraphTaskInstanceFileTree(instanceId, { maxDepth: 4, maxEntries: 160 }).catch(() => null),
        listGraphTaskInstanceArtifacts(instanceId).catch(() => null),
        listGraphTaskInstanceNodeSessions(instanceId).catch(() => ({ sessions: [] })),
        getGraphTaskInstanceMonitor(instanceId, 80).catch(() => null),
      ]);
      setFileTree(tree);
      setArtifacts(artifactPayload);
      setNodeSessions(sessionsPayload.sessions ?? []);
      setMonitor(monitorPayload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "项目监控加载失败");
    } finally {
      setLoading(false);
    }
  }, [instance]);

  useEffect(() => {
    let cancelled = false;
    void loadWorkspace().finally(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, [loadWorkspace]);

  async function startRun() {
    if (!instance?.graph_task_instance_id) return;
    setAction("start");
    setError("");
    try {
      await startGraphTaskInstanceRun(instance.graph_task_instance_id, { run_mode: "auto_run" });
      await loadWorkspace();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动项目运行失败");
    } finally {
      setAction("");
    }
  }

  async function refreshAll() {
    onRefreshInstances?.();
    await loadWorkspace();
  }

  if (!instance) {
    const graphState = activeGraph?.enabled ? "已发布" : activeGraph?.publish_state || "草稿";
    return (
      <section className={`graph-instance-workbench graph-instance-workbench--${variant} graph-instance-workbench--empty`} aria-label="任务图项目监控">
        <div className="graph-instance-project-launcher">
          <header>
            <div>
              <span>项目启动</span>
              <strong>监控态需要一个任务图项目</strong>
            </div>
            {onCreateInstance ? (
              <button onClick={onCreateInstance} type="button">
                <PlayCircle size={14} />
                <span>封装</span>
              </button>
            ) : null}
          </header>
          <div className="graph-instance-project-launcher__facts" aria-label="项目启动状态">
            <ProjectFact label="当前图" value={activeGraph?.title || graphTitle || "未打开图定义"} />
            <ProjectFact label="发布状态" value={graphState} />
            <ProjectFact label="项目" value={instancesLoading ? "读取中" : `${instances.length} 个`} />
            <ProjectFact label="Agent 会话" value="待创建" />
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className={`graph-instance-workbench graph-instance-workbench--${variant}`} aria-label="任务图项目监控">
      <header className="graph-instance-workbench__header">
        <div>
          <span>{variant === "canvas" ? "监控态项目插件" : "任务图项目监控"}</span>
          <strong>{instance.title || instance.graph_task_instance_id}</strong>
        </div>
        <nav aria-label="任务图项目操作">
          {instances.length > 1 && onSelectInstance ? (
            <select
              aria-label="切换任务图项目"
              disabled={loading || instancesLoading}
              onChange={(event) => {
                const next = instances.find((item) => item.graph_task_instance_id === event.target.value);
                if (next) onSelectInstance(next);
              }}
              value={selectedInstanceId || instance.graph_task_instance_id}
            >
              {instances.map((item) => (
                <option key={item.graph_task_instance_id} value={item.graph_task_instance_id}>
                  {item.title || item.graph_task_instance_id}
                </option>
              ))}
            </select>
          ) : null}
          <button disabled={loading || Boolean(action)} onClick={() => void refreshAll()} title="刷新项目监控" type="button">
            <RefreshCw size={14} />
            <span>刷新</span>
          </button>
          <button disabled={loading || Boolean(action)} onClick={() => void startRun()} title="启动项目运行" type="button">
            <PlayCircle size={14} />
            <span>{action === "start" ? "启动中" : "运行"}</span>
          </button>
        </nav>
      </header>
      <div className="graph-instance-project-strip" aria-label="项目身份">
        <ProjectFact label="project_id" value={instance.graph_task_instance_id} />
        <ProjectFact label="root_session_id" value={instance.root_session_id || "未创建"} />
        <ProjectFact label="file_space_id" value={instance.file_space_id || "随项目创建"} />
        <ProjectFact label="artifact_index_id" value={instance.artifact_index_id || "随运行累积"} />
      </div>
      {error ? <p className="graph-repository-error">{error}</p> : null}
      <div className="graph-instance-workbench__grid">
        <GraphInstanceRunMonitor
          artifactCount={artifacts?.artifacts?.length ?? 0}
          fileCount={fileTree?.total_entries ?? 0}
          instance={instance}
          loading={loading}
          monitor={monitor}
          nodeSessionCount={nodeSessions.length}
          onRefresh={() => void refreshAll()}
          onStartRun={() => void startRun()}
          runningAction={action}
        />
        <main className="graph-instance-workbench__main">
          <nav className="graph-instance-workbench__switch" aria-label="项目资源面板">
            <button
              className={centerPanel === "files" ? "graph-instance-workbench__switch-item graph-instance-workbench__switch-item--active" : "graph-instance-workbench__switch-item"}
              onClick={() => setCenterPanel("files")}
              type="button"
            >
              <FolderTree size={14} />
              <span>文件空间</span>
            </button>
            <button
              className={centerPanel === "artifacts" ? "graph-instance-workbench__switch-item graph-instance-workbench__switch-item--active" : "graph-instance-workbench__switch-item"}
              onClick={() => setCenterPanel("artifacts")}
              type="button"
            >
              <Archive size={14} />
              <span>产物</span>
            </button>
          </nav>
          {centerPanel === "files" ? (
            <GraphInstanceFileManager fileTree={fileTree} loading={loading} />
          ) : (
            <GraphInstanceArtifactManager
              artifacts={artifacts}
              loading={loading}
              profileInput={{
                graphId: instance.graph_id,
                metadata: {
                  ...(graphMetadata ?? {}),
                  ...(instance.metadata ?? {}),
                },
                title: graphTitle || instance.title,
              }}
            />
          )}
        </main>
        <GraphInstanceNodeSessions
          humanControls={monitor?.human_controls ?? null}
          instance={instance}
          nodeSessions={nodeSessions}
          onOpenSession={(session) => {
            openSessionProjection({
              session_id: session.id,
              scope: session.scope,
              title: session.title || "节点会话",
              subtitle: instance.title ? `${instance.title} / ${session.id}` : session.id,
              source: "graph-node",
            });
          }}
        />
      </div>
      {extensions.length ? (
        <div className="graph-repository-extension-strip" aria-label="项目监控插件">
          {extensions.map((extension) => (
            <span key={extension.extension_id}>{extension.displayName}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ProjectFact({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <span>{label}</span>
      <strong>{value}</strong>
    </p>
  );
}
