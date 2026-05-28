"use client";

import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  File,
  Folder,
  FolderOpen,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import type { CodeEnvironmentTreeNode } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type CenterPanel = "chat" | "file";

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

function WorkspaceManagerPanel({ onOpenFile }: { onOpenFile: (path: string) => void }) {
  const {
    currentSessionId,
    inspectorDirty,
    inspectorPath,
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
  centerPanel,
  onReturnToChat,
  onToggleRightPanel,
  rightPanelCollapsed,
}: {
  centerPanel: CenterPanel;
  onReturnToChat: () => void;
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
  const title = centerPanel === "file" ? "文件" : "会话";
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
        {centerPanel === "file" ? (
          <button onClick={onReturnToChat} type="button">返回会话</button>
        ) : null}
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

function CenterFilePage({ onReturnToChat }: { onReturnToChat: () => void }) {
  const { inspectorContent, inspectorDirty, inspectorPath, saveInspector, updateInspectorContent } = useAppStore();
  const [editing, setEditing] = useState(false);
  return (
    <section className="workbench-file-page" aria-label="文件查看">
      <header>
        <div>
          <strong>{compactFileName(inspectorPath)}</strong>
          <span>{inspectorPath}</span>
        </div>
        <div className="workbench-file-page__actions">
          <button onClick={onReturnToChat} type="button">返回会话</button>
          {editing ? (
            <button disabled={!inspectorDirty} onClick={() => void saveInspector().then(() => setEditing(false))} type="button">保存</button>
          ) : (
            <button onClick={() => setEditing(true)} type="button">编辑</button>
          )}
        </div>
      </header>
      {editing ? (
        <textarea value={inspectorContent} onChange={(event) => updateInspectorContent(event.target.value)} spellCheck={false} />
      ) : (
        <pre>{inspectorContent || "文件为空。"}</pre>
      )}
    </section>
  );
}

function RightToolPanel() {
  return (
    <aside className="workbench-right-panel" aria-label="辅助面板">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>监控</strong>
        </div>
      </header>
      <div className="workbench-right-body">
        <TaskMonitorDock embedded />
      </div>
    </aside>
  );
}

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const { inspectorWidth, loadInspectorFile, setInspectorWidth, setSidebarWidth, sidebarWidth } = useAppStore();
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [centerPanel, setCenterPanel] = useState<CenterPanel>("chat");
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
      <WorkspaceManagerPanel
        onOpenFile={(path) => {
          void loadInspectorFile(path).then(() => setCenterPanel("file"));
        }}
      />
      <ResizeHandle label="调整左栏宽度" onResize={(delta) => setSidebarWidth(clamp(sidebarWidth + delta, 220, 420))} side="left" />
      <section className="workbench-center" aria-label="主工作区">
        <MainToolbar
          centerPanel={centerPanel}
          onReturnToChat={() => setCenterPanel("chat")}
          onToggleRightPanel={() => setRightCollapsed((value) => !value)}
          rightPanelCollapsed={rightCollapsed}
        />
        <div className="workbench-center-content">
          {centerPanel === "file" ? <CenterFilePage onReturnToChat={() => setCenterPanel("chat")} /> : children}
        </div>
      </section>
      {rightCollapsed ? null : (
        <ResizeHandle label="调整右栏宽度" onResize={(delta) => setInspectorWidth(clamp(inspectorWidth + delta, 300, 560))} side="right" />
      )}
      {rightCollapsed ? null : (
        <RightToolPanel />
      )}
    </main>
  );
}
