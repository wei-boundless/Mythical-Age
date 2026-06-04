"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  FolderOpen,
  LibraryBig,
  MessageSquare,
  Play,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Workflow,
} from "lucide-react";

import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import {
  getTaskSystemEnvironmentProjects,
  getTaskSystemOverview,
  getTaskSystemProject,
  getTaskSystemProjectLifecycleActions,
  getTaskSystemProjectRepositories,
  getTaskSystemProjectRepositoryFile,
  getTaskSystemProjectRepositoryTree,
  listTaskEnvironmentSessions,
  previewTaskSystemProjectLifecycle,
  resolveTaskEnvironmentSession,
  startTaskGraphHarnessRun,
  startTaskSystemProjectLifecycleRun,
  type ProjectFilePayload,
  type ProjectFileTreePayload,
  type ProjectInstance,
  type ProjectLifecycleActionSpec,
  type ProjectLifecycleActionsPayload,
  type ProjectLibraryPayload,
  type ProjectLibraryRepository,
  type ProjectLifecyclePreviewPayload,
  type ProjectRepositoriesPayload,
  type ProjectTreeNode,
  type SessionScope,
  type SessionSummary,
  type TaskGraphRecord,
  type TaskSystemOverview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { SessionPoolKey } from "@/lib/store/types";
import {
  buildCenterWorkspaceTaskGraphInitialInputs,
  centerWorkspaceTaskEnvironmentId,
  listCenterWorkspaceTaskGraphs,
  resolveCenterWorkspaceSelectedGraphId,
} from "@/components/workspace/views/center/centerWorkspaceHelpers";
import { TaskGraphRunControlPanel } from "@/components/workspace/views/task-system/TaskGraphRunControlPanel";

const WRITING_ENVIRONMENT_ID = "env.creation.writing";

type SelectedFile = {
  repository_id: string;
  path: string;
  name: string;
};

type DeskSection = "overview" | "library" | "workflow" | "graph";
type WritingFlowKind = "design" | "framework" | "draft" | "review";

const WRITING_FLOW_LABELS: Record<WritingFlowKind, { title: string; description: string; keywords: string[] }> = {
  design: { title: "设计体系", description: "整理项目定位、世界观、角色和核心卖点。", keywords: ["design", "world", "character", "init"] },
  framework: { title: "写作框架", description: "拆分卷章结构、节奏和阶段目标。", keywords: ["outline", "framework", "plan"] },
  draft: { title: "正文创作", description: "按既定框架推进正文生成。", keywords: ["chapter", "draft", "novel"] },
  review: { title: "审核返修", description: "审查产物质量，形成返修或提交结论。", keywords: ["review", "repair", "commit"] },
};

function projectTitle(project: ProjectInstance | null) {
  const title = project?.title?.trim();
  if (!title) return "未选择作品";
  if (/^honghuang era$/i.test(title)) return "洪荒时代";
  return title;
}

function compactId(value: string | undefined) {
  if (!value) return "";
  return value
    .replace(/^project\.creation\.writing\./, "")
    .replace(/^repo\.writing\./, "")
    .replace(/[._-]+/g, " ")
    .trim();
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function textValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function sessionTaskGraphBinding(session: SessionSummary | null | undefined) {
  const binding = recordValue(session?.task_binding);
  const graphRunId = textValue(binding.graph_run_id);
  const graphHarnessConfigId = textValue(binding.graph_harness_config_id);
  if (!graphRunId || !graphHarnessConfigId) return null;
  return {
    task_run_id: textValue(binding.task_run_id),
    graph_run_id: graphRunId,
    graph_harness_config_id: graphHarnessConfigId,
    graph_id: textValue(binding.graph_id),
    session_scope: recordValue(binding.session_scope),
  };
}

function repositorySignature(repository: ProjectLibraryRepository) {
  return [
    repository.project_role,
    repository.repository_kind,
    repository.repository_id,
    repository.title,
    ...(repository.selected_roles ?? []),
  ].join(" ").toLowerCase();
}

function repositoryDisplayName(repository: ProjectLibraryRepository) {
  const signature = repositorySignature(repository);
  if (signature.includes("official_work") || signature.includes("official")) return "正式作品";
  if (signature.includes("draft_workspace") || signature.includes("draft")) return "草稿与改写";
  if (signature.includes("artifact_repository") || signature.includes("artifact") || signature.includes("output")) return "创作产出";
  if (signature.includes("memory_repository") || signature.includes("memory")) return "作品记忆";
  if (signature.includes("asset")) return "设定素材";
  if (signature.includes("review")) return "评审记录";
  return repository.title && !/[._]|repository|workspace/i.test(repository.title)
    ? repository.title
    : "作品资料";
}

function repositoryPurpose(repository: ProjectLibraryRepository) {
  const signature = repositorySignature(repository);
  if (signature.includes("official_work") || signature.includes("official")) return "沉淀最终可发布文本";
  if (signature.includes("draft_workspace") || signature.includes("draft")) return "收纳草稿、改写稿和临时片段";
  if (signature.includes("artifact_repository") || signature.includes("artifact") || signature.includes("output")) return "归档每次创作生成的结果";
  if (signature.includes("memory_repository") || signature.includes("memory")) return "沉淀角色、设定、风格和长期约束";
  if (signature.includes("asset")) return "管理世界观、人物、小纲和参考资料";
  if (signature.includes("review")) return "归档审核意见和返修记录";
  return "用于本作品创作的资料";
}

function collectFiles(node: ProjectTreeNode | null): ProjectTreeNode[] {
  if (!node) return [];
  const result: ProjectTreeNode[] = [];
  const visit = (current: ProjectTreeNode) => {
    if (current.kind === "file") result.push(current);
    current.children.forEach(visit);
  };
  node.children.forEach(visit);
  return result;
}

function fileTypeLabel(path: string) {
  const lower = path.toLowerCase();
  if (lower.endsWith(".md")) return "文稿";
  if (lower.endsWith(".json")) return "结构资料";
  if (lower.endsWith(".txt")) return "文本";
  return "文件";
}

function firstPathSegment(path: string) {
  return path.split("/").filter(Boolean)[0] || "根目录";
}

function formatProjectState(project: ProjectInstance | null) {
  const state = String(project?.lifecycle_state || "").toLowerCase();
  if (state === "active") return "进行中";
  if (state === "archived") return "已归档";
  if (state === "draft") return "筹备中";
  return "待开始";
}

function creativeSessionTaskTitle(session: SessionSummary) {
  const task = session.active_task?.available ? session.active_task : null;
  const title = String(task?.title || "").trim();
  if (title && !/^(session|taskrun|task|turn|turnrun|grun|coordrun|rtobj|rtpacket)[:-]/i.test(title)) {
    return title;
  }
  return session.title || "未命名沟通记录";
}

function creativeSessionTaskMeta(session: SessionSummary) {
  const task = session.active_task?.available ? session.active_task : null;
  if (!task) {
    return `${session.message_count} 条`;
  }
  const status = String(task.status || task.lifecycle || "").trim();
  const label = task.action_required
    ? "需要处理"
    : status === "running" || task.bucket === "running"
      ? "运行中"
      : status === "completed" || task.terminal
        ? "已完成"
        : status || "任务";
  return `${label} · ${task.task_run_count > 1 ? `${task.task_run_count} 个任务记录` : "当前任务"}`;
}

function getRepositoryFiles(trees: Record<string, ProjectFileTreePayload>, repositoryId: string) {
  return collectFiles(trees[repositoryId]?.tree ?? null);
}

function creativeSessionScope(projectId: string): SessionScope {
  return {
    workspace_view: "task_environment",
    task_environment_id: WRITING_ENVIRONMENT_ID,
    project_id: projectId,
  };
}

function creativeSessionPoolKey(projectId: string): SessionPoolKey {
  return `task_environment:${WRITING_ENVIRONMENT_ID}:${projectId}` as SessionPoolKey;
}

function graphMatchesFlow(graph: TaskGraphRecord, flow: WritingFlowKind) {
  const haystack = [
    graph.graph_id,
    graph.title,
    JSON.stringify(graph.metadata ?? {}),
  ].join(" ").toLowerCase();
  return WRITING_FLOW_LABELS[flow].keywords.some((keyword) => haystack.includes(keyword));
}

function chooseFlowGraph(graphs: TaskGraphRecord[], flow: WritingFlowKind, selectedGraphId: string) {
  const selected = graphs.find((graph) => graph.graph_id === selectedGraphId);
  if (selected && graphMatchesFlow(selected, flow)) return selected;
  return graphs.find((graph) => graphMatchesFlow(graph, flow)) ?? selected ?? graphs[0] ?? null;
}

function graphCustomerTitle(graph: TaskGraphRecord | null | undefined) {
  if (!graph) return "自动匹配创作流程";
  return String(graph.title || "")
    .replace(/任务图/g, "流程")
    .replace(/模块化/g, "")
    .replace(/graph/gi, "流程")
    .trim() || "创作流程";
}

function groupCustomerTitle(group: string) {
  const normalized = group.replace(/^graphrun\./, "").replace(/^taskrun\./, "").trim();
  if (!normalized) return "创作批次";
  const timestamp = normalized.match(/\d{10,}/)?.[0];
  if (timestamp) return `创作批次 ${timestamp.slice(-6)}`;
  const cleaned = normalized
    .replace(/\bgrun\b/gi, "")
    .replace(/\bgraph\b/gi, "")
    .replace(/\bwriting\b/gi, "")
    .replace(/\bmodular\b/gi, "")
    .replace(/\bnovel\b/gi, "")
    .replace(/\bmaster\b/gi, "综合创作")
    .replace(/\bdesign\b/gi, "设计")
    .replace(/\binit\b/gi, "初始化")
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || "创作批次";
}

function CreativeProjectRail({
  projects,
  scopedSessions,
  selectedProjectId,
  currentSessionId,
  loading,
  onRefresh,
  onRefreshSessions,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onSelectProject,
}: {
  projects: ProjectInstance[];
  scopedSessions: SessionSummary[];
  selectedProjectId: string;
  currentSessionId: string | null;
  loading: boolean;
  onRefresh: () => void;
  onRefreshSessions: () => void;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onSelectProject: (projectId: string) => void;
}) {
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const visibleSessions = [...scopedSessions].sort((a, b) => b.updated_at - a.updated_at).slice(0, 8);

  return (
    <aside className="workbench-resource-panel creative-project-rail" aria-label="写作项目">
      <header className="workbench-panel-head">
        <div>
          <strong>写作环境</strong>
          <span>作品、资料、写作流程</span>
        </div>
      </header>

      <div className="creative-env-line">
        <span>工作区</span>
        <strong>长篇写作</strong>
        <small>管理作品资料，提交写作需求，跟进创作产出</small>
      </div>

      <nav className="creative-rail-body" aria-label="作品列表">
        <div className="creative-rail-heading">
          <button onClick={onRefresh} type="button">
            <RefreshCw size={14} />
            <span>{loading ? "正在更新" : "刷新作品"}</span>
          </button>
          <em>{projects.length} 个</em>
        </div>
        <div className="creative-project-list">
          {projects.length ? projects.map((project) => (
            <button
              aria-current={selectedProjectId === project.project_id ? "page" : undefined}
              className={selectedProjectId === project.project_id ? "creative-project-row creative-project-row--active" : "creative-project-row"}
              key={project.project_id}
              onClick={() => onSelectProject(project.project_id)}
              type="button"
            >
              <LibraryBig size={15} />
              <span>
                <strong>{projectTitle(project)}</strong>
                <small>{project.project_kind === "long_novel" ? "长篇小说" : "创作项目"}</small>
              </span>
              <em>{formatProjectState(project)}</em>
            </button>
          )) : (
            <div className="creative-inline-state">还没有作品。</div>
          )}
        </div>
      </nav>

      <section className="creative-session-drawer" aria-label="作品沟通记录">
        <button className="creative-session-toggle" onClick={() => setSessionsOpen((value) => !value)} type="button">
          {sessionsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>沟通记录</span>
          <MessageSquare size={14} onClick={(event) => {
            event.stopPropagation();
            onCreateSession();
          }} />
        </button>
        {sessionsOpen ? (
          <>
          <div className="creative-session-toolbar">
            <button onClick={onRefreshSessions} type="button"><RefreshCw size={12} />刷新</button>
            <button onClick={onCreateSession} type="button"><MessageSquare size={12} />新建</button>
          </div>
          <div className="creative-session-list">
            {visibleSessions.length ? visibleSessions.map((session) => (
              <div
                className={session.id === currentSessionId ? "creative-session-row creative-session-row--active" : "creative-session-row"}
                key={session.id}
              >
                <button onClick={() => onSelectSession(session.id)} type="button">
                  <MessageSquare size={13} />
                  <span>{creativeSessionTaskTitle(session)}</span>
                  <small>{creativeSessionTaskMeta(session)}</small>
                </button>
                <button
                  aria-label={`删除 ${session.title || "沟通记录"}`}
                  className="creative-session-delete"
                  onClick={() => onDeleteSession(session.id)}
                  type="button"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            )) : <div className="creative-inline-state">暂无沟通记录。</div>}
          </div>
          </>
        ) : null}
      </section>
    </aside>
  );
}

function CreativeGraphOperationsPanel({
  flow,
  onSelectFlow,
  onSelectGraph,
  onStartGraph,
  onTaskMessageChange,
  selectedGraph,
  selectedProject,
  startError,
  starting,
  taskGraphs,
  taskMessage,
}: {
  flow: WritingFlowKind;
  onSelectFlow: (flow: WritingFlowKind) => void;
  onSelectGraph: (graphId: string) => void;
  onStartGraph: () => void;
  onTaskMessageChange: (value: string) => void;
  selectedGraph: TaskGraphRecord | null;
  selectedProject: ProjectInstance | null;
  startError: string;
  starting: boolean;
  taskGraphs: TaskGraphRecord[];
  taskMessage: string;
}) {
  const {
    openTaskGraphWorkspace,
  } = useAppStore();

  return (
    <section className="creative-graph-ops" aria-label="写作图任务运行与监控">
      <section className="creative-work-strip creative-graph-ops__launch" aria-label="图任务启动">
        <div className="creative-strip-head">
          <strong>图任务运行</strong>
          <span>{selectedGraph ? graphCustomerTitle(selectedGraph) : "当前环境没有可用流程"}</span>
        </div>
        <div className="creative-flow-grid">
          {(Object.keys(WRITING_FLOW_LABELS) as WritingFlowKind[]).map((key) => (
            <button
              className={flow === key ? "creative-flow-option creative-flow-option--active" : "creative-flow-option"}
              key={key}
              onClick={() => onSelectFlow(key)}
              type="button"
            >
              <strong>{WRITING_FLOW_LABELS[key].title}</strong>
              <span>{WRITING_FLOW_LABELS[key].description}</span>
            </button>
          ))}
        </div>
        <label className="creative-graph-select">
          <span>当前任务图</span>
          <select disabled={!taskGraphs.length || starting} onChange={(event) => onSelectGraph(event.target.value)} value={selectedGraph?.graph_id || ""}>
            {taskGraphs.map((graph) => (
              <option key={graph.graph_id} value={graph.graph_id}>
                {graphCustomerTitle(graph)}
              </option>
            ))}
          </select>
        </label>
        <textarea
          className="creative-task-composer creative-task-composer--compact"
          onChange={(event) => onTaskMessageChange(event.target.value)}
          placeholder="输入本次要启动或绑定的写作任务。"
          value={taskMessage}
        />
        <div className="creative-workflow-actions">
          <button disabled={starting || !selectedProject || !taskMessage.trim() || !selectedGraph} onClick={onStartGraph} type="button">
            <Play size={15} />
            <span>{starting ? "正在启动" : "启动/绑定运行"}</span>
          </button>
          <button
            disabled={!selectedGraph}
            onClick={() => {
              if (!selectedGraph) return;
              openTaskGraphWorkspace({ graph_id: selectedGraph.graph_id, task_environment_id: WRITING_ENVIRONMENT_ID, mode: "editor" });
            }}
            type="button"
          >
            <ExternalLink size={15} />
            <span>任务系统编辑</span>
          </button>
        </div>
        {startError ? <div className="creative-error-line">{startError}</div> : null}
      </section>

      <TaskGraphRunControlPanel
        className="creative-work-strip creative-graph-ops__monitor"
        graphId={selectedGraph?.graph_id}
        taskEnvironmentId={WRITING_ENVIRONMENT_ID}
        title="运行监控"
      />
    </section>
  );
}

function CreativeCommandDesk({
  selectedProject,
  project,
  repositories,
  trees,
  selectedFile,
  scopedSessions,
  currentSessionId,
  selectedGraphId,
  taskGraphs,
  overview,
  flow,
  taskMessage,
  starting,
  startError,
  activeSection,
  loading,
  error,
  onSelectSection,
  onSelectFile,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onSelectGraph,
  onSelectFlow,
  onTaskMessageChange,
  onStartGraph,
}: {
  selectedProject: ProjectInstance | null;
  project: ProjectLibraryPayload | null;
  repositories: ProjectRepositoriesPayload | null;
  trees: Record<string, ProjectFileTreePayload>;
  selectedFile: SelectedFile | null;
  scopedSessions: SessionSummary[];
  currentSessionId: string | null;
  selectedGraphId: string;
  taskGraphs: TaskGraphRecord[];
  overview: TaskSystemOverview | null;
  flow: WritingFlowKind;
  taskMessage: string;
  starting: boolean;
  startError: string;
  activeSection: DeskSection;
  loading: boolean;
  error: string;
  onSelectSection: (section: DeskSection) => void;
  onSelectFile: (file: SelectedFile) => void;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onSelectGraph: (graphId: string) => void;
  onSelectFlow: (flow: WritingFlowKind) => void;
  onTaskMessageChange: (value: string) => void;
  onStartGraph: () => void;
}) {
  const repositoryList = repositories?.repositories ?? [];
  const artifactRepository = repositoryList.find((repository) => repository.project_role === "artifact_repository") ?? null;
  const artifactFiles = artifactRepository ? getRepositoryFiles(trees, artifactRepository.repository_id) : [];
  const artifactGroups = Array.from(new Set(artifactFiles.map((file) => firstPathSegment(file.path)))).slice(0, 6);
  const selectedGraph = taskGraphs.find((graph) => graph.graph_id === selectedGraphId) ?? taskGraphs[0] ?? null;

  return (
    <section className="workbench-view-host creative-command-desk" aria-label="写作项目工作台">
      <header className="creative-desk-top">
        <div>
          <span>当前作品</span>
          <strong>{projectTitle(selectedProject)}</strong>
          <small>{selectedProject ? "长篇小说创作" : "请选择作品"}</small>
        </div>
        <div className="creative-desk-status">
          <span>{formatProjectState(selectedProject)}</span>
          <span>{repositoryList.length} 类资料</span>
          <span>{artifactFiles.length} 份产出</span>
        </div>
      </header>

      <div className="creative-desk-tabs" role="tablist" aria-label="工作台区域">
        <button aria-selected={activeSection === "overview"} onClick={() => onSelectSection("overview")} role="tab" type="button">
          <BookOpen size={14} />
          <span>作品总览</span>
        </button>
        <button aria-selected={activeSection === "library"} onClick={() => onSelectSection("library")} role="tab" type="button">
          <FolderOpen size={14} />
          <span>资料库</span>
        </button>
        <button aria-selected={activeSection === "workflow"} onClick={() => onSelectSection("workflow")} role="tab" type="button">
          <Workflow size={14} />
          <span>开始创作</span>
        </button>
        <button aria-selected={activeSection === "graph"} onClick={() => onSelectSection("graph")} role="tab" type="button">
          <Workflow size={14} />
          <span>任务图</span>
        </button>
      </div>

      {error ? <div className="creative-error-line">{error}</div> : null}

      <div className="creative-desk-body">
        {activeSection === "overview" ? (
          <div className="creative-overview-grid">
            <section className="creative-work-strip" aria-label="作品资料状态">
              <div className="creative-strip-head">
                <strong>作品资料</strong>
                <span>{loading ? "正在整理" : repositoryList.length ? "可用于创作" : "等待整理"}</span>
              </div>
              <div className="creative-resource-table">
                {repositoryList.length ? repositoryList.map((repository) => {
                  const tree = trees[repository.repository_id];
                  return (
                    <button
                      className="creative-resource-row"
                      key={repository.repository_id}
                      onClick={() => {
                        const firstFile = getRepositoryFiles(trees, repository.repository_id)[0];
                        if (firstFile) onSelectFile({ repository_id: repository.repository_id, path: firstFile.path, name: firstFile.name });
                      }}
                      type="button"
                    >
                      <FolderOpen size={15} />
                      <span>
                        <strong>{repositoryDisplayName(repository)}</strong>
                        <small>{repositoryPurpose(repository)}</small>
                      </span>
                      <em>{tree ? `${tree.total_entries} 项` : "整理中"}</em>
                    </button>
                  );
                }) : <div className="creative-inline-state">作品资料正在准备。</div>}
              </div>
            </section>

            <section className="creative-work-strip" aria-label="创作产出概览">
              <div className="creative-strip-head">
                <strong>创作产出</strong>
                <span>{artifactGroups.length ? "按创作批次整理" : "暂无产出"}</span>
              </div>
              <div className="creative-run-lanes">
                {artifactGroups.length ? artifactGroups.map((group) => {
                  const count = artifactFiles.filter((file) => firstPathSegment(file.path) === group).length;
                  return (
                    <button
                      className="creative-run-lane"
                      key={group}
                      onClick={() => {
                        const firstFile = artifactFiles.find((file) => firstPathSegment(file.path) === group);
                        if (artifactRepository && firstFile) {
                          onSelectFile({ repository_id: artifactRepository.repository_id, path: firstFile.path, name: firstFile.name });
                        }
                      }}
                      type="button"
                    >
                  <span>{groupCustomerTitle(group)}</span>
                      <em>{count} 文件</em>
                    </button>
                  );
                }) : <div className="creative-inline-state">提交写作需求后，产出会在这里归档。</div>}
              </div>
            </section>

            <section className="creative-work-strip" aria-label="下一步操作">
              <div className="creative-strip-head">
                <strong>下一步</strong>
                <span>选择下一步工作</span>
              </div>
              <div className="creative-next-actions">
                <button onClick={() => onSelectSection("library")} type="button">
                  <FolderOpen size={15} />
                  <span>查看作品资料</span>
                  <small>查看正式稿、草稿、作品记忆和创作产出</small>
                </button>
                <button onClick={() => onSelectSection("workflow")} type="button">
                  <Workflow size={15} />
                  <span>提交写作需求</span>
                  <small>输入目标，选择流程，启动或绑定图运行</small>
                </button>
                <button onClick={() => onSelectSection("graph")} type="button">
                  <Workflow size={15} />
                  <span>查看图运行</span>
                  <small>启动、暂停、续跑并监控当前写作图任务</small>
                </button>
              </div>
            </section>
          </div>
        ) : null}

        {activeSection === "library" ? (
          <section className="creative-library-browser" aria-label="作品资料浏览">
            <div className="creative-strip-head">
              <strong>作品资料</strong>
              <span>选择资料后在右侧查看内容</span>
            </div>
            <div className="creative-library-columns">
              {repositoryList.length ? repositoryList.map((repository) => {
                const files = getRepositoryFiles(trees, repository.repository_id).slice(0, 80);
                return (
                  <section className="creative-repository-column" key={repository.repository_id}>
                    <header>
                      <span>{repositoryDisplayName(repository)}</span>
                      <em>{files.length} 文件</em>
                    </header>
                    <div>
                      {files.length ? files.map((item) => (
                        <button
                          className={selectedFile?.repository_id === repository.repository_id && selectedFile.path === item.path ? "creative-library-file creative-library-file--active" : "creative-library-file"}
                          key={`${repository.repository_id}:${item.path}`}
                          onClick={() => onSelectFile({ repository_id: repository.repository_id, path: item.path, name: item.name })}
                          title={item.path}
                          type="button"
                        >
                          <FileText size={13} />
                          <span>{item.name}</span>
                          <em>{fileTypeLabel(item.path)}</em>
                        </button>
                      )) : <div className="creative-inline-state">暂无文件。</div>}
                    </div>
                  </section>
                );
              }) : <div className="creative-inline-state">作品资料正在准备。</div>}
            </div>
          </section>
        ) : null}

        {activeSection === "workflow" ? (
          <section className="creative-workflow-stage creative-workflow-console" aria-label="创作控制台">
            <section className="creative-work-strip" aria-label="写作需求">
              <div className="creative-strip-head">
                <strong>写作需求</strong>
                <span>{currentSessionId ? "已关联本作品" : "开始后会生成沟通记录"}</span>
              </div>
              <textarea
                className="creative-task-composer"
                onChange={(event) => onTaskMessageChange(event.target.value)}
                placeholder="描述这次写作任务的目标、风格、约束和需要产出的内容。"
                value={taskMessage}
              />
              <div className="creative-workflow-actions">
                <button disabled={starting || !selectedProject || !taskMessage.trim() || !selectedGraph} onClick={onStartGraph} type="button">
                  <Play size={15} />
                  <span>{starting ? "正在启动" : "启动/绑定创作"}</span>
                </button>
                <button disabled={!selectedProject} onClick={onCreateSession} type="button">
                  <MessageSquare size={15} />
                  <span>新建沟通记录</span>
                </button>
              </div>
              {startError ? <div className="creative-error-line">{startError}</div> : null}
            </section>

            <section className="creative-work-strip" aria-label="创作流程">
              <div className="creative-strip-head">
                <strong>创作流程</strong>
                <span>{selectedGraph ? graphCustomerTitle(selectedGraph) : "暂无可用流程"}</span>
              </div>
              <div className="creative-flow-grid">
                {(Object.keys(WRITING_FLOW_LABELS) as WritingFlowKind[]).map((key) => (
                  <button
                    className={flow === key ? "creative-flow-option creative-flow-option--active" : "creative-flow-option"}
                    key={key}
                    onClick={() => onSelectFlow(key)}
                    type="button"
                  >
                    <strong>{WRITING_FLOW_LABELS[key].title}</strong>
                    <span>{WRITING_FLOW_LABELS[key].description}</span>
                  </button>
                ))}
              </div>
              <label className="creative-graph-select">
                <span>执行方式</span>
                <select disabled={!taskGraphs.length || starting} onChange={(event) => onSelectGraph(event.target.value)} value={selectedGraph?.graph_id || ""}>
                  {taskGraphs.map((graph) => (
                    <option key={graph.graph_id} value={graph.graph_id}>
                      {graphCustomerTitle(graph)}
                    </option>
                  ))}
                </select>
              </label>
            </section>

            <section className="creative-work-strip" aria-label="沟通记录">
              <div className="creative-strip-head">
                <strong>沟通记录</strong>
                <span>{scopedSessions.length ? `${scopedSessions.length} 条` : "当前作品暂无记录"}</span>
              </div>
              <div className="creative-session-board">
                {scopedSessions.length ? scopedSessions.slice(0, 6).map((session) => (
                  <div
                    className={session.id === currentSessionId ? "creative-session-board-row creative-session-board-row--active" : "creative-session-board-row"}
                    key={session.id}
                  >
                    <button onClick={() => onSelectSession(session.id)} type="button">
                      <MessageSquare size={14} />
                      <span>{creativeSessionTaskTitle(session)}</span>
                      <em>{creativeSessionTaskMeta(session)}</em>
                    </button>
                    <button
                      aria-label={`删除 ${session.title || "沟通记录"}`}
                      className="creative-session-delete"
                      onClick={() => onDeleteSession(session.id)}
                      type="button"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                )) : <div className="creative-inline-state">新建或开始创作后，沟通记录会归入当前作品。</div>}
              </div>
            </section>
          </section>
        ) : null}

        {activeSection === "graph" ? (
          <CreativeGraphOperationsPanel
            flow={flow}
            onSelectFlow={onSelectFlow}
            onSelectGraph={onSelectGraph}
            onStartGraph={onStartGraph}
            onTaskMessageChange={onTaskMessageChange}
            selectedGraph={selectedGraph}
            selectedProject={selectedProject}
            startError={startError}
            starting={starting}
            taskGraphs={taskGraphs}
            taskMessage={taskMessage}
          />
        ) : null}
      </div>

      <footer className="creative-desk-footer">
        <Search size={13} />
        <span>{activeSection === "graph" ? "任务图编辑在任务系统维护；这里仅负责启动、暂停、续跑和监控。" : selectedFile ? `正在查看：${selectedFile.name}` : "选择资料后，右侧会显示内容预览。"}</span>
      </footer>
    </section>
  );
}

function CreativeInspector({
  selectedProject,
  project,
  repositories,
  selectedFile,
  file,
  lifecycleActions,
  cleanupPreview,
  loading,
  error,
  onRefresh,
  onPreviewCleanup,
  onExecuteCleanup,
}: {
  selectedProject: ProjectInstance | null;
  project: ProjectLibraryPayload | null;
  repositories: ProjectRepositoriesPayload | null;
  selectedFile: SelectedFile | null;
  file: ProjectFilePayload | null;
  lifecycleActions: ProjectLifecycleActionsPayload | null;
  cleanupPreview: ProjectLifecyclePreviewPayload | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onPreviewCleanup: () => void;
  onExecuteCleanup: (actionId: string) => void;
}) {
  const cleanupAction = useMemo(
    () => (lifecycleActions?.actions ?? []).find((item: ProjectLifecycleActionSpec) => item.operation === "delete_task_records_by_selector") ?? null,
    [lifecycleActions]
  );
  const cleanupActionId = cleanupAction?.action_id ?? "";
  const repositoryList = repositories?.repositories ?? [];
  const fileContent = file?.content ?? "";

  return (
    <aside className="workbench-right-panel creative-inspector creative-file-reader" aria-label="文件阅览">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>{selectedFile?.name || "文件阅览"}</strong>
          <span>{selectedFile?.path || projectTitle(selectedProject)}</span>
        </div>
        <button className="workbench-icon-button" disabled={loading || !selectedProject} onClick={onRefresh} type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="creative-inspector-body">
        <section className="creative-inspector-section creative-inspector-section--preview" aria-label="文件正文">
          <header>
            <FileText size={15} />
            <strong>{selectedFile?.name || "选择文件"}</strong>
            {file ? <span>{fileContent.length.toLocaleString("zh-CN")} 字符</span> : null}
          </header>
          {file ? (
            <pre className="creative-file-preview">{fileContent || "文件为空。"}</pre>
          ) : (
            <div className="creative-inline-state">从资料库选择一份资料后在这里阅读全文。</div>
          )}
        </section>

        <section className="creative-inspector-section creative-inspector-section--meta" aria-label="作品信息">
          <header>
            <LibraryBig size={15} />
            <strong>作品信息</strong>
          </header>
          <dl className="creative-fact-list creative-fact-list--compact">
            <div><dt>作品</dt><dd>{project?.project ? projectTitle(project.project) : projectTitle(selectedProject)}</dd></div>
            <div><dt>类型</dt><dd>{selectedProject?.project_kind === "long_novel" ? "长篇小说" : "创作项目"}</dd></div>
            <div><dt>资料</dt><dd>{repositoryList.length ? `${repositoryList.length} 类可用` : "整理中"}</dd></div>
            <div><dt>状态</dt><dd>{formatProjectState(selectedProject)}</dd></div>
          </dl>
          {error ? <div className="creative-error-line">{error}</div> : null}
        </section>

        <section className="creative-inspector-section creative-inspector-section--meta" aria-label="可用资料">
          <header>
            <Settings2 size={15} />
            <strong>可用资料</strong>
          </header>
          <div className="creative-permission-list">
            {repositoryList.length ? repositoryList.map((repository) => (
              <div className="creative-permission-row" key={repository.repository_id}>
                <span>{repositoryDisplayName(repository)}</span>
                <em>{repository.writable === false ? "只读" : "可更新"}</em>
              </div>
            )) : <div className="creative-inline-state">资料正在准备。</div>}
          </div>
        </section>

        <section className="creative-inspector-section creative-inspector-section--meta" aria-label="作品整理">
          <header>
            <RefreshCw size={15} />
            <strong>作品整理</strong>
          </header>
          <div className="creative-maintenance-actions">
            <button disabled={loading || !selectedProject || !cleanupAction} onClick={onPreviewCleanup} type="button">
              <RefreshCw size={13} />
              <span>检查可整理内容</span>
            </button>
            <button
              disabled={loading || !selectedProject || !cleanupActionId || !cleanupPreview || Number(cleanupPreview.preview.counts?.task_count ?? 0) <= 0}
              onClick={() => onExecuteCleanup(cleanupActionId)}
              type="button"
            >
              <FileText size={13} />
              <span>整理旧记录</span>
            </button>
          </div>
          {cleanupPreview ? (
            <div className="creative-inline-state">
              可整理 {cleanupPreview.preview.counts?.task_count ?? 0} 条旧记录；作品资料和创作产出会保留。
            </div>
          ) : cleanupAction ? (
            <div className="creative-inline-state">整理前会先检查影响范围。</div>
          ) : null}
        </section>
      </div>
    </aside>
  );
}

export function CreativeEnvironmentView() {
  const {
    bindTaskGraphMonitorRun,
    currentSessionId,
    inspectorWidth,
    removeSession,
    selectSession,
    setInspectorWidth,
    setTaskGraphRunInteractionOpen,
  } = useAppStore();
  const [projects, setProjects] = useState<ProjectInstance[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [project, setProject] = useState<ProjectLibraryPayload | null>(null);
  const [repositories, setRepositories] = useState<ProjectRepositoriesPayload | null>(null);
  const [trees, setTrees] = useState<Record<string, ProjectFileTreePayload>>({});
  const [overview, setOverview] = useState<TaskSystemOverview | null>(null);
  const [scopedSessions, setScopedSessions] = useState<SessionSummary[]>([]);
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null);
  const [file, setFile] = useState<ProjectFilePayload | null>(null);
  const [lifecycleActions, setLifecycleActions] = useState<ProjectLifecycleActionsPayload | null>(null);
  const [cleanupPreview, setCleanupPreview] = useState<ProjectLifecyclePreviewPayload | null>(null);
  const [activeSection, setActiveSection] = useState<DeskSection>("overview");
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [flow, setFlow] = useState<WritingFlowKind>("design");
  const [taskMessage, setTaskMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const writingProjects = useMemo<ProjectInstance[]>(() => projects, [projects]);
  const selectedProject = useMemo(() => {
    return writingProjects.find((item) => item.project_id === selectedProjectId) ?? writingProjects[0] ?? null;
  }, [selectedProjectId, writingProjects]);
  const taskGraphs = useMemo(
    () => listCenterWorkspaceTaskGraphs(overview).filter((graph) => centerWorkspaceTaskEnvironmentId(graph) === WRITING_ENVIRONMENT_ID),
    [overview]
  );
  const scopedCurrentSessionId = scopedSessions.some((session) => session.id === currentSessionId) ? currentSessionId : null;

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const [payload, taskOverview] = await Promise.all([
        getTaskSystemEnvironmentProjects(WRITING_ENVIRONMENT_ID),
        getTaskSystemOverview(),
      ]);
      const nextProjects = payload.projects;
      setProjects(nextProjects);
      setOverview(taskOverview);
      setSelectedGraphId((current) => resolveCenterWorkspaceSelectedGraphId(taskOverview, current));
      const firstProjectId = nextProjects[0]?.project_id ?? "";
      setSelectedProjectId((current) => current || firstProjectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取写作项目。");
    } finally {
      setLoading(false);
    }
  }

  async function loadProject(projectId: string) {
    if (!projectId) return;
    setLoading(true);
    setError("");
    setSelectedFile(null);
    setFile(null);
    setCleanupPreview(null);
    try {
      const nextProject = await getTaskSystemProject(projectId);
      setProject(nextProject);
      const nextRepositories = await getTaskSystemProjectRepositories(projectId);
      setRepositories(nextRepositories);
      setLifecycleActions(await getTaskSystemProjectLifecycleActions(projectId));
      setLoading(false);
      const treeEntries = await Promise.all(
        nextRepositories.repositories
          .filter((repository) => repository.readable !== false)
          .map(async (repository) => {
            const tree = await getTaskSystemProjectRepositoryTree(projectId, repository.repository_id, {
              maxDepth: repository.project_role === "artifact_repository" ? 5 : 3,
              maxEntries: 900,
            }).catch(() => null);
            return [repository.repository_id, tree] as const;
          })
      );
      setTrees(Object.fromEntries(treeEntries.filter((entry): entry is readonly [string, ProjectFileTreePayload] => Boolean(entry[1]))));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法打开项目库。");
      setProject(null);
      setRepositories(null);
      setLifecycleActions(null);
      setTrees({});
    } finally {
      setLoading(false);
    }
  }

  async function loadScopedSessions(projectId: string) {
    if (!projectId) {
      setScopedSessions([]);
      return;
    }
    try {
      const response = await listTaskEnvironmentSessions(WRITING_ENVIRONMENT_ID, creativeSessionScope(projectId));
      setScopedSessions(response.sessions);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取项目会话。");
      setScopedSessions([]);
    }
  }

  async function createProjectSession() {
    if (!selectedProject) return "";
    setError("");
    try {
      const response = await resolveTaskEnvironmentSession(WRITING_ENVIRONMENT_ID, {
        workspace_view: "task_environment",
        project_id: selectedProject.project_id,
        intent: "new_conversation",
        title: `${selectedProject.title || "写作项目"} 会话`,
        create_if_missing: true,
      });
      if (!response.session) return "";
      setScopedSessions((current) => [response.session!, ...current.filter((session) => session.id !== response.session!.id)]);
      const scope = creativeSessionScope(selectedProject.project_id);
      await selectSession({
        sessionId: response.session.id,
        scope,
        poolKey: creativeSessionPoolKey(selectedProject.project_id),
      });
      return response.session.id;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法创建项目会话。");
      return "";
    }
  }

  async function selectProjectSession(sessionId: string) {
    if (!selectedProject) return;
    const scope = creativeSessionScope(selectedProject.project_id);
    await selectSession({
      sessionId,
      scope,
      poolKey: creativeSessionPoolKey(selectedProject.project_id),
    });
  }

  async function deleteProjectSession(sessionId: string) {
    if (!selectedProject) return;
    const scope = creativeSessionScope(selectedProject.project_id);
    setError("");
    try {
      await removeSession({
        sessionId,
        scope,
        poolKey: creativeSessionPoolKey(selectedProject.project_id),
      });
      await loadScopedSessions(selectedProject.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法删除沟通记录。");
    }
  }

  function selectFlow(nextFlow: WritingFlowKind) {
    setFlow(nextFlow);
    const graph = chooseFlowGraph(taskGraphs, nextFlow, selectedGraphId);
    if (graph) setSelectedGraphId(graph.graph_id);
  }

  async function startWritingGraph() {
    if (!selectedProject) {
      setStartError("请先选择写作项目。");
      return;
    }
    const graph = taskGraphs.find((item) => item.graph_id === selectedGraphId) ?? chooseFlowGraph(taskGraphs, flow, selectedGraphId);
    if (!graph) {
      setStartError("当前写作环境没有可用的创作流程。");
      return;
    }
    const message = taskMessage.trim();
    if (!message) {
      setStartError("请输入写作需求。");
      return;
    }
    setStarting(true);
    setStartError("");
    try {
      const resolved = await resolveTaskEnvironmentSession(WRITING_ENVIRONMENT_ID, {
        workspace_view: "task_environment",
        project_id: selectedProject.project_id,
        intent: "continue_conversation",
        preferred_session_id: currentSessionId && scopedSessions.some((session) => session.id === currentSessionId) ? currentSessionId : "",
        title: `${selectedProject.title || "写作项目"} 会话`,
        create_if_missing: true,
      });
      const sessionId = resolved.session?.id ?? "";
      if (!sessionId) return;
      const sessionScope = creativeSessionScope(selectedProject.project_id);
      await selectSession({
        sessionId,
        scope: sessionScope,
        poolKey: creativeSessionPoolKey(selectedProject.project_id),
      });
      const existingTaskBinding = sessionTaskGraphBinding(resolved.session);
      if (existingTaskBinding) {
        if (existingTaskBinding.graph_id && existingTaskBinding.graph_id !== graph.graph_id) {
          throw new Error(`当前作品会话已绑定其他创作流程：${existingTaskBinding.graph_id}`);
        }
        bindTaskGraphMonitorRun({
          task_run_id: existingTaskBinding.task_run_id || undefined,
          graph_run_id: existingTaskBinding.graph_run_id,
          graph_harness_config_id: existingTaskBinding.graph_harness_config_id,
          graph_id: graph.graph_id,
          session_id: sessionId,
          project_id: selectedProject.project_id,
          session_scope: {
            ...existingTaskBinding.session_scope,
            ...sessionScope,
          },
          title: graph.title || graph.graph_id,
        });
        setTaskGraphRunInteractionOpen(true);
        await loadScopedSessions(selectedProject.project_id);
        return;
      }
      const result = await startTaskGraphHarnessRun(graph.graph_id, {
        session_id: sessionId,
        session_scope: sessionScope,
        initial_inputs: {
          ...buildCenterWorkspaceTaskGraphInitialInputs(message, graph),
          project_id: selectedProject.project_id,
          session_scope: sessionScope,
          runtime_scope: sessionScope,
          writing_flow: flow,
        },
        include_trace: true,
        dispatch_ready: true,
        run_mode: "dispatch_only",
      });
      bindTaskGraphMonitorRun({
        task_run_id: result.task_run_id,
        graph_run_id: result.graph_run_id,
        graph_harness_config_id: result.graph_harness_config_id,
        graph_id: graph.graph_id,
        session_id: sessionId,
        project_id: selectedProject.project_id,
        session_scope: sessionScope,
        title: graph.title || graph.graph_id,
      });
      setTaskMessage("");
      setTaskGraphRunInteractionOpen(true);
      await loadScopedSessions(selectedProject.project_id);
    } catch (caught) {
      setStartError(caught instanceof Error ? caught.message : "创作流程启动失败。");
    } finally {
      setStarting(false);
    }
  }

  async function openFile(nextFile: SelectedFile) {
    if (!selectedProject) return;
    setSelectedFile(nextFile);
    setError("");
    try {
      setFile(await getTaskSystemProjectRepositoryFile(selectedProject.project_id, nextFile.repository_id, nextFile.path));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法打开文件。");
      setFile(null);
    }
  }

  async function previewCleanup() {
    if (!selectedProject) return;
    const actionId = (lifecycleActions?.actions ?? []).find((item) => item.operation === "delete_task_records_by_selector")?.action_id ?? "";
    if (!actionId) return;
    setLoading(true);
    setError("");
    try {
      setCleanupPreview(await previewTaskSystemProjectLifecycle(selectedProject.project_id, actionId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法生成维护预览。");
    } finally {
      setLoading(false);
    }
  }

  async function executeCleanup(actionId: string) {
    if (!selectedProject) return;
    setLoading(true);
    setError("");
    try {
      await startTaskSystemProjectLifecycleRun(selectedProject.project_id, {
        action: actionId,
        execute: true,
      });
      setCleanupPreview(await previewTaskSystemProjectLifecycle(selectedProject.project_id, actionId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法执行维护动作。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!selectedProjectId && writingProjects[0]?.project_id) {
      setSelectedProjectId(writingProjects[0].project_id);
    }
  }, [selectedProjectId, writingProjects]);

  useEffect(() => {
    let cancelled = false;
    async function loadInitialProjects() {
      setLoading(true);
      setError("");
      try {
        const [payload, taskOverview] = await Promise.all([
          getTaskSystemEnvironmentProjects(WRITING_ENVIRONMENT_ID),
          getTaskSystemOverview(),
        ]);
        if (cancelled) return;
        const nextProjects = payload.projects;
        setProjects(nextProjects);
        setOverview(taskOverview);
        setSelectedGraphId((current) => resolveCenterWorkspaceSelectedGraphId(taskOverview, current));
        const firstProjectId = nextProjects[0]?.project_id ?? "";
        setSelectedProjectId((current) => current || firstProjectId);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "无法读取写作项目。");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadInitialProjects();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (inspectorWidth < 560) {
      setInspectorWidth(620);
    }
  }, [inspectorWidth, setInspectorWidth]);

  useEffect(() => {
    if (selectedProjectId) void loadProject(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) void loadScopedSessions(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    const graph = chooseFlowGraph(taskGraphs, flow, selectedGraphId);
    if (graph && graph.graph_id !== selectedGraphId) {
      setSelectedGraphId(graph.graph_id);
    }
  }, [flow, selectedGraphId, taskGraphs]);

  return (
    <WorkbenchShell
      className="creative-environment-shell"
      hideMainToolbar
      leftPanel={(
        <CreativeProjectRail
          currentSessionId={scopedCurrentSessionId}
          loading={loading}
          onRefresh={() => void loadOverview()}
          onRefreshSessions={() => selectedProject && void loadScopedSessions(selectedProject.project_id)}
          onCreateSession={() => void createProjectSession()}
          onSelectSession={(sessionId) => void selectProjectSession(sessionId)}
          onDeleteSession={(sessionId) => void deleteProjectSession(sessionId)}
          onSelectProject={setSelectedProjectId}
          selectedProjectId={selectedProject?.project_id ?? ""}
          scopedSessions={scopedSessions}
          projects={writingProjects}
        />
      )}
      leftPanelLabel="写作项目"
      rightPanel={(
        <CreativeInspector
          error={error}
          file={file}
          lifecycleActions={lifecycleActions}
          cleanupPreview={cleanupPreview}
          loading={loading}
          onRefresh={() => selectedProject && void loadProject(selectedProject.project_id)}
          onPreviewCleanup={() => void previewCleanup()}
          onExecuteCleanup={(actionId) => void executeCleanup(actionId)}
          project={project}
          repositories={repositories}
          selectedFile={selectedFile}
          selectedProject={selectedProject}
        />
      )}
      rightPanelLabel="资料预览"
    >
      <CreativeCommandDesk
        activeSection={activeSection}
        currentSessionId={scopedCurrentSessionId}
        error={error}
        flow={flow}
        loading={loading}
        onCreateSession={() => void createProjectSession()}
        onSelectFile={(item) => void openFile(item)}
        onSelectFlow={selectFlow}
        onSelectGraph={setSelectedGraphId}
        onSelectSection={setActiveSection}
        onSelectSession={(sessionId) => void selectProjectSession(sessionId)}
        onDeleteSession={(sessionId) => void deleteProjectSession(sessionId)}
        onStartGraph={() => void startWritingGraph()}
        onTaskMessageChange={setTaskMessage}
        overview={overview}
        project={project}
        repositories={repositories}
        scopedSessions={scopedSessions}
        selectedFile={selectedFile}
        selectedGraphId={selectedGraphId}
        selectedProject={selectedProject}
        startError={startError}
        starting={starting}
        taskGraphs={taskGraphs}
        taskMessage={taskMessage}
        trees={trees}
      />
    </WorkbenchShell>
  );
}
