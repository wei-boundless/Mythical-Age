"use client";

import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  File,
  Folder,
  FolderOpen,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Trash2,
  Unlink,
} from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { RunMonitorPanel } from "@/components/layout/RunMonitorPanel";
import { FileChangesPanel } from "@/components/layout/FileChangesPanel";
import type { CodeEnvironmentTreeNode } from "@/lib/api";
import type { SessionSummary } from "@/lib/api";
import { sessionSummaryIsRunning, sessionSummaryTask, sessionTaskActivityKind, sessionTaskStatusLabel } from "@/lib/sessionTaskPresentation";
import { useAppStore } from "@/lib/store";

const LEFT_WIDTH_KEY = "agentWorkbench.leftWidth";
const RIGHT_WIDTH_KEY = "agentWorkbench.rightWidth";
const LEFT_COLLAPSED_KEY = "agentWorkbench.leftCollapsed";
const RIGHT_COLLAPSED_KEY = "agentWorkbench.rightCollapsed";
const RUN_SECTION_OPEN_KEY = "agentWorkbench.rightSection.runOpen";
const CHANGES_SECTION_OPEN_KEY = "agentWorkbench.rightSection.changesOpen";
const PANEL_RAIL_WIDTH = 44;
const RESIZE_HANDLE_WIDTH = 8;
const WORKBENCH_CENTER_MIN_WIDTH = 520;
const WORKBENCH_CENTER_COMPACT_MIN_WIDTH = 340;
const WORKBENCH_EDGE_GUTTER = 10;
const RIGHT_PANEL_MIN_WIDTH = 320;
const DEFAULT_SESSION_TITLE = "New Session";

export type WorkbenchShellControls = {
  closeLeftPanel: () => void;
  closeRightPanel: () => void;
  leftCollapsed: boolean;
  leftPanelLabel: string;
  openLeftPanel: () => void;
  openRightPanel: () => void;
  rightCollapsed: boolean;
  rightPanelLabel: string;
  toggleLeftPanel: () => void;
  toggleRightPanel: () => void;
};

const WorkbenchShellControlsContext = createContext<WorkbenchShellControls | null>(null);

export function useWorkbenchShellControls() {
  return useContext(WorkbenchShellControlsContext);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function clampLeftWidth(value: number) {
  return clamp(value, 180, 780);
}

function clampRightWidth(value: number) {
  return clamp(value, RIGHT_PANEL_MIN_WIDTH, 1180);
}

function workbenchCenterMinWidth(viewportWidth: number) {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) {
    return WORKBENCH_CENTER_MIN_WIDTH;
  }
  return clamp(Math.floor(viewportWidth * 0.42), WORKBENCH_CENTER_COMPACT_MIN_WIDTH, WORKBENCH_CENTER_MIN_WIDTH);
}

function fitWorkbenchPanelWidths({
  inspectorWidth,
  leftCollapsed,
  rightCollapsed,
  sidebarWidth,
  viewportWidth,
}: {
  inspectorWidth: number;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  sidebarWidth: number;
  viewportWidth: number;
}) {
  const centerMinWidth = workbenchCenterMinWidth(viewportWidth);
  const leftMin = leftCollapsed ? PANEL_RAIL_WIDTH : 180;
  const rightMin = rightCollapsed ? PANEL_RAIL_WIDTH : RIGHT_PANEL_MIN_WIDTH;
  let leftWidth = leftCollapsed ? PANEL_RAIL_WIDTH : clampLeftWidth(sidebarWidth);
  let rightWidth = rightCollapsed ? PANEL_RAIL_WIDTH : clampRightWidth(inspectorWidth);
  const handleWidth = (leftCollapsed ? 0 : RESIZE_HANDLE_WIDTH) + (rightCollapsed ? 0 : RESIZE_HANDLE_WIDTH);
  const maxCombinedWidth = Number.isFinite(viewportWidth) && viewportWidth > 0
    ? Math.max(leftMin + rightMin, viewportWidth - centerMinWidth - handleWidth - WORKBENCH_EDGE_GUTTER)
    : Number.POSITIVE_INFINITY;
  const overflow = leftWidth + rightWidth - maxCombinedWidth;

  if (overflow > 0 && Number.isFinite(overflow)) {
    const leftRoom = Math.max(0, leftWidth - leftMin);
    const rightRoom = Math.max(0, rightWidth - rightMin);
    const room = leftRoom + rightRoom;
    if (room > 0) {
      const leftReduction = Math.min(leftRoom, overflow * (leftRoom / room));
      const rightReduction = Math.min(rightRoom, overflow - leftReduction);
      leftWidth -= leftReduction;
      rightWidth -= rightReduction;
      const remainder = leftWidth + rightWidth - maxCombinedWidth;
      if (remainder > 0) {
        if (leftWidth - leftMin >= rightWidth - rightMin) {
          leftWidth = Math.max(leftMin, leftWidth - remainder);
        } else {
          rightWidth = Math.max(rightMin, rightWidth - remainder);
        }
      }
    }
  }

  return {
    centerMinWidth,
    leftWidth: Math.round(leftWidth),
    rightWidth: Math.round(rightWidth),
  };
}

