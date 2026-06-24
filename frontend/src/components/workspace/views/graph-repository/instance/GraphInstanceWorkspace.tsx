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
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

import type { GraphInstanceWorkspaceExtension } from "../templates/graphTemplateTypes";
import { GraphInstanceArtifactManager } from "./GraphInstanceArtifactManager";
import { GraphInstanceFileManager } from "./GraphInstanceFileManager";
import { GraphInstanceNodeSessions } from "./GraphInstanceNodeSessions";
import { GraphInstanceRunMonitor } from "./GraphInstanceRunMonitor";

type InstanceCenterPanel = "files" | "artifacts";

export function GraphInstanceWorkspace({
  extensions,
  instance,
}: {
  instance: GraphTaskInstanceSummary | null;
  extensions: GraphInstanceWorkspaceExtension[];
}) {
  const { openSessionProjection } = useAppStore();
  const [fileTree, setFileTree] = useState<GraphTaskInstanceFileTree | null>(null);
  const [artifacts, setArtifacts] = useState<GraphTaskInstanceArtifacts | null>(null);
  const [nodeSessions, setNodeSessions] = useState<SessionSummary[]>([]);
  const [monitor, setMonitor] = useState<GraphTaskInstanceMonitor | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [centerPanel, setCenterPanel] = useState<InstanceCenterPanel>("files");
  const [error, setError] = useState("");

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
      setError(exc instanceof Error ? exc.message : "实例工作台加载失败");
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
      setError(exc instanceof Error ? exc.message : "启动实例运行失败");
    } finally {
      setAction("");
    }
  }

  if (!instance) {
    return (
      <section className="graph-instance-workbench">
        <div className="graph-repository-empty">选择一个实例后会显示通用文件空间、产物、节点会话和运行状态。</div>
      </section>
    );
  }

  return (
    <section className="graph-instance-workbench" aria-label="实例工作台">
      <header className="graph-instance-workbench__header">
        <div>
          <span>实例工作台</span>
          <strong>{instance.title || instance.graph_task_instance_id}</strong>
        </div>
        <nav aria-label="实例工作台操作">
          <button disabled={loading || Boolean(action)} onClick={() => void loadWorkspace()} title="刷新实例工作台" type="button">
            <RefreshCw size={14} />
            <span>刷新</span>
          </button>
          <button disabled={loading || Boolean(action)} onClick={() => void startRun()} title="启动实例运行" type="button">
            <PlayCircle size={14} />
            <span>{action === "start" ? "启动中" : "运行"}</span>
          </button>
        </nav>
      </header>
      {error ? <p className="graph-repository-error">{error}</p> : null}
      <div className="graph-instance-workbench__grid">
        <GraphInstanceRunMonitor
          artifactCount={artifacts?.artifacts?.length ?? 0}
          fileCount={fileTree?.total_entries ?? 0}
          instance={instance}
          loading={loading}
          monitor={monitor}
          nodeSessionCount={nodeSessions.length}
          onRefresh={() => void loadWorkspace()}
          onStartRun={() => void startRun()}
          runningAction={action}
        />
        <main className="graph-instance-workbench__main">
          <nav className="graph-instance-workbench__switch" aria-label="实例资源面板">
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
            <GraphInstanceArtifactManager artifacts={artifacts} loading={loading} />
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
        <div className="graph-repository-extension-strip" aria-label="实例工作台插件">
          {extensions.map((extension) => (
            <span key={extension.extension_id}>{extension.displayName}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
