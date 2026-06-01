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
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import type { CodeEnvironmentTreeNode } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type CenterPanel = "chat" | "file";

const LEFT_WIDTH_KEY = "agentWorkbench.leftWidth";
const RIGHT_WIDTH_KEY = "agentWorkbench.rightWidth";
const LEFT_COLLAPSED_KEY = "agentWorkbench.leftCollapsed";
const RIGHT_COLLAPSED_KEY = "agentWorkbench.rightCollapsed";
const PANEL_RAIL_WIDTH = 44;
const RESIZE_HANDLE_WIDTH = 8;
const WORKBENCH_CENTER_MIN_WIDTH = 520;
const WORKBENCH_CENTER_COMPACT_MIN_WIDTH = 340;
const WORKBENCH_EDGE_GUTTER = 10;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function clampLeftWidth(value: number) {
  return clamp(value, 180, 780);
}

function clampRightWidth(value: number) {
  return clamp(value, 240, 820);
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
  const rightMin = rightCollapsed ? PANEL_RAIL_WIDTH : 240;
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

function compactFileName(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function isEditableWorkspacePath(path: string, editablePrefixes: string[] = []) {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  return editablePrefixes.some((prefix) => normalized.startsWith(prefix));
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

function WorkspaceManagerPanel({ onOpenFile }: { onOpenFile: (path: string) => void }) {
  const {
    currentSessionId,
    inspectorPath,
    sessions,
    createNewSession,
    refreshWorkspaceTree,
    removeSession,
    selectSession,
    workspaceContext,
    workspaceTree,
    workspaceTreeError,
    workspaceTreeLoading,
  } = useAppStore();
  const visibleSessions = [...sessions].sort((a, b) => b.updated_at - a.updated_at);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? null;
  const projectName = workspaceContext?.project_name || "当前项目";
  const projectRoot = workspaceContext?.project_root || "未加载项目根";
  const projectTreeNodes = workspaceTree?.tree.children || [];

  return (
    <aside className="workbench-resource-panel" aria-label="任务环境管理">
      <header className="workbench-panel-head">
        <div>
          <strong>任务环境</strong>
          <span>环境集合</span>
        </div>
        <WorkspaceModeSwitcher />
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
  leftPanelCollapsed,
  onReturnToChat,
  onToggleLeftPanel,
  onToggleRightPanel,
  rightPanelCollapsed,
}: {
  centerPanel: CenterPanel;
  leftPanelCollapsed: boolean;
  onReturnToChat: () => void;
  onToggleLeftPanel: () => void;
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
    workspaceContext,
  } = useAppStore();
  const editable = isEditableWorkspacePath(inspectorPath, workspaceContext?.editable_prefixes);
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
        <button
          aria-label={leftPanelCollapsed ? "打开左侧任务环境" : "收起左侧任务环境"}
          className="workbench-toolbar-icon-button"
          onClick={onToggleLeftPanel}
          title={leftPanelCollapsed ? "打开左侧任务环境" : "收起左侧任务环境"}
          type="button"
        >
          {leftPanelCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
        </button>
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

function CenterFilePage({ onReturnToChat }: { onReturnToChat: () => void }) {
  const { inspectorContent, inspectorDirty, inspectorPath, saveInspector, updateInspectorContent, workspaceContext } = useAppStore();
  const [editing, setEditing] = useState(false);
  const editable = isEditableWorkspacePath(inspectorPath, workspaceContext?.editable_prefixes);

  useEffect(() => {
    if (!editable && editing) {
      setEditing(false);
    }
  }, [editable, editing]);

  return (
    <section className="workbench-file-page" aria-label="文件查看">
      <header>
        <div>
          <strong>{compactFileName(inspectorPath)}</strong>
          <span>{inspectorPath}</span>
        </div>
        <div className="workbench-file-page__actions">
          <button onClick={onReturnToChat} type="button">返回会话</button>
          {!editable ? (
            <span className="workbench-file-page__badge">只读</span>
          ) : editing ? (
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
  const { inspectorWidth, loadInspectorFile, setInspectorWidth, setSidebarWidth, sidebarWidth } = useAppStore();
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [centerPanel, setCenterPanel] = useState<CenterPanel>("chat");
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
      onOpenFile={(path) => {
        void loadInspectorFile(path).then(() => setCenterPanel("file"));
      }}
    />
  );
  const right = rightPanel ?? <RightToolPanel />;

  return (
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
            centerPanel={centerPanel}
            leftPanelCollapsed={leftCollapsed}
            onReturnToChat={() => setCenterPanel("chat")}
            onToggleLeftPanel={() => setLeftCollapsed((value) => !value)}
            onToggleRightPanel={() => setRightCollapsed((value) => !value)}
            rightPanelCollapsed={rightCollapsed}
          />
        )}
        <div className="workbench-center-content">
          {centerPanel === "file" ? <CenterFilePage onReturnToChat={() => setCenterPanel("chat")} /> : children}
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
  );
}