function looksRuntimeIdentifier(value: string, currentSessionId = "") {
  const text = value.trim();
  if (!text) return false;
  if (currentSessionId && text === currentSessionId) return true;
  return /^(session|taskrun|task|turn|turnrun|grun|coordrun|rtobj|rtpacket)[:-]/i.test(text);
}

function friendlySessionTitle(title: string | undefined, currentSessionId: string) {
  const candidate = String(title || "").trim();
  if (candidate && !looksRuntimeIdentifier(candidate, currentSessionId) && !looksAssistantArtifactSessionTitle(candidate)) {
    return candidate;
  }
  return "当前会话";
}

function looksAssistantArtifactSessionTitle(title: string | undefined) {
  const text = String(title || "").replace(/\s+/g, " ").trim();
  if (!text) return false;
  if (["```", "##", "---", "|---", "###"].some((marker) => text.includes(marker))) return true;
  if (
    [
      "经过全面排查",
      "以下是我的",
      "这是我的",
      "这是一个独立的",
      "这是一个独立的小型交付请求",
      "好，我已经",
      "好了，我已经",
      "好的，我已经",
      "现在我已经",
      "我现在已经",
      "我已经完成",
      "我已经读完",
      "已完成",
    ].some((prefix) => text.startsWith(prefix))
  ) {
    return true;
  }
  return ["诊断结果", "诊断结论", "修改已完成", "交付请求", "以下是修复结果"].some((fragment) => text.includes(fragment));
}

function isLegacyInternalEditablePath(path: string) {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  return [
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/skills/builtin/",
  ].some((prefix) => normalized.startsWith(prefix));
}

