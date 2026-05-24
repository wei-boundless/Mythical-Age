"use client";

import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  Code2,
  File,
  FileCode2,
  Folder,
  FolderOpen,
  Globe2,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  MonitorDot,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { CodeEnvironmentView } from "@/components/workspace/views/CodeEnvironmentView";
import type { CodeEnvironmentTreeNode } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type RightPanel = "monitor" | "coding" | "browser" | "details";

const LEFT_WIDTH_KEY = "agentWorkbench.leftWidth";
const RIGHT_WIDTH_KEY = "agentWorkbench.rightWidth";
function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function compactFileName(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
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

function WorkbenchProjectTreeNode({ node }: { node: CodeEnvironmentTreeNode }) {
  const directory = node.kind === "directory";
  const [expanded, setExpanded] = useState(false);
  const hasChildren = directory && node.children.length > 0;
  return (
    <li>
      <button
        aria-expanded={hasChildren ? expanded : undefined}
        className={directory ? "workbench-project-tree-row workbench-project-tree-row--directory" : "workbench-project-tree-row"}
        onClick={() => {
          if (hasChildren) setExpanded((value) => !value);
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
            <WorkbenchProjectTreeNode key={`${child.kind}:${child.path}`} node={child} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function WorkspaceManagerPanel() {
  const {
    currentSessionId,
    inspectorDirty,
    sessions,
    createNewSession,
    refreshWorkspaceTree,
    removeSession,
    saveInspector,
    selectSession,
    workspaceContext,
    workspaceTree,
    workspaceTreeError,
    workspaceTreeLoading,
  } = useAppStore();
  const visibleSessions = [...sessions].sort((a, b) => b.updated_at - a.updated_at);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? null;
  const projectName = workspaceContext?.project_name || "当前工作区";
  const projectRoot = workspaceContext?.project_root || "未加载项目根";
  const projectTreeNodes = workspaceTree?.tree.children || [];

  return (
    <aside className="workbench-resource-panel" aria-label="工作区管理">
      <header className="workbench-panel-head">
        <div>
          <strong>工作区</strong>
          <span>主会话</span>
        </div>
        <button aria-label="保存当前文件" className="workbench-icon-button" disabled={!inspectorDirty} onClick={() => void saveInspector()} type="button">
          <Save size={15} />
        </button>
      </header>

      <section className="workbench-project-context" aria-label="当前项目上下文">
        <div className="workbench-project-context__summary">
          <div>
            <span>当前项目</span>
            <strong>{projectName}</strong>
            <small title={projectRoot}>{projectRoot}</small>
          </div>
          <button disabled={workspaceTreeLoading} onClick={() => void refreshWorkspaceTree()} type="button">
            <RefreshCw size={14} />
            <span>刷新</span>
          </button>
        </div>
      </section>

      <div className="workbench-left-body">
        <section className="workbench-file-tree" aria-label="项目文件">
          <div className="workbench-file-tree__head">
            <div>
              <strong>项目文件</strong>
              <span>{workspaceTree ? `${workspaceTree.total_entries} 项` : workspaceTreeLoading ? "加载中" : "未加载"}</span>
            </div>
            <FolderOpen size={15} />
          </div>
          <div className="workbench-project-file-list">
            {workspaceTreeError ? <div className="workbench-tree-state workbench-tree-state--error">{workspaceTreeError}</div> : null}
            {workspaceTreeLoading && !workspaceTree ? <div className="workbench-tree-state">正在读取项目目录。</div> : null}
            {!workspaceTreeLoading && !workspaceTreeError && workspaceTree && !projectTreeNodes.length ? (
              <div className="workbench-tree-state">未发现可显示文件。</div>
            ) : null}
            {projectTreeNodes.length ? (
              <ul className="workbench-project-tree">
                {projectTreeNodes.map((node) => (
                  <WorkbenchProjectTreeNode key={`${node.kind}:${node.path}`} node={node} />
                ))}
              </ul>
            ) : null}
            {workspaceTree?.truncated ? <div className="workbench-tree-state">文件较多，已显示前 {workspaceTree.max_entries} 项。</div> : null}
          </div>
        </section>

        <section className="workbench-session-panel" aria-label="对话记录">
          <div className="workbench-session-toolbar">
            <div>
              <strong>对话</strong>
              <span>{currentSession?.title || "未选择"}</span>
            </div>
            <button aria-label="新会话" onClick={() => void createNewSession()} type="button">
              <Plus size={15} />
              <span>新建</span>
            </button>
          </div>
          <div className="workbench-session-list">
            {visibleSessions.length ? visibleSessions.map((session) => (
              <div className={session.id === currentSessionId ? "workbench-session-row workbench-session-row--active" : "workbench-session-row"} key={session.id}>
                <button aria-current={session.id === currentSessionId ? "page" : undefined} onClick={() => void selectSession(session.id)} type="button">
                  <strong>{session.title || "未命名会话"}</strong>
                  <small>{session.message_count} · {formatSessionTime(session.updated_at)}</small>
                </button>
                <button aria-label={`删除 ${session.title}`} onClick={() => void removeSession(session.id)} type="button">
                  <Trash2 size={13} />
                </button>
              </div>
            )) : (
              <div className="workbench-empty-state">
                <MessageSquare size={18} />
                <strong>还没有对话</strong>
                <span>新建后开始</span>
              </div>
            )}
          </div>
        </section>
      </div>
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
    currentSessionId,
    inspectorDirty,
    inspectorPath,
    saveInspector,
    sessionActivity,
  } = useAppStore();
  const title = "会话";
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
  onPanelChange,
}: {
  activePanel: RightPanel;
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
        <button className={activePanel === "coding" ? "is-active" : ""} onClick={() => onPanelChange("coding")} type="button">
          <Code2 size={14} />Coding
        </button>
        <button className={activePanel === "browser" ? "is-active" : ""} onClick={() => onPanelChange("browser")} type="button">
          <Globe2 size={14} />网页
        </button>
        <button className={activePanel === "details" ? "is-active" : ""} onClick={() => onPanelChange("details")} type="button">
          <FileCode2 size={14} />文件
        </button>
      </div>
      <div className="workbench-right-body">
        {activePanel === "monitor" ? <TaskMonitorDock embedded /> : null}
        {activePanel === "coding" ? <CodeEnvironmentView embedded /> : null}
        {activePanel === "browser" ? <BrowserPanel /> : null}
        {activePanel === "details" ? <FileInspectorPanel /> : null}
      </div>
    </aside>
  );
}

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const { inspectorWidth, setInspectorWidth, setSidebarWidth, sidebarWidth } = useAppStore();
  const [rightPanel, setRightPanel] = useState<RightPanel>("monitor");
  const [rightCollapsed, setRightCollapsed] = useState(false);
  usePersistedWorkbenchWidths();

  const effectiveLeftWidth = clamp(sidebarWidth, 220, 420);
  const effectiveRightWidth = rightCollapsed ? 0 : clamp(inspectorWidth, 300, 560);

  return (
    <main
      className="agent-workbench agent-workbench--chat-only"
      style={{
        gridTemplateColumns: `${effectiveLeftWidth}px 8px minmax(0, 1fr) ${rightCollapsed ? "0px 0px" : `8px ${effectiveRightWidth}px`}`,
      }}
    >
      <WorkspaceManagerPanel />
      <ResizeHandle label="调整左栏宽度" onResize={(delta) => setSidebarWidth(clamp(sidebarWidth + delta, 220, 420))} side="left" />
      <section className="workbench-center" aria-label="主工作区">
        <MainToolbar onToggleRightPanel={() => setRightCollapsed((value) => !value)} rightPanelCollapsed={rightCollapsed} />
        <div className="workbench-center-content">
          {children}
        </div>
      </section>
      {rightCollapsed ? null : (
        <ResizeHandle label="调整右栏宽度" onResize={(delta) => setInspectorWidth(clamp(inspectorWidth + delta, 300, 560))} side="right" />
      )}
      {rightCollapsed ? null : (
        <RightToolPanel
          activePanel={rightPanel}
          onPanelChange={setRightPanel}
        />
      )}
    </main>
  );
}
