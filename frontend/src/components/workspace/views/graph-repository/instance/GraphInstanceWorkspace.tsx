"use client";

import { useCallback, useEffect, useState } from "react";
import { Archive, BookOpen, ExternalLink, FolderTree, PlayCircle, RefreshCw } from "lucide-react";
import {
  getGraphTaskInstanceFileTree,
  getGraphTaskInstanceMonitor,
  getWritingGraphInstanceDesk,
  listGraphTaskInstanceArtifacts,
  listGraphTaskInstanceNodeSessions,
  readGraphTaskInstanceFile,
  startGraphTaskInstanceRun,
  submitWritingGraphChapterAction,
  writeGraphTaskInstanceFile,
  type GraphTaskInstanceArtifacts,
  type GraphTaskInstanceFileTree,
  type GraphTaskInstanceMonitor,
  type GraphTaskInstanceSummary,
  type HumanEdgeControlView,
  type SessionSummary,
  type TaskGraphRecord,
  type WritingChapterAction,
  type WritingGraphInstanceDesk,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { WritingChapterDesk } from "@/components/workspace/views/task-graph-foreground/WritingChapterDesk";

import type { GraphInstanceWorkspaceExtension } from "../templates/graphTemplateTypes";
import { GraphInstanceArtifactManager } from "./GraphInstanceArtifactManager";
import { GraphInstanceFileManager } from "./GraphInstanceFileManager";
import { GraphInstanceNodeSessions } from "./GraphInstanceNodeSessions";
import { GraphInstanceRunMonitor } from "./GraphInstanceRunMonitor";

type InstanceCenterPanel = "writing" | "files" | "artifacts";
type FileEditorMode = "edit" | "preview";
type AssetTab = "library" | "artifacts";

type WritingFileNode = {
  children: WritingFileNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

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
  const [writingDesk, setWritingDesk] = useState<WritingGraphInstanceDesk | null>(null);
  const [writingDeskLoading, setWritingDeskLoading] = useState(false);
  const [fileSearch, setFileSearch] = useState("");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [assetTab, setAssetTab] = useState<AssetTab>("library");
  const [fileEditorMode, setFileEditorMode] = useState<FileEditorMode>("preview");
  const [fileContent, setFileContent] = useState("");
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [newFilePath, setNewFilePath] = useState("");
  const [newFileContent, setNewFileContent] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [focusMode, setFocusMode] = useState(false);
  const writingDeskAvailable = isWritingDeskAvailable({
    activeGraph,
    extensions,
    graphMetadata,
    graphTitle,
    instance,
  });

  useEffect(() => {
    setCenterPanel(writingDeskAvailable && initialPanel === "files" ? "writing" : initialPanel);
  }, [initialPanel, writingDeskAvailable]);

  useEffect(() => {
    if (!writingDeskAvailable && centerPanel === "writing") setCenterPanel("files");
  }, [centerPanel, writingDeskAvailable]);

  useEffect(() => {
    setWritingDesk(null);
    setFileSearch("");
    setArtifactSearch("");
    setFileContent("");
    setSelectedFilePath("");
    setNewFilePath("");
    setNewFileContent("");
    setSelectedNodeId("");
  }, [instance?.graph_task_instance_id]);

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
    setWritingDeskLoading(writingDeskAvailable);
    setError("");
    try {
      const [tree, artifactPayload, sessionsPayload, monitorPayload, writingDeskPayload] = await Promise.all([
        getGraphTaskInstanceFileTree(instanceId, { maxDepth: 4, maxEntries: 160 }).catch(() => null),
        listGraphTaskInstanceArtifacts(instanceId).catch(() => null),
        listGraphTaskInstanceNodeSessions(instanceId).catch(() => ({ sessions: [] })),
        getGraphTaskInstanceMonitor(instanceId, 80).catch(() => null),
        writingDeskAvailable
          ? getWritingGraphInstanceDesk(instanceId, 80, { includeRuntime: true, includeFileTree: true }).catch(() => null)
          : Promise.resolve(null),
      ]);
      setFileTree(tree);
      setArtifacts(artifactPayload);
      setNodeSessions(sessionsPayload.sessions ?? []);
      setMonitor(monitorPayload);
      setWritingDesk(writingDeskPayload);
      if (writingDeskPayload?.reader) {
        setSelectedFilePath((current) => current || String(writingDeskPayload.reader.path || "").trim());
        setFileContent((current) => current || String(writingDeskPayload.reader.content || ""));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "项目监控加载失败");
    } finally {
      setLoading(false);
      setWritingDeskLoading(false);
    }
  }, [instance, writingDeskAvailable]);

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

  async function loadWritingFile(path: string) {
    const instanceId = instance?.graph_task_instance_id;
    const targetPath = String(path || "").trim();
    if (!instanceId || !targetPath) return;
    setAction("load-file");
    setError("");
    try {
      const result = await readGraphTaskInstanceFile(instanceId, targetPath);
      setSelectedFilePath(result.path || targetPath);
      setFileContent(result.content || "");
      setFileEditorMode("preview");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "读取写作文件失败");
    } finally {
      setAction("");
    }
  }

  async function saveSelectedFile() {
    const instanceId = instance?.graph_task_instance_id;
    if (!instanceId || !selectedFilePath.trim()) return;
    setAction("save-file");
    setError("");
    try {
      await writeGraphTaskInstanceFile(instanceId, selectedFilePath, fileContent);
      await loadWorkspace();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存写作文件失败");
    } finally {
      setAction("");
    }
  }

  async function writeNewFile() {
    const instanceId = instance?.graph_task_instance_id;
    const targetPath = newFilePath.trim();
    if (!instanceId || !targetPath) return;
    setAction("write-file");
    setError("");
    try {
      await writeGraphTaskInstanceFile(instanceId, targetPath, newFileContent);
      setNewFileContent("");
      setSelectedFilePath(targetPath);
      setFileContent(newFileContent);
      await loadWorkspace();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "写入正式库失败");
    } finally {
      setAction("");
    }
  }

  async function openChapterAction(chapterAction: WritingChapterAction) {
    const instanceId = instance?.graph_task_instance_id;
    if (!instanceId || !chapterAction.enabled || !chapterAction.control_id) return;
    const content = chapterAction.decision === "replace"
      ? window.prompt("输入要替换为正式稿的内容", fileContent)
      : "";
    if (chapterAction.decision === "replace" && content === null) return;
    const instruction = chapterAction.decision === "revise"
      ? window.prompt("返修说明", chapterAction.description || "")
      : "";
    if (chapterAction.decision === "revise" && instruction === null) return;
    setAction("human-edge-decision");
    setError("");
    try {
      await submitWritingGraphChapterAction(instanceId, {
        action: chapterAction.action,
        content: content || undefined,
        control_id: chapterAction.control_id,
        instruction: instruction || undefined,
        target_path: selectedFilePath || undefined,
        apply_now: true,
      });
      await loadWorkspace();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "提交章节审核动作失败");
    } finally {
      setAction("");
    }
  }

  async function openSession(session: SessionSummary | null) {
    if (!session?.id) return;
    openSessionProjection({
      session_id: session.id,
      scope: session.scope,
      title: session.title || "节点会话",
      subtitle: instance?.title ? `${instance.title} / ${session.id}` : session.id,
      source: "graph-node",
    });
  }

  const writingDeskModel = buildWritingDeskModel({
    artifactSearch,
    artifacts,
    fileSearch,
    fileTree,
    nodeSessions,
    selectedFilePath,
    selectedNodeId,
    writingDesk,
  });

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
          {writingDeskAvailable ? (
            <a
              className="graph-instance-workbench__header-link"
              href={`/writing-project?instance_id=${encodeURIComponent(instance.graph_task_instance_id)}`}
              title="打开写作项目"
            >
              <ExternalLink size={14} />
              <span>写作项目</span>
            </a>
          ) : null}
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
            {writingDeskAvailable ? (
              <button
                className={centerPanel === "writing" ? "graph-instance-workbench__switch-item graph-instance-workbench__switch-item--active" : "graph-instance-workbench__switch-item"}
                onClick={() => setCenterPanel("writing")}
                type="button"
              >
                <BookOpen size={14} />
                <span>写作台</span>
              </button>
            ) : null}
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
          {centerPanel === "writing" && writingDeskAvailable ? (
            <WritingChapterDesk
              action={action}
              artifactSearch={artifactSearch}
              artifacts={writingDeskModel.artifacts}
              assetTab={assetTab}
              chapterActions={writingDesk?.chapter_actions ?? []}
              chapterFiles={writingDeskModel.chapterFiles}
              decisionHistory={writingDeskModel.decisionHistory}
              fileContent={fileContent}
              fileEditorMode={fileEditorMode}
              fileSearch={fileSearch}
              filteredArtifacts={writingDeskModel.filteredArtifacts}
              flatFiles={writingDeskModel.flatFiles}
              focusMode={focusMode}
              loadFile={loadWritingFile}
              newFileContent={newFileContent}
              newFilePath={newFilePath}
              nextChapterFile={writingDeskModel.nextChapterFile}
              nodeCards={writingDeskModel.nodeCards}
              openChapterAction={openChapterAction}
              openSession={openSession}
              previousChapterFile={writingDeskModel.previousChapterFile}
              saveSelectedFile={saveSelectedFile}
              selectedFileName={writingDeskModel.selectedFileName}
              selectedFilePath={selectedFilePath}
              selectedHumanControl={writingDeskModel.selectedHumanControl}
              selectedNode={writingDeskModel.selectedNode}
              setArtifactSearch={setArtifactSearch}
              setAssetTab={setAssetTab}
              setFileContent={setFileContent}
              setFileEditorMode={setFileEditorMode}
              setFileSearch={setFileSearch}
              setFocusMode={setFocusMode}
              setNewFileContent={setNewFileContent}
              setNewFilePath={setNewFilePath}
              setSelectedNodeId={setSelectedNodeId}
              visibleChapterFiles={writingDeskModel.visibleChapterFiles}
              writeNewFile={writeNewFile}
            />
          ) : centerPanel === "files" ? (
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

function isWritingDeskAvailable({
  activeGraph,
  extensions,
  graphMetadata,
  graphTitle,
  instance,
}: {
  activeGraph?: TaskGraphRecord | null;
  extensions: GraphInstanceWorkspaceExtension[];
  graphMetadata?: Record<string, unknown>;
  graphTitle?: string;
  instance: GraphTaskInstanceSummary | null;
}) {
  if (extensions.some((extension) => extension.componentKey === "writing_chapter_desk")) return true;
  const values = [
    instance?.graph_id,
    activeGraph?.graph_id,
    activeGraph?.domain_id,
    graphTitle,
    graphMetadata?.domain_id,
    graphMetadata?.category,
    instance?.metadata?.graph_title,
  ].map((value) => String(value ?? "").toLowerCase());
  return values.some((value) => value.includes("writing") || value.includes("novel") || value.includes("写作"));
}

function buildWritingDeskModel({
  artifactSearch,
  artifacts,
  fileSearch,
  fileTree,
  nodeSessions,
  selectedFilePath,
  selectedNodeId,
  writingDesk,
}: {
  artifactSearch: string;
  artifacts: GraphTaskInstanceArtifacts | null;
  fileSearch: string;
  fileTree: GraphTaskInstanceFileTree | null;
  nodeSessions: SessionSummary[];
  selectedFilePath: string;
  selectedNodeId: string;
  writingDesk: WritingGraphInstanceDesk | null;
}) {
  const chapterFiles = (writingDesk?.chapter_index ?? [])
    .map((chapter) => writingChapterToFileNode(chapter))
    .filter((file) => file.path);
  const flatFiles = flattenWritingFileTree((writingDesk?.file_tree ?? fileTree)?.tree ?? null).filter((file) => file.path);
  const sourceFiles = chapterFiles.length ? chapterFiles : flatFiles;
  const normalizedFileSearch = fileSearch.trim().toLowerCase();
  const visibleChapterFiles = normalizedFileSearch
    ? sourceFiles.filter((file) => `${file.name} ${file.path}`.toLowerCase().includes(normalizedFileSearch))
    : sourceFiles;
  const selectedIndex = sourceFiles.findIndex((file) => file.path === selectedFilePath);
  const artifactItems = writingDesk?.artifacts?.artifacts ?? artifacts?.artifacts ?? [];
  const normalizedArtifactSearch = artifactSearch.trim().toLowerCase();
  const filteredArtifacts = normalizedArtifactSearch
    ? artifactItems.filter((artifact) => JSON.stringify(artifact).toLowerCase().includes(normalizedArtifactSearch))
    : artifactItems;
  const controls = [
    ...(writingDesk?.human_controls?.available ?? []),
    ...(writingDesk?.human_controls?.pending ?? []),
  ];
  const preferredControlId = writingDesk?.chapter_actions.find((chapterAction) => chapterAction.enabled && chapterAction.control_id)?.control_id || "";
  const selectedHumanControl = controls.find((control) => control.control_id === preferredControlId) ?? controls[0] ?? null;
  const sessions = writingDesk?.node_sessions?.length ? writingDesk.node_sessions : nodeSessions;
  const nodeCards = sessions.map((session, index) => sessionToNodeCard(session, index));
  const selectedNode = nodeCards.find((node) => node.nodeId === selectedNodeId) ?? nodeCards[0] ?? null;
  const selectedFileName = sourceFiles.find((file) => file.path === selectedFilePath)?.name || basename(selectedFilePath);
  return {
    artifacts: artifactItems,
    chapterFiles,
    decisionHistory: writingDesk?.human_controls?.history ?? [],
    filteredArtifacts,
    flatFiles,
    nextChapterFile: selectedIndex >= 0 ? sourceFiles[selectedIndex + 1] ?? null : null,
    nodeCards,
    previousChapterFile: selectedIndex > 0 ? sourceFiles[selectedIndex - 1] ?? null : null,
    selectedFileName,
    selectedHumanControl,
    selectedNode,
    visibleChapterFiles,
  };
}

function writingChapterToFileNode(chapter: Record<string, unknown>): WritingFileNode {
  const path = text(chapter.path);
  return {
    children: [],
    kind: "file",
    name: text(chapter.title) || text(chapter.chapter_id) || basename(path),
    path,
  };
}

function flattenWritingFileTree(tree: Record<string, unknown> | null): WritingFileNode[] {
  if (!tree) return [];
  const children = Array.isArray(tree.children)
    ? tree.children
    : Array.isArray(tree.entries)
      ? tree.entries
      : [];
  const kind = text(tree.kind) || text(tree.type);
  const path = text(tree.path);
  const name = text(tree.name) || basename(path);
  const current = path && kind !== "directory" && kind !== "folder"
    ? [{ children: [], kind: "file", name: name || path, path }]
    : [];
  return [
    ...current,
    ...children.flatMap((child) => flattenWritingFileTree(asRecord(child))),
  ];
}

function sessionToNodeCard(session: SessionSummary, index: number) {
  const nodeId = text(session.active_task?.task_id) || session.id || `session-${index}`;
  return {
    artifactCount: 0,
    detail: text(session.active_task?.task_run_id) || text(session.scope?.project_id),
    nodeId,
    scopeLabel: text(session.scope?.workspace_view) || "graph_task",
    session,
    status: text(session.active_task?.status) || text(session.conversation_state) || "idle",
    title: session.title || nodeId,
    updatedAt: session.updated_at,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function text(value: unknown) {
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return [
      record.title,
      record.name,
      record.label,
      record.display_name,
      record.node_id,
      record.task_id,
      record.id,
    ].map((item) => String(item ?? "").trim()).find(Boolean) || "";
  }
  return String(value ?? "").trim();
}

function basename(path: string) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}