function formatSessionTime(timestamp: number) {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "无时间";
  const date = new Date(timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function sessionTask(session: SessionSummary) {
  return sessionSummaryTask(session);
}

function projectRootFromSession(session: SessionSummary | null | undefined) {
  return String(session?.conversation_state?.project_binding?.workspace_root || "").trim();
}

function workspaceRootKey(root: string) {
  return root.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

function sessionBelongsToProject(session: SessionSummary, workspaceRoot: string) {
  const root = workspaceRootKey(workspaceRoot);
  return Boolean(root && workspaceRootKey(projectRootFromSession(session)) === root);
}

function projectNameFromRoot(root: string) {
  const normalized = root.replace(/\\/g, "/").replace(/\/+$/, "");
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || root || "当前项目";
}

function sessionDisplayTitle(session: SessionSummary) {
  const title = friendlySessionTitle(session.title, session.id);
  return title === DEFAULT_SESSION_TITLE && Number(session.message_count || 0) > 0 ? "未命名会话" : title;
}

function sessionMetaLine(session: SessionSummary) {
  const task = sessionTask(session);
  const projectRoot = projectRootFromSession(session);
  const projectLabel = projectRoot ? `${projectNameFromRoot(projectRoot)} · ` : "";
  if (!task) {
    return `${projectLabel}${sessionTurnCountLabel(session)} · ${formatSessionTime(session.updated_at)}`;
  }
  const updatedAt = Number(task.updated_at || session.updated_at || 0);
  return `${projectLabel}${sessionTaskStatusLabel(task)} · ${formatSessionTime(updatedAt)}`;
}

function sessionTurnCountLabel(session: SessionSummary) {
  const turnCount = Number(session.turn_count);
  if (Number.isFinite(turnCount) && turnCount >= 0) {
    return `${turnCount} 轮`;
  }
  return `${session.message_count} 条`;
}

function sessionIsRunning(session: SessionSummary) {
  return sessionSummaryIsRunning(session);
}

function projectSelectionErrorMessage(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error || "");
  if (/project directory selection cancelled/i.test(raw)) {
    return "";
  }
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (String(parsed?.detail || "").toLowerCase() === "project directory selection cancelled") {
      return "";
    }
  } catch {
    // Keep the original error when it is not the known user-cancel response.
  }
  return raw;
}

function usePersistedWorkbenchWidths() {
  const { sidebarWidth, inspectorWidth, setSidebarWidth, setInspectorWidth } = useAppStore();

  useEffect(() => {
    const left = Number(window.localStorage.getItem(LEFT_WIDTH_KEY));
    const right = Number(window.localStorage.getItem(RIGHT_WIDTH_KEY));
    if (Number.isFinite(left) && left > 0) setSidebarWidth(clampLeftWidth(left));
    if (Number.isFinite(right) && right > 0) setInspectorWidth(clampRightWidth(right));
  }, [setInspectorWidth, setSidebarWidth]);

  useEffect(() => {
    window.localStorage.setItem(LEFT_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    window.localStorage.setItem(RIGHT_WIDTH_KEY, String(inspectorWidth));
  }, [inspectorWidth]);
}

function ResizeHandle({
  label,
  onResize,
  side,
}: {
  label: string;
  onResize: (delta: number) => void;
  side: "left" | "right";
}) {
  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const pointerId = event.pointerId;
    const move = (moveEvent: globalThis.PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      onResize(side === "left" ? delta : -delta);
    };
    const up = () => {
      handle.releasePointerCapture(pointerId);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  return (
    <div
      aria-label={label}
      className="workbench-resize-handle"
      onPointerDown={startDrag}
      role="separator"
    />
  );
}

function WorkbenchProjectTreeNode({
  activePath,
  node,
  onOpenFile,
}: {
  activePath: string;
  node: CodeEnvironmentTreeNode;
  onOpenFile: (path: string) => void;
}) {
  const directory = node.kind === "directory";
  const [expanded, setExpanded] = useState(false);
  const hasChildren = directory && node.children.length > 0;
  const selected = !directory && node.path === activePath;
  return (
    <li>
      <button
        aria-expanded={hasChildren ? expanded : undefined}
        aria-current={selected ? "true" : undefined}
        className={[
          "workbench-project-tree-row",
          directory ? "workbench-project-tree-row--directory" : "",
          selected ? "workbench-project-tree-row--active" : "",
        ].filter(Boolean).join(" ")}
        onClick={() => {
          if (directory) {
            if (hasChildren) setExpanded((value) => !value);
            return;
          }
          if (node.path) onOpenFile(node.path);
        }}
        style={{ "--tree-depth": node.depth } as CSSProperties}
        title={node.path || node.name}
        type="button"
      >
        {hasChildren ? (expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="workbench-project-tree-row__spacer" />}
        {directory ? (expanded ? <FolderOpen size={13} /> : <Folder size={13} />) : <File size={13} />}
        <span>{node.name}</span>
        {node.truncated ? <small>截断</small> : null}
      </button>
      {hasChildren && expanded ? (
        <ul>
          {node.children.map((child) => (
            <WorkbenchProjectTreeNode
              activePath={activePath}
              key={`${child.kind}:${child.path}`}
              node={child}
              onOpenFile={onOpenFile}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function WorkspaceManagerPanel({
  onCollapse,
  onOpenFile,
}: {
  onCollapse: () => void;
  onOpenFile: (path: string) => void;
}) {
  const {
    activeProjectKey,
    activeProjectRoot,
    currentSessionId,
    inspectorPath,
    projectSessions,
    projectWorkspaces,
    projectWorkspacesError,
    projectWorkspacesLoading,
    sessions,
    createNewSession,
    removeProjectWorkspace,
    removeSession,
    selectProjectWorkspace,
    selectProjectWorkspaceDirectory,
    selectSession,
    workspaceTree,
    workspaceTreeError,
    workspaceTreeLoading,
  } = useAppStore();
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? null;
  const currentSessionProjectRoot = projectRootFromSession(currentSession);
  const projectScopeActive = Boolean(activeProjectKey || currentSessionProjectRoot);
  const visibleSessions = [
    ...(projectScopeActive
      ? activeProjectKey
        ? projectSessions
        : sessions.filter((session) => sessionBelongsToProject(session, currentSessionProjectRoot))
      : sessions.filter((session) => !projectRootFromSession(session))),
  ].sort((a, b) => b.updated_at - a.updated_at);
  const boundProjectRoot = activeProjectKey ? activeProjectRoot : currentSessionProjectRoot;
  const workspaceSummary = workspaceTree
    ? `${workspaceTree.total_entries} 项 · ${workspaceTree.root_name}`
    : workspaceTreeLoading
      ? "项目文件加载中"
      : "项目文件未加载";
  const projectWorkspacesErrorLabel = projectSelectionErrorMessage(projectWorkspacesError);
  const projectTreeNodes = workspaceTree?.tree.children || [];
  const unboundSessionCount = sessions.filter((session) => !projectRootFromSession(session)).length;
  const [bindingProjectBusy, setBindingProjectBusy] = useState(false);
  const [bindingProjectError, setBindingProjectError] = useState("");
  const [pendingRemoveProjectKey, setPendingRemoveProjectKey] = useState("");
  const [removingProjectKey, setRemovingProjectKey] = useState("");
  const [removeProjectError, setRemoveProjectError] = useState("");
  const [filesOpen, setFilesOpen] = useState(false);

  useEffect(() => {
    if (!boundProjectRoot) {
      return;
    }
    setBindingProjectError("");
  }, [boundProjectRoot]);

  async function handleBindProject() {
    setBindingProjectBusy(true);
    setBindingProjectError("");
    try {
      await selectProjectWorkspaceDirectory();
    } catch (error) {
      setBindingProjectError(projectSelectionErrorMessage(error));
    } finally {
      setBindingProjectBusy(false);
    }
  }

  async function handleRemoveProject(projectKey: string) {
    setRemovingProjectKey(projectKey);
    setRemoveProjectError("");
    try {
      await removeProjectWorkspace(projectKey);
      setPendingRemoveProjectKey("");
    } catch (error) {
      setRemoveProjectError(projectSelectionErrorMessage(error) || "项目移出失败。");
    } finally {
      setRemovingProjectKey("");
    }
  }

  return (
    <aside className="workbench-resource-panel" aria-label="任务环境管理">
      <header className="workbench-panel-head">
        <div>
          <strong>项目</strong>
          <span>{projectWorkspaces.length ? `${projectWorkspaces.length} 个可选项目` : "可直接对话"}</span>
        </div>
        <div className="workbench-panel-head__actions">
          <button
            aria-label="收起左侧项目栏"
            className="workbench-panel-head__action"
            onClick={onCollapse}
            title="收起左侧项目栏"
            type="button"
          >
            <PanelLeftClose size={14} />
          </button>
          <button
            aria-label="添加项目"
            className="workbench-panel-head__action"
            disabled={bindingProjectBusy || projectWorkspacesLoading}
            onClick={() => void handleBindProject()}
            title="添加项目"
            type="button"
          >
            <Plus size={14} />
          </button>
        </div>
      </header>

      <section className="workbench-project-context workbench-project-switcher" aria-label="会话范围">
        <div className="workbench-project-switcher__list">
          <button
            aria-current={!projectScopeActive ? "page" : undefined}
            className={[
              "workbench-project-scope-row",
              !projectScopeActive ? "workbench-project-scope-row--active" : "",
            ].filter(Boolean).join(" ")}
            disabled={projectWorkspacesLoading}
            onClick={() => {
              if (projectScopeActive) {
                void selectProjectWorkspace("");
              }
            }}
            title="切换到未绑定会话"
            type="button"
          >
            <span className="workbench-project-scope-row__icon"><MessageSquare size={14} /></span>
            <span className="workbench-project-scope-row__main">
              <strong>未绑定会话</strong>
              <small>{unboundSessionCount} 个对话</small>
            </span>
          </button>

          {projectWorkspaces.map((project) => {
            const active = project.key === activeProjectKey;
            const pendingRemove = pendingRemoveProjectKey === project.key;
            const removing = removingProjectKey === project.key;
            return (
              <div
                className={[
                  "workbench-project-scope-item",
                  active ? "workbench-project-scope-item--active" : "",
                  pendingRemove ? "workbench-project-scope-item--confirming" : "",
                ].filter(Boolean).join(" ")}
                key={project.key}
              >
                <div className="workbench-project-scope-row-wrap">
                  <button
                    aria-current={active ? "page" : undefined}
                    className="workbench-project-scope-row"
                    disabled={projectWorkspacesLoading || removing}
                    onClick={() => {
                      if (!active) {
                        void selectProjectWorkspace(project.key);
                      }
                    }}
                    title={project.workspace_root}
                    type="button"
                  >
                    <span className={project.available ? "workbench-project-scope-row__status" : "workbench-project-scope-row__status is-missing"} />
                    <span className="workbench-project-scope-row__icon"><Folder size={14} /></span>
                    <span className="workbench-project-scope-row__main">
                      <strong>{project.name}</strong>
                      <small>{project.workspace_root}</small>
                    </span>
                    <span className="workbench-project-scope-row__count" title={`${project.session_count} 个项目对话`}>
                      {project.session_count}
                    </span>
                  </button>
                  <div className="workbench-project-scope-row__actions">
                    <button
                      disabled={removing}
                      onClick={() => setPendingRemoveProjectKey(pendingRemove ? "" : project.key)}
                      title="移出项目列表"
                      type="button"
                    >
                      <Unlink size={13} />
                    </button>
                  </div>
                </div>
                {pendingRemove ? (
                  <div className="workbench-project-remove-confirm">
                    <span>移出项目</span>
                    <button disabled={removing} onClick={() => setPendingRemoveProjectKey("")} type="button">取消</button>
                    <button disabled={removing} onClick={() => void handleRemoveProject(project.key)} type="button">
                      {removing ? "移出中" : "确认"}
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>

        {bindingProjectError ? <small className="workbench-project-bind-error">{bindingProjectError}</small> : null}
        {projectWorkspacesErrorLabel ? <small className="workbench-project-bind-error">{projectWorkspacesErrorLabel}</small> : null}
        {removeProjectError ? <small className="workbench-project-bind-error">{removeProjectError}</small> : null}
      </section>

      <div className="workbench-left-body">
        <section className="workbench-session-panel workbench-session-panel--primary" aria-label="对话记录">
          <div className="workbench-session-toolbar">
            <div>
              <strong>对话</strong>
              <span>{boundProjectRoot ? `${visibleSessions.length} 个项目对话` : `${visibleSessions.length} 个未绑定对话`}</span>
            </div>
            <button aria-label={boundProjectRoot ? "新建项目对话" : "新建未绑定对话"} onClick={() => void createNewSession()} type="button">
              <Plus size={15} />
              <span>新建</span>
            </button>
          </div>
          <div className="workbench-session-list">
            {visibleSessions.length ? visibleSessions.map((session) => {
              const active = session.id === currentSessionId;
              const running = sessionIsRunning(session);
              return (
              <div className={[
                "workbench-session-row",
                active ? "workbench-session-row--active" : "",
                running ? "workbench-session-row--running" : "",
              ].filter(Boolean).join(" ")} key={session.id}>
                <button
                  aria-current={active ? "page" : undefined}
                  onClick={() => void selectSession({ sessionId: session.id, scope: session.scope, poolKey: "main-chat" })}
                  type="button"
                >
                  <span className="workbench-session-title-line">
                    {running ? <span aria-label="正在运行" className="workbench-session-running-dot" role="img" title="正在运行" /> : null}
                    <strong>{sessionDisplayTitle(session)}</strong>
                  </span>
                  <small>{sessionMetaLine(session)}</small>
                </button>
                <button
                  aria-label={`删除 ${session.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void removeSession({ sessionId: session.id, scope: session.scope, poolKey: "main-chat" });
                  }}
                  type="button"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            );}) : (
              <div className="workbench-empty-state">
                <MessageSquare size={18} />
                <strong>{boundProjectRoot ? "这个项目还没有对话" : "还没有未绑定对话"}</strong>
                <span>{boundProjectRoot ? "新建后开始" : "可以不绑定项目直接开始"}</span>
              </div>
            )}
          </div>
        </section>

        <section
          className={filesOpen ? "workbench-file-tree workbench-file-tree--secondary" : "workbench-file-tree workbench-file-tree--secondary is-collapsed"}
          aria-label="项目文件"
        >
          <div className="workbench-file-tree__head">
            <button
              aria-expanded={filesOpen}
              className="workbench-file-tree__toggle"
              onClick={() => setFilesOpen((value) => !value)}
              type="button"
            >
              {filesOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <div>
                <strong>项目文件</strong>
                <span>{workspaceSummary}</span>
              </div>
            </button>
          </div>
          {filesOpen ? (
            <div className="workbench-project-file-list">
              {workspaceTreeError ? <div className="workbench-tree-state workbench-tree-state--error">{workspaceTreeError}</div> : null}
              {workspaceTreeLoading && !workspaceTree ? <div className="workbench-tree-state">正在读取项目目录。</div> : null}
              {!workspaceTreeLoading && !workspaceTreeError && workspaceTree && !projectTreeNodes.length ? (
                <div className="workbench-tree-state">未发现可显示文件。</div>
              ) : null}
              {projectTreeNodes.length ? (
                <ul className="workbench-project-tree">
                  {projectTreeNodes.map((node) => (
                    <WorkbenchProjectTreeNode
                      activePath={inspectorPath}
                      key={`${node.kind}:${node.path}`}
                      node={node}
                      onOpenFile={onOpenFile}
                    />
                  ))}
                </ul>
              ) : null}
              {workspaceTree?.truncated ? <div className="workbench-tree-state">文件较多，已显示前 {workspaceTree.max_entries} 项。</div> : null}
            </div>
          ) : null}
        </section>
      </div>
    </aside>
  );
}

function MainToolbar({
  leftPanelCollapsed,
  onToggleLeftPanel,
  onToggleRightPanel,
  rightPanelCollapsed,
}: {
  leftPanelCollapsed: boolean;
  onToggleLeftPanel: () => void;
  onToggleRightPanel: () => void;
  rightPanelCollapsed: boolean;
}) {
  const {
    activeStreamSessionIds,
    currentSessionId,
    inspectorDirty,
    inspectorPath,
    inspectorTarget,
    saveInspector,
    sessionActivity,
    sessions,
  } = useAppStore();
  const editable = Boolean(inspectorTarget) || isLegacyInternalEditablePath(inspectorPath);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? null;
  const currentTask = currentSession ? sessionTask(currentSession) : undefined;
  const currentTaskActivity = sessionTaskActivityKind(currentTask);
  const subject = friendlySessionTitle(currentSession?.title, currentSessionId || "");
  const receivingStream = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const taskRunning = currentSession ? sessionIsRunning(currentSession) : false;
  const streaming = receivingStream || taskRunning;
  const activityLabel = streaming
    ? sessionActivity.title || sessionActivity.detail || sessionActivity.event || "处理中"
    : currentTaskActivity === "waiting" || currentTaskActivity === "paused" || currentTaskActivity === "stale" || currentTaskActivity === "stopped" || currentTaskActivity === "failed"
      ? sessionTaskStatusLabel(currentTask)
    : inspectorDirty
      ? "有未保存文件"
      : "待命";
  const runtimeStateClassName = [
    "workbench-runtime-state",
    streaming ? "workbench-runtime-state--active" : "",
    !streaming && (currentTaskActivity === "waiting" || currentTaskActivity === "paused" || currentTaskActivity === "stale") ? "workbench-runtime-state--waiting" : "",
    !streaming && currentTaskActivity === "stopped" ? "workbench-runtime-state--stopped" : "",
  ].filter(Boolean).join(" ");

  return (
    <header className="workbench-main-toolbar">
      <div className="workbench-breadcrumb">
        <span>会话</span>
        <strong>{subject}</strong>
      </div>
      <div className={runtimeStateClassName}>
        <CircleDot size={13} />
        <span>{activityLabel}</span>
      </div>
      <div className="workbench-toolbar-actions">
        <button
          aria-label={leftPanelCollapsed ? "打开左侧任务环境" : "收起左侧任务环境"}
          className="workbench-toolbar-icon-button"
          onClick={onToggleLeftPanel}
          title={leftPanelCollapsed ? "打开左侧任务环境" : "收起左侧任务环境"}
          type="button"
        >
          {leftPanelCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
        </button>
        <button
          aria-label={rightPanelCollapsed ? "打开辅助栏" : "收起辅助栏"}
          className="workbench-toolbar-icon-button"
          onClick={onToggleRightPanel}
          title={rightPanelCollapsed ? "打开辅助栏" : "收起辅助栏"}
          type="button"
        >
          {rightPanelCollapsed ? <PanelRightOpen size={15} /> : <PanelRightClose size={15} />}
        </button>
        <button disabled={!inspectorDirty || !editable} onClick={() => void saveInspector()} type="button">保存</button>
      </div>
    </header>
  );
}

function useViewportWidth() {
  const [viewportWidth, setViewportWidth] = useState(0);

  useEffect(() => {
    const update = () => setViewportWidth(window.innerWidth);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return viewportWidth;
}

function useStoredSectionOpen(storageKey: string, defaultOpen: boolean) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    const saved = window.localStorage.getItem(storageKey);
    if (saved === "true" || saved === "false") {
      setOpen(saved === "true");
    }
  }, [storageKey]);

  useEffect(() => {
    window.localStorage.setItem(storageKey, String(open));
  }, [open, storageKey]);

  return [open, setOpen] as const;
}

function CollapsibleToolSection({
  children,
  defaultOpen = true,
  grow = false,
  storageKey,
  summary,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  grow?: boolean;
  storageKey: string;
  summary: string;
  title: string;
}) {
  const [open, setOpen] = useStoredSectionOpen(storageKey, defaultOpen);

  return (
    <section
      className={[
        "workbench-tool-section",
        open ? "workbench-tool-section--open" : "workbench-tool-section--closed",
        grow ? "workbench-tool-section--grow" : "",
      ].filter(Boolean).join(" ")}
    >
      <button
        aria-expanded={open}
        className="workbench-tool-section__toggle"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>
          <strong>{title}</strong>
          <small>{summary}</small>
        </span>
      </button>
      {open ? <div className="workbench-tool-section__body">{children}</div> : null}
    </section>
  );
}

function RightToolPanel() {
  const { runMonitor, runMonitorStreamStatus } = useAppStore();
  const summary = runMonitor?.summary;
  const runSummary = summary
    ? `${summary.active ?? 0} 运行 · ${summary.waiting ?? 0} 等待 · ${summary.attention ?? 0} 关注`
    : runMonitorStreamStatus === "connected"
      ? "实时连接"
      : runMonitorStreamStatus === "connecting"
        ? "连接中"
        : "待命";

  return (
    <aside className="workbench-right-panel" aria-label="辅助面板">
      <div className="workbench-right-body">
        <CollapsibleToolSection
          storageKey={RUN_SECTION_OPEN_KEY}
          summary={runSummary}
          title="运行"
        >
          <RunMonitorPanel embedded />
        </CollapsibleToolSection>
        <CollapsibleToolSection
          grow
          storageKey={CHANGES_SECTION_OPEN_KEY}
          summary="当前对话 · 产物 · 其它任务"
          title="变更"
        >
          <FileChangesPanel embedded />
        </CollapsibleToolSection>
      </div>
    </aside>
  );
}

function CollapsedPanelRail({
  label,
  onOpen,
  side,
}: {
  label: string;
  onOpen: () => void;
  side: "left" | "right";
}) {
  return (
    <aside className={`workbench-collapsed-rail workbench-collapsed-rail--${side}`} aria-label={`${label}已收起`}>
      <button aria-label={`打开${label}`} onClick={onOpen} title={`打开${label}`} type="button">
        {side === "left" ? <PanelLeftOpen size={16} /> : <PanelRightOpen size={16} />}
      </button>
      <span>{label}</span>
    </aside>
  );
}

export function WorkbenchShell({
  children,
  className = "",
  hideMainToolbar = false,
  leftPanel,
  leftPanelLabel = "任务环境",
  rightPanel,
  rightPanelLabel = "辅助栏",
}: {
  children: ReactNode;
  className?: string;
  hideMainToolbar?: boolean;
  leftPanel?: ReactNode;
  leftPanelLabel?: string;
  rightPanel?: ReactNode;
  rightPanelLabel?: string;
}) {
  const { inspectorWidth, openWorkspaceFile, setInspectorWidth, setSidebarWidth, sidebarWidth } = useAppStore();
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const viewportWidth = useViewportWidth();
  usePersistedWorkbenchWidths();

  useEffect(() => {
    setLeftCollapsed(window.localStorage.getItem(LEFT_COLLAPSED_KEY) === "true");
    setRightCollapsed(window.localStorage.getItem(RIGHT_COLLAPSED_KEY) === "true");
  }, []);

  useEffect(() => {
    window.localStorage.setItem(LEFT_COLLAPSED_KEY, String(leftCollapsed));
  }, [leftCollapsed]);

  useEffect(() => {
    window.localStorage.setItem(RIGHT_COLLAPSED_KEY, String(rightCollapsed));
  }, [rightCollapsed]);

  const layout = fitWorkbenchPanelWidths({
    inspectorWidth,
    leftCollapsed,
    rightCollapsed,
    sidebarWidth,
    viewportWidth,
  });
  const effectiveLeftWidth = layout.leftWidth;
  const effectiveRightWidth = layout.rightWidth;
  const left = leftPanel ?? (
    <WorkspaceManagerPanel
      onCollapse={() => setLeftCollapsed(true)}
      onOpenFile={(path) => {
        openWorkspaceFile(path);
      }}
    />
  );
  const right = rightPanel ?? <RightToolPanel />;
  const shellControls = useMemo<WorkbenchShellControls>(() => ({
    closeLeftPanel: () => setLeftCollapsed(true),
    closeRightPanel: () => setRightCollapsed(true),
    leftCollapsed,
    leftPanelLabel,
    openLeftPanel: () => setLeftCollapsed(false),
    openRightPanel: () => setRightCollapsed(false),
    rightCollapsed,
    rightPanelLabel,
    toggleLeftPanel: () => setLeftCollapsed((value) => !value),
    toggleRightPanel: () => setRightCollapsed((value) => !value),
  }), [leftCollapsed, leftPanelLabel, rightCollapsed, rightPanelLabel]);

  return (
    <WorkbenchShellControlsContext.Provider value={shellControls}>
      <main
        className={["agent-workbench agent-workbench--chat-only", className].filter(Boolean).join(" ")}
        style={{
          gridTemplateColumns: `${effectiveLeftWidth}px ${leftCollapsed ? "0px" : `${RESIZE_HANDLE_WIDTH}px`} minmax(${layout.centerMinWidth}px, 1fr) ${rightCollapsed ? `0px ${effectiveRightWidth}px` : `${RESIZE_HANDLE_WIDTH}px ${effectiveRightWidth}px`}`,
        }}
      >
        {leftCollapsed ? (
          <CollapsedPanelRail label={leftPanelLabel} onOpen={() => setLeftCollapsed(false)} side="left" />
        ) : left}
        {leftCollapsed ? null : (
          <ResizeHandle
            label={`调整${leftPanelLabel}宽度`}
            onResize={(delta) => {
              const nextLayout = fitWorkbenchPanelWidths({
                inspectorWidth: effectiveRightWidth,
                leftCollapsed,
                rightCollapsed,
                sidebarWidth: effectiveLeftWidth + delta,
                viewportWidth,
              });
              setSidebarWidth(nextLayout.leftWidth);
            }}
            side="left"
          />
        )}
        {leftCollapsed ? <div aria-hidden="true" /> : null}
        <section className={hideMainToolbar ? "workbench-center workbench-center--no-toolbar" : "workbench-center"} aria-label="主任务环境">
          {hideMainToolbar ? null : (
            <MainToolbar
              leftPanelCollapsed={leftCollapsed}
              onToggleLeftPanel={() => setLeftCollapsed((value) => !value)}
              onToggleRightPanel={() => setRightCollapsed((value) => !value)}
              rightPanelCollapsed={rightCollapsed}
            />
          )}
          <div className="workbench-center-content">
            {children}
          </div>
        </section>
        {rightCollapsed ? null : (
          <ResizeHandle
            label={`调整${rightPanelLabel}宽度`}
            onResize={(delta) => {
              const nextLayout = fitWorkbenchPanelWidths({
                inspectorWidth: effectiveRightWidth + delta,
                leftCollapsed,
                rightCollapsed,
                sidebarWidth: effectiveLeftWidth,
                viewportWidth,
              });
              setInspectorWidth(nextLayout.rightWidth);
            }}
            side="right"
          />
        )}
        {rightCollapsed ? <div aria-hidden="true" /> : null}
        {rightCollapsed ? (
          <CollapsedPanelRail label={rightPanelLabel} onOpen={() => setRightCollapsed(false)} side="right" />
        ) : (
          right
        )}
      </main>
    </WorkbenchShellControlsContext.Provider>
  );
}
