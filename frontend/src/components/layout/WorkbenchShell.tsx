"use client";

import {
  BookOpen,
  CircleDot,
  Compass,
  FileCode2,
  Folder,
  Globe2,
  LayoutGrid,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  MonitorDot,
  Plus,
  Save,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { RuntimeMonitorDetailView } from "@/components/layout/RuntimeMonitorDetailView";
import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

type LeftPanel = "project" | "files" | "sessions";
type RightPanel = "monitor" | "browser" | "details";

const LEFT_WIDTH_KEY = "agentWorkbench.leftWidth";
const RIGHT_WIDTH_KEY = "agentWorkbench.rightWidth";
const TONE_KEY = "workspaceTone";

const workspaceTones = ["default", "water", "leaf", "gold", "ember", "lumen"] as const;
type WorkspaceTone = (typeof workspaceTones)[number];

const navItems: Array<{ view: WorkspaceView; label: string; icon: typeof MessageSquare }> = [
  { view: "chat", label: "会话", icon: MessageSquare },
  { view: "task-system", label: "图任务", icon: Workflow },
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

function workspaceResourceConfig(view: WorkspaceView) {
  if (view === "task-system") {
    return {
      title: "图任务资源",
      summary: "任务图、断点重续、运行监控相关文件。",
      focusGroups: ["项目记忆", "项目文件"],
      actions: [
        { label: "任务图配置", detail: "图结构、节点协议、运行包" },
        { label: "断点重续", detail: "checkpoint、人工介入、恢复状态" },
        { label: "运行监控", detail: "任务进度、状态、事件流" },
      ],
    };
  }
  if (view === "capability-system") {
    return {
      title: "能力资源",
      summary: "Skills、MCP、权限端点与工具治理。",
      focusGroups: ["Skills", "MCP", "能力系统"],
      actions: [
        { label: "Skills", detail: "技能说明、触发条件、执行约束" },
        { label: "MCP", detail: "本地与外部端点统一管理" },
        { label: "权限", detail: "工具权限、文件边界、审批策略" },
      ],
    };
  }
  if (view === "playground") {
    return {
      title: "投影资源",
      summary: "灵魂系统只作为管家投影与辅助呈现资源。",
      focusGroups: ["投影资产"],
      actions: [
        { label: "当前投影", detail: "激活角色、视觉资产、行为边界" },
        { label: "投影素材", detail: "头像、姿态、状态呈现" },
        { label: "交互策略", detail: "何时出现、如何提示、如何退场" },
      ],
    };
  }
  return {
    title: "会话资源",
    summary: "当前会话、项目记忆与可编辑上下文。",
    focusGroups: ["项目记忆", "项目文件"],
    actions: [
      { label: "当前会话", detail: "对话、任务入口、人工介入" },
      { label: "项目记忆", detail: "长期上下文与可维护知识" },
      { label: "文件编辑", detail: "打开右侧编辑器处理配置" },
    ],
  };
}

function compactFileName(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function isNavActive(current: WorkspaceView, target: WorkspaceView) {
  if (target === "task-system") return current === "task-system";
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

function ResourcePanel({ activePanel, onPanelChange }: { activePanel: LeftPanel; onPanelChange: (panel: LeftPanel) => void }) {
  const {
    activeWorkspaceView,
    currentSessionId,
    editableFiles,
    inspectorDirty,
    inspectorPath,
    sessions,
    createNewSession,
    loadInspectorFile,
    removeSession,
    saveInspector,
    selectSession,
  } = useAppStore();
  const selectedContext = activeWorkspaceView === "task-system"
    ? "图任务层"
    : activeWorkspaceView === "capability-system"
      ? "能力系统"
      : "会话";
  const fileGroups = useMemo(() => groupEditableFiles(editableFiles), [editableFiles]);
  const resourceConfig = workspaceResourceConfig(activeWorkspaceView);
  const focusedFiles = fileGroups
    .filter((group) => resourceConfig.focusGroups.includes(group.title))
    .flatMap((group) => group.files)
    .slice(0, 8);

  return (
    <aside className="workbench-resource-panel" aria-label="项目与文件">
      <header className="workbench-panel-head">
        <div>
          <strong>工作区</strong>
          <span>{selectedContext}</span>
        </div>
        <button aria-label="保存当前文件" className="workbench-icon-button" disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">
          <Save size={15} />
        </button>
      </header>

      <div className="workbench-segmented" aria-label="左栏内容">
        <button className={activePanel === "project" ? "is-active" : ""} onClick={() => onPanelChange("project")} type="button">
          <Compass size={14} />项目
        </button>
        <button className={activePanel === "files" ? "is-active" : ""} onClick={() => onPanelChange("files")} type="button">
          <Folder size={14} />文件
        </button>
        <button className={activePanel === "sessions" ? "is-active" : ""} onClick={() => onPanelChange("sessions")} type="button">
          <MessageSquare size={14} />会话
        </button>
      </div>

      {activePanel === "project" ? (
        <div className="workbench-project-stack">
          <section className="workbench-resource-summary">
            <strong>{resourceConfig.title}</strong>
            <span>{resourceConfig.summary}</span>
          </section>
          <section className="workbench-resource-actions" aria-label="当前层资源">
            {resourceConfig.actions.map((item) => (
              <article className="workbench-resource-action" key={item.label}>
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </article>
            ))}
          </section>
          {focusedFiles.length ? (
            <section className="workbench-file-group">
              <header><BookOpen size={14} /><span>快捷文件</span></header>
              {focusedFiles.map((path) => (
                <button
                  className={path === inspectorPath ? "workbench-file-row workbench-file-row--active" : "workbench-file-row"}
                  key={path}
                  onClick={() => void loadInspectorFile(path)}
                  type="button"
                >
                  <FileCode2 size={14} />
                  <span><strong>{compactFileName(path)}</strong><small>{path}</small></span>
                </button>
              ))}
            </section>
          ) : null}
        </div>
      ) : null}

      {activePanel === "files" ? (
        <div className="workbench-file-tree">
          <div className="workbench-search-line">
            <Search size={14} />
            <span>{inspectorPath || "选择文件"}</span>
          </div>
          {fileGroups.map((group) => (
            <section className="workbench-file-group" key={group.title}>
              <header><BookOpen size={14} /><span>{group.title}</span></header>
              {group.files.map((path) => (
                <button
                  className={path === inspectorPath ? "workbench-file-row workbench-file-row--active" : "workbench-file-row"}
                  key={path}
                  onClick={() => void loadInspectorFile(path)}
                  type="button"
                >
                  <FileCode2 size={14} />
                  <span><strong>{compactFileName(path)}</strong><small>{path}</small></span>
                </button>
              ))}
            </section>
          ))}
        </div>
      ) : null}

      {activePanel === "sessions" ? (
        <section className="workbench-session-panel">
          <div className="workbench-section-title">
            <span>会话</span>
            <button aria-label="新会话" className="workbench-icon-button" onClick={() => void createNewSession()} type="button">
              <Plus size={15} />
            </button>
          </div>
          <div className="workbench-session-list">
            {sessions.map((session) => (
              <div className={session.id === currentSessionId ? "workbench-session-row workbench-session-row--active" : "workbench-session-row"} key={session.id}>
                <button onClick={() => void selectSession(session.id)} type="button">
                  <strong>{session.title}</strong>
                  <small>{session.message_count} 条消息</small>
                </button>
                <button aria-label={`删除 ${session.title}`} onClick={() => void removeSession(session.id)} type="button">
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
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
  const [leftPanel, setLeftPanel] = useState<LeftPanel>("project");
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
      <ResourcePanel activePanel={leftPanel} onPanelChange={setLeftPanel} />
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
