"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  FolderTree,
  MessageSquare,
  RefreshCw,
  Route,
  ShieldCheck,
} from "lucide-react";

import {
  getWritingGraphInstanceDesk,
  listGraphTaskInstances,
  readGraphTaskInstanceFile,
  submitWritingGraphChapterAction,
  writeGraphTaskInstanceFile,
  type GraphTaskInstanceArtifacts,
  type GraphTaskInstanceSummary,
  type HumanEdgeControlView,
  type SessionSummary,
  type WritingChapterAction,
  type WritingGraphInstanceDesk,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

import { WritingChapterDesk } from "./WritingChapterDesk";

type FileEditorMode = "edit" | "preview";
type AssetTab = "library" | "artifacts";
type ProjectSurface = "writing" | "assets" | "review" | "runtime";

type WritingFileNode = {
  children: WritingFileNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

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

const DEFAULT_WRITING_GRAPH_ID = "graph.writing.modular_novel.master";
const DEFAULT_INSTANCE_ID = "project.creation.writing.honghuang";

const PROJECT_SURFACES: Array<{
  id: ProjectSurface;
  label: string;
  detail: string;
  icon: typeof BookOpen;
}> = [
  { id: "writing", label: "正文生产", detail: "章节阅读、编辑、提交", icon: BookOpen },
  { id: "assets", label: "项目资产", detail: "设定、文件、产物", icon: FolderTree },
  { id: "review", label: "审核队列", detail: "人工裁决与记录", icon: ShieldCheck },
  { id: "runtime", label: "图引擎", detail: "运行、节点、会话", icon: Route },
];

export function WritingProjectShellPage() {
  const { openSessionProjection } = useAppStore();
  const [instanceId, setInstanceId] = useState("");
  const [instances, setInstances] = useState<GraphTaskInstanceSummary[]>([]);
  const [desk, setDesk] = useState<WritingGraphInstanceDesk | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [activeSurface, setActiveSurface] = useState<ProjectSurface>("writing");
  const [fileSearch, setFileSearch] = useState("");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [assetTab, setAssetTab] = useState<AssetTab>("library");
  const [fileEditorMode, setFileEditorMode] = useState<FileEditorMode>("preview");
  const [fileContent, setFileContent] = useState("");
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [newFilePath, setNewFilePath] = useState("");
  const [newFileContent, setNewFileContent] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [focusMode, setFocusMode] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedSurface = params.get("surface");
    setInstanceId(String(params.get("instance_id") || params.get("instanceId") || DEFAULT_INSTANCE_ID).trim());
    if (isProjectSurface(requestedSurface)) setActiveSurface(requestedSurface);
  }, []);

  const loadDesk = useCallback(async (targetInstanceId = instanceId) => {
    const normalizedInstanceId = String(targetInstanceId || "").trim();
    if (!normalizedInstanceId) return;
    setLoading(true);
    setError("");
    try {
      const payload = await getWritingGraphInstanceDesk(normalizedInstanceId, 160, {
        includeRuntime: true,
        includeFileTree: true,
      });
      setDesk(payload);
      setInstanceId(payload.graph_task_instance_id || normalizedInstanceId);
      const currentPath = selectedFilePath.trim();
      const readerPath = String(payload.reader?.path || "").trim();
      const preferredPath = currentPath || selectInitialReadingPath(payload);

      if (!currentPath && preferredPath && preferredPath !== readerPath) {
        try {
          const preferredFile = await readGraphTaskInstanceFile(payload.graph_task_instance_id || normalizedInstanceId, preferredPath);
          setSelectedFilePath(preferredFile.path || preferredPath);
          setFileContent(stringifyContent(preferredFile.content));
        } catch {
          setSelectedFilePath(preferredPath);
          setFileContent(stringifyContent(payload.reader?.content));
        }
      } else {
        setSelectedFilePath((current) => current || preferredPath);
        setFileContent((current) => current || stringifyContent(payload.reader?.content));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "写作项目加载失败");
    } finally {
      setLoading(false);
    }
  }, [instanceId, selectedFilePath]);

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      try {
        const payload = await listGraphTaskInstances(DEFAULT_WRITING_GRAPH_ID);
        if (cancelled) return;
        setInstances(payload.instances ?? []);
        const preferred = instanceId || DEFAULT_INSTANCE_ID;
        const selected = payload.instances.find((item) => item.graph_task_instance_id === preferred)
          ?? payload.instances[0]
          ?? null;
        const selectedId = selected?.graph_task_instance_id || preferred;
        setInstanceId(selectedId);
        await loadDesk(selectedId);
      } catch {
        if (!cancelled) await loadDesk(instanceId || DEFAULT_INSTANCE_ID);
      }
    }
    if (instanceId) void loadInitial();
    return () => {
      cancelled = true;
    };
  }, [instanceId, loadDesk]);

  async function selectInstance(nextInstanceId: string) {
    const normalized = nextInstanceId.trim();
    if (!normalized || normalized === instanceId) return;
    setInstanceId(normalized);
    setDesk(null);
    setFileContent("");
    setSelectedFilePath("");
    setSelectedNodeId("");
    await loadDesk(normalized);
  }

  async function refresh() {
    await loadDesk(instanceId || DEFAULT_INSTANCE_ID);
  }

  async function loadFile(path: string) {
    const targetPath = path.trim();
    if (!instanceId || !targetPath) return;
    setAction("load-file");
    setError("");
    try {
      const result = await readGraphTaskInstanceFile(instanceId, targetPath);
      setSelectedFilePath(result.path || targetPath);
      setFileContent(stringifyContent(result.content));
      setFileEditorMode("preview");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "读取项目文件失败");
    } finally {
      setAction("");
    }
  }

  async function openProjectFile(path: string) {
    await loadFile(path);
    setActiveSurface("writing");
  }

  async function saveSelectedFile() {
    if (!instanceId || !selectedFilePath.trim()) return;
    setAction("save-file");
    setError("");
    try {
      await writeGraphTaskInstanceFile(instanceId, selectedFilePath, fileContent);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存文件失败");
    } finally {
      setAction("");
    }
  }

  async function writeNewFile() {
    const targetPath = newFilePath.trim();
    if (!instanceId || !targetPath) return;
    setAction("write-file");
    setError("");
    try {
      await writeGraphTaskInstanceFile(instanceId, targetPath, newFileContent);
      setSelectedFilePath(targetPath);
      setFileContent(newFileContent);
      setNewFileContent("");
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "写入正式库失败");
    } finally {
      setAction("");
    }
  }

  async function openChapterAction(chapterAction: WritingChapterAction) {
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
      await refresh();
      setActiveSurface("review");
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
      subtitle: desk?.instance?.title ? `${desk.instance.title} / ${session.id}` : session.id,
      source: "graph-node",
    });
  }

  const model = useMemo(() => buildWritingProjectModel({
    artifactSearch,
    fileSearch,
    selectedFilePath,
    selectedNodeId,
    writingDesk: desk,
  }), [artifactSearch, desk, fileSearch, selectedFilePath, selectedNodeId]);

  const selectedInstance = instances.find((item) => item.graph_task_instance_id === instanceId) ?? desk?.instance ?? null;
  const activeGraphRunId = text(selectedInstance?.active_graph_run_id) || text(desk?.graph_debug_ref?.active_graph_run_id);
  const pendingControls = (desk?.human_controls?.pending?.length ?? 0) + (desk?.human_controls?.available?.length ?? 0);
  const graphMonitorUrl = `/?view=graph-repository&graph_id=${encodeURIComponent(DEFAULT_WRITING_GRAPH_ID)}&instance_id=${encodeURIComponent(instanceId || DEFAULT_INSTANCE_ID)}&panel=writing&context=monitor`;
  const projectTitle = selectedInstance?.title || desk?.instance?.title || "洪荒时代";
  const shellClassName = [
    "writing-project-shell",
    activeSurface === "writing" ? "writing-project-shell--writing" : "",
    activeSurface === "writing" && focusMode ? "writing-project-shell--reader-focus" : "",
  ].filter(Boolean).join(" ");

  return (
    <main className={shellClassName}>
      <header className="writing-project-shell__topbar">
        <a href="/" className="writing-project-shell__back">
          <ArrowLeft size={15} />
          <span>主工作台</span>
        </a>
        <div className="writing-project-shell__title">
          <span>写作项目</span>
          <strong>{projectTitle}</strong>
          <small>{instanceId || DEFAULT_INSTANCE_ID}</small>
        </div>
        <nav className="writing-project-shell__actions" aria-label="写作项目操作">
          {instances.length > 1 ? (
            <select
              aria-label="切换写作项目"
              disabled={loading || Boolean(action)}
              onChange={(event) => void selectInstance(event.target.value)}
              value={instanceId}
            >
              {instances.map((item) => (
                <option key={item.graph_task_instance_id} value={item.graph_task_instance_id}>
                  {item.title || item.graph_task_instance_id}
                </option>
              ))}
            </select>
          ) : null}
          <button disabled={loading || Boolean(action)} onClick={() => void refresh()} type="button">
            <RefreshCw size={14} />
            <span>{loading ? "刷新中" : "刷新"}</span>
          </button>
          <a href={graphMonitorUrl}>
            <ExternalLink size={14} />
            <span>图监控</span>
          </a>
        </nav>
      </header>

      <section className="writing-project-shell__meta" aria-label="写作项目状态">
        <ProjectFact icon={<BookOpen size={14} />} label="章节" value={`${model.chapterFiles.length}`} />
        <ProjectFact icon={<Archive size={14} />} label="产物" value={`${desk?.summary?.artifact_count ?? model.artifacts.length}`} />
        <ProjectFact icon={<ShieldCheck size={14} />} label="待审" value={`${pendingControls}`} />
        <ProjectFact icon={<MessageSquare size={14} />} label="节点会话" value={`${desk?.summary?.node_session_count ?? model.nodeCards.length}`} />
        <ProjectFact icon={<Route size={14} />} label="运行" value={activeGraphRunId || "未启动"} />
      </section>

      <div className="writing-project-shell__body">
        <aside className="writing-project-shell__rail" aria-label="写作项目导航">
          <section className="writing-project-shell__identity">
            <span>当前项目</span>
            <strong>{projectTitle}</strong>
            <small>{statusLabel(selectedInstance?.status || "idle")}</small>
          </section>
          <nav className="writing-project-shell__nav" aria-label="项目层级">
            {PROJECT_SURFACES.map((surface) => {
              const Icon = surface.icon;
              return (
                <button
                  aria-pressed={activeSurface === surface.id}
                  className={activeSurface === surface.id ? "writing-project-shell__nav-item writing-project-shell__nav-item--active" : "writing-project-shell__nav-item"}
                  key={surface.id}
                  onClick={() => setActiveSurface(surface.id)}
                  type="button"
                >
                  <Icon size={16} />
                  <span>
                    <strong>{surface.label}</strong>
                    <small>{surface.detail}</small>
                  </span>
                </button>
              );
            })}
          </nav>
          <section className="writing-project-shell__engine-card" aria-label="图引擎状态">
            <header>
              <span>图引擎</span>
              <strong>{activeGraphRunId ? "已连接" : "未启动"}</strong>
            </header>
            <p>
              <span>graph_id</span>
              <strong>{selectedInstance?.graph_id || DEFAULT_WRITING_GRAPH_ID}</strong>
            </p>
            <p>
              <span>run_id</span>
              <strong>{activeGraphRunId || "-"}</strong>
            </p>
            <a href={graphMonitorUrl}>
              <ExternalLink size={13} />
              <span>打开图监控</span>
            </a>
          </section>
        </aside>

        <section className={`writing-project-shell__stage writing-project-shell__stage--${activeSurface}`} aria-label="写作项目工作区">
          {error ? <p className="writing-project-shell__error">{error}</p> : null}
          {!desk && loading ? <div className="writing-project-shell__loading">正在打开写作项目...</div> : null}
          {desk && activeSurface === "writing" ? (
            <WritingChapterDesk
              action={action}
              artifactSearch={artifactSearch}
              artifacts={model.artifacts}
              assetTab={assetTab}
              chapterActions={desk.chapter_actions ?? []}
              chapterFiles={model.chapterFiles}
              decisionHistory={model.decisionHistory}
              fileContent={fileContent}
              fileEditorMode={fileEditorMode}
              fileSearch={fileSearch}
              filteredArtifacts={model.filteredArtifacts}
              flatFiles={model.flatFiles}
              focusMode={focusMode}
              loadFile={loadFile}
              newFileContent={newFileContent}
              newFilePath={newFilePath}
              nextChapterFile={model.nextChapterFile}
              nodeCards={model.nodeCards}
              openChapterAction={openChapterAction}
              openSession={openSession}
              previousChapterFile={model.previousChapterFile}
              saveSelectedFile={saveSelectedFile}
              selectedFileName={model.selectedFileName}
              selectedFilePath={selectedFilePath}
              selectedHumanControl={model.selectedHumanControl}
              selectedNode={model.selectedNode}
              setArtifactSearch={setArtifactSearch}
              setAssetTab={setAssetTab}
              setFileContent={setFileContent}
              setFileEditorMode={setFileEditorMode}
              setFileSearch={setFileSearch}
              setFocusMode={setFocusMode}
              setNewFileContent={setNewFileContent}
              setNewFilePath={setNewFilePath}
              setSelectedNodeId={setSelectedNodeId}
              visibleChapterFiles={model.visibleChapterFiles}
              writeNewFile={writeNewFile}
            />
          ) : null}
          {desk && activeSurface === "assets" ? (
            <ProjectAssetsSurface
              artifactSearch={artifactSearch}
              categories={desk.writing_assets?.categories ?? []}
              filteredArtifacts={model.filteredArtifacts}
              flatFiles={model.flatFiles}
              onOpenFile={(path) => void openProjectFile(path)}
              setArtifactSearch={setArtifactSearch}
            />
          ) : null}
          {desk && activeSurface === "review" ? (
            <ProjectReviewSurface
              action={action}
              chapterActions={desk.chapter_actions ?? []}
              controls={[
                ...(desk.human_controls?.available ?? []),
                ...(desk.human_controls?.pending ?? []),
              ]}
              decisionHistory={model.decisionHistory}
              onOpenChapterAction={openChapterAction}
              selectedHumanControl={model.selectedHumanControl}
            />
          ) : null}
          {desk && activeSurface === "runtime" ? (
            <ProjectRuntimeSurface
              graphDebugRef={desk.graph_debug_ref ?? {}}
              graphMonitorUrl={graphMonitorUrl}
              nodeCards={model.nodeCards}
              onOpenSession={openSession}
              selectedNode={model.selectedNode}
              setSelectedNodeId={setSelectedNodeId}
            />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function ProjectFact({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <p>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </p>
  );
}

function ProjectAssetsSurface({
  artifactSearch,
  categories,
  filteredArtifacts,
  flatFiles,
  onOpenFile,
  setArtifactSearch,
}: {
  artifactSearch: string;
  categories: NonNullable<WritingGraphInstanceDesk["writing_assets"]>["categories"];
  filteredArtifacts: Array<Record<string, unknown>>;
  flatFiles: WritingFileNode[];
  onOpenFile: (path: string) => void;
  setArtifactSearch: (value: string) => void;
}) {
  return (
    <div className="writing-project-surface writing-project-assets">
      <header className="writing-project-surface__head">
        <div>
          <span>项目资产</span>
          <strong>设定库、正式文件与节点产物</strong>
        </div>
        <FolderTree size={17} />
      </header>
      <div className="writing-project-assets__grid">
        <section className="writing-project-panel writing-project-assets__categories">
          <header>
            <span>设定库</span>
            <strong>{categories.length} 类</strong>
          </header>
          <div>
            {categories.map((category) => (
              <article key={category.category_id || category.title}>
                <strong>{category.title || category.category_id}</strong>
                <span>{category.items.length} 项</span>
                {category.items.slice(0, 5).map((item, index) => (
                  <small key={`${category.category_id}:${index}`}>{text(item.title) || text(item.name) || text(item.path) || `资产 ${index + 1}`}</small>
                ))}
              </article>
            ))}
            {!categories.length ? <div className="boundary-empty">暂无项目设定资产。</div> : null}
          </div>
        </section>

        <section className="writing-project-panel writing-project-assets__files">
          <header>
            <span>正式库文件</span>
            <strong>{flatFiles.length} 个</strong>
          </header>
          <div>
            {flatFiles.slice(0, 120).map((file) => (
              <button key={file.path} onClick={() => onOpenFile(file.path)} type="button">
                <FileText size={14} />
                <span>
                  <strong>{file.name || basename(file.path)}</strong>
                  <small>{file.path}</small>
                </span>
              </button>
            ))}
            {!flatFiles.length ? <div className="boundary-empty">正式库还没有可查看文件。</div> : null}
          </div>
        </section>

        <section className="writing-project-panel writing-project-assets__artifacts">
          <header>
            <span>节点产物</span>
            <strong>{filteredArtifacts.length} 个</strong>
          </header>
          <label className="writing-project-search">
            <FolderTree size={14} />
            <input onChange={(event) => setArtifactSearch(event.target.value)} placeholder="搜索产物" value={artifactSearch} />
          </label>
          <div>
            {filteredArtifacts.slice(0, 100).map((artifact) => {
              const path = text(artifact.path);
              return (
                <button disabled={!path} key={text(artifact.artifact_id) || path} onClick={() => path && onOpenFile(path)} type="button">
                  <Archive size={14} />
                  <span>
                    <strong>{text(artifact.name) || basename(path) || "未命名产物"}</strong>
                    <small>{path || "没有文件路径"}</small>
                  </span>
                </button>
              );
            })}
            {!filteredArtifacts.length ? <div className="boundary-empty">没有匹配的节点产物。</div> : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function ProjectReviewSurface({
  action,
  chapterActions,
  controls,
  decisionHistory,
  onOpenChapterAction,
  selectedHumanControl,
}: {
  action: string;
  chapterActions: WritingChapterAction[];
  controls: HumanEdgeControlView[];
  decisionHistory: Array<Record<string, unknown>>;
  selectedHumanControl: HumanEdgeControlView | null;
  onOpenChapterAction: (action: WritingChapterAction) => void;
}) {
  const visibleActions: WritingChapterAction[] = chapterActions.length
    ? chapterActions
    : (["pass", "revise", "replace"] as const).map((decision) => ({
        action: decision === "pass" ? "approve" : decision === "revise" ? "request_revision" : "replace_with_user_text",
        control_id: "",
        decision,
        edge_id: "",
        enabled: false,
        label: writingDecisionLabel(decision),
      }));

  return (
    <div className="writing-project-surface writing-project-review">
      <header className="writing-project-surface__head">
        <div>
          <span>审核队列</span>
          <strong>{selectedHumanControl ? controlTitle(selectedHumanControl) : "当前无可处理边"}</strong>
        </div>
        <ShieldCheck size={17} />
      </header>
      <div className="writing-project-review__grid">
        <section className="writing-project-panel writing-project-review__actions">
          <header>
            <span>章节裁决</span>
            <strong>{visibleActions.filter((item) => item.enabled).length} 个可用动作</strong>
          </header>
          <div>
            {visibleActions.map((chapterAction) => (
              <button
                disabled={!chapterAction.enabled || !chapterAction.control_id || action === "human-edge-decision"}
                key={`${chapterAction.control_id || "fallback"}:${chapterAction.decision}`}
                onClick={() => onOpenChapterAction(chapterAction)}
                type="button"
              >
                <CheckCircle2 size={15} />
                <span>
                  <strong>{chapterAction.label || writingDecisionLabel(chapterAction.decision)}</strong>
                  <small>{chapterAction.description || chapterAction.reason || "等待章节审核输入"}</small>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="writing-project-panel writing-project-review__controls">
          <header>
            <span>待处理边</span>
            <strong>{controls.length} 条</strong>
          </header>
          <div>
            {controls.map((control) => (
              <article key={control.control_id}>
                <strong>{controlTitle(control)}</strong>
                <span>{control.reason || control.edge_id}</span>
                <small>{control.allowed_decisions.map(writingDecisionLabel).join(" / ")}</small>
              </article>
            ))}
            {!controls.length ? <div className="boundary-empty">当前没有等待人工裁决的边。</div> : null}
          </div>
        </section>

        <section className="writing-project-panel writing-project-review__history">
          <header>
            <span>审核记录</span>
            <strong>{decisionHistory.length} 条</strong>
          </header>
          <div>
            {decisionHistory.slice(0, 80).map((item) => (
              <article key={text(item.decision_id) || `${text(item.edge_id)}:${text(item.created_at)}`}>
                <strong>{text(item.decision) || "decision"} · {text(item.edge_id) || "edge"}</strong>
                <span>{text(item.status) || "submitted"}</span>
                <small>{timestampLabel(item.updated_at ?? item.created_at)}</small>
              </article>
            ))}
            {!decisionHistory.length ? <div className="boundary-empty">章节审核记录会显示在这里。</div> : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function ProjectRuntimeSurface({
  graphDebugRef,
  graphMonitorUrl,
  nodeCards,
  onOpenSession,
  selectedNode,
  setSelectedNodeId,
}: {
  graphDebugRef: Record<string, unknown>;
  graphMonitorUrl: string;
  nodeCards: NodeRuntimeCard[];
  selectedNode: NodeRuntimeCard | null;
  onOpenSession: (session: SessionSummary | null) => Promise<void>;
  setSelectedNodeId: (nodeId: string) => void;
}) {
  const debugEntries = Object.entries(graphDebugRef).slice(0, 10);
  return (
    <div className="writing-project-surface writing-project-runtime">
      <header className="writing-project-surface__head">
        <div>
          <span>图引擎</span>
          <strong>{selectedNode?.title || "节点运行视图"}</strong>
        </div>
        <Route size={17} />
      </header>
      <div className="writing-project-runtime__grid">
        <section className="writing-project-panel writing-project-runtime__nodes">
          <header>
            <span>节点会话</span>
            <strong>{nodeCards.length} 个</strong>
          </header>
          <div>
            {nodeCards.map((node) => (
              <button
                className={selectedNode?.nodeId === node.nodeId ? "writing-project-runtime__node writing-project-runtime__node--active" : "writing-project-runtime__node"}
                key={node.nodeId}
                onClick={() => setSelectedNodeId(node.nodeId)}
                type="button"
              >
                <Clock3 size={14} />
                <span>
                  <strong>{node.title}</strong>
                  <small>{statusLabel(node.status)} · {node.session ? `${node.session.message_count ?? 0} 条消息` : "暂无会话"}</small>
                </span>
              </button>
            ))}
            {!nodeCards.length ? <div className="boundary-empty">暂无节点会话。</div> : null}
          </div>
        </section>

        <section className="writing-project-panel writing-project-runtime__detail">
          <header>
            <span>节点详情</span>
            <strong>{selectedNode?.nodeId || "-"}</strong>
          </header>
          <div>
            <RuntimeField label="状态" value={statusLabel(selectedNode?.status || "idle")} />
            <RuntimeField label="scope" value={selectedNode?.scopeLabel || "-"} />
            <RuntimeField label="task_run" value={selectedNode?.detail || "-"} />
            <RuntimeField label="updated" value={timestampLabel(selectedNode?.updatedAt)} />
            <button disabled={!selectedNode?.session} onClick={() => void onOpenSession(selectedNode?.session ?? null)} type="button">
              <MessageSquare size={14} />
              <span>{selectedNode?.session ? "打开节点会话" : "暂无节点会话"}</span>
            </button>
            <a href={graphMonitorUrl}>
              <ExternalLink size={14} />
              <span>打开完整图监控</span>
            </a>
          </div>
        </section>

        <section className="writing-project-panel writing-project-runtime__debug">
          <header>
            <span>运行引用</span>
            <strong>{debugEntries.length} 项</strong>
          </header>
          <div>
            {debugEntries.map(([key, value]) => (
              <RuntimeField key={key} label={key} value={text(value) || stringifyContent(value)} />
            ))}
            {!debugEntries.length ? <div className="boundary-empty">暂无运行引用。</div> : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function RuntimeField({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <span>{label}</span>
      <strong>{value}</strong>
    </p>
  );
}

function buildWritingProjectModel({
  artifactSearch,
  fileSearch,
  selectedFilePath,
  selectedNodeId,
  writingDesk,
}: {
  artifactSearch: string;
  fileSearch: string;
  selectedFilePath: string;
  selectedNodeId: string;
  writingDesk: WritingGraphInstanceDesk | null;
}) {
  const chapterFiles = selectPrimaryChapterFiles(writingDesk?.chapter_index ?? []);
  const flatFiles = uniqueFiles(flattenWritingFileTree(writingDesk?.file_tree?.tree ?? null).filter((file) => file.path));
  const sourceFiles = chapterFiles.length ? chapterFiles : flatFiles;
  const normalizedFileSearch = fileSearch.trim().toLowerCase();
  const visibleChapterFiles = normalizedFileSearch
    ? sourceFiles.filter((file) => `${file.name} ${file.path}`.toLowerCase().includes(normalizedFileSearch))
    : sourceFiles;
  const selectedIndex = sourceFiles.findIndex((file) => file.path === selectedFilePath);
  const artifactItems = writingDesk?.artifacts?.artifacts ?? [];
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
  const nodeCards = (writingDesk?.node_sessions ?? []).map((session, index) => sessionToNodeCard(session, index));
  const selectedNode = nodeCards.find((node) => node.nodeId === selectedNodeId) ?? nodeCards[0] ?? null;
  const selectedFileName = sourceFiles.find((file) => file.path === selectedFilePath)?.name || basename(selectedFilePath);
  return {
    artifacts: artifactItems as NonNullable<GraphTaskInstanceArtifacts["artifacts"]>,
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
  const chapterNumber = Number(chapter.chapter_number);
  const chapterLabel = Number.isFinite(chapterNumber) && chapterNumber > 0 ? `第 ${chapterNumber} 章` : "";
  const title = text(chapter.title) || text(chapter.chapter_id) || basename(path);
  const displayTitle = chapterLabel && title && normalizeTitle(title) !== normalizeTitle(chapterLabel)
    ? `${chapterLabel} · ${title}`
    : chapterLabel || title;
  return {
    children: [],
    kind: "file",
    name: displayTitle,
    path,
  };
}

function selectPrimaryChapterFiles(chapterIndex: WritingGraphInstanceDesk["chapter_index"]) {
  const groups = new Map<string, Array<Record<string, unknown>>>();
  for (const chapter of chapterIndex) {
    const record = chapter as Record<string, unknown>;
    const path = text(record.path);
    if (!path) continue;
    const chapterNumber = Number(record.chapter_number);
    const key = Number.isFinite(chapterNumber) && chapterNumber > 0
      ? `chapter:${chapterNumber}`
      : text(record.chapter_id) || path;
    groups.set(key, [...(groups.get(key) ?? []), record]);
  }

  return Array.from(groups.values())
    .map((items) => {
      const selected = [...items].sort((left, right) => {
        const leftScore = chapterCandidateScore(text(left.path));
        const rightScore = chapterCandidateScore(text(right.path));
        if (rightScore !== leftScore) return rightScore - leftScore;
        return timestampValue(right.updated_at) - timestampValue(left.updated_at);
      })[0];
      return writingChapterToFileNode(selected);
    })
    .sort((left, right) => chapterNumberFromPathOrName(left) - chapterNumberFromPathOrName(right));
}

function selectInitialReadingPath(writingDesk: WritingGraphInstanceDesk | null) {
  const primaryChapterPath = selectPrimaryChapterFiles(writingDesk?.chapter_index ?? [])[0]?.path?.trim() || "";
  if (primaryChapterPath) return primaryChapterPath;
  return String(writingDesk?.reader?.path || "").trim();
}

function chapterCandidateScore(path: string) {
  const normalized = path.toLowerCase().replace(/\\/g, "/");
  if (/\/chapter_\d+\/draft_round_\d+\.md$/.test(normalized)) return 100;
  if (/draft_round_\d+\.md$/.test(normalized)) return 90;
  if (/chapter_commit_round_\d+\.md$/.test(normalized)) return 70;
  if (/draft_batch_assemble_round_\d+\.md$/.test(normalized)) return 55;
  if (/review_round_\d+\.md$/.test(normalized)) return 35;
  if (/outline_round_\d+\.md$/.test(normalized)) return 25;
  if (/(unit_route|progress_route)_round_\d+\.md$/.test(normalized)) return 10;
  return 20;
}

function chapterNumberFromPathOrName(file: WritingFileNode) {
  const fromName = file.name.match(/第\s*(\d+)\s*章/);
  if (fromName) return Number(fromName[1]);
  const fromPath = file.path.match(/chapter[_-](\d+)/i);
  if (fromPath) return Number(fromPath[1]);
  return Number.MAX_SAFE_INTEGER;
}

function normalizeTitle(value: string) {
  return value.replace(/\s+/g, "");
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

function uniqueFiles(files: WritingFileNode[]) {
  const seen = new Set<string>();
  return files.filter((file) => {
    const path = file.path.trim();
    if (!path || seen.has(path)) return false;
    seen.add(path);
    return true;
  });
}

function sessionToNodeCard(session: SessionSummary, index: number): NodeRuntimeCard {
  const nodeId = text(session.active_task?.task_id) || session.id || `session-${index}`;
  return {
    artifactCount: 0,
    detail: text(session.active_task?.task_run_id) || text(session.scope?.project_id),
    nodeId,
    scopeLabel: text(session.scope?.workspace_view) || "graph_task",
    session,
    status: text(session.active_task?.status) || text(session.conversation_state) || "idle",
    title: text(session.title) || nodeId,
    updatedAt: session.updated_at,
  };
}

function isProjectSurface(value: unknown): value is ProjectSurface {
  return value === "writing" || value === "assets" || value === "review" || value === "runtime";
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

function stringifyContent(value: unknown) {
  if (typeof value === "string") return value;
  if (value == null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function basename(path: string) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function controlTitle(control: HumanEdgeControlView) {
  return `${control.source_node_id || "上游"} -> ${control.target_node_id || "下游"}`;
}

function writingDecisionLabel(decision: string) {
  if (decision === "pass") return "通过本章";
  if (decision === "revise") return "退稿给写手";
  if (decision === "replace") return "采用改写稿";
  return decision;
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
  const status = text(value).toLowerCase() || "idle";
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
