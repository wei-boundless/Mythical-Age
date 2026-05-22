"use client";

import {
  CircleDot,
  FileCode2,
  Folder,
  Globe2,
  LayoutGrid,
  MessageSquare,
  Network,
  PanelRightClose,
  PanelRightOpen,
  MonitorDot,
  PencilLine,
  Plus,
  Save,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { RuntimeMonitorDetailView } from "@/components/layout/RuntimeMonitorDetailView";
import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

type LeftPanel = "sessions" | "files";
type RightPanel = "monitor" | "browser" | "details";

const LEFT_WIDTH_KEY = "agentWorkbench.leftWidth";
const RIGHT_WIDTH_KEY = "agentWorkbench.rightWidth";
const TONE_KEY = "workspaceTone";

const workspaceTones = ["default", "water", "leaf", "gold", "ember", "lumen"] as const;
type WorkspaceTone = (typeof workspaceTones)[number];

const navItems: Array<{ view: WorkspaceView; label: string; icon: typeof MessageSquare }> = [
  { view: "chat", label: "会话", icon: MessageSquare },
  { view: "task-system", label: "图任务", icon: Workflow },
  { view: "orchestration", label: "编排", icon: Network },
  { view: "capability-system", label: "能力", icon: LayoutGrid },
  { view: "playground", label: "投影", icon: Sparkles },
];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function fileGroupTitle(path: string) {
  if (path.startsWith("soul/")) return "投影资产";
  if (path.startsWith("durable_memory/")) return "项目记忆";
  if (path.toLowerCase().includes("skill")) return "Skills";
  if (path.toLowerCase().includes("mcp")) return "MCP";
  if (path.startsWith("capability_system/")) return "能力系统";
  return "项目文件";
}

function groupEditableFiles(paths: string[]) {
  const groups = new Map<string, string[]>();
  for (const path of paths) {
    const title = fileGroupTitle(path);
    const group = groups.get(title) ?? [];
    group.push(path);
    groups.set(title, group);
  }
  return Array.from(groups.entries()).map(([title, files]) => ({
    title,
    files: files.slice().sort((a, b) => a.localeCompare(b)),
  }));
}

function normalizeSearch(value: string) {
  return value.trim().toLocaleLowerCase();
}

function compactFileName(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function compactDirectory(path: string) {
  const parts = path.split("/");
  if (parts.length <= 1) return "根目录";
  return parts.slice(0, -1).join("/");
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

function workspaceViewLabel(view: WorkspaceView) {
  if (view === "task-system") return "图任务";
  if (view === "orchestration") return "编排";
  if (view === "capability-system") return "能力";
  if (view === "playground") return "投影";
  if (view === "system-framework") return "系统";
  return "会话";
}

function isNavActive(current: WorkspaceView, target: WorkspaceView) {
  if (target === "task-system") return current === "task-system";
  if (target === "orchestration") return current === "orchestration";
  if (target === "capability-system") return current === "capability-system";
  return current === target;
}

function normalizeWorkspaceTone(value: string | null): WorkspaceTone {
  return workspaceTones.includes(value as WorkspaceTone) ? (value as WorkspaceTone) : "default";
}

function applyWorkspaceTone(tone: WorkspaceTone) {
  if (tone === "default") {
    delete document.documentElement.dataset.workspaceTone;
  } else {
    document.documentElement.dataset.workspaceTone = tone;
  }
  window.localStorage.setItem(TONE_KEY, tone);
}

function usePersistedWorkbenchWidths() {
  const { sidebarWidth, inspectorWidth, setSidebarWidth, setInspectorWidth } = useAppStore();

  useEffect(() => {
    const left = Number(window.localStorage.getItem(LEFT_WIDTH_KEY));
    const right = Number(window.localStorage.getItem(RIGHT_WIDTH_KEY));
    if (Number.isFinite(left) && left > 0) setSidebarWidth(clamp(left, 220, 420));
    if (Number.isFinite(right) && right > 0) setInspectorWidth(clamp(right, 300, 560));
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

function WorkbenchRail() {
  const { activeWorkspaceView, setWorkspaceView } = useAppStore();
  const [workspaceTone, setWorkspaceTone] = useState<WorkspaceTone>("default");

  useEffect(() => {
    const storedTone = normalizeWorkspaceTone(window.localStorage.getItem(TONE_KEY));
    setWorkspaceTone(storedTone);
    applyWorkspaceTone(storedTone);
  }, []);

  function updateWorkspaceTone(tone: WorkspaceTone) {
    setWorkspaceTone(tone);
    applyWorkspaceTone(tone);
  }

  return (
    <aside className="workbench-rail" aria-label="主层级">
      <div className="workbench-rail__mark">演</div>
      <nav className="workbench-rail__nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = isNavActive(activeWorkspaceView, item.view);
          return (
            <button
              aria-label={item.label}
              aria-pressed={active}
              className={active ? "workbench-rail__button workbench-rail__button--active" : "workbench-rail__button"}
              key={item.view}
              onClick={() => setWorkspaceView(item.view)}
              title={item.label}
              type="button"
            >
              <Icon size={17} />
            </button>
          );
        })}
      </nav>
      <div className="workbench-rail__footer">
        <div className="workbench-tone-switch" aria-label="工作区色调">
          {workspaceTones.map((tone, index) => (
            <button
              aria-label={tone === "default" ? "使用默认色调" : `切换工作区色调 ${index}`}
              aria-pressed={workspaceTone === tone}
              className={workspaceTone === tone ? "workbench-tone-switch__item workbench-tone-switch__item--active" : "workbench-tone-switch__item"}
              data-tone={tone}
              key={tone}
              onClick={() => updateWorkspaceTone(tone)}
              title={tone === "default" ? "默认" : `色调 ${index}`}
              type="button"
            />
          ))}
        </div>
        <button aria-label="设置" className="workbench-rail__button" title="设置" type="button">
          <Settings2 size={16} />
        </button>
      </div>
    </aside>
  );
}

function WorkspaceManagerPanel({ activePanel, onPanelChange }: { activePanel: LeftPanel; onPanelChange: (panel: LeftPanel) => void }) {
  const [fileQuery, setFileQuery] = useState("");
  const [sessionQuery, setSessionQuery] = useState("");
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const {
    activeWorkspaceView,
    currentSessionId,
    editableFiles,
    globalRuntimeMonitorStreamStatus,
    inspectorDirty,
    inspectorPath,
    sessions,
    createNewSession,
    loadInspectorFile,
    renameCurrentSession,
    removeSession,
    saveInspector,
    selectSession,
    workspaceContext,
  } = useAppStore();
  const fileGroups = useMemo(() => groupEditableFiles(editableFiles), [editableFiles]);
  const visibleFileGroups = useMemo(() => {
    const query = normalizeSearch(fileQuery);
    if (!query) return fileGroups;
    return fileGroups
      .map((group) => ({
        ...group,
        files: group.files.filter((path) => {
          const haystack = normalizeSearch(`${group.title} ${path} ${compactFileName(path)} ${compactDirectory(path)}`);
          return haystack.includes(query);
        }),
      }))
      .filter((group) => group.files.length > 0);
  }, [fileGroups, fileQuery]);
  const visibleFileCount = visibleFileGroups.reduce((count, group) => count + group.files.length, 0);
  const visibleSessions = useMemo(() => {
    const query = normalizeSearch(sessionQuery);
    const sorted = [...sessions].sort((a, b) => b.updated_at - a.updated_at);
    if (!query) return sorted;
    return sorted.filter((session) => normalizeSearch(`${session.title} ${session.id}`).includes(query));
  }, [sessionQuery, sessions]);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? null;
  const streamLabel = globalRuntimeMonitorStreamStatus === "connected"
    ? "事件流"
    : globalRuntimeMonitorStreamStatus === "connecting"
      ? "连接中"
      : globalRuntimeMonitorStreamStatus === "fallback"
        ? "快照兜底"
        : "未连接";
  const canRenameSession = Boolean(
    currentSession && sessionTitleDraft.trim() && sessionTitleDraft.trim() !== currentSession.title
  );
  const projectName = workspaceContext?.project_name || "当前工作区";
  const projectRoot = workspaceContext?.project_root || "未加载项目根";

  useEffect(() => {
    setSessionTitleDraft(currentSession?.title ?? "");
  }, [currentSession?.id, currentSession?.title]);

  function handleRenameSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canRenameSession) return;
    void renameCurrentSession(sessionTitleDraft.trim());
  }

  return (
    <aside className="workbench-resource-panel" aria-label="工作区管理">
      <header className="workbench-panel-head">
        <div>
          <strong>工作区</strong>
          <span>{workspaceViewLabel(activeWorkspaceView)}</span>
        </div>
        <button aria-label="保存当前文件" className="workbench-icon-button" disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">
          <Save size={15} />
        </button>
      </header>

      <section className="workbench-project-context" aria-label="当前项目上下文">
        <div>
          <span>当前项目</span>
          <strong>{projectName}</strong>
          <small title={projectRoot}>{projectRoot}</small>
        </div>
        <dl>
          <div>
            <dt>当前层</dt>
            <dd>{workspaceViewLabel(activeWorkspaceView)}</dd>
          </div>
          <div>
            <dt>会话</dt>
            <dd>{currentSession?.title || "未选择"}</dd>
          </div>
          <div>
            <dt>文件</dt>
            <dd>{inspectorPath ? compactFileName(inspectorPath) : "未打开"}</dd>
          </div>
          <div>
            <dt>监控</dt>
            <dd>{streamLabel}</dd>
          </div>
        </dl>
      </section>

      <div className="workbench-segmented" aria-label="项目对象">
        <button className={activePanel === "sessions" ? "is-active" : ""} onClick={() => onPanelChange("sessions")} type="button">
          <MessageSquare size={14} />会话
        </button>
        <button className={activePanel === "files" ? "is-active" : ""} onClick={() => onPanelChange("files")} type="button">
          <Folder size={14} />文件
        </button>
      </div>

      {activePanel === "files" ? (
        <div className="workbench-file-tree">
          <div className="workbench-manager-toolbar">
            <div>
              <strong>文件管理</strong>
              <span>{visibleFileCount} / {editableFiles.length}</span>
            </div>
            <button aria-label="保存当前文件" disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">
              <Save size={14} />
              <span>{inspectorDirty ? "保存" : "已同步"}</span>
            </button>
          </div>
          <label className="workbench-search-box">
            <Search size={14} />
            <input
              aria-label="搜索文件"
              onChange={(event) => setFileQuery(event.target.value)}
              placeholder="搜索文件"
              value={fileQuery}
            />
          </label>
          <section className={inspectorDirty ? "workbench-current-file workbench-current-file--dirty" : "workbench-current-file"}>
            <div>
              <span>当前文件</span>
              <strong>{inspectorPath ? compactFileName(inspectorPath) : "未打开"}</strong>
              <small title={inspectorPath}>{inspectorPath || "无"}</small>
            </div>
            <em>{inspectorDirty ? "未保存" : "已同步"}</em>
          </section>
          {visibleFileGroups.length ? (
            visibleFileGroups.map((group) => (
              <section className="workbench-file-group" key={group.title}>
                <header><span>{group.title}</span><small>{group.files.length}</small></header>
                {group.files.map((path) => (
                  <button
                    className={path === inspectorPath ? "workbench-file-row workbench-file-row--active" : "workbench-file-row"}
                    key={path}
                    onClick={() => void loadInspectorFile(path)}
                    type="button"
                  >
                    <FileCode2 size={14} />
                    <span><strong>{compactFileName(path)}</strong><small title={path}>{compactDirectory(path)}</small></span>
                  </button>
                ))}
              </section>
            ))
          ) : (
            <div className="workbench-empty-state">
              <Folder size={18} />
              <strong>{editableFiles.length ? "没有匹配文件" : "没有可编辑文件"}</strong>
              <span>{fileQuery || "文件入口为空"}</span>
            </div>
          )}
        </div>
      ) : null}

      {activePanel === "sessions" ? (
        <section className="workbench-session-panel">
          <div className="workbench-manager-toolbar">
            <div>
              <strong>会话管理</strong>
              <span>{visibleSessions.length} / {sessions.length}</span>
            </div>
            <button aria-label="新会话" onClick={() => void createNewSession()} type="button">
              <Plus size={15} />
              <span>新建</span>
            </button>
          </div>
          <form className="workbench-session-active" onSubmit={handleRenameSession}>
            <span>当前会话</span>
            <div className="workbench-session-title-editor">
              <PencilLine size={14} />
              <input
                aria-label="当前会话名称"
                disabled={!currentSession}
                onChange={(event) => setSessionTitleDraft(event.target.value)}
                value={sessionTitleDraft}
              />
              <button disabled={!canRenameSession} type="submit">保存</button>
            </div>
            <small>{currentSession ? `${currentSession.message_count} 条消息 · ${formatSessionTime(currentSession.updated_at)}` : "未选择"}</small>
          </form>
          <label className="workbench-search-box">
            <Search size={14} />
            <input
              aria-label="搜索会话"
              onChange={(event) => setSessionQuery(event.target.value)}
              placeholder="搜索会话"
              value={sessionQuery}
            />
          </label>
          <div className="workbench-session-list">
            {visibleSessions.length ? visibleSessions.map((session) => (
              <div className={session.id === currentSessionId ? "workbench-session-row workbench-session-row--active" : "workbench-session-row"} key={session.id}>
                <button aria-current={session.id === currentSessionId ? "page" : undefined} onClick={() => void selectSession(session.id)} type="button">
                  <strong>{session.title || "未命名会话"}</strong>
                  <small>{session.message_count} 条消息 · {formatSessionTime(session.updated_at)}</small>
                </button>
                <button aria-label={`删除 ${session.title}`} onClick={() => void removeSession(session.id)} type="button">
                  <Trash2 size={13} />
                </button>
              </div>
            )) : (
              <div className="workbench-empty-state">
                <MessageSquare size={18} />
                <strong>{sessions.length ? "没有匹配会话" : "还没有会话"}</strong>
                <span>{sessionQuery || "会话列表为空"}</span>
              </div>
            )}
          </div>
        </section>
      ) : null}
    </aside>
  );
}

function MainToolbar({
  onToggleRightPanel,
  rightPanelCollapsed,
}: {
  onToggleRightPanel: () => void;
  rightPanelCollapsed: boolean;
}) {
  const {
    activeStreamSessionIds,
    activeWorkspaceView,
    currentSessionId,
    inspectorDirty,
    inspectorPath,
    saveInspector,
    sessionActivity,
  } = useAppStore();
  const title = activeWorkspaceView === "task-system"
    ? "图任务层"
    : activeWorkspaceView === "orchestration"
      ? "编排系统"
    : activeWorkspaceView === "capability-system"
      ? "能力系统"
      : activeWorkspaceView === "playground"
        ? "投影"
      : "会话";
  const streaming = Boolean(currentSessionId && activeStreamSessionIds.includes(currentSessionId));
  const activityLabel = streaming
    ? sessionActivity.title || sessionActivity.detail || sessionActivity.event || "执行中"
    : inspectorDirty
      ? "有未保存文件"
      : "待命";

  return (
    <header className="workbench-main-toolbar">
      <div className="workbench-breadcrumb">
        <span>{title}</span>
        <strong>{inspectorDirty ? `${compactFileName(inspectorPath)} 已修改` : compactFileName(inspectorPath || "workspace")}</strong>
      </div>
      <div className={streaming ? "workbench-runtime-state workbench-runtime-state--active" : "workbench-runtime-state"}>
        <CircleDot size={13} />
        <span>{activityLabel}</span>
      </div>
      <div className="workbench-toolbar-actions">
        <button
          aria-label={rightPanelCollapsed ? "打开辅助栏" : "收起辅助栏"}
          className="workbench-toolbar-icon-button"
          onClick={onToggleRightPanel}
          title={rightPanelCollapsed ? "打开辅助栏" : "收起辅助栏"}
          type="button"
        >
          {rightPanelCollapsed ? <PanelRightOpen size={15} /> : <PanelRightClose size={15} />}
        </button>
        <button disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">保存</button>
      </div>
    </header>
  );
}

function BrowserPanel() {
  const [draft, setDraft] = useState("http://localhost:3000/");
  const [url, setUrl] = useState("http://localhost:3000/");
  const normalizedUrl = useMemo(() => {
    const value = draft.trim();
    if (!value) return "";
    if (/^https?:\/\//i.test(value)) return value;
    return `https://${value}`;
  }, [draft]);

  return (
    <section className="workbench-browser-panel" aria-label="网页预览">
      <form
        className="workbench-browser-bar"
        onSubmit={(event) => {
          event.preventDefault();
          if (normalizedUrl) setUrl(normalizedUrl);
        }}
      >
        <Globe2 size={15} />
        <input onChange={(event) => setDraft(event.target.value)} value={draft} />
        <button type="submit">打开</button>
      </form>
      <iframe className="workbench-browser-frame" src={url} title="网页预览" />
    </section>
  );
}

function FileInspectorPanel() {
  const { inspectorContent, inspectorDirty, inspectorPath, saveInspector, updateInspectorContent } = useAppStore();
  return (
    <section className="workbench-file-inspector" aria-label="文件编辑器">
      <header>
        <div>
          <strong>{compactFileName(inspectorPath)}</strong>
          <span>{inspectorPath}</span>
        </div>
        <button disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">保存</button>
      </header>
      <textarea value={inspectorContent} onChange={(event) => updateInspectorContent(event.target.value)} spellCheck={false} />
    </section>
  );
}

function RightToolPanel({
  activePanel,
  onOpenMonitorDetail,
  onPanelChange,
}: {
  activePanel: RightPanel;
  onOpenMonitorDetail: () => void;
  onPanelChange: (panel: RightPanel) => void;
}) {
  return (
    <aside className="workbench-right-panel" aria-label="辅助面板">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>辅助</strong>
          <span>监控 / 网页 / 文件</span>
        </div>
      </header>
      <div className="workbench-right-tabs" aria-label="右栏工具">
        <button className={activePanel === "monitor" ? "is-active" : ""} onClick={() => onPanelChange("monitor")} type="button">
          <MonitorDot size={14} />监控
        </button>
        <button className={activePanel === "browser" ? "is-active" : ""} onClick={() => onPanelChange("browser")} type="button">
          <Globe2 size={14} />网页
        </button>
        <button className={activePanel === "details" ? "is-active" : ""} onClick={() => onPanelChange("details")} type="button">
          <FileCode2 size={14} />文件
        </button>
      </div>
      <div className="workbench-right-body">
        {activePanel === "monitor" ? <TaskMonitorDock embedded onOpenTaskDetail={onOpenMonitorDetail} /> : null}
        {activePanel === "browser" ? <BrowserPanel /> : null}
        {activePanel === "details" ? <FileInspectorPanel /> : null}
      </div>
    </aside>
  );
}

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const { activeWorkspaceView, inspectorWidth, setInspectorWidth, setSidebarWidth, sidebarWidth } = useAppStore();
  const [leftPanel, setLeftPanel] = useState<LeftPanel>("sessions");
  const [rightPanel, setRightPanel] = useState<RightPanel>("monitor");
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [centerMode, setCenterMode] = useState<"workspace" | "monitor-detail">("workspace");
  usePersistedWorkbenchWidths();

  useEffect(() => {
    setCenterMode("workspace");
  }, [activeWorkspaceView]);

  const effectiveLeftWidth = clamp(sidebarWidth, 220, 420);
  const effectiveRightWidth = rightCollapsed ? 0 : clamp(inspectorWidth, 300, 560);

  return (
    <main
      className="agent-workbench"
      style={{
        gridTemplateColumns: `48px ${effectiveLeftWidth}px 8px minmax(0, 1fr) ${rightCollapsed ? "0px 0px" : `8px ${effectiveRightWidth}px`}`,
      }}
    >
      <WorkbenchRail />
      <WorkspaceManagerPanel activePanel={leftPanel} onPanelChange={setLeftPanel} />
      <ResizeHandle label="调整左栏宽度" onResize={(delta) => setSidebarWidth(clamp(sidebarWidth + delta, 220, 420))} side="left" />
      <section className="workbench-center" aria-label="主工作区">
        <MainToolbar onToggleRightPanel={() => setRightCollapsed((value) => !value)} rightPanelCollapsed={rightCollapsed} />
        <div className="workbench-center-content">
          {centerMode === "monitor-detail" ? (
            <RuntimeMonitorDetailView onClose={() => setCenterMode("workspace")} />
          ) : children}
        </div>
      </section>
      {rightCollapsed ? null : (
        <ResizeHandle label="调整右栏宽度" onResize={(delta) => setInspectorWidth(clamp(inspectorWidth + delta, 300, 560))} side="right" />
      )}
      {rightCollapsed ? null : (
        <RightToolPanel
          activePanel={rightPanel}
          onOpenMonitorDetail={() => setCenterMode("monitor-detail")}
          onPanelChange={setRightPanel}
        />
      )}
    </main>
  );
}
