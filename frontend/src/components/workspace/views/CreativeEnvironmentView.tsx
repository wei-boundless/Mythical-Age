"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  LibraryBig,
  MessageSquare,
  RefreshCw,
} from "lucide-react";

import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import {
  getTaskSystemEnvironmentProjects,
  getTaskSystemProject,
  getTaskSystemProjectRepositories,
  getTaskSystemProjectRepositoryFile,
  getTaskSystemProjectRepositoryTree,
  type ProjectFilePayload,
  type ProjectFileTreePayload,
  type ProjectInstance,
  type ProjectLibraryPayload,
  type ProjectLibraryRepository,
  type ProjectRepositoriesPayload,
  type ProjectTreeNode,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

const WRITING_ENVIRONMENT_ID = "env.creation.writing";

type SelectedFile = {
  repository_id: string;
  path: string;
  name: string;
};

function projectTitle(project: ProjectInstance | null) {
  return project?.title || project?.project_id || "未选择项目";
}

function repositoryLabel(repository: ProjectLibraryRepository) {
  const title = repository.title || repository.repository_id;
  const roles = repository.selected_roles?.length ? ` · ${repository.selected_roles.join("/")}` : "";
  return `${title}${roles}`;
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

function CreativeLeftPanel({
  projects,
  selectedProjectId,
  loading,
  onRefresh,
  onSelectProject,
}: {
  projects: ProjectInstance[];
  selectedProjectId: string;
  loading: boolean;
  onRefresh: () => void;
  onSelectProject: (projectId: string) => void;
}) {
  const { createNewSession, currentSessionId, sessions, selectSession } = useAppStore();
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const visibleSessions = [...sessions].sort((a, b) => b.updated_at - a.updated_at).slice(0, 8);

  return (
    <aside className="workbench-resource-panel creative-workspace-left" aria-label="写作项目">
      <header className="workbench-panel-head">
        <div>
          <strong>写作项目</strong>
          <span>{projects.length} 个项目</span>
        </div>
        <WorkspaceModeSwitcher />
      </header>

      <section className="creative-project-card">
        <span>当前环境</span>
        <strong>创作写作</strong>
        <small>打开项目即可进入它自己的项目库</small>
      </section>

      <div className="creative-section-list">
        <section className="creative-section">
          <button className="creative-section__head" onClick={onRefresh} type="button">
            <RefreshCw size={14} />
            <div>
              <strong>项目实例</strong>
              <span>{loading ? "正在读取" : "项目库与创作流程"}</span>
            </div>
            <em>{projects.length}</em>
          </button>
          <div className="creative-file-list">
            {projects.length ? projects.map((project) => (
              <button
                className={selectedProjectId === project.project_id ? "creative-file-row creative-file-row--active" : "creative-file-row"}
                key={project.project_id}
                onClick={() => onSelectProject(project.project_id)}
                type="button"
              >
                <LibraryBig size={14} />
                <span>{project.title || project.project_id}</span>
                <small>{project.project_kind || project.lifecycle_state}</small>
              </button>
            )) : (
              <div className="creative-empty">还没有写作项目。</div>
            )}
          </div>
        </section>
      </div>

      <section className="creative-section creative-session-compact">
        <button className="creative-section__head" onClick={() => setSessionsOpen((value) => !value)} type="button">
          {sessionsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <div>
            <strong>会话</strong>
            <span>写作过程记录</span>
          </div>
          <MessageSquare size={14} onClick={(event) => {
            event.stopPropagation();
            void createNewSession();
          }} />
        </button>
        {sessionsOpen ? (
          <div className="creative-session-list">
            {visibleSessions.map((session) => (
              <button
                className={session.id === currentSessionId ? "creative-session-row creative-session-row--active" : "creative-session-row"}
                key={session.id}
                onClick={() => void selectSession(session.id)}
                type="button"
              >
                <MessageSquare size={13} />
                <span>{session.title || "未命名会话"}</span>
                <small>{new Date(session.updated_at * 1000).toLocaleDateString("zh-CN")}</small>
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </aside>
  );
}

function CreativeRightPanel({
  selectedProject,
  project,
  repositories,
  trees,
  selectedFile,
  file,
  loading,
  error,
  onRefresh,
  onSelectFile,
}: {
  selectedProject: ProjectInstance | null;
  project: ProjectLibraryPayload | null;
  repositories: ProjectRepositoriesPayload | null;
  trees: Record<string, ProjectFileTreePayload>;
  selectedFile: SelectedFile | null;
  file: ProjectFilePayload | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onSelectFile: (file: SelectedFile) => void;
}) {
  return (
    <aside className="workbench-right-panel creative-workspace-right" aria-label="项目库">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>项目库</strong>
          <span>{projectTitle(selectedProject)}</span>
        </div>
        <button className="workbench-icon-button" disabled={loading || !selectedProject} onClick={onRefresh} type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="creative-right-body">
        <section className="creative-detail-card creative-detail-card--selected">
          <header>
            <LibraryBig size={15} />
            <strong>{project?.project.title || "未打开项目"}</strong>
            <em>{project?.project.project_kind || "等待项目"}</em>
          </header>
          <dl>
            <div><dt>项目</dt><dd>{selectedProject?.project_id || "未选择"}</dd></div>
            <div><dt>库</dt><dd>{project?.library.library_id || "未解析"}</dd></div>
            <div><dt>结构</dt><dd>{project?.library.schema_version || "未加载"}</dd></div>
          </dl>
          {error ? <div className="creative-empty">{error}</div> : null}
        </section>

        {(repositories?.repositories ?? []).map((repository) => {
          const tree = trees[repository.repository_id];
          const files = collectFiles(tree?.tree ?? null).slice(0, 12);
          return (
            <section className="creative-detail-card" key={repository.repository_id}>
              <header>
                <FolderOpen size={15} />
                <strong>{repositoryLabel(repository)}</strong>
                <em>{tree ? `${tree.total_entries} 项` : "未加载"}</em>
              </header>
              <div className="creative-tree-summary creative-tree-summary--stack">
                {files.length ? files.map((item) => (
                  <button
                    className={selectedFile?.repository_id === repository.repository_id && selectedFile.path === item.path ? "creative-file-chip creative-file-chip--active" : "creative-file-chip"}
                    key={`${repository.repository_id}:${item.path}`}
                    onClick={() => onSelectFile({ repository_id: repository.repository_id, path: item.path, name: item.name })}
                    type="button"
                  >
                    <FileText size={13} />
                    <span title={item.path}>{item.name}</span>
                  </button>
                )) : <div className="creative-empty">暂无可显示文件。</div>}
              </div>
            </section>
          );
        })}

        <section className="creative-detail-card">
          <header>
            <FileText size={15} />
            <strong>{selectedFile?.name || "文件预览"}</strong>
            <em>{file ? "已打开" : "未选择"}</em>
          </header>
          {file ? (
            <pre className="creative-file-preview">{file.content.slice(0, 2400)}</pre>
          ) : (
            <div className="creative-empty">从项目库中选择一个文件。</div>
          )}
        </section>
      </div>
    </aside>
  );
}

export function CreativeEnvironmentView() {
  const [projects, setProjects] = useState<ProjectInstance[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [project, setProject] = useState<ProjectLibraryPayload | null>(null);
  const [repositories, setRepositories] = useState<ProjectRepositoriesPayload | null>(null);
  const [trees, setTrees] = useState<Record<string, ProjectFileTreePayload>>({});
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null);
  const [file, setFile] = useState<ProjectFilePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const writingProjects = useMemo<ProjectInstance[]>(() => projects, [projects]);

  const selectedProject = useMemo(() => {
    return writingProjects.find((item) => item.project_id === selectedProjectId) ?? writingProjects[0] ?? null;
  }, [selectedProjectId, writingProjects]);

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const payload = await getTaskSystemEnvironmentProjects(WRITING_ENVIRONMENT_ID);
      const nextProjects = payload.projects;
      setProjects(nextProjects);
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
    try {
      const nextProject = await getTaskSystemProject(projectId);
      setProject(nextProject);
      const nextRepositories = await getTaskSystemProjectRepositories(projectId);
      setRepositories(nextRepositories);
      const treeEntries = await Promise.all(
        nextRepositories.repositories
          .filter((repository) => repository.readable !== false)
          .map(async (repository) => {
            const tree = await getTaskSystemProjectRepositoryTree(projectId, repository.repository_id, {
              maxDepth: repository.project_role === "artifact_repository" ? 5 : 3,
              maxEntries: 800,
            }).catch(() => null);
            return [repository.repository_id, tree] as const;
          })
      );
      setTrees(Object.fromEntries(treeEntries.filter((entry): entry is readonly [string, ProjectFileTreePayload] => Boolean(entry[1]))));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法打开项目库。");
      setProject(null);
      setRepositories(null);
      setTrees({});
    } finally {
      setLoading(false);
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
        const payload = await getTaskSystemEnvironmentProjects(WRITING_ENVIRONMENT_ID);
        if (cancelled) return;
        const nextProjects = payload.projects;
        setProjects(nextProjects);
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
    if (selectedProjectId) void loadProject(selectedProjectId);
  }, [selectedProjectId]);

  return (
    <WorkbenchShell
      className="creative-environment-shell"
      leftPanel={(
        <CreativeLeftPanel
          loading={loading}
          onRefresh={() => void loadOverview()}
          onSelectProject={setSelectedProjectId}
          selectedProjectId={selectedProject?.project_id ?? ""}
          projects={writingProjects}
        />
      )}
      leftPanelLabel="写作项目"
      rightPanel={(
        <CreativeRightPanel
          error={error}
          file={file}
          loading={loading}
          onRefresh={() => selectedProject && void loadProject(selectedProject.project_id)}
          onSelectFile={(item) => void openFile(item)}
          project={project}
          repositories={repositories}
          selectedFile={selectedFile}
          selectedProject={selectedProject}
          trees={trees}
        />
      )}
      rightPanelLabel="项目库"
    >
      <section className="workbench-view-host creative-center-host" aria-label="写作项目会话">
        <div className="creative-center-banner">
          <div>
            <span>写作环境</span>
            <strong>{projectTitle(selectedProject)}</strong>
          </div>
          <div>
            <LibraryBig size={15} />
            <span>{project?.project.title || "项目库"}</span>
          </div>
        </div>
        <CenterWorkspaceView />
      </section>
    </WorkbenchShell>
  );
}
